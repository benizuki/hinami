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

EXISTING_UNIT = OrgUnitRecord(id="itdept01", name="情報システム部", kind="部門")
NEW_UNIT = {"parent_id": "", "name": "新しい部門", "kind": "部門", "sort_order": 0}


def user_row(email: str, role: str, tenant_role: str) -> dict:
    return {
        "email": email,
        "name": email,
        "role": role,
        "enabled": True,
        "tenant_memberships": [{"tenant_id": "default", "role": tenant_role}],
    }


class OrgUnitPermissionTest(unittest.TestCase):
    """組織の階層は所属の基準になるため、参照は全員、変更は管理者だけ。"""

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
                user_row("sysadmin@example.com", "admin", "admin"),
                user_row("tenantadmin@example.com", "user", "admin"),
                user_row("member@example.com", "user", "user"),
                user_row("watcher@example.com", "viewer", "viewer"),
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

        # 認証ファイルのパスは読み込み時に確定するため、環境変数ではなく属性を差し替える。
        for attribute, value in (
            ("AUTH_DIR", auth_dir),
            ("USER_MASTER_FILE", auth_dir / "user_master.json"),
            ("TENANT_MASTER_FILE", auth_dir / "tenant_master.json"),
        ):
            auth_patcher = patch.object(auth, attribute, value)
            auth_patcher.start()
            self.addCleanup(auth_patcher.stop)
        self.main = main
        store = HinamiSQLiteStore(root / "hinami.sqlite")
        for patcher in (
            patch.object(runtime, "store", store),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        store.save_org_unit(EXISTING_UNIT, "default")
        self.store = store
        self.tokens = {user["email"]: issue_app_token(user) for user in list_user_master_entries()}
        self.client = TestClient(main.app, raise_server_exceptions=False)

    def headers(self, email: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tokens[email]}", "Host": "127.0.0.1:8000"}

    def test_everyone_can_read_the_hierarchy(self) -> None:
        """所属の選択に使うため、参照まで止めると日報が書けなくなる。"""
        for email in self.tokens:
            with self.subTest(email=email):
                response = self.client.get("/api/org-units", headers=self.headers(email))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()[0]["id"], "itdept01")

    def test_user_and_viewer_cannot_create(self) -> None:
        for email in ("member@example.com", "watcher@example.com"):
            with self.subTest(email=email):
                response = self.client.post(
                    "/api/org-units", json=NEW_UNIT, headers=self.headers(email)
                )
                self.assertEqual(response.status_code, 403)
        self.assertEqual(len(self.store.list_org_units("default")), 1)

    def test_user_and_viewer_cannot_update(self) -> None:
        for email in ("member@example.com", "watcher@example.com"):
            with self.subTest(email=email):
                response = self.client.put(
                    f"/api/org-units/{EXISTING_UNIT.id}",
                    json={**NEW_UNIT, "name": "書き換え"},
                    headers=self.headers(email),
                )
                self.assertEqual(response.status_code, 403)
        self.assertEqual(self.store.list_org_units("default")[0].name, "情報システム部")

    def test_user_and_viewer_cannot_delete(self) -> None:
        for email in ("member@example.com", "watcher@example.com"):
            with self.subTest(email=email):
                response = self.client.delete(
                    f"/api/org-units/{EXISTING_UNIT.id}", headers=self.headers(email)
                )
                self.assertEqual(response.status_code, 403)
        self.assertEqual(len(self.store.list_org_units("default")), 1)

    def test_tenant_admin_can_manage(self) -> None:
        """テナント管理者は自分のテナントの組織を管理できる。"""
        response = self.client.post(
            "/api/org-units", json=NEW_UNIT, headers=self.headers("tenantadmin@example.com")
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.store.list_org_units("default")), 2)

    def test_system_admin_can_manage(self) -> None:
        response = self.client.post(
            "/api/org-units", json=NEW_UNIT, headers=self.headers("sysadmin@example.com")
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.store.list_org_units("default")), 2)


if __name__ == "__main__":
    unittest.main()
