import type {
  MailRequestTypeRule,
  MailSourceRule,
  WorkJournalEmailCategoryCount,
} from '../../api/hinami'

export interface ClassifiableMessage {
  subject: string
  /** 「表示名 <address>」形式のFromヘッダー。 */
  from: string
  threadId: string
  direction: 'received' | 'sent'
}

export const UNCLASSIFIED_LABEL = '未分類'

const REPLY_PREFIX = /^\s*(?:re|fw|fwd|返信|転送)\s*(?:\[[#\d]+\])?\s*[:：]\s*/i

/**
 * 件名を判定用に均す。全角・大文字・返信の接頭辞・申請番号の違いで
 * 同じ種類のメールが別物として数えられるのを防ぐ。
 */
export function normalizeSubject(subject: string): string {
  let text = subject.normalize('NFKC').toLowerCase()
  while (REPLY_PREFIX.test(text)) text = text.replace(REPLY_PREFIX, '')
  // 申請番号・日付・金額は種別の判定に関係しないため、1つの記号へ寄せる。
  text = text.replace(/\d+/g, '#')
  return text.replace(/\s+/g, ' ').trim()
}

export function mailAddress(from: string): string {
  const angled = from.match(/<([^>]+)>/)?.[1]
  return (angled || from).trim().toLowerCase()
}

export function matchMailSource(from: string, sources: MailSourceRule[]): MailSourceRule | null {
  const address = mailAddress(from)
  if (!address) return null
  const domain = address.split('@')[1] || ''
  for (const source of sources) {
    const value = source.match_value.trim().toLowerCase()
    if (!value) continue
    if (source.match_type === 'domain') {
      if (domain === value || domain.endsWith(`.${value}`)) return source
    } else if (address === value) {
      return source
    }
  }
  return null
}

export function matchMailRequestType(
  subject: string,
  source: MailSourceRule | null,
  requestTypes: MailRequestTypeRule[],
): MailRequestTypeRule | null {
  const normalized = normalizeSubject(subject)
  if (!normalized) return null
  for (const rule of requestTypes) {
    // 差出人を指定した種別は、その経路から届いたメールだけを見る。
    if (rule.source_ids.length && (!source || !rule.source_ids.includes(source.id))) continue
    const hit = rule.keywords.some((keyword) => {
      const needle = normalizeSubject(keyword)
      return needle.length > 0 && normalized.includes(needle)
    })
    if (hit) return rule
  }
  return null
}

interface Bucket extends WorkJournalEmailCategoryCount {
  threads: Set<string>
}

/**
 * 件名と差出人をブラウザ内で分類し、件数へ畳む。
 * 呼び出し側はこの結果だけを保存し、件名・差出人は保存しない。
 */
export function classifyMailMessages(
  messages: ClassifiableMessage[],
  sources: MailSourceRule[],
  requestTypes: MailRequestTypeRule[],
): WorkJournalEmailCategoryCount[] {
  const orderedSources = [...sources].sort((left, right) => left.sort_order - right.sort_order)
  const orderedTypes = [...requestTypes].sort((left, right) => left.sort_order - right.sort_order)
  const buckets = new Map<string, Bucket>()
  for (const message of messages) {
    const source = matchMailSource(message.from, orderedSources)
    const rule = matchMailRequestType(message.subject, source, orderedTypes)
    const bucket: WorkJournalEmailCategoryCount = rule
      ? {
        rule_id: rule.id,
        name: rule.name,
        category: rule.category,
        source_id: source?.id || '',
        source_name: source?.name || '',
        received: 0,
        sent: 0,
        thread_count: 0,
      }
      : source
        ? {
          rule_id: '',
          name: source.name,
          category: source.default_category,
          source_id: source.id,
          source_name: source.name,
          received: 0,
          sent: 0,
          thread_count: 0,
        }
        : {
          rule_id: '',
          name: UNCLASSIFIED_LABEL,
          category: 'その他',
          source_id: '',
          source_name: '',
          received: 0,
          sent: 0,
          thread_count: 0,
        }
    const key = `${bucket.rule_id}|${bucket.name}|${bucket.category}|${bucket.source_id}`
    const current = buckets.get(key) ?? { ...bucket, threads: new Set<string>() }
    if (message.direction === 'sent') current.sent += 1
    else current.received += 1
    // 同じ案件の往復を1件として数え、回覧で件数だけが膨らむ状態を見分ける。
    if (message.threadId) current.threads.add(message.threadId)
    buckets.set(key, current)
  }
  return [...buckets.values()]
    .map(({ threads, ...count }) => ({ ...count, thread_count: threads.size }))
    .sort((left, right) => (right.received + right.sent) - (left.received + left.sent) || left.name.localeCompare(right.name))
}
