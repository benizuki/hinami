<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { saveGoogleIntegrations, type GoogleIntegrationSettings } from '../../../api/hinami'
import { useGoogleIntegrations } from '../../shell/useGoogleIntegrations'
import { useNotifier } from '../../shell/useNotifier'

defineProps<{
  /** Googleログインが無効な開発モードでは、どの機能も使われない。 */
  googleOauthEnabled: boolean
}>()

type Feature = keyof GoogleIntegrationSettings

const FEATURES: { key: Feature; icon: string; title: string; text: string }[] = [
  { key: 'calendar', icon: 'mdi-calendar-outline', title: 'Googleカレンダー', text: '記録をつけるとき、その日の自分の予定を読み込みます。' },
  { key: 'meet', icon: 'mdi-video-outline', title: 'Google Meet', text: '予定の会議について、実際の参加人数や録画・議事録の有無を確認します。カレンダーが有効なときだけ使えます。' },
  { key: 'gmail', icon: 'mdi-email-outline', title: 'Gmail', text: 'その日の送受信の件数と、依頼らしいメールの候補を確認します。本文は保存しません。' },
  { key: 'drive', icon: 'mdi-google-drive', title: 'Google Drive', text: 'Driveの資料を選んで、記録をつける対話に添付できます。' },
]

const { notify } = useNotifier()
const { googleIntegrations, reload, apply } = useGoogleIntegrations()

const form = ref<GoogleIntegrationSettings>({ ...googleIntegrations.value })
const loading = ref(false)
const saving = ref(false)
const error = ref('')

const changed = computed(() => FEATURES.some(({ key }) => form.value[key] !== googleIntegrations.value[key]))

function toggle(feature: Feature, value: boolean | null) {
  form.value = { ...form.value, [feature]: Boolean(value) }
  // Meetの実績はカレンダーの予定から辿るため、カレンダーを止めたら一緒に止める。
  if (feature === 'calendar' && !value) form.value.meet = false
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    await reload()
    form.value = { ...googleIntegrations.value }
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  error.value = ''
  try {
    const saved = await saveGoogleIntegrations(form.value)
    apply(saved)
    form.value = { ...saved }
    notify('Google連携の設定を保存しました。')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'Google連携の設定を保存できませんでした。'
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="panel backup-panel settings-panel">
    <div class="settings-panel__heading">
      <div>
        <h2>Google連携</h2>
        <p>記録をつけるときに使うGoogleの機能を選びます。全テナント共通の設定です。</p>
      </div>
      <v-btn variant="text" size="small" prepend-icon="mdi-refresh" :loading="loading" @click="load">更新</v-btn>
    </div>

    <p v-if="error" class="backup-error"><v-icon size="18">mdi-alert-circle-outline</v-icon>{{ error }}</p>
    <p v-if="!googleOauthEnabled" class="google-integrations-notice">
      <v-icon size="17">mdi-information-outline</v-icon>
      Googleログインが無効のため、いまはどの機能も使われません。GOOGLE_OAUTH_CLIENT_ID を設定すると有効になります。
    </p>

    <ul class="google-integrations">
      <li v-for="feature in FEATURES" :key="feature.key">
        <span class="google-integrations__icon"><v-icon size="20">{{ feature.icon }}</v-icon></span>
        <div>
          <b>{{ feature.title }}</b>
          <p>{{ feature.text }}</p>
        </div>
        <v-switch
          :model-value="form[feature.key]"
          :disabled="feature.key === 'meet' && !form.calendar"
          color="success"
          density="compact"
          inset
          hide-details
          :label="form[feature.key] ? 'オン' : 'オフ'"
          :aria-label="`${feature.title}を使う`"
          @update:model-value="toggle(feature.key, $event)"
        ></v-switch>
      </li>
    </ul>

    <div class="google-integrations__actions">
      <p>無効にした機能は、日々の記録の画面で許可を求めず、ボタンも出しません。すでに許可した権限は、各利用者が Google アカウントの設定から取り消せます。</p>
      <v-btn color="primary" prepend-icon="mdi-check" :loading="saving" :disabled="!changed" @click="save">保存</v-btn>
    </div>
  </section>
</template>

<style scoped>
.google-integrations-notice { display:flex; align-items:flex-start; gap:6px; margin:0 0 12px; padding:10px 12px; border-radius:10px; color:var(--ink-5); background:var(--surface-muted); font-size:12px; line-height:1.6; }
.google-integrations { margin:0; padding:0; list-style:none; border-top:1px solid var(--border-subtle); }
.google-integrations li { display:grid; grid-template-columns:36px minmax(0,1fr) auto; align-items:center; gap:12px; padding:12px 0; border-bottom:1px solid var(--border-subtle); }
.google-integrations__icon { display:grid; place-items:center; width:36px; height:36px; border-radius:10px; color:var(--text-brand-strong); background:var(--surface-accent); }
.google-integrations b { color:var(--ink-3); font-size:14px; }
.google-integrations p { margin:2px 0 0; color:var(--ink-7); font-size:12px; line-height:1.6; }
/* オンは苔色のトラック、オフは淡い地に縁取り。色だけに頼らず、横の「オン／オフ」の文字でも分かるようにする。 */
.google-integrations :deep(.v-selection-control:not(.v-selection-control--dirty) .v-switch__track) { opacity:1; background:var(--surface-raised); box-shadow:inset 0 0 0 1px var(--border-soft); }
.google-integrations :deep(.v-selection-control:not(.v-selection-control--dirty) .v-switch__thumb) { color:var(--ink-7); background:var(--surface-card); }
.google-integrations :deep(.v-selection-control--dirty .v-switch__track) { opacity:1; }
.google-integrations :deep(.v-switch .v-label) { min-width:2.2em; margin-inline-start:6px; opacity:1; color:var(--ink-5); font-size:12px; font-weight:600; }
.google-integrations :deep(.v-selection-control--dirty ~ .v-label) { color:var(--text-brand-strong); }
.google-integrations__actions { display:flex; align-items:center; justify-content:space-between; gap:16px; margin-top:14px; }
.google-integrations__actions p { margin:0; color:var(--ink-7); font-size:12px; line-height:1.7; }
.google-integrations__actions .v-btn { flex:0 0 auto; height:40px; text-transform:none; }
@media (max-width: 780px) {
  .google-integrations__actions { align-items:stretch; flex-direction:column; }
}
</style>
