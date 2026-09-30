"""SQLiteバックアップの作成・一覧・ダウンロード。"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from .. import runtime
from ..schemas import SQLiteBackupRecord, SQLiteDatabaseStatistics

logger = logging.getLogger(__name__)

router = APIRouter()


SQLITE_BACKUP_ID_PATTERN = re.compile(r"^hinami-\d{8}T\d{6}\d{6}Z-[a-f0-9]{8}$")


def _backup_path(backup_id: str) -> Path:
    """バックアップIDを許可済みディレクトリ内のパスへ安全に解決する。"""
    if not SQLITE_BACKUP_ID_PATTERN.fullmatch(backup_id):
        raise HTTPException(status_code=404, detail="バックアップが見つかりません。")
    backup_dir = runtime.SQLITE_BACKUP_DIR.resolve()
    candidate = (backup_dir / f"{backup_id}.sqlite").resolve()
    if candidate.parent != backup_dir:
        raise HTTPException(status_code=404, detail="バックアップが見つかりません。")
    return candidate


def _backup_record(path: Path) -> SQLiteBackupRecord:
    stat = path.stat()
    return SQLiteBackupRecord(
        id=path.stem,
        filename=path.name,
        created_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        size_bytes=stat.st_size,
    )


@router.get("/api/backups", response_model=list[SQLiteBackupRecord])
def list_sqlite_backups() -> list[SQLiteBackupRecord]:
    if not runtime.SQLITE_BACKUP_DIR.is_dir():
        return []
    backup_dir = runtime.SQLITE_BACKUP_DIR.resolve()
    records: list[SQLiteBackupRecord] = []
    for path in runtime.SQLITE_BACKUP_DIR.glob("hinami-*.sqlite"):
        if (
            path.is_file()
            and path.resolve().parent == backup_dir
            and SQLITE_BACKUP_ID_PATTERN.fullmatch(path.stem)
        ):
            records.append(_backup_record(path))
    return sorted(records, key=lambda record: record.created_at, reverse=True)


@router.get("/api/backups/statistics", response_model=SQLiteDatabaseStatistics)
def get_sqlite_database_statistics() -> SQLiteDatabaseStatistics:
    statistics = runtime.store.get_database_statistics()
    backups = list_sqlite_backups()
    return statistics.model_copy(
        update={
            "backup_bytes": sum(backup.size_bytes for backup in backups),
            "backup_count": len(backups),
        }
    )


@router.post("/api/backups", response_model=SQLiteBackupRecord, status_code=201)
async def create_sqlite_backup() -> SQLiteBackupRecord:
    now = datetime.now(timezone.utc)
    backup_id = f"hinami-{now.strftime('%Y%m%dT%H%M%S%fZ')}-{uuid4().hex[:8]}"
    backup_path = _backup_path(backup_id)
    try:
        await run_in_threadpool(runtime.store.create_backup, backup_path)
        return _backup_record(backup_path)
    except OSError as exc:
        logger.exception("SQLite backup creation failed")
        raise HTTPException(status_code=500, detail="SQLiteバックアップを作成できませんでした。") from exc


@router.get("/api/backups/{backup_id}")
def download_sqlite_backup(backup_id: str) -> FileResponse:
    backup_path = _backup_path(backup_id)
    if not backup_path.is_file():
        raise HTTPException(status_code=404, detail="バックアップが見つかりません。")
    return FileResponse(
        backup_path,
        media_type="application/vnd.sqlite3",
        filename=backup_path.name,
    )
