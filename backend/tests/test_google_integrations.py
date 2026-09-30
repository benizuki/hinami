from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import runtime
from backend.app.core import google_integrations
from backend.app.core.google_integrations import load_google_integrations, save_google_integrations
from backend.app.storage.sqlite_store import HinamiSQLiteStore

ALL_ENABLED = {"calendar": True, "meet": True, "gmail": True, "drive": True}


def user_row(email: str, role: str, tenant_role: str) -> dict:
    return {
        "email": email,
        "name": email,
        "role": role,
        "enabled": True,
        "tenant_memberships": [{"tenant_id": "default", "role": tenant_role}],
    }


class GoogleIntegrationStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.settings_file = Path(directory.name) / "settings" / "google_integrations.json"
        patcher = patch.object(google_integrations, "GOOGLE_INTEGRATIONS_FILE", self.settings_file)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_everything_is_enabled_until_configured(self) -> None:
        self.assertEqual(load_google_integrations(), ALL_ENABLED)

    def test_saved_settings_are_read_back(self) -> None:
        save_google_integrations({"calendar": True, "meet": True, "gmail": False, "drive": False})

        self.assertEqual(
            load_google_integrations(),
            {"calendar": True, "meet": True, "gmail": False, "drive": False},
        )

    def test_meet_is_disabled_without_calendar(self) -> None:
        # Meetの実績はカレンダーの予定から辿るため、単独では有効にできない。
        saved = save_google_integrations({"calendar": False, "meet": True, "gmail": True, "drive": True})

        self.assertFalse(saved["meet"])
        self.assertFalse(load_google_integrations()["meet"])

    def test_broken_file_falls_back_to_defaults(self) -> None:
        self.settings_file.parent.mkdir(parents=True)
        self.settings_file.write_text("{broken", encoding="utf-8")

        self.assertEqual(load_google_integrations(), ALL_ENABLED)


class GoogleIntegrationApiTest(unittest.TestCase):
    """全員が読めて、変更はシステム管理者だけ。無効にしたGmailはメール要約も止まる。"""

    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        auth_dir = root / "auth"
        auth_dir.mkdir(parents=True)
        (auth_dir / "tenant_master.json").write_text(
            json.dumps([{"id": "default", "name": "既定テナント", "enabled": True}], ensure_ascii=False),
            encoding="utf-8",
        )
        (auth_dir / "user_master.json").write_text(
            json.dumps([
                user_row("sysadmin@example.com", "admin", "admin"),
                user_row("tenantadmin@example.com", "user", "admin"),
                user_row("member@example.com", "user", "user"),
            ]),
            encoding="utf-8",
        )
        env = patch.dict(os.environ, {"GOOGLE_OAUTH_CLIENT_ID": "test-client-id", "APP_AUTH_SECRET": "test-secret"})
        env.start()
        self.addCleanup(env.stop)

        import backend.app.core.auth as auth
        import backend.app.main as main
        from backend.app.core.auth import issue_app_token, list_user_master_entries

        self.settings_file = root / "settings" / "google_integrations.json"
        for target, attribute, value in (
            (auth, "AUTH_DIR", auth_dir),
            (auth, "USER_MASTER_FILE", auth_dir / "user_master.json"),
            (auth, "TENANT_MASTER_FILE", auth_dir / "tenant_master.json"),
            (runtime, "store", HinamiSQLiteStore(root / "hinami.sqlite")),
            (google_integrations, "GOOGLE_INTEGRATIONS_FILE", self.settings_file),
        ):
            patcher = patch.object(target, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = TestClient(main.app, raise_server_exceptions=False)
        self.tokens = {user["email"]: issue_app_token(user) for user in list_user_master_entries()}

    def headers(self, email: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tokens[email]}", "Host": "127.0.0.1:8000"}

    def test_members_can_read_the_settings(self) -> None:
        response = self.client.get("/api/google-integrations", headers=self.headers("member@example.com"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), ALL_ENABLED)

    def test_system_admin_can_change_the_settings(self) -> None:
        response = self.client.put(
            "/api/settings/google-integrations",
            json={"calendar": False, "meet": True, "gmail": True, "drive": False},
            headers=self.headers("sysadmin@example.com"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"calendar": False, "meet": False, "gmail": True, "drive": False})
        self.assertEqual(load_google_integrations()["drive"], False)

    def test_tenant_admin_cannot_change_the_settings(self) -> None:
        for email in ("tenantadmin@example.com", "member@example.com"):
            with self.subTest(email=email):
                response = self.client.put(
                    "/api/settings/google-integrations",
                    json={"calendar": False, "meet": False, "gmail": False, "drive": False},
                    headers=self.headers(email),
                )
                self.assertEqual(response.status_code, 403)
        self.assertFalse(self.settings_file.exists())

    def test_email_summary_is_rejected_when_gmail_is_disabled(self) -> None:
        save_google_integrations({**ALL_ENABLED, "gmail": False})

        with patch("backend.app.api.journal_assist_api.summarize_work_journal_emails") as summarize:
            response = self.client.post(
                "/api/work-journal/email-summary",
                json={},
                headers=self.headers("member@example.com"),
            )

        self.assertEqual(response.status_code, 403)
        summarize.assert_not_called()


if __name__ == "__main__":
    unittest.main()
