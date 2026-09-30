<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  checkAiModel,
  getAiModels,
  saveAiModels,
  type AiModelSettings,
  type AiModelSettingsResponse,
  type AiRole,
  type ConnectionCheckResult,
} from '../../../api/hinami'
import { useNotifier } from '../../shell/useNotifier'
import ConnectionCheckNotice from './ConnectionCheckNotice.vue'

const CONNECTION_LABELS = { 'gemini-api': '① Gemini API キー', vertex: '② Vertex AI' } as const
const CONNECTION_SHORT = { 'gemini-api': '①', vertex: '②' } as const
const ENGINE_LABELS = { 'gemini-tts': 'Gemini TTS（①）', 'cloud-tts': 'Cloud Text-to-Speech（②）' } as const
const ROLE_LABELS: Record<AiRole, string> = { chat: '対話・記録の作成', transcription: '文字起こし', speech: '読み上げ' }

const { notify } = useNotifier()

const EMPTY: AiModelSettings = {
  chat_connection: '', chat_model: '', transcription_connection: '', transcription_model: '', speech_engine: '', speech_model: '',
}
const saved = ref<AiModelSettingsResponse | null>(null)
const form = ref<AiModelSettings>({ ...EMPTY })
const loading = ref(false)
const saving = ref(false)
const checking = ref<AiRole | null>(null)
const error = ref('')
const checks = ref<Partial<Record<AiRole, ConnectionCheckResult>>>({})

const environment = computed(() => saved.value?.environment)
const changed = computed(() => !saved.value || (Object.keys(form.value) as (keyof AiModelSettings)[])
  .some((key) => form.value[key] !== saved.value?.[key]))

function connectionItems(fallback: string) {
  return [
    { title: `環境の設定（${fallback}）`, value: '' },
    { title: CONNECTION_LABELS['gemini-api'], value: 'gemini-api' },
    { title: CONNECTION_LABELS.vertex, value: 'vertex' },
  ]
}
const chatConnectionItems = computed(() => connectionItems(CONNECTION_SHORT[environment.value?.chat_connection ?? 'gemini-api']))
// 文字起こしは、決めていなければ対話と同じ接続を使う。
const transcriptionConnectionItems = computed(() => {
  const chat = form.value.chat_connection || environment.value?.chat_connection || 'gemini-api'
  return connectionItems(`対話と同じ ${CONNECTION_SHORT[chat]}`)
})
const engineItems = computed(() => [
  { title: `環境の設定（${ENGINE_LABELS[environment.value?.speech_engine ?? 'gemini-tts']}）`, value: '' },
  { title: ENGINE_LABELS['gemini-tts'], value: 'gemini-tts' },
  { title: ENGINE_LABELS['cloud-tts'], value: 'cloud-tts' },
])
const chatModelPlaceholder = computed(() => environment.value?.chat_model ?? '')
const transcriptionModelPlaceholder = computed(() => form.value.chat_model || environment.value?.transcription_model || '')
// 読み上げのモデルは方式ごとに別物。保存済みの方式と違う方式を選んでいる間は、既定のモデル名を出さない。
const speechModelPlaceholder = computed(() => {
  const engine = form.value.speech_engine || environment.value?.speech_engine
  return engine === saved.value?.effective.speech_engine ? saved.value?.effective.speech_model ?? '' : '方式の既定のモデル'
})

function onEngineChange() {
  // 方式が変わると、同じモデル名は使えない。入力済みのモデル名は外す。
  form.value.speech_model = ''
}

function apply(response: AiModelSettingsResponse) {
  saved.value = response
  const { environment: _environment, effective: _effective, ...settings } = response
  form.value = { ...settings }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    apply(await getAiModels())
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'AIモデルの設定を取得できませんでした。'
  } finally {
    loading.value = false
  }
}

async function save(): Promise<boolean> {
  saving.value = true
  error.value = ''
  checks.value = {}
  try {
    apply(await saveAiModels(form.value))
    notify('AIモデルの設定を保存しました。')
    return true
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'AIモデルの設定を保存できませんでした。'
    return false
  } finally {
    saving.value = false
  }
}

async function check(role: AiRole) {
  if (changed.value && !await save()) return
  checking.value = role
  try {
    checks.value = { ...checks.value, [role]: await checkAiModel(role) }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '接続を確認できませんでした。'
  } finally {
    checking.value = null
  }
}

function serviceName(role: AiRole) {
  const effective = saved.value?.effective
  if (role === 'speech') return effective?.speech_engine === 'cloud-tts' ? 'Cloud Text-to-Speech' : 'Gemini API'
  return effective?.[`${role}_connection`] === 'vertex' ? 'Vertex AI' : 'Gemini API'
}

onMounted(load)
</script>

<template>
  <section class="panel backup-panel settings-panel">
    <div class="settings-panel__heading">
      <div>
        <h2>役割ごとの接続方法とモデル</h2>
        <p>役割ごとに、使う接続方法とモデルを選びます。空欄の項目は環境の設定に従います。業務名の名寄せは対話と同じ接続方法を使います。</p>
      </div>
      <v-btn variant="text" size="small" prepend-icon="mdi-refresh" :loading="loading" @click="load">更新</v-btn>
    </div>

    <p v-if="error" class="backup-error"><v-icon size="18">mdi-alert-circle-outline</v-icon>{{ error }}</p>

    <div class="ai-models">
      <section class="ai-models__role">
        <h3>{{ ROLE_LABELS.chat }}</h3>
        <div class="settings-grid">
          <v-select v-model="form.chat_connection" :items="chatConnectionItems" label="接続方法" :disabled="loading" hide-details></v-select>
          <v-text-field v-model="form.chat_model" label="モデル" :placeholder="chatModelPlaceholder" persistent-placeholder hide-details></v-text-field>
        </div>
        <div class="ai-models__check">
          <v-btn variant="text" size="small" prepend-icon="mdi-lan-connect" :loading="checking === 'chat'" :disabled="loading || saving || Boolean(checking)" @click="check('chat')">接続を確認</v-btn>
        </div>
        <ConnectionCheckNotice v-if="checks.chat" :result="checks.chat" :service="serviceName('chat')" />
      </section>

      <section class="ai-models__role">
        <h3>{{ ROLE_LABELS.transcription }}</h3>
        <div class="settings-grid">
          <v-select v-model="form.transcription_connection" :items="transcriptionConnectionItems" label="接続方法" :disabled="loading" hide-details></v-select>
          <v-text-field v-model="form.transcription_model" label="モデル" :placeholder="transcriptionModelPlaceholder" persistent-placeholder hide-details></v-text-field>
        </div>
        <p class="settings-note">空欄なら対話と同じ接続方法・モデルを使います。専用のモデル（例: gemini-3.5-transcribe）も指定できます。</p>
        <div class="ai-models__check">
          <v-btn variant="text" size="small" prepend-icon="mdi-lan-connect" :loading="checking === 'transcription'" :disabled="loading || saving || Boolean(checking)" @click="check('transcription')">接続を確認</v-btn>
        </div>
        <ConnectionCheckNotice v-if="checks.transcription" :result="checks.transcription" :service="serviceName('transcription')" />
      </section>

      <section class="ai-models__role">
        <h3>{{ ROLE_LABELS.speech }}</h3>
        <div class="settings-grid">
          <v-select v-model="form.speech_engine" :items="engineItems" label="方式（接続方法はこれで決まります）" :disabled="loading" hide-details @update:model-value="onEngineChange"></v-select>
          <v-text-field v-model="form.speech_model" label="モデル" :placeholder="speechModelPlaceholder" persistent-placeholder hide-details></v-text-field>
        </div>
        <p class="settings-note">Gemini TTS は ① Gemini API キー、Cloud Text-to-Speech は ② Google Cloud の接続を使います。声・トーン・ペースは各利用者が選べます。</p>
        <div class="ai-models__check">
          <v-btn variant="text" size="small" prepend-icon="mdi-lan-connect" :loading="checking === 'speech'" :disabled="loading || saving || Boolean(checking)" @click="check('speech')">接続を確認</v-btn>
        </div>
        <ConnectionCheckNotice v-if="checks.speech" :result="checks.speech" :service="serviceName('speech')" />
      </section>
    </div>

    <div class="settings-actions">
      <p>保存した直後から、AI機能の呼び出しがこの設定になります。接続の確認ではモデルの情報を引くだけで、生成や音声合成はしません。</p>
      <div>
        <v-btn color="primary" prepend-icon="mdi-check" :loading="saving" :disabled="!changed || loading" @click="save">保存</v-btn>
      </div>
    </div>
  </section>
</template>

<style scoped>
.ai-models { display:grid; gap:0; border-top:1px solid var(--border-subtle); }
.ai-models__role { display:grid; gap:10px; padding:14px 0; border-bottom:1px solid var(--border-subtle); }
.ai-models__role h3 { margin:0; color:var(--ink-3); font-size:14px; }
.ai-models__check { display:flex; justify-content:flex-end; }
.ai-models__check .v-btn { text-transform:none; }
</style>
