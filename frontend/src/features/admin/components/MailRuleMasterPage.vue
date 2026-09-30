<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  deleteMailRequestTypeRule,
  deleteMailSourceRule,
  getMailClassificationRules,
  saveMailRequestTypeRule,
  saveMailSourceRule,
  type MailCategory,
  type MailRequestTypeRule,
  type MailSourceKind,
  type MailSourceRule,
} from '../../../api/hinami'
import { classifyMailMessages } from '../../journals/mail-classification'
import { useNotifier } from '../../shell/useNotifier'

const props = defineProps<{ canManage: boolean }>()

const { notify } = useNotifier()

const CATEGORIES: MailCategory[] = ['見積', '発注', 'ワークフロー', '調査依頼', '回答依頼', '報告・通知', 'その他']
const SOURCE_KINDS: Array<{ title: string; value: MailSourceKind }> = [
  { title: 'システム通知', value: 'system' },
  { title: '社内の人', value: 'internal' },
  { title: '社外', value: 'external' },
]
const MATCH_TYPES = [
  { title: 'アドレス一致', value: 'address' as const },
  { title: 'ドメイン一致', value: 'domain' as const },
]

type Tab = 'sources' | 'requestTypes'

const tab = ref<Tab>('sources')
const sources = ref<MailSourceRule[]>([])
const requestTypes = ref<MailRequestTypeRule[]>([])
const loading = ref(false)
const saving = ref(false)
const loadError = ref('')
const selectedSourceId = ref('')
const selectedRequestTypeId = ref('')
const keywordText = ref('')
const trialSubject = ref('')
const trialFrom = ref('')

const sourceForm = ref({
  name: '',
  kind: 'system' as MailSourceKind,
  match_type: 'address' as 'address' | 'domain',
  match_value: '',
  default_category: 'ワークフロー' as MailCategory,
  sort_order: 0,
})
const requestTypeForm = ref({
  name: '',
  category: 'ワークフロー' as MailCategory,
  source_ids: [] as string[],
  sort_order: 0,
})

const editingSource = computed(() => Boolean(selectedSourceId.value))
const editingRequestType = computed(() => Boolean(selectedRequestTypeId.value))
const sourceNames = computed(() => new Map(sources.value.map((source) => [source.id, source.name])))

// 入力した件名がどう判定されるかを、保存前にその場で確かめられるようにする。
const trialResult = computed(() => {
  if (!trialSubject.value.trim() && !trialFrom.value.trim()) return null
  const [count] = classifyMailMessages(
    [{ subject: trialSubject.value, from: trialFrom.value, threadId: 'trial', direction: 'received' }],
    sources.value,
    requestTypes.value,
  )
  return count ?? null
})

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const rules = await getMailClassificationRules()
    sources.value = rules.sources
    requestTypes.value = rules.request_types
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : 'メール分類マスターを取得できませんでした。'
  } finally {
    loading.value = false
  }
}

function startAddSource() {
  selectedSourceId.value = ''
  sourceForm.value = {
    name: '',
    kind: 'system',
    match_type: 'address',
    match_value: '',
    default_category: 'ワークフロー',
    sort_order: sources.value.length * 10,
  }
}

function selectSource(source: MailSourceRule) {
  selectedSourceId.value = source.id
  sourceForm.value = {
    name: source.name,
    kind: source.kind,
    match_type: source.match_type,
    match_value: source.match_value,
    default_category: source.default_category,
    sort_order: source.sort_order,
  }
}

function startAddRequestType() {
  selectedRequestTypeId.value = ''
  keywordText.value = ''
  requestTypeForm.value = {
    name: '',
    category: 'ワークフロー',
    source_ids: [],
    sort_order: requestTypes.value.length * 10,
  }
}

function selectRequestType(rule: MailRequestTypeRule) {
  selectedRequestTypeId.value = rule.id
  keywordText.value = rule.keywords.join('\n')
  requestTypeForm.value = {
    name: rule.name,
    category: rule.category,
    source_ids: [...rule.source_ids],
    sort_order: rule.sort_order,
  }
}

async function submitSource() {
  if (!sourceForm.value.name.trim() || !sourceForm.value.match_value.trim()) return
  saving.value = true
  try {
    await saveMailSourceRule({
      id: selectedSourceId.value || undefined,
      ...sourceForm.value,
      name: sourceForm.value.name.trim(),
      match_value: sourceForm.value.match_value.trim(),
    })
    notify(`差出人「${sourceForm.value.name.trim()}」を保存しました`)
    await load()
    if (!selectedSourceId.value) startAddSource()
  } catch (error) {
    notify(error instanceof Error ? error.message : '差出人を保存できませんでした')
  } finally {
    saving.value = false
  }
}

async function submitRequestType() {
  const keywords = keywordText.value.split('\n').map((line) => line.trim()).filter(Boolean)
  if (!requestTypeForm.value.name.trim() || !keywords.length) return
  saving.value = true
  try {
    await saveMailRequestTypeRule({
      id: selectedRequestTypeId.value || undefined,
      ...requestTypeForm.value,
      name: requestTypeForm.value.name.trim(),
      keywords,
    })
    notify(`種別「${requestTypeForm.value.name.trim()}」を保存しました`)
    await load()
    if (!selectedRequestTypeId.value) startAddRequestType()
  } catch (error) {
    notify(error instanceof Error ? error.message : '申請・依頼種別を保存できませんでした')
  } finally {
    saving.value = false
  }
}

async function removeSource(source: MailSourceRule) {
  saving.value = true
  try {
    await deleteMailSourceRule(source.id)
    notify(`差出人「${source.name}」を削除しました`)
    if (selectedSourceId.value === source.id) startAddSource()
    await load()
  } catch (error) {
    notify(error instanceof Error ? error.message : '差出人を削除できませんでした')
  } finally {
    saving.value = false
  }
}

async function removeRequestType(rule: MailRequestTypeRule) {
  saving.value = true
  try {
    await deleteMailRequestTypeRule(rule.id)
    notify(`種別「${rule.name}」を削除しました`)
    if (selectedRequestTypeId.value === rule.id) startAddRequestType()
    await load()
  } catch (error) {
    notify(error instanceof Error ? error.message : '申請・依頼種別を削除できませんでした')
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  await load()
  startAddSource()
  startAddRequestType()
})
</script>

<template>
  <section class="page mail-rule-page">
    <div class="page-heading page-heading--compact">
      <div>
        <div class="eyebrow">MAIL CLASSIFICATION MASTER</div>
        <h1>メール分類マスター</h1>
        <p>
          日々の記録に残すメール件数を、差出人と件名から分類するための設定です。判定はブラウザの中だけで行い、
          保存されるのは分類ごとの件数だけです。件名・差出人・本文はサーバーへ送りません。
        </p>
      </div>
      <div class="heading-actions">
        <span v-if="!props.canManage" class="org-unit-readonly"><v-icon size="16">mdi-lock-outline</v-icon>閲覧のみ</span>
        <v-btn variant="outlined" prepend-icon="mdi-refresh" :loading="loading" @click="load">再読み込み</v-btn>
      </div>
    </div>

    <p v-if="loadError" class="journal-error"><v-icon size="17">mdi-alert-circle-outline</v-icon>{{ loadError }}</p>

    <div class="mail-rule-tabs" role="tablist">
      <button type="button" role="tab" :aria-selected="tab === 'sources'" :class="{ active: tab === 'sources' }" @click="tab = 'sources'">
        差出人（{{ sources.length }}）
      </button>
      <button type="button" role="tab" :aria-selected="tab === 'requestTypes'" :class="{ active: tab === 'requestTypes' }" @click="tab = 'requestTypes'">
        申請・依頼種別（{{ requestTypes.length }}）
      </button>
    </div>

    <div v-if="tab === 'sources'" class="org-unit-page__layout">
      <section class="panel org-unit-tree">
        <div class="panel__header">
          <div>
            <h2>差出人</h2>
            <p>ワークフローシステムなど、通知アドレスが決まっている送信元を登録します。上から順に判定します。</p>
          </div>
          <v-btn v-if="props.canManage" color="primary" variant="tonal" prepend-icon="mdi-plus" @click="startAddSource">追加</v-btn>
        </div>
        <p v-if="!sources.length" class="org-unit-empty">
          まだ登録がありません。ワークフローシステムの通知アドレス（例: noreply@wf.example.co.jp）から登録すると、
          その経路のメールを確実に切り分けられます。
        </p>
        <div v-else class="mail-rule-rows">
          <div v-for="source in sources" :key="source.id" class="mail-rule-row" :class="{ active: selectedSourceId === source.id }">
            <button type="button" class="mail-rule-row__label" @click="selectSource(source)">
              <b>{{ source.name }}</b>
              <em>{{ source.default_category }}</em>
              <small>{{ source.match_type === 'domain' ? '@' : '' }}{{ source.match_value }}</small>
            </button>
            <div v-if="props.canManage" class="org-unit-tree__actions">
              <button type="button" aria-label="削除" @click="removeSource(source)"><v-icon size="17">mdi-trash-can-outline</v-icon></button>
            </div>
          </div>
        </div>
      </section>

      <aside class="panel org-unit-editor">
        <div class="panel__header">
          <div>
            <h2>{{ editingSource ? '差出人を編集' : '差出人を追加' }}</h2>
            <p>アドレス一致が既定です。ドメイン一致は取引先まで巻き込みやすいので、必要なときだけ使います。</p>
          </div>
        </div>
        <v-text-field v-model="sourceForm.name" label="名称" placeholder="購買ワークフロー" density="comfortable" hide-details :disabled="!props.canManage"></v-text-field>
        <v-select v-model="sourceForm.match_type" :items="MATCH_TYPES" label="照合方法" density="comfortable" hide-details :disabled="!props.canManage"></v-select>
        <v-text-field
          v-model="sourceForm.match_value"
          :label="sourceForm.match_type === 'domain' ? 'ドメイン' : 'メールアドレス'"
          :placeholder="sourceForm.match_type === 'domain' ? 'wf.example.co.jp' : 'noreply@wf.example.co.jp'"
          density="comfortable"
          :disabled="!props.canManage"
          hint="小文字に揃えて保存します。ドメインは下位ドメインも一致します。"
          persistent-hint
        ></v-text-field>
        <v-select v-model="sourceForm.kind" :items="SOURCE_KINDS" label="種類" density="comfortable" hide-details :disabled="!props.canManage"></v-select>
        <v-select
          v-model="sourceForm.default_category"
          :items="CATEGORIES"
          label="既定の分類"
          density="comfortable"
          :disabled="!props.canManage"
          hint="件名がどの種別にも当たらなかったときに使う分類です。"
          persistent-hint
        ></v-select>
        <v-text-field
          v-model.number="sourceForm.sort_order"
          type="number"
          min="0"
          label="判定順"
          density="comfortable"
          :disabled="!props.canManage"
          hint="小さいほど先に判定します。"
          persistent-hint
        ></v-text-field>
        <div v-if="props.canManage" class="org-unit-editor__actions">
          <v-btn v-if="editingSource" variant="text" @click="startAddSource">新規追加に切り替える</v-btn>
          <v-spacer></v-spacer>
          <v-btn color="primary" :loading="saving" :disabled="!sourceForm.name.trim() || !sourceForm.match_value.trim()" @click="submitSource">
            {{ editingSource ? '更新' : '追加' }}
          </v-btn>
        </div>
      </aside>
    </div>

    <div v-else class="org-unit-page__layout">
      <section class="panel org-unit-tree">
        <div class="panel__header">
          <div>
            <h2>申請・依頼種別</h2>
            <p>件名に含まれる語句で分類します。上から順に当てるため、細かい種別を上に置きます。</p>
          </div>
          <v-btn v-if="props.canManage" color="primary" variant="tonal" prepend-icon="mdi-plus" @click="startAddRequestType">追加</v-btn>
        </div>
        <p v-if="!requestTypes.length" class="org-unit-empty">まだ登録がありません。追加するまで、メールの内訳は集計されません。</p>
        <div v-else class="mail-rule-rows">
          <div v-for="rule in requestTypes" :key="rule.id" class="mail-rule-row" :class="{ active: selectedRequestTypeId === rule.id }">
            <button type="button" class="mail-rule-row__label" @click="selectRequestType(rule)">
              <b>{{ rule.name }}</b>
              <em>{{ rule.category }}</em>
              <small>{{ rule.keywords.join('、') }}</small>
              <span v-if="rule.source_ids.length" class="org-unit-tree__departments">
                <v-icon size="13">mdi-email-fast-outline</v-icon>
                {{ rule.source_ids.map((id) => sourceNames.get(id) || id).join('、') }}
              </span>
            </button>
            <div v-if="props.canManage" class="org-unit-tree__actions">
              <button type="button" aria-label="削除" @click="removeRequestType(rule)"><v-icon size="17">mdi-trash-can-outline</v-icon></button>
            </div>
          </div>
        </div>
      </section>

      <aside class="panel org-unit-editor">
        <div class="panel__header">
          <div>
            <h2>{{ editingRequestType ? '種別を編集' : '種別を追加' }}</h2>
            <p>判定は語句の部分一致です。大文字小文字・全角半角・「Re:」・申請番号の違いは無視して照合します。</p>
          </div>
        </div>
        <v-text-field v-model="requestTypeForm.name" label="種別名" placeholder="購買申請" density="comfortable" hide-details :disabled="!props.canManage"></v-text-field>
        <v-select v-model="requestTypeForm.category" :items="CATEGORIES" label="分類" density="comfortable" hide-details :disabled="!props.canManage"></v-select>
        <v-textarea
          v-model="keywordText"
          label="件名に含まれる語句"
          placeholder="購買申請&#10;購買依頼"
          rows="4"
          density="comfortable"
          auto-grow
          :disabled="!props.canManage"
          hint="1行に1語。どれか1つでも件名に含まれていれば、この種別として数えます。"
          persistent-hint
        ></v-textarea>
        <v-select
          v-model="requestTypeForm.source_ids"
          :items="sources"
          item-title="name"
          item-value="id"
          label="対象の差出人"
          density="comfortable"
          multiple
          chips
          closable-chips
          :disabled="!props.canManage"
          :no-data-text="'差出人がまだ登録されていません。'"
          hint="指定しなければ全ての差出人が対象です。指定すると、その経路から届いたメールだけを見ます。"
          persistent-hint
        ></v-select>
        <v-text-field
          v-model.number="requestTypeForm.sort_order"
          type="number"
          min="0"
          label="判定順"
          density="comfortable"
          :disabled="!props.canManage"
          hint="小さいほど先に判定します。「承認依頼」のような広い語句より細かい種別は、より小さい値にしてください。"
          persistent-hint
        ></v-text-field>
        <div v-if="props.canManage" class="org-unit-editor__actions">
          <v-btn v-if="editingRequestType" variant="text" @click="startAddRequestType">新規追加に切り替える</v-btn>
          <v-spacer></v-spacer>
          <v-btn color="primary" :loading="saving" :disabled="!requestTypeForm.name.trim() || !keywordText.trim()" @click="submitRequestType">
            {{ editingRequestType ? '更新' : '追加' }}
          </v-btn>
        </div>
      </aside>
    </div>

    <section class="panel mail-rule-trial">
      <div class="panel__header">
        <div>
          <h2>判定を試す</h2>
          <p>実際のメールの件名と差出人を貼り付けて、いまの設定でどう分類されるかを確かめられます。入力内容は保存されません。</p>
        </div>
      </div>
      <div class="mail-rule-trial__inputs">
        <v-text-field v-model="trialSubject" label="件名" placeholder="[ワークフロー] 承認依頼: 購買申請 No.12345" density="comfortable" hide-details></v-text-field>
        <v-text-field v-model="trialFrom" label="差出人" placeholder="購買ワークフロー <noreply@wf.example.co.jp>" density="comfortable" hide-details></v-text-field>
      </div>
      <div v-if="trialResult" class="mail-rule-trial__result">
        <b>{{ trialResult.name }}</b>
        <em>{{ trialResult.category }}</em>
        <small v-if="trialResult.source_name">差出人: {{ trialResult.source_name }}</small>
        <small v-else>差出人の登録には一致しませんでした</small>
      </div>
    </section>
  </section>
</template>
