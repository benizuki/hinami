from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class SQLiteBackupRecord(BaseModel):
    """作成済みSQLiteバックアップの一覧表示用メタデータ。"""

    id: str = Field(pattern=r"^hinami-\d{8}T\d{6}\d{6}Z-[a-f0-9]{8}$")
    filename: str
    created_at: str
    size_bytes: int = Field(ge=0)


class SQLiteTableStatistics(BaseModel):
    """SQLite内のユーザーテーブルごとの使用量。"""

    name: str
    row_count: int = Field(ge=0)
    table_bytes: int = Field(ge=0)
    index_bytes: int = Field(ge=0)
    total_bytes: int = Field(ge=0)


class SQLiteDatabaseStatistics(BaseModel):
    """バックアップ管理画面に表示する稼働SQLiteの統計。"""

    database_filename: str
    journal_mode: str
    last_modified_at: str
    database_bytes: int = Field(ge=0)
    wal_bytes: int = Field(ge=0)
    shm_bytes: int = Field(ge=0)
    active_files_bytes: int = Field(ge=0)
    allocated_bytes: int = Field(ge=0)
    logical_used_bytes: int = Field(ge=0)
    unused_bytes: int = Field(ge=0)
    usage_percent: float = Field(ge=0, le=100)
    total_records: int = Field(ge=0)
    table_count: int = Field(ge=0)
    backup_bytes: int = Field(ge=0)
    backup_count: int = Field(ge=0)
    tables: list[SQLiteTableStatistics] = Field(default_factory=list)


class SavedInterviewAttachment(BaseModel):
    id: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")
    name: str = Field(min_length=1, max_length=255)
    mime_type: Literal["image/png", "image/jpeg", "image/webp", "application/pdf"]
    size: int = Field(ge=0, le=8 * 1024 * 1024)
    uploaded_at: str = ""


class InterviewMessage(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=8000)
    attachments: list[SavedInterviewAttachment] = Field(default_factory=list, max_length=20)


class InterviewAttachment(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    mime_type: Literal["image/png", "image/jpeg", "image/webp", "application/pdf"]
    data: str = Field(min_length=1, max_length=12_000_000)


class AudioTranscriptionDecision(BaseModel):
    transcript: str = Field(max_length=8000)


class AudioTranscriptionResponse(AudioTranscriptionDecision):
    provider: str = "gemini-api"
    model: str = ""


SpeechTone = Literal["default", "calm", "friendly", "cheerful"]
SpeechPace = Literal["normal", "slow", "fast"]


class SpeechPreferences(BaseModel):
    """利用者ごとの読み上げの好み。voice が空ならシステムの既定の声を使う。"""

    voice: str = Field(default="", max_length=40)
    tone: SpeechTone = "default"
    pace: SpeechPace = "normal"


class SpeechOption(BaseModel):
    id: str
    label: str


class SpeechPreferencesResponse(SpeechPreferences):
    """保存済みの好みと、画面で選べる候補。"""

    default_voice: str
    voices: list[SpeechOption]
    tones: list[SpeechOption]
    paces: list[SpeechOption]


class SpeechSynthesisRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    # 保存前の試聴に使う。省くと、呼び出した利用者の保存済みの好みで読み上げる。
    preferences: SpeechPreferences | None = None


# 全社は全部門を統括するポジションを表す。配下に部門をぶら下げなくても、
# そのテナントの全組織を束ねる所属として扱う。
OrgUnitKind = Literal["全社", "部門", "課", "チーム", "その他"]


class OrgUnitRecord(BaseModel):
    """人の所属を表す組織単位。parent_idで階層を表す。"""

    id: str = Field(default="", max_length=80)
    tenant_id: str = ""
    parent_id: str = Field(default="", max_length=80)
    name: str = Field(min_length=1, max_length=120)
    kind: OrgUnitKind = "部門"
    sort_order: int = Field(default=0, ge=0, le=9999)
    updated_at: str = ""


class OrgUnitUpsert(BaseModel):
    parent_id: str = Field(default="", max_length=80)
    name: str = Field(min_length=1, max_length=120)
    kind: OrgUnitKind = "部門"
    sort_order: int = Field(default=0, ge=0, le=9999)


# メール傾向の分類軸。組織や期間をまたいで件数を比べるため、名称は固定で持つ。
MailCategory = Literal[
    "見積",
    "発注",
    "ワークフロー",
    "調査依頼",
    "回答依頼",
    "報告・通知",
    "その他",
]
MailSourceKind = Literal["system", "internal", "external"]
# 件名の判定語。長い文をそのまま入れても一致しないため、短めに制限する。
MailKeyword = Annotated[str, Field(min_length=1, max_length=80)]


class MailSourceRule(BaseModel):
    """差出人からメールの経路を判別するマスター。

    ワークフローシステムの通知は差出人が固定なので、件名を読む前に確実に切り分けられる。
    """

    id: str = Field(default="", max_length=80)
    name: str = Field(min_length=1, max_length=120)
    kind: MailSourceKind = "system"
    match_type: Literal["address", "domain"] = "address"
    # 照合は小文字化して行うため、保存時にも小文字へ寄せる。
    match_value: str = Field(min_length=1, max_length=255)
    default_category: MailCategory = "その他"
    sort_order: int = Field(default=0, ge=0, le=9999)
    updated_at: str = ""


class MailSourceRuleUpsert(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: MailSourceKind = "system"
    match_type: Literal["address", "domain"] = "address"
    match_value: str = Field(min_length=1, max_length=255)
    default_category: MailCategory = "その他"
    sort_order: int = Field(default=0, ge=0, le=9999)


class MailRequestTypeRule(BaseModel):
    """件名から申請・依頼の種別を判別するマスター。

    正規表現ではなく語句の部分一致にしているのは、管理者が書きやすいことと、
    ブラウザ側で評価しても危険な式が入り込まないようにするため。
    """

    id: str = Field(default="", max_length=80)
    name: str = Field(min_length=1, max_length=120)
    category: MailCategory = "その他"
    # 空なら全ての差出人が対象。指定すると、その経路から届いたメールだけを見る。
    source_ids: list[str] = Field(default_factory=list, max_length=20)
    keywords: list[MailKeyword] = Field(default_factory=list, max_length=20)
    sort_order: int = Field(default=0, ge=0, le=9999)
    updated_at: str = ""


class MailRequestTypeRuleUpsert(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    category: MailCategory = "その他"
    source_ids: list[str] = Field(default_factory=list, max_length=20)
    keywords: list[MailKeyword] = Field(default_factory=list, max_length=20)
    sort_order: int = Field(default=0, ge=0, le=9999)


class MailClassificationRules(BaseModel):
    sources: list[MailSourceRule] = Field(default_factory=list, max_length=200)
    request_types: list[MailRequestTypeRule] = Field(default_factory=list, max_length=200)


class WorkJournalMeetArtifact(BaseModel):
    kind: Literal["smart_note", "transcript"]
    state: str = Field(default="", max_length=40)
    url: str = Field(
        default="",
        max_length=1000,
        pattern=r"^$|^https://docs\.google\.com/",
    )


class WorkJournalCalendarEvent(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    start: str = Field(default="", max_length=80)
    end: str = Field(default="", max_length=80)
    all_day: bool = False
    private: bool = False
    response_status: Literal["", "accepted", "declined", "tentative", "needsAction"] = ""
    meet_code: str = Field(default="", max_length=64, pattern=r"^$|^[a-z0-9-]+$")
    meet_url: str = Field(
        default="",
        max_length=1000,
        pattern=r"^$|^https://meet\.google\.com/",
    )
    meet_participant_count: int | None = Field(default=None, ge=0, le=100_000)
    meet_artifacts: list[WorkJournalMeetArtifact] = Field(default_factory=list, max_length=20)


class WorkJournalEmailRequestCandidate(BaseModel):
    subject: str = Field(default="件名なし", max_length=255)
    sender: str = Field(default="", max_length=255)
    snippet: str = Field(default="", max_length=500)
    summary: str = Field(default="", max_length=500)
    url: str = Field(
        default="",
        max_length=1000,
        pattern=r"^$|^https://mail\.google\.com/",
    )


class WorkJournalEmailContext(BaseModel):
    received_count: int = Field(default=0, ge=0, le=1_000_000)
    sent_count: int = Field(default=0, ge=0, le=1_000_000)
    unread_count: int = Field(default=0, ge=0, le=1_000_000)
    request_candidates: list[WorkJournalEmailRequestCandidate] = Field(
        default_factory=list,
        max_length=8,
    )


class WorkJournalEmailSummaryRequest(WorkJournalEmailContext):
    pass


class WorkJournalSituationContext(BaseModel):
    local_datetime: str = Field(default="", max_length=80)
    timezone: str = Field(default="", max_length=80)
    time_of_day: Literal["朝", "昼", "夕方", "夜", ""] = ""
    weather_summary: str = Field(default="", max_length=160)


class WorkJournalAttachmentRef(BaseModel):
    """解析済みの資料は本文を再送しないため、dataは任意とする。"""

    name: str = Field(min_length=1, max_length=255)
    mime_type: Literal["image/png", "image/jpeg", "image/webp", "application/pdf"]
    data: str = Field(default="", max_length=12_000_000)


class WorkJournalAttachmentInsight(BaseModel):
    source_name: str = Field(default="", max_length=255)
    document_title: str = Field(default="", max_length=255)
    related_business: str = Field(default="未確認", max_length=255)
    content_summary: str = Field(default="", max_length=1200)
    key_topics: list[str] = Field(default_factory=list, max_length=8)


class WorkJournalAttachmentAnalysis(BaseModel):
    insights: list[WorkJournalAttachmentInsight] = Field(default_factory=list, max_length=4)


class WorkJournalAttachmentAnalysisRequest(BaseModel):
    attachments: list[InterviewAttachment] = Field(default_factory=list, max_length=4)


class WorkJournalRecentEntry(BaseModel):
    """過去に確定した日報のうち、思い出す手掛かりになる部分だけを渡す。"""

    journal_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    summary_items: list[str] = Field(default_factory=list, max_length=6)
    next_focus: str = Field(default="", max_length=500)


class WorkJournalItem(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=1000)
    result: str = Field(default="未確認", max_length=500)


class WorkJournalReference(BaseModel):
    """資料の識別に使う情報だけを保存し、本文や本文要約は保存しない。"""

    name: str = Field(min_length=1, max_length=255)
    url: str = Field(
        default="",
        max_length=2000,
        pattern=r"^$|^https://(?:drive|docs)\.google\.com/",
    )
    document_title: str = Field(default="", max_length=255)
    related_business: str = Field(default="", max_length=255)
    key_topics: list[str] = Field(default_factory=list, max_length=8)


class WorkJournalAnalysis(BaseModel):
    progressed_items: list[str] = Field(default_factory=list, max_length=30)
    ingenuity: list[str] = Field(default_factory=list, max_length=30)
    unplanned_work: list[str] = Field(default_factory=list, max_length=30)
    support_needed: list[str] = Field(default_factory=list, max_length=30)


class WorkJournalMeetingActivity(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    start: str = Field(default="", max_length=80)
    end: str = Field(default="", max_length=80)


class WorkJournalEmailCategoryCount(BaseModel):
    """分類ごとのメール件数。件名・差出人は残さず、この件数だけを保存する。"""

    rule_id: str = Field(default="", max_length=80)
    name: str = Field(min_length=1, max_length=120)
    category: MailCategory = "その他"
    source_id: str = Field(default="", max_length=80)
    source_name: str = Field(default="", max_length=120)
    received: int = Field(default=0, ge=0, le=100_000)
    sent: int = Field(default=0, ge=0, le=100_000)
    # スレッド数。同じ案件の往復を1件として数え、通知の回覧で件数が膨らむのを見分ける。
    thread_count: int = Field(default=0, ge=0, le=100_000)


class WorkJournalActivityContext(BaseModel):
    email_counts_available: bool = False
    received_email_count: int = Field(default=0, ge=0, le=1_000_000)
    sent_email_count: int = Field(default=0, ge=0, le=1_000_000)
    unread_email_count: int = Field(default=0, ge=0, le=1_000_000)
    # 分類は上限件数まで読んで打ち切るため、母数を残して件数と区別できるようにする。
    email_classified_count: int = Field(default=0, ge=0, le=1_000_000)
    email_categories: list[WorkJournalEmailCategoryCount] = Field(default_factory=list, max_length=60)
    participated_meetings: list[WorkJournalMeetingActivity] = Field(default_factory=list, max_length=30)


class WorkJournalDraft(BaseModel):
    summary: str = Field(default="", max_length=2000)
    summary_items: list[str] = Field(default_factory=list, max_length=12)
    work_items: list[WorkJournalItem] = Field(default_factory=list, max_length=30)
    next_focus: str = Field(default="", max_length=500)
    references: list[WorkJournalReference] = Field(default_factory=list, max_length=10)
    analysis: WorkJournalAnalysis = Field(default_factory=WorkJournalAnalysis)
    activity_context: WorkJournalActivityContext = Field(default_factory=WorkJournalActivityContext)


class WorkJournalTurnRequest(BaseModel):
    journal_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    department: str = Field(min_length=1, max_length=120)
    participant: str = Field(min_length=1, max_length=120)
    messages: list[InterviewMessage] = Field(default_factory=list, max_length=12)
    calendar_events: list[WorkJournalCalendarEvent] = Field(default_factory=list, max_length=30)
    email_context: WorkJournalEmailContext = Field(default_factory=WorkJournalEmailContext)
    attachments: list[WorkJournalAttachmentRef] = Field(default_factory=list, max_length=4)
    attachment_insights: list[WorkJournalAttachmentInsight] = Field(default_factory=list, max_length=4)
    recent_journals: list[WorkJournalRecentEntry] = Field(default_factory=list, max_length=3)
    situation_context: WorkJournalSituationContext = Field(default_factory=WorkJournalSituationContext)


class WorkJournalTurnDecision(BaseModel):
    reply: str = Field(min_length=1, max_length=4000)
    progress: int = Field(default=0, ge=0, le=100)
    is_complete: bool = False
    draft: WorkJournalDraft | None = None


class WorkJournalTurnResponse(WorkJournalTurnDecision):
    provider: str = "gemini-api"
    model: str = ""


class WorkJournalSaveRequest(WorkJournalDraft):
    journal_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    # org_unit_idが正で、org_unit_nameは表示用。department系は移行前のレコード用に残す。
    org_unit_id: str = Field(default="", max_length=80)
    org_unit_name: str = Field(default="", max_length=120)
    department_id: str = Field(default="", max_length=80)
    department: str = Field(default="", max_length=120)
    participant: str = Field(min_length=1, max_length=120)


class WorkJournalRecord(WorkJournalSaveRequest):
    owner_email: str = ""
    created_at: str = ""
    updated_at: str = ""


class WorkJournalMemberSummary(BaseModel):
    """業務日報を閲覧できる相手の一覧。manager が配下メンバーを選ぶために使う。"""

    email: str = Field(min_length=1, max_length=254)
    name: str = Field(default="", max_length=120)
    org_unit_id: str = ""
    org_unit_name: str = ""
    is_self: bool = False


class WorkJournalMemberActivity(BaseModel):
    """組織共有では所属名で識別し、メールアドレスは出さない。"""

    participant: str = Field(min_length=1, max_length=120)
    journal_count: int = Field(default=0, ge=0)
    latest_journal_date: str = ""
    progressed_items: list[str] = Field(default_factory=list, max_length=60)
    ingenuity: list[str] = Field(default_factory=list, max_length=60)
    unplanned_work: list[str] = Field(default_factory=list, max_length=60)
    support_needed: list[str] = Field(default_factory=list, max_length=60)
    # メール分類を残した日報の数。件数を人ごとに比べるときの母数になる。
    email_classified_journal_count: int = Field(default=0, ge=0)
    email_categories: list[WorkJournalEmailCategoryCount] = Field(default_factory=list, max_length=60)


class WorkJournalOrganizationActivity(BaseModel):
    org_unit_id: str = ""
    org_unit_name: str = ""
    date_from: str = ""
    date_to: str = ""
    journal_count: int = Field(default=0, ge=0)
    email_classified_journal_count: int = Field(default=0, ge=0)
    email_categories: list[WorkJournalEmailCategoryCount] = Field(default_factory=list, max_length=60)
    members: list[WorkJournalMemberActivity] = Field(default_factory=list, max_length=200)


class WorkProfileOwner(BaseModel):
    participant: str = Field(min_length=1, max_length=120)
    occurrence_count: int = Field(default=0, ge=0)
    last_journal_date: str = ""


class WorkProfileEntry(BaseModel):
    """組織で繰り返される業務の正規形。日報を重ねるほど業務名の揺れが減る。"""

    task_key: str = Field(min_length=1, max_length=200)
    task_name: str = Field(min_length=1, max_length=160)
    summary: str = Field(default="", max_length=600)
    aliases: list[str] = Field(default_factory=list, max_length=40)
    document_names: list[str] = Field(default_factory=list, max_length=40)
    owners: list[WorkProfileOwner] = Field(default_factory=list, max_length=200)
    occurrence_count: int = Field(default=0, ge=0)
    first_journal_date: str = ""
    last_journal_date: str = ""
    embedding: list[float] = Field(default_factory=list, max_length=4096)
    updated_at: str = ""


class WorkJournalDocumentTouch(BaseModel):
    participant: str = Field(min_length=1, max_length=120)
    journal_date: str = ""
    action: Literal["作成", "更新", "確認", "未確認"] = "未確認"


class WorkJournalDocumentFlow(BaseModel):
    """同じ資料が複数人の日報に現れた流れ。Excelバケツリレーの検出に使う。"""

    document_key: str = ""
    name: str = Field(min_length=1, max_length=255)
    document_title: str = ""
    related_business: str = ""
    url: str = ""
    touches: list[WorkJournalDocumentTouch] = Field(default_factory=list, max_length=200)
    participants: list[str] = Field(default_factory=list, max_length=60)
    handoff_count: int = Field(default=0, ge=0)
    is_relay: bool = False


class WorkJournalDocumentFlowReport(BaseModel):
    org_unit_id: str = ""
    org_unit_name: str = ""
    date_from: str = ""
    date_to: str = ""
    flows: list[WorkJournalDocumentFlow] = Field(default_factory=list, max_length=200)


class WorkJournalTaskCluster(BaseModel):
    task_name: str = Field(min_length=1, max_length=160)
    summary: str = Field(default="", max_length=600)
    participants: list[str] = Field(default_factory=list, max_length=60)
    occurrence_count: int = Field(default=0, ge=0)
    journal_dates: list[str] = Field(default_factory=list, max_length=200)
    single_owner: bool = False


class WorkJournalWorkMap(BaseModel):
    org_unit_id: str = ""
    org_unit_name: str = ""
    date_from: str = ""
    date_to: str = ""
    clusters: list[WorkJournalTaskCluster] = Field(default_factory=list, max_length=60)
    profiles: list[WorkProfileEntry] = Field(default_factory=list, max_length=200, exclude=True)
    provider: str = "gemini-api"
    model: str = ""


class WorkGraphNode(BaseModel):
    id: str = Field(min_length=1, max_length=260)
    kind: Literal["task", "person", "document"]
    label: str = Field(min_length=1, max_length=260)
    occurrence_count: int = Field(default=0, ge=0)
    owners: list[str] = Field(default_factory=list, max_length=60)
    single_owner: bool = False


class WorkGraphEdge(BaseModel):
    source: str = Field(min_length=1, max_length=260)
    target: str = Field(min_length=1, max_length=260)
    kind: Literal["owns", "uses", "handoff"]
    weight: int = Field(default=1, ge=0)


class WorkGraphHotspot(BaseModel):
    """順位付けの根拠を数値のまま持たせ、スコアだけで判断させない。"""

    node_id: str = Field(min_length=1, max_length=260)
    label: str = Field(min_length=1, max_length=260)
    kind: Literal["task", "document"]
    reason: str = Field(default="", max_length=400)
    owners: list[str] = Field(default_factory=list, max_length=60)
    occurrence_count: int = Field(default=0, ge=0)
    handoff_count: int = Field(default=0, ge=0)
    document_count: int = Field(default=0, ge=0)
    downstream_people: list[str] = Field(default_factory=list, max_length=60)


class WorkGraph(BaseModel):
    org_unit_id: str = ""
    org_unit_name: str = ""
    date_from: str = ""
    date_to: str = ""
    nodes: list[WorkGraphNode] = Field(default_factory=list, max_length=600)
    edges: list[WorkGraphEdge] = Field(default_factory=list, max_length=2000)
    automation_targets: list[WorkGraphHotspot] = Field(default_factory=list, max_length=20)
    key_person_risks: list[WorkGraphHotspot] = Field(default_factory=list, max_length=20)


class WorkJournalDigestRequest(BaseModel):
    org_unit_id: str = Field(min_length=1, max_length=80)
    date_from: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    date_to: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class WorkJournalDigestItem(BaseModel):
    summary: str = Field(min_length=1, max_length=400)
    members: list[str] = Field(default_factory=list, max_length=30)


class WorkJournalOrganizationDigest(BaseModel):
    overview: str = Field(default="", max_length=1200)
    progress: list[WorkJournalDigestItem] = Field(default_factory=list, max_length=8)
    ingenuity: list[WorkJournalDigestItem] = Field(default_factory=list, max_length=8)
    unplanned_work: list[WorkJournalDigestItem] = Field(default_factory=list, max_length=8)
    support_needed: list[WorkJournalDigestItem] = Field(default_factory=list, max_length=8)
    collaboration_hints: list[str] = Field(default_factory=list, max_length=6)


class WorkJournalDigestResponse(WorkJournalOrganizationDigest):
    activity: WorkJournalOrganizationActivity = Field(
        default_factory=WorkJournalOrganizationActivity
    )
    provider: str = "gemini-api"
    model: str = ""


AiProposalKind = Literal["agent", "assist", "automation", "process-change", "human", "needs-info"]
AiProposalPriority = Literal["high", "medium", "low"]
AiCapability = Literal[
    "読む・抽出",
    "検索・要約",
    "照合・構造化",
    "判断支援",
    "文面生成",
    "システム操作",
    "監視・催促",
]


class ProcessAiProposalDraft(BaseModel):
    """Geminiが返す提案。工程IDと分類だけを受け取り、事実はリクエスト側から補う。"""

    step_ids: list[str] = Field(default_factory=list, max_length=20)
    kind: AiProposalKind = "needs-info"
    priority: AiProposalPriority = "low"
    title: str = Field(default="", max_length=120)
    summary: str = Field(default="", max_length=400)
    ecrs: list[Literal["E", "C", "R", "S"]] = Field(min_length=1, max_length=4)
    before: str = Field(min_length=1, max_length=800)
    after: str = Field(min_length=1, max_length=800)
    improvement_actions: list[str] = Field(min_length=1, max_length=8)
    capabilities: list[AiCapability] = Field(default_factory=list, max_length=7)
    ai_actions: list[str] = Field(default_factory=list, max_length=6)
    reasons: list[str] = Field(default_factory=list, max_length=6)
    expected_benefits: list[str] = Field(default_factory=list, max_length=6)
    human_role: str = Field(default="", max_length=300)
    requirements: list[str] = Field(default_factory=list, max_length=8)
    risks: list[str] = Field(default_factory=list, max_length=8)
    missing_information: list[str] = Field(default_factory=list, max_length=8)


class ProcessAiProposalDataItem(BaseModel):
    name: str = ""
    type: str = ""
    relation: str = ""


class ProcessAiProposal(ProcessAiProposalDraft):
    """検証済みの提案。工程名・データ・システムは入力の事実だけで埋める。"""

    id: str = ""
    actor: str = ""
    step_labels: list[str] = Field(default_factory=list)
    input_data: list[ProcessAiProposalDataItem] = Field(default_factory=list)
    output_data: list[ProcessAiProposalDataItem] = Field(default_factory=list)
    system_names: list[str] = Field(default_factory=list)
    evidence_level: Literal["高", "中", "低"] = "低"


class ProcessAiOpportunityResponse(BaseModel):
    proposals: list[ProcessAiProposal] = Field(default_factory=list)
    recommended_count: int = 0
    agent_candidate_count: int = 0
    assist_candidate_count: int = 0
    automation_candidate_count: int = 0
    needs_info_count: int = 0
    uncovered_step_labels: list[str] = Field(default_factory=list)
    provider: str = "gemini-api"
    model: str = ""
    generated_at: str = ""


class AiUsageUserRow(BaseModel):
    user_email: str = ""
    calls: int = 0
    total_duration_ms: int = 0
    errors: int = 0
    rate_limited: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class AiUsageFeatureRow(BaseModel):
    feature: str = ""
    calls: int = 0
    total_duration_ms: int = 0
    total_tokens: int = 0


class AiUsageDayRow(BaseModel):
    day: str = ""
    calls: int = 0
    total_tokens: int = 0


class AiUsageReport(BaseModel):
    date_from: str = ""
    date_to: str = ""
    scope: Literal["tenant", "self"] = "self"
    total_calls: int = 0
    total_tokens: int = 0
    rate_limit_per_minute: int = 0
    rate_limit_per_day: int = 0
    used_today: int = 0
    by_user: list[AiUsageUserRow] = Field(default_factory=list)
    by_feature: list[AiUsageFeatureRow] = Field(default_factory=list)
    by_day: list[AiUsageDayRow] = Field(default_factory=list)


class GeminiSettings(BaseModel):
    """Gemini APIキーの設定状況。キーそのものは返さない。"""

    # environment … GEMINI_API_KEY（画面からは変更できない）
    # stored      … 画面から登録したキー
    # none        … 未設定
    source: Literal["environment", "stored", "none"]
    configured: bool
    # 登録したキーの見分けに使う末尾4文字。
    key_hint: str | None = None


class GoogleIntegrationSettings(BaseModel):
    """Google連携を機能ごとに有効にするか。Meetはカレンダーが有効なときだけ使える。"""

    calendar: bool = True
    meet: bool = True
    gmail: bool = True
    drive: bool = True


class AppModeSettings(BaseModel):
    """動作モード。diary=日記寄り、work=業務より。画面の言葉づかいだけが変わる。"""

    mode: Literal["diary", "work"] = "diary"


class GoogleCloudAuthSettings(BaseModel):
    """② Vertex AI（Google Cloud）への接続。Vertex AI と Cloud Text-to-Speech で共通に使う。"""

    # 空なら GOOGLE_CLOUD_PROJECT / GOOGLE_CLOUD_LOCATION に従う。
    project: str = Field(default="", max_length=30)
    location: str = Field(default="", max_length=40)
    # Kubernetes 上でだけ使う Workload Identity 連携の識別子（任意）。
    wif_project_number: str = Field(default="", max_length=20)
    wif_pool_id: str = Field(default="", max_length=32)
    wif_provider_id: str = Field(default="", max_length=32)
    wif_service_account: str = Field(default="", max_length=120)


class GoogleCloudEnvironment(BaseModel):
    project: str
    location: str


class GoogleCloudSettingsResponse(GoogleCloudAuthSettings):
    # 画面で空のときに使われる、環境変数の値。
    environment: GoogleCloudEnvironment
    # いま使われる認証。Kubernetes 上で WIF が設定されていれば wif、それ以外は adc（google.auth.default）。
    active_auth: Literal["adc", "wif"]
    running_on_kubernetes: bool


AiConnection = Literal["gemini-api", "vertex"]
SpeechEngine = Literal["gemini-tts", "cloud-tts"]


class AiModelSettings(BaseModel):
    """役割ごとの接続方法とモデル。空の項目は環境変数に従う。

    接続方法: gemini-api（① Gemini API キー）/ vertex（② Vertex AI）。
    読み上げは方式で接続方法が決まる（gemini-tts は ①、cloud-tts は ②）。
    """

    chat_connection: Literal["", "gemini-api", "vertex"] = ""
    chat_model: str = Field(default="", max_length=100)
    transcription_connection: Literal["", "gemini-api", "vertex"] = ""
    transcription_model: str = Field(default="", max_length=100)
    speech_engine: Literal["", "gemini-tts", "cloud-tts"] = ""
    speech_model: str = Field(default="", max_length=100)


class AiModelValues(BaseModel):
    chat_connection: AiConnection
    chat_model: str
    transcription_connection: AiConnection
    transcription_model: str
    speech_engine: SpeechEngine
    speech_model: str


class AiModelSettingsResponse(AiModelSettings):
    # 画面で何も選んでいないときの値（環境変数とその既定）と、実際に使われる値。
    environment: AiModelValues
    effective: AiModelValues


class WorkloadIdentityInfo(BaseModel):
    """GCP 側で信頼を登録するための値。どれも秘密ではない。"""

    subject: str
    namespace: str
    service_account: str
    issuer: str
    jwks: dict


class ConnectionCheckResult(BaseModel):
    ok: bool
    # credentials: 認証情報の用意 / sts: トークンの交換 / api: サービスへの問い合わせ
    step: Literal["credentials", "sts", "api"]
    message: str


class GeminiApiKeyUpdate(BaseModel):
    api_key: str = Field(min_length=1, max_length=512)


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    llm_configured: bool
    # provider/model は運用者向けの情報なので、本番では返さない。
    provider: str | None = None
    model: str | None = None


AuthRole = Literal["admin", "manager", "user", "viewer"]
# システムロールは3種。admin=全テナントの管理、viewer=全テナントの閲覧、
# none=システム権限なし（所属テナントの権限だけで動く）。
SystemRole = Literal["none", "admin", "viewer"]


class TenantMembership(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=80)
    role: AuthRole = "viewer"
    # 組織はテナントごとに別なので、所属もテナントごとに持つ。
    org_unit_id: str = Field(default="", max_length=80)


class TenantRecord(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    enabled: bool = True
    created_at: str | None = None
    updated_at: str | None = None


class TenantUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    enabled: bool = True


class AuthConfig(BaseModel):
    google_oauth_enabled: bool
    google_client_id: str = ""


class AuthGoogleLoginRequest(BaseModel):
    # Google IDトークンは通常1KB前後。検証へ進む前に桁違いの入力を弾く。
    credential: str = Field(min_length=1, max_length=8192)


class AuthUser(BaseModel):
    email: str
    name: str
    google_subject: str | None = None
    oauth_name: str | None = None
    oauth_picture: str | None = None
    department: str | None = None
    department_id: str | None = None
    org_unit_id: str | None = None
    role: SystemRole
    tenant_memberships: list[TenantMembership] = Field(default_factory=list)


class AuthLoginResponse(BaseModel):
    token: str | None = None
    user: AuthUser


class UserMasterEntry(BaseModel):
    email: str
    name: str
    department: str | None = None
    department_id: str | None = None
    org_unit_id: str | None = None
    role: SystemRole = "none"
    tenant_memberships: list[TenantMembership] = Field(default_factory=list)
    enabled: bool = True
    google_subject: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class UserMasterUpdate(BaseModel):
    email: str | None = None
    name: str
    department: str | None = None
    department_id: str | None = None
    org_unit_id: str | None = None
    role: SystemRole = "none"
    tenant_memberships: list[TenantMembership] = Field(default_factory=list)
    enabled: bool = True
    google_subject: str | None = None
