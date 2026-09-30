from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import runtime
from backend.app.api import middleware
from backend.app.schemas import WorkJournalRecord


class SQLiteBackupApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        from backend.app import main
        from backend.app.storage.sqlite_store import HinamiSQLiteStore

        root = Path(self.directory.name)
        self.store = HinamiSQLiteStore(root / "hinami.sqlite")
        patchers = (
            patch.object(runtime, "store", self.store),
            patch.object(runtime, "SQLITE_BACKUP_DIR", root / "backups"),
            patch.object(middleware, "auth_enabled", return_value=False),
        )
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.main = main
        self.client = TestClient(main.app)

    def test_create_list_and_download_backup(self) -> None:
        self.store.save_work_journal(
            WorkJournalRecord.model_validate({
                "journal_date": "2026-08-10",
                "participant": "佐藤",
                "owner_email": "owner@example.com",
                "updated_at": "2026-08-10T09:00:00Z",
            }),
            "default",
        )

        created = self.client.post("/api/backups")
        self.assertEqual(created.status_code, 201)
        backup = created.json()
        self.assertRegex(backup["id"], r"^hinami-\d{8}T\d{12}Z-[a-f0-9]{8}$")
        self.assertGreater(backup["size_bytes"], 0)

        listed = self.client.get("/api/backups")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual([item["id"] for item in listed.json()], [backup["id"]])

        statistics_response = self.client.get("/api/backups/statistics")
        self.assertEqual(statistics_response.status_code, 200)
        statistics = statistics_response.json()
        self.assertEqual(statistics["database_filename"], "hinami.sqlite")
        self.assertEqual(statistics["journal_mode"], "WAL")
        self.assertGreaterEqual(statistics["total_records"], 1)
        self.assertGreater(statistics["table_count"], 0)
        self.assertEqual(statistics["backup_count"], 1)
        self.assertEqual(statistics["backup_bytes"], backup["size_bytes"])
        self.assertEqual(
            statistics["active_files_bytes"],
            statistics["database_bytes"] + statistics["wal_bytes"] + statistics["shm_bytes"],
        )
        self.assertEqual(
            statistics["logical_used_bytes"] + statistics["unused_bytes"],
            statistics["allocated_bytes"],
        )
        journals = next(item for item in statistics["tables"] if item["name"] == "work_journals")
        self.assertEqual(journals["row_count"], 1)
        self.assertEqual(journals["total_bytes"], journals["table_bytes"] + journals["index_bytes"])

        downloaded = self.client.get(f"/api/backups/{backup['id']}")
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(downloaded.headers["content-type"], "application/vnd.sqlite3")
        self.assertTrue(downloaded.content.startswith(b"SQLite format 3"))

    def test_backup_routes_require_system_admin_when_auth_is_enabled(self) -> None:
        with patch.object(middleware, "auth_enabled", return_value=True):
            self.assertEqual(middleware._required_role_for_request("GET", "/api/backups"), "admin")
            self.assertEqual(
                middleware._required_role_for_request("GET", "/api/backups/statistics"),
                "admin",
            )
            self.assertEqual(
                middleware._required_role_for_request("GET", "/api/backups/hinami-20260829T123456000000Z-1234abcd"),
                "admin",
            )


if __name__ == "__main__":
    unittest.main()
