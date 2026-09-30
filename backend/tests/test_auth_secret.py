from __future__ import annotations

import os
import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.app.core import auth


class AuthSecretTest(unittest.TestCase):
    """APP_AUTH_SECRET が無ければ生成して保存し、再起動後も同じ鍵を使う。"""

    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.secret_file = Path(directory.name) / "auth" / "app_auth_secret"
        patcher = patch.object(auth, "AUTH_SECRET_FILE", self.secret_file)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _forget_cache(self) -> None:
        # 再起動の代わり。プロセス内のキャッシュを捨てて、ファイルから読み直させる。
        auth._stored_auth_secrets.pop(self.secret_file, None)

    def test_secret_is_generated_and_stored_with_owner_only_permission(self) -> None:
        with patch.dict(os.environ, {"APP_AUTH_SECRET": ""}):
            secret = auth._auth_secret()

        self.assertGreaterEqual(len(secret), 64)
        self.assertEqual(self.secret_file.read_text(encoding="utf-8"), secret)
        self.assertEqual(stat.S_IMODE(self.secret_file.stat().st_mode), 0o600)
        self.assertEqual(list(self.secret_file.parent.glob(".app_auth_secret.*")), [])

    def test_stored_secret_survives_restart(self) -> None:
        with patch.dict(os.environ, {"APP_AUTH_SECRET": ""}):
            first = auth._auth_secret()
            self._forget_cache()
            second = auth._auth_secret()

        self.assertEqual(first, second)

    def test_token_issued_before_restart_is_still_valid(self) -> None:
        user = {"email": "user@example.com", "role": "viewer", "token_version": 0}
        with patch.dict(os.environ, {"APP_AUTH_SECRET": ""}), patch.object(
            auth, "_find_user_by_email", return_value=user
        ):
            token = auth.issue_app_token(user)
            self._forget_cache()
            verified = auth.verify_app_token(token)

        self.assertEqual(verified["email"], "user@example.com")

    def test_environment_variable_takes_priority(self) -> None:
        with patch.dict(os.environ, {"APP_AUTH_SECRET": "from-env"}):
            self.assertEqual(auth._auth_secret(), "from-env")

        self.assertFalse(self.secret_file.exists())

    def test_generated_secret_is_rejected_on_cloud(self) -> None:
        with patch.dict(
            os.environ,
            {"GOOGLE_OAUTH_CLIENT_ID": "client-id", "K_SERVICE": "hinami"},
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "APP_AUTH_SECRET"):
                auth.validate_auth_configuration()

        with patch.dict(
            os.environ,
            {"GOOGLE_OAUTH_CLIENT_ID": "client-id", "K_SERVICE": "hinami", "APP_AUTH_SECRET": "x"},
            clear=True,
        ):
            auth.validate_auth_configuration()


if __name__ == "__main__":
    unittest.main()
