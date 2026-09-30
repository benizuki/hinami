"""ビルド済みのフロントエンドを配信する。全パスを受けるため、必ず最後に登録する。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..core.paths import REPO_ROOT_DIR
from ..runtime import is_production

router = APIRouter()


FRONTEND_DIST_DIR = REPO_ROOT_DIR / "frontend" / "dist"


BLOCKED_SPA_PATH_PREFIXES = ("api", "wordpress", "wp", "wp-admin", "wp-content", "wp-includes")
API_DOC_PATH_SEGMENTS = ("docs", "redoc", "openapi.json")


def _frontend_index_file() -> Path:
    index_file = FRONTEND_DIST_DIR / "index.html"
    if not index_file.is_file():
        raise HTTPException(
            status_code=503,
            detail="Frontend build not found. Run `npm run build`.",
        )
    return index_file


def _resolve_frontend_file(full_path: str) -> Path | None:
    static_file = (FRONTEND_DIST_DIR / full_path).resolve()
    if not static_file.is_relative_to(FRONTEND_DIST_DIR.resolve()):
        return None
    return static_file


def _should_reject_spa_fallback(full_path: str) -> bool:
    path = full_path.strip("/")
    if not path:
        return False
    segments = [segment for segment in path.lower().split("/") if segment]
    if any(segment.startswith(".") for segment in segments):
        return True
    if segments and segments[0] in BLOCKED_SPA_PATH_PREFIXES:
        return True
    # 本番ではAPI仕様を配信しない。SPAへ流すと存在するように見えてしまう。
    if is_production() and segments and segments[0] in API_DOC_PATH_SEGMENTS:
        return True
    return bool(Path(path).suffix)


@router.get("/", include_in_schema=False)
def frontend_index() -> FileResponse:
    return FileResponse(_frontend_index_file())


@router.get("/{full_path:path}", include_in_schema=False)
def frontend_spa_fallback(full_path: str) -> FileResponse:
    """存在する静的ファイルを返し、Vueの画面ルートはindex.htmlへ戻す。"""
    static_file = _resolve_frontend_file(full_path)
    if static_file and static_file.is_file():
        return FileResponse(static_file)
    if _should_reject_spa_fallback(full_path):
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(_frontend_index_file())
