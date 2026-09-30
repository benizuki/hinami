from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import runtime
from backend.app.api import journal_assist_api, middleware
from backend.app.core import google_integrations
from backend.app.core.ai_usage import (
    AI_ENDPOINT_FEATURES,
    BurstLimiter,
    TokenUsage,
    begin_token_capture,
    current_feature_label,
    feature_for_path,
    rate_limit_per_day,
    rate_limit_per_minute,
    record_model_tokens,
    summarize_tokens,
)
from backend.app.schemas import WorkJournalEmailContext
from backend.app.services.gemini import GeminiError

# メール要約は既定値だけで受け付けるAI機能なので、記録と制限の確認に使う。
EMAIL_SUMMARY_PAYLOAD: dict[str, object] = {}


class UsageMetadata:
    """Geminiのusage_metadataを模した最小の入れ物。"""

    def __init__(self, prompt=0, candidates=0, thoughts=0, total=0) -> None:
        self.prompt_token_count = prompt
        self.candidates_token_count = candidates
        self.thoughts_token_count = thoughts
        self.total_token_count = total


class TokenCaptureTest(unittest.TestCase):
    def test_thinking_tokens_are_counted_as_output(self) -> None:
        """思考トークンも課金対象なので出力側へ含める。"""
        bucket = begin_token_capture()
        record_model_tokens(UsageMetadata(prompt=1000, candidates=200, thoughts=300, total=1500))

        self.assertEqual(summarize_tokens(bucket), TokenUsage(prompt=1000, output=500, total=1500))

    def test_multiple_calls_in_one_request_are_summed(self) -> None:
        bucket = begin_token_capture()
        record_model_tokens(UsageMetadata(prompt=100, candidates=10, total=110))
        record_model_tokens(UsageMetadata(prompt=200, candidates=20, total=220))

        self.assertEqual(summarize_tokens(bucket), TokenUsage(prompt=300, output=30, total=330))

    def test_total_falls_back_to_the_sum_when_absent(self) -> None:
        bucket = begin_token_capture()
        record_model_tokens(UsageMetadata(prompt=40, candidates=5))

        self.assertEqual(summarize_tokens(bucket).total, 45)

    def test_missing_metadata_is_ignored(self) -> None:
        bucket = begin_token_capture()
        record_model_tokens(None)
        record_model_tokens(UsageMetadata())

        self.assertEqual(summarize_tokens(bucket), TokenUsage(0, 0, 0))


class BurstLimiterTest(unittest.TestCase):
    def test_allows_calls_up_to_the_limit(self) -> None:
        limiter = BurstLimiter()
        now = datetime(2026, 8, 14, 9, 0, tzinfo=timezone.utc)

        for _ in range(3):
            self.assertEqual(limiter.retry_after_seconds("default", "a@x.com", 3, now), 0)
            limiter.record("default", "a@x.com", now)

        self.assertGreater(limiter.retry_after_seconds("default", "a@x.com", 3, now), 0)

    def test_window_slides_so_calls_recover(self) -> None:
        limiter = BurstLimiter()
        now = datetime(2026, 8, 14, 9, 0, tzinfo=timezone.utc)
        for _ in range(2):
            limiter.record("default", "a@x.com", now)

        self.assertGreater(limiter.retry_after_seconds("default", "a@x.com", 2, now), 0)
        later = now + timedelta(seconds=61)
        self.assertEqual(limiter.retry_after_seconds("default", "a@x.com", 2, later), 0)

    def test_users_and_tenants_are_counted_separately(self) -> None:
        limiter = BurstLimiter()
        now = datetime(2026, 8, 14, 9, 0, tzinfo=timezone.utc)
        limiter.record("default", "a@x.com", now)

        self.assertEqual(limiter.retry_after_seconds("default", "b@x.com", 1, now), 0)
        self.assertEqual(limiter.retry_after_seconds("east", "a@x.com", 1, now), 0)
        self.assertGreater(limiter.retry_after_seconds("default", "a@x.com", 1, now), 0)

    def test_zero_limit_means_unlimited(self) -> None:
        limiter = BurstLimiter()
        now = datetime(2026, 8, 14, 9, 0, tzinfo=timezone.utc)
        for _ in range(50):
            limiter.record("default", "a@x.com", now)

        self.assertEqual(limiter.retry_after_seconds("default", "a@x.com", 0, now), 0)


class RateLimitSettingsTest(unittest.TestCase):
    def test_defaults_apply_when_unset(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HINAMI_AI_RATE_PER_MINUTE", None)
            os.environ.pop("HINAMI_AI_RATE_PER_DAY", None)
            self.assertEqual(rate_limit_per_minute(), 12)
            self.assertEqual(rate_limit_per_day(), 300)

    def test_invalid_values_fall_back_to_defaults(self) -> None:
        with patch.dict(os.environ, {"HINAMI_AI_RATE_PER_MINUTE": "abc"}):
            self.assertEqual(rate_limit_per_minute(), 12)

    def test_zero_disables_the_limit(self) -> None:
        with patch.dict(os.environ, {"HINAMI_AI_RATE_PER_DAY": "0"}):
            self.assertEqual(rate_limit_per_day(), 0)

    def test_only_ai_endpoints_are_measured(self) -> None:
        self.assertEqual(feature_for_path("/api/work-journal/turn"), "記録の対話")
        self.assertEqual(feature_for_path("/api/work-journals/organization/work-map"), "記録の見取り図")
        # 名前を変える前の記録も、新しい名前で集計する。
        self.assertEqual(current_feature_label("業務の棚卸し"), "記録の見取り図")
        self.assertEqual(feature_for_path("/api/org-units"), "")
        self.assertEqual(feature_for_path("/api/work-journals"), "")
        for path in AI_ENDPOINT_FEATURES:
            self.assertTrue(path.startswith("/api/"), path)


class AiUsageEndpointTest(unittest.TestCase):
    """認証を無効化した状態で、記録と制限が働くことを確かめる。"""

    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        patcher = patch.dict(os.environ, {
            "GOOGLE_OAUTH_CLIENT_ID": "",
            "HINAMI_API_HOST": "127.0.0.1",
            "HINAMI_DATA_DIR": self.directory.name,
            "HINAMI_AUTH_DIR": str(Path(self.directory.name) / "auth"),
        })
        patcher.start()
        self.addCleanup(patcher.stop)
        from backend.app import main
        from backend.app.storage.sqlite_store import HinamiSQLiteStore

        self.main = main
        # モジュール読み込み時に実データのパスで作られるため、必ず差し替える。
        store_patcher = patch.object(runtime, "store", HinamiSQLiteStore(Path(self.directory.name) / "hinami.sqlite"))
        store_patcher.start()
        self.addCleanup(store_patcher.stop)
        # メール要約はGmail連携の設定を読む。実データの設定に左右されないよう空の場所へ向ける。
        settings_patcher = patch.object(
            google_integrations, "GOOGLE_INTEGRATIONS_FILE", Path(self.directory.name) / "google_integrations.json"
        )
        settings_patcher.start()
        self.addCleanup(settings_patcher.stop)
        middleware._ai_burst_limiter.reset()
        self.addCleanup(middleware._ai_burst_limiter.reset)
        self.client = TestClient(main.app, raise_server_exceptions=False)

    def test_usage_is_recorded_for_ai_endpoints(self) -> None:
        with patch.object(journal_assist_api, "summarize_work_journal_emails") as generate:
            generate.return_value = WorkJournalEmailContext()
            self.client.post("/api/work-journal/email-summary", json=EMAIL_SUMMARY_PAYLOAD)

        summary = runtime.store.summarize_ai_usage(
            tenant_id="default", date_from="2000-01-01", date_to="2999-01-01"
        )
        self.assertEqual([row[0] for row in summary["by_feature"]], ["記録のメール要約"])

    def test_non_ai_endpoints_are_not_recorded(self) -> None:
        self.client.get("/api/org-units")

        summary = runtime.store.summarize_ai_usage(
            tenant_id="default", date_from="2000-01-01", date_to="2999-01-01"
        )
        self.assertEqual(summary["by_feature"], [])

    def test_burst_limit_returns_429_with_retry_after(self) -> None:
        with patch.dict(os.environ, {"HINAMI_AI_RATE_PER_MINUTE": "2"}), \
                patch.object(journal_assist_api, "summarize_work_journal_emails") as generate:
            generate.return_value = WorkJournalEmailContext()
            payload = EMAIL_SUMMARY_PAYLOAD
            statuses = [
                self.client.post("/api/work-journal/email-summary", json=payload).status_code
                for _ in range(3)
            ]
            blocked = self.client.post("/api/work-journal/email-summary", json=payload)

        self.assertEqual(statuses[:2], [200, 200])
        self.assertEqual(blocked.status_code, 429)
        self.assertIn("Retry-After", blocked.headers)
        self.assertGreater(int(blocked.headers["Retry-After"]), 0)

    def test_daily_limit_blocks_further_calls(self) -> None:
        with patch.dict(os.environ, {"HINAMI_AI_RATE_PER_DAY": "1", "HINAMI_AI_RATE_PER_MINUTE": "0"}), \
                patch.object(journal_assist_api, "summarize_work_journal_emails") as generate:
            generate.return_value = WorkJournalEmailContext()
            payload = EMAIL_SUMMARY_PAYLOAD
            first = self.client.post("/api/work-journal/email-summary", json=payload)
            second = self.client.post("/api/work-journal/email-summary", json=payload)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertIn("1日あたりの上限", second.json()["detail"])

    def test_rate_limited_calls_do_not_count_toward_the_daily_budget(self) -> None:
        """制限で弾いた分まで数えると、いつまでも解除されなくなる。"""
        with patch.dict(os.environ, {"HINAMI_AI_RATE_PER_MINUTE": "1"}), \
                patch.object(journal_assist_api, "summarize_work_journal_emails") as generate:
            generate.return_value = WorkJournalEmailContext()
            payload = EMAIL_SUMMARY_PAYLOAD
            self.client.post("/api/work-journal/email-summary", json=payload)
            self.client.post("/api/work-journal/email-summary", json=payload)

        counted = runtime.store.count_ai_usage_since(
            tenant_id="default", user_email=middleware.LOCAL_USAGE_USER, since="2000-01-01"
        )
        self.assertEqual(counted, 1)

    def test_tokens_recorded_inside_the_threadpool_reach_the_middleware(self) -> None:
        """記録はミドルウェア、計上はワーカースレッド。ここが繋がらないと常に0になる。"""
        def generate(_request):
            record_model_tokens(UsageMetadata(prompt=900, candidates=120, thoughts=80, total=1100))
            return WorkJournalEmailContext()

        with patch.object(journal_assist_api, "summarize_work_journal_emails", side_effect=generate):
            self.client.post("/api/work-journal/email-summary", json=EMAIL_SUMMARY_PAYLOAD)

        report = self.client.get("/api/ai-usage").json()
        self.assertEqual(report["total_tokens"], 1100)
        self.assertEqual(report["by_user"][0]["prompt_tokens"], 900)
        self.assertEqual(report["by_user"][0]["output_tokens"], 200)
        self.assertEqual(report["by_feature"][0]["total_tokens"], 1100)

    def test_report_exposes_totals_and_limits(self) -> None:
        with patch.object(journal_assist_api, "summarize_work_journal_emails") as generate:
            generate.return_value = WorkJournalEmailContext()
            self.client.post("/api/work-journal/email-summary", json=EMAIL_SUMMARY_PAYLOAD)

        report = self.client.get("/api/ai-usage").json()

        self.assertEqual(report["total_calls"], 1)
        self.assertEqual(report["used_today"], 1)
        self.assertEqual([row["feature"] for row in report["by_feature"]], ["記録のメール要約"])
        self.assertEqual(len(report["by_day"]), 1)
        self.assertGreater(report["rate_limit_per_day"], 0)

    def test_records_under_old_feature_names_are_merged_into_the_new_names(self) -> None:
        # 機能名を「業務日報…」から変えたため、以前の記録も新しい名前で合算して見せる。
        with patch.object(journal_assist_api, "summarize_work_journal_emails") as generate:
            generate.return_value = WorkJournalEmailContext()
            self.client.post("/api/work-journal/email-summary", json=EMAIL_SUMMARY_PAYLOAD)
        runtime.store.record_ai_usage(
            tenant_id="default",
            user_email=middleware.LOCAL_USAGE_USER,
            feature="業務日報のメール要約",
            endpoint="/api/work-journal/email-summary",
            outcome="ok",
            duration_ms=10,
            occurred_at=datetime.now(timezone.utc).isoformat(),
            total_tokens=5,
        )

        report = self.client.get("/api/ai-usage").json()

        self.assertEqual([row["feature"] for row in report["by_feature"]], ["記録のメール要約"])
        self.assertEqual(report["by_feature"][0]["calls"], 2)

    def test_failed_calls_are_recorded_as_errors(self) -> None:
        with patch.object(journal_assist_api, "summarize_work_journal_emails") as generate:
            generate.side_effect = GeminiError("Geminiに接続できません")
            response = self.client.post("/api/work-journal/email-summary", json=EMAIL_SUMMARY_PAYLOAD)

        self.assertEqual(response.status_code, 503)
        report = self.client.get("/api/ai-usage").json()
        self.assertEqual(report["by_user"][0]["errors"], 1)


if __name__ == "__main__":
    unittest.main()
