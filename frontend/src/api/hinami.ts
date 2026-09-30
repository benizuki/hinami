export interface LlmInterviewMessage {
  role: 'user' | 'assistant'
  text: string
  attachments?: SavedInterviewAttachment[]
}

export interface SavedInterviewAttachment {
  id: string
  name: string
  mime_type: 'image/png' | 'image/jpeg' | 'image/webp' | 'application/pdf'
  size: number
  uploaded_at: string
}

export interface LlmInterviewAttachment {
  name: string
  mime_type: 'image/png' | 'image/jpeg' | 'image/webp' | 'application/pdf'
  data: string
}

export interface AudioTranscriptionResponse {
  transcript: string
  provider: string
  model: string
}

export interface WorkJournalCalendarEvent {
  title: string
  start: string
  end: string
  all_day: boolean
  private: boolean
  response_status: '' | 'accepted' | 'declined' | 'tentative' | 'needsAction'
  meet_code: string
  meet_url: string
  meet_participant_count: number | null
  meet_artifacts: WorkJournalMeetArtifact[]
}

export interface WorkJournalMeetArtifact {
  kind: 'smart_note' | 'transcript'
  state: string
  url: string
}

export interface WorkJournalEmailRequestCandidate {
  subject: string
  sender: string
  snippet: string
  summary: string
  url: string
}

export interface WorkJournalEmailContext {
  received_count: number
  sent_count: number
  unread_count: number
  request_candidates: WorkJournalEmailRequestCandidate[]
}

export interface WorkJournalSituationContext {
  local_datetime: string
  timezone: string
  time_of_day: '朝' | '昼' | '夕方' | '夜' | ''
  weather_summary: string
}

export interface WorkJournalAttachmentInsight {
  source_name: string
  document_title: string
  related_business: string
  content_summary: string
  key_topics: string[]
}

export interface WorkJournalRecentEntry {
  journal_date: string
  summary_items: string[]
  next_focus: string
}

export interface WorkJournalItem {
  title: string
  description: string
  result: string
}

export interface WorkJournalReference {
  name: string
  url: string
  document_title?: string
  related_business?: string
  key_topics?: string[]
}

export interface WorkJournalDocumentTouch {
  participant: string
  journal_date: string
  action: '作成' | '更新' | '確認' | '未確認'
}

export interface WorkJournalDocumentFlow {
  document_key: string
  name: string
  document_title: string
  related_business: string
  url: string
  touches: WorkJournalDocumentTouch[]
  participants: string[]
  handoff_count: number
  is_relay: boolean
}

export interface WorkJournalDocumentFlowReport {
  org_unit_id: string
  org_unit_name: string
  date_from: string
  date_to: string
  flows: WorkJournalDocumentFlow[]
}

export interface WorkJournalTaskCluster {
  task_name: string
  summary: string
  participants: string[]
  occurrence_count: number
  journal_dates: string[]
  single_owner: boolean
}

// 全社は全部門を統括するポジション。配下を持たなくてもテナント全体を範囲にする。
export type OrgUnitKind = '全社' | '部門' | '課' | 'チーム' | 'その他'

export interface OrgUnitRecord {
  id: string
  tenant_id: string
  parent_id: string
  name: string
  kind: OrgUnitKind
  sort_order: number
  updated_at: string
}

export type MailCategory = '見積' | '発注' | 'ワークフロー' | '調査依頼' | '回答依頼' | '報告・通知' | 'その他'
export type MailSourceKind = 'system' | 'internal' | 'external'

/** 差出人からメールの経路を判別するマスター。通知アドレスが固定の系統に効く。 */
export interface MailSourceRule {
  id: string
  name: string
  kind: MailSourceKind
  match_type: 'address' | 'domain'
  match_value: string
  default_category: MailCategory
  sort_order: number
  updated_at: string
}

/** 件名から申請・依頼の種別を判別するマスター。判定は語句の部分一致で行う。 */
export interface MailRequestTypeRule {
  id: string
  name: string
  category: MailCategory
  /** 空なら全ての差出人が対象。 */
  source_ids: string[]
  keywords: string[]
  sort_order: number
  updated_at: string
}

export interface MailClassificationRules {
  sources: MailSourceRule[]
  request_types: MailRequestTypeRule[]
}

export interface WorkJournalEmailCategoryCount {
  rule_id: string
  name: string
  category: MailCategory
  source_id: string
  source_name: string
  received: number
  sent: number
  thread_count: number
}

export interface WorkJournalMemberActivity {
  participant: string
  journal_count: number
  latest_journal_date: string
  progressed_items: string[]
  ingenuity: string[]
  unplanned_work: string[]
  support_needed: string[]
  email_classified_journal_count: number
  email_categories: WorkJournalEmailCategoryCount[]
}

export interface WorkJournalOrganizationActivity {
  org_unit_id: string
  org_unit_name: string
  date_from: string
  date_to: string
  journal_count: number
  email_classified_journal_count: number
  email_categories: WorkJournalEmailCategoryCount[]
  members: WorkJournalMemberActivity[]
}

export interface WorkJournalDigestItem {
  summary: string
  members: string[]
}

export interface WorkJournalOrganizationDigest {
  overview: string
  progress: WorkJournalDigestItem[]
  ingenuity: WorkJournalDigestItem[]
  unplanned_work: WorkJournalDigestItem[]
  support_needed: WorkJournalDigestItem[]
  collaboration_hints: string[]
  activity: WorkJournalOrganizationActivity
}

export interface WorkGraphHotspot {
  node_id: string
  label: string
  kind: 'task' | 'document'
  reason: string
  owners: string[]
  occurrence_count: number
  handoff_count: number
  document_count: number
  downstream_people: string[]
}

export interface WorkGraph {
  org_unit_id: string
  org_unit_name: string
  date_from: string
  date_to: string
  nodes: Array<{ id: string; kind: 'task' | 'person' | 'document'; label: string; occurrence_count: number; owners: string[]; single_owner: boolean }>
  edges: Array<{ source: string; target: string; kind: 'owns' | 'uses' | 'handoff'; weight: number }>
  automation_targets: WorkGraphHotspot[]
  key_person_risks: WorkGraphHotspot[]
}

export interface WorkJournalWorkMap {
  org_unit_id: string
  org_unit_name: string
  date_from: string
  date_to: string
  clusters: WorkJournalTaskCluster[]
}

export interface WorkJournalAnalysis {
  progressed_items: string[]
  ingenuity: string[]
  unplanned_work: string[]
  support_needed: string[]
}

export interface WorkJournalMeetingActivity {
  title: string
  start: string
  end: string
}

export interface WorkJournalActivityContext {
  email_counts_available: boolean
  received_email_count: number
  sent_email_count: number
  unread_email_count: number
  /** 分類のために件名を読んだ通数。上限で打ち切るため、受信件数とは一致しないことがある。 */
  email_classified_count: number
  email_categories: WorkJournalEmailCategoryCount[]
  participated_meetings: WorkJournalMeetingActivity[]
}

export interface WorkJournalDraft {
  summary: string
  summary_items: string[]
  work_items: WorkJournalItem[]
  next_focus: string
  references: WorkJournalReference[]
  analysis: WorkJournalAnalysis
  activity_context: WorkJournalActivityContext
}

export interface WorkJournalTurnResponse {
  reply: string
  progress: number
  is_complete: boolean
  draft: WorkJournalDraft | null
  provider: string
  model: string
}

export interface WorkJournalRecord extends WorkJournalDraft {
  journal_date: string
  org_unit_id: string
  org_unit_name: string
  department_id?: string
  department?: string
  participant: string
  owner_email: string
  created_at: string
  updated_at: string
}

// managerは編集権限はuser相当で、加えて自組織配下メンバーの業務日報を閲覧できる。
export type AuthRole = 'admin' | 'manager' | 'user' | 'viewer'
/**
 * システムロール。admin=全テナントの管理、viewer=全テナントの閲覧、
 * none=システム権限なし（所属テナントの権限だけで動く）。
 */
export type SystemRole = 'none' | 'admin' | 'viewer'

export interface TenantMembership {
  tenant_id: string
  role: AuthRole
  /** 組織はテナントごとに別なので、所属もテナントごとに持つ。 */
  org_unit_id?: string
}

export interface TenantRecord {
  id: string
  name: string
  description: string
  enabled: boolean
  created_at?: string | null
  updated_at?: string | null
}

export interface AuthConfig {
  google_oauth_enabled: boolean
  google_client_id: string
  // メールアドレスだけで入れるお試しログイン（Docker Composeの体験用）
  demo_login_enabled?: boolean
}

export interface AuthUser {
  email: string
  name: string
  google_subject?: string | null
  oauth_name?: string | null
  oauth_picture?: string | null
  department?: string | null
  department_id?: string | null
  org_unit_id?: string | null
  role: SystemRole
  tenant_memberships: TenantMembership[]
}

export interface AuthLoginResponse {
  token?: string | null
  user: AuthUser
}

export interface UserMasterEntry {
  email: string
  name: string
  department?: string | null
  department_id?: string | null
  org_unit_id?: string | null
  role: SystemRole
  tenant_memberships: TenantMembership[]
  enabled: boolean
  google_subject?: string | null
  created_at?: string | null
  updated_at?: string | null
}

// Authentication is held by an HttpOnly cookie and sent automatically by the
// browser. The active tenant is only a non-sensitive UI preference; the
// backend still validates tenant access on every request.
const ACTIVE_TENANT_COOKIE_NAME = 'hinami_active_tenant'
const PREFERENCE_COOKIE_MAX_AGE = 60 * 60 * 24 * 365

function readCookie(name: string) {
  if (typeof document === 'undefined') return ''
  const prefix = `${name}=`
  const value = document.cookie
    .split('; ')
    .find((item) => item.startsWith(prefix))
    ?.slice(prefix.length)
  return value ? decodeURIComponent(value) : ''
}

function writeCookie(name: string, value: string) {
  if (typeof document === 'undefined') return
  document.cookie = `${name}=${encodeURIComponent(value)}; Max-Age=${PREFERENCE_COOKIE_MAX_AGE}; Path=/; SameSite=Lax`
}

let activeTenantId = readCookie(ACTIVE_TENANT_COOKIE_NAME) || 'default'

export function getActiveTenantId() {
  return activeTenantId
}

export function setActiveTenantId(tenantId: string) {
  activeTenantId = tenantId.trim().toLowerCase() || 'default'
  writeCookie(ACTIVE_TENANT_COOKIE_NAME, activeTenantId)
}

async function authFetch(input: RequestInfo | URL, init: RequestInit = {}) {
  const headers = new Headers(init.headers || {})
  headers.set('X-Tenant-ID', activeTenantId)
  return fetch(input, { ...init, credentials: init.credentials ?? 'include', headers })
}

export async function getAuthConfig(): Promise<AuthConfig> {
  const response = await fetch('/api/auth/config')
  if (!response.ok) throw new Error('認証設定を取得できませんでした。')
  return await response.json() as AuthConfig
}

export async function loginWithGoogleCredential(credential: string): Promise<AuthLoginResponse> {
  const response = await fetch('/api/auth/google', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ credential }),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `GoogleログインAPI error: ${response.status}`)
  }
  const result = await response.json() as AuthLoginResponse
  return result
}

export async function loginWithDemoEmail(email: string): Promise<AuthLoginResponse> {
  const response = await fetch('/api/auth/demo', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string | { msg?: string }[] }
    const detail = Array.isArray(body.detail) ? 'メールアドレスの形式が正しくありません。' : body.detail
    throw new Error(detail || `お試しログインAPI error: ${response.status}`)
  }
  return await response.json() as AuthLoginResponse
}

export async function getCurrentUser(): Promise<AuthUser> {
  const response = await authFetch('/api/auth/me')
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `ログイン状態確認API error: ${response.status}`)
  }
  return await response.json() as AuthUser
}

export async function logout(): Promise<void> {
  await authFetch('/api/auth/logout', { method: 'POST' }).catch(() => undefined)
}

export async function getUsers(): Promise<UserMasterEntry[]> {
  const response = await authFetch('/api/users')
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `ユーザー一覧API error: ${response.status}`)
  }
  return await response.json() as UserMasterEntry[]
}

export async function getTenants(): Promise<TenantRecord[]> {
  const response = await authFetch('/api/tenants')
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `テナント一覧API error: ${response.status}`)
  }
  return await response.json() as TenantRecord[]
}

export async function saveTenant(tenant: TenantRecord, originalId?: string): Promise<TenantRecord> {
  const response = await authFetch(originalId ? `/api/tenants/${encodeURIComponent(originalId)}` : '/api/tenants', {
    method: originalId ? 'PUT' : 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(tenant),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `テナント保存API error: ${response.status}`)
  }
  return await response.json() as TenantRecord
}

export async function saveUser(user: UserMasterEntry, originalEmail?: string): Promise<UserMasterEntry> {
  const response = await authFetch(originalEmail ? `/api/users/${encodeURIComponent(originalEmail)}` : '/api/users', {
    method: originalEmail ? 'PUT' : 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(user),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `ユーザー保存API error: ${response.status}`)
  }
  return await response.json() as UserMasterEntry
}

export async function deleteUser(email: string): Promise<void> {
  const response = await authFetch(`/api/users/${encodeURIComponent(email)}`, { method: 'DELETE' })
  if (!response.ok && response.status !== 404) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `ユーザー削除API error: ${response.status}`)
  }
}

export async function requestWorkJournalTurn(payload: {
  journal_date: string
  department: string
  participant: string
  messages: LlmInterviewMessage[]
  calendar_events: WorkJournalCalendarEvent[]
  email_context: WorkJournalEmailContext
  attachments: Array<Omit<LlmInterviewAttachment, 'data'> & { data: string }>
  attachment_insights: WorkJournalAttachmentInsight[]
  recent_journals: WorkJournalRecentEntry[]
  situation_context: WorkJournalSituationContext
}, signal?: AbortSignal): Promise<WorkJournalTurnResponse> {
  // 解析済みの資料は本文を送らないため、待ち時間も短くて済む。
  const timeout = payload.attachments.some((attachment) => attachment.data) ? 240_000 : 120_000
  return postJson<WorkJournalTurnResponse>('/api/work-journal/turn', payload, timeout, signal)
}

export async function analyzeWorkJournalAttachments(
  attachments: LlmInterviewAttachment[],
): Promise<WorkJournalAttachmentInsight[]> {
  const body = await postJson<{ insights: WorkJournalAttachmentInsight[] }>(
    '/api/work-journal/attachment-insights',
    { attachments },
    240_000,
  )
  return body.insights ?? []
}

export async function summarizeWorkJournalEmails(payload: WorkJournalEmailContext): Promise<WorkJournalEmailContext> {
  const response = await authFetch('/api/work-journal/email-summary', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `メール要約API error: ${response.status}`)
  }
  return await response.json() as WorkJournalEmailContext
}

/** ownerEmailを省くと自分の日報。他人の指定はmanager以上だけ通り、権限がなければ404になる。 */
export async function getWorkJournals(dateFrom: string, dateTo: string, ownerEmail = ''): Promise<WorkJournalRecord[]> {
  const params = new URLSearchParams({ date_from: dateFrom, date_to: dateTo })
  if (ownerEmail) params.set('owner_email', ownerEmail)
  const response = await authFetch(`/api/work-journals?${params}`)
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `記録取得API error: ${response.status}`)
  }
  return await response.json() as WorkJournalRecord[]
}

export interface WorkJournalMemberSummary {
  email: string
  name: string
  org_unit_id: string
  org_unit_name: string
  is_self: boolean
}

/** 業務日報を閲覧できるメンバー。manager以外には自分だけが返る。 */
export async function getWorkJournalMembers(): Promise<WorkJournalMemberSummary[]> {
  const response = await authFetch('/api/work-journals/members')
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `記録メンバー取得API error: ${response.status}`)
  }
  return await response.json() as WorkJournalMemberSummary[]
}

export async function saveWorkJournal(payload: Omit<WorkJournalRecord, 'owner_email' | 'created_at' | 'updated_at'>): Promise<WorkJournalRecord> {
  const response = await authFetch('/api/work-journals', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `記録保存API error: ${response.status}`)
  }
  return await response.json() as WorkJournalRecord
}

export async function getWorkJournalDocumentFlows(
  orgUnitId: string,
  dateFrom: string,
  dateTo: string,
): Promise<WorkJournalDocumentFlowReport> {
  const params = new URLSearchParams({ org_unit_id: orgUnitId, date_from: dateFrom, date_to: dateTo })
  const response = await authFetch(`/api/work-journals/organization/document-flows?${params}`)
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `資料の流れ取得API error: ${response.status}`)
  }
  return await response.json() as WorkJournalDocumentFlowReport
}

export async function getMailClassificationRules(): Promise<MailClassificationRules> {
  const response = await authFetch('/api/mail-rules')
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `メール分類マスター取得API error: ${response.status}`)
  }
  return await response.json() as MailClassificationRules
}

async function saveMailRule<T>(path: string, id: string, body: unknown): Promise<T> {
  const response = await authFetch(id ? `${path}/${encodeURIComponent(id)}` : path, {
    method: id ? 'PUT' : 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    const detail = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(detail.detail || `メール分類マスター保存API error: ${response.status}`)
  }
  return await response.json() as T
}

async function deleteMailRule(path: string, id: string): Promise<void> {
  const response = await authFetch(`${path}/${encodeURIComponent(id)}`, { method: 'DELETE' })
  if (!response.ok && response.status !== 404) {
    const detail = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(detail.detail || `メール分類マスター削除API error: ${response.status}`)
  }
}

export async function saveMailSourceRule(
  payload: Omit<MailSourceRule, 'id' | 'updated_at'> & { id?: string },
): Promise<MailSourceRule> {
  const { id, ...body } = payload
  return await saveMailRule<MailSourceRule>('/api/mail-rules/sources', id || '', body)
}

export async function deleteMailSourceRule(id: string): Promise<void> {
  await deleteMailRule('/api/mail-rules/sources', id)
}

export async function saveMailRequestTypeRule(
  payload: Omit<MailRequestTypeRule, 'id' | 'updated_at'> & { id?: string },
): Promise<MailRequestTypeRule> {
  const { id, ...body } = payload
  return await saveMailRule<MailRequestTypeRule>('/api/mail-rules/request-types', id || '', body)
}

export async function deleteMailRequestTypeRule(id: string): Promise<void> {
  await deleteMailRule('/api/mail-rules/request-types', id)
}

/** tenantIdを渡すと、選択中テナント以外の組織も引ける（所属の設定に使う）。 */
export async function getOrgUnits(tenantId = ''): Promise<OrgUnitRecord[]> {
  const query = tenantId ? `?${new URLSearchParams({ tenant_id: tenantId })}` : ''
  const response = await authFetch(`/api/org-units${query}`)
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `組織マスター取得API error: ${response.status}`)
  }
  return await response.json() as OrgUnitRecord[]
}

export async function saveOrgUnit(payload: {
  id?: string
  parent_id: string
  name: string
  kind: OrgUnitKind
  sort_order: number
}): Promise<OrgUnitRecord> {
  const { id, ...body } = payload
  const response = await authFetch(id ? `/api/org-units/${encodeURIComponent(id)}` : '/api/org-units', {
    method: id ? 'PUT' : 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    const detail = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(detail.detail || `組織マスター保存API error: ${response.status}`)
  }
  return await response.json() as OrgUnitRecord
}

export async function deleteOrgUnit(orgUnitId: string): Promise<void> {
  const response = await authFetch(`/api/org-units/${encodeURIComponent(orgUnitId)}`, { method: 'DELETE' })
  if (!response.ok && response.status !== 404) {
    const detail = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(detail.detail || `組織マスター削除API error: ${response.status}`)
  }
}

export async function getOrganizationJournalActivity(
  orgUnitId: string,
  dateFrom: string,
  dateTo: string,
): Promise<WorkJournalOrganizationActivity> {
  const params = new URLSearchParams({ org_unit_id: orgUnitId, date_from: dateFrom, date_to: dateTo })
  const response = await authFetch(`/api/work-journals/organization?${params}`)
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `チームの記録取得API error: ${response.status}`)
  }
  return await response.json() as WorkJournalOrganizationActivity
}

export async function summarizeOrganizationJournals(payload: {
  org_unit_id: string
  date_from: string
  date_to: string
}): Promise<WorkJournalOrganizationDigest> {
  return postJson<WorkJournalOrganizationDigest>('/api/work-journals/organization/summary', payload, 180_000)
}

export async function getWorkJournalWorkGraph(
  orgUnitId: string,
  dateFrom: string,
  dateTo: string,
): Promise<WorkGraph> {
  const params = new URLSearchParams({ org_unit_id: orgUnitId, date_from: dateFrom, date_to: dateTo })
  const response = await authFetch(`/api/work-journals/organization/work-graph?${params}`)
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `業務グラフ取得API error: ${response.status}`)
  }
  return await response.json() as WorkGraph
}

export async function buildWorkJournalWorkMap(payload: {
  org_unit_id: string
  date_from: string
  date_to: string
}): Promise<WorkJournalWorkMap> {
  return postJson<WorkJournalWorkMap>('/api/work-journals/organization/work-map', payload, 180_000)
}

export async function deleteWorkJournal(journalDate: string): Promise<void> {
  const response = await authFetch(`/api/work-journals/${encodeURIComponent(journalDate)}`, { method: 'DELETE' })
  if (!response.ok && response.status !== 404) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `記録削除API error: ${response.status}`)
  }
}

export async function transcribeAudio(audio: Blob): Promise<AudioTranscriptionResponse> {
  const controller = new AbortController()
  const timeoutId = window.setTimeout(() => controller.abort(), 60_000)
  try {
    const response = await authFetch('/api/speech/transcribe', {
      method: 'POST',
      headers: { 'Content-Type': audio.type || 'audio/webm' },
      body: audio,
      signal: controller.signal,
    })
    if (!response.ok) {
      const body = await response.json().catch(() => ({})) as { detail?: string }
      throw new Error(body.detail || `音声文字起こしAPI error: ${response.status}`)
    }
    return await response.json() as AudioTranscriptionResponse
  } finally {
    window.clearTimeout(timeoutId)
  }
}

/**
 * 文章を読み上げたWAVを返す。preferences を渡すと保存前の試聴になり、
 * 省くとサーバーが本人の保存済みの好みで読み上げる。
 */
export async function synthesizeSpeech(text: string, signal?: AbortSignal, preferences?: SpeechPreferences): Promise<Blob> {
  const response = await authFetch('/api/speech', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(preferences ? { text, preferences } : { text }),
    signal,
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `音声生成API error: ${response.status}`)
  }
  return response.blob()
}

export async function streamSpeech(
  text: string,
  signal?: AbortSignal,
): Promise<{ stream: ReadableStream<Uint8Array>; sampleRate: number }> {
  const response = await authFetch('/api/speech/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
    signal,
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    // 呼び出し側が上限超過（429）を見分けて、別経路での再試行を控えられるようにする。
    throw Object.assign(new Error(body.detail || `ストリーミング音声生成API error: ${response.status}`), { status: response.status })
  }
  if (!response.body) throw new Error('ストリーミング音声を受信できませんでした。')
  const sampleRate = Number(response.headers.get('X-Audio-Sample-Rate')) || 24_000
  return { stream: response.body, sampleRate }
}

export interface AiUsageReport {
  date_from: string
  date_to: string
  scope: 'tenant' | 'self'
  total_calls: number
  total_tokens: number
  rate_limit_per_minute: number
  rate_limit_per_day: number
  used_today: number
  by_user: Array<{ user_email: string; calls: number; total_duration_ms: number; errors: number; rate_limited: number; prompt_tokens: number; output_tokens: number; total_tokens: number }>
  by_feature: Array<{ feature: string; calls: number; total_duration_ms: number; total_tokens: number }>
  by_day: Array<{ day: string; calls: number; total_tokens: number }>
}

export interface SQLiteBackupRecord {
  id: string
  filename: string
  created_at: string
  size_bytes: number
}

export interface SQLiteTableStatistics {
  name: string
  row_count: number
  table_bytes: number
  index_bytes: number
  total_bytes: number
}

export interface SQLiteDatabaseStatistics {
  database_filename: string
  journal_mode: string
  last_modified_at: string
  database_bytes: number
  wal_bytes: number
  shm_bytes: number
  active_files_bytes: number
  allocated_bytes: number
  logical_used_bytes: number
  unused_bytes: number
  usage_percent: number
  total_records: number
  table_count: number
  backup_bytes: number
  backup_count: number
  tables: SQLiteTableStatistics[]
}

export async function getSQLiteBackups(): Promise<SQLiteBackupRecord[]> {
  const response = await authFetch('/api/backups')
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `バックアップ一覧API error: ${response.status}`)
  }
  return await response.json() as SQLiteBackupRecord[]
}

export async function getSQLiteDatabaseStatistics(): Promise<SQLiteDatabaseStatistics> {
  const response = await authFetch('/api/backups/statistics')
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `データ量取得API error: ${response.status}`)
  }
  return await response.json() as SQLiteDatabaseStatistics
}

export async function createSQLiteBackup(): Promise<SQLiteBackupRecord> {
  const response = await authFetch('/api/backups', { method: 'POST' })
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `バックアップ作成API error: ${response.status}`)
  }
  return await response.json() as SQLiteBackupRecord
}

export async function downloadSQLiteBackup(backup: SQLiteBackupRecord): Promise<void> {
  const response = await authFetch(`/api/backups/${encodeURIComponent(backup.id)}`)
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `バックアップダウンロードAPI error: ${response.status}`)
  }
  const blob = await response.blob()
  const objectUrl = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = objectUrl
  link.download = backup.filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(objectUrl)
}

export async function getAiUsage(dateFrom: string, dateTo: string): Promise<AiUsageReport> {
  const params = new URLSearchParams({ date_from: dateFrom, date_to: dateTo })
  const response = await authFetch(`/api/ai-usage?${params}`)
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `AI利用状況API error: ${response.status}`)
  }
  return await response.json() as AiUsageReport
}

async function postJson<T>(path: string, payload: unknown, timeout: number, externalSignal?: AbortSignal): Promise<T> {
  const controller = new AbortController()
  const timeoutId = window.setTimeout(() => controller.abort(), timeout)
  const abortRequest = () => controller.abort()
  if (externalSignal) {
    if (externalSignal.aborted) controller.abort()
    else externalSignal.addEventListener('abort', abortRequest, { once: true })
  }
  try {
    const response = await authFetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: controller.signal,
    })
    if (!response.ok) {
      const body = await response.json().catch(() => ({})) as { detail?: string }
      throw new Error(body.detail || `LLM API error: ${response.status}`)
    }
    return await response.json() as T
  } finally {
    window.clearTimeout(timeoutId)
    externalSignal?.removeEventListener('abort', abortRequest)
  }
}

export type GeminiApiKeySource = 'environment' | 'stored' | 'none'

export interface GeminiSettings {
  source: GeminiApiKeySource
  configured: boolean
  key_hint?: string
}

export async function getGeminiSettings(): Promise<GeminiSettings> {
  const response = await authFetch('/api/settings/gemini')
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `AI設定取得API error: ${response.status}`)
  }
  return await response.json() as GeminiSettings
}

export async function saveGeminiApiKey(apiKey: string): Promise<GeminiSettings> {
  const response = await authFetch('/api/settings/gemini', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ api_key: apiKey }),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `APIキー保存API error: ${response.status}`)
  }
  return await response.json() as GeminiSettings
}

export async function deleteGeminiApiKey(): Promise<void> {
  const response = await authFetch('/api/settings/gemini', { method: 'DELETE' })
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `APIキー削除API error: ${response.status}`)
  }
}

/** Google連携を機能ごとに使うか。Meetはカレンダーが有効なときだけ使える。 */
export interface GoogleIntegrationSettings {
  calendar: boolean
  meet: boolean
  gmail: boolean
  drive: boolean
}

export async function getGoogleIntegrations(): Promise<GoogleIntegrationSettings> {
  const response = await authFetch('/api/google-integrations')
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `Google連携設定取得API error: ${response.status}`)
  }
  return await response.json() as GoogleIntegrationSettings
}

export async function saveGoogleIntegrations(settings: GoogleIntegrationSettings): Promise<GoogleIntegrationSettings> {
  const response = await authFetch('/api/settings/google-integrations', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `Google連携設定保存API error: ${response.status}`)
  }
  return await response.json() as GoogleIntegrationSettings
}

/** 動作モード。画面の言葉づかいだけが変わる（diary=日記寄り、work=業務より）。 */
export type AppMode = 'diary' | 'work'

export async function getAppMode(): Promise<AppMode> {
  const response = await authFetch('/api/app-mode')
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `動作モード取得API error: ${response.status}`)
  }
  return (await response.json() as { mode: AppMode }).mode
}

export async function saveAppMode(mode: AppMode): Promise<AppMode> {
  const response = await authFetch('/api/settings/app-mode', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode }),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `動作モード保存API error: ${response.status}`)
  }
  return (await response.json() as { mode: AppMode }).mode
}

export type SpeechTone = 'default' | 'calm' | 'friendly' | 'cheerful'
export type SpeechPace = 'normal' | 'slow' | 'fast'

/** 利用者ごとの読み上げの好み。voice が空ならシステムの既定の声を使う。 */
export interface SpeechPreferences {
  voice: string
  tone: SpeechTone
  pace: SpeechPace
}

export interface SpeechOption<Id extends string = string> {
  id: Id
  label: string
}

export interface SpeechPreferencesResponse extends SpeechPreferences {
  default_voice: string
  voices: SpeechOption[]
  tones: SpeechOption<SpeechTone>[]
  paces: SpeechOption<SpeechPace>[]
}

export async function getSpeechPreferences(): Promise<SpeechPreferencesResponse> {
  const response = await authFetch('/api/user-preferences/speech')
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `読み上げ設定取得API error: ${response.status}`)
  }
  return await response.json() as SpeechPreferencesResponse
}

export async function saveSpeechPreferences(preferences: SpeechPreferences): Promise<SpeechPreferencesResponse> {
  const response = await authFetch('/api/user-preferences/speech', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(preferences),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `読み上げ設定保存API error: ${response.status}`)
  }
  return await response.json() as SpeechPreferencesResponse
}

/** ② Vertex AI（Google Cloud）への接続。Vertex AI と Cloud Text-to-Speech で共通に使う。 */
export interface GoogleCloudAuthSettings {
  project: string
  location: string
  /** Kubernetes 上でだけ使う Workload Identity 連携の識別子（任意）。 */
  wif_project_number: string
  wif_pool_id: string
  wif_provider_id: string
  wif_service_account: string
}

export interface GoogleCloudSettingsResponse extends GoogleCloudAuthSettings {
  environment: { project: string; location: string }
  /** いま使われる認証。Kubernetes 上で WIF が設定されていれば wif、それ以外は adc（google.auth.default）。 */
  active_auth: 'adc' | 'wif'
  running_on_kubernetes: boolean
}

/** 接続方法。gemini-api は ① Gemini APIキー、vertex は ② Vertex AI。 */
export type AiConnection = 'gemini-api' | 'vertex'
/** 読み上げの方式。gemini-tts は ① 固定、cloud-tts は ② 固定。 */
export type SpeechEngine = 'gemini-tts' | 'cloud-tts'
export type AiRole = 'chat' | 'transcription' | 'speech'

export interface AiModelValues {
  chat_connection: AiConnection
  chat_model: string
  transcription_connection: AiConnection
  transcription_model: string
  speech_engine: SpeechEngine
  speech_model: string
}

/** 役割ごとの接続方法とモデル。空の項目は環境変数に従う。 */
export interface AiModelSettings {
  chat_connection: '' | AiConnection
  chat_model: string
  transcription_connection: '' | AiConnection
  transcription_model: string
  speech_engine: '' | SpeechEngine
  speech_model: string
}

export interface AiModelSettingsResponse extends AiModelSettings {
  environment: AiModelValues
  effective: AiModelValues
}

export interface WorkloadIdentityInfo {
  subject: string
  namespace: string
  service_account: string
  issuer: string
  jwks: Record<string, unknown>
}

export interface ConnectionCheckResult {
  ok: boolean
  step: 'credentials' | 'sts' | 'api'
  message: string
}

async function settingsRequest<T>(path: string, label: string, init?: RequestInit): Promise<T> {
  const response = await authFetch(path, init)
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `${label} API error: ${response.status}`)
  }
  return await response.json() as T
}

export function getGoogleCloudAuth(): Promise<GoogleCloudSettingsResponse> {
  return settingsRequest('/api/settings/google-cloud', 'Google Cloud設定取得')
}

export function saveGoogleCloudAuth(settings: GoogleCloudAuthSettings): Promise<GoogleCloudSettingsResponse> {
  return settingsRequest('/api/settings/google-cloud', 'Google Cloud設定保存', jsonPut(settings))
}

export function getWorkloadIdentity(): Promise<WorkloadIdentityInfo> {
  return settingsRequest('/api/settings/google-cloud/workload-identity', 'Workload Identity情報取得')
}

export function getAiModels(): Promise<AiModelSettingsResponse> {
  return settingsRequest('/api/settings/ai-models', 'AIモデル設定取得')
}

export function saveAiModels(settings: AiModelSettings): Promise<AiModelSettingsResponse> {
  return settingsRequest('/api/settings/ai-models', 'AIモデル設定保存', jsonPut(settings))
}

export function checkAiModel(role: AiRole): Promise<ConnectionCheckResult> {
  return settingsRequest(`/api/settings/ai-models/${role}/check`, '接続確認', { method: 'POST' })
}

function jsonPut(body: unknown): RequestInit {
  return { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
}
