from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.core.auth import auth_enabled, demo_login_enabled, validate_auth_configuration


class DemoLoginConfigurationTest(unittest.TestCase):
    def test_demo_login_requires_login_without_google(self) -> None:
        with patch.dict(
            os.environ,
            {"HINAMI_API_HOST": "0.0.0.0", "HINAMI_LOCAL_CLIENT_HOSTS": "172.29.90.1", "HINAMI_DEMO_LOGIN": "1"},
            clear=True,
        ):
            validate_auth_configuration()
            self.assertTrue(demo_login_enabled())
            self.assertTrue(auth_enabled())

    def test_demo_login_cannot_be_combined_with_google(self) -> None:
        with patch.dict(
            os.environ,
            {"HINAMI_API_HOST": "0.0.0.0", "GOOGLE_OAUTH_CLIENT_ID": "id", "HINAMI_DEMO_LOGIN": "1"},
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "HINAMI_DEMO_LOGIN"):
                validate_auth_configuration()

    def test_demo_login_is_rejected_on_cloud_and_production(self) -> None:
        for extra in ({"K_SERVICE": "run"}, {"APP_ENV": "production", "HINAMI_API_HOST": "127.0.0.1"}):
            with patch.dict(os.environ, {"HINAMI_DEMO_LOGIN": "1", **extra}, clear=True):
                with self.assertRaises(RuntimeError):
                    validate_auth_configuration()


class DemoLoginApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        patcher = patch.dict(os.environ, {
            "HINAMI_DEMO_LOGIN": "1",
            "HINAMI_API_HOST": "127.0.0.1",
            "APP_AUTH_SECRET": "test-secret",
            "HINAMI_AUTH_DIR": str(Path(self.directory.name) / "auth"),
        }, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        from backend.app import main, runtime
        from backend.app.api import auth_api
        from backend.app.core import auth
        from backend.app.storage.sqlite_store import HinamiSQLiteStore

        for target in (
            patch.object(runtime, "store", HinamiSQLiteStore(Path(self.directory.name) / "hinami.sqlite")),
            patch.object(auth, "AUTH_DIR", Path(self.directory.name) / "auth"),
            patch.object(auth, "USER_MASTER_FILE", Path(self.directory.name) / "auth" / "user_master.json"),
            patch.object(auth, "TENANT_MASTER_FILE", Path(self.directory.name) / "auth" / "tenant_master.json"),
        ):
            target.start()
            self.addCleanup(target.stop)
        auth_api._login_limiter.__init__()
        self.client = TestClient(main.app, raise_server_exceptions=False)

    def login(self, email: str):
        return self.client.post("/api/auth/demo", json={"email": email})

    def test_config_advertises_demo_login(self) -> None:
        body = self.client.get("/api/auth/config").json()
        self.assertTrue(body["demo_login_enabled"])
        self.assertFalse(body["google_oauth_enabled"])

    def test_requires_login_and_rejects_bad_email(self) -> None:
        self.assertEqual(self.client.get("/api/work-journals").status_code, 401)
        self.assertEqual(self.login("not-an-email").status_code, 400)

    def test_first_user_is_admin_in_root_org_and_next_is_user(self) -> None:
        first = self.login("first@example.com")
        self.assertEqual(first.status_code, 200)
        user = first.json()["user"]
        self.assertEqual(user["role"], "admin")
        self.assertEqual(user["org_unit_id"], "root")
        units = self.client.get("/api/org-units").json()
        self.assertEqual([(unit["id"], unit["name"], unit["kind"]) for unit in units], [("root", "ルート", "全社")])
        self.assertEqual(self.client.get("/api/auth/me").json()["email"], "first@example.com")

        second_client = TestClient(self.client.app, raise_server_exceptions=False)
        second = second_client.post("/api/auth/demo", json={"email": "Second@Example.com"}).json()["user"]
        self.assertEqual(second["email"], "second@example.com")
        self.assertEqual(second["role"], "none")
        self.assertEqual(second["org_unit_id"], "root")
        self.assertEqual(second["tenant_memberships"][0]["role"], "user")

    def test_same_email_logs_in_again_without_duplicating(self) -> None:
        self.login("a@example.com")
        again = self.login("a@example.com")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json()["user"]["role"], "admin")


class RootOrgUnitTest(unittest.TestCase):
    def test_root_is_created_once_and_not_recreated_after_removal(self) -> None:
        from backend.app import runtime
        from backend.app.api.common import ensure_root_org_unit
        from backend.app.schemas import OrgUnitRecord
        from backend.app.storage.sqlite_store import HinamiSQLiteStore

        with TemporaryDirectory() as directory:
            store = HinamiSQLiteStore(Path(directory) / "hinami.sqlite")
            with patch.object(runtime, "store", store):
                self.assertEqual(ensure_root_org_unit("default"), "root")
                self.assertEqual(ensure_root_org_unit("default"), "root")
                self.assertEqual(len(store.list_org_units("default")), 1)
                store.delete_org_unit("root", "default")
                store.save_org_unit(
                    OrgUnitRecord(
                        id="x", name="営業", kind="部門"
                    ),
                    "default",
                )
                self.assertEqual(ensure_root_org_unit("default"), "")


class DemoLoginDisabledTest(unittest.TestCase):
    def test_endpoint_is_not_available_without_demo_flag(self) -> None:
        with patch.dict(os.environ, {"HINAMI_API_HOST": "127.0.0.1"}, clear=True):
            from backend.app import main

            client = TestClient(main.app, raise_server_exceptions=False)
            self.assertEqual(client.post("/api/auth/demo", json={"email": "a@example.com"}).status_code, 404)
            self.assertFalse(client.get("/api/auth/config").json()["demo_login_enabled"])


if __name__ == "__main__":
    unittest.main()
