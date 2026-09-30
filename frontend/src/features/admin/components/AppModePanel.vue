<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { saveAppMode, type AppMode } from '../../../api/hinami'
import { useAppMode } from '../../shell/useAppMode'
import { useNotifier } from '../../shell/useNotifier'

const MODES: { key: AppMode; icon: string; title: string; text: string; example: string }[] = [
  { key: 'diary', icon: 'mdi-book-open-page-variant-outline', title: '日記寄り', text: '一日を振り返る日記のような言葉づかいにします。', example: '「今日のできごと」' },
  { key: 'work', icon: 'mdi-briefcase-check-outline', title: '業務より', text: '日々の業務を記録する日報のような言葉づかいにします。', example: '「今日やった仕事」' },
]

const { notify } = useNotifier()
const { appMode, ensureLoaded, apply } = useAppMode()

const selected = ref<AppMode>(appMode.value)
const saving = ref(false)
const error = ref('')

const changed = computed(() => selected.value !== appMode.value)

async function save() {
  saving.value = true
  error.value = ''
  try {
    const saved = await saveAppMode(selected.value)
    apply(saved)
    selected.value = saved
    notify('動作モードを保存しました。')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '動作モードを保存できませんでした。'
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  await ensureLoaded()
  selected.value = appMode.value
})
</script>

<template>
  <section class="panel backup-panel settings-panel">
    <div class="settings-panel__heading">
      <div>
        <h2>動作モード</h2>
        <p>画面の言葉づかいを選びます。全テナント共通の設定です。記録の内容や分析は変わりません。</p>
      </div>
    </div>

    <p v-if="error" class="backup-error"><v-icon size="18">mdi-alert-circle-outline</v-icon>{{ error }}</p>

    <div class="app-mode" role="radiogroup" aria-label="動作モード">
      <button
        v-for="item in MODES"
        :key="item.key"
        type="button"
        role="radio"
        class="app-mode__option"
        :class="{ 'app-mode__option--on': selected === item.key }"
        :aria-checked="selected === item.key"
        @click="selected = item.key"
      >
        <v-icon size="22">{{ item.icon }}</v-icon>
        <span><b>{{ item.title }}</b><small>{{ item.text }}</small><em>{{ item.example }}</em></span>
      </button>
    </div>

    <div class="app-mode__actions">
      <v-btn color="primary" prepend-icon="mdi-check" :loading="saving" :disabled="!changed" @click="save">保存</v-btn>
    </div>
  </section>
</template>

<style scoped>
.app-mode { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:12px; margin-top:8px; }
.app-mode__option { display:flex; align-items:flex-start; gap:12px; padding:14px 16px; border:1px solid var(--border-mid); border-radius:12px; color:var(--ink-3); background:var(--surface-card); text-align:left; }
.app-mode__option:hover { background:var(--surface-subtle); }
.app-mode__option--on { border-color:var(--border-brand-strong); color:var(--text-brand-strong); background:var(--surface-accent); }
.app-mode__option b, .app-mode__option small, .app-mode__option em { display:block; }
.app-mode__option b { font-size:14px; }
.app-mode__option small { margin-top:4px; color:var(--ink-7); font-size:12px; line-height:1.6; }
.app-mode__option em { margin-top:6px; color:var(--ink-6); font-size:12px; font-style:normal; }
.app-mode__actions { display:flex; justify-content:flex-end; margin-top:16px; }
.app-mode__actions .v-btn { height:40px; text-transform:none; }
@media (max-width: 780px) { .app-mode { grid-template-columns:1fr; } }
</style>
