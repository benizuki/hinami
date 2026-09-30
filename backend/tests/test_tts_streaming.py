from __future__ import annotations

import base64
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from backend.app.core import ai_models
from backend.app.services import gemini, tts


def _audio_event(data: bytes) -> SimpleNamespace:
    return SimpleNamespace(
        event_type="step.delta",
        delta=SimpleNamespace(type="audio", data=base64.b64encode(data).decode("ascii")),
    )


class _FakeInteractions:
    def __init__(self, stream_events=None, output_audio: bytes = b"") -> None:
        self.calls: list[dict] = []
        self.stream_events = stream_events or []
        self.output_audio = output_audio
        self.closed = False

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            fake = self

            class _Stream:
                def __iter__(self):
                    return iter(fake.stream_events)

                def close(self):
                    fake.closed = True

            return _Stream()
        return SimpleNamespace(
            output_audio=SimpleNamespace(data=base64.b64encode(self.output_audio).decode("ascii"))
        )


class TtsStreamingTest(unittest.TestCase):
    def setUp(self) -> None:
        # 画面で選んだ読み上げの方式（実データの設定）に左右されないよう、空の場所へ向ける。
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        patcher = patch.object(ai_models, "AI_MODELS_FILE", Path(directory.name) / "ai_models.json")
        patcher.start()
        self.addCleanup(patcher.stop)
        environment = patch.dict("os.environ", {"HINAMI_TTS_ENGINE": ""})
        environment.start()
        self.addCleanup(environment.stop)

    def client(self, interactions: _FakeInteractions) -> SimpleNamespace:
        return SimpleNamespace(interactions=interactions)

    def test_stream_requests_pcm_and_yields_audio_as_it_arrives(self) -> None:
        interactions = _FakeInteractions(
            stream_events=[
                SimpleNamespace(event_type="step.start"),
                _audio_event(b"first"),
                SimpleNamespace(event_type="step.delta", delta=SimpleNamespace(type="text", data="")),
                _audio_event(b"second"),
            ]
        )
        with (
            patch.object(tts, "_client", return_value=self.client(interactions)),
            patch.dict(
                "os.environ",
                {
                    "GEMINI_TTS_MODEL": "gemini-3.8-flash-lite-tts",
                    "GEMINI_TTS_VOICE": "Sulafat",
                    "GEMINI_TTS_STYLE": "落ち着いて読み上げる",
                },
                clear=False,
            ),
        ):
            chunks = list(tts.begin_speech_stream("  質問です。  "))

        self.assertEqual(chunks, [b"first", b"second"])
        self.assertTrue(interactions.closed)
        request = interactions.calls[0]
        self.assertTrue(request["stream"])
        self.assertEqual(request["model"], "gemini-3.8-flash-lite-tts")
        self.assertEqual(
            request["response_format"],
            {"type": "audio", "mime_type": "audio/l16", "sample_rate": tts.STREAMING_TTS_SAMPLE_RATE},
        )
        self.assertEqual(
            request["generation_config"],
            {"speech_config": [{"voice": "Sulafat", "language": "ja-JP"}], "seed": tts.DEFAULT_TTS_SEED},
        )
        content = request["input"][0]["content"][0]
        self.assertEqual(content["text"], "質問です。")
        self.assertEqual(content["annotations"], [{"type": "speech_metadata", "style": "落ち着いて読み上げる"}])

    def test_stream_fails_before_responding_when_no_audio_arrives(self) -> None:
        interactions = _FakeInteractions(stream_events=[SimpleNamespace(event_type="step.start")])
        with patch.object(tts, "_client", return_value=self.client(interactions)):
            with self.assertRaisesRegex(tts.SpeechSynthesisError, "音声データを取得できませんでした"):
                tts.begin_speech_stream("質問です。")

    def test_buffered_synthesis_returns_wav_and_is_cached(self) -> None:
        interactions = _FakeInteractions(output_audio=b"RIFF....WAVE")
        tts._synthesize_cached.cache_clear()
        self.addCleanup(tts._synthesize_cached.cache_clear)
        with patch.object(tts, "_client", return_value=self.client(interactions)):
            first = tts.synthesize_speech("質問です。")
            second = tts.synthesize_speech(" 質問です。 ")

        self.assertEqual(first, b"RIFF....WAVE")
        self.assertEqual(second, first)
        self.assertEqual(len(interactions.calls), 1)
        self.assertEqual(interactions.calls[0]["response_format"], {"type": "audio"})

    def test_empty_style_sends_no_annotation(self) -> None:
        interactions = _FakeInteractions(stream_events=[_audio_event(b"a")])
        with (
            patch.object(tts, "_client", return_value=self.client(interactions)),
            patch.dict("os.environ", {"GEMINI_TTS_STYLE": ""}, clear=False),
        ):
            list(tts.begin_speech_stream("質問です。"))

        self.assertNotIn("annotations", interactions.calls[0]["input"][0]["content"][0])

    def test_stream_rejects_empty_text_before_opening_client(self) -> None:
        with self.assertRaisesRegex(tts.SpeechSynthesisError, "空です"):
            tts.begin_speech_stream("   ")

    def test_language_is_sent_and_can_be_disabled(self) -> None:
        with patch.dict("os.environ", {"GEMINI_TTS_LANGUAGE": ""}):
            speaker = tts._interaction_request("文", "m", "Kore", "", None)["generation_config"]["speech_config"][0]
        self.assertEqual(speaker, {"voice": "Kore"})

    def test_rate_limit_event_is_reported_with_its_reason(self) -> None:
        # 上限に達するとストリームは音声の代わりにerrorイベントを返す。理由を握りつぶさない。
        events = [
            SimpleNamespace(event_type="interaction.created"),
            SimpleNamespace(
                event_type="error",
                error=SimpleNamespace(code="rate_limit_exceeded", message="limit: 100 requests per day"),
            ),
        ]
        interactions = SimpleNamespace(create=lambda **_: iter(events))
        with patch.object(tts, "_client", return_value=SimpleNamespace(interactions=interactions)):
            with self.assertRaisesRegex(tts.SpeechRateLimitError, "100 requests per day"):
                tts.begin_speech_stream("質問です。")

    def test_other_error_events_are_reported(self) -> None:
        events = [SimpleNamespace(event_type="error", error={"code": "invalid_argument", "message": "bad voice"})]
        interactions = SimpleNamespace(create=lambda **_: iter(events))
        with patch.object(tts, "_client", return_value=SimpleNamespace(interactions=interactions)):
            with self.assertRaisesRegex(tts.SpeechSynthesisError, "invalid_argument bad voice"):
                tts.begin_speech_stream("質問です。")

    def test_no_speaking_style_is_sent_by_default(self) -> None:
        # 話し方の指示は声の調子を引っ張るため、既定では送らず素の読み上げにする。
        with patch.dict("os.environ", {}, clear=False) as environ:
            environ.pop("GEMINI_TTS_STYLE", None)
            text, model, voice, style = tts._speech_settings("質問です。")
        content = tts._interaction_request(text, model, voice, style, None)["input"][0]["content"][0]
        self.assertEqual(style, "")
        self.assertNotIn("annotations", content)

    def test_seed_is_fixed_by_default_and_can_be_changed_or_disabled(self) -> None:
        # 生成型の読み上げは呼び出しごとに声が揺れるため、毎回同じシードで生成する。
        with patch.dict("os.environ", {}, clear=False) as environ:
            environ.pop("GEMINI_TTS_SEED", None)
            self.assertEqual(tts._speech_seed(), tts.DEFAULT_TTS_SEED)
        with patch.dict("os.environ", {"GEMINI_TTS_SEED": "42"}):
            self.assertEqual(tts._speech_seed(), 42)
        with patch.dict("os.environ", {"GEMINI_TTS_SEED": ""}):
            self.assertIsNone(tts._speech_seed())
            self.assertNotIn("seed", tts._interaction_request("文", "m", "v", "", None)["generation_config"])
        with patch.dict("os.environ", {"GEMINI_TTS_SEED": "abc"}):
            self.assertEqual(tts._speech_seed(), tts.DEFAULT_TTS_SEED)

    def test_missing_api_key_is_reported_as_a_speech_error(self) -> None:
        # 画面から登録したキーが実データにあっても読まないよう、保存先も空の場所へ向ける。
        with TemporaryDirectory() as directory, patch.dict("os.environ", {"GEMINI_API_KEY": ""}, clear=False), \
                patch.object(gemini, "GEMINI_API_KEY_FILE", Path(directory) / "gemini_api_key"):
            with self.assertRaisesRegex(tts.SpeechSynthesisError, "GEMINI_API_KEY"):
                tts.begin_speech_stream("質問です。")


if __name__ == "__main__":
    unittest.main()
