from __future__ import annotations

import re

from ..schemas import (
    WorkGraph,
    WorkGraphEdge,
    WorkGraphHotspot,
    WorkGraphNode,
    WorkJournalDocumentFlowReport,
    WorkProfileEntry,
)


# 業務グラフはLLMを使わず、蓄積した業務辞書と資料の受け渡し実績だけで構築する。
# 「どこにAI Agentを置くか」「どの属人化から手を付けるか」の2つを判断するための最小構成にする。


def _document_key(value: str) -> str:
    without_extension = re.sub(
        r"\.(pdf|xlsx?|docx?|pptx?|csv|png|jpe?g|webp)$", "", value.strip(), flags=re.IGNORECASE
    )
    return re.sub(r"[\s　_\-]", "", without_extension).lower()


def build_work_graph(
    department: str,
    date_from: str,
    date_to: str,
    profiles: list[WorkProfileEntry],
    flow_report: WorkJournalDocumentFlowReport,
) -> WorkGraph:
    nodes: dict[str, WorkGraphNode] = {}
    edges: list[WorkGraphEdge] = []

    flows_by_key = {flow.document_key: flow for flow in flow_report.flows}
    # 資料は正規化した名前でも引けるようにし、業務辞書側の表記揺れを吸収する。
    flows_by_name: dict[str, str] = {}
    for flow in flow_report.flows:
        for label in (flow.name, flow.document_title):
            key = _document_key(label)
            if key:
                flows_by_name.setdefault(key, flow.document_key)

    for flow in flow_report.flows:
        node_id = f"document:{flow.document_key}"
        nodes[node_id] = WorkGraphNode(
            id=node_id,
            kind="document",
            label=flow.document_title or flow.name,
            occurrence_count=len(flow.touches),
            owners=list(flow.participants),
        )
        for previous, current in zip(flow.touches, flow.touches[1:]):
            if previous.participant == current.participant:
                continue
            edges.append(
                WorkGraphEdge(
                    source=f"person:{previous.participant}",
                    target=f"person:{current.participant}",
                    kind="handoff",
                    weight=1,
                )
            )

    for profile in profiles:
        task_id = f"task:{profile.task_key}"
        owners = [owner.participant for owner in profile.owners]
        nodes[task_id] = WorkGraphNode(
            id=task_id,
            kind="task",
            label=profile.task_name,
            occurrence_count=profile.occurrence_count,
            owners=owners,
            single_owner=len(owners) == 1,
        )
        for owner in profile.owners:
            person_id = f"person:{owner.participant}"
            nodes.setdefault(
                person_id,
                WorkGraphNode(id=person_id, kind="person", label=owner.participant),
            )
            edges.append(
                WorkGraphEdge(
                    source=person_id,
                    target=task_id,
                    kind="owns",
                    weight=owner.occurrence_count,
                )
            )
        for document_name in profile.document_names:
            document_key = flows_by_name.get(_document_key(document_name))
            if not document_key:
                continue
            edges.append(
                WorkGraphEdge(
                    source=task_id,
                    target=f"document:{document_key}",
                    kind="uses",
                    weight=1,
                )
            )

    for edge in edges:
        for node_id in (edge.source, edge.target):
            if node_id.startswith("person:"):
                nodes.setdefault(
                    node_id,
                    WorkGraphNode(id=node_id, kind="person", label=node_id.split(":", 1)[1]),
                )

    graph = WorkGraph(
        department=department,
        date_from=date_from,
        date_to=date_to,
        nodes=sorted(nodes.values(), key=lambda node: (node.kind, node.label))[:600],
        edges=edges[:2000],
    )
    graph.automation_targets = _automation_targets(profiles, flows_by_name, flows_by_key)
    graph.key_person_risks = _key_person_risks(profiles, flows_by_name, flows_by_key)
    return graph


def _related_flows(
    profile: WorkProfileEntry,
    flows_by_name: dict[str, str],
    flows_by_key: dict[str, object],
) -> list:
    keys = {
        flows_by_name.get(_document_key(name))
        for name in profile.document_names
    }
    return [flows_by_key[key] for key in keys if key and key in flows_by_key]


def _automation_targets(
    profiles: list[WorkProfileEntry],
    flows_by_name: dict[str, str],
    flows_by_key: dict[str, object],
) -> list[WorkGraphHotspot]:
    """繰り返しが多く、受け渡しを伴う業務ほど、自動化の波及が大きい。"""
    hotspots: list[tuple[int, WorkGraphHotspot]] = []
    for profile in profiles:
        flows = _related_flows(profile, flows_by_name, flows_by_key)
        handoffs = sum(flow.handoff_count for flow in flows)
        people = sorted({participant for flow in flows for participant in flow.participants})
        if profile.occurrence_count < 2 and not handoffs:
            continue
        reasons = [f"{profile.occurrence_count}回の繰り返し"]
        if handoffs:
            reasons.append(f"資料の受け渡し{handoffs}回")
        if len(people) >= 2:
            reasons.append(f"{len(people)}名が関与")
        hotspots.append(
            (
                profile.occurrence_count * 2 + handoffs * 3 + len(people),
                WorkGraphHotspot(
                    node_id=f"task:{profile.task_key}",
                    label=profile.task_name,
                    kind="task",
                    reason="、".join(reasons) + "。手を入れると関係する人へ波及する。",
                    owners=[owner.participant for owner in profile.owners],
                    occurrence_count=profile.occurrence_count,
                    handoff_count=handoffs,
                    document_count=len(flows),
                    downstream_people=people,
                ),
            )
        )
    return [hotspot for _, hotspot in sorted(hotspots, key=lambda item: item[0], reverse=True)][:20]


def _key_person_risks(
    profiles: list[WorkProfileEntry],
    flows_by_name: dict[str, str],
    flows_by_key: dict[str, object],
) -> list[WorkGraphHotspot]:
    """担当が1人で、かつ後工程の人がいる業務ほど、止まったときの影響が大きい。"""
    hotspots: list[tuple[int, WorkGraphHotspot]] = []
    for profile in profiles:
        owners = [owner.participant for owner in profile.owners]
        if len(owners) != 1:
            continue
        flows = _related_flows(profile, flows_by_name, flows_by_key)
        downstream = sorted(
            {
                participant
                for flow in flows
                for participant in flow.participants
                if participant != owners[0]
            }
        )
        reasons = [f"{owners[0]}のみが記録", f"{profile.occurrence_count}回"]
        if downstream:
            reasons.append(f"止まると{len(downstream)}名の後工程へ影響")
        else:
            reasons.append("後工程への受け渡しは確認できていない")
        hotspots.append(
            (
                len(downstream) * 5 + profile.occurrence_count,
                WorkGraphHotspot(
                    node_id=f"task:{profile.task_key}",
                    label=profile.task_name,
                    kind="task",
                    reason="、".join(reasons) + "。",
                    owners=owners,
                    occurrence_count=profile.occurrence_count,
                    handoff_count=sum(flow.handoff_count for flow in flows),
                    document_count=len(flows),
                    downstream_people=downstream,
                ),
            )
        )
    return [hotspot for _, hotspot in sorted(hotspots, key=lambda item: item[0], reverse=True)][:20]
