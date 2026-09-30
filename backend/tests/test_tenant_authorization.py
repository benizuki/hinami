from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi import HTTPException

from backend.app.core import auth


class TenantAuthorizationTest(unittest.TestCase):
    def _paths(self, directory: str) -> dict[str, Path]:
        auth_dir = Path(directory) / "auth"
        return {
            "AUTH_DIR": auth_dir,
            "USER_MASTER_FILE": auth_dir / "user_master.json",
            "TENANT_MASTER_FILE": auth_dir / "tenant_master.json",
        }

    def test_tenant_role_is_scoped_per_tenant(self) -> None:
        with TemporaryDirectory() as directory, patch.multiple(auth, **self._paths(directory)):
            auth.ensure_user_master()
            auth.create_tenant_entry(
                tenant_id="east",
                name="東日本",
                description="",
                enabled=True,
            )
            user = {
                "role": "user",
                "tenant_memberships": [
                    {"tenant_id": "default", "role": "viewer"},
                    {"tenant_id": "east", "role": "admin"},
                ],
            }

            self.assertEqual(auth.ensure_tenant_role(user, "east", "admin"), "admin")
            with self.assertRaises(HTTPException) as context:
                auth.ensure_tenant_role(user, "default", "user")
            self.assertEqual(context.exception.status_code, 403)

    def test_user_without_membership_cannot_access_tenant(self) -> None:
        with TemporaryDirectory() as directory, patch.multiple(auth, **self._paths(directory)):
            auth.ensure_user_master()
            user = {"role": "none", "tenant_memberships": []}

            with self.assertRaises(HTTPException) as context:
                auth.ensure_tenant_role(user, "default", "viewer")

            self.assertEqual(context.exception.status_code, 403)

    def test_system_viewer_can_read_every_tenant(self) -> None:
        with TemporaryDirectory() as directory, patch.multiple(auth, **self._paths(directory)):
            auth.ensure_user_master()
            user = {"role": "viewer", "tenant_memberships": []}

            self.assertEqual(auth.ensure_tenant_role(user, "default", "viewer"), "viewer")
            with self.assertRaises(HTTPException):
                auth.ensure_tenant_role(user, "default", "user")

    def test_system_admin_can_access_every_tenant(self) -> None:
        with TemporaryDirectory() as directory, patch.multiple(auth, **self._paths(directory)):
            auth.ensure_user_master()
            user = {"role": "admin", "tenant_memberships": []}

            self.assertEqual(auth.ensure_tenant_role(user, "default", "admin"), "admin")


if __name__ == "__main__":
    unittest.main()
