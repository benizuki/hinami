from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import main



from backend.app.api import frontend_api
class ProductionExposureTest(unittest.TestCase):
    """本番では、未認証で拾える運用情報とAPI仕様を出さない。

    FastAPI の docs_url / openapi_url はアプリ生成時に決まるため、ここでは
    リクエスト時に効く部分を確かめる。生成時の分岐は APP_ENV=prod で起動して
    /docs と /openapi.json が404になることを確認済み。
    """

    def setUp(self) -> None:
        # 認証を省くローカル起動の構成で確かめる（それ以外のホストでは起動自体を拒否する）。
        patcher = patch.dict(os.environ, {"GOOGLE_OAUTH_CLIENT_ID": "", "HINAMI_API_HOST": "127.0.0.1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(main.app, raise_server_exceptions=False)

    @patch.dict(os.environ, {"APP_ENV": "prod"})
    def test_health_hides_the_provider_and_model(self) -> None:
        body = self.client.get("/api/health", headers={"Host": "127.0.0.1:8000"}).json()

        self.assertNotIn("model", body)
        self.assertNotIn("provider", body)
        self.assertIn("llm_configured", body)

    @patch.dict(os.environ, {"APP_ENV": "development"})
    def test_health_keeps_the_model_outside_production(self) -> None:
        body = self.client.get("/api/health", headers={"Host": "127.0.0.1:8000"}).json()

        self.assertIn("model", body)

    @patch.dict(os.environ, {"APP_ENV": "prod"})
    def test_api_doc_paths_do_not_fall_back_to_the_spa(self) -> None:
        for path in ("docs", "redoc", "openapi.json"):
            with self.subTest(path=path):
                self.assertTrue(frontend_api._should_reject_spa_fallback(path))

    @patch.dict(os.environ, {"APP_ENV": "development"})
    def test_api_doc_paths_are_reachable_outside_production(self) -> None:
        self.assertFalse(frontend_api._should_reject_spa_fallback("docs"))


if __name__ == "__main__":
    unittest.main()
