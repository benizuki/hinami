<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import {
  getSpeechPreferences,
  saveSpeechPreferences,
  synthesizeSpeech,
  type SpeechPreferences,
  type SpeechPreferencesResponse,
} from '../../api/hinami'
import { useNotifier } from '../shell/useNotifier'
import { useSpeechPreferences } from './useSpeechPreferences'

const open = defineModel<boolean>({ required: true })

const PREVIEW_TEXT = 'こんにちは。今日はどんなお仕事をしましたか？'

const { notify } = useNotifier()
const { markPreferencesChanged } = useSpeechPreferences()

const options = ref<SpeechPreferencesResponse | null>(null)
const form = ref<SpeechPreferences>({ voice: '', tone: 'default', pace: 'normal' })
const loading = ref(false)
const saving = ref(false)
const previewing = ref(false)
const error = ref('')
let previewAudio: HTMLAudioElement | null = null
let previewUrl = ''
let previewController: AbortController | null = null

const voiceItems = computed(() => [
  { title: `システムの既定（${options.value?.default_voice ?? ''}）`, value: '' },
  ...(options.value?.voices ?? []).map((voice) => ({ title: `${voice.id}（${voice.label}）`, value: voice.id })),
])
const toneItems = computed(() => (options.value?.tones ?? []).map((tone) => ({ title: tone.label, value: tone.id })))
const paceItems = computed(() => (options.value?.paces ?? []).map((pace) => ({ title: pace.label, value: pace.id })))

async function load() {
  loading.value = true
  error.value = ''
  try {
    options.value = await getSpeechPreferences()
    form.value = { voice: options.value.voice, tone: options.value.tone, pace: options.value.pace }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '読み上げの設定を取得できませんでした。'
  } finally {
    loading.value = false
  }
}

function stopPreview() {
  previewController?.abort()
  previewController = null
  previewAudio?.pause()
  previewAudio = null
  if (previewUrl) URL.revokeObjectURL(previewUrl)
  previewUrl = ''
  previewing.value = false
}

async function preview() {
  stopPreview()
  previewing.value = true
  error.value = ''
  const controller = new AbortController()
  previewController = controller
  try {
    const blob = await synthesizeSpeech(PREVIEW_TEXT, controller.signal, form.value)
    if (controller.signal.aborted) return
    previewUrl = URL.createObjectURL(blob)
    previewAudio = new Audio(previewUrl)
    previewAudio.onended = () => stopPreview()
    await previewAudio.play()
  } catch (cause) {
    if (controller.signal.aborted) return
    error.value = cause instanceof Error ? cause.message : '試聴の音声を作れませんでした。'
    stopPreview()
  }
}

async function save() {
  saving.value = true
  error.value = ''
  try {
    options.value = await saveSpeechPreferences(form.value)
    markPreferencesChanged()
    notify('読み上げの設定を保存しました。')
    open.value = false
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '読み上げの設定を保存できませんでした。'
  } finally {
    saving.value = false
  }
}

watch(open, (value) => {
  if (value) void load()
  else stopPreview()
})
onUnmounted(stopPreview)
</script>

<template>
  <v-dialog v-model="open" max-width="520">
    <v-card class="dialog-card">
      <v-card-title>読み上げの設定</v-card-title>
      <v-card-subtitle>AIの質問を読み上げる声・トーン・ペースを選びます。あなただけに適用されます。</v-card-subtitle>
      <v-card-text>
        <p v-if="error" class="backup-error"><v-icon size="18">mdi-alert-circle-outline</v-icon>{{ error }}</p>
        <v-progress-linear v-if="loading" indeterminate color="primary" class="speech-preferences__loading"></v-progress-linear>
        <div class="speech-preferences">
          <v-select v-model="form.voice" :items="voiceItems" label="声" :disabled="loading" hide-details></v-select>
          <div class="speech-preferences__row">
            <v-select v-model="form.tone" :items="toneItems" label="トーン" :disabled="loading" hide-details></v-select>
            <v-select v-model="form.pace" :items="paceItems" label="ペース" :disabled="loading" hide-details></v-select>
          </div>
          <p class="speech-preferences__note">トーンやペースを指定しないと、声そのものの自然な読み方になります。気になるところだけ変えるのがおすすめです。</p>
        </div>
      </v-card-text>
      <v-card-actions>
        <v-btn
          variant="outlined"
          :prepend-icon="previewing ? 'mdi-stop' : 'mdi-play'"
          :disabled="loading"
          @click="previewing ? stopPreview() : preview()"
        >{{ previewing ? '停止' : '試聴' }}</v-btn>
        <v-spacer></v-spacer>
        <v-btn variant="text" @click="open = false">キャンセル</v-btn>
        <v-btn color="primary" prepend-icon="mdi-content-save-outline" :loading="saving" :disabled="loading" @click="save">保存</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<style scoped>
.speech-preferences { display:grid; gap:12px; }
.speech-preferences__row { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
.speech-preferences__note { margin:0; color:var(--ink-7); font-size:12px; line-height:1.7; }
.speech-preferences__loading { margin-bottom:12px; }
@media (max-width: 480px) {
  .speech-preferences__row { grid-template-columns:1fr; }
}
</style>
