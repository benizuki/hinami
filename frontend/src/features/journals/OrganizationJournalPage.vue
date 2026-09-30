<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  getOrganizationJournalActivity,
  summarizeOrganizationJournals,
  type WorkJournalDigestItem,
  type WorkJournalEmailCategoryCount,
  type WorkJournalMemberActivity,
  type WorkJournalOrganizationDigest,
} from '../../api/hinami'
import { useAuthSession } from '../admin/useAuthSession'
import { useAppMode } from '../shell/useAppMode'
import { useNotifier } from '../shell/useNotifier'
import { getOrgUnits, type OrgUnitRecord } from '../../api/hinami'

type DigestGroupKey = 'progress' | 'ingenuity' | 'unplanned_work' | 'support_needed'

const { currentUser } = useAuthSession()
const { notify } = useNotifier()
const { labels } = useAppMode()

// 評価ではなく声を掛け合うための共有なので、支援の欄まで同じ扱いで並べる。
const DIGEST_GROUPS: Array<{ key: DigestGroupKey; icon: string }> = [
  { key: 'progress', icon: 'mdi-progress-check' },
  { key: 'ingenuity', icon: 'mdi-lightbulb-on-outline' },
  { key: 'unplanned_work', icon: 'mdi-flash-alert-outline' },
  { key: 'support_needed', icon: 'mdi-hand-heart-outline' },
]

const today = new Date()
const selectedOrgUnitId = ref('')
const dateFrom = ref(toDateKey(new Date(today.getFullYear(), today.getMonth(), today.getDate() - 6)))
const dateTo = ref(toDateKey(today))
const members = ref<WorkJournalMemberActivity[]>([])
const journalCount = ref(0)
const mailCategories = ref<WorkJournalEmailCategoryCount[]>([])
const mailClassifiedJournalCount = ref(0)
const activityLoading = ref(false)
const activityError = ref('')
const digest = ref<WorkJournalOrganizationDigest | null>(null)
const digestLoading = ref(false)
const digestError = ref('')
const expandedMember = ref('')

const orgUnits = ref<OrgUnitRecord[]>([])
// 階層が読み取れるよう、親からの深さでインデントした選択肢にする。
const orgUnitOptions = computed(() => {
  const byParent = new Map<string, OrgUnitRecord[]>()
  for (const unit of orgUnits.value) {
    byParent.set(unit.parent_id, [...(byParent.get(unit.parent_id) || []), unit])
  }
  const options: Array<{ id: string; name: string; label: string }> = []
  const walk = (parentId: string, depth: number) => {
    for (const unit of byParent.get(parentId) || []) {
      options.push({ id: unit.id, name: unit.name, label: `${'　'.repeat(depth)}${unit.name}` })
      walk(unit.id, depth + 1)
    }
  }
  walk('', 0)
  return options
})
const selectedOrgUnitName = computed(() => orgUnitOptions.value.find((option) => option.id === selectedOrgUnitId.value)?.name || '')
const digestGroups = computed(() => {
  const current = digest.value
  if (!current) return []
  return DIGEST_GROUPS
    .map((group) => ({ ...group, ...labels.value.team.digestGroups[group.key], items: current[group.key] as WorkJournalDigestItem[] }))
    .filter((group) => group.items.length)
})

function toDateKey(date: Date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function shortDate(dateKey: string) {
  if (!dateKey) return ''
  const [, month, day] = dateKey.split('-').map(Number)
  return `${month}/${day}`
}

// 列は組織で件数の多い分類から並べる。人ごとに列が入れ替わると比べられない。
const mailColumns = computed(() => mailCategories.value.slice(0, 6))
const mailTotal = computed(() => mailCategories.value.reduce((sum, count) => sum + count.received + count.sent, 0))
const mailMembers = computed(() => members.value.filter((member) => member.email_categories.length))

function mailCategoryKey(count: WorkJournalEmailCategoryCount) {
  return `${count.rule_id}-${count.source_id}-${count.name}`
}

function mailCategoryTotal(count: WorkJournalEmailCategoryCount) {
  return count.received + count.sent
}

function mailShare(count: WorkJournalEmailCategoryCount) {
  if (!mailTotal.value) return 0
  return Math.round((mailCategoryTotal(count) / mailTotal.value) * 100)
}

function memberMailCount(member: WorkJournalMemberActivity, name: string) {
  return member.email_categories
    .filter((count) => count.name === name)
    .reduce((sum, count) => sum + count.received + count.sent, 0)
}

function memberMailTotal(member: WorkJournalMemberActivity) {
  return member.email_categories.reduce((sum, count) => sum + count.received + count.sent, 0)
}

/** 日報を書いた日数が人ごとに違うため、合計だけを並べると記入量の差が業務量の差に見える。 */
function memberMailPerDay(member: WorkJournalMemberActivity) {
  if (!member.email_classified_journal_count) return '—'
  return (memberMailTotal(member) / member.email_classified_journal_count).toFixed(1)
}

function memberEntryCount(member: WorkJournalMemberActivity) {
  return member.progressed_items.length + member.ingenuity.length
    + member.unplanned_work.length + member.support_needed.length
}

function setPeriodDays(days: number) {
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate() - (days - 1))
  dateFrom.value = toDateKey(start)
  dateTo.value = toDateKey(today)
}

async function loadActivity() {
  if (!selectedOrgUnitId.value || activityLoading.value) return
  activityLoading.value = true
  activityError.value = ''
  try {
    const activity = await getOrganizationJournalActivity(selectedOrgUnitId.value, dateFrom.value, dateTo.value)
    members.value = activity.members
    journalCount.value = activity.journal_count
    mailCategories.value = activity.email_categories
    mailClassifiedJournalCount.value = activity.email_classified_journal_count
  } catch (error) {
    activityError.value = error instanceof Error ? error.message : 'チームの記録を取得できませんでした。'
    members.value = []
    journalCount.value = 0
    mailCategories.value = []
    mailClassifiedJournalCount.value = 0
  } finally {
    activityLoading.value = false
  }
}

async function createDigest() {
  if (!selectedOrgUnitId.value || digestLoading.value) return
  digestLoading.value = true
  digestError.value = ''
  try {
    digest.value = await summarizeOrganizationJournals({
      org_unit_id: selectedOrgUnitId.value,
      date_from: dateFrom.value,
      date_to: dateTo.value,
    })
    notify(`${selectedOrgUnitName.value}のサマリーを作成しました`)
  } catch (error) {
    digestError.value = error instanceof Error ? error.message : 'サマリーを作成できませんでした。'
    digest.value = null
  } finally {
    digestLoading.value = false
  }
}

watch([selectedOrgUnitId, dateFrom, dateTo], () => {
  // 期間や組織を変えたら、前のサマリーは表示しない。
  digest.value = null
  digestError.value = ''
  expandedMember.value = ''
  void loadActivity()
})

onMounted(async () => {
  try {
    orgUnits.value = await getOrgUnits()
  } catch {
    // 組織マスターを取得できない場合は選択肢なしで表示する。
  }
  selectedOrgUnitId.value = currentUser.value?.org_unit_id || orgUnitOptions.value[0]?.id || ''
  if (selectedOrgUnitId.value) void loadActivity()
})
</script>

<template>
  <section class="page organization-journal-page">
    <div class="page-heading page-heading--compact">
      <div>
        <div class="eyebrow">TEAM JOURNAL</div>
        <h1>チームの記録</h1>
      </div>
    </div>

    <div class="panel mining-controls">
      <v-select v-model="selectedOrgUnitId" :items="orgUnitOptions" item-title="label" item-value="id" label="組織" hide-details density="comfortable"></v-select>
      <v-text-field v-model="dateFrom" type="date" label="開始日" hide-details density="comfortable"></v-text-field>
      <v-text-field v-model="dateTo" type="date" label="終了日" hide-details density="comfortable"></v-text-field>
      <div class="organization-period-presets">
        <button type="button" @click="setPeriodDays(7)">1週間</button>
        <button type="button" @click="setPeriodDays(30)">1か月</button>
      </div>
    </div>

    <p v-if="activityError" class="journal-error"><v-icon size="17">mdi-alert-circle-outline</v-icon>{{ activityError }}</p>

    <section class="panel mining-panel">
      <div class="panel__header">
        <div>
          <h2>この期間のサマリー</h2>
          <p v-if="activityLoading">記録を読み込んでいます</p>
          <p v-else>{{ members.length }}名が{{ journalCount }}件の記録を保存しています。</p>
        </div>
        <v-btn color="primary" prepend-icon="mdi-auto-fix" :loading="digestLoading" :disabled="!members.length" @click="createDigest">サマリーを作成</v-btn>
      </div>
      <p v-if="digestError" class="journal-error"><v-icon size="17">mdi-alert-circle-outline</v-icon>{{ digestError }}</p>
      <div v-else-if="digestLoading" class="mining-loading"><v-progress-circular indeterminate size="22" width="2"></v-progress-circular>{{ labels.team.digestLoading }}</div>
      <template v-else-if="digest">
        <p v-if="digest.overview" class="organization-overview">{{ digest.overview }}</p>
        <div class="organization-digest-groups">
          <article v-for="group in digestGroups" :key="group.key">
            <h3><v-icon size="17">{{ group.icon }}</v-icon>{{ group.label }}</h3>
            <small>{{ group.hint }}</small>
            <ul>
              <li v-for="(item, index) in group.items" :key="`${group.key}-${index}`">
                <span>{{ item.summary }}</span>
                <em v-if="item.members.length">{{ item.members.join('、') }}</em>
              </li>
            </ul>
          </article>
        </div>
        <div v-if="digest.collaboration_hints.length" class="organization-hints">
          <h3><v-icon size="17">mdi-account-multiple-check-outline</v-icon>{{ labels.team.hintsTitle }}</h3>
          <ul><li v-for="hint in digest.collaboration_hints" :key="hint">{{ hint }}</li></ul>
        </div>
      </template>
      <p v-else-if="members.length" class="mining-empty">「サマリーを作成」を押すと、この期間の記録をまとめます。</p>
      <p v-else-if="!activityLoading" class="mining-empty">この期間に保存された記録はまだありません。</p>
    </section>

    <section v-if="mailCategories.length" class="panel mining-panel organization-mail">
      <div class="panel__header">
        <div>
          <h2>メールの傾向</h2>
          <p>
            分類を保存した記録{{ mailClassifiedJournalCount }}件から集計しています。{{ labels.team.mailNote }}
          </p>
        </div>
      </div>
      <ul class="organization-mail-bars">
        <li v-for="count in mailCategories" :key="mailCategoryKey(count)">
          <span class="organization-mail-bars__name">{{ count.name }}</span>
          <em>{{ count.category }}</em>
          <span class="organization-mail-bars__track"><i :style="{ width: `${mailShare(count)}%` }"></i></span>
          <b>{{ mailCategoryTotal(count) }}件</b>
          <small v-if="count.thread_count">{{ count.thread_count }}案件</small>
        </li>
      </ul>
      <div v-if="mailMembers.length" class="organization-mail-table">
        <table>
          <thead>
            <tr>
              <th>メンバー</th>
              <th v-for="column in mailColumns" :key="`head-${mailCategoryKey(column)}`">{{ column.name }}</th>
              <th>合計</th>
              <th>1日あたり</th>
              <th>対象日数</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="member in mailMembers" :key="`mail-${member.participant}`">
              <th scope="row">{{ member.participant }}</th>
              <td v-for="column in mailColumns" :key="`${member.participant}-${mailCategoryKey(column)}`">
                {{ memberMailCount(member, column.name) || '—' }}
              </td>
              <td><b>{{ memberMailTotal(member) }}</b></td>
              <td>{{ memberMailPerDay(member) }}</td>
              <td>{{ member.email_classified_journal_count }}日</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section v-if="members.length" class="panel mining-panel organization-members">
      <div class="panel__header">
        <div>
          <h2>メンバー別の内訳</h2>
          <p>名前を押すと、その人が保存した内容を確認できます。</p>
        </div>
      </div>
      <article v-for="member in members" :key="member.participant">
        <button type="button" :aria-expanded="expandedMember === member.participant" @click="expandedMember = expandedMember === member.participant ? '' : member.participant">
          <v-icon size="18">{{ expandedMember === member.participant ? 'mdi-chevron-down' : 'mdi-chevron-right' }}</v-icon>
          <b>{{ member.participant }}</b>
          <span>{{ labels.memberCount(member.journal_count, memberEntryCount(member)) }}</span>
          <small v-if="member.latest_journal_date">最終 {{ shortDate(member.latest_journal_date) }}</small>
        </button>
        <div v-if="expandedMember === member.participant" class="organization-member-detail">
          <section v-for="group in DIGEST_GROUPS" :key="`${member.participant}-${group.key}`">
            <template v-if="group.key === 'progress' ? member.progressed_items.length : member[group.key].length">
              <h4><v-icon size="15">{{ group.icon }}</v-icon>{{ labels.team.digestGroups[group.key].label }}</h4>
              <ul>
                <li v-for="text in (group.key === 'progress' ? member.progressed_items : member[group.key])" :key="text">{{ text }}</li>
              </ul>
            </template>
          </section>
        </div>
      </article>
    </section>
  </section>
</template>
