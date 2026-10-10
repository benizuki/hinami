from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.schemas import OrgUnitRecord
from backend.app.storage.sqlite_store import HinamiSQLiteStore

ALPHA_SALES = OrgUnitRecord(id="alphasales", name="営業部", kind="部門")
BETA_BACK = OrgUnitRecord(id="betaback01", name="管理部", kind="部門")


class TenantUserManagementTest(unittest.TestCase):
    """テナント管理者が決められるのは、自テナントへの所属とそこでのロールだけ。"""

    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        auth_dir = root / "auth"
        auth_dir.mkdir(parents=True, exist_ok=True)
        (auth_dir / "tenant_master.json").write_text(
            json.dumps([
                {"id": "alpha", "name": "アルファ", "enabled": True},
                {"id": "beta", "name": "ベータ", "enabled": True},
            ], ensure_ascii=False),
            encoding="utf-8",
        )
        (auth_dir / "user_master.json").write_text(
            json.dumps([
                {
                    "email": "sysadmin@example.com",
                    "name": "管理者",
                    "role": "admin",
                    "enabled": True,
                    "tenant_memberships": [],
                },
                {
                    "email": "alpha-admin@example.com",
                    "name": "アルファ管理者",
                    "role": "none",
                    "enabled": True,
                    "tenant_memberships": [{"tenant_id": "alpha", "role": "admin"}],
                },
                {
                    # アルファでは一般利用者、ベータでは管理者の兼務者。
                    "email": "shared@example.com",
                    "google_subject": "shared-subject",
                    "name": "兼務",
                    "role": "none",
                    "enabled": True,
                    "tenant_memberships": [
                        {"tenant_id": "alpha", "role": "user", "org_unit_id": ALPHA_SALES.id},
                        {"tenant_id": "beta", "role": "admin", "org_unit_id": BETA_BACK.id},
                    ],
                },
                {
                    "email": "beta-only@example.com",
                    "google_subject": "beta-subject",
                    "name": "ベータ専任",
                    "role": "none",
                    "enabled": True,
                    "tenant_memberships": [
                        {"tenant_id": "beta", "role": "user", "org_unit_id": BETA_BACK.id},
                    ],
                },
            ], ensure_ascii=False),
            encoding="utf-8",
        )
        env = patch.dict(os.environ, {
            "GOOGLE_OAUTH_CLIENT_ID": "test-client-id",
            "APP_AUTH_SECRET": "test-secret",
        })
        env.start()
        self.addCleanup(env.stop)

        import backend.app.core.auth as auth
        import backend.app.main as main
        from backend.app import runtime

        for attribute, value in (
            ("AUTH_DIR", auth_dir),
            ("USER_MASTER_FILE", auth_dir / "user_master.json"),
            ("TENANT_MASTER_FILE", auth_dir / "tenant_master.json"),
        ):
            auth_patcher = patch.object(auth, attribute, value)
            auth_patcher.start()
            self.addCleanup(auth_patcher.stop)
        store = HinamiSQLiteStore(root / "hinami.sqlite")
        store_patcher = patch.object(runtime, "store", store)
        store_patcher.start()
        self.addCleanup(store_patcher.stop)
        store.save_org_unit(ALPHA_SALES, "alpha")
        store.save_org_unit(BETA_BACK, "beta")

        self.auth = auth
        self.tokens = {
            user["email"]: auth.issue_app_token(user) for user in auth.list_user_master_entries()
        }
        self.client = TestClient(main.app, raise_server_exceptions=False)

    def headers(self, email: str, tenant_id: str = "alpha") -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.tokens[email]}",
            "X-Tenant-ID": tenant_id,
            "Host": "127.0.0.1:8000",
        }

    def user(self, email: str) -> dict:
        return next(entry for entry in self.auth.list_user_master_entries() if entry["email"] == email)

    def test_tenant_admin_cannot_take_over_a_shared_user(self) -> None:
        """メールやGoogle連携を書き換えられると、他テナントの管理権限ごと奪える。"""
        response = self.client.put(
            "/api/users/shared@example.com",
            json={
                "email": "attacker@example.com",
                "google_subject": "",
                "name": "書き換え",
                "department": "管理部",
                "role": "admin",
                "enabled": False,
                "tenant_memberships": [
                    {"tenant_id": "alpha", "role": "manager", "org_unit_id": ALPHA_SALES.id},
                    {"tenant_id": "beta", "role": "viewer"},
                ],
            },
            headers=self.headers("alpha-admin@example.com"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["tenant_memberships"], [
            {"tenant_id": "alpha", "role": "manager", "org_unit_id": ALPHA_SALES.id},
        ])
        stored = self.user("shared@example.com")
        self.assertEqual(stored["google_subject"], "shared-subject")
        self.assertEqual(stored["name"], "兼務")
        self.assertIsNone(stored["department"])
        self.assertEqual(stored["role"], "none")
        self.assertTrue(stored["enabled"])
        self.assertIn(
            {"tenant_id": "beta", "role": "admin", "org_unit_id": BETA_BACK.id},
            stored["tenant_memberships"],
        )
        self.assertFalse(any(
            entry["email"] == "attacker@example.com" for entry in self.auth.list_user_master_entries()
        ))

    def test_tenant_admin_creates_a_user_without_account_wide_settings(self) -> None:
        response = self.client.post(
            "/api/users",
            json={
                "email": "New@Example.com",
                "name": "新人",
                "google_subject": "attacker-subject",
                "department": "管理部",
                "role": "admin",
                "enabled": True,
                "tenant_memberships": [
                    {"tenant_id": "alpha", "role": "user", "org_unit_id": ALPHA_SALES.id},
                    {"tenant_id": "beta", "role": "admin"},
                ],
            },
            headers=self.headers("alpha-admin@example.com"),
        )

        self.assertEqual(response.status_code, 200)
        stored = self.user("new@example.com")
        self.assertEqual(stored["name"], "新人")
        self.assertIsNone(stored["google_subject"])
        self.assertIsNone(stored["department"])
        self.assertEqual(stored["role"], "none")
        self.assertEqual(stored["tenant_memberships"], [
            {"tenant_id": "alpha", "role": "user", "org_unit_id": ALPHA_SALES.id},
        ])

    def test_adding_a_registered_user_only_adds_the_membership(self) -> None:
        response = self.client.post(
            "/api/users",
            json={
                "email": "beta-only@example.com",
                "name": "書き換え",
                "google_subject": "attacker-subject",
                "role": "none",
                "enabled": True,
                "tenant_memberships": [{"tenant_id": "alpha", "role": "viewer"}],
            },
            headers=self.headers("alpha-admin@example.com"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([m["tenant_id"] for m in response.json()["tenant_memberships"]], ["alpha"])
        stored = self.user("beta-only@example.com")
        self.assertEqual(stored["name"], "ベータ専任")
        self.assertEqual(stored["google_subject"], "beta-subject")
        self.assertEqual(
            {m["tenant_id"]: m["role"] for m in stored["tenant_memberships"]},
            {"beta": "user", "alpha": "viewer"},
        )

    def test_adding_a_member_twice_is_a_conflict(self) -> None:
        response = self.client.post(
            "/api/users",
            json={
                "email": "shared@example.com",
                "name": "兼務",
                "role": "none",
                "enabled": True,
                "tenant_memberships": [{"tenant_id": "alpha", "role": "admin"}],
            },
            headers=self.headers("alpha-admin@example.com"),
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.user("shared@example.com")["tenant_memberships"][0]["role"], "user")

    def test_system_admin_can_still_change_the_login_email(self) -> None:
        response = self.client.put(
            "/api/users/beta-only@example.com",
            json={
                "email": "renamed@example.com",
                "name": "ベータ専任",
                "role": "none",
                "enabled": True,
                "tenant_memberships": [
                    {"tenant_id": "beta", "role": "user", "org_unit_id": BETA_BACK.id},
                ],
            },
            headers=self.headers("sysadmin@example.com"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.user("renamed@example.com")["google_subject"], "beta-subject")

    def test_omitted_fields_keep_their_current_values(self) -> None:
        """渡さなかった項目でGoogle連携が外れたり、無効の利用者が有効に戻ったりしない。"""
        self.auth.update_user_master_entry("beta-only@example.com", {"enabled": False})
        self.auth.update_user_master_entry("beta-only@example.com", {"name": "改名"})

        stored = self.user("beta-only@example.com")
        self.assertEqual(stored["name"], "改名")
        self.assertEqual(stored["google_subject"], "beta-subject")
        self.assertFalse(stored["enabled"])


if __name__ == "__main__":
    unittest.main()
