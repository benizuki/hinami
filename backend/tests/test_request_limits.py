from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.app import main



from backend.app.api import middleware

from backend.app.api import auth_api
class LoginRateLimitTest(unittest.TestCase):
    """/api/auth/google は未認証で呼べて、1回ごとにGoogleの検証まで進む。"""

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
        auth_api._login_limiter.reset()
        self.addCleanup(auth_api._login_limiter.reset)

        from fastapi.testclient import TestClient

        self.client = TestClient(main.app, raise_server_exceptions=False)

    def test_repeated_logins_from_one_client_are_throttled(self) -> None:
        headers = {"Host": "127.0.0.1:8000", "X-Forwarded-For": "203.0.113.9"}
        statuses = []
        for _ in range(auth_api.LOGIN_RATE_PER_MINUTE + 2):
            response = self.client.post(
                "/api/auth/google", json={"credential": "not-a-real-token"}, headers=headers
            )
            statuses.append(response.status_code)

        self.assertNotIn(429, statuses[: auth_api.LOGIN_RATE_PER_MINUTE])
        self.assertEqual(statuses[-1], 429)

    def test_an_oversized_credential_is_rejected_before_verification(self) -> None:
        response = self.client.post(
            "/api/auth/google",
            json={"credential": "a" * 20_000},
            headers={"Host": "127.0.0.1:8000", "X-Forwarded-For": "203.0.113.10"},
        )

        self.assertEqual(response.status_code, 422)

    def test_spoofed_forwarded_for_does_not_bypass_the_limit_by_default(self) -> None:
        """直接公開された環境では、X-Forwarded-For を変えても別の接続元とみなさない。"""
        statuses = []
        for index in range(auth_api.LOGIN_RATE_PER_MINUTE + 2):
            response = self.client.post(
                "/api/auth/google",
                json={"credential": "not-a-real-token"},
                headers={"Host": "127.0.0.1:8000", "X-Forwarded-For": f"198.51.100.{index}"},
            )
            statuses.append(response.status_code)

        self.assertEqual(statuses[-1], 429)

    def test_forwarded_for_is_used_when_the_proxy_is_trusted(self) -> None:
        with patch.dict(os.environ, {"HINAMI_TRUST_FORWARDED_FOR": "true"}):
            statuses = []
            for index in range(auth_api.LOGIN_RATE_PER_MINUTE + 2):
                response = self.client.post(
                    "/api/auth/google",
                    json={"credential": "not-a-real-token"},
                    headers={"Host": "127.0.0.1:8000", "X-Forwarded-For": f"198.51.100.{index}"},
                )
                statuses.append(response.status_code)

        self.assertNotIn(429, statuses)

    def test_a_request_declaring_a_huge_body_is_rejected(self) -> None:
        response = self.client.request(
            "POST",
            "/api/work-journals",
            content=b"{}",
            headers={
                "Host": "127.0.0.1:8000",
                "Content-Type": "application/json",
                "Content-Length": str(middleware.MAX_REQUEST_BYTES + 1),
            },
        )

        self.assertEqual(response.status_code, 413)


if __name__ == "__main__":
    unittest.main()
