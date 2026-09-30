from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

PROTECTED_REQUESTS = (
    ("GET", "/api/users"),
    ("GET", "/api/work-journals"),
    ("POST", "/api/work-journals"),
    ("GET", "/api/org-units"),
    ("DELETE", "/api/users/no-such-user@example.invalid"),
)
MALFORMED_HOSTS = (
    "example.com/anything",
    "example.com/../../api",
    "example.com anything",
    "example.com\tanything",
    "a" * 300,
)


def build_client(test: unittest.TestCase, directory: str) -> TestClient:
    """実データのパスで作られたストアを、必ず一時DBへ差し替えてから使う。"""
    from backend.app import main
    from backend.app import runtime
    from backend.app.api import middleware
    from backend.app.storage.sqlite_store import HinamiSQLiteStore

    patcher = patch.object(runtime, "store", HinamiSQLiteStore(Path(directory) / "hinami.sqlite"))
    patcher.start()
    test.addCleanup(patcher.stop)
    return TestClient(main.app, raise_server_exceptions=False)


class RequestAuthorizationTest(unittest.TestCase):
    """認可判定はHostヘッダーで揺れてはいけない。"""

    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        patcher = patch.dict(os.environ, {
            "GOOGLE_OAUTH_CLIENT_ID": "test-client-id",
            "APP_AUTH_SECRET": "test-secret",
            "HINAMI_AUTH_DIR": str(Path(self.directory.name) / "auth"),
        })
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = build_client(self, self.directory.name)

    def request(self, method: str, path: str, **kwargs):
        payload = {"json": {}} if method in {"PUT", "POST", "PATCH"} else {}
        return self.client.request(method, path, **payload, **kwargs)

    def test_protected_apis_require_authentication(self) -> None:
        for method, path in PROTECTED_REQUESTS:
            with self.subTest(method=method, path=path):
                response = self.request(method, path, headers={"Host": "127.0.0.1:8000"})
                self.assertEqual(response.status_code, 401)

    def test_malformed_host_never_reaches_a_protected_handler(self) -> None:
        """Hostにパスを混ぜるとrequest.urlのパスがずれ、認可判定が素通りしていた。"""
        for host in MALFORMED_HOSTS:
            for method, path in PROTECTED_REQUESTS:
                with self.subTest(host=host, method=method, path=path):
                    response = self.request(method, path, headers={"Host": host})
                    self.assertIn(response.status_code, {400, 401})

    def test_public_endpoints_still_answer(self) -> None:
        for path in ("/api/health", "/api/auth/config"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_malformed_bearer_tokens_return_401_not_500(self) -> None:
        for token in ("a.b.a", "a.b.a=", "a.b.1", "a.b.c", "notatoken", "", "a.b." + "A" * 9000):
            with self.subTest(token=token[:16]):
                response = self.client.get(
                    "/api/work-journals", headers={"Authorization": f"Bearer {token}"}
                )
                self.assertEqual(response.status_code, 401)

    def test_cross_origin_writes_are_rejected(self) -> None:
        response = self.client.post(
            "/api/work-journals",
            json={},
            headers={"Origin": "http://evil.example", "Host": "127.0.0.1:8000"},
        )
        self.assertEqual(response.status_code, 403)

    def test_origin_matching_a_forged_host_is_rejected_when_hosts_are_configured(self) -> None:
        """HINAMI_ALLOWED_HOSTS を設定すると、同一オリジン判定もその一覧に限定される。"""
        from backend.app import main

        from backend.app import runtime
        from backend.app.api import middleware
        with patch.object(middleware, "allowed_hosts", ["127.0.0.1:8000"]):
            forged = self.client.post(
                "/api/work-journals",
                json={},
                headers={"Origin": "http://evil.example", "Host": "evil.example"},
            )
            self.assertEqual(forged.status_code, 400)

            unlisted = self.client.post(
                "/api/work-journals",
                json={},
                headers={"Origin": "http://other.example", "Host": "other.example"},
            )
            self.assertEqual(unlisted.status_code, 400)

    def test_same_origin_writes_pass_the_origin_check(self) -> None:
        """本番は同一オリジン配信のため、この経路を塞ぐと保存できなくなる。"""
        response = self.client.post(
            "/api/work-journals",
            json={},
            headers={"Origin": "http://127.0.0.1:8000", "Host": "127.0.0.1:8000"},
        )
        # Originでは弾かれず、認証で止まることを確認する。
        self.assertEqual(response.status_code, 401)


class UnauthenticatedModeClientTest(unittest.TestCase):
    """ログインなしの開発モードは、ループバックと宣言した接続元からだけ使える。"""

    def _client(self, host: str) -> TestClient:
        from backend.app import main

        from backend.app import runtime
        from backend.app.api import middleware
        return TestClient(main.app, raise_server_exceptions=False, client=(host, 50000))

    def test_remote_client_is_rejected(self) -> None:
        # HINAMI_API_HOST の宣言だけでは、実際に0.0.0.0で待ち受けていても気付けない。
        with patch.dict(
            os.environ,
            {"GOOGLE_OAUTH_CLIENT_ID": "", "HINAMI_API_HOST": "127.0.0.1", "HINAMI_LOCAL_CLIENT_HOSTS": ""},
        ):
            response = self._client("192.168.1.10").get(
                "/api/health", headers={"X-Forwarded-For": "127.0.0.1"}
            )
        self.assertEqual(response.status_code, 403)

    def test_loopback_and_declared_gateway_are_allowed(self) -> None:
        with patch.dict(
            os.environ,
            {"GOOGLE_OAUTH_CLIENT_ID": "", "HINAMI_API_HOST": "0.0.0.0", "HINAMI_LOCAL_CLIENT_HOSTS": "172.29.90.1"},
        ):
            for host in ("127.0.0.1", "172.29.90.1"):
                with self.subTest(host=host):
                    self.assertEqual(self._client(host).get("/api/health").status_code, 200)
            self.assertEqual(self._client("172.29.90.2").get("/api/health").status_code, 403)


if __name__ == "__main__":
    unittest.main()
