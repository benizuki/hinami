from __future__ import annotations

import json
import os
import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.services import gemini
from backend.app.services.gemini import GeminiError

VALID_KEY = "AIzaSyTestKey_0123456789abcdefghij"


def user_row(email: str, role: str, tenant_role: str) -> dict:
    return {
        "email": email,
        "name": email,
        "role": role,
        "enabled": True,
        "tenant_memberships": [{"tenant_id": "default", "role": tenant_role}],
    }


class GeminiSettingsTest(unittest.TestCase):
    """APIキーはシステム管理者だけが画面から登録でき、キーそのものは返さない。"""

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
            ]),
            encoding="utf-8",
        )
        env = patch.dict(os.environ, {
            "GOOGLE_OAUTH_CLIENT_ID": "test-client-id",
            "APP_AUTH_SECRET": "test-secret",
            "GEMINI_API_KEY": "",
        })
        env.start()
        self.addCleanup(env.stop)

        import backend.app.core.auth as auth
        import backend.app.main as main
        from backend.app import runtime
        from backend.app.api import settings_api
        from backend.app.core.auth import issue_app_token, list_user_master_entries
        from backend.app.storage.sqlite_store import HinamiSQLiteStore

        self.key_file = root / "secrets" / "gemini_api_key"
        for target, attribute, value in (
            (auth, "AUTH_DIR", auth_dir),
            (auth, "USER_MASTER_FILE", auth_dir / "user_master.json"),
            (auth, "TENANT_MASTER_FILE", auth_dir / "tenant_master.json"),
            (runtime, "store", HinamiSQLiteStore(root / "hinami.sqlite")),
            (gemini, "GEMINI_API_KEY_FILE", self.key_file),
        ):
            patcher = patch.object(target, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        # 実際のGemini APIには問い合わせない。
        verify = patch.object(settings_api, "verify_gemini_api_key")
        self.verify = verify.start()
        self.addCleanup(verify.stop)
        self.client = TestClient(main.app, raise_server_exceptions=False)
        self.tokens = {user["email"]: issue_app_token(user) for user in list_user_master_entries()}

    def headers(self, email: str = "sysadmin@example.com") -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tokens[email]}", "Host": "127.0.0.1:8000"}

    def test_system_admin_can_store_key_without_it_being_returned(self) -> None:
        response = self.client.put("/api/settings/gemini", json={"api_key": f"  {VALID_KEY}\n"}, headers=self.headers())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"source": "stored", "configured": True, "key_hint": VALID_KEY[-4:]})
        self.assertNotIn(VALID_KEY, response.text)
        self.verify.assert_called_once_with(VALID_KEY)
        self.assertEqual(self.key_file.read_text(encoding="utf-8"), VALID_KEY)
        self.assertEqual(stat.S_IMODE(self.key_file.stat().st_mode), 0o600)
        self.assertEqual(gemini.gemini_api_key(), VALID_KEY)

        body = self.client.get("/api/settings/gemini", headers=self.headers()).json()
        self.assertEqual(body["source"], "stored")
        self.assertNotIn(VALID_KEY, json.dumps(body))

    def test_rejected_key_is_not_stored(self) -> None:
        self.verify.side_effect = GeminiError("このAPIキーは使えませんでした（HTTP 400）。キーを確認してください。")

        response = self.client.put("/api/settings/gemini", json={"api_key": VALID_KEY}, headers=self.headers())

        self.assertEqual(response.status_code, 422)
        self.assertFalse(self.key_file.exists())

    def test_keys_with_dots_are_accepted(self) -> None:
        # 新しい形式のキーは . を含む。形式判定で弾かず、実際の問い合わせに任せる。
        key = "AQ.Ab8RN6Jk_test-KEY.0123456789abcdef"

        response = self.client.put("/api/settings/gemini", json={"api_key": key}, headers=self.headers())

        self.assertEqual(response.status_code, 200)
        self.verify.assert_called_once_with(key)

    def test_malformed_key_is_rejected_before_verification(self) -> None:
        for value in ("short", f"{VALID_KEY}\nX-Injected: 1", f"{VALID_KEY} {VALID_KEY}", "キー" * 20):
            with self.subTest(value=value):
                response = self.client.put("/api/settings/gemini", json={"api_key": value}, headers=self.headers())
                self.assertEqual(response.status_code, 422)
        self.verify.assert_not_called()

    def test_tenant_admin_cannot_read_or_change_the_key(self) -> None:
        headers = self.headers("tenantadmin@example.com")
        self.assertEqual(self.client.get("/api/settings/gemini", headers=headers).status_code, 403)
        self.assertEqual(
            self.client.put("/api/settings/gemini", json={"api_key": VALID_KEY}, headers=headers).status_code,
            403,
        )
        self.assertEqual(self.client.delete("/api/settings/gemini", headers=headers).status_code, 403)
        self.assertFalse(self.key_file.exists())

    def test_environment_variable_takes_priority_and_locks_the_screen(self) -> None:
        with patch.dict(os.environ, {"GEMINI_API_KEY": "from-environment"}):
            body = self.client.get("/api/settings/gemini", headers=self.headers()).json()
            put = self.client.put("/api/settings/gemini", json={"api_key": VALID_KEY}, headers=self.headers())
            delete = self.client.delete("/api/settings/gemini", headers=self.headers())

        self.assertEqual(body, {"source": "environment", "configured": True})
        self.assertEqual(put.status_code, 409)
        self.assertEqual(delete.status_code, 409)

    def test_stored_key_can_be_removed(self) -> None:
        gemini.save_gemini_api_key(VALID_KEY)

        response = self.client.delete("/api/settings/gemini", headers=self.headers())

        self.assertEqual(response.status_code, 204)
        self.assertFalse(self.key_file.exists())
        self.assertEqual(gemini.gemini_api_key_source(), "none")


if __name__ == "__main__":
    unittest.main()
