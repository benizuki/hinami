from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.app.schemas import (
    WorkJournalAnalysis,
    WorkJournalItem,
    WorkJournalRecord,
    WorkJournalReference,
)
from backend.app.services import llm_work_journal_mining as mining
from backend.app.services import work_graph
from backend.app.services.gemini import GeminiError
from backend.app.storage.sqlite_store import HinamiSQLiteStore


def journal(
    participant: str,
    journal_date: str,
    work_items: list[WorkJournalItem] | None = None,
    references: list[WorkJournalReference] | None = None,
    department: str = "経理・財務",
    org_unit_id: str = "itsec001",
    analysis: WorkJournalAnalysis | None = None,
) -> WorkJournalRecord:
    return WorkJournalRecord(
        journal_date=journal_date,
        department=department,
        org_unit_id=org_unit_id,
        participant=participant,
        work_items=work_items or [],
        references=references or [],
        analysis=analysis or WorkJournalAnalysis(),
    )


class DocumentFlowTest(unittest.TestCase):
    def test_same_drive_file_across_members_is_detected_as_a_relay(self) -> None:
        drive_url = "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view"
        records = [
            journal(
                "佐藤",
                "2026-08-10",
                work_items=[WorkJournalItem(title="月次売上表の作成", description="月次売上表を作成した。")],
                references=[WorkJournalReference(name="月次売上表.xlsx", url=drive_url)],
            ),
            journal(
                "鈴木",
                "2026-08-11",
                work_items=[WorkJournalItem(title="月次売上表の更新", description="月次売上表へ実績を反映した。")],
                references=[WorkJournalReference(name="月次売上表.xlsx", url=drive_url)],
            ),
            journal(
                "田中",
                "2026-08-12",
                work_items=[WorkJournalItem(title="月次売上表の確認", description="月次売上表をレビューした。")],
                references=[WorkJournalReference(name="月次売上表.xlsx", url=drive_url)],
            ),
        ]

        report = mining.build_document_flows("経理・財務", "2026-08-01", "2026-08-31", records)

        self.assertEqual(len(report.flows), 1)
        flow = report.flows[0]
        self.assertTrue(flow.is_relay)
        self.assertEqual(flow.participants, ["佐藤", "鈴木", "田中"])
        self.assertEqual(flow.handoff_count, 2)
        self.assertEqual([touch.action for touch in flow.touches], ["作成", "更新", "確認"])

    def test_same_file_name_without_drive_link_is_still_grouped(self) -> None:
        records = [
            journal(
                "佐藤",
                "2026-08-10",
                work_items=[WorkJournalItem(title="請求一覧の作成", description="請求一覧を作成した。")],
                references=[WorkJournalReference(name="請求一覧 2026.xlsx")],
            ),
            journal(
                "鈴木",
                "2026-08-12",
                work_items=[WorkJournalItem(title="請求一覧の確認", description="請求一覧をチェックした。")],
                references=[WorkJournalReference(name="請求一覧_2026.XLSX")],
            ),
        ]

        report = mining.build_document_flows("経理・財務", "", "", records)

        self.assertEqual(len(report.flows), 1)
        self.assertEqual(report.flows[0].participants, ["佐藤", "鈴木"])

    def test_single_owner_document_is_not_marked_as_a_relay(self) -> None:
        records = [
            journal(
                "佐藤",
                "2026-08-10",
                work_items=[WorkJournalItem(title="個人メモの更新", description="個人メモを修正した。")],
                references=[WorkJournalReference(name="個人メモ.xlsx")],
            ),
            journal(
                "佐藤",
                "2026-08-11",
                work_items=[WorkJournalItem(title="個人メモの更新", description="個人メモを追記した。")],
                references=[WorkJournalReference(name="個人メモ.xlsx")],
            ),
        ]

        report = mining.build_document_flows("経理・財務", "", "", records)

        self.assertFalse(report.flows[0].is_relay)
        self.assertEqual(report.flows[0].handoff_count, 0)

    def test_saved_document_insight_is_used_for_identification(self) -> None:
        records = [
            journal(
                "佐藤",
                "2026-08-10",
                work_items=[WorkJournalItem(title="設備点検報告の作成", description="点検報告をまとめた。")],
                references=[
                    WorkJournalReference(
                        name="scan_0012.pdf",
                        document_title="設備点検報告書",
                        related_business="設備保全",
                        key_topics=["点検結果", "是正処置"],
                    )
                ],
            ),
        ]

        report = mining.build_document_flows("製造部", "", "", records)

        self.assertEqual(report.flows[0].document_title, "設備点検報告書")
        self.assertEqual(report.flows[0].related_business, "設備保全")


class WorkMapTest(unittest.TestCase):
    def setUp(self) -> None:
        # 埋め込みは名寄せの補助なので、テストでは外部呼び出しを行わない。
        patcher = patch.object(mining, "embed_texts", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)

    def _records(self) -> list[WorkJournalRecord]:
        # 日付順に並べ替えてからindexを振るため、index順は 佐藤(10日)/鈴木(11日)/佐藤(17日) になる。
        return [
            journal(
                "佐藤",
                "2026-08-10",
                work_items=[WorkJournalItem(title="月次売上集計", description="売上を集計した。")],
            ),
            journal(
                "佐藤",
                "2026-08-17",
                work_items=[WorkJournalItem(title="月次の集計作業", description="売上を集計した。")],
            ),
            journal(
                "鈴木",
                "2026-08-11",
                work_items=[WorkJournalItem(title="請求書の確認", description="請求書を確認した。")],
            ),
        ]

    def test_single_owner_task_is_flagged_and_counted_deterministically(self) -> None:
        analysis = mining.WorkJournalClusterAnalysis(
            clusters=[
                mining.WorkJournalClusterAssignment(
                    task_name="月次売上集計",
                    summary="月次の売上を集計する作業。",
                    item_indexes=[0, 2],
                ),
                mining.WorkJournalClusterAssignment(
                    task_name="請求書確認",
                    summary="請求書の内容を確認する作業。",
                    item_indexes=[1],
                ),
            ]
        )
        with patch.object(mining, "generate_structured", return_value=analysis):
            work_map = mining.build_work_map("経理・財務", "2026-08-01", "2026-08-31", self._records())

        by_name = {cluster.task_name: cluster for cluster in work_map.clusters}
        self.assertEqual(by_name["月次売上集計"].participants, ["佐藤"])
        self.assertEqual(by_name["月次売上集計"].occurrence_count, 2)
        self.assertTrue(by_name["月次売上集計"].single_owner)
        self.assertEqual(by_name["月次売上集計"].journal_dates, ["2026-08-10", "2026-08-17"])

    def test_invented_indexes_from_the_model_are_ignored(self) -> None:
        analysis = mining.WorkJournalClusterAnalysis(
            clusters=[
                mining.WorkJournalClusterAssignment(task_name="月次売上集計", item_indexes=[0, 2, 99]),
            ]
        )
        with patch.object(mining, "generate_structured", return_value=analysis):
            work_map = mining.build_work_map("経理・財務", "", "", self._records())

        self.assertEqual(work_map.clusters[0].occurrence_count, 2)
        self.assertEqual(work_map.clusters[0].participants, ["佐藤"])

    def test_clustering_failure_falls_back_to_title_grouping(self) -> None:
        with patch.object(
            mining,
            "generate_structured",
            side_effect=GeminiError("Gemini 応答の項目形式が想定と異なります"),
        ):
            work_map = mining.build_work_map("経理・財務", "", "", self._records())

        self.assertTrue(work_map.clusters)
        self.assertEqual(sum(cluster.occurrence_count for cluster in work_map.clusters), 3)

    def test_clustering_prompt_forbids_evaluation_and_invented_tasks(self) -> None:
        for phrase in ("人事評価", "創作しない", "人名を含めない"):
            self.assertIn(phrase, mining.WORK_JOURNAL_WORK_MAP_INSTRUCTION)


class OrgUnitJournalStoreTest(unittest.TestCase):
    def test_journal_query_is_scoped_by_tenant_and_org_unit(self) -> None:
        with TemporaryDirectory() as directory:
            store = HinamiSQLiteStore(Path(directory) / "hinami.sqlite")
            store.save_work_journal(journal("佐藤", "2026-08-10"), "default")
            store.save_work_journal(
                WorkJournalRecord(
                    journal_date="2026-08-10",
                    department="製造部",
                    org_unit_id="mfg00001",
                    participant="鈴木",
                    owner_email="suzuki@example.com",
                ),
                "default",
            )
            store.save_work_journal(
                WorkJournalRecord(
                    journal_date="2026-08-10",
                    department="経理・財務",
                    org_unit_id="itsec001",
                    participant="他テナント",
                    owner_email="other@example.com",
                ),
                "east",
            )

            records = store.list_org_unit_work_journals(["itsec001"], "default")

            self.assertEqual([record.participant for record in records], ["佐藤"])

    def test_journal_query_ignores_records_without_an_org_unit(self) -> None:
        """所属未設定の旧レコードは拾わない。起動時の移行で補う。"""
        with TemporaryDirectory() as directory:
            store = HinamiSQLiteStore(Path(directory) / "hinami.sqlite")
            store.save_work_journal(journal("佐藤", "2026-08-10", org_unit_id=""), "default")

            self.assertEqual(store.list_org_unit_work_journals(["itsec001"], "default"), [])
            self.assertEqual(len(store.list_all_work_journals("default")), 1)

class WorkGraphTest(unittest.TestCase):
    def _fixture(self):
        from backend.app.schemas import WorkProfileEntry, WorkProfileOwner

        drive_url = "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view"
        records = [
            journal(
                "佐藤", "2026-08-10",
                work_items=[WorkJournalItem(title="月次売上表の作成", description="月次売上表を作成した。")],
                references=[WorkJournalReference(name="月次売上表.xlsx", url=drive_url)],
            ),
            journal(
                "鈴木", "2026-08-11",
                work_items=[WorkJournalItem(title="月次売上表の確認", description="月次売上表を確認した。")],
                references=[WorkJournalReference(name="月次売上表.xlsx", url=drive_url)],
            ),
        ]
        flow_report = mining.build_document_flows("経理・財務", "", "", records)
        profiles = [
            WorkProfileEntry(
                task_key="月次売上集計",
                task_name="月次売上集計",
                document_names=["月次売上表.xlsx"],
                owners=[WorkProfileOwner(participant="佐藤", occurrence_count=4)],
                occurrence_count=4,
            ),
            WorkProfileEntry(
                task_key="採用面接",
                task_name="採用面接",
                owners=[
                    WorkProfileOwner(participant="鈴木", occurrence_count=1),
                    WorkProfileOwner(participant="田中", occurrence_count=1),
                ],
                occurrence_count=2,
            ),
        ]
        return profiles, flow_report

    def test_graph_links_people_tasks_and_documents(self) -> None:
        profiles, flow_report = self._fixture()

        graph = work_graph.build_work_graph("経理・財務", "", "", profiles, flow_report)

        kinds = {node.id: node.kind for node in graph.nodes}
        self.assertIn("task:月次売上集計", kinds)
        self.assertIn("person:佐藤", kinds)
        self.assertTrue(any(node.kind == "document" for node in graph.nodes))
        self.assertTrue(any(edge.kind == "owns" for edge in graph.edges))
        self.assertTrue(any(edge.kind == "uses" for edge in graph.edges))
        self.assertTrue(any(edge.kind == "handoff" for edge in graph.edges))

    def test_single_owner_task_with_downstream_people_is_the_top_risk(self) -> None:
        profiles, flow_report = self._fixture()

        graph = work_graph.build_work_graph("経理・財務", "", "", profiles, flow_report)

        self.assertTrue(graph.key_person_risks)
        top = graph.key_person_risks[0]
        self.assertEqual(top.label, "月次売上集計")
        self.assertEqual(top.owners, ["佐藤"])
        self.assertEqual(top.downstream_people, ["鈴木"])
        self.assertIn("後工程", top.reason)
        # 複数人で担当している業務は属人化リスクに含めない。
        self.assertNotIn("採用面接", [risk.label for risk in graph.key_person_risks])

    def test_automation_targets_are_ranked_with_visible_reasons(self) -> None:
        profiles, flow_report = self._fixture()

        graph = work_graph.build_work_graph("経理・財務", "", "", profiles, flow_report)

        self.assertTrue(graph.automation_targets)
        top = graph.automation_targets[0]
        self.assertEqual(top.label, "月次売上集計")
        self.assertEqual(top.occurrence_count, 4)
        self.assertEqual(top.handoff_count, 1)
        self.assertIn("繰り返し", top.reason)

    def test_documents_are_matched_to_the_work_item_that_mentions_them(self) -> None:
        analysis = mining.WorkJournalClusterAnalysis(
            clusters=[
                mining.WorkJournalClusterAssignment(task_name="月次売上集計", item_indexes=[0]),
                mining.WorkJournalClusterAssignment(task_name="採用面接", item_indexes=[1]),
            ]
        )
        records = [
            journal(
                "佐藤", "2026-08-10",
                work_items=[
                    WorkJournalItem(title="月次売上表の作成", description="月次売上表を作成した。"),
                    WorkJournalItem(title="採用面接", description="候補者と面接した。"),
                ],
                references=[WorkJournalReference(name="月次売上表.xlsx")],
            )
        ]
        with (
            patch.object(mining, "generate_structured", return_value=analysis),
            patch.object(mining, "embed_texts", return_value=[]),
        ):
            work_map = mining.build_work_map("経理・財務", "", "", records)

        by_name = {entry.task_name: entry for entry in work_map.profiles}
        self.assertEqual(by_name["月次売上集計"].document_names, ["月次売上表.xlsx"])
        self.assertEqual(by_name["採用面接"].document_names, [])


if __name__ == "__main__":
    unittest.main()


class WorkProfileTest(unittest.TestCase):
    def _clusters(self) -> list:
        from backend.app.schemas import WorkJournalTaskCluster

        return [
            WorkJournalTaskCluster(
                task_name="月次売上集計",
                summary="月次の売上を集計する作業。",
                participants=["佐藤"],
                occurrence_count=2,
                journal_dates=["2026-08-10", "2026-08-17"],
                single_owner=True,
            )
        ]

    def test_new_task_becomes_a_profile_entry_with_owners(self) -> None:
        with patch.object(mining, "embed_texts", return_value=[]):
            profiles = mining.merge_work_profiles(
                [],
                self._clusters(),
                {"月次売上集計": ["月次売上表.xlsx"]},
                {"月次売上集計": [("佐藤", "2026-08-10"), ("佐藤", "2026-08-17")]},
            )

        self.assertEqual(len(profiles), 1)
        entry = profiles[0]
        self.assertEqual(entry.task_name, "月次売上集計")
        self.assertEqual(entry.occurrence_count, 2)
        self.assertEqual([owner.participant for owner in entry.owners], ["佐藤"])
        self.assertEqual(entry.document_names, ["月次売上表.xlsx"])
        self.assertEqual(entry.first_journal_date, "2026-08-10")
        self.assertEqual(entry.last_journal_date, "2026-08-17")

    def test_reworded_task_name_is_absorbed_as_an_alias(self) -> None:
        from backend.app.schemas import WorkJournalTaskCluster, WorkProfileEntry

        known = [WorkProfileEntry(task_key="月次売上集計", task_name="月次売上集計")]
        clusters = [
            WorkJournalTaskCluster(
                task_name="月次 売上 集計",
                participants=["鈴木"],
                journal_dates=["2026-09-01"],
            )
        ]
        with patch.object(mining, "embed_texts", return_value=[]):
            profiles = mining.merge_work_profiles(
                known, clusters, {}, {"月次 売上 集計": [("鈴木", "2026-09-01")]}
            )

        self.assertEqual(len(profiles), 1)
        self.assertEqual(profiles[0].task_name, "月次売上集計")
        self.assertIn("月次 売上 集計", profiles[0].aliases)

    def test_embedding_similarity_merges_a_differently_worded_task(self) -> None:
        from backend.app.schemas import WorkJournalTaskCluster, WorkProfileEntry

        known = [
            WorkProfileEntry(
                task_key="月次売上集計",
                task_name="月次売上集計",
                embedding=[1.0, 0.0, 0.0],
            )
        ]
        clusters = [
            WorkJournalTaskCluster(
                task_name="売上の月次集計作業",
                participants=["鈴木"],
                journal_dates=["2026-09-01"],
            )
        ]
        with patch.object(mining, "embed_texts", return_value=[[0.99, 0.1, 0.0]]):
            profiles = mining.merge_work_profiles(
                known, clusters, {}, {"売上の月次集計作業": [("鈴木", "2026-09-01")]}
            )

        self.assertEqual(len(profiles), 1)
        self.assertIn("売上の月次集計作業", profiles[0].aliases)

    def test_unrelated_task_is_not_merged_by_embedding(self) -> None:
        from backend.app.schemas import WorkJournalTaskCluster, WorkProfileEntry

        known = [
            WorkProfileEntry(task_key="月次売上集計", task_name="月次売上集計", embedding=[1.0, 0.0, 0.0])
        ]
        clusters = [
            WorkJournalTaskCluster(task_name="採用面接", participants=["鈴木"], journal_dates=["2026-09-01"])
        ]
        with patch.object(mining, "embed_texts", return_value=[[0.0, 1.0, 0.0]]):
            profiles = mining.merge_work_profiles(
                known, clusters, {}, {"採用面接": [("鈴木", "2026-09-01")]}
            )

        self.assertEqual(len(profiles), 2)

    def test_known_task_names_are_offered_to_the_clustering_prompt(self) -> None:
        from backend.app.schemas import WorkProfileEntry

        analysis = mining.WorkJournalClusterAnalysis(
            clusters=[mining.WorkJournalClusterAssignment(task_name="月次売上集計", item_indexes=[0])]
        )
        records = [
            journal(
                "佐藤",
                "2026-09-01",
                work_items=[WorkJournalItem(title="月次の集計", description="売上を集計した。")],
            )
        ]
        with (
            patch.object(mining, "generate_structured", return_value=analysis) as generate,
            patch.object(mining, "embed_texts", return_value=[]),
        ):
            mining.build_work_map(
                "経理・財務",
                "",
                "",
                records,
                [WorkProfileEntry(task_key="月次売上集計", task_name="月次売上集計")],
            )

        prompt = generate.call_args.args[0]
        self.assertIn("known_task_names", prompt)
        self.assertIn("新しい言い換えを作らず", prompt)

    def test_profiles_round_trip_through_the_store(self) -> None:
        from backend.app.schemas import WorkProfileEntry

        with TemporaryDirectory() as directory:
            store = HinamiSQLiteStore(Path(directory) / "hinami.sqlite")
            store.save_work_profiles(
                [WorkProfileEntry(task_key="月次売上集計", task_name="月次売上集計", embedding=[0.1, 0.2])],
                org_unit_id="itsec001",
                tenant_id="default",
            )

            self.assertEqual(store.list_work_profiles("itsec001", "default")[0].embedding, [0.1, 0.2])
            self.assertEqual(store.list_work_profiles("mfg00001", "default"), [])
            self.assertEqual(store.list_work_profiles("itsec001", "east"), [])
