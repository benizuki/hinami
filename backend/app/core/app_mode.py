"""動作モード。画面の言葉づかいを「日記寄り」か「業務より」で切り替える、システム全体で1つの設定。

保存するのは表示の言葉づかいだけで、日報のデータ構造や分析には関わらない。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

from .paths import RUNTIME_DATA_DIR

APP_MODES = ("diary", "work")
DEFAULT_APP_MODE = "diary"
APP_MODE_FILE = RUNTIME_DATA_DIR / "settings" / "app_mode.json"
logger = logging.getLogger(__name__)


def load_app_mode() -> str:
    try:
        raw = json.loads(APP_MODE_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return DEFAULT_APP_MODE
    except (OSError, json.JSONDecodeError):
        # 壊れた設定で画面ごと止めない。既定で動かし、ログに残す。
        logger.warning("App mode setting could not be read; using the default.", exc_info=True)
        return DEFAULT_APP_MODE
    mode = raw.get("mode") if isinstance(raw, dict) else None
    return mode if mode in APP_MODES else DEFAULT_APP_MODE


def save_app_mode(mode: str) -> str:
    if mode not in APP_MODES:
        raise ValueError(f"unknown app mode: {mode}")
    path = APP_MODE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    # 書き終えてから置き換える。読み手が書きかけの設定を読むことはない。
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=".app_mode.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"mode": mode}, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
    return mode
