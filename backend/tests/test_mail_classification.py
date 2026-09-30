from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.schemas import (
    OrgUnitRecord,
    WorkJournalEmailCategoryCount,
    WorkJournalRecord,
)
from backend.app.services.llm_work_journal_digest import build_organization_activity
from backend.app.services.mail_classification import (
    MAIL_REQUEST_TYPE_RULE_KIND,
    MAIL_SOURCE_RULE_KIND,
    merge_email_category_counts,
)
from backend.app.storage.sqlite_store import HinamiSQLiteStore

ORG_UNIT = OrgUnitRecord(id="itsec001", name="基幹システム課", kind="課")


def journal(
    date: str,
    participant: str,
    categories: list[dict[str, object]],
) -> WorkJournalRecord:
    return WorkJournalRecord.model_validate({
        "journal_date": date,
        "participant": participant,
        "owner_email": f"{participant}@example.com",
        "org_unit_id": ORG_UNIT.id,
        "org_unit_name": ORG_UNIT.name,
        "updated_at": f"{date}T09:00:00Z",
        "activity_context": {
            "email_counts_available": True,
            "received_email_count": 20,
            "email_classified_count": 20,
            "email_categories": categories,
        },
    })


class MailRuleStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = HinamiSQLiteStore(Path(self.directory.name) / "hinami.sqlite")

    def test_rules_come_back_in_registration_order(self) -> None:
        """判定は前から順に当てるため、並び順が変わると分類結果が変わる。"""
        for rule_id, sort_order in (("second", 20), ("first", 10)):
            self.store.save_mail_rule(
                MAIL_SOURCE_RULE_KIND,
                {"id": rule_id, "name": rule_id, "sort_order": sort_order},
                "default",
            )
        stored = self.store.list_mail_rules(MAIL_SOURCE_RULE_KIND, "default")
        self.assertEqual([rule["id"] for rule in stored], ["first", "second"])

    def test_rule_kinds_and_tenants_do_not_mix(self) -> None:
        self.store.save_mail_rule(
            MAIL_SOURCE_RULE_KIND, {"id": "wf", "name": "WF", "sort_order": 0}, "default"
        )
        self.store.save_mail_rule(
            MAIL_REQUEST_TYPE_RULE_KIND, {"id": "wf", "name": "申請", "sort_order": 0}, "default"
        )
        self.store.save_mail_rule(
            MAIL_SOURCE_RULE_KIND, {"id": "wf", "name": "別テナント", "sort_order": 0}, "other"
        )
        self.assertEqual(
            [rule["name"] for rule in self.store.list_mail_rules(MAIL_SOURCE_RULE_KIND, "default")],
            ["WF"],
        )
        self.assertEqual(
            [rule["name"] for rule in self.store.list_mail_rules(MAIL_SOURCE_RULE_KIND, "other")],
            ["別テナント"],
        )
        self.assertTrue(self.store.delete_mail_rule(MAIL_SOURCE_RULE_KIND, "wf", "default"))
        self.assertFalse(self.store.delete_mail_rule(MAIL_SOURCE_RULE_KIND, "wf", "default"))
        self.assertEqual(
            len(self.store.list_mail_rules(MAIL_REQUEST_TYPE_RULE_KIND, "default")), 1
        )


class MailRuleApiTest(unittest.TestCase):
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
        self.main = main
        root = Path(self.directory.name)
        store = HinamiSQLiteStore(root / "hinami.sqlite")
        for patcher in (
            patch.object(runtime, "store", store),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.store = store
        self.client = TestClient(main.app)

    def test_defaults_are_delivered_once_and_stay_deleted(self) -> None:
        """既定値を消した管理者の判断を、次の参照で覆さない。"""
        first = self.client.get("/api/mail-rules")
        self.assertEqual(first.status_code, 200)
        request_types = first.json()["request_types"]
        self.assertTrue(request_types)
        self.assertEqual(first.json()["sources"], [])
        for rule in request_types:
            response = self.client.delete(f"/api/mail-rules/request-types/{rule['id']}")
            self.assertEqual(response.status_code, 204)
        self.assertEqual(self.client.get("/api/mail-rules").json()["request_types"], [])

    def test_source_address_is_stored_in_lower_case(self) -> None:
        response = self.client.post("/api/mail-rules/sources", json={
            "name": "購買ワークフロー",
            "kind": "system",
            "match_type": "address",
            "match_value": "  NoReply@WF.example.co.jp ",
            "default_category": "ワークフロー",
            "sort_order": 10,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["match_value"], "noreply@wf.example.co.jp")

    def test_request_type_rejects_an_unknown_source(self) -> None:
        response = self.client.post("/api/mail-rules/request-types", json={
            "name": "購買申請",
            "category": "ワークフロー",
            "source_ids": ["missing"],
            "keywords": ["購買申請"],
        })
        self.assertEqual(response.status_code, 422)

    def test_deleting_a_source_clears_it_from_request_types(self) -> None:
        """参照が残ると、対象の無い種別として黙って一致しなくなる。"""
        source_id = self.client.post("/api/mail-rules/sources", json={
            "name": "購買ワークフロー",
            "match_value": "noreply@wf.example.co.jp",
            "default_category": "ワークフロー",
        }).json()["id"]
        rule_id = self.client.post("/api/mail-rules/request-types", json={
            "name": "購買申請",
            "category": "ワークフロー",
            "source_ids": [source_id],
            "keywords": ["購買申請", "購買申請"],
        }).json()["id"]
        self.assertEqual(
            self.client.delete(f"/api/mail-rules/sources/{source_id}").status_code, 204
        )
        rules = self.client.get("/api/mail-rules").json()["request_types"]
        stored = next(rule for rule in rules if rule["id"] == rule_id)
        self.assertEqual(stored["source_ids"], [])
        # 同じ語を2回登録しても、判定は1回で足りる。
        self.assertEqual(stored["keywords"], ["購買申請"])

    def test_unknown_rule_id_is_not_created_by_update(self) -> None:
        response = self.client.put("/api/mail-rules/sources/missing", json={
            "name": "存在しない",
            "match_value": "a@example.com",
        })
        self.assertEqual(response.status_code, 404)


class EmailCategoryAggregationTest(unittest.TestCase):
    def test_counts_are_summed_per_member_and_organization(self) -> None:
        activity = build_organization_activity(
            ORG_UNIT.id, ORG_UNIT.name, "2026-08-10", "2026-08-11",
            [
                journal("2026-08-10", "佐藤", [
                    {"rule_id": "wf", "name": "購買申請", "category": "ワークフロー",
                     "received": 4, "sent": 1, "thread_count": 3},
                    {"rule_id": "", "name": "未分類", "category": "その他", "received": 2},
                ]),
                journal("2026-08-11", "佐藤", [
                    {"rule_id": "wf", "name": "購買申請", "category": "ワークフロー",
                     "received": 6, "sent": 0, "thread_count": 5},
                ]),
                journal("2026-08-11", "鈴木", [
                    {"rule_id": "est", "name": "見積", "category": "見積", "received": 3},
                ]),
            ],
        )
        sato = next(member for member in activity.members if member.participant == "佐藤")
        self.assertEqual(sato.email_classified_journal_count, 2)
        workflow = next(count for count in sato.email_categories if count.rule_id == "wf")
        self.assertEqual((workflow.received, workflow.sent, workflow.thread_count), (10, 1, 8))
        self.assertEqual(activity.email_classified_journal_count, 3)
        self.assertEqual(
            {count.name: count.received for count in activity.email_categories},
            {"購買申請": 10, "見積": 3, "未分類": 2},
        )

    def test_members_without_classification_are_not_counted(self) -> None:
        """分類していない日報を母数に入れると、件数の少なさが働き方の差に見えてしまう。"""
        activity = build_organization_activity(
            ORG_UNIT.id, ORG_UNIT.name, "2026-08-10", "2026-08-10",
            [journal("2026-08-10", "佐藤", [])],
        )
        self.assertEqual(activity.email_classified_journal_count, 0)
        self.assertEqual(activity.members[0].email_categories, [])

    def test_merge_keeps_the_first_known_source_name(self) -> None:
        merged = merge_email_category_counts([
            [WorkJournalEmailCategoryCount(rule_id="wf", name="購買申請", category="ワークフロー", received=1)],
            [WorkJournalEmailCategoryCount(
                rule_id="wf", name="購買申請", category="ワークフロー",
                source_id="src1", source_name="購買ワークフロー", received=1,
            )],
        ])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].source_name, "購買ワークフロー")
        self.assertEqual(merged[0].received, 2)


if __name__ == "__main__":
    unittest.main()
