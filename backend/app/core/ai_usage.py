from __future__ import annotations

import os
from collections import deque
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, NamedTuple

# AI呼び出しを伴うエンドポイントと、利用状況の画面に出す機能名。
# ここに無いパスは記録も制限もしない。
AI_ENDPOINT_FEATURES: dict[str, str] = {
    "/api/speech/transcribe": "音声の文字起こし",
    "/api/speech": "読み上げ",
    "/api/speech/stream": "読み上げ",
    "/api/work-journal/turn": "記録の対話",
    "/api/work-journal/attachment-insights": "記録の資料解析",
    "/api/work-journal/email-summary": "記録のメール要約",
    "/api/work-journals/organization/summary": "チームの記録のまとめ",
    "/api/work-journals/organization/work-map": "記録の見取り図",
}
# 利用記録には機能名をそのまま保存している。名前を変えた機能は、過去の記録も新しい名前で集計する。
LEGACY_FEATURE_LABELS: dict[str, str] = {
    "業務日報": "記録の対話",
    "業務日報の資料解析": "記録の資料解析",
    "業務日報のメール要約": "記録のメール要約",
    "組織サマリー": "チームの記録のまとめ",
    "業務の棚卸し": "記録の見取り図",
}


def current_feature_label(label: str) -> str:
    return LEGACY_FEATURE_LABELS.get(label, label)

DEFAULT_RATE_PER_MINUTE = 12
DEFAULT_RATE_PER_DAY = 300
DEFAULT_RETENTION_DAYS = 90


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    # 0以下は「制限なし」として扱う。運用で一時的に外せるようにする。
    return value if value > 0 else 0


def rate_limit_per_minute() -> int:
    return _positive_int("HINAMI_AI_RATE_PER_MINUTE", DEFAULT_RATE_PER_MINUTE)


def rate_limit_per_day() -> int:
    return _positive_int("HINAMI_AI_RATE_PER_DAY", DEFAULT_RATE_PER_DAY)


def usage_retention_days() -> int:
    return _positive_int("HINAMI_AI_USAGE_RETENTION_DAYS", DEFAULT_RETENTION_DAYS)


def feature_for_path(path: str) -> str:
    return AI_ENDPOINT_FEATURES.get(path, "")


class BurstLimiter:
    """直近1分の呼び出し回数を利用者ごとに数える。

    連打を止めるためのもので、プロセス内で完結する。1日あたりの上限は
    プロセスをまたいで数える必要があるため、記録テーブル側で判定する。
    """

    def __init__(self, window_seconds: int = 60) -> None:
        self.window = timedelta(seconds=window_seconds)
        self._events: dict[tuple[str, str], deque[datetime]] = {}
        self._lock = Lock()

    def _prune(self, key: tuple[str, str], now: datetime) -> deque[datetime]:
        events = self._events.setdefault(key, deque())
        threshold = now - self.window
        while events and events[0] < threshold:
            events.popleft()
        if not events:
            self._events.pop(key, None)
            return deque()
        return events

    def retry_after_seconds(
        self,
        tenant_id: str,
        user_email: str,
        limit: int,
        now: datetime | None = None,
    ) -> int:
        """上限に達していれば次に空くまでの秒数を返す。空いていれば0。"""
        if limit <= 0:
            return 0
        moment = now or datetime.now(timezone.utc)
        key = (tenant_id, user_email)
        with self._lock:
            events = self._prune(key, moment)
            if len(events) < limit:
                return 0
            wait = (events[0] + self.window) - moment
        return max(1, int(wait.total_seconds()) + 1)

    def try_acquire(
        self,
        tenant_id: str,
        user_email: str,
        limit: int,
        now: datetime | None = None,
    ) -> int:
        """空いていれば1回分を消費して0を返す。埋まっていれば待ち秒数を返す。

        確認と記録を1つのロックにまとめる。別々に呼ぶと、その間に届いた同時
        リクエストが揃って上限を通り抜けてしまう。
        """
        if limit <= 0:
            return 0
        moment = now or datetime.now(timezone.utc)
        key = (tenant_id, user_email)
        with self._lock:
            events = self._prune(key, moment)
            if len(events) >= limit:
                wait = (events[0] + self.window) - moment
                return max(1, int(wait.total_seconds()) + 1)
            self._events.setdefault(key, events).append(moment)
        return 0

    def record(self, tenant_id: str, user_email: str, now: datetime | None = None) -> None:
        moment = now or datetime.now(timezone.utc)
        key = (tenant_id, user_email)
        with self._lock:
            events = self._events.setdefault(key, deque())
            events.append(moment)
            threshold = moment - self.window
            while events and events[0] < threshold:
                events.popleft()

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


def start_of_utc_day(now: datetime | None = None) -> str:
    moment = now or datetime.now(timezone.utc)
    return moment.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def retention_cutoff(now: datetime | None = None) -> str:
    moment = now or datetime.now(timezone.utc)
    return (moment - timedelta(days=usage_retention_days())).isoformat()


class TokenUsage(NamedTuple):
    prompt: int
    output: int
    total: int


# リクエスト単位のトークン集計。ミドルウェアが器を用意し、LLM呼び出し側が積む。
# run_in_threadpoolはコンテキストを複製するため、可変オブジェクトを共有して受け渡す。
_token_bucket: ContextVar[list[TokenUsage] | None] = ContextVar("ai_token_usage", default=None)


def begin_token_capture() -> list[TokenUsage]:
    bucket: list[TokenUsage] = []
    _token_bucket.set(bucket)
    return bucket


def record_model_tokens(usage_metadata: Any) -> None:
    """Geminiのusage_metadataを1回分として積む。器が無ければ何もしない。"""
    bucket = _token_bucket.get()
    if bucket is None or usage_metadata is None:
        return

    def count(name: str) -> int:
        value = getattr(usage_metadata, name, 0)
        return int(value) if isinstance(value, (int, float)) else 0

    # 思考トークンは課金対象なので出力側へ含める。
    output = count("candidates_token_count") + count("thoughts_token_count")
    prompt = count("prompt_token_count")
    total = count("total_token_count") or prompt + output
    if prompt or output or total:
        bucket.append(TokenUsage(prompt=prompt, output=output, total=total))


def summarize_tokens(bucket: list[TokenUsage] | None) -> TokenUsage:
    if not bucket:
        return TokenUsage(0, 0, 0)
    return TokenUsage(
        prompt=sum(item.prompt for item in bucket),
        output=sum(item.output for item in bucket),
        total=sum(item.total for item in bucket),
    )
