from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import runtime
from backend.app.api import speech_api
from backend.app.services import tts
from backend.app.storage.sqlite_store import HinamiSQLiteStore


def user_row(email: str, role: str, tenant_role: str) -> dict:
    return {
        "email": email,
        "name": email,
        "role": role,
        "enabled": True,
        "tenant_memberships": [{"tenant_id": "default", "role": tenant_role}],
    }


class SpeechStyleTest(unittest.TestCase):
    def test_defaults_follow_the_system_setting(self) -> None:
        self.assertIsNone(tts.speech_style("default", "normal"))

    def test_tone_and_pace_become_short_english_words(self) -> None:
        self.assertEqual(tts.speech_style("cheerful", "normal"), "cheerful")
        self.assertEqual(tts.speech_style("default", "slow"), "slow")
        self.assertEqual(tts.speech_style("calm", "fast"), "calm, fast")

    def test_explicit_voice_and_style_override_the_environment(self) -> None:
        with patch.dict(os.environ, {"GEMINI_TTS_VOICE": "Sulafat", "GEMINI_TTS_STYLE": "warm"}):
            self.assertEqual(tts._speech_settings("文です。")[2:], ("Sulafat", "warm"))
            self.assertEqual(tts._speech_settings("文です。", "Puck", "cheerful")[2:], ("Puck", "cheerful"))


class SpeechPreferencesApiTest(unittest.TestCase):
    """読み上げの好みは本人ごとに保存され、読み上げに使われる。"""

    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        auth_dir = root / "auth"
        auth_dir.mkdir(parents=True)
        (auth_dir / "tenant_master.json").write_text(
            json.dumps([{"id": "default", "name": "既定テナント", "enabled": True}], ensure_ascii=False),
            encoding="utf-8",
        )
        (auth_dir / "user_master.json").write_text(
            json.dumps([
                user_row("member@example.com", "user", "user"),
                user_row("watcher@example.com", "viewer", "viewer"),
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
            (runtime, "store", HinamiSQLiteStore(root / "hinami.sqlite")),
        ):
            patcher = patch.object(target, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        # 実際のGemini APIには問い合わせない。受け取った声と話し方だけを確かめる。
        synthesize = patch.object(speech_api, "synthesize_speech", return_value=b"RIFF")
        self.synthesize = synthesize.start()
        self.addCleanup(synthesize.stop)
        self.client = TestClient(main.app, raise_server_exceptions=False)
        self.tokens = {user["email"]: issue_app_token(user) for user in list_user_master_entries()}

    def headers(self, email: str = "member@example.com") -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tokens[email]}", "Host": "127.0.0.1:8000"}

    def test_defaults_and_choices_are_returned(self) -> None:
        body = self.client.get("/api/user-preferences/speech", headers=self.headers()).json()

        self.assertEqual((body["voice"], body["tone"], body["pace"]), ("", "default", "normal"))
        self.assertEqual(len(body["voices"]), len(tts.VOICE_CATALOG))
        self.assertEqual([tone["id"] for tone in body["tones"]], list(tts.TONE_STYLES))
        self.assertEqual([pace["id"] for pace in body["paces"]], list(tts.PACE_STYLES))

    def test_saved_preferences_are_used_for_speech(self) -> None:
        saved = self.client.put(
            "/api/user-preferences/speech",
            json={"voice": "Puck", "tone": "cheerful", "pace": "slow"},
            headers=self.headers(),
        )
        self.assertEqual(saved.status_code, 200)

        response = self.client.post("/api/speech", json={"text": "こんにちは。"}, headers=self.headers())

        self.assertEqual(response.status_code, 200)
        self.synthesize.assert_called_once_with("こんにちは。", "Puck", "cheerful", "slow")

    def test_preview_uses_the_given_preferences_without_saving(self) -> None:
        response = self.client.post(
            "/api/speech",
            json={"text": "試聴です。", "preferences": {"voice": "Kore", "tone": "calm", "pace": "fast"}},
            headers=self.headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.synthesize.assert_called_once_with("試聴です。", "Kore", "calm", "fast")
        stored = self.client.get("/api/user-preferences/speech", headers=self.headers()).json()
        self.assertEqual(stored["voice"], "")

    def test_default_preferences_leave_voice_and_style_to_the_system(self) -> None:
        self.client.post("/api/speech", json={"text": "こんにちは。"}, headers=self.headers())

        self.synthesize.assert_called_once_with("こんにちは。", None, "default", "normal")

    def test_rate_limit_is_returned_as_429(self) -> None:
        self.synthesize.side_effect = tts.SpeechRateLimitError("Gemini TTS の利用上限に達しました。")

        response = self.client.post("/api/speech", json={"text": "文。"}, headers=self.headers())

        self.assertEqual(response.status_code, 429)
        self.assertIn("利用上限", response.json()["detail"])

    def test_unknown_voice_is_rejected(self) -> None:
        for request in (
            lambda: self.client.put(
                "/api/user-preferences/speech", json={"voice": "Nobody"}, headers=self.headers()
            ),
            lambda: self.client.post(
                "/api/speech", json={"text": "文。", "preferences": {"voice": "Nobody"}}, headers=self.headers()
            ),
        ):
            self.assertEqual(request().status_code, 422)
        self.synthesize.assert_not_called()

    def test_preferences_are_kept_per_user_and_viewers_can_save_their_own(self) -> None:
        self.client.put("/api/user-preferences/speech", json={"voice": "Puck"}, headers=self.headers())
        response = self.client.put(
            "/api/user-preferences/speech",
            json={"voice": "Kore", "pace": "slow"},
            headers=self.headers("watcher@example.com"),
        )

        self.assertEqual(response.status_code, 200)
        member = self.client.get("/api/user-preferences/speech", headers=self.headers()).json()
        watcher = self.client.get("/api/user-preferences/speech", headers=self.headers("watcher@example.com")).json()
        self.assertEqual((member["voice"], member["pace"]), ("Puck", "normal"))
        self.assertEqual((watcher["voice"], watcher["pace"]), ("Kore", "slow"))


if __name__ == "__main__":
    unittest.main()
