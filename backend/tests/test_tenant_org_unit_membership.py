from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.schemas import OrgUnitRecord, WorkJournalRecord
from backend.app.storage.sqlite_store import HinamiSQLiteStore

ALPHA_SALES = OrgUnitRecord(id="alphasales", name="営業部", kind="部門")
ALPHA_TEAM = OrgUnitRecord(id="alphateam1", parent_id="alphasales", name="営業1課", kind="課")
ALPHA_ALL = OrgUnitRecord(id="alphaall01", name="全社", kind="全社")
BETA_BACK = OrgUnitRecord(id="betaback01", name="管理部", kind="部門")


class TenantOrgUnitMembershipTest(unittest.TestCase):
    """所属組織はテナントごとに持ち、全社は全部門を束ねる。"""

    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
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
                    "tenant_memberships": [
                        {"tenant_id": "alpha", "role": "admin"},
                        {"tenant_id": "beta", "role": "admin"},
                    ],
                },
                {
                    "email": "both@example.com",
                    "name": "兼務",
                    "role": "none",
                    "enabled": True,
                    "tenant_memberships": [
                        {"tenant_id": "alpha", "role": "user", "org_unit_id": ALPHA_TEAM.id},
                        {"tenant_id": "beta", "role": "user", "org_unit_id": BETA_BACK.id},
                    ],
                },
                {
                    "email": "executive@example.com",
                    "name": "統括",
                    "role": "none",
                    "enabled": True,
                    "tenant_memberships": [
                        {"tenant_id": "alpha", "role": "manager", "org_unit_id": ALPHA_ALL.id},
                    ],
                },
                {
                    # 移行前の行。テナントを持たないorg_unit_idだけを持つ。
                    "email": "legacy@example.com",
                    "name": "旧データ",
                    "role": "none",
                    "org_unit_id": ALPHA_SALES.id,
                    "enabled": True,
                    "tenant_memberships": [{"tenant_id": "alpha", "role": "user"}],
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
        from backend.app.core.auth import issue_app_token, list_user_master_entries

        for attribute, value in (
            ("AUTH_DIR", auth_dir),
            ("USER_MASTER_FILE", auth_dir / "user_master.json"),
            ("TENANT_MASTER_FILE", auth_dir / "tenant_master.json"),
        ):
            auth_patcher = patch.object(auth, attribute, value)
            auth_patcher.start()
            self.addCleanup(auth_patcher.stop)
        store = HinamiSQLiteStore(root / "hinami.sqlite")
        for patcher in (
            patch.object(runtime, "store", store),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        for unit in (ALPHA_SALES, ALPHA_TEAM, ALPHA_ALL):
            store.save_org_unit(unit, "alpha")
        store.save_org_unit(BETA_BACK, "beta")
        store.save_work_journal(
            WorkJournalRecord(
                journal_date="2026-09-17",
                participant="兼務",
                org_unit_id=ALPHA_TEAM.id,
                org_unit_name=ALPHA_TEAM.name,
                owner_email="both@example.com",
            ),
            "alpha",
        )
        self.main = main
        self.store = store
        self.tokens = {user["email"]: issue_app_token(user) for user in list_user_master_entries()}
        self.client = TestClient(main.app, raise_server_exceptions=False)

    def headers(self, email: str, tenant_id: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.tokens[email]}",
            "X-Tenant-ID": tenant_id,
            "Host": "127.0.0.1:8000",
        }

    def test_auth_me_returns_the_org_unit_of_the_selected_tenant(self) -> None:
        for tenant_id, expected in (("alpha", ALPHA_TEAM.id), ("beta", BETA_BACK.id)):
            with self.subTest(tenant_id=tenant_id):
                response = self.client.get("/api/auth/me", headers=self.headers("both@example.com", tenant_id))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["org_unit_id"], expected)

    def test_org_units_of_another_tenant_can_be_listed_for_assignment(self) -> None:
        response = self.client.get(
            "/api/org-units",
            params={"tenant_id": "beta"},
            headers=self.headers("sysadmin@example.com", "alpha"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([unit["id"] for unit in response.json()], [BETA_BACK.id])

    def test_an_org_unit_from_another_tenant_is_rejected(self) -> None:
        response = self.client.put(
            "/api/users/both@example.com",
            json={
                "email": "both@example.com",
                "name": "兼務",
                "role": "none",
                "enabled": True,
                "tenant_memberships": [
                    {"tenant_id": "alpha", "role": "user", "org_unit_id": BETA_BACK.id},
                ],
            },
            headers=self.headers("sysadmin@example.com", "alpha"),
        )

        self.assertEqual(response.status_code, 422)

    def test_a_company_wide_position_covers_every_organization(self) -> None:
        """全社の所属は、部門を配下へ付け替えなくても全メンバーを見渡せる。"""
        response = self.client.get(
            "/api/work-journals/members", headers=self.headers("executive@example.com", "alpha")
        )

        self.assertEqual(response.status_code, 200)
        emails = [member["email"] for member in response.json()]
        self.assertIn("both@example.com", emails)
        self.assertIn("legacy@example.com", emails)

    def test_a_company_wide_position_reads_the_whole_organization_digest(self) -> None:
        response = self.client.get(
            "/api/work-journals/organization",
            params={"org_unit_id": ALPHA_ALL.id},
            headers=self.headers("executive@example.com", "alpha"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["journal_count"], 1)
