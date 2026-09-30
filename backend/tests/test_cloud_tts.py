from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from backend.app.core import ai_models, google_cloud_auth
from backend.app.services import cloud_tts, tts


class _FakeCloudClient:
    """Cloud Text-to-Speech のクライアントの代わり。受け取った要求を覚えておく。"""

    def __init__(self, chunks=(b"\x01\x00", b"\x02\x00"), error: Exception | None = None) -> None:
        self.chunks = chunks
        self.error = error
        self.stream_requests: list = []
        self.synthesize_kwargs: dict = {}

    def streaming_synthesize(self, requests):
        if self.error:
            raise self.error
        self.stream_requests = list(requests)
        return iter([SimpleNamespace(audio_content=chunk) for chunk in self.chunks])

    def synthesize_speech(self, **kwargs):
        if self.error:
            raise self.error
        self.synthesize_kwargs = kwargs
        return SimpleNamespace(audio_content=b"RIFF....WAVE")


class ResourceExhausted(Exception):
    code = 429


class DefaultCredentialsError(Exception):
    pass


class CloudTtsTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.settings_file = Path(directory.name) / "ai_models.json"
        settings_patcher = patch.object(ai_models, "AI_MODELS_FILE", self.settings_file)
        settings_patcher.start()
        self.addCleanup(settings_patcher.stop)
        env = patch.dict(os.environ, {"HINAMI_TTS_ENGINE": "cloud-tts", "GEMINI_TTS_STYLE": "", "CLOUD_TTS_MODEL": ""})
        env.start()
        self.addCleanup(env.stop)
        cloud_tts._synthesize_cached.cache_clear()
        self.addCleanup(cloud_tts._synthesize_cached.cache_clear)

    def use_client(self, client: _FakeCloudClient) -> _FakeCloudClient:
        patcher = patch.object(cloud_tts, "_client", return_value=client)
        patcher.start()
        self.addCleanup(patcher.stop)
        return client

    def test_engine_is_selected_by_environment(self) -> None:
        self.assertEqual(tts.speech_engine(), "cloud-tts")
        # 以前の値 gemini-api は Gemini TTS として受け付ける。
        for value, expected in (("", "gemini-tts"), ("gemini-api", "gemini-tts"), ("unknown", "gemini-tts")):
            with self.subTest(value=value), patch.dict(os.environ, {"HINAMI_TTS_ENGINE": value}):
                self.assertEqual(tts.speech_engine(), expected)

    def test_stream_sends_voice_model_pace_and_tone(self) -> None:
        client = self.use_client(_FakeCloudClient())

        audio = b"".join(tts.begin_speech_stream("今日はどうでしたか？", "Puck", "cheerful", "slow"))

        self.assertEqual(audio, b"\x01\x00\x02\x00")
        config = client.stream_requests[0].streaming_config
        self.assertEqual(
            (config.voice.name, config.voice.model_name, config.voice.language_code),
            ("Puck", cloud_tts.DEFAULT_CLOUD_TTS_MODEL, "ja-JP"),
        )
        self.assertEqual(config.streaming_audio_config.sample_rate_hertz, tts.STREAMING_TTS_SAMPLE_RATE)
        self.assertAlmostEqual(config.streaming_audio_config.speaking_rate, 0.85)
        # ペースは数値で渡すので、言葉の指示はトーンだけにする。
        self.assertEqual(client.stream_requests[1].input.prompt, "cheerful")
        self.assertEqual(client.stream_requests[1].input.text, "今日はどうでしたか？")

    def test_default_preferences_use_the_default_voice_without_prompt(self) -> None:
        client = self.use_client(_FakeCloudClient())
        with patch.dict(os.environ, {"GEMINI_TTS_VOICE": "Sulafat"}):
            b"".join(tts.begin_speech_stream("質問です。"))

        self.assertEqual(client.stream_requests[0].streaming_config.voice.name, "Sulafat")
        self.assertAlmostEqual(client.stream_requests[0].streaming_config.streaming_audio_config.speaking_rate, 1.0)
        self.assertEqual(client.stream_requests[1].input.prompt, "")

    def test_buffered_synthesis_returns_wav(self) -> None:
        client = self.use_client(_FakeCloudClient())

        audio = tts.synthesize_speech("質問です。", "Kore", "default", "fast")

        self.assertTrue(audio.startswith(b"RIFF"))
        self.assertEqual(client.synthesize_kwargs["voice"].name, "Kore")
        self.assertAlmostEqual(client.synthesize_kwargs["audio_config"].speaking_rate, 1.2)

    def test_speaking_rate_is_scaled_and_bounded(self) -> None:
        with patch.dict(os.environ, {"CLOUD_TTS_SPEAKING_RATE": "1.8"}):
            self.assertEqual(cloud_tts.cloud_speech_settings("fast")[1], 2.0)
        with patch.dict(os.environ, {"CLOUD_TTS_SPEAKING_RATE": "3"}):
            with self.assertRaisesRegex(tts.SpeechSynthesisError, "0.25〜2.0"):
                cloud_tts.cloud_speech_settings("normal")

    def test_quota_errors_become_rate_limit_errors(self) -> None:
        self.use_client(_FakeCloudClient(error=ResourceExhausted("quota exceeded")))

        with self.assertRaises(tts.SpeechRateLimitError):
            tts.begin_speech_stream("質問です。")

    def test_missing_credentials_are_explained(self) -> None:
        self.use_client(_FakeCloudClient(error=DefaultCredentialsError("no credentials")))

        with self.assertRaisesRegex(tts.SpeechSynthesisError, "application-default login"):
            tts.synthesize_speech("質問です。")

    def test_engine_and_model_chosen_on_screen_override_the_environment(self) -> None:
        ai_models.save_ai_models({"speech_engine": "gemini-tts"})
        self.assertEqual(tts.speech_engine(), "gemini-tts")
        self.assertEqual(ai_models.environment_speech_engine(), "cloud-tts")

        ai_models.save_ai_models({"speech_engine": "cloud-tts", "speech_model": "gemini-2.5-pro-tts"})
        self.assertEqual(cloud_tts.cloud_speech_settings("normal")[0], "gemini-2.5-pro-tts")

    def test_client_uses_the_shared_google_cloud_credentials(self) -> None:
        cloud_tts._cached_client.cache_clear()
        self.addCleanup(cloud_tts._cached_client.cache_clear)
        sentinel = object()
        with patch("backend.app.core.google_cloud_auth.google_cloud_credentials", return_value=sentinel), \
                patch("google.cloud.texttospeech.TextToSpeechClient") as client_class:
            cloud_tts._client()

        client_class.assert_called_once_with(credentials=sentinel)

    def test_quota_project_is_passed_without_a_service_account(self) -> None:
        cloud_tts._cached_client.cache_clear()
        self.addCleanup(cloud_tts._cached_client.cache_clear)
        with patch("backend.app.core.google_cloud_auth.google_cloud_credentials", return_value=None), \
                patch("backend.app.core.google_cloud_auth.quota_project", return_value="123456789012"), \
                patch("google.cloud.texttospeech.TextToSpeechClient") as client_class:
            cloud_tts._client()

        client_class.assert_called_once_with(credentials=None, client_options={"quota_project_id": "123456789012"})

    def test_adc_client_uses_the_environment_credentials(self) -> None:
        cloud_tts._cached_client.cache_clear()
        self.addCleanup(cloud_tts._cached_client.cache_clear)
        with patch("backend.app.core.google_cloud_auth.load_google_cloud_auth",
                      return_value=dict(google_cloud_auth.DEFAULT_GOOGLE_CLOUD_AUTH)), \
                patch("google.cloud.texttospeech.TextToSpeechClient") as client_class:
            cloud_tts._client()

        client_class.assert_called_once_with(credentials=None)

    def test_check_reports_the_step_that_failed(self) -> None:
        client = self.use_client(_FakeCloudClient())
        client.list_voices = lambda **_: (_ for _ in ()).throw(RuntimeError("API has not been used"))

        result = cloud_tts.check_cloud_tts()

        self.assertEqual((result["ok"], result["step"]), (False, "api"))
        self.assertIn("API has not been used", result["message"])

    def test_check_succeeds_without_synthesizing(self) -> None:
        client = self.use_client(_FakeCloudClient())
        client.list_voices = lambda **_: SimpleNamespace(voices=[1, 2, 3])

        result = cloud_tts.check_cloud_tts()

        self.assertTrue(result["ok"])
        self.assertIn("3件", result["message"])
        self.assertEqual(client.synthesize_kwargs, {})


if __name__ == "__main__":
    unittest.main()
