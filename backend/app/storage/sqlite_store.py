from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from ..schemas import (
    OrgUnitRecord,
    SQLiteDatabaseStatistics,
    SQLiteTableStatistics,
    WorkJournalRecord,
    WorkProfileEntry,
)


class HinamiSQLiteStore:
    """業務日報・組織・メール分類・AI利用記録の保存先。

    問い合わせはすべて主キー検索か絞り込み＋整列で、集計はPython側で行う。
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        # isolation_level=Noneで暗黙のトランザクションを止め、
        # BEGIN/COMMITを明示している箇所と挙動を揃える。
        connection = sqlite3.connect(str(self.path), isolation_level=None, timeout=30.0)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _column_names(connection: sqlite3.Connection, table: str) -> set[str]:
        return {
            str(row[1])
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }

    def _initialize(self) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS work_journals (
                    tenant_id TEXT NOT NULL,
                    owner_email TEXT NOT NULL,
                    journal_date TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, owner_email, journal_date)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS work_profiles (
                    tenant_id TEXT NOT NULL,
                    org_unit_id TEXT NOT NULL,
                    task_key TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, org_unit_id, task_key)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS org_units (
                    tenant_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    parent_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    sort_order INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id TEXT NOT NULL,
                    user_email TEXT NOT NULL,
                    feature TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    occurred_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS ai_usage_tenant_time"
                " ON ai_usage (tenant_id, occurred_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS ai_usage_tenant_user_time"
                " ON ai_usage (tenant_id, user_email, occurred_at)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS mail_classification_rules (
                    tenant_id TEXT NOT NULL,
                    rule_kind TEXT NOT NULL,
                    id TEXT NOT NULL,
                    sort_order INTEGER NOT NULL,
                    record_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, rule_kind, id)
                )
                """
            )
            # 利用者ごとの設定。テナントを跨いで同じ人には同じ好みを使う。
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS user_preferences (
                    user_email TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_email, kind)
                )
                """
            )

    def create_backup(self, destination: Path) -> None:
        """稼働中のDBから一貫性のあるSQLiteスナップショットを作成する。

        WALファイルを単純にコピーすると、チェックポイントのタイミング次第で復元に
        必要な内容が欠ける。そのためSQLite標準のbackup APIを使い、全ストア書き込みと
        同じロックの中でコピーする。
        """
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connection() as source:
            target = sqlite3.connect(str(destination), isolation_level=None)
            try:
                source.backup(target)
            finally:
                target.close()
        destination.chmod(0o600)

    def get_database_statistics(self) -> SQLiteDatabaseStatistics:
        """稼働DBのファイル、ページ、テーブル別使用量を読み取り専用で集計する。"""
        with self._lock, self._connection() as connection:
            page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
            page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
            freelist_count = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
            journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).upper()
            schema_rows = connection.execute(
                """
                SELECT name, type, tbl_name
                FROM sqlite_schema
                WHERE type IN ('table', 'index')
                ORDER BY name
                """
            ).fetchall()
            table_names = [
                str(name)
                for name, object_type, _ in schema_rows
                if object_type == "table" and not str(name).startswith("sqlite_")
            ]
            index_owners = {
                str(name): str(table_name)
                for name, object_type, table_name in schema_rows
                if object_type == "index" and str(table_name) in table_names
            }
            object_sizes: dict[str, int] = {}
            try:
                object_sizes = {
                    str(name): int(size or 0)
                    for name, size in connection.execute(
                        "SELECT name, SUM(pgsize) FROM dbstat GROUP BY name"
                    ).fetchall()
                }
            except sqlite3.OperationalError:
                # dbstatが無効なSQLiteビルドでも、件数とDB全体の統計は表示できる。
                object_sizes = {}

            index_sizes = {name: 0 for name in table_names}
            for index_name, owner in index_owners.items():
                index_sizes[owner] += object_sizes.get(index_name, 0)

            tables: list[SQLiteTableStatistics] = []
            for table_name in table_names:
                quoted_name = table_name.replace('"', '""')
                row_count = int(
                    connection.execute(f'SELECT COUNT(*) FROM "{quoted_name}"').fetchone()[0]
                )
                table_bytes = object_sizes.get(table_name, 0)
                index_bytes = index_sizes[table_name]
                tables.append(
                    SQLiteTableStatistics(
                        name=table_name,
                        row_count=row_count,
                        table_bytes=table_bytes,
                        index_bytes=index_bytes,
                        total_bytes=table_bytes + index_bytes,
                    )
                )

        wal_path = Path(f"{self.path}-wal")
        shm_path = Path(f"{self.path}-shm")
        database_stat = self.path.stat() if self.path.is_file() else None
        wal_stat = wal_path.stat() if wal_path.is_file() else None
        shm_stat = shm_path.stat() if shm_path.is_file() else None
        database_bytes = database_stat.st_size if database_stat else 0
        wal_bytes = wal_stat.st_size if wal_stat else 0
        shm_bytes = shm_stat.st_size if shm_stat else 0
        allocated_bytes = page_count * page_size
        unused_bytes = freelist_count * page_size
        logical_used_bytes = max(0, allocated_bytes - unused_bytes)
        usage_percent = (
            round(logical_used_bytes / allocated_bytes * 100, 1) if allocated_bytes else 0.0
        )
        tables.sort(key=lambda item: (-item.total_bytes, -item.row_count, item.name))
        modified_timestamps = [item.st_mtime for item in (database_stat, wal_stat) if item]
        modified_at = datetime.fromtimestamp(
            max(modified_timestamps, default=datetime.now(timezone.utc).timestamp()),
            timezone.utc,
        ).isoformat()
        return SQLiteDatabaseStatistics(
            database_filename=self.path.name,
            journal_mode=journal_mode,
            last_modified_at=modified_at,
            database_bytes=database_bytes,
            wal_bytes=wal_bytes,
            shm_bytes=shm_bytes,
            active_files_bytes=database_bytes + wal_bytes + shm_bytes,
            allocated_bytes=allocated_bytes,
            logical_used_bytes=logical_used_bytes,
            unused_bytes=unused_bytes,
            usage_percent=usage_percent,
            total_records=sum(item.row_count for item in tables),
            table_count=len(tables),
            backup_bytes=0,
            backup_count=0,
            tables=tables,
        )

    def list_work_journals(
        self,
        owner_email: str,
        tenant_id: str = "default",
        date_from: str = "",
        date_to: str = "",
    ) -> list[WorkJournalRecord]:
        clauses = ["tenant_id = ?", "owner_email = ?"]
        parameters: list[str] = [tenant_id.strip().lower(), owner_email.strip().lower()]
        if date_from:
            clauses.append("journal_date >= ?")
            parameters.append(date_from)
        if date_to:
            clauses.append("journal_date <= ?")
            parameters.append(date_to)
        query = (
            "SELECT record_json FROM work_journals WHERE "
            + " AND ".join(clauses)
            + " ORDER BY journal_date"
        )
        with self._lock, self._connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [
            WorkJournalRecord.model_validate(
                json.loads(record_json) if isinstance(record_json, str) else record_json
            )
            for (record_json,) in rows
        ]

    def list_org_units(self, tenant_id: str = "default") -> list[OrgUnitRecord]:
        normalized = tenant_id.strip().lower()
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT id, parent_id, name, kind, sort_order, updated_at FROM org_units"
                " WHERE tenant_id = ? ORDER BY sort_order, name",
                (normalized,),
            ).fetchall()
        return [
            OrgUnitRecord(
                id=str(identifier),
                tenant_id=normalized,
                parent_id=str(parent_id or ""),
                name=str(name),
                kind=str(kind),  # type: ignore[arg-type]
                sort_order=int(sort_order or 0),
                updated_at=str(updated_at or ""),
            )
            for identifier, parent_id, name, kind, sort_order, updated_at in rows
        ]

    def save_org_unit(self, record: OrgUnitRecord, tenant_id: str = "default") -> OrgUnitRecord:
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO org_units (
                    tenant_id, id, parent_id, name, kind, sort_order, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (tenant_id, id) DO UPDATE SET
                    parent_id = excluded.parent_id,
                    name = excluded.name,
                    kind = excluded.kind,
                    sort_order = excluded.sort_order,
                    updated_at = excluded.updated_at
                """,
                (
                    tenant_id.strip().lower(),
                    record.id,
                    record.parent_id,
                    record.name,
                    record.kind,
                    record.sort_order,
                    record.updated_at,
                ),
            )
        return record

    def delete_org_unit(self, org_unit_id: str, tenant_id: str = "default") -> bool:
        normalized = tenant_id.strip().lower()
        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM org_units WHERE tenant_id = ? AND id = ?",
                (normalized, org_unit_id.strip()),
            )
            deleted = cursor.rowcount > 0
        return deleted

    def list_mail_rules(self, rule_kind: str, tenant_id: str = "default") -> list[dict[str, Any]]:
        """メール分類マスターを整列済みで返す。判定は登録順に前から当てる。"""
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT record_json FROM mail_classification_rules"
                " WHERE tenant_id = ? AND rule_kind = ? ORDER BY sort_order, id",
                (tenant_id.strip().lower(), rule_kind),
            ).fetchall()
        return [json.loads(record_json) for (record_json,) in rows]

    def save_mail_rule(
        self,
        rule_kind: str,
        record: dict[str, Any],
        tenant_id: str = "default",
    ) -> dict[str, Any]:
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO mail_classification_rules (
                    tenant_id, rule_kind, id, sort_order, record_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (tenant_id, rule_kind, id) DO UPDATE SET
                    sort_order = excluded.sort_order,
                    record_json = excluded.record_json,
                    updated_at = excluded.updated_at
                """,
                (
                    tenant_id.strip().lower(),
                    rule_kind,
                    str(record.get("id", "")),
                    int(record.get("sort_order", 0) or 0),
                    json.dumps(record, ensure_ascii=False),
                    str(record.get("updated_at", "")),
                ),
            )
        return record

    def delete_mail_rule(
        self,
        rule_kind: str,
        rule_id: str,
        tenant_id: str = "default",
    ) -> bool:
        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM mail_classification_rules"
                " WHERE tenant_id = ? AND rule_kind = ? AND id = ?",
                (tenant_id.strip().lower(), rule_kind, rule_id.strip()),
            )
            return cursor.rowcount > 0

    def get_user_preference(self, user_email: str, kind: str) -> dict[str, Any] | None:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT record_json FROM user_preferences WHERE user_email = ? AND kind = ?",
                (user_email, kind),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def save_user_preference(self, user_email: str, kind: str, record: dict[str, Any]) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO user_preferences (user_email, kind, record_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_email, kind) DO UPDATE SET
                    record_json = excluded.record_json,
                    updated_at = excluded.updated_at
                """,
                (
                    user_email,
                    kind,
                    json.dumps(record, ensure_ascii=False),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def list_all_work_journals(self, tenant_id: str = "default") -> list[WorkJournalRecord]:
        """移行処理のため、テナント内のすべての日報を取得する。"""
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT record_json FROM work_journals WHERE tenant_id = ? ORDER BY journal_date",
                (tenant_id.strip().lower(),),
            ).fetchall()
        return [
            WorkJournalRecord.model_validate(
                json.loads(record_json) if isinstance(record_json, str) else record_json
            )
            for (record_json,) in rows
        ]

    def list_org_unit_work_journals(
        self,
        org_unit_ids: list[str],
        tenant_id: str = "default",
        date_from: str = "",
        date_to: str = "",
    ) -> list[WorkJournalRecord]:
        """組織内共有のため、指定した組織単位（配下を含む）の日報を取得する。

        組織名は改称されうるため、突合は組織単位のIDだけで行う。
        """
        clauses = ["tenant_id = ?"]
        parameters: list[str] = [tenant_id.strip().lower()]
        if date_from:
            clauses.append("journal_date >= ?")
            parameters.append(date_from)
        if date_to:
            clauses.append("journal_date <= ?")
            parameters.append(date_to)
        query = (
            "SELECT record_json FROM work_journals WHERE "
            + " AND ".join(clauses)
            + " ORDER BY journal_date"
        )
        with self._lock, self._connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        targets = {value.strip() for value in org_unit_ids if value.strip()}
        if not targets:
            return []
        records = [
            WorkJournalRecord.model_validate(
                json.loads(record_json) if isinstance(record_json, str) else record_json
            )
            for (record_json,) in rows
        ]
        return [record for record in records if record.org_unit_id.strip() in targets]

    def list_work_profiles(
        self,
        org_unit_id: str,
        tenant_id: str = "default",
    ) -> list[WorkProfileEntry]:
        """組織で確定済みの業務辞書を返す。名寄せの基準として使う。"""
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT record_json FROM work_profiles WHERE tenant_id = ? AND org_unit_id = ?"
                " ORDER BY task_key",
                (tenant_id.strip().lower(), org_unit_id.strip()),
            ).fetchall()
        return [
            WorkProfileEntry.model_validate(
                json.loads(record_json) if isinstance(record_json, str) else record_json
            )
            for (record_json,) in rows
        ]

    def save_work_profiles(
        self,
        entries: list[WorkProfileEntry],
        org_unit_id: str,
        tenant_id: str = "default",
    ) -> list[WorkProfileEntry]:
        if not entries or not org_unit_id.strip():
            return []
        with self._lock, self._connection() as connection:
            for entry in entries:
                connection.execute(
                    """
                    INSERT INTO work_profiles (
                        tenant_id, org_unit_id, task_key, record_json, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT (tenant_id, org_unit_id, task_key) DO UPDATE SET
                        record_json = excluded.record_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        tenant_id.strip().lower(),
                        org_unit_id.strip(),
                        entry.task_key,
                        json.dumps(entry.model_dump(mode="json"), ensure_ascii=False),
                        entry.updated_at,
                    ),
                )
        return entries

    def save_work_journal(
        self,
        record: WorkJournalRecord,
        tenant_id: str = "default",
    ) -> WorkJournalRecord:
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO work_journals (
                    tenant_id, owner_email, journal_date, record_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (tenant_id, owner_email, journal_date) DO UPDATE SET
                    record_json = excluded.record_json,
                    updated_at = excluded.updated_at
                """,
                (
                    tenant_id.strip().lower(),
                    record.owner_email.strip().lower(),
                    record.journal_date,
                    json.dumps(record.model_dump(mode="json"), ensure_ascii=False),
                    record.updated_at,
                ),
            )
        return record

    def delete_work_journal(
        self,
        journal_date: str,
        owner_email: str,
        tenant_id: str = "default",
    ) -> bool:
        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                """
                DELETE FROM work_journals
                WHERE tenant_id = ? AND owner_email = ? AND journal_date = ?
                """,
                (tenant_id.strip().lower(), owner_email.strip().lower(), journal_date),
            )
            return cursor.rowcount > 0

    def record_ai_usage(
        self,
        *,
        tenant_id: str,
        user_email: str,
        feature: str,
        endpoint: str,
        outcome: str,
        duration_ms: int,
        occurred_at: str,
        prompt_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int = 0,
    ) -> None:
        """AI呼び出し1件を記録する。利用状況の可視化と1日あたりの上限判定に使う。"""
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO ai_usage (
                    tenant_id, user_email, feature, endpoint, outcome, duration_ms,
                    prompt_tokens, output_tokens, total_tokens, occurred_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant_id.strip().lower(),
                    user_email.strip().lower(),
                    feature,
                    endpoint,
                    outcome,
                    max(0, int(duration_ms)),
                    max(0, int(prompt_tokens)),
                    max(0, int(output_tokens)),
                    max(0, int(total_tokens)),
                    occurred_at,
                ),
            )

    def count_ai_usage_since(
        self,
        *,
        tenant_id: str,
        user_email: str,
        since: str,
    ) -> int:
        """1日あたりの上限判定。プロセスをまたいで数えるためDBで数える。"""
        with self._lock, self._connection() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) FROM ai_usage
                WHERE tenant_id = ? AND user_email = ? AND occurred_at >= ? AND outcome != 'rate-limited'
                """,
                (tenant_id.strip().lower(), user_email.strip().lower(), since),
            ).fetchone()
        return int(row[0]) if row else 0

    def summarize_ai_usage(
        self,
        *,
        tenant_id: str,
        date_from: str,
        date_to: str,
        user_email: str = "",
    ) -> dict[str, list[tuple]]:
        """利用状況の集計。利用者別・機能別・日別をそれぞれ返す。"""
        clauses = ["tenant_id = ?", "occurred_at >= ?", "occurred_at < ?"]
        parameters: list[str] = [tenant_id.strip().lower(), date_from, date_to]
        if user_email.strip():
            clauses.append("user_email = ?")
            parameters.append(user_email.strip().lower())
        where = " AND ".join(clauses)
        with self._lock, self._connection() as connection:
            by_user = connection.execute(
                f"""
                SELECT user_email, COUNT(*), SUM(duration_ms),
                       SUM(CASE WHEN outcome = 'error' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN outcome = 'rate-limited' THEN 1 ELSE 0 END),
                       SUM(prompt_tokens), SUM(output_tokens), SUM(total_tokens)
                FROM ai_usage WHERE {where}
                GROUP BY user_email ORDER BY COUNT(*) DESC
                """,
                parameters,
            ).fetchall()
            by_feature = connection.execute(
                f"SELECT feature, COUNT(*), SUM(duration_ms), SUM(total_tokens)"
                f" FROM ai_usage WHERE {where} GROUP BY feature ORDER BY COUNT(*) DESC",
                parameters,
            ).fetchall()
            by_day = connection.execute(
                f"SELECT substr(occurred_at, 1, 10) AS day, COUNT(*), SUM(total_tokens)"
                f" FROM ai_usage WHERE {where} GROUP BY day ORDER BY day",
                parameters,
            ).fetchall()
        return {"by_user": by_user, "by_feature": by_feature, "by_day": by_day}

    def prune_ai_usage(self, *, before: str) -> int:
        """保存期間を過ぎた記録を消す。件数の記録なので長期保持する必要はない。"""
        with self._lock, self._connection() as connection:
            cursor = connection.execute("DELETE FROM ai_usage WHERE occurred_at < ?", (before,))
            return cursor.rowcount
