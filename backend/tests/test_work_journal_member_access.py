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

DEPARTMENT = OrgUnitRecord(id="sales0001", name="営業部", kind="部門")
TEAM = OrgUnitRecord(id="sales0002", parent_id="sales0001", name="営業1課", kind="課")
OTHER = OrgUnitRecord(id="backoffice", name="管理部", kind="部門")


def user_row(email: str, role: str, tenant_role: str, org_unit_id: str) -> dict:
    return {
        "email": email,
        "name": email,
        "role": role,
        "org_unit_id": org_unit_id,
        "enabled": True,
        "tenant_memberships": [{"tenant_id": "default", "role": tenant_role}],
    }


def journal(owner_email: str, org_unit: OrgUnitRecord) -> WorkJournalRecord:
    return WorkJournalRecord(
        journal_date="2026-09-17",
        participant=owner_email,
        org_unit_id=org_unit.id,
        org_unit_name=org_unit.name,
        owner_email=owner_email,
    )


class WorkJournalMemberAccessTest(unittest.TestCase):
    """他人の業務日報は、manager以上が自組織配下についてだけ開ける。"""

    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        auth_dir = root / "auth"
        auth_dir.mkdir(parents=True, exist_ok=True)
        (auth_dir / "tenant_master.json").write_text(
            json.dumps([{"id": "default", "name": "既定テナント", "enabled": True}], ensure_ascii=False),
            encoding="utf-8",
        )
        (auth_dir / "user_master.json").write_text(
            json.dumps([
                user_row("sysadmin@example.com", "admin", "admin", ""),
                user_row("manager@example.com", "none", "manager", DEPARTMENT.id),
                user_row("member@example.com", "none", "user", TEAM.id),
                user_row("outsider@example.com", "none", "user", OTHER.id),
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
        for unit in (DEPARTMENT, TEAM, OTHER):
            store.save_org_unit(unit, "default")
        store.save_work_journal(journal("member@example.com", TEAM), "default")
        store.save_work_journal(journal("outsider@example.com", OTHER), "default")
        self.store = store
        self.tokens = {user["email"]: issue_app_token(user) for user in list_user_master_entries()}
        self.client = TestClient(main.app, raise_server_exceptions=False)

    def headers(self, email: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tokens[email]}", "Host": "127.0.0.1:8000"}

    def member_emails(self, email: str) -> list[str]:
        response = self.client.get("/api/work-journals/members", headers=self.headers(email))
        self.assertEqual(response.status_code, 200)
        return [member["email"] for member in response.json()]

    def test_manager_sees_only_its_own_subtree(self) -> None:
        emails = self.member_emails("manager@example.com")
        self.assertIn("manager@example.com", emails)
        self.assertIn("member@example.com", emails)
        self.assertNotIn("outsider@example.com", emails)

    def test_plain_user_sees_only_itself(self) -> None:
        self.assertEqual(self.member_emails("member@example.com"), ["member@example.com"])

    def test_system_admin_sees_every_tenant_member(self) -> None:
        emails = self.member_emails("sysadmin@example.com")
        self.assertIn("member@example.com", emails)
        self.assertIn("outsider@example.com", emails)

    def test_manager_can_read_a_subordinate_journal(self) -> None:
        response = self.client.get(
            "/api/work-journals",
            params={"owner_email": "member@example.com"},
            headers=self.headers("manager@example.com"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([record["owner_email"] for record in response.json()], ["member@example.com"])

    def test_manager_cannot_read_outside_its_organization(self) -> None:
        response = self.client.get(
            "/api/work-journals",
            params={"owner_email": "outsider@example.com"},
            headers=self.headers("manager@example.com"),
        )

        self.assertEqual(response.status_code, 404)

    def test_plain_user_cannot_read_another_journal(self) -> None:
        response = self.client.get(
            "/api/work-journals",
            params={"owner_email": "member@example.com"},
            headers=self.headers("outsider@example.com"),
        )

        self.assertEqual(response.status_code, 404)
