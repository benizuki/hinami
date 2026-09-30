from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.app.schemas import OrgUnitRecord, WorkJournalRecord
from backend.app.storage.sqlite_store import HinamiSQLiteStore


def journal(journal_date: str, owner: str = "owner@example.com") -> WorkJournalRecord:
    return WorkJournalRecord.model_validate({
        "journal_date": journal_date,
        "participant": "佐藤",
        "owner_email": owner,
        "org_unit_id": "unit-a",
        "org_unit_name": "経理課",
        "updated_at": f"{journal_date}T09:00:00Z",
    })


class SQLiteStoreTest(unittest.TestCase):
    def test_file_does_not_grow_with_repeated_saves(self) -> None:
        """同じ日報の上書きでファイルが膨らまないこと。"""
        with TemporaryDirectory() as directory:
            path = Path(directory) / "hinami.sqlite"
            store = HinamiSQLiteStore(path)

            def total_size() -> int:
                return sum(
                    candidate.stat().st_size
                    for candidate in path.parent.iterdir()
                    if candidate.name.startswith(path.name)
                )

            store.save_work_journal(journal("2026-08-10"), "default")
            size_after_first = total_size()
            for index in range(300):
                record = journal("2026-08-10")
                record.participant = f"佐藤{index}"
                store.save_work_journal(record, "default")

            self.assertLess(total_size(), size_after_first * 2)

    def test_backup_is_a_readable_snapshot(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "hinami.sqlite"
            backup_path = Path(directory) / "backups" / "hinami-test.sqlite"
            store = HinamiSQLiteStore(path)
            store.save_work_journal(journal("2026-08-10"), "default")

            store.create_backup(backup_path)
            store.save_work_journal(journal("2026-08-11"), "default")

            self.assertTrue(backup_path.is_file())
            with sqlite3.connect(str(backup_path)) as connection:
                rows = connection.execute("SELECT journal_date FROM work_journals").fetchall()
            self.assertEqual(rows, [("2026-08-10",)])

    def test_work_journal_is_replaced_on_the_same_date(self) -> None:
        with TemporaryDirectory() as directory:
            store = HinamiSQLiteStore(Path(directory) / "hinami.sqlite")
            store.save_work_journal(journal("2026-08-10"), "default")
            updated = journal("2026-08-10")
            updated.participant = "鈴木"
            store.save_work_journal(updated, "default")

            records = store.list_work_journals("owner@example.com", "default")

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].participant, "鈴木")

    def test_work_journals_are_filtered_by_date_range(self) -> None:
        with TemporaryDirectory() as directory:
            store = HinamiSQLiteStore(Path(directory) / "hinami.sqlite")
            for date in ("2026-08-01", "2026-08-05", "2026-08-09"):
                store.save_work_journal(journal(date), "default")

            records = store.list_work_journals(
                "owner@example.com", "default", date_from="2026-08-03", date_to="2026-08-06"
            )

            self.assertEqual([record.journal_date for record in records], ["2026-08-05"])

    def test_work_journals_are_isolated_between_tenants(self) -> None:
        with TemporaryDirectory() as directory:
            store = HinamiSQLiteStore(Path(directory) / "hinami.sqlite")
            store.save_work_journal(journal("2026-08-10"), "default")
            store.save_work_journal(journal("2026-08-10"), "east")

            self.assertEqual(len(store.list_work_journals("owner@example.com", "default")), 1)
            self.assertEqual(len(store.list_all_work_journals("east")), 1)

    def test_deleting_a_work_journal_reports_whether_it_existed(self) -> None:
        with TemporaryDirectory() as directory:
            store = HinamiSQLiteStore(Path(directory) / "hinami.sqlite")
            store.save_work_journal(journal("2026-08-10"), "default")

            self.assertTrue(store.delete_work_journal("2026-08-10", "owner@example.com", "default"))
            self.assertFalse(store.delete_work_journal("2026-08-10", "owner@example.com", "default"))

    def test_deleting_an_org_unit_reports_whether_it_existed(self) -> None:
        with TemporaryDirectory() as directory:
            store = HinamiSQLiteStore(Path(directory) / "hinami.sqlite")
            store.save_org_unit(
                OrgUnitRecord(id="unit-a", tenant_id="default", parent_id="", name="経理課", kind="課"),
                "default",
            )

            self.assertTrue(store.delete_org_unit("unit-a", "default"))
            self.assertFalse(store.delete_org_unit("unit-a", "default"))
            self.assertEqual(store.list_org_units("default"), [])


if __name__ == "__main__":
    unittest.main()
