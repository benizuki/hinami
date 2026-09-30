"""Serve the pre-built Hinami frontend and FastAPI backend."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    local_uvicorn = root / ".venv" / "bin" / "uvicorn"
    uvicorn = str(local_uvicorn) if local_uvicorn.is_file() else shutil.which("uvicorn")
    if uvicorn is None:
        raise SystemExit("uvicornが見つかりません。バックエンド依存関係をインストールしてください。")

    host = os.getenv("HINAMI_API_HOST", "127.0.0.1")
    port = os.getenv("HINAMI_API_PORT", "8000")
    os.environ["HINAMI_API_HOST"] = host
    args = [uvicorn, "backend.app.main:app", "--host", host, "--port", port]
    if os.getenv("HINAMI_RELOAD", "").lower() in {"1", "true", "yes"}:
        args.append("--reload")

    os.chdir(root)
    os.execv(uvicorn, args)


if __name__ == "__main__":
    main()
