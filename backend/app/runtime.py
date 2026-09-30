"""プロセス全体で共有する実行時の状態（保存先とストア）。

ルーターは `runtime.store` を呼び出しのたびに属性として参照する。
テストはこの属性を差し替えて一時DBを使う（`from .runtime import store` では差し替えが効かない）。
"""

from __future__ import annotations

import os
from pathlib import Path

from .core.paths import RUNTIME_DATA_DIR
from .storage.sqlite_store import HinamiSQLiteStore

SQLITE_STORE_PATH = Path(
    os.getenv(
        "HINAMI_SQLITE_PATH",
        str(RUNTIME_DATA_DIR / "hinami.sqlite"),
    )
)
SQLITE_BACKUP_DIR = Path(
    os.getenv(
        "HINAMI_SQLITE_BACKUP_DIR",
        str(RUNTIME_DATA_DIR / "backups"),
    )
)

store = HinamiSQLiteStore(SQLITE_STORE_PATH)


def is_production() -> bool:
    return os.getenv("APP_ENV", "").strip().lower() in {"prod", "production"}
