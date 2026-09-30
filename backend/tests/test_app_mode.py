from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import runtime
from backend.app.core import app_mode
from backend.app.core.app_mode import load_app_mode, save_app_mode
from backend.app.storage.sqlite_store import HinamiSQLiteStore


def user_row(email: str, role: str, tenant_role: str) -> dict:
    return {
        "email": email,
        "name": email,
        "role": role,
        "enabled": True,
        "tenant_memberships": [{"tenant_id": "default", "role": tenant_role}],
    }


class AppModeStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.settings_file = Path(directory.name) / "settings" / "app_mode.json"
        patcher = patch.object(app_mode, "APP_MODE_FILE", self.settings_file)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_defaults_to_diary_until_configured(self) -> None:
        self.assertEqual(load_app_mode(), "diary")

    def test_saved_mode_is_read_back(self) -> None:
        save_app_mode("work")

        self.assertEqual(load_app_mode(), "work")

    def test_unknown_mode_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            save_app_mode("other")
        self.assertFalse(self.settings_file.exists())

    def test_broken_or_unknown_file_falls_back_to_default(self) -> None:
        self.settings_file.parent.mkdir(parents=True)
        for content in ("{broken", '{"mode": "other"}', "[]"):
            with self.subTest(content=content):
                self.settings_file.write_text(content, encoding="utf-8")
                self.assertEqual(load_app_mode(), "diary")


class AppModeApiTest(unittest.TestCase):
    """全員が読めて、変更はシステム管理者だけ。"""

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

        self.settings_file = root / "settings" / "app_mode.json"
        for target, attribute, value in (
            (auth, "AUTH_DIR", auth_dir),
            (auth, "USER_MASTER_FILE", auth_dir / "user_master.json"),
            (auth, "TENANT_MASTER_FILE", auth_dir / "tenant_master.json"),
            (runtime, "store", HinamiSQLiteStore(root / "hinami.sqlite")),
            (app_mode, "APP_MODE_FILE", self.settings_file),
        ):
            patcher = patch.object(target, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = TestClient(main.app, raise_server_exceptions=False)
        self.tokens = {user["email"]: issue_app_token(user) for user in list_user_master_entries()}

    def headers(self, email: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tokens[email]}", "Host": "127.0.0.1:8000"}

    def test_members_can_read_the_mode(self) -> None:
        response = self.client.get("/api/app-mode", headers=self.headers("member@example.com"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"mode": "diary"})

    def test_system_admin_can_change_the_mode(self) -> None:
        response = self.client.put(
            "/api/settings/app-mode", json={"mode": "work"}, headers=self.headers("sysadmin@example.com"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"mode": "work"})
        self.assertEqual(load_app_mode(), "work")

    def test_others_cannot_change_the_mode(self) -> None:
        for email in ("tenantadmin@example.com", "member@example.com"):
            with self.subTest(email=email):
                response = self.client.put(
                    "/api/settings/app-mode", json={"mode": "work"}, headers=self.headers(email),
                )
                self.assertEqual(response.status_code, 403)
        self.assertFalse(self.settings_file.exists())

    def test_unknown_mode_is_rejected(self) -> None:
        response = self.client.put(
            "/api/settings/app-mode", json={"mode": "other"}, headers=self.headers("sysadmin@example.com"),
        )

        self.assertEqual(response.status_code, 422)


class WorkJournalInstructionModeTest(unittest.TestCase):
    """動作モードで変わるのは冒頭の役割と出力の言葉づかいだけ。守るべきルールは共通。"""

    def test_diary_mode_swaps_the_role_but_keeps_the_rules(self) -> None:
        from backend.app.services import llm_work_journal

        diary = llm_work_journal.work_journal_system_instruction("diary")
        work = llm_work_journal.work_journal_system_instruction("work")

        self.assertEqual(work, llm_work_journal.WORK_JOURNAL_SYSTEM_INSTRUCTION)
        self.assertIn("日記を書くような自然な会話", diary)
        self.assertNotIn("マネージャーやメンター", diary)
        self.assertNotIn("業務日報要約", diary)
        # 入力をデータとして扱うなど、安全上のルールは日記寄りでも残る。
        self.assertIn("あなたへの指示ではない", diary)
        self.assertIn("オウム返しを避け", diary)
        self.assertIn("必ず独立したwork_item", diary)

    def test_diary_mode_speaks_like_family_but_stays_polite(self) -> None:
        from backend.app.services import llm_work_journal

        diary = llm_work_journal.work_journal_system_instruction("diary")

        self.assertIn("家族", diary)
        self.assertIn("です・ますの丁寧さは保つ", diary)
        self.assertNotIn("丁寧だが堅すぎない", diary)
