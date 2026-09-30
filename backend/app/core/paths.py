from __future__ import annotations

import os
from pathlib import Path


REPO_ROOT_DIR = Path(__file__).resolve().parents[3]
LOCAL_DATA_DIR = REPO_ROOT_DIR / "backend" / "app" / "data"
RUNTIME_DATA_DIR = Path(os.getenv("HINAMI_DATA_DIR", str(LOCAL_DATA_DIR)))
