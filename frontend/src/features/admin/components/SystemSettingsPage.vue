<script setup lang="ts">
import { ref, watch } from 'vue'
import AiModelsPanel from './AiModelsPanel.vue'
import AppModePanel from './AppModePanel.vue'
import GeminiSettingsPanel from './GeminiSettingsPanel.vue'
import GoogleCloudAuthPanel from './GoogleCloudAuthPanel.vue'
import GoogleIntegrationsPanel from './GoogleIntegrationsPanel.vue'

defineProps<{
  googleOauthEnabled: boolean
}>()

type SettingsTab = 'connections' | 'models' | 'google' | 'mode'

const TABS: { key: SettingsTab; label: string; icon: string }[] = [
  { key: 'connections', label: '接続方法', icon: 'mdi-key-chain-variant' },
  { key: 'models', label: 'AIモデル', icon: 'mdi-robot-outline' },
  { key: 'google', label: 'Google連携', icon: 'mdi-google' },
  { key: 'mode', label: '動作モード', icon: 'mdi-book-open-page-variant-outline' },
]
// 開き直したとき、前回見ていたタブへ戻す（このブラウザにだけ覚えておく）。
const TAB_STORAGE_KEY = 'hinami_system_settings_tab'

function readTab(): SettingsTab {
  try {
    const stored = localStorage.getItem(TAB_STORAGE_KEY)
    return TABS.some((tab) => tab.key === stored) ? stored as SettingsTab : 'connections'
  } catch {
    return 'connections'
  }
}

const tab = ref<SettingsTab>(readTab())
watch(tab, (value) => {
  try {
    localStorage.setItem(TAB_STORAGE_KEY, value)
  } catch {
    // 保存できなくても、この画面を開いている間は選んだタブのまま使える。
  }
})
</script>

<template>
  <section class="page simple-page system-settings-page">
    <div class="page-heading page-heading--compact">
      <div>
        <div class="eyebrow">SYSTEM SETTINGS</div>
        <h1>システム設定</h1>
        <p>全テナントに共通する設定です。システム管理者だけが変更できます。</p>
      </div>
    </div>

    <v-tabs v-model="tab" color="primary" density="comfortable" show-arrows class="system-settings__tabs">
      <v-tab v-for="item in TABS" :key="item.key" :value="item.key" :prepend-icon="item.icon">{{ item.label }}</v-tab>
    </v-tabs>

    <!-- 各タブは開いたときに最新の設定を読み込む。接続方法を変えてから AIモデル を開いても古い値を見せない。 -->
    <div v-if="tab === 'connections'" class="system-settings__body">
      <p class="system-settings__lead">AIを呼び出す方法です。使うものだけ設定します。どちらを使うかは「AIモデル」で役割ごとに選びます。</p>
      <GeminiSettingsPanel />
      <GoogleCloudAuthPanel />
    </div>
    <div v-else-if="tab === 'models'" class="system-settings__body">
      <AiModelsPanel />
    </div>
    <div v-else-if="tab === 'mode'" class="system-settings__body">
      <AppModePanel />
    </div>
    <div v-else class="system-settings__body">
      <GoogleIntegrationsPanel :google-oauth-enabled="googleOauthEnabled" />
    </div>
  </section>
</template>

<style scoped>
.system-settings__tabs { margin-bottom:16px; border-bottom:1px solid var(--border-default); }
.system-settings__tabs :deep(.v-tab) { font-size:13px; letter-spacing:0; text-transform:none; }
.system-settings__lead { margin:0 0 12px; color:var(--ink-7); font-size:13px; line-height:1.7; }
</style>
