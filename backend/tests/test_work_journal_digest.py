from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.schemas import (
    OrgUnitRecord,
    WorkJournalOrganizationDigest,
    WorkJournalRecord,
)
from backend.app.services.gemini import GeminiError
from backend.app.services.llm_work_journal_digest import (
    build_organization_activity,
    summarize_organization_journals,
)
from backend.app.storage.sqlite_store import HinamiSQLiteStore

ORG_UNIT = OrgUnitRecord(id="itsec001", name="基幹システム課", kind="課")


def journal(date: str, participant: str, owner: str) -> WorkJournalRecord:
    return WorkJournalRecord.model_validate({
        "journal_date": date,
        "participant": participant,
        "owner_email": owner,
        "org_unit_id": ORG_UNIT.id,
        "org_unit_name": ORG_UNIT.name,
        "updated_at": f"{date}T09:00:00Z",
        "analysis": {
            "progressed_items": [f"{participant}が請求書の照合を進めた"],
            "ingenuity": ["照合手順をチェックリスト化した"],
            "unplanned_work": ["障害対応が割り込んだ"],
            "support_needed": ["照合ルールの確認をお願いしたい"],
        },
    })


class OrganizationActivityTest(unittest.TestCase):
    def test_activity_keeps_the_org_unit_id_and_name(self) -> None:
        """組織マスター導入時にdepartmentから改名した項目。取り違えると要約が落ちる。"""
        activity = build_organization_activity(
            ORG_UNIT.id, ORG_UNIT.name, "2026-08-08", "2026-08-14",
            [journal("2026-08-10", "佐藤", "sato@example.com")],
        )

        self.assertEqual(activity.org_unit_id, "itsec001")
        self.assertEqual(activity.org_unit_name, "基幹システム課")
        self.assertEqual(activity.journal_count, 1)

    def test_members_are_grouped_by_participant(self) -> None:
        activity = build_organization_activity(
            ORG_UNIT.id, ORG_UNIT.name, "2026-08-08", "2026-08-14",
            [
                journal("2026-08-10", "佐藤", "sato@example.com"),
                journal("2026-08-11", "佐藤", "sato@example.com"),
                journal("2026-08-11", "鈴木", "suzuki@example.com"),
            ],
        )

        self.assertEqual([member.participant for member in activity.members], ["佐藤", "鈴木"])
        self.assertEqual(activity.members[0].journal_count, 2)
        self.assertEqual(activity.members[0].latest_journal_date, "2026-08-11")


class SummarizeOrganizationJournalsTest(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch(
            "backend.app.services.llm_work_journal_digest.generate_structured"
        )
        self.generate = patcher.start()
        self.addCleanup(patcher.stop)
        self.activity = build_organization_activity(
            ORG_UNIT.id, ORG_UNIT.name, "2026-08-08", "2026-08-14",
            [journal("2026-08-10", "佐藤", "sato@example.com")],
        )

    def test_the_org_unit_name_is_sent_to_the_model(self) -> None:
        self.generate.return_value = WorkJournalOrganizationDigest(overview="ok")

        summarize_organization_journals(self.activity)

        prompt = self.generate.call_args.args[0]
        self.assertIn("基幹システム課", prompt)
        self.assertIn("佐藤", prompt)

    def test_falls_back_to_the_aggregation_when_the_model_fails(self) -> None:
        self.generate.side_effect = GeminiError("Geminiに接続できません")

        digest = summarize_organization_journals(self.activity)

        self.assertIn("基幹システム課", digest.overview)
        self.assertTrue(digest.progress)

    def test_an_empty_organization_does_not_call_the_model(self) -> None:
        empty = build_organization_activity(ORG_UNIT.id, ORG_UNIT.name, "", "", [])

        digest = summarize_organization_journals(empty)

        self.generate.assert_not_called()
        self.assertIn("まだありません", digest.overview)


class OrganizationSummaryEndpointTest(unittest.TestCase):
    """画面から呼ぶ経路をそのまま通す。改名漏れはここでしか出なかった。"""

    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        env = patch.dict(os.environ, {
            "GOOGLE_OAUTH_CLIENT_ID": "",
            "HINAMI_API_HOST": "127.0.0.1",
            "HINAMI_AUTH_DIR": str(Path(self.directory.name) / "auth"),
        })
        env.start()
        self.addCleanup(env.stop)
        import backend.app.main as main

        from backend.app import runtime
        from backend.app.api import middleware
        self.main = main
        root = Path(self.directory.name)
        store = HinamiSQLiteStore(root / "hinami.sqlite")
        for patcher in (
            patch.object(runtime, "store", store),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        store.save_org_unit(ORG_UNIT, "default")
        store.save_work_journal(journal("2026-08-10", "佐藤", "sato@example.com"), "default")
        middleware._ai_burst_limiter.reset()
        self.addCleanup(middleware._ai_burst_limiter.reset)
        self.client = TestClient(main.app, raise_server_exceptions=False)

    def test_activity_endpoint_returns_the_org_unit_name(self) -> None:
        response = self.client.get(
            "/api/work-journals/organization",
            params={"org_unit_id": ORG_UNIT.id, "date_from": "2026-08-08", "date_to": "2026-08-14"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["org_unit_id"], "itsec001")
        self.assertEqual(body["org_unit_name"], "基幹システム課")
        self.assertEqual(body["journal_count"], 1)

    def test_summary_endpoint_succeeds(self) -> None:
        with patch(
            "backend.app.services.llm_work_journal_digest.generate_structured"
        ) as generate:
            generate.return_value = WorkJournalOrganizationDigest(overview="今週は照合が進みました。")
            response = self.client.post(
                "/api/work-journals/organization/summary",
                json={
                    "org_unit_id": ORG_UNIT.id,
                    "date_from": "2026-08-08",
                    "date_to": "2026-08-14",
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["overview"], "今週は照合が進みました。")
        self.assertEqual(body["activity"]["org_unit_name"], "基幹システム課")

    def test_summary_endpoint_survives_a_model_failure(self) -> None:
        with patch(
            "backend.app.services.llm_work_journal_digest.generate_structured"
        ) as generate:
            generate.side_effect = GeminiError("Geminiに接続できません")
            response = self.client.post(
                "/api/work-journals/organization/summary",
                json={
                    "org_unit_id": ORG_UNIT.id,
                    "date_from": "2026-08-08",
                    "date_to": "2026-08-14",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("基幹システム課", response.json()["overview"])


if __name__ == "__main__":
    unittest.main()
