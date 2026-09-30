from __future__ import annotations

import base64
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.app import runtime
from backend.app.api import settings_api
from backend.app.core import ai_models, google_cloud_auth, k8s_token
from backend.app.services import gemini
from backend.app.storage.sqlite_store import HinamiSQLiteStore

WIF_SETTINGS = {
    "project": "hinami-prod",
    "location": "asia-northeast1",
    "wif_project_number": "123456789012",
    "wif_pool_id": "hinami-pool",
    "wif_provider_id": "k3s-provider",
    "wif_service_account": "hinami-tts@example-project.iam.gserviceaccount.com",
}
# 環境変数の影響を受けないよう、関係する値はすべて空にしてから試す。
CLEAN_ENVIRONMENT = {
    "GEMINI_BACKEND": "",
    "GEMINI_MODEL": "",
    "GEMINI_TRANSCRIPTION_BACKEND": "",
    "GEMINI_TRANSCRIPTION_MODEL": "",
    "HINAMI_TTS_ENGINE": "",
    "GEMINI_TTS_MODEL": "",
    "CLOUD_TTS_MODEL": "",
    "GOOGLE_CLOUD_PROJECT": "",
    "GOOGLE_CLOUD_LOCATION": "",
    "GEMINI_API_KEY": "AIzaSyTestKey_0123456789abcdefghij",
}


def user_row(email: str, role: str, tenant_role: str) -> dict:
    return {
        "email": email,
        "name": email,
        "role": role,
        "enabled": True,
        "tenant_memberships": [{"tenant_id": "default", "role": tenant_role}],
    }


class IsolatedSettings(unittest.TestCase):
    """設定ファイルを一時フォルダへ向け、環境変数を空にする。"""

    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for target, attribute, value in (
            (google_cloud_auth, "GOOGLE_CLOUD_AUTH_FILE", self.root / "google_cloud.json"),
            (ai_models, "AI_MODELS_FILE", self.root / "ai_models.json"),
            (gemini, "GEMINI_API_KEY_FILE", self.root / "gemini_api_key"),
        ):
            patcher = patch.object(target, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        env = patch.dict(os.environ, CLEAN_ENVIRONMENT)
        env.start()
        self.addCleanup(env.stop)
        for cached in (google_cloud_auth._credentials_for, gemini._vertex_client):
            cached.cache_clear()
            self.addCleanup(cached.cache_clear)


class GoogleCloudSettingsTest(IsolatedSettings):
    """② Vertex AI（Google Cloud）への接続：プロジェクト、リージョン、認証。"""

    def on_kubernetes(self, running: bool = True) -> None:
        patcher = patch.object(k8s_token, "running_on_kubernetes", return_value=running)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_defaults_to_adc_and_environment_project(self) -> None:
        self.assertEqual(google_cloud_auth.active_auth(), "adc")
        self.assertIsNone(google_cloud_auth.google_cloud_credentials())
        with patch.dict(os.environ, {"GOOGLE_CLOUD_PROJECT": "env-project"}):
            settings = google_cloud_auth.effective_google_cloud()
        self.assertEqual((settings["project"], settings["location"]), ("env-project", "global"))

    def test_wif_settings_are_saved_and_read_back(self) -> None:
        google_cloud_auth.save_google_cloud_auth(WIF_SETTINGS)

        self.assertEqual(google_cloud_auth.load_google_cloud_auth(), WIF_SETTINGS)
        self.assertEqual(
            google_cloud_auth.wif_audience(WIF_SETTINGS),
            "//iam.googleapis.com/projects/123456789012/locations/global/"
            "workloadIdentityPools/hinami-pool/providers/k3s-provider",
        )

    def test_invalid_settings_are_rejected(self) -> None:
        for key, value, message in (
            ("project", "123456", "プロジェクトID"),
            ("location", "Tokyo!", "リージョン"),
            ("wif_project_number", "my-project", "プロジェクト番号"),
            ("wif_pool_id", "P", "プールID"),
            ("wif_provider_id", "", "プロバイダーID"),
            ("wif_service_account", "someone@example.com", "サービスアカウント"),
        ):
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError, message):
                    google_cloud_auth.save_google_cloud_auth({**WIF_SETTINGS, key: value})

    def test_auth_is_chosen_by_where_it_runs(self) -> None:
        # WIF を設定していても、Kubernetes の外（ローカルや Docker）では google.auth.default()（ADC）を使う。
        google_cloud_auth.save_google_cloud_auth(WIF_SETTINGS)
        self.on_kubernetes(False)
        self.assertEqual(google_cloud_auth.active_auth(), "adc")
        self.assertEqual(google_cloud_auth.credentials_key(), ("adc",))
        self.assertIsNone(google_cloud_auth.google_cloud_credentials())

    def test_kubernetes_without_wif_uses_adc(self) -> None:
        self.on_kubernetes(True)
        self.assertEqual(google_cloud_auth.active_auth(), "adc")

    def test_wif_fields_are_optional_but_must_be_complete(self) -> None:
        saved = google_cloud_auth.save_google_cloud_auth({"project": "hinami-prod"})
        self.assertFalse(google_cloud_auth.wif_configured(saved))
        with self.assertRaisesRegex(ValueError, "プールID"):
            google_cloud_auth.save_google_cloud_auth({"wif_project_number": "123456789012"})

    def test_adc_refresh_uses_google_auth_default(self) -> None:
        credentials = MagicMock()
        with patch("google.auth.default", return_value=(credentials, "project")) as default:
            google_cloud_auth.refresh_google_cloud_credentials()
        default.assert_called_once()
        credentials.refresh.assert_called_once()

    def test_missing_default_credentials_are_explained(self) -> None:
        class DefaultCredentialsError(Exception):
            pass

        message = google_cloud_auth.describe_auth_error(DefaultCredentialsError("not found"))
        self.assertIn("gcloud auth application-default login", message)
        self.assertIn("GOOGLE_APPLICATION_CREDENTIALS", message)

    def test_service_account_is_optional(self) -> None:
        # koyorina と同じく、なりすまし先は任意。空なら Kubernetes の身元に直接権限を付ける。
        self.on_kubernetes(True)
        settings = google_cloud_auth.save_google_cloud_auth({**WIF_SETTINGS, "wif_service_account": ""})

        self.assertNotIn("service_account_impersonation_url", google_cloud_auth.wif_credential_config(settings))
        # プロジェクトを引数に取らない API（Cloud Text-to-Speech）は、② のプロジェクトで数える。
        self.assertEqual(google_cloud_auth.quota_project(), "hinami-prod")

    def test_quota_project_is_not_set_with_a_service_account(self) -> None:
        google_cloud_auth.save_google_cloud_auth(WIF_SETTINGS)
        self.assertIsNone(google_cloud_auth.quota_project())

    def test_wif_credentials_exchange_the_kubernetes_token(self) -> None:
        self.on_kubernetes(True)
        google_cloud_auth.save_google_cloud_auth(WIF_SETTINGS)
        sentinel = object()
        with patch.object(k8s_token, "credentials", return_value=sentinel) as credentials:
            self.assertIs(google_cloud_auth.google_cloud_credentials(), sentinel)

        config, supplier = credentials.call_args.args
        self.assertEqual(supplier.audience, google_cloud_auth.wif_audience(WIF_SETTINGS))
        self.assertIn(":generateAccessToken", config["service_account_impersonation_url"])


class AiModelsTest(IsolatedSettings):
    """役割ごとの接続方法とモデル。空の項目は環境変数に従う。"""

    def test_defaults(self) -> None:
        settings = ai_models.effective_ai_models()

        self.assertEqual(settings["chat_connection"], "gemini-api")
        self.assertEqual(settings["chat_model"], gemini.DEFAULT_GEMINI_MODEL)
        # 文字起こしは、決めていなければ対話と同じ接続とモデル。
        self.assertEqual(settings["transcription_connection"], "gemini-api")
        self.assertEqual(settings["transcription_model"], gemini.DEFAULT_GEMINI_MODEL)
        self.assertEqual(settings["speech_engine"], "gemini-tts")

    def test_environment_can_set_each_role(self) -> None:
        with patch.dict(os.environ, {
            "GEMINI_BACKEND": "vertex",
            "GEMINI_MODEL": "gemini-3.8-flash",
            "GEMINI_TRANSCRIPTION_BACKEND": "gemini-api",
            "GEMINI_TRANSCRIPTION_MODEL": "gemini-3.5-transcribe",
            "HINAMI_TTS_ENGINE": "cloud-tts",
            "CLOUD_TTS_MODEL": "gemini-2.5-pro-tts",
        }):
            settings = ai_models.effective_ai_models()

        self.assertEqual(settings, {
            "chat_connection": "vertex",
            "chat_model": "gemini-3.8-flash",
            "transcription_connection": "gemini-api",
            "transcription_model": "gemini-3.5-transcribe",
            "speech_engine": "cloud-tts",
            "speech_model": "gemini-2.5-pro-tts",
        })

    def test_transcription_follows_the_chat_connection(self) -> None:
        google_cloud_auth.save_google_cloud_auth({"project": "hinami-prod"})
        ai_models.save_ai_models({"chat_connection": "vertex"})
        self.assertEqual(ai_models.effective_ai_models()["transcription_connection"], "vertex")

    def test_vertex_requires_a_project(self) -> None:
        with self.assertRaisesRegex(ValueError, "プロジェクトID"):
            ai_models.save_ai_models({"transcription_connection": "vertex"})

    def test_invalid_values_are_rejected(self) -> None:
        for key, value in (("chat_connection", "other"), ("speech_engine", "other"), ("chat_model", "a b")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                ai_models.save_ai_models({key: value})


class GeminiRoutingTest(IsolatedSettings):
    """役割ごとに、選んだ接続方法とモデルで呼び出す。"""

    def use_vertex_for(self, **connections: str) -> None:
        google_cloud_auth.save_google_cloud_auth({"project": "hinami-prod", "location": ""})
        ai_models.save_ai_models(connections)

    def test_vertex_client_uses_project_location_and_cloud_credentials(self) -> None:
        self.use_vertex_for(chat_connection="vertex")
        with patch("google.genai.Client") as client_class:
            gemini.gemini_client()

        kwargs = client_class.call_args.kwargs
        self.assertEqual((kwargs["vertexai"], kwargs["project"], kwargs["location"]), (True, "hinami-prod", "global"))
        self.assertIsNone(kwargs["credentials"])

    def test_chat_and_transcription_can_use_different_connections(self) -> None:
        self.use_vertex_for(chat_connection="gemini-api", transcription_connection="vertex",
                            transcription_model="gemini-3.5-transcribe")
        with patch.object(gemini, "_client") as api_client, patch.object(gemini, "_vertex_client") as vertex:
            gemini.gemini_client(role="chat")
            gemini.gemini_client(role="transcription")

        api_client.assert_called_once()
        vertex.assert_called_once()
        self.assertEqual(gemini.model_for("transcription"), "gemini-3.5-transcribe")

    def test_transcription_is_generated_with_its_role(self) -> None:
        with patch.object(gemini, "generate_structured") as generate:
            gemini.generate_audio_transcription(b"audio", "audio/webm")
        self.assertEqual(generate.call_args.kwargs["role"], "transcription")

    def test_gemini_tts_always_uses_the_api_key(self) -> None:
        # 読み上げの Gemini TTS は ① 固定。対話を ② にしても変わらない。
        self.use_vertex_for(chat_connection="vertex", transcription_connection="vertex")
        with patch.object(gemini, "_client") as api_client, patch("google.genai.Client") as vertex_class:
            gemini.gemini_api_key_client()
        api_client.assert_called_once()
        vertex_class.assert_not_called()
        self.assertEqual(ai_models.speech_connection("gemini-tts"), "gemini-api")
        self.assertEqual(ai_models.speech_connection("cloud-tts"), "vertex")

    def test_check_looks_up_the_role_model_without_generating(self) -> None:
        ai_models.save_ai_models({"transcription_model": "gemini-3.5-transcribe"})
        client = MagicMock()
        with patch.object(gemini, "_client", return_value=client):
            result = gemini.check_ai_model("transcription")

        self.assertTrue(result["ok"])
        client.models.get.assert_called_once_with(model="gemini-3.5-transcribe")
        client.models.generate_content.assert_not_called()

    def test_speech_check_uses_cloud_tts_when_selected(self) -> None:
        ai_models.save_ai_models({"speech_engine": "cloud-tts"})
        expected = {"ok": True, "step": "api", "message": "ok"}
        with patch("backend.app.services.cloud_tts.check_cloud_tts", return_value=expected) as check:
            self.assertEqual(gemini.check_ai_model("speech"), expected)
        check.assert_called_once()

    def test_configured_depends_on_the_connection(self) -> None:
        self.assertTrue(gemini.gemini_configured())
        ai_models.AI_MODELS_FILE.write_text(json.dumps({"chat_connection": "vertex"}), encoding="utf-8")
        self.assertFalse(gemini.gemini_configured())


class KubernetesTokenTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        claims = {"sub": "system:serviceaccount:hinami:hinami-app"}
        payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
        (self.directory / "token").write_text(f"header.{payload}.signature")

    def test_identity_is_read_from_the_mounted_token(self) -> None:
        self.assertEqual(k8s_token.identity(self.directory), ("hinami", "hinami-app"))
        self.assertEqual(k8s_token.subject(self.directory), "system:serviceaccount:hinami:hinami-app")

    def test_missing_token_means_not_on_kubernetes(self) -> None:
        with self.assertRaises(k8s_token.TokenUnavailable):
            k8s_token.identity(self.directory / "missing")

    def test_token_is_requested_with_the_audience_and_reused(self) -> None:
        supplier = k8s_token.KubernetesTokenSupplier("//iam.googleapis.com/example", self.directory)
        with patch.object(k8s_token, "_request", return_value={"status": {"token": "issued"}}) as request:
            self.assertEqual(supplier.get_subject_token(None, None), "issued")
            self.assertEqual(supplier.get_subject_token(None, None), "issued")

        request.assert_called_once()
        method, path, _, body = request.call_args.args
        self.assertEqual((method, path), ("POST", "/api/v1/namespaces/hinami/serviceaccounts/hinami-app/token"))
        self.assertEqual(body["spec"]["audiences"], ["//iam.googleapis.com/example"])


class SettingsApiTest(IsolatedSettings):
    """接続方法と役割ごとのモデルは、システム管理者だけが変えられる。"""

    def setUp(self) -> None:
        super().setUp()
        auth_dir = self.root / "auth"
        auth_dir.mkdir(parents=True)
        (auth_dir / "tenant_master.json").write_text(
            json.dumps([{"id": "default", "name": "既定テナント", "enabled": True}], ensure_ascii=False),
            encoding="utf-8",
        )
        (auth_dir / "user_master.json").write_text(
            json.dumps([
                user_row("sysadmin@example.com", "admin", "admin"),
                user_row("tenantadmin@example.com", "user", "admin"),
            ]),
            encoding="utf-8",
        )
        env = patch.dict(os.environ, {"GOOGLE_OAUTH_CLIENT_ID": "test-client-id", "APP_AUTH_SECRET": "test-secret"})
        env.start()
        self.addCleanup(env.stop)

        import backend.app.core.auth as auth
        import backend.app.main as main
        from backend.app.core.auth import issue_app_token, list_user_master_entries

        for target, attribute, value in (
            (auth, "AUTH_DIR", auth_dir),
            (auth, "USER_MASTER_FILE", auth_dir / "user_master.json"),
            (auth, "TENANT_MASTER_FILE", auth_dir / "tenant_master.json"),
            (runtime, "store", HinamiSQLiteStore(self.root / "hinami.sqlite")),
        ):
            patcher = patch.object(target, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = TestClient(main.app, raise_server_exceptions=False)
        self.tokens = {user["email"]: issue_app_token(user) for user in list_user_master_entries()}

    def headers(self, email: str = "sysadmin@example.com") -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tokens[email]}", "Host": "127.0.0.1:8000"}

    def test_google_cloud_settings_are_saved_with_environment_defaults(self) -> None:
        response = self.client.put("/api/settings/google-cloud", json=WIF_SETTINGS, headers=self.headers())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            **WIF_SETTINGS,
            "environment": {"project": "", "location": "global"},
            # テストは Kubernetes の外で動くので、WIF を設定していても ADC を使う。
            "active_auth": "adc",
            "running_on_kubernetes": False,
        })

    def test_ai_models_are_saved_per_role(self) -> None:
        self.client.put("/api/settings/google-cloud", json={"project": "hinami-prod"}, headers=self.headers())
        response = self.client.put(
            "/api/settings/ai-models",
            json={"chat_connection": "vertex", "transcription_model": "gemini-3.5-transcribe", "speech_engine": "cloud-tts"},
            headers=self.headers(),
        )

        self.assertEqual(response.status_code, 200)
        effective = response.json()["effective"]
        self.assertEqual(effective["chat_connection"], "vertex")
        self.assertEqual(effective["transcription_connection"], "vertex")
        self.assertEqual(effective["transcription_model"], "gemini-3.5-transcribe")
        self.assertEqual(effective["speech_engine"], "cloud-tts")
        self.assertEqual(response.json()["environment"]["chat_connection"], "gemini-api")

    def test_vertex_without_a_project_returns_422(self) -> None:
        response = self.client.put("/api/settings/ai-models", json={"chat_connection": "vertex"}, headers=self.headers())

        self.assertEqual(response.status_code, 422)
        self.assertIn("プロジェクトID", response.json()["detail"])

    def test_role_check_returns_the_result(self) -> None:
        result = {"ok": False, "step": "sts", "message": "invalid_grant"}
        with patch.object(settings_api, "check_ai_model", return_value=result) as check:
            response = self.client.post("/api/settings/ai-models/transcription/check", headers=self.headers())

        self.assertEqual(response.json(), result)
        check.assert_called_once_with("transcription")
        self.assertEqual(
            self.client.post("/api/settings/ai-models/other/check", headers=self.headers()).status_code, 422
        )

    def test_tenant_admin_cannot_read_or_change_settings(self) -> None:
        headers = self.headers("tenantadmin@example.com")
        for method, path in (
            ("GET", "/api/settings/ai-models"),
            ("PUT", "/api/settings/ai-models"),
            ("PUT", "/api/settings/google-cloud"),
            ("POST", "/api/settings/ai-models/chat/check"),
        ):
            with self.subTest(method=method, path=path):
                response = self.client.request(method, path, json={} if method == "PUT" else None, headers=headers)
                self.assertEqual(response.status_code, 403)

    def test_workload_identity_is_unavailable_outside_kubernetes(self) -> None:
        with patch.object(k8s_token.identity, "__defaults__", (Path("/nonexistent/serviceaccount"),)):
            response = self.client.get("/api/settings/google-cloud/workload-identity", headers=self.headers())

        self.assertEqual(response.status_code, 409)
        self.assertIn("Kubernetes", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
