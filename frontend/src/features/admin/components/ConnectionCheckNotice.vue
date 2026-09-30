<script setup lang="ts">
import type { ConnectionCheckResult } from '../../../api/hinami'

defineProps<{
  result: ConnectionCheckResult
  /** 問い合わせ先の名前（「Vertex AI への問い合わせ」のように段階名に使う）。 */
  service: string
}>()

const STEP_LABELS: Record<ConnectionCheckResult['step'], string> = {
  credentials: '認証情報の用意',
  sts: 'アクセストークンの取得',
  api: 'への問い合わせ',
}
</script>

<template>
  <div class="connection-check" :class="result.ok ? 'connection-check--ok' : 'connection-check--ng'" role="status">
    <v-icon size="18">{{ result.ok ? 'mdi-check-circle-outline' : 'mdi-alert-circle-outline' }}</v-icon>
    <span v-if="result.ok">使えます。{{ result.message }}</span>
    <span v-else>{{ result.step === 'api' ? `${service}${STEP_LABELS.api}` : STEP_LABELS[result.step] }}で止まりました。{{ result.message }}</span>
  </div>
</template>

<style scoped>
.connection-check { display:flex; align-items:flex-start; gap:6px; margin-top:12px; padding:10px 12px; border-radius:10px; font-size:13px; line-height:1.6; overflow-wrap:anywhere; }
.connection-check--ok { color:var(--text-brand-strong); background:var(--surface-accent); }
.connection-check--ng { color:var(--text-danger-soft); background:var(--surface-danger); }
</style>
