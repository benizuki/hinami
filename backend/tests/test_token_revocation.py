from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi import HTTPException

from backend.app.core import auth


class TokenRevocationTest(unittest.TestCase):
    """署名が正しくても、失効済みのトークンは受け付けてはいけない。"""

    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        patcher = patch.dict(os.environ, {
            "GOOGLE_OAUTH_CLIENT_ID": "test-client-id",
            "APP_AUTH_SECRET": "test-secret",
            "HINAMI_AUTH_DIR": str(Path(directory.name) / "auth"),
        })
        patcher.start()
        self.addCleanup(patcher.stop)
        auth_dir = patch.object(auth, "AUTH_DIR", Path(directory.name) / "auth")
        auth_dir.start()
        self.addCleanup(auth_dir.stop)
        for attribute, filename in (
            ("USER_MASTER_FILE", "user_master.json"),
            ("TENANT_MASTER_FILE", "tenant_master.json"),
        ):
            file_patcher = patch.object(
                auth, attribute, Path(directory.name) / "auth" / filename
            )
            file_patcher.start()
            self.addCleanup(file_patcher.stop)
        auth.ensure_user_master()
        self.user = auth.create_user_master_entry(
            email="member@example.com",
            name="Member",
            department=None,
            department_id=None,
            org_unit_id=None,
            # システム全体のロールは持たず、テナント内で一般ユーザーとして所属する。
            role="none",
            enabled=True,
            google_subject="subject-1",
            tenant_memberships=[{"tenant_id": "default", "role": "user"}],
        )

    def test_a_freshly_issued_token_is_accepted(self) -> None:
        token = auth.issue_app_token(self.user)

        verified = auth.verify_app_token(token)

        self.assertEqual(verified["email"], "member@example.com")

    def test_revoking_tokens_rejects_the_previous_token(self) -> None:
        token = auth.issue_app_token(self.user)

        auth.revoke_user_tokens("member@example.com")

        with self.assertRaises(HTTPException) as context:
            auth.verify_app_token(token)
        self.assertEqual(context.exception.status_code, 401)

    def test_a_token_issued_after_revocation_still_works(self) -> None:
        auth.revoke_user_tokens("member@example.com")
        reloaded = auth.list_user_master_entries()[0]

        token = auth.issue_app_token(reloaded)

        self.assertEqual(auth.verify_app_token(token)["email"], "member@example.com")

    def test_changing_the_system_role_revokes_existing_tokens(self) -> None:
        token = auth.issue_app_token(self.user)

        auth.update_user_master_entry("member@example.com", {**self.user, "role": "admin"})

        with self.assertRaises(HTTPException) as context:
            auth.verify_app_token(token)
        self.assertEqual(context.exception.status_code, 401)

    def test_backfilling_the_google_subject_keeps_the_token_valid(self) -> None:
        """ログイン時のsubject補完で失効させると、毎回ログインし直しになる。"""
        token = auth.issue_app_token(self.user)

        auth.update_user_master_entry(
            "member@example.com", {**self.user, "google_subject": "subject-1"}
        )

        self.assertEqual(auth.verify_app_token(token)["email"], "member@example.com")


if __name__ == "__main__":
    unittest.main()
