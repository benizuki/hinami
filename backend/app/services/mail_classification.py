"""メール傾向分析の分類マスターと集計。

件名・差出人はブラウザ側で判定して件数へ畳んでから届く。ここで扱うのは
分類の定義（マスター）と、保存済みの件数を組織・個人で足し合わせる処理だけで、
メールの中身はサーバーへ渡さない。
"""

from __future__ import annotations

from ..schemas import (
    MailRequestTypeRule,
    WorkJournalEmailCategoryCount,
)


MAIL_SOURCE_RULE_KIND = "source"
MAIL_REQUEST_TYPE_RULE_KIND = "request_type"

# 初回に配る既定の判定語。社内固有の申請名はここに足さず、管理画面から登録する。
DEFAULT_REQUEST_TYPE_RULES: tuple[dict[str, object], ...] = (
    {
        "id": "default-estimate",
        "name": "見積",
        "category": "見積",
        "keywords": ["見積", "御見積", "お見積", "相見積", "quotation", "quote"],
    },
    {
        "id": "default-order",
        "name": "発注",
        "category": "発注",
        "keywords": ["発注", "注文", "注文書", "購買依頼", "purchase order"],
    },
    {
        "id": "default-workflow",
        "name": "ワークフロー",
        "category": "ワークフロー",
        "keywords": ["承認依頼", "申請", "決裁", "稟議", "差戻", "ワークフロー"],
    },
    {
        "id": "default-survey",
        "name": "調査依頼",
        "category": "調査依頼",
        "keywords": ["調査依頼", "調査のお願い", "確認依頼", "確認のお願い", "ご確認ください"],
    },
    {
        "id": "default-answer",
        "name": "回答依頼",
        "category": "回答依頼",
        "keywords": ["回答依頼", "回答のお願い", "ご回答", "提出依頼", "期限", "締切"],
    },
    {
        "id": "default-notice",
        "name": "報告・通知",
        "category": "報告・通知",
        "keywords": ["報告", "通知", "お知らせ", "議事録", "完了しました"],
    },
)


def default_request_type_rules(now: str) -> list[MailRequestTypeRule]:
    """マスター未登録のテナントへ配る初期値。順番がそのまま判定順になる。"""
    return [
        MailRequestTypeRule(
            id=str(rule["id"]),
            name=str(rule["name"]),
            category=rule["category"],  # type: ignore[arg-type]
            source_ids=[],
            keywords=list(rule["keywords"]),  # type: ignore[arg-type]
            sort_order=index * 10,
            updated_at=now,
        )
        for index, rule in enumerate(DEFAULT_REQUEST_TYPE_RULES)
    ]


def _aggregation_key(count: WorkJournalEmailCategoryCount) -> str:
    # 古い日報にはrule_idが無い。表示名で束ねれば、マスターを作り直しても系列が続く。
    return f"{count.rule_id or ''}|{count.name}|{count.category}"


def merge_email_category_counts(
    groups: list[list[WorkJournalEmailCategoryCount]],
) -> list[WorkJournalEmailCategoryCount]:
    """日報ごとの分類件数を、同じ分類同士で足し合わせる。"""
    merged: dict[str, WorkJournalEmailCategoryCount] = {}
    for counts in groups:
        for count in counts:
            key = _aggregation_key(count)
            current = merged.get(key)
            if current is None:
                merged[key] = count.model_copy(deep=True)
                continue
            current.received += count.received
            current.sent += count.sent
            current.thread_count += count.thread_count
            if not current.source_name:
                current.source_id = count.source_id
                current.source_name = count.source_name
    return sorted(
        merged.values(),
        key=lambda item: (-(item.received + item.sent), item.name),
    )
