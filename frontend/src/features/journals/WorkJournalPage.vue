<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  analyzeWorkJournalAttachments,
  deleteWorkJournal,
  getMailClassificationRules,
  getWorkJournalMembers,
  getWorkJournals,
  requestWorkJournalTurn,
  saveWorkJournal,
  summarizeWorkJournalEmails,
  type LlmInterviewMessage,
  type LlmInterviewAttachment,
  type WorkJournalAnalysis,
  type WorkJournalAttachmentInsight,
  type WorkJournalCalendarEvent,
  type WorkJournalDraft,
  type WorkJournalEmailCategoryCount,
  type WorkJournalEmailContext,
  type WorkJournalMemberSummary,
  type MailClassificationRules,
  type WorkJournalRecentEntry,
  type WorkJournalRecord,
  type WorkJournalSituationContext,
} from '../../api/hinami'
import {
  interviewAttachmentMaxBytes,
  interviewAttachmentTotalMaxBytes,
  readFileAsDataUrl,
  supportedInterviewAttachmentTypes,
} from '../../utils/attachments'
import { useAppMode } from '../shell/useAppMode'
import { useGoogleIntegrations } from '../shell/useGoogleIntegrations'
import { useAuthSession } from '../admin/useAuthSession'
import { useVoice } from '../voice/useVoice'
import { useNotifier } from '../shell/useNotifier'
import { getOrgUnits, type OrgUnitRecord } from '../../api/hinami'
import { classifyMailMessages, type ClassifiableMessage } from './mail-classification'

const { authConfig, currentUser, canEdit, requestGoogleAccessToken } = useAuthSession()
const { googleIntegrations, ensureLoaded: ensureGoogleIntegrations } = useGoogleIntegrations()
const { labels } = useAppMode()

// 機能ごとに求めるスコープ。管理者が無効にした機能のスコープは要求しない。
const GOOGLE_SCOPES = {
  calendar: 'https://www.googleapis.com/auth/calendar.events.owned.readonly',
  meet: 'https://www.googleapis.com/auth/meetings.space.readonly',
  gmail: 'https://www.googleapis.com/auth/gmail.readonly',
  drive: 'https://www.googleapis.com/auth/drive.readonly',
} as const
const { notify } = useNotifier()

type DialogStep = 'setup' | 'conversation' | 'review'
type ChatMessage = LlmInterviewMessage & { id: number }
type JournalUpload = LlmInterviewAttachment & {
  id: string
  size: number
  previewUrl?: string
  sourceUrl?: string
  insight?: WorkJournalAttachmentInsight
  insightFailed?: boolean
  analyzing?: boolean
}
type MonthlyInsightKey = keyof WorkJournalAnalysis
type MonthlyInsightEntry = { text: string; date: string }
type DrivePickerFile = { id: string; name: string; mimeType: string; modifiedTime: string; webViewLink: string; iconLink: string }
type DrivePickerLocation = { id: string; name: string }
type DrivePickerBreadcrumb = { id: string; name: string }

const today = new Date()
today.setHours(0, 0, 0, 0)
const currentMonth = ref(new Date(today.getFullYear(), today.getMonth(), 1))
const selectedDate = ref(toDateKey(today))
const records = ref<WorkJournalRecord[]>([])
const loading = ref(false)
const loadError = ref('')
const dialogOpen = ref(false)
const dialogStep = ref<DialogStep>('setup')
const calendarEvents = ref<WorkJournalCalendarEvent[]>([])
const calendarLoading = ref(false)
const calendarError = ref('')
const meetError = ref('')
const emailContext = ref<WorkJournalEmailContext>(emptyEmailContext())
const emailLoading = ref(false)
const emailError = ref('')
const mailRules = ref<MailClassificationRules>({ sources: [], request_types: [] })
const emailCategories = ref<WorkJournalEmailCategoryCount[]>([])
const emailClassifiedCount = ref(0)
const mailRulesConfigured = computed(
  () => mailRules.value.sources.length > 0 || mailRules.value.request_types.length > 0,
)
const weatherLocation = ref('')
const weatherSummary = ref('')
const weatherLoading = ref(false)
const messages = ref<ChatMessage[]>([])
const chatElement = ref<HTMLElement | null>(null)
const responseText = ref('')
const attachmentInput = ref<HTMLInputElement | null>(null)
const attachments = ref<JournalUpload[]>([])
const attachmentError = ref('')
const attachmentDragActive = ref(false)
const recentJournals = ref<WorkJournalRecentEntry[]>([])
const driveLinkOpen = ref(false)
const driveLink = ref('')
const driveLoading = ref(false)
const driveError = ref('')
const drivePickerOpen = ref(false)
const drivePickerLoading = ref(false)
const drivePickerFiles = ref<DrivePickerFile[]>([])
const drivePickerSearch = ref('')
const drivePickerLocations = ref<DrivePickerLocation[]>([])
const drivePickerLocationId = ref('')
const drivePickerBreadcrumbs = ref<DrivePickerBreadcrumb[]>([])
const drivePickerSelectedFile = ref<DrivePickerFile | null>(null)
const selectedMeetingKeys = ref<string[]>([])
const aiThinking = ref(false)
const turnError = ref('')
const draft = ref<WorkJournalDraft | null>(null)
const reviewWorkIndex = ref(0)
const detailWorkIndex = ref(0)
const saving = ref(false)
let turnController: AbortController | null = null
let drivePickerAccessToken = ''
let attachmentAnalysis: Promise<void> | null = null
// Google APIを無制限に辿らないための上限。詳細は docs/google-api-data-flow.md を参照。
const MEET_CONTEXT_MAX_EVENTS = 10
const MEET_PARTICIPANT_MAX_PAGES = 2
const MEET_PARTICIPANT_PAGE_SIZE = 250
const MEET_ARTIFACT_PAGE_SIZE = 10
const GMAIL_COUNT_MAX_PAGES = 4
const GMAIL_COUNT_PAGE_SIZE = 500
const GMAIL_REQUEST_CANDIDATE_LIMIT = 8
// 分類のために件名を読む上限。1通ずつ問い合わせるため、日の活動量が読めれば十分な数で打ち切る。
const GMAIL_CLASSIFY_MAX_MESSAGES = 80
const GMAIL_CLASSIFY_CONCURRENCY = 6

// AIの返答は1文字ずつ現れるように見せる。長い返答でも約2秒で出し切る。
// 動きを減らす設定のときは一度に出す。
const prefersReducedMotion = typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
const REVEAL_TICK_MS = 24
const REVEAL_MAX_TICKS = 85
const revealingMessageId = ref<number | null>(null)
const revealedLength = ref(0)
let revealTimer = 0

function stopReveal() {
  window.clearTimeout(revealTimer)
  revealingMessageId.value = null
}

function revealMessage(message: ChatMessage) {
  stopReveal()
  if (prefersReducedMotion) return
  const step = Math.max(1, Math.ceil(message.text.length / REVEAL_MAX_TICKS))
  revealingMessageId.value = message.id
  revealedLength.value = 0
  const tick = () => {
    revealedLength.value += step
    if (revealedLength.value >= message.text.length) {
      revealingMessageId.value = null
      return
    }
    revealTimer = window.setTimeout(tick, REVEAL_TICK_MS)
  }
  tick()
}

function displayedMessageText(message: ChatMessage) {
  return message.id === revealingMessageId.value ? message.text.slice(0, revealedLength.value) : message.text
}

watch(
  () => [messages.value.length, aiThinking.value, revealedLength.value],
  async () => {
    await nextTick()
    if (chatElement.value) chatElement.value.scrollTop = chatElement.value.scrollHeight
  },
  { flush: 'post' },
)

const {
  voiceInputSupported,
  voiceOutputSupported,
  isVoiceListening,
  isVoiceTranscribing,
  isAiSpeaking,
  voicePlaybackEnabled,
  voiceStatus,
  voiceError,
  stopAiSpeech,
  unlockAiAudio,
  speakAiMessage,
  toggleVoicePlayback,
  cancelVoiceInput,
  toggleVoiceInput,
} = useVoice(responseText)

/** 振り返りパートナーの状態。ヘッダーのオーブと文言を切り替える。 */
const aiPresence = computed(() => {
  if (isVoiceListening.value) return { state: 'listening', label: 'あなたの声を聞いています' }
  if (isVoiceTranscribing.value) return { state: 'thinking', label: '声を文字にしています' }
  if (aiThinking.value) return { state: 'thinking', label: '今日のことを整理しています' }
  if (isAiSpeaking.value || revealingMessageId.value !== null) return { state: 'speaking', label: '話しています' }
  return { state: 'idle', label: 'あなたの番です。話すか、書いてください' }
})

const weekdayLabels = ['日', '月', '火', '水', '木', '金', '土']
// 日報の保存時に構造化した内容を、月単位で本人へ返すための区分。
const MONTHLY_INSIGHT_GROUPS: Array<{ key: MonthlyInsightKey; icon: string }> = [
  { key: 'progressed_items', icon: 'mdi-progress-check' },
  { key: 'ingenuity', icon: 'mdi-lightbulb-on-outline' },
  { key: 'unplanned_work', icon: 'mdi-flash-alert-outline' },
  { key: 'support_needed', icon: 'mdi-hand-heart-outline' },
]
// managerは配下メンバーの日報を選んで閲覧できる。閲覧できる相手はバックエンドが決める。
const journalMembers = ref<WorkJournalMemberSummary[]>([])
const currentEmail = computed(() => (currentUser.value?.email || '').trim().toLowerCase())
const viewingEmail = ref('')
const viewingMember = computed(() => journalMembers.value.find((member) => member.email === viewingEmail.value))
const viewingOther = computed(() => Boolean(viewingEmail.value) && !viewingMember.value?.is_self)
const canSelectMember = computed(() => journalMembers.value.length > 1)
const memberOptions = computed(() => journalMembers.value.map((member) => ({
  value: member.email,
  title: member.is_self
    ? `${member.name}（自分）`
    : member.org_unit_name ? `${member.name}（${member.org_unit_name}）` : member.name,
})))

const monthLabel = computed(() => new Intl.DateTimeFormat('ja-JP', { year: 'numeric', month: 'long' }).format(currentMonth.value))
const recordMap = computed(() => new Map(records.value.map((record) => [record.journal_date, record])))
const selectedRecord = computed(() => recordMap.value.get(selectedDate.value))
const participant = computed(() => currentUser.value?.name?.trim() || '利用者')
// 組織マスターで解決できない場合は、別組織の日報として保存されるのを防ぐため未確定のままにする。
const orgUnits = ref<OrgUnitRecord[]>([])
const orgUnitsLoaded = ref(false)
// ログインなしの開発モードには利用者がいないため、記入する組織を画面で選ぶ。
// 選んだ組織はこのブラウザにだけ覚えておく（開発・お試し用の便宜で、本番では使われない）。
const DEV_ORG_UNIT_KEY = 'hinami_dev_org_unit'
const devMode = computed(() => !authConfig.value.google_oauth_enabled)
const devOrgUnitId = ref(readDevOrgUnitId())
function readDevOrgUnitId() {
  try {
    return localStorage.getItem(DEV_ORG_UNIT_KEY) || ''
  } catch {
    return ''
  }
}
watch(devOrgUnitId, (value) => {
  try {
    localStorage.setItem(DEV_ORG_UNIT_KEY, value)
  } catch {
    // 保存できなくても、この画面を開いている間は選んだ組織で書ける。
  }
})
const selectedOrgUnit = computed(() => {
  if (devMode.value) {
    return orgUnits.value.find((unit) => unit.id === devOrgUnitId.value) ?? orgUnits.value[0]
  }
  const target = (currentUser.value?.org_unit_id || '').trim()
  if (!target) return undefined
  return orgUnits.value.find((unit) => unit.id === target)
})
const orgUnitUnresolved = computed(() => orgUnitsLoaded.value && !selectedOrgUnit.value)
// Googleでログインしていて、かつ管理者がその機能を有効にしているときだけ使う。
const googleSignedIn = computed(() => authConfig.value.google_oauth_enabled && Boolean(currentUser.value))
const calendarEnabled = computed(() => googleSignedIn.value && googleIntegrations.value.calendar)
const meetEnabled = computed(() => calendarEnabled.value && googleIntegrations.value.meet)
const gmailEnabled = computed(() => googleSignedIn.value && googleIntegrations.value.gmail)
const driveEnabled = computed(() => googleSignedIn.value && googleIntegrations.value.drive)
const monthlyRecords = computed(() => {
  const prefix = `${currentMonth.value.getFullYear()}-${String(currentMonth.value.getMonth() + 1).padStart(2, '0')}`
  return records.value
    .filter((record) => record.journal_date.startsWith(prefix))
    .sort((left, right) => right.journal_date.localeCompare(left.journal_date))
})
const monthlyInsightGroups = computed(() => MONTHLY_INSIGHT_GROUPS.map((group) => {
  const entries: MonthlyInsightEntry[] = []
  for (const record of monthlyRecords.value) {
    for (const text of record.analysis?.[group.key] ?? []) {
      const trimmed = text.trim()
      // 同じ言い回しが続いた日は最初の1件だけ残し、一覧を読みやすく保つ。
      if (trimmed && !entries.some((entry) => entry.text === trimmed)) {
        entries.push({ text: trimmed, date: record.journal_date })
      }
    }
  }
  return { ...group, ...labels.value.insightGroups[group.key], entries }
}))
const filteredDrivePickerFiles = computed(() => {
  const query = drivePickerSearch.value.trim().toLocaleLowerCase('ja')
  return query
    ? drivePickerFiles.value.filter((file) => file.name.toLocaleLowerCase('ja').includes(query))
    : drivePickerFiles.value
})

function emptyEmailContext(): WorkJournalEmailContext {
  return { received_count: 0, sent_count: 0, unread_count: 0, request_candidates: [] }
}
const calendarDays = computed(() => {
  const year = currentMonth.value.getFullYear()
  const month = currentMonth.value.getMonth()
  const first = new Date(year, month, 1)
  const start = new Date(year, month, 1 - first.getDay())
  return Array.from({ length: 42 }, (_, index) => {
    const date = new Date(start)
    date.setDate(start.getDate() + index)
    const key = toDateKey(date)
    return {
      key,
      day: date.getDate(),
      currentMonth: date.getMonth() === month,
      today: key === toDateKey(today),
      record: recordMap.value.get(key),
    }
  })
})

function toDateKey(date: Date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function dateLabel(dateKey: string) {
  const [year, month, day] = dateKey.split('-').map(Number)
  return new Intl.DateTimeFormat('ja-JP', { month: 'long', day: 'numeric', weekday: 'short' }).format(new Date(year, month - 1, day))
}

function shortDateLabel(dateKey: string) {
  const [, month, day] = dateKey.split('-').map(Number)
  return `${month}/${day}`
}

function monthRange() {
  const start = new Date(currentMonth.value.getFullYear(), currentMonth.value.getMonth(), 1)
  const end = new Date(currentMonth.value.getFullYear(), currentMonth.value.getMonth() + 1, 0)
  return { from: toDateKey(start), to: toDateKey(end) }
}

async function loadRecords() {
  loading.value = true
  loadError.value = ''
  try {
    const range = monthRange()
    records.value = await getWorkJournals(range.from, range.to, viewingOther.value ? viewingEmail.value : '')
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : '記録を読み込めませんでした。'
  } finally {
    loading.value = false
  }
}

async function moveMonth(offset: number) {
  currentMonth.value = new Date(currentMonth.value.getFullYear(), currentMonth.value.getMonth() + offset, 1)
  selectedDate.value = toDateKey(currentMonth.value)
  detailWorkIndex.value = 0
  await loadRecords()
}

async function goToday() {
  currentMonth.value = new Date(today.getFullYear(), today.getMonth(), 1)
  selectedDate.value = toDateKey(today)
  detailWorkIndex.value = 0
  await loadRecords()
}

function selectDay(dateKey: string) {
  selectedDate.value = dateKey
  detailWorkIndex.value = 0
}

function openJournal(dateKey = selectedDate.value) {
  if (viewingOther.value) {
    notify('他のメンバーの記録は閲覧のみです')
    return
  }
  if (!canEdit.value) {
    notify('viewer権限では記録をつけられません')
    return
  }
  if (orgUnitUnresolved.value) {
    notify('所属組織が組織マスターに登録されていません。管理者へ設定を依頼してください')
    return
  }
  selectedDate.value = dateKey
  dialogStep.value = 'setup'
  calendarEvents.value = []
  calendarError.value = ''
  meetError.value = ''
  emailContext.value = emptyEmailContext()
  emailError.value = ''
  emailCategories.value = []
  emailClassifiedCount.value = 0
  weatherLocation.value = ''
  weatherSummary.value = ''
  messages.value = []
  responseText.value = ''
  turnError.value = ''
  draft.value = null
  reviewWorkIndex.value = 0
  attachments.value = []
  attachmentError.value = ''
  driveLinkOpen.value = false
  driveLink.value = ''
  driveError.value = ''
  drivePickerOpen.value = false
  drivePickerFiles.value = []
  drivePickerSearch.value = ''
  drivePickerLocations.value = []
  drivePickerLocationId.value = ''
  drivePickerBreadcrumbs.value = []
  drivePickerSelectedFile.value = null
  selectedMeetingKeys.value = []
  recentJournals.value = []
  dialogOpen.value = true
  void loadAutomaticContext()
}

function closeDialog() {
  turnController?.abort()
  turnController = null
  cancelVoiceInput()
  stopAiSpeech()
  dialogOpen.value = false
  messages.value = []
  draft.value = null
  responseText.value = ''
  attachments.value = []
  drivePickerOpen.value = false
  drivePickerFiles.value = []
  drivePickerBreadcrumbs.value = []
  drivePickerSelectedFile.value = null
  drivePickerAccessToken = ''
}

function formatAttachmentSize(size: number) {
  return size >= 1024 * 1024
    ? `${(size / 1024 / 1024).toFixed(1)}MB`
    : `${Math.max(1, Math.round(size / 1024))}KB`
}

async function addJournalFiles(files: File[] | FileList, sourceUrl = '') {
  attachmentError.value = ''
  for (const file of Array.from(files)) {
    const mimeType = file.type.split(';', 1)[0] as LlmInterviewAttachment['mime_type']
    if (!supportedInterviewAttachmentTypes.has(mimeType)) {
      attachmentError.value = 'PNG・JPEG・WebP・PDFのみ添付できます。Googleの資料はPDFへ変換して読み込みます。'
      continue
    }
    if (attachments.value.length >= 4) {
      attachmentError.value = '1on1で利用できる資料は4件までです。'
      break
    }
    if (file.size > interviewAttachmentMaxBytes) {
      attachmentError.value = `${file.name}は8MBを超えています。`
      continue
    }
    const totalBytes = attachments.value.reduce((sum, item) => sum + item.size, 0)
    if (totalBytes + file.size > interviewAttachmentTotalMaxBytes) {
      attachmentError.value = '資料の合計は20MB以内にしてください。'
      break
    }
    if (attachments.value.some((item) => item.name === file.name && item.size === file.size)) continue
    try {
      const dataUrl = await readFileAsDataUrl(file)
      attachments.value.push({
        id: `journal-attachment-${Date.now()}-${attachments.value.length}`,
        name: file.name,
        mime_type: mimeType,
        data: dataUrl.slice(dataUrl.indexOf(',') + 1),
        size: file.size,
        previewUrl: mimeType.startsWith('image/') ? dataUrl : undefined,
        sourceUrl,
      })
    } catch (error) {
      attachmentError.value = error instanceof Error ? error.message : '資料を読み込めませんでした。'
    }
  }
  void ensureAttachmentInsights()
}

async function runAttachmentAnalysis() {
  // 会話中に同じ資料を何度も読み直さないよう、追加した時点で1回だけ要約する。
  for (;;) {
    const pending = attachments.value.filter((item) => item.data && !item.insight && !item.insightFailed)
    if (!pending.length) return
    pending.forEach((item) => { item.analyzing = true })
    try {
      const insights = await analyzeWorkJournalAttachments(
        pending.map(({ name, mime_type, data }) => ({ name, mime_type, data })),
      )
      pending.forEach((item, index) => {
        const insight = insights[index]
        if (insight) item.insight = insight
        else item.insightFailed = true
      })
    } catch {
      // 要約できなくても、資料本文を添えたまま従来どおり1on1を続けられる。
      pending.forEach((item) => { item.insightFailed = true })
    } finally {
      pending.forEach((item) => { item.analyzing = false })
    }
  }
}

function ensureAttachmentInsights() {
  if (!attachmentAnalysis) {
    attachmentAnalysis = runAttachmentAnalysis().finally(() => { attachmentAnalysis = null })
  }
  return attachmentAnalysis
}

function attachmentStatusLabel(attachment: JournalUpload) {
  if (attachment.analyzing) return '内容を確認中'
  if (!attachment.insight) return ''
  const title = attachment.insight.document_title.trim()
  if (!title) return '内容を確認済み'
  return title.length > 24 ? `${title.slice(0, 24)}…` : title
}

function onAttachmentInput(event: Event) {
  const input = event.target as HTMLInputElement
  if (input.files?.length) void addJournalFiles(input.files)
  input.value = ''
}

function onComposerPaste(event: ClipboardEvent) {
  if (!event.clipboardData?.files.length) return
  event.preventDefault()
  void addJournalFiles(event.clipboardData.files)
}

function onComposerDrop(event: DragEvent) {
  attachmentDragActive.value = false
  if (event.dataTransfer?.files.length) void addJournalFiles(event.dataTransfer.files)
}

function removeAttachment(id: string) {
  attachments.value = attachments.value.filter((item) => item.id !== id)
  attachmentError.value = ''
}

function googleDriveFileId(url: string) {
  const patterns = [
    /\/d\/([a-zA-Z0-9_-]{10,})/,
    /[?&]id=([a-zA-Z0-9_-]{10,})/,
  ]
  return patterns.map((pattern) => pattern.exec(url)?.[1]).find(Boolean) || ''
}

async function addGoogleDriveFile() {
  if (!driveEnabled.value) return
  const sourceUrl = driveLink.value.trim()
  const fileId = googleDriveFileId(sourceUrl)
  if (!fileId) {
    driveError.value = 'Google Drive、Googleドキュメント、スプレッドシート、スライドの共有リンクを貼り付けてください。'
    return
  }
  await addGoogleDriveFileById(fileId, sourceUrl)
}

async function addGoogleDriveFileById(fileId: string, sourceUrl: string, existingAccessToken = '') {
  driveLoading.value = true
  driveError.value = ''
  try {
    const accessToken = existingAccessToken || await requestGoogleAccessToken(GOOGLE_SCOPES.drive)
    const headers = { Authorization: `Bearer ${accessToken}` }
    const metadataParams = new URLSearchParams({
      fields: 'id,name,mimeType,size,webViewLink,capabilities(canDownload)',
      supportsAllDrives: 'true',
    })
    const metadataResponse = await fetch(
      `https://www.googleapis.com/drive/v3/files/${encodeURIComponent(fileId)}?${metadataParams}`,
      { headers },
    )
    if (!metadataResponse.ok) {
      const body = await metadataResponse.json().catch(() => ({})) as { error?: { message?: string } }
      throw new Error(body.error?.message || `Google Drive API error: ${metadataResponse.status}`)
    }
    const metadata = await metadataResponse.json() as {
      name?: string
      mimeType?: string
      webViewLink?: string
      capabilities?: { canDownload?: boolean }
    }
    if (metadata.capabilities?.canDownload === false) throw new Error('この資料はダウンロードが許可されていません。')
    const googleWorkspaceFile = metadata.mimeType?.startsWith('application/vnd.google-apps.')
    const contentUrl = googleWorkspaceFile
      ? `https://www.googleapis.com/drive/v3/files/${encodeURIComponent(fileId)}/export?mimeType=${encodeURIComponent('application/pdf')}`
      : `https://www.googleapis.com/drive/v3/files/${encodeURIComponent(fileId)}?alt=media&supportsAllDrives=true`
    const contentResponse = await fetch(contentUrl, { headers })
    if (!contentResponse.ok) {
      const body = await contentResponse.json().catch(() => ({})) as { error?: { message?: string } }
      throw new Error(body.error?.message || `Google Drive資料取得エラー: ${contentResponse.status}`)
    }
    const blob = await contentResponse.blob()
    const mimeType = googleWorkspaceFile ? 'application/pdf' : blob.type.split(';', 1)[0]
    const originalName = metadata.name?.trim() || 'Google Drive資料'
    const fileName = googleWorkspaceFile && !originalName.toLowerCase().endsWith('.pdf') ? `${originalName}.pdf` : originalName
    await addJournalFiles(
      [new File([blob], fileName, { type: mimeType })],
      metadata.webViewLink || sourceUrl,
    )
    if (attachments.value.some((item) => item.name === fileName)) {
      driveLink.value = ''
      driveLinkOpen.value = false
      drivePickerOpen.value = false
    }
  } catch (error) {
    driveError.value = error instanceof Error ? error.message : 'Google Driveの資料を読み込めませんでした。'
  } finally {
    driveLoading.value = false
  }
}

async function openGoogleDrivePicker() {
  if (!driveEnabled.value || drivePickerLoading.value || attachments.value.length >= 4) return
  drivePickerOpen.value = true
  drivePickerLoading.value = true
  driveError.value = ''
  try {
    drivePickerAccessToken = await requestGoogleAccessToken(GOOGLE_SCOPES.drive)
    drivePickerLocations.value = [{ id: '', name: 'マイドライブ' }]
    try {
      const driveParams = new URLSearchParams({ pageSize: '100', fields: 'drives(id,name)' })
      const driveResponse = await fetch(`https://www.googleapis.com/drive/v3/drives?${driveParams}`, {
        headers: { Authorization: `Bearer ${drivePickerAccessToken}` },
      })
      if (driveResponse.ok) {
        const driveBody = await driveResponse.json() as { drives?: DrivePickerLocation[] }
        drivePickerLocations.value.push(...(driveBody.drives || []))
      }
    } catch {
      // 共有ドライブ一覧が取得できなくても、マイドライブの選択は続けられる。
    }
    await selectDrivePickerLocation('')
  } catch (error) {
    driveError.value = error instanceof Error ? error.message : 'Google Driveのファイル一覧を読み込めませんでした。'
    drivePickerLoading.value = false
  }
}

async function selectDrivePickerLocation(locationId: string) {
  const location = drivePickerLocations.value.find((item) => item.id === locationId)
  const rootId = locationId || 'root'
  drivePickerLocationId.value = locationId
  drivePickerBreadcrumbs.value = [{ id: rootId, name: location?.name || 'マイドライブ' }]
  drivePickerSearch.value = ''
  drivePickerSelectedFile.value = null
  await loadDrivePickerFolder(rootId)
}

async function loadDrivePickerFolder(folderId: string) {
  drivePickerLoading.value = true
  driveError.value = ''
  try {
    const params = new URLSearchParams({
      q: `'${folderId.replaceAll("'", "\\'")}' in parents and trashed = false`,
      spaces: 'drive',
      orderBy: 'folder,name',
      pageSize: '1000',
      fields: 'files(id,name,mimeType,modifiedTime,webViewLink,iconLink)',
      supportsAllDrives: 'true',
      includeItemsFromAllDrives: 'true',
    })
    if (drivePickerLocationId.value) {
      params.set('corpora', 'drive')
      params.set('driveId', drivePickerLocationId.value)
    } else {
      params.set('corpora', 'user')
    }
    const response = await fetch(`https://www.googleapis.com/drive/v3/files?${params}`, {
      headers: { Authorization: `Bearer ${drivePickerAccessToken}` },
    })
    if (!response.ok) {
      const body = await response.json().catch(() => ({})) as { error?: { message?: string } }
      throw new Error(body.error?.message || `Google Drive API error: ${response.status}`)
    }
    const body = await response.json() as { files?: DrivePickerFile[] }
    drivePickerFiles.value = (body.files || []).filter((file) =>
      isDrivePickerFolder(file) || isDrivePickerSelectableFile(file),
    )
  } catch (error) {
    driveError.value = error instanceof Error ? error.message : 'Google Driveのファイル一覧を読み込めませんでした。'
  } finally {
    drivePickerLoading.value = false
  }
}

async function openDrivePickerFolder(file: DrivePickerFile) {
  drivePickerBreadcrumbs.value.push({ id: file.id, name: file.name })
  drivePickerSearch.value = ''
  drivePickerSelectedFile.value = null
  await loadDrivePickerFolder(file.id)
}

async function openDrivePickerBreadcrumb(index: number) {
  const breadcrumb = drivePickerBreadcrumbs.value[index]
  drivePickerBreadcrumbs.value = drivePickerBreadcrumbs.value.slice(0, index + 1)
  drivePickerSearch.value = ''
  drivePickerSelectedFile.value = null
  await loadDrivePickerFolder(breadcrumb.id)
}

async function selectGoogleDriveFile(file: DrivePickerFile) {
  if (driveLoading.value) return
  await addGoogleDriveFileById(file.id, file.webViewLink, drivePickerAccessToken)
}

async function confirmGoogleDriveFile() {
  if (!drivePickerSelectedFile.value || driveLoading.value) return
  await selectGoogleDriveFile(drivePickerSelectedFile.value)
}

function isDrivePickerFolder(file: DrivePickerFile) {
  return file.mimeType === 'application/vnd.google-apps.folder'
}

function isDrivePickerSelectableFile(file: DrivePickerFile) {
  return [
    'application/vnd.google-apps.document',
    'application/vnd.google-apps.spreadsheet',
    'application/vnd.google-apps.presentation',
    'application/pdf',
  ].includes(file.mimeType) || file.mimeType.startsWith('image/')
}

function drivePickerFileIcon(file: DrivePickerFile) {
  if (file.mimeType === 'application/vnd.google-apps.folder') return 'mdi-folder-outline'
  if (file.mimeType.includes('spreadsheet')) return 'mdi-google-spreadsheet'
  if (file.mimeType.includes('presentation')) return 'mdi-google-slides'
  if (file.mimeType.includes('document')) return 'mdi-file-document-outline'
  if (file.mimeType === 'application/pdf') return 'mdi-file-pdf-box'
  if (file.mimeType.startsWith('image/')) return 'mdi-file-image-outline'
  return 'mdi-file-outline'
}

function driveModifiedLabel(modifiedTime: string) {
  const date = new Date(modifiedTime)
  return Number.isNaN(date.getTime())
    ? 'Google Drive'
    : `更新 ${new Intl.DateTimeFormat('ja-JP', { dateStyle: 'medium' }).format(date)}`
}

async function loadCalendarEvents(existingAccessToken = '') {
  if (!calendarEnabled.value || calendarLoading.value) return
  calendarLoading.value = true
  calendarError.value = ''
  meetError.value = ''
  try {
    const accessToken = existingAccessToken || await requestGoogleAccessToken([
      GOOGLE_SCOPES.calendar,
      ...(meetEnabled.value ? [GOOGLE_SCOPES.meet] : []),
    ].join(' '))
    const [year, month, day] = selectedDate.value.split('-').map(Number)
    const start = new Date(year, month - 1, day, 0, 0, 0)
    const end = new Date(year, month - 1, day + 1, 0, 0, 0)
    const params = new URLSearchParams({
      timeMin: start.toISOString(),
      timeMax: end.toISOString(),
      singleEvents: 'true',
      orderBy: 'startTime',
      maxResults: '30',
      fields: 'items(summary,status,visibility,start,end,attendees(self,responseStatus),conferenceData(conferenceId,entryPoints(entryPointType,uri)))',
    })
    const calendarResponse = await fetch(`https://www.googleapis.com/calendar/v3/calendars/primary/events?${params}`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    })
    if (!calendarResponse.ok) {
      const body = await calendarResponse.json().catch(() => ({})) as { error?: { message?: string } }
      throw new Error(body.error?.message || `Google Calendar API error: ${calendarResponse.status}`)
    }
    const body = await calendarResponse.json() as {
      items?: Array<{
        summary?: string
        status?: string
        visibility?: string
        start?: { dateTime?: string; date?: string }
        end?: { dateTime?: string; date?: string }
        attendees?: Array<{ self?: boolean; responseStatus?: WorkJournalCalendarEvent['response_status'] }>
        conferenceData?: {
          conferenceId?: string
          entryPoints?: Array<{ entryPointType?: string; uri?: string }>
        }
      }>
    }
    const events = (body.items ?? [])
      .filter((event) => event.status !== 'cancelled')
      .map<WorkJournalCalendarEvent>((event) => {
        const privateEvent = event.visibility === 'private'
        const meetUrl = event.conferenceData?.entryPoints?.find((entry) => entry.entryPointType === 'video')?.uri || ''
        const meetCode = event.conferenceData?.conferenceId?.trim()
          || meetUrl.match(/meet\.google\.com\/([a-z0-9-]+)/i)?.[1]
          || ''
        return {
          title: privateEvent ? '非公開の予定' : event.summary?.trim() || '名称未設定の予定',
          start: event.start?.dateTime || event.start?.date || '',
          end: event.end?.dateTime || event.end?.date || '',
          all_day: Boolean(event.start?.date && !event.start?.dateTime),
          private: privateEvent,
          response_status: event.attendees?.find((attendee) => attendee.self)?.responseStatus || '',
          meet_code: meetCode,
          meet_url: meetUrl.startsWith('https://meet.google.com/') ? meetUrl : '',
          meet_participant_count: null,
          meet_artifacts: [],
        }
      })
    calendarEvents.value = meetEnabled.value ? await loadMeetContext(accessToken, events) : events
    if (!calendarEvents.value.length) calendarError.value = 'この日の予定はありませんでした。予定なしでも始められます。'
  } catch (error) {
    calendarError.value = error instanceof Error ? error.message : '予定を読み込めませんでした。'
  } finally {
    calendarLoading.value = false
  }
}

type MeetConferenceRecord = { name?: string }
type MeetArtifactResponse = {
  smartNotes?: Array<{ state?: string; docsDestination?: { exportUri?: string; document?: string } }>
  transcripts?: Array<{ state?: string; docsDestination?: { exportUri?: string; document?: string } }>
}

async function fetchMeetJson<T>(url: string, accessToken: string): Promise<T> {
  const response = await fetch(url, { headers: { Authorization: `Bearer ${accessToken}` } })
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { error?: { message?: string } }
    throw new Error(body.error?.message || `Google Meet API error: ${response.status}`)
  }
  return await response.json() as T
}

function meetDocumentUrl(destination?: { exportUri?: string; document?: string }) {
  if (destination?.exportUri?.startsWith('https://docs.google.com/')) return destination.exportUri
  if (destination?.document?.match(/^[A-Za-z0-9_-]+$/)) return `https://docs.google.com/document/d/${destination.document}/view`
  return ''
}

async function loadMeetRecord(accessToken: string, event: WorkJournalCalendarEvent): Promise<WorkJournalCalendarEvent> {
  if (!event.meet_code) return event
  const [year, month, day] = selectedDate.value.split('-').map(Number)
  const rangeStart = new Date(year, month - 1, day, 0, 0, 0).toISOString()
  const rangeEnd = new Date(year, month - 1, day + 1, 0, 0, 0).toISOString()
  const recordParams = new URLSearchParams({
    filter: `space.meeting_code = "${event.meet_code}" AND start_time >= "${rangeStart}" AND start_time < "${rangeEnd}"`,
    pageSize: '10',
    fields: 'conferenceRecords(name,startTime,endTime)',
  })
  const records = await fetchMeetJson<{ conferenceRecords?: MeetConferenceRecord[] }>(
    `https://meet.googleapis.com/v2/conferenceRecords?${recordParams}`,
    accessToken,
  )
  const recordName = records.conferenceRecords?.[0]?.name
  if (!recordName?.match(/^conferenceRecords\/[A-Za-z0-9_-]+$/)) return event

  const artifactParams = new URLSearchParams({ pageSize: String(MEET_ARTIFACT_PAGE_SIZE) })
  const [participantResult, smartNotesResult, transcriptsResult] = await Promise.allSettled([
    (async () => {
      // 参加者はリソース名だけを取得して人数を数える。氏名・メールアドレスは取得しない。
      let count = 0
      let pageToken = ''
      for (let page = 0; page < MEET_PARTICIPANT_MAX_PAGES; page += 1) {
        const params = new URLSearchParams({
          pageSize: String(MEET_PARTICIPANT_PAGE_SIZE),
          fields: 'participants(name),nextPageToken',
        })
        if (pageToken) params.set('pageToken', pageToken)
        const response = await fetchMeetJson<{ participants?: Array<{ name?: string }>; nextPageToken?: string }>(
          `https://meet.googleapis.com/v2/${recordName}/participants?${params}`,
          accessToken,
        )
        count += response.participants?.length || 0
        pageToken = response.nextPageToken || ''
        if (!pageToken) break
      }
      return count
    })(),
    fetchMeetJson<MeetArtifactResponse>(`https://meet.googleapis.com/v2/${recordName}/smartNotes?${artifactParams}`, accessToken),
    fetchMeetJson<MeetArtifactResponse>(`https://meet.googleapis.com/v2/${recordName}/transcripts?${artifactParams}`, accessToken),
  ])
  const smartNotes = smartNotesResult.status === 'fulfilled' ? smartNotesResult.value : {}
  const transcripts = transcriptsResult.status === 'fulfilled' ? transcriptsResult.value : {}
  if ([participantResult, smartNotesResult, transcriptsResult].some((result) => result.status === 'rejected')) {
    meetError.value = '一部のMeet実績を確認できませんでした。会議の参加権限によって表示できない場合があります。'
  }
  return {
    ...event,
    meet_participant_count: participantResult.status === 'fulfilled' ? participantResult.value : null,
    meet_artifacts: [
      ...(smartNotes.smartNotes || []).map((item) => ({
        kind: 'smart_note' as const,
        state: item.state || '',
        url: meetDocumentUrl(item.docsDestination),
      })),
      ...(transcripts.transcripts || []).map((item) => ({
        kind: 'transcript' as const,
        state: item.state || '',
        url: meetDocumentUrl(item.docsDestination),
      })),
    ],
  }
}

async function loadMeetContext(accessToken: string, events: WorkJournalCalendarEvent[]) {
  const meetEvents = events.filter((event) => event.meet_code).slice(0, MEET_CONTEXT_MAX_EVENTS)
  if (!meetEvents.length) return events
  const enriched = new Map<string, WorkJournalCalendarEvent>()
  const results = await Promise.allSettled(meetEvents.map((event) => loadMeetRecord(accessToken, event)))
  results.forEach((result, index) => {
    const source = meetEvents[index]
    if (result.status === 'fulfilled') enriched.set(`${source.start}-${source.title}`, result.value)
  })
  if (results.some((result) => result.status === 'rejected')) {
    meetError.value = '一部のMeet実績を確認できませんでした。参加権限やOAuthスコープをご確認ください。'
  }
  return events.map((event) => enriched.get(`${event.start}-${event.title}`) || event)
}

function gmailDayRange() {
  const [year, month, day] = selectedDate.value.split('-').map(Number)
  const start = new Date(year, month - 1, day, 0, 0, 0)
  const end = new Date(year, month - 1, day + 1, 0, 0, 0)
  return {
    after: Math.floor(start.getTime() / 1000),
    before: Math.floor(end.getTime() / 1000),
  }
}

async function listGmailMessages(accessToken: string, query: string, maxResults = 1, pageToken = '', labelId = '') {
  const params = new URLSearchParams({
    q: query,
    maxResults: String(maxResults),
    includeSpamTrash: 'false',
    fields: 'messages(id,threadId),nextPageToken',
  })
  if (pageToken) params.set('pageToken', pageToken)
  if (labelId) params.append('labelIds', labelId)
  const response = await fetch(`https://gmail.googleapis.com/gmail/v1/users/me/messages?${params}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: 'no-store',
  })
  const responseText = await response.text()
  let body: {
    messages?: Array<{ id?: string; threadId?: string }>
    nextPageToken?: string
    error?: { message?: string }
  } = {}
  if (responseText.trim()) {
    try {
      body = JSON.parse(responseText) as typeof body
    } catch {
      if (response.ok) throw new Error('Gmail APIから読み取れない応答が返されました。もう一度お試しください。')
    }
  }
  if (!response.ok) {
    throw new Error(body.error?.message || `Gmail API error: ${response.status}`)
  }
  // 部分レスポンスで該当メールが0件の場合、本文が空になることがあるため {} を0件として返す。
  return body
}

async function countGmailMessages(accessToken: string, query: string, labelId: 'INBOX' | 'SENT') {
  // 件数は活動量の目安なので、上限まで数えて打ち切る。総数の正確さは必要としない。
  let count = 0
  let pageToken = ''
  for (let page = 0; page < GMAIL_COUNT_MAX_PAGES; page += 1) {
    const response = await listGmailMessages(accessToken, query, GMAIL_COUNT_PAGE_SIZE, pageToken, labelId)
    count += response.messages?.length ?? 0
    pageToken = response.nextPageToken || ''
    if (!pageToken) break
  }
  return count
}

function gmailHeader(headers: Array<{ name?: string; value?: string }> | undefined, name: string) {
  return headers?.find((header) => header.name?.toLowerCase() === name.toLowerCase())?.value?.trim() || ''
}

function senderLabel(value: string) {
  const named = value.match(/^\s*"?([^"<]+?)"?\s*</)?.[1]?.trim()
  return named || value.replace(/<[^>]+>/g, '').trim() || '差出人不明'
}

async function fetchGmailMetadata(accessToken: string, messageId: string) {
  const params = new URLSearchParams({
    format: 'metadata',
    metadataHeaders: 'Subject',
    fields: 'id,threadId,payload(headers)',
  })
  params.append('metadataHeaders', 'From')
  const response = await fetch(
    `https://gmail.googleapis.com/gmail/v1/users/me/messages/${encodeURIComponent(messageId)}?${params}`,
    { headers: { Authorization: `Bearer ${accessToken}` }, cache: 'no-store' },
  )
  if (!response.ok) return null
  const responseText = await response.text()
  if (!responseText.trim()) return null
  try {
    return JSON.parse(responseText) as {
      threadId?: string
      payload?: { headers?: Array<{ name?: string; value?: string }> }
    }
  } catch {
    return null
  }
}

/** Gmailを一度に叩きすぎないよう、同時実行数を抑えて順に処理する。 */
async function mapWithConcurrency<T, R>(items: T[], limit: number, worker: (item: T) => Promise<R>) {
  const results: R[] = []
  let cursor = 0
  const runners = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (cursor < items.length) {
      const index = cursor
      cursor += 1
      results[index] = await worker(items[index])
    }
  })
  await Promise.all(runners)
  return results
}

/**
 * その日のメールを件名と差出人で分類する。判定はすべてブラウザ内で完結し、
 * 保存するのは分類ごとの件数だけで、件名・差出人はサーバーへ送らない。
 */
async function classifyDayMail(accessToken: string, dayQuery: string) {
  const { sources, request_types: requestTypes } = mailRules.value
  if (!sources.length && !requestTypes.length) {
    emailCategories.value = []
    emailClassifiedCount.value = 0
    return
  }
  const sentLimit = Math.floor(GMAIL_CLASSIFY_MAX_MESSAGES / 2)
  const [inbox, sent] = await Promise.all([
    listGmailMessages(accessToken, dayQuery, GMAIL_CLASSIFY_MAX_MESSAGES, '', 'INBOX'),
    listGmailMessages(accessToken, dayQuery, sentLimit, '', 'SENT'),
  ])
  const targets = [
    ...(inbox.messages ?? []).map((message) => ({ ...message, direction: 'received' as const })),
    ...(sent.messages ?? []).map((message) => ({ ...message, direction: 'sent' as const })),
  ].filter((message) => message.id)
  const fetched = await mapWithConcurrency(targets, GMAIL_CLASSIFY_CONCURRENCY, async (target) => {
    const body = await fetchGmailMetadata(accessToken, target.id || '')
    if (!body) return null
    return {
      subject: gmailHeader(body.payload?.headers, 'Subject'),
      from: gmailHeader(body.payload?.headers, 'From'),
      threadId: body.threadId || target.threadId || '',
      direction: target.direction,
    } satisfies ClassifiableMessage
  })
  const messages = fetched.filter((message): message is ClassifiableMessage => Boolean(message))
  emailClassifiedCount.value = messages.length
  emailCategories.value = classifyMailMessages(messages, sources, requestTypes)
}

async function loadEmailContext(existingAccessToken = '') {
  if (!gmailEnabled.value || emailLoading.value) return
  emailLoading.value = true
  emailError.value = ''
  try {
    const accessToken = existingAccessToken || await requestGoogleAccessToken(GOOGLE_SCOPES.gmail)
    const { after, before } = gmailDayRange()
    const dayQuery = `after:${after} before:${before}`
    const requestQuery = `${dayQuery} {依頼 お願い 確認 対応 回答 提出 期限 締切}`
    const [received, sent, unread, requests] = await Promise.all([
      countGmailMessages(accessToken, dayQuery, 'INBOX'),
      countGmailMessages(accessToken, dayQuery, 'SENT'),
      countGmailMessages(accessToken, `${dayQuery} is:unread`, 'INBOX'),
      listGmailMessages(accessToken, requestQuery, GMAIL_REQUEST_CANDIDATE_LIMIT, '', 'INBOX'),
    ])
    const requestMessages = await Promise.all(
      (requests.messages ?? []).filter((message) => message.id).map(async (message) => {
        const params = new URLSearchParams({
          format: 'metadata',
          metadataHeaders: 'Subject',
          fields: 'id,threadId,snippet,payload(headers)',
        })
        params.append('metadataHeaders', 'From')
        const response = await fetch(
          `https://gmail.googleapis.com/gmail/v1/users/me/messages/${encodeURIComponent(message.id || '')}?${params}`,
          { headers: { Authorization: `Bearer ${accessToken}` }, cache: 'no-store' },
        )
        if (!response.ok) return null
        const responseText = await response.text()
        if (!responseText.trim()) return null
        let body: {
          threadId?: string
          snippet?: string
          payload?: { headers?: Array<{ name?: string; value?: string }> }
        }
        try {
          body = JSON.parse(responseText) as typeof body
        } catch {
          return null
        }
        const threadId = body.threadId || message.threadId || ''
        return {
          subject: (gmailHeader(body.payload?.headers, 'Subject') || '件名なし').slice(0, 255),
          sender: senderLabel(gmailHeader(body.payload?.headers, 'From')).slice(0, 255),
          snippet: body.snippet?.trim().slice(0, 500) || '',
          summary: '',
          url: threadId ? `https://mail.google.com/mail/u/0/#all/${encodeURIComponent(threadId)}` : '',
        }
      }),
    )
    const context: WorkJournalEmailContext = {
      received_count: received,
      sent_count: sent,
      unread_count: unread,
      request_candidates: requestMessages.filter((message): message is NonNullable<typeof message> => Boolean(message)),
    }
    emailContext.value = await summarizeWorkJournalEmails(context)
    try {
      await classifyDayMail(accessToken, dayQuery)
    } catch {
      // 分類できなくても件数と依頼候補は使えるため、日報の作成は止めない。
      emailCategories.value = []
      emailClassifiedCount.value = 0
    }
  } catch (error) {
    emailError.value = error instanceof Error ? error.message : 'この日のメールを確認できませんでした。'
  } finally {
    emailLoading.value = false
  }
}

function calendarEventLabel(event: WorkJournalCalendarEvent) {
  if (event.all_day) return `終日 ${event.title}`
  const date = new Date(event.start)
  const time = Number.isNaN(date.getTime()) ? '' : new Intl.DateTimeFormat('ja-JP', { hour: '2-digit', minute: '2-digit', hour12: false }).format(date)
  return `${time} ${event.title}`.trim()
}

function meetingActivityLabel(meeting: { title: string; start: string }) {
  const date = new Date(meeting.start)
  const time = Number.isNaN(date.getTime()) ? '' : new Intl.DateTimeFormat('ja-JP', { hour: '2-digit', minute: '2-digit', hour12: false }).format(date)
  return `${time} ${meeting.title}`.trim()
}

function calendarResponseLabel(status: WorkJournalCalendarEvent['response_status']) {
  return ({
    accepted: '参加予定',
    declined: '欠席予定',
    tentative: '仮承諾',
    needsAction: '出欠未回答',
  } as Record<string, string>)[status] || ''
}

function meetArtifactLabel(kind: 'smart_note' | 'transcript') {
  return kind === 'smart_note' ? 'Geminiの会議メモ' : '文字起こし'
}

function currentSituation(): WorkJournalSituationContext {
  const now = new Date()
  const hour = now.getHours()
  const timeOfDay = hour < 11 ? '朝' : hour < 16 ? '昼' : hour < 19 ? '夕方' : '夜'
  return {
    local_datetime: now.toISOString(),
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    time_of_day: timeOfDay,
    weather_summary: weatherSummary.value,
  }
}

function weatherLabel(code: number) {
  if (code === 0) return '晴れ'
  if ([1, 2].includes(code)) return '晴れ時々曇り'
  if (code === 3) return '曇り'
  if ([45, 48].includes(code)) return '霧'
  if ([51, 53, 55, 56, 57].includes(code)) return '霧雨'
  if ([61, 63, 65, 66, 67, 80, 81, 82].includes(code)) return '雨'
  if ([71, 73, 75, 77, 85, 86].includes(code)) return '雪'
  if ([95, 96, 99].includes(code)) return '雷雨'
  return '変わりやすい天気'
}

async function loadCurrentWeather() {
  if (weatherLoading.value) return
  if (!navigator.geolocation) {
    return
  }
  weatherLoading.value = true
  try {
    const position = await new Promise<GeolocationPosition>((resolve, reject) => {
      navigator.geolocation.getCurrentPosition(resolve, reject, {
        enableHighAccuracy: false,
        timeout: 8000,
        maximumAge: 30 * 60 * 1000,
      })
    })
    const latitude = Number(position.coords.latitude.toFixed(2))
    const longitude = Number(position.coords.longitude.toFixed(2))
    const latitudeLabel = `${latitude >= 0 ? '北緯' : '南緯'}${Math.abs(latitude).toFixed(2)}°`
    const longitudeLabel = `${longitude >= 0 ? '東経' : '西経'}${Math.abs(longitude).toFixed(2)}°`
    weatherLocation.value = `${latitudeLabel}・${longitudeLabel}付近`
    const params = new URLSearchParams({
      latitude: latitude.toFixed(2),
      longitude: longitude.toFixed(2),
      current: 'temperature_2m,apparent_temperature,weather_code',
      timezone: 'auto',
    })
    const response = await fetch(`https://api.open-meteo.com/v1/forecast?${params}`)
    if (!response.ok) throw new Error(`天気API error: ${response.status}`)
    const body = await response.json() as {
      current?: { temperature_2m?: number; apparent_temperature?: number; weather_code?: number }
    }
    if (!body.current || typeof body.current.weather_code !== 'number') throw new Error('天気を読み取れませんでした。')
    const temperature = typeof body.current.temperature_2m === 'number'
      ? `、気温は${Math.round(body.current.temperature_2m)}℃ほどでした`
      : 'でした'
    weatherSummary.value = `今日は${weatherLabel(body.current.weather_code)}${temperature}。`
  } catch {
    // 天気は雑談用の任意情報なので、取得できなくても日報を妨げない。
  } finally {
    weatherLoading.value = false
  }
}

async function loadRecentJournals() {
  // 前回の続きを思い出す手掛かりとして、直近に確定した日報の要約だけを渡す。
  recentJournals.value = []
  const [year, month, day] = selectedDate.value.split('-').map(Number)
  const dateFrom = toDateKey(new Date(year, month - 1, day - 14))
  const dateTo = toDateKey(new Date(year, month - 1, day - 1))
  try {
    const history = await getWorkJournals(dateFrom, dateTo)
    recentJournals.value = history
      .slice()
      .sort((left, right) => right.journal_date.localeCompare(left.journal_date))
      .slice(0, 2)
      .map((record) => ({
        journal_date: record.journal_date,
        summary_items: recordSummaryItems(record).slice(0, 6),
        next_focus: record.next_focus,
      }))
  } catch {
    // 過去の日報は補助情報なので、取得できなくても今日の振り返りは始められる。
  }
}

async function loadAutomaticContext() {
  await loadRecentJournals()
  await ensureGoogleIntegrations()
  // 有効な機能のスコープだけを1回の許可画面でまとめて求める。
  const scopes = [
    ...(calendarEnabled.value ? [GOOGLE_SCOPES.calendar] : []),
    ...(gmailEnabled.value ? [GOOGLE_SCOPES.gmail] : []),
    ...(meetEnabled.value ? [GOOGLE_SCOPES.meet] : []),
  ]
  // Google連携と位置情報の許可画面が重ならないよう、順番に確認する。
  if (scopes.length) {
    try {
      const accessToken = await requestGoogleAccessToken(scopes.join(' '))
      await Promise.all([
        calendarEnabled.value ? loadCalendarEvents(accessToken) : undefined,
        gmailEnabled.value ? loadEmailContext(accessToken) : undefined,
      ])
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Googleの予定とメールを確認できませんでした。'
      if (calendarEnabled.value) calendarError.value = message
      if (gmailEnabled.value) emailError.value = message
    }
  }
  await loadCurrentWeather()
}

function recordSummaryItems(record: WorkJournalRecord) {
  if (record.summary_items?.length) return record.summary_items
  return record.summary.match(/[^。！？\n]+[。！？]?/g)?.map((item) => item.trim()).filter(Boolean) || [record.summary]
}

function updateDraftSummaryItems(value: unknown) {
  if (!draft.value) return
  const items = String(value).split('\n').map((item) => item.trim().replace(/^[・●-]\s*/, '')).filter(Boolean).slice(0, 12)
  draft.value.summary_items = items
  draft.value.summary = items.join(' ')
}

const draftAnalysisGroups = computed(() => {
  const analysis = draft.value?.analysis
  if (!analysis) return []
  return MONTHLY_INSIGHT_GROUPS
    .filter((group) => analysis[group.key].length)
    .map((group) => ({ key: group.key, label: labels.value.insightGroups[group.key].label, icon: group.icon, items: analysis[group.key] }))
})

function updateDraftAnalysis(key: MonthlyInsightKey, value: unknown) {
  if (!draft.value) return
  draft.value.analysis[key] = String(value)
    .split('\n')
    .map((item) => item.trim().replace(/^[・●-]\s*/, ''))
    .filter(Boolean)
    .slice(0, 30)
}

function moveReviewWork(offset: number) {
  const count = draft.value?.work_items.length ?? 0
  if (!count) return
  reviewWorkIndex.value = (reviewWorkIndex.value + offset + count) % count
}

function moveDetailWork(offset: number) {
  const count = selectedRecord.value?.work_items.length ?? 0
  if (!count) return
  detailWorkIndex.value = (detailWorkIndex.value + offset + count) % count
}

function mailCategoryKey(count: WorkJournalEmailCategoryCount) {
  return `${count.rule_id}-${count.source_id}-${count.name}`
}

function meetingKey(event: WorkJournalCalendarEvent) {
  return `${event.start}\u0000${event.title}`
}

function inferParticipatedMeetingKeys(nextDraft: WorkJournalDraft) {
  const evidence = [
    ...messages.value.filter((message) => message.role === 'user').map((message) => message.text),
    ...nextDraft.work_items.flatMap((item) => [item.title, item.description, item.result]),
  ].join(' ')
  const participationMentioned = /(参加|出席|打ち合わせ|会議|ミーティング)/.test(evidence)
  if (!participationMentioned) return []
  return calendarEvents.value
    .filter((event) => !event.private && event.title.length >= 2 && evidence.includes(event.title))
    .map(meetingKey)
}

function buildActivityContext() {
  const selected = new Set(selectedMeetingKeys.value)
  return {
    email_counts_available: gmailEnabled.value && !emailError.value && !emailLoading.value,
    received_email_count: emailError.value ? 0 : emailContext.value.received_count,
    sent_email_count: emailError.value ? 0 : emailContext.value.sent_count,
    unread_email_count: emailError.value ? 0 : emailContext.value.unread_count,
    // 保存するのは分類ごとの件数だけで、件名・差出人はブラウザの外へ出さない。
    email_classified_count: emailError.value ? 0 : emailClassifiedCount.value,
    email_categories: emailError.value ? [] : emailCategories.value,
    participated_meetings: calendarEvents.value
      .filter((event) => selected.has(meetingKey(event)))
      .map((event) => ({ title: event.title, start: event.start, end: event.end })),
  }
}

async function requestTurn() {
  if (aiThinking.value || !selectedOrgUnit.value) return
  aiThinking.value = true
  turnError.value = ''
  turnController = new AbortController()
  try {
    await ensureAttachmentInsights()
    if (!dialogOpen.value) return
    const uploads = attachments.value
    const insights = uploads.map((upload) => upload.insight).filter(Boolean) as WorkJournalAttachmentInsight[]
    // 全件の要約がそろったときだけ本文を省き、1件でも欠ければ従来どおり資料ごと渡す。
    const analyzed = uploads.length > 0 && insights.length === uploads.length
    const result = await requestWorkJournalTurn({
      journal_date: selectedDate.value,
      department: selectedOrgUnit.value.name,
      participant: participant.value,
      messages: messages.value.map(({ role, text }) => ({ role, text })),
      calendar_events: calendarEvents.value,
      email_context: emailContext.value,
      attachments: uploads.map(({ name, mime_type, data }) => ({ name, mime_type, data: analyzed ? '' : data })),
      attachment_insights: analyzed ? insights : [],
      recent_journals: recentJournals.value,
      situation_context: currentSituation(),
    }, turnController.signal)
    const reply: ChatMessage = { id: Date.now(), role: 'assistant', text: result.reply }
    messages.value.push(reply)
    revealMessage(reply)
    speakAiMessage(result.reply)
    if (result.is_complete && result.draft) {
      const confirmedDraft = structuredClone(result.draft)
      // 資料の識別情報だけ日報へ残す。本文と本文要約は保存しない。
      confirmedDraft.references = attachments.value.map((attachment) => ({
        name: attachment.name,
        url: attachment.sourceUrl || '',
        document_title: attachment.insight?.document_title || '',
        related_business: attachment.insight?.related_business || '',
        key_topics: attachment.insight?.key_topics?.slice(0, 8) || [],
      }))
      selectedMeetingKeys.value = inferParticipatedMeetingKeys(confirmedDraft)
      confirmedDraft.activity_context = buildActivityContext()
      draft.value = confirmedDraft
      reviewWorkIndex.value = 0
      dialogStep.value = 'review'
    }
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') return
    turnError.value = error instanceof Error ? error.message : 'AIとの対話を続けられませんでした。'
  } finally {
    aiThinking.value = false
    turnController = null
  }
}

async function beginJournal() {
  unlockAiAudio()
  dialogStep.value = 'conversation'
  stopReveal()
  messages.value = []
  await requestTurn()
}

async function sendResponse() {
  const text = responseText.value.trim()
  if ((!text && !attachments.value.length) || aiThinking.value || isVoiceListening.value || isVoiceTranscribing.value) return
  unlockAiAudio()
  const messageText = text || '今日作成・更新した資料を添付しました。内容を手掛かりに振り返りたいです。'
  messages.value.push({ id: Date.now(), role: 'user', text: messageText })
  responseText.value = ''
  await requestTurn()
}

async function finishConversation() {
  if (aiThinking.value || isVoiceListening.value || isVoiceTranscribing.value) return
  unlockAiAudio()
  messages.value.push({ id: Date.now(), role: 'user', text: '今日はここまでで大丈夫です。まとめてください。' })
  responseText.value = ''
  await requestTurn()
}

async function saveDraft() {
  if (!canEdit.value || !draft.value || !selectedOrgUnit.value || saving.value) return
  saving.value = true
  try {
    const saved = await saveWorkJournal({
      journal_date: selectedDate.value,
      org_unit_id: selectedOrgUnit.value.id,
      org_unit_name: selectedOrgUnit.value.name,
      participant: participant.value,
      ...draft.value,
      activity_context: buildActivityContext(),
    })
    const index = records.value.findIndex((record) => record.journal_date === saved.journal_date)
    if (index >= 0) records.value.splice(index, 1, saved)
    else records.value.push(saved)
    closeDialog()
    notify(`${dateLabel(saved.journal_date)}の記録を保存しました`)
  } catch (error) {
    turnError.value = error instanceof Error ? error.message : '記録を保存できませんでした。'
  } finally {
    saving.value = false
  }
}

async function removeSelectedRecord() {
  const record = selectedRecord.value
  if (viewingOther.value) {
    notify('他のメンバーの記録は削除できません')
    return
  }
  if (!canEdit.value) {
    notify('viewer権限では記録を削除できません')
    return
  }
  if (!record || !window.confirm(`${dateLabel(record.journal_date)}の記録を削除しますか？`)) return
  try {
    await deleteWorkJournal(record.journal_date)
    records.value = records.value.filter((item) => item.journal_date !== record.journal_date)
    notify('記録を削除しました')
  } catch (error) {
    notify(error instanceof Error ? error.message : '記録を削除できませんでした')
  }
}

// 初期表示で自分を選ぶときは、onMountedの読み込みと重ならないよう見送る。
watch(viewingEmail, async (_next, previous) => {
  if (!previous) return
  detailWorkIndex.value = 0
  await loadRecords()
})

onMounted(async () => {
  void ensureGoogleIntegrations()
  try {
    journalMembers.value = await getWorkJournalMembers()
    viewingEmail.value = journalMembers.value.find((member) => member.is_self)?.email || currentEmail.value
  } catch {
    // 一覧を取得できないときは自分の日報だけを扱う。
  }
  try {
    mailRules.value = await getMailClassificationRules()
  } catch {
    // マスターを取得できないときは分類せず、件数だけの日報として動かす。
  }
  try {
    orgUnits.value = await getOrgUnits()
  } catch {
    // 取得できない場合も未解決として扱い、誤った組織で保存させない。
  } finally {
    orgUnitsLoaded.value = true
  }
  await loadRecords()
})
onUnmounted(() => {
  stopReveal()
  cancelVoiceInput()
  stopAiSpeech()
})
</script>

<template>
  <section class="page work-journal-page">
    <div class="page-heading page-heading--compact">
      <div>
        <div class="eyebrow">{{ viewingOther ? 'MEMBER WORK JOURNAL' : 'MY WORK JOURNAL' }}</div>
        <h1>日々の記録</h1>
        <p v-if="viewingOther">{{ viewingMember?.name }}さんの記録を閲覧しています。編集はできません。</p>
        <p v-else>今日一日をAIと短く振り返り、確認した記録だけをカレンダーへ残します。</p>
      </div>
      <div class="heading-actions">
        <v-btn variant="tonal" color="primary" prepend-icon="mdi-calendar-today" @click="goToday">今日へ</v-btn>
        <v-btn v-if="!viewingOther" color="primary" prepend-icon="mdi-notebook-edit-outline" :disabled="!canEdit || orgUnitUnresolved" @click="openJournal(toDateKey(today))">今日の記録をつける</v-btn>
        <v-btn v-else variant="outlined" prepend-icon="mdi-account-arrow-left-outline" @click="viewingEmail = currentEmail">自分の記録へ戻る</v-btn>
      </div>
    </div>

    <div v-if="canSelectMember" class="journal-member-bar">
      <v-icon size="18">mdi-account-group-outline</v-icon>
      <v-select
        v-model="viewingEmail"
        :items="memberOptions"
        label="表示するメンバー"
        density="comfortable"
        variant="outlined"
        hide-details
      ></v-select>
      <span v-if="viewingOther" class="journal-member-bar__readonly"><v-icon size="15">mdi-eye-outline</v-icon>閲覧のみ</span>
      <small v-else>自組織とその配下メンバーの記録を確認できます。</small>
    </div>

    <div v-if="devMode && orgUnits.length" class="journal-member-bar">
      <v-icon size="18">mdi-sitemap-outline</v-icon>
      <v-select
        :model-value="selectedOrgUnit?.id"
        :items="orgUnits"
        item-title="name"
        item-value="id"
        label="記入する組織（開発モード）"
        density="comfortable"
        variant="outlined"
        hide-details
        @update:model-value="devOrgUnitId = $event"
      ></v-select>
      <small>ログインなしで動かしているため、記録をつける組織をここで選びます。</small>
    </div>

    <div v-if="orgUnitUnresolved && !viewingOther" class="journal-error"><v-icon size="18">mdi-alert-circle-outline</v-icon>{{ devMode ? '組織マスターに組織がまだありません。先に組織マスターで組織を登録してください。' : '所属組織が組織マスターに登録されていないため、記録を保存できません。管理者にユーザー管理画面で所属の設定を依頼してください。' }}</div>
    <div v-if="loadError" class="journal-error"><v-icon size="18">mdi-alert-circle-outline</v-icon>{{ loadError }}</div>
    <div class="journal-layout">
      <section class="panel journal-calendar-panel">
        <header class="journal-calendar-header">
          <button aria-label="前月" @click="moveMonth(-1)"><v-icon>mdi-chevron-left</v-icon></button>
          <h2>{{ monthLabel }}</h2>
          <button aria-label="翌月" @click="moveMonth(1)"><v-icon>mdi-chevron-right</v-icon></button>
        </header>
        <div class="journal-weekdays"><span v-for="weekday in weekdayLabels" :key="weekday">{{ weekday }}</span></div>
        <div class="journal-calendar" :class="{ loading }">
          <button
            v-for="day in calendarDays"
            :key="day.key"
            :class="{ muted: !day.currentMonth, today: day.today, selected: selectedDate === day.key, recorded: !!day.record }"
            @click="selectDay(day.key)"
          >
            <span>{{ day.day }}</span>
            <div v-if="day.record"><v-icon size="15">mdi-check-circle</v-icon><b>{{ day.record.work_items.length }}件</b></div>
          </button>
        </div>
      </section>

      <aside class="panel journal-detail-panel">
        <div class="panel__header">
          <div><h2>{{ dateLabel(selectedDate) }}</h2><p>{{ selectedRecord ? '保存済みの記録' : '記録はまだありません' }}</p></div>
          <span v-if="selectedRecord" class="journal-saved-badge"><v-icon size="15">mdi-check</v-icon>保存済み</span>
        </div>
        <template v-if="selectedRecord">
          <section class="journal-summary">
            <h3>今日のまとめ</h3>
            <ul><li v-for="item in recordSummaryItems(selectedRecord)" :key="item">{{ item }}</li></ul>
          </section>
          <section v-if="selectedRecord.activity_context.email_counts_available || selectedRecord.activity_context.participated_meetings.length" class="journal-detail-group journal-activity-summary">
            <h3><v-icon size="17">mdi-chart-timeline-variant</v-icon>その日の活動情報</h3>
            <div v-if="selectedRecord.activity_context.email_counts_available" class="journal-activity-counts">
              <span>受信 <b>{{ selectedRecord.activity_context.received_email_count }}</b>件</span>
              <span>送信 <b>{{ selectedRecord.activity_context.sent_email_count }}</b>件</span>
              <span>未読 <b>{{ selectedRecord.activity_context.unread_email_count }}</b>件</span>
            </div>
            <div v-if="selectedRecord.activity_context.email_categories.length" class="journal-email-breakdown">
              <b>メールの内訳<small>{{ selectedRecord.activity_context.email_classified_count }}通を判定</small></b>
              <ul>
                <li v-for="count in selectedRecord.activity_context.email_categories" :key="mailCategoryKey(count)">
                  <span>{{ count.name }}</span>
                  <em>{{ count.category }}</em>
                  <span class="journal-email-breakdown__count">
                    受信 <b>{{ count.received }}</b> / 送信 <b>{{ count.sent }}</b>
                    <small v-if="count.thread_count">{{ count.thread_count }}案件</small>
                  </span>
                </li>
              </ul>
            </div>
            <ul v-if="selectedRecord.activity_context.participated_meetings.length">
              <li v-for="meeting in selectedRecord.activity_context.participated_meetings" :key="`${meeting.start}-${meeting.title}`">{{ meetingActivityLabel(meeting) }}</li>
            </ul>
          </section>
          <section v-if="selectedRecord.work_items.length" class="journal-detail-group journal-work-carousel journal-work-carousel--detail">
            <header><h3><v-icon size="17">mdi-briefcase-check-outline</v-icon>{{ labels.todayItems }}</h3><b>{{ detailWorkIndex + 1 }} / {{ selectedRecord.work_items.length }}</b></header>
            <div class="journal-work-carousel__stage">
              <button v-if="selectedRecord.work_items.length > 1" type="button" :aria-label="labels.prevItem" @click="moveDetailWork(-1)"><v-icon>mdi-chevron-left</v-icon></button>
              <article>
                <b>{{ selectedRecord.work_items[detailWorkIndex]?.title }}</b>
                <p>{{ selectedRecord.work_items[detailWorkIndex]?.description }}</p>
                <small v-if="selectedRecord.work_items[detailWorkIndex]?.result && selectedRecord.work_items[detailWorkIndex]?.result !== '未確認'"><v-icon size="14">mdi-progress-check</v-icon>{{ selectedRecord.work_items[detailWorkIndex]?.result }}</small>
              </article>
              <button v-if="selectedRecord.work_items.length > 1" type="button" :aria-label="labels.nextItem" @click="moveDetailWork(1)"><v-icon>mdi-chevron-right</v-icon></button>
            </div>
            <nav v-if="selectedRecord.work_items.length > 1" :aria-label="labels.itemPicker"><button v-for="(_, index) in selectedRecord.work_items" :key="index" type="button" :class="{ active: detailWorkIndex === index }" :aria-label="`${index + 1}件目を表示`" @click="detailWorkIndex = index"></button></nav>
          </section>
          <section v-if="selectedRecord.next_focus" class="journal-detail-group">
            <h3><v-icon size="17">mdi-arrow-right-circle-outline</v-icon>次に覚えておきたいこと</h3>
            <p class="journal-next-focus">{{ selectedRecord.next_focus }}</p>
          </section>
          <section v-if="selectedRecord.references.length" class="journal-detail-group journal-reference-list">
            <h3><v-icon size="17">mdi-paperclip</v-icon>関連資料</h3>
            <div v-for="reference in selectedRecord.references" :key="`${reference.name}-${reference.url}`">
              <v-icon size="16">{{ reference.url ? 'mdi-google-drive' : 'mdi-file-outline' }}</v-icon>
              <a v-if="reference.url" :href="reference.url" target="_blank" rel="noopener noreferrer">{{ reference.name }}</a>
              <span v-else>{{ reference.name }}</span>
            </div>
          </section>
          <div v-if="!viewingOther" class="journal-detail-actions">
            <v-btn variant="text" color="error" prepend-icon="mdi-trash-can-outline" :disabled="!canEdit" @click="removeSelectedRecord">削除</v-btn>
            <v-btn color="primary" prepend-icon="mdi-refresh" :disabled="!canEdit" @click="openJournal()">振り返り直す</v-btn>
          </div>
        </template>
        <div v-else class="journal-empty-detail">
          <v-icon size="46">mdi-notebook-outline</v-icon>
          <b>この日の記録はまだありません</b>
          <p v-if="viewingOther">{{ viewingMember?.name }}さんはこの日の記録を保存していません。</p>
          <template v-else>
            <p>AIとの短い会話から、今日の記録を一緒にまとめられます。</p>
            <v-btn color="primary" prepend-icon="mdi-notebook-edit-outline" :disabled="!canEdit || orgUnitUnresolved" @click="openJournal()">この日の記録をつける</v-btn>
          </template>
        </div>
      </aside>
    </div>

    <section v-if="monthlyRecords.length" class="panel journal-insights-panel">
      <div class="panel__header">
        <div>
          <h2>{{ monthLabel }}の振り返り</h2>
          <p v-if="viewingOther">{{ viewingMember?.name }}さんが保存した{{ monthlyRecords.length }}日分の記録から、{{ labels.insightSummary }}をまとめています。日付を押すとその日の記録を開けます。</p>
          <p v-else>保存した{{ monthlyRecords.length }}日分の記録から、{{ labels.insightSummary }}をまとめています。日付を押すとその日の記録を開けます。</p>
        </div>
      </div>
      <div class="journal-insights-groups">
        <article v-for="group in monthlyInsightGroups" :key="group.key">
          <h3><v-icon size="17">{{ group.icon }}</v-icon>{{ group.label }}<b>{{ group.entries.length }}</b></h3>
          <ul v-if="group.entries.length">
            <li v-for="entry in group.entries.slice(0, 6)" :key="`${entry.date}-${entry.text}`">
              <span>{{ entry.text }}</span>
              <button type="button" :aria-label="`${dateLabel(entry.date)}の記録を開く`" @click="selectDay(entry.date)">{{ shortDateLabel(entry.date) }}</button>
            </li>
          </ul>
          <p v-else class="journal-insights-empty">{{ group.empty }}</p>
          <small v-if="group.entries.length > 6">ほか{{ group.entries.length - 6 }}件</small>
        </article>
      </div>
    </section>

    <v-dialog v-model="dialogOpen" max-width="1280" persistent>
      <v-card class="dialog-card work-journal-dialog">
        <v-card-title>{{ dateLabel(selectedDate) }}の記録</v-card-title>
        <v-card-subtitle>{{ dialogStep === 'setup' ? '今日を思い出す準備' : dialogStep === 'conversation' ? 'AIと一緒に振り返り中' : '保存する内容を確認' }}</v-card-subtitle>
        <v-card-text>
          <section v-if="dialogStep === 'setup'" class="journal-setup">
            <div class="journal-opening-guide">
              <section><v-icon size="25">mdi-weather-sunset</v-icon><span><b>今日のことを気軽に残しましょう</b><small>{{ labels.startHint }}</small></span></section>
              <section><v-icon size="22">mdi-timer-sand</v-icon><span><b>3〜5分くらいを目安に振り返ります</b><small>話したいことがなくなったところで、いつでも今日のまとめを作れます。</small></span></section>
            </div>
            <div class="journal-context-guides">
              <aside class="journal-context-tip">
                <span>TIP</span>
                <v-icon size="21">mdi-lightbulb-on-outline</v-icon>
                <div><b>予定やメールは思い出すきっかけです</b><small>予定や依頼が表示されても、実際に対応したとは決めつけません。今日行ったことだけを気軽に話してください。</small></div>
              </aside>
              <aside class="journal-privacy-note">
                <span class="journal-privacy-icon" aria-hidden="true">⚠️</span>
                <div><b>予定・メール本文・Meet詳細は保存しません</b><small>保存するのは選択日のメール件数と、本人が確認した参加打ち合わせだけです。参加者名・会議メモ本文・位置情報は保存しません。</small></div>
              </aside>
            </div>
            <section v-if="calendarLoading || calendarError || calendarEvents.length" class="journal-calendar-context">
              <header><span><v-icon size="20">mdi-calendar-blank-outline</v-icon><b>この日の予定・Meet</b></span><em>一時利用のみ、保存しません</em></header>
              <div v-if="calendarLoading" class="journal-context-loading"><v-progress-circular indeterminate size="16" width="2"></v-progress-circular>予定とMeet実績を確認しています</div>
              <p v-else-if="calendarError" class="reflection-calendar-message">{{ calendarError }}</p>
              <template v-else>
                <div class="journal-calendar-events">
                  <article v-for="event in calendarEvents" :key="`${event.start}-${event.title}`">
                    <div class="journal-calendar-event__title">
                      <span>{{ calendarEventLabel(event) }}</span>
                      <a v-if="event.meet_url" :href="event.meet_url" target="_blank" rel="noopener noreferrer" aria-label="Google Meetを開く"><v-icon size="17">mdi-video-outline</v-icon></a>
                    </div>
                    <div v-if="calendarResponseLabel(event.response_status) || event.meet_participant_count !== null || event.meet_artifacts.length" class="journal-calendar-event__facts">
                      <span v-if="calendarResponseLabel(event.response_status)">{{ calendarResponseLabel(event.response_status) }}</span>
                      <span v-if="event.meet_participant_count !== null">実参加 {{ event.meet_participant_count }}名</span>
                      <template v-for="(artifact, artifactIndex) in event.meet_artifacts" :key="`${artifact.kind}-${artifactIndex}`">
                        <a v-if="artifact.url" :href="artifact.url" target="_blank" rel="noopener noreferrer">{{ meetArtifactLabel(artifact.kind) }}<v-icon size="14">mdi-open-in-new</v-icon></a>
                        <span v-else-if="artifact.state">{{ meetArtifactLabel(artifact.kind) }} {{ artifact.state === 'FILE_GENERATED' ? 'あり' : '作成中' }}</span>
                      </template>
                    </div>
                  </article>
                </div>
                <p v-if="meetError" class="reflection-calendar-message">{{ meetError }}</p>
              </template>
            </section>
            <section v-if="emailLoading || emailError || emailContext.received_count || emailContext.sent_count || emailContext.request_candidates.length" class="journal-email-context">
              <header><span><v-icon size="20">mdi-email-outline</v-icon><b>{{ dateLabel(selectedDate) }}のメール</b></span><em>一時利用のみ、保存しません</em></header>
              <p class="journal-context-description">対象は{{ dateLabel(selectedDate) }}の0:00〜24:00に受信トレイへ届いたメールと、その日に送信したメールだけです。</p>
              <div v-if="emailLoading" class="journal-context-loading"><v-progress-circular indeterminate size="16" width="2"></v-progress-circular>メールを確認しています</div>
              <p v-else-if="emailError" class="reflection-calendar-message">{{ emailError }}</p>
              <template v-else>
                <div class="journal-email-counts">
                  <span>受信 <b>{{ emailContext.received_count }}</b>件</span>
                  <span>送信 <b>{{ emailContext.sent_count }}</b>件</span>
                  <span>未読 <b>{{ emailContext.unread_count }}</b>件</span>
                </div>
                <div v-if="emailCategories.length" class="journal-email-breakdown">
                  <b>メールの内訳<small>{{ emailClassifiedCount }}通を件名と差出人で判定</small></b>
                  <ul>
                    <li v-for="count in emailCategories" :key="mailCategoryKey(count)">
                      <span>{{ count.name }}</span>
                      <em>{{ count.category }}</em>
                      <span class="journal-email-breakdown__count">
                        受信 <b>{{ count.received }}</b> / 送信 <b>{{ count.sent }}</b>
                        <small v-if="count.thread_count">{{ count.thread_count }}案件</small>
                      </span>
                    </li>
                  </ul>
                </div>
                <p v-else-if="!mailRulesConfigured" class="journal-email-empty">メール分類マスターが未登録のため、内訳は集計していません。</p>
                <div v-if="emailContext.request_candidates.length" class="journal-email-requests">
                  <b>依頼候補</b>
                  <a v-for="candidate in emailContext.request_candidates" :key="`${candidate.subject}-${candidate.url}`" :href="candidate.url || undefined" target="_blank" rel="noopener noreferrer">
                    <span><strong>{{ candidate.summary || candidate.subject }}</strong><small>{{ candidate.sender }}・{{ candidate.subject }}</small></span>
                    <v-icon size="17">mdi-open-in-new</v-icon>
                  </a>
                </div>
                <p v-else class="journal-email-empty">依頼に当たりそうなメールは見つかりませんでした。</p>
              </template>
            </section>
            <div v-if="calendarLoading || weatherLoading || weatherLocation || weatherSummary" class="journal-context-status">
              <span v-if="weatherLoading"><v-progress-circular indeterminate size="13" width="2"></v-progress-circular>天気を確認中</span>
              <span v-if="weatherLocation"><v-icon size="15">mdi-map-marker-outline</v-icon>認識位置：{{ weatherLocation }}</span>
              <span v-if="weatherSummary"><v-icon size="15">mdi-weather-partly-cloudy</v-icon>{{ weatherSummary }}</span>
            </div>
          </section>

          <section v-else-if="dialogStep === 'conversation'" class="journal-conversation">
            <header class="journal-conversation-header">
              <div class="journal-ai-presence" :class="`journal-ai-presence--${aiPresence.state}`" role="status" aria-live="polite">
                <span class="journal-ai-orb" aria-hidden="true"></span>
                <span class="journal-ai-presence__text"><b>振り返りパートナー</b><small>{{ aiPresence.label }}</small></span>
                <span v-if="aiPresence.state === 'speaking'" class="journal-ai-wave" aria-hidden="true"><i></i><i></i><i></i><i></i></span>
              </div>
              <v-btn type="button" variant="tonal" color="primary" prepend-icon="mdi-check-circle-outline" :disabled="aiThinking || isVoiceListening || isVoiceTranscribing" @click="finishConversation">作成を終了</v-btn>
            </header>
            <div class="journal-conversation-main">
              <div ref="chatElement" class="journal-chat">
                <article v-for="message in messages" :key="message.id" :class="`journal-chat-message journal-chat-message--${message.role}`"><span>{{ message.role === 'assistant' ? '振り返りパートナー' : participant }}</span><p>{{ displayedMessageText(message) }}<i v-if="message.id === revealingMessageId" class="journal-chat-caret" aria-hidden="true"></i></p></article>
                <div v-if="aiThinking" class="journal-chat-message journal-chat-message--assistant journal-chat-thinking" role="status"><span>振り返りパートナー</span><p><i></i><i></i><i></i><small>今日のことを少し整理しています</small></p></div>
              </div>
              <form
                class="journal-composer"
                :class="{ 'journal-composer--dragging': attachmentDragActive }"
                @submit.prevent="sendResponse"
                @paste="onComposerPaste"
                @dragenter.prevent="attachmentDragActive = true"
                @dragover.prevent="attachmentDragActive = true"
                @dragleave.prevent="attachmentDragActive = false"
                @drop.prevent="onComposerDrop"
              >
              <v-textarea
                v-model="responseText"
                class="journal-response-input"
                label="思い浮かんだことをそのまま話すか、書いてください"
                rows="6"
                auto-grow
                :disabled="aiThinking || isVoiceTranscribing"
              ></v-textarea>
              <div v-if="attachments.length" class="journal-attachments">
                <article v-for="attachment in attachments" :key="attachment.id">
                  <v-icon size="18">{{ attachment.sourceUrl ? 'mdi-google-drive' : attachment.mime_type === 'application/pdf' ? 'mdi-file-pdf-box' : 'mdi-file-image-outline' }}</v-icon>
                  <span><b>{{ attachment.name }}</b><small>{{ formatAttachmentSize(attachment.size) }}{{ attachment.sourceUrl ? '・Google Drive' : '' }}{{ attachmentStatusLabel(attachment) ? `・${attachmentStatusLabel(attachment)}` : '' }}</small></span>
                  <button type="button" aria-label="資料を外す" @click="removeAttachment(attachment.id)"><v-icon size="17">mdi-close</v-icon></button>
                </article>
              </div>
              <div v-if="driveLinkOpen && driveEnabled" class="journal-drive-link">
                <v-text-field v-model="driveLink" label="Google Driveの共有リンク" placeholder="https://drive.google.com/..." hide-details @keydown.enter.prevent="addGoogleDriveFile"></v-text-field>
                <v-btn type="button" variant="tonal" color="primary" :loading="driveLoading" :disabled="!driveLink.trim()" @click="addGoogleDriveFile">読み込む</v-btn>
              </div>
              <p v-if="attachmentError || driveError" class="journal-inline-error">{{ attachmentError || driveError }}</p>
              <p v-if="voiceStatus || voiceError" :class="voiceError ? 'journal-inline-error' : 'journal-voice-status'"><v-icon size="16">{{ voiceError ? 'mdi-alert-circle-outline' : isVoiceListening ? 'mdi-record-circle' : 'mdi-waveform' }}</v-icon>{{ voiceError || voiceStatus }}</p>
              <div class="journal-composer-actions">
                <div>
                  <input ref="attachmentInput" type="file" accept="image/png,image/jpeg,image/webp,application/pdf" multiple hidden @change="onAttachmentInput">
                  <v-btn type="button" size="small" variant="text" prepend-icon="mdi-paperclip" :disabled="aiThinking || attachments.length >= 4" @click="attachmentInput?.click()">資料</v-btn>
                  <template v-if="googleIntegrations.drive">
                    <v-btn type="button" size="small" variant="text" prepend-icon="mdi-google-drive" :disabled="aiThinking || !driveEnabled || attachments.length >= 4" @click="openGoogleDrivePicker">Driveから選択</v-btn>
                    <v-btn type="button" size="small" variant="text" prepend-icon="mdi-link-variant" :disabled="aiThinking || !driveEnabled || attachments.length >= 4" @click="driveLinkOpen = !driveLinkOpen; driveError = ''">リンク</v-btn>
                  </template>
                  <v-btn
                    type="button"
                    size="small"
                    :variant="isVoiceListening ? 'flat' : 'text'"
                    :color="isVoiceListening ? 'error' : undefined"
                    :prepend-icon="isVoiceListening ? 'mdi-stop-circle-outline' : 'mdi-microphone-outline'"
                    :disabled="!voiceInputSupported || aiThinking || isVoiceTranscribing"
                    @click="toggleVoiceInput"
                  >{{ isVoiceListening ? '録音停止' : isVoiceTranscribing ? '文字起こし中' : '音声入力' }}</v-btn>
                  <v-btn v-if="voiceOutputSupported" type="button" size="small" variant="text" :prepend-icon="voicePlaybackEnabled ? 'mdi-volume-high' : 'mdi-volume-off'" @click="toggleVoicePlayback">読み上げ</v-btn>
                </div>
                <span><v-btn type="submit" color="primary" :loading="aiThinking" :disabled="(!responseText.trim() && !attachments.length) || isVoiceListening || isVoiceTranscribing">送る</v-btn></span>
              </div>
                <div v-if="attachmentDragActive" class="journal-drop-overlay"><v-icon size="30">mdi-tray-arrow-down</v-icon>ここへ資料をドロップ</div>
              </form>
            </div>
            <aside class="journal-conversation-context">
              <header>
                <span><v-icon size="19">mdi-lightbulb-on-outline</v-icon><b>振り返りの手がかり</b></span>
                <em>一時利用のみ</em>
              </header>
              <section class="journal-context-block">
                <h3><v-icon size="17">mdi-calendar-blank-outline</v-icon>この日の予定・打ち合わせ</h3>
                <p v-if="calendarLoading">予定を確認しています。</p>
                <p v-else-if="calendarError">{{ calendarError }}</p>
                <div v-else-if="calendarEvents.length" class="journal-context-meetings">
                  <article v-for="event in calendarEvents" :key="`conversation-${event.start}-${event.title}`">
                    <b>{{ calendarEventLabel(event) }}</b>
                    <div v-if="calendarResponseLabel(event.response_status) || event.meet_participant_count !== null">
                      <span v-if="calendarResponseLabel(event.response_status)">{{ calendarResponseLabel(event.response_status) }}</span>
                      <span v-if="event.meet_participant_count !== null">実参加 {{ event.meet_participant_count }}名</span>
                    </div>
                    <a v-for="(artifact, artifactIndex) in event.meet_artifacts.filter((item) => item.url)" :key="`context-artifact-${artifactIndex}`" :href="artifact.url" target="_blank" rel="noopener noreferrer">
                      {{ meetArtifactLabel(artifact.kind) }}を見る<v-icon size="13">mdi-open-in-new</v-icon>
                    </a>
                  </article>
                </div>
                <p v-else>予定はありませんでした。</p>
              </section>
              <section class="journal-context-block">
                <h3><v-icon size="17">mdi-email-outline</v-icon>この日のメール</h3>
                <p v-if="emailLoading">メールを確認しています。</p>
                <p v-else-if="emailError">{{ emailError }}</p>
                <div v-else class="journal-context-mail-counts">
                  <span>受信 <b>{{ emailContext.received_count }}</b></span>
                  <span>送信 <b>{{ emailContext.sent_count }}</b></span>
                  <span>未読 <b>{{ emailContext.unread_count }}</b></span>
                </div>
                <div v-if="!emailLoading && !emailError && emailContext.request_candidates.length" class="journal-context-request-list">
                  <strong>依頼候補の要約</strong>
                  <a v-for="candidate in emailContext.request_candidates" :key="`conversation-${candidate.subject}-${candidate.url}`" :href="candidate.url || undefined" target="_blank" rel="noopener noreferrer">
                    <span>{{ candidate.summary || candidate.subject }}</span>
                    <v-icon v-if="candidate.url" size="14">mdi-open-in-new</v-icon>
                  </a>
                </div>
                <p v-else-if="!emailLoading && !emailError">依頼候補は見つかりませんでした。</p>
              </section>
              <footer><span aria-hidden="true">⚠️</span>メール件数と確認した参加打ち合わせだけ保存します。本文・予定一覧・Meet詳細は保存しません。</footer>
            </aside>
          </section>

          <section v-else-if="draft" class="journal-review">
            <div class="journal-review-note"><v-icon size="20">mdi-check-decagram-outline</v-icon><span><b>この内容を記録として保存します</b><small>会話全文やメール本文、カレンダー予定一覧は保存しません。まとめ・分類情報・メール件数と、下で確認した参加打ち合わせを保存します。</small></span></div>
            <div class="journal-share-note"><v-icon size="20">mdi-account-group-outline</v-icon><span><b>保存した記録は{{ selectedOrgUnit?.name || '所属組織' }}の中で共有されます</b><small>評価のためではなく、互いの動きを把握して声を掛け合うための共有です。ここで確認・編集した内容がそのまま共有されます。</small></span></div>
            <section class="journal-summary-editor">
              <h3>今日のまとめ</h3>
              <v-textarea
                :model-value="draft.summary_items.join('\n')"
                class="journal-summary-input"
                label="1行に1つ、今日の要点"
                rows="7"
                auto-grow
                :hint="labels.itemsHint"
                persistent-hint
                @update:model-value="updateDraftSummaryItems"
              ></v-textarea>
            </section>
            <div class="journal-review-section journal-work-items-review">
              <header class="journal-work-carousel__heading"><h3>{{ labels.todayItems }}</h3><b v-if="draft.work_items.length">{{ reviewWorkIndex + 1 }} / {{ draft.work_items.length }}</b></header>
              <div v-if="draft.work_items.length" class="journal-work-carousel journal-work-carousel--review">
                <div class="journal-work-carousel__stage">
                  <button v-if="draft.work_items.length > 1" type="button" :aria-label="labels.prevItem" @click="moveReviewWork(-1)"><v-icon size="28">mdi-chevron-left</v-icon></button>
                  <article>
                    <v-text-field v-model="draft.work_items[reviewWorkIndex].title" :label="labels.itemField" variant="underlined" hide-details></v-text-field>
                    <v-textarea v-model="draft.work_items[reviewWorkIndex].description" label="内容と、やったこと" rows="5" variant="underlined" auto-grow hide-details></v-textarea>
                    <v-textarea v-model="draft.work_items[reviewWorkIndex].result" label="進み具合" rows="2" variant="underlined" auto-grow hide-details></v-textarea>
                  </article>
                  <button v-if="draft.work_items.length > 1" type="button" :aria-label="labels.nextItem" @click="moveReviewWork(1)"><v-icon size="28">mdi-chevron-right</v-icon></button>
                </div>
                <nav v-if="draft.work_items.length > 1" :aria-label="labels.itemPicker"><button v-for="(_, index) in draft.work_items" :key="index" type="button" :class="{ active: reviewWorkIndex === index }" :aria-label="`${index + 1}件目を表示`" @click="reviewWorkIndex = index"></button></nav>
              </div>
              <p v-else class="journal-work-empty">{{ labels.itemsEmpty }}</p>
            </div>
            <v-textarea v-model="draft.next_focus" label="次に覚えておきたいこと（任意）" rows="2" auto-grow></v-textarea>
            <div v-if="draftAnalysisGroups.length" class="journal-review-section journal-analysis-review">
              <h3>組織で共有する分類</h3>
              <p>月ごとの振り返りと組織のサマリーに使われます。共有したくない項目は消してください。</p>
              <section v-for="group in draftAnalysisGroups" :key="group.key">
                <v-textarea
                  :model-value="group.items.join('\n')"
                  :label="group.label"
                  rows="2"
                  variant="underlined"
                  auto-grow
                  hide-details
                  @update:model-value="(value) => updateDraftAnalysis(group.key, value)"
                ></v-textarea>
              </section>
            </div>
            <div class="journal-review-section journal-activity-review">
              <h3>活動情報として保存</h3>
              <div v-if="!emailError" class="journal-activity-counts">
                <span>受信 <b>{{ emailContext.received_count }}</b>件</span>
                <span>送信 <b>{{ emailContext.sent_count }}</b>件</span>
                <span>未読 <b>{{ emailContext.unread_count }}</b>件</span>
              </div>
              <p v-else>メール件数を取得できなかったため、件数は保存しません。</p>
              <p v-if="!emailError && emailCategories.length" class="journal-activity-note">
                件名から判定した内訳（{{ emailCategories.length }}分類・{{ emailClassifiedCount }}通）も件数だけ保存します。件名と差出人は保存しません。
              </p>
              <p>実際に参加した打ち合わせだけ選んでください。</p>
              <div v-if="calendarEvents.length" class="journal-meeting-confirmation">
                <label v-for="event in calendarEvents" :key="`save-${meetingKey(event)}`">
                  <input v-model="selectedMeetingKeys" type="checkbox" :value="meetingKey(event)">
                  <span><b>{{ calendarEventLabel(event) }}</b><small>{{ selectedMeetingKeys.includes(meetingKey(event)) ? '参加として保存' : '保存しない' }}</small></span>
                </label>
              </div>
              <small>メールの件名・本文、予定の参加者、Meet詳細は保存されません。</small>
            </div>
            <div v-if="draft.references.length" class="journal-review-section journal-review-references">
              <h3>記録に残す関連資料</h3>
              <article v-for="(reference, index) in draft.references" :key="`${reference.name}-${index}`">
                <v-icon size="17">{{ reference.url ? 'mdi-google-drive' : 'mdi-file-outline' }}</v-icon><span><b>{{ reference.name }}</b><small>{{ reference.url || '端末から添付（資料名のみ保存）' }}</small></span>
                <button type="button" aria-label="記録から資料参照を外す" @click="draft.references.splice(index, 1)"><v-icon size="17">mdi-close</v-icon></button>
              </article>
            </div>
          </section>
          <p v-if="turnError" class="journal-error"><v-icon size="17">mdi-alert-circle-outline</v-icon>{{ turnError }}</p>
        </v-card-text>
        <v-card-actions><v-btn variant="text" @click="closeDialog">保存せず閉じる</v-btn><v-spacer></v-spacer><v-btn v-if="dialogStep === 'setup'" color="primary" prepend-icon="mdi-message-processing-outline" @click="beginJournal">振り返りを始める</v-btn><v-btn v-else-if="dialogStep === 'review'" color="primary" prepend-icon="mdi-content-save-outline" :loading="saving" @click="saveDraft">この内容で保存</v-btn></v-card-actions>
      </v-card>
    </v-dialog>
    <v-dialog v-model="drivePickerOpen" max-width="720">
      <v-card class="dialog-card journal-drive-picker">
        <v-card-title>Google Driveから資料を選択</v-card-title>
        <v-card-subtitle>最近更新したPDF・画像・Googleドキュメントなどを表示しています</v-card-subtitle>
        <v-card-text>
          <div class="journal-drive-picker__locations" aria-label="ドライブの選択">
            <button v-for="location in drivePickerLocations" :key="location.id || 'my-drive'" type="button" :class="{ active: drivePickerLocationId === location.id }" @click="selectDrivePickerLocation(location.id)">
              <v-icon size="17">{{ location.id ? 'mdi-google-drive' : 'mdi-folder-home-outline' }}</v-icon>{{ location.name }}
            </button>
          </div>
          <nav v-if="drivePickerBreadcrumbs.length" class="journal-drive-picker__breadcrumbs" aria-label="現在のフォルダ">
            <template v-for="(breadcrumb, index) in drivePickerBreadcrumbs" :key="breadcrumb.id">
              <v-icon v-if="index" size="16">mdi-chevron-right</v-icon>
              <button type="button" :disabled="index === drivePickerBreadcrumbs.length - 1" @click="openDrivePickerBreadcrumb(index)">{{ breadcrumb.name }}</button>
            </template>
          </nav>
          <v-text-field v-model="drivePickerSearch" prepend-inner-icon="mdi-magnify" label="このフォルダ内を絞り込む" clearable hide-details></v-text-field>
          <div v-if="drivePickerLoading" class="journal-drive-picker__loading"><v-progress-circular indeterminate size="24"></v-progress-circular>ファイル一覧を読み込んでいます</div>
          <p v-else-if="driveError" class="journal-error"><v-icon size="17">mdi-alert-circle-outline</v-icon>{{ driveError }}</p>
          <div v-else-if="filteredDrivePickerFiles.length" class="journal-drive-picker__list">
            <button
              v-for="file in filteredDrivePickerFiles"
              :key="file.id"
              type="button"
              :class="{ selected: !isDrivePickerFolder(file) && drivePickerSelectedFile?.id === file.id }"
              :aria-pressed="isDrivePickerFolder(file) ? undefined : drivePickerSelectedFile?.id === file.id"
              :disabled="driveLoading"
              @click="isDrivePickerFolder(file) ? openDrivePickerFolder(file) : drivePickerSelectedFile = file"
            >
              <v-icon size="24">{{ drivePickerFileIcon(file) }}</v-icon>
              <span><b>{{ file.name }}</b><small>{{ isDrivePickerFolder(file) ? 'フォルダ' : driveModifiedLabel(file.modifiedTime) }}</small></span>
              <v-icon size="19">{{ isDrivePickerFolder(file) ? 'mdi-chevron-right' : drivePickerSelectedFile?.id === file.id ? 'mdi-check-circle' : 'mdi-circle-outline' }}</v-icon>
            </button>
          </div>
          <p v-else class="journal-drive-picker__empty">選択できるファイルがありません。</p>
        </v-card-text>
        <v-card-actions class="journal-drive-picker__actions">
          <span v-if="drivePickerSelectedFile"><v-icon size="17">mdi-file-check-outline</v-icon>{{ drivePickerSelectedFile.name }}</span>
          <span v-else>ファイルを1つ選択してください</span>
          <v-spacer></v-spacer>
          <v-btn variant="text" :disabled="driveLoading" @click="drivePickerOpen = false">キャンセル</v-btn>
          <v-btn color="primary" prepend-icon="mdi-check" :loading="driveLoading" :disabled="!drivePickerSelectedFile" @click="confirmGoogleDriveFile">このファイルを選択</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </section>
</template>
