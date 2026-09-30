<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  buildWorkJournalWorkMap,
  getWorkJournalDocumentFlows,
  getWorkJournalWorkGraph,
  type WorkGraphHotspot,
  type WorkJournalDocumentFlow,
  type WorkJournalTaskCluster,
} from '../../api/hinami'
import { useAuthSession } from '../admin/useAuthSession'
import { useAppMode } from '../shell/useAppMode'
import { useNotifier } from '../shell/useNotifier'
import { getOrgUnits, type OrgUnitRecord } from '../../api/hinami'

type MiningTab = 'documents' | 'tasks' | 'leverage'

const { currentUser } = useAuthSession()
const { notify } = useNotifier()
const { labels } = useAppMode()

const today = new Date()
const activeTab = ref<MiningTab>('documents')
const selectedOrgUnitId = ref('')
const dateFrom = ref(toDateKey(new Date(today.getFullYear(), today.getMonth() - 1, 1)))
const dateTo = ref(toDateKey(today))
const flows = ref<WorkJournalDocumentFlow[]>([])
const flowsLoading = ref(false)
const flowsError = ref('')
const clusters = ref<WorkJournalTaskCluster[]>([])
const workMapLoading = ref(false)
const workMapError = ref('')
const workMapRequested = ref(false)
const automationTargets = ref<WorkGraphHotspot[]>([])
const keyPersonRisks = ref<WorkGraphHotspot[]>([])
const graphLoading = ref(false)
const graphError = ref('')

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
const relayFlows = computed(() => flows.value.filter((flow) => flow.is_relay))
const singleOwnerClusters = computed(() => clusters.value.filter((cluster) => cluster.single_owner))
const sharedClusters = computed(() => clusters.value.filter((cluster) => !cluster.single_owner))

function toDateKey(date: Date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function shortDate(dateKey: string) {
  const [, month, day] = dateKey.split('-').map(Number)
  return `${month}/${day}`
}

function actionIcon(action: string) {
  if (action === '作成') return 'mdi-file-plus-outline'
  if (action === '更新') return 'mdi-file-edit-outline'
  if (action === '確認') return 'mdi-file-check-outline'
  return 'mdi-file-outline'
}

async function loadDocumentFlows() {
  if (!selectedOrgUnitId.value || flowsLoading.value) return
  flowsLoading.value = true
  flowsError.value = ''
  try {
    const report = await getWorkJournalDocumentFlows(selectedOrgUnitId.value, dateFrom.value, dateTo.value)
    flows.value = report.flows
  } catch (error) {
    flowsError.value = error instanceof Error ? error.message : '資料の流れを取得できませんでした。'
    flows.value = []
  } finally {
    flowsLoading.value = false
  }
}

async function loadWorkGraph() {
  if (!selectedOrgUnitId.value || graphLoading.value) return
  graphLoading.value = true
  graphError.value = ''
  try {
    const graph = await getWorkJournalWorkGraph(selectedOrgUnitId.value, dateFrom.value, dateTo.value)
    automationTargets.value = graph.automation_targets
    keyPersonRisks.value = graph.key_person_risks
  } catch (error) {
    graphError.value = error instanceof Error ? error.message : '業務グラフを取得できませんでした。'
    automationTargets.value = []
    keyPersonRisks.value = []
  } finally {
    graphLoading.value = false
  }
}

async function loadWorkMap() {
  if (!selectedOrgUnitId.value || workMapLoading.value) return
  workMapLoading.value = true
  workMapError.value = ''
  workMapRequested.value = true
  try {
    const result = await buildWorkJournalWorkMap({
      org_unit_id: selectedOrgUnitId.value,
      date_from: dateFrom.value,
      date_to: dateTo.value,
    })
    clusters.value = result.clusters
    await loadWorkGraph()
    notify(`${selectedOrgUnitName.value}の業務を${result.clusters.length}件に整理しました`)
  } catch (error) {
    workMapError.value = error instanceof Error ? error.message : '記録の見取り図を作成できませんでした。'
    clusters.value = []
  } finally {
    workMapLoading.value = false
  }
}

watch([selectedOrgUnitId, dateFrom, dateTo], () => {
  // 期間や組織を変えたら、前の集計結果は表示しない。
  clusters.value = []
  workMapRequested.value = false
  workMapError.value = ''
  automationTargets.value = []
  keyPersonRisks.value = []
  void loadDocumentFlows()
  void loadWorkGraph()
})

onMounted(async () => {
  try {
    orgUnits.value = await getOrgUnits()
  } catch {
    // 組織マスターを取得できない場合は選択肢なしで表示する。
  }
  selectedOrgUnitId.value = currentUser.value?.org_unit_id || orgUnitOptions.value[0]?.id || ''
  if (selectedOrgUnitId.value) {
    void loadDocumentFlows()
    void loadWorkGraph()
  }
})
</script>

<template>
  <section class="page work-mining-page">
    <div class="page-heading page-heading--compact">
      <div>
        <div class="eyebrow">WORK MINING</div>
        <h1>記録の見取り図</h1>
        <p>{{ labels.mining.lead }}</p>
      </div>
    </div>

    <div class="panel mining-controls">
      <v-select v-model="selectedOrgUnitId" :items="orgUnitOptions" item-title="label" item-value="id" label="組織" hide-details density="comfortable"></v-select>
      <v-text-field v-model="dateFrom" type="date" label="開始日" hide-details density="comfortable"></v-text-field>
      <v-text-field v-model="dateTo" type="date" label="終了日" hide-details density="comfortable"></v-text-field>
      <v-btn variant="tonal" color="primary" prepend-icon="mdi-refresh" :loading="flowsLoading" :disabled="!selectedOrgUnitId" @click="loadDocumentFlows">読み込む</v-btn>
    </div>

    <div class="mining-tabs">
      <button type="button" :class="{ active: activeTab === 'documents' }" @click="activeTab = 'documents'">
        <v-icon size="18">mdi-file-move-outline</v-icon>{{ labels.mining.tabDocuments }}<b v-if="relayFlows.length">{{ relayFlows.length }}</b>
      </button>
      <button type="button" :class="{ active: activeTab === 'tasks' }" @click="activeTab = 'tasks'">
        <v-icon size="18">mdi-account-supervisor-outline</v-icon>{{ labels.mining.tabTasks }}<b v-if="singleOwnerClusters.length">{{ singleOwnerClusters.length }}</b>
      </button>
      <button type="button" :class="{ active: activeTab === 'leverage' }" @click="activeTab = 'leverage'">
        <v-icon size="18">mdi-target</v-icon>{{ labels.mining.tabLeverage }}<b v-if="automationTargets.length">{{ automationTargets.length }}</b>
      </button>
    </div>

    <section v-if="activeTab === 'documents'" class="panel mining-panel">
      <div class="panel__header">
        <div>
          <h2>{{ labels.mining.documentsTitle }}</h2>
          <p>{{ labels.mining.documentsLead }}</p>
        </div>
      </div>
      <p v-if="flowsError" class="journal-error"><v-icon size="17">mdi-alert-circle-outline</v-icon>{{ flowsError }}</p>
      <div v-else-if="flowsLoading" class="mining-loading"><v-progress-circular indeterminate size="22" width="2"></v-progress-circular>記録を読み込んでいます</div>
      <template v-else-if="relayFlows.length">
        <article v-for="flow in relayFlows" :key="flow.document_key" class="mining-flow">
          <header>
            <div>
              <b>{{ flow.document_title || flow.name }}</b>
              <small v-if="flow.related_business">{{ flow.related_business }}</small>
            </div>
            <span class="mining-flow__badge"><v-icon size="14">mdi-swap-horizontal</v-icon>{{ labels.mining.handoff }}{{ flow.handoff_count }}回・{{ flow.participants.length }}名</span>
          </header>
          <ol class="mining-flow__chain">
            <li v-for="(touch, index) in flow.touches" :key="`${flow.document_key}-${index}`">
              <v-icon size="15">{{ actionIcon(touch.action) }}</v-icon>
              <b>{{ touch.participant }}</b>
              <span>{{ touch.action }}</span>
              <small>{{ shortDate(touch.journal_date) }}</small>
            </li>
          </ol>
          <a v-if="flow.url" :href="flow.url" target="_blank" rel="noopener noreferrer"><v-icon size="15">mdi-google-drive</v-icon>元の資料を開く</a>
        </article>
      </template>
      <p v-else class="mining-empty">この期間に、複数人で回している資料は見つかりませんでした。</p>
    </section>

    <section v-else-if="activeTab === 'tasks'" class="panel mining-panel">
      <div class="panel__header">
        <div>
          <h2>{{ labels.mining.tasksTitle }}</h2>
          <p>{{ labels.mining.tasksLead }}</p>
        </div>
        <v-btn color="primary" prepend-icon="mdi-auto-fix" :loading="workMapLoading" :disabled="!selectedOrgUnitId" @click="loadWorkMap">{{ labels.mining.tasksButton }}</v-btn>
      </div>
      <p v-if="workMapError" class="journal-error"><v-icon size="17">mdi-alert-circle-outline</v-icon>{{ workMapError }}</p>
      <div v-else-if="workMapLoading" class="mining-loading"><v-progress-circular indeterminate size="22" width="2"></v-progress-circular>{{ labels.mining.tasksLoading }}</div>
      <template v-else-if="clusters.length">
        <h3 v-if="singleOwnerClusters.length" class="mining-group-heading"><v-icon size="17">mdi-account-alert-outline</v-icon>{{ labels.mining.singleHeading }}</h3>
        <article v-for="cluster in singleOwnerClusters" :key="cluster.task_name" class="mining-task mining-task--single">
          <header><b>{{ cluster.task_name }}</b><span>{{ cluster.participants[0] }}のみ・{{ cluster.occurrence_count }}回</span></header>
          <p v-if="cluster.summary">{{ cluster.summary }}</p>
          <small>{{ cluster.journal_dates.map(shortDate).join('、') }}</small>
        </article>
        <h3 v-if="sharedClusters.length" class="mining-group-heading"><v-icon size="17">mdi-account-group-outline</v-icon>{{ labels.mining.sharedHeading }}</h3>
        <article v-for="cluster in sharedClusters" :key="cluster.task_name" class="mining-task">
          <header><b>{{ cluster.task_name }}</b><span>{{ cluster.participants.join('、') }}・{{ cluster.occurrence_count }}回</span></header>
          <p v-if="cluster.summary">{{ cluster.summary }}</p>
        </article>
      </template>
      <p v-else-if="workMapRequested" class="mining-empty">{{ labels.mining.tasksEmpty }}</p>
      <p v-else class="mining-empty">{{ labels.mining.tasksPrompt }}</p>
    </section>

    <section v-else class="panel mining-panel">
      <div class="panel__header">
        <div>
          <h2>{{ labels.mining.leverageTitle }}</h2>
          <p>{{ labels.mining.leverageLead }}</p>
        </div>
      </div>
      <p v-if="graphError" class="journal-error"><v-icon size="17">mdi-alert-circle-outline</v-icon>{{ graphError }}</p>
      <div v-else-if="graphLoading" class="mining-loading"><v-progress-circular indeterminate size="22" width="2"></v-progress-circular>{{ labels.mining.leverageLoading }}</div>
      <template v-else-if="automationTargets.length || keyPersonRisks.length">
        <h3 v-if="automationTargets.length" class="mining-group-heading"><v-icon size="17">mdi-robot-outline</v-icon>{{ labels.mining.automationHeading }}</h3>
        <article v-for="target in automationTargets" :key="target.node_id" class="mining-task">
          <header><b>{{ target.label }}</b><span>{{ target.owners.join('、') || '担当未確認' }}</span></header>
          <p>{{ target.reason }}</p>
          <div class="mining-metrics">
            <span>繰り返し <b>{{ target.occurrence_count }}</b>回</span>
            <span>受け渡し <b>{{ target.handoff_count }}</b>回</span>
            <span>資料 <b>{{ target.document_count }}</b>件</span>
            <span>関与 <b>{{ target.downstream_people.length }}</b>名</span>
          </div>
        </article>
        <h3 v-if="keyPersonRisks.length" class="mining-group-heading"><v-icon size="17">mdi-alert-outline</v-icon>{{ labels.mining.riskHeading }}</h3>
        <article v-for="risk in keyPersonRisks" :key="`risk-${risk.node_id}`" class="mining-task mining-task--single">
          <header><b>{{ risk.label }}</b><span>{{ risk.owners.join('、') }}のみ</span></header>
          <p>{{ risk.reason }}</p>
          <div v-if="risk.downstream_people.length" class="mining-metrics">
            <span>後工程 <b>{{ risk.downstream_people.join('、') }}</b></span>
          </div>
        </article>
      </template>
      <p v-else class="mining-empty">{{ labels.mining.leverageEmpty }}</p>
    </section>
  </section>
</template>
