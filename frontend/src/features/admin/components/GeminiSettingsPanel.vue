<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  deleteGeminiApiKey,
  getGeminiSettings,
  saveGeminiApiKey,
  type GeminiSettings,
} from '../../../api/hinami'
import { useNotifier } from '../../shell/useNotifier'

const { notify } = useNotifier()

const settings = ref<GeminiSettings | null>(null)
const apiKey = ref('')
const showKey = ref(false)
const loading = ref(false)
const saving = ref(false)
const removing = ref(false)
const error = ref('')

// 環境変数のキーが優先されるため、そのあいだ画面からは変更できない。
const lockedByEnvironment = computed(() => settings.value?.source === 'environment')
const status = computed(() => {
  switch (settings.value?.source) {
    case 'environment':
      return { icon: 'mdi-server-security', title: '環境変数で設定済み', text: 'GEMINI_API_KEY のキーを使っています。画面からは変更できません。' }
    case 'stored':
      return { icon: 'mdi-key-variant', title: `画面から登録したキー（末尾 ${settings.value.key_hint ?? '****'}）`, text: 'AI機能はこのキーで動いています。' }
    case 'none':
      return { icon: 'mdi-key-remove', title: 'APIキーが未設定です', text: '対話・記録の作成・読み上げなどのAI機能を使えません。' }
    default:
      return null
  }
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    settings.value = await getGeminiSettings()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'AI設定を取得できませんでした。'
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!apiKey.value.trim()) return
  saving.value = true
  error.value = ''
  try {
    settings.value = await saveGeminiApiKey(apiKey.value.trim())
    apiKey.value = ''
    showKey.value = false
    notify('APIキーを確認して保存しました。')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'APIキーを保存できませんでした。'
  } finally {
    saving.value = false
  }
}

async function remove() {
  if (!window.confirm('登録したAPIキーを削除しますか？削除するとAI機能が使えなくなります。')) return
  removing.value = true
  error.value = ''
  try {
    await deleteGeminiApiKey()
    await load()
    notify('APIキーを削除しました。')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'APIキーを削除できませんでした。'
  } finally {
    removing.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="panel backup-panel settings-panel">
    <div class="settings-panel__heading">
      <div>
        <h2>① Gemini API キー</h2>
        <p>① を使う役割（対話・文字起こし・Gemini TTS の読み上げ）で使うキーです。② Vertex AI だけを使う場合は設定不要です。</p>
      </div>
      <v-btn variant="text" size="small" prepend-icon="mdi-refresh" :loading="loading" @click="load">更新</v-btn>
    </div>

    <p v-if="error" class="backup-error"><v-icon size="18">mdi-alert-circle-outline</v-icon>{{ error }}</p>

    <div v-if="status" class="backup-panel__intro">
      <span><v-icon size="22">{{ status.icon }}</v-icon></span>
      <div>
        <b>{{ status.title }}</b>
        <p>{{ status.text }}</p>
      </div>
    </div>
    <v-progress-linear v-else-if="loading" indeterminate color="primary"></v-progress-linear>

    <form v-if="settings && !lockedByEnvironment" class="backup-download-form" @submit.prevent="save">
      <v-text-field
        v-model="apiKey"
        :type="showKey ? 'text' : 'password'"
        :label="settings.source === 'stored' ? '新しいAPIキー' : 'APIキー'"
        placeholder="Google AI Studio で発行したキー"
        density="comfortable"
        autocomplete="off"
        spellcheck="false"
        hide-details
        :append-inner-icon="showKey ? 'mdi-eye-off-outline' : 'mdi-eye-outline'"
        @click:append-inner="showKey = !showKey"
      ></v-text-field>
      <div class="ai-settings-actions">
        <v-btn type="submit" color="primary" prepend-icon="mdi-check" :loading="saving" :disabled="!apiKey.trim()">確認して保存</v-btn>
        <v-btn
          v-if="settings.source === 'stored'"
          variant="outlined"
          color="error"
          prepend-icon="mdi-delete-outline"
          :loading="removing"
          @click="remove"
        >削除</v-btn>
      </div>
    </form>

    <p v-if="settings && !lockedByEnvironment" class="ai-settings-note">
      保存する前に Gemini API へ問い合わせて、キーが使えるかを確かめます。キーはサーバーのデータ保存先に保存され、画面には末尾4文字だけを表示します。
      業務データを扱うため、有料枠のキーを勧めます。
    </p>
  </section>
</template>

<style scoped>
.ai-settings-actions { display:flex; gap:8px; }
.ai-settings-actions .v-btn { height:40px; text-transform:none; }
.ai-settings-note { margin:0; color:var(--ink-7); font-size:12px; line-height:1.7; }
</style>
