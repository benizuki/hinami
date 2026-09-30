"""Google連携（カレンダー・Meet・Gmail・Drive）を機能ごとに有効・無効にする設定。

Google API はブラウザが利用者本人のトークンで直接呼ぶ。そのため無効化は、
画面がその機能のスコープを要求しないことと、サーバー側で扱うAPI（メール要約）を
止めることで効かせる。設定はシステム全体で1つ。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path

from .paths import RUNTIME_DATA_DIR

GOOGLE_INTEGRATION_FEATURES = ("calendar", "meet", "gmail", "drive")
GOOGLE_INTEGRATIONS_FILE = RUNTIME_DATA_DIR / "settings" / "google_integrations.json"
logger = logging.getLogger(__name__)


def _normalized(values: Mapping[str, object]) -> dict[str, bool]:
    # 未設定の機能は有効として扱う。設定を作る前から従来どおり動かすため。
    settings = {feature: bool(values.get(feature, True)) for feature in GOOGLE_INTEGRATION_FEATURES}
    # Meetの実績はカレンダーの予定にある会議コードから辿るため、カレンダー無しでは使えない。
    settings["meet"] = settings["meet"] and settings["calendar"]
    return settings


def load_google_integrations() -> dict[str, bool]:
    try:
        raw = json.loads(GOOGLE_INTEGRATIONS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raw = {}
    except (OSError, json.JSONDecodeError):
        # 壊れた設定で画面ごと止めない。既定（すべて有効）で動かし、ログに残す。
        logger.warning("Google integration settings could not be read; using defaults.", exc_info=True)
        raw = {}
    return _normalized(raw if isinstance(raw, dict) else {})


def google_integration_enabled(feature: str) -> bool:
    return load_google_integrations().get(feature, False)


def save_google_integrations(values: Mapping[str, object]) -> dict[str, bool]:
    settings = _normalized(values)
    path = GOOGLE_INTEGRATIONS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    # 書き終えてから置き換える。読み手が書きかけの設定を読むことはない。
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=".google_integrations.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(settings, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
    return settings
