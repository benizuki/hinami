<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { getAiUsage, type AiUsageReport } from '../../../api/hinami'

const today = new Date()
const dateFrom = ref(toDateKey(new Date(today.getFullYear(), today.getMonth(), today.getDate() - 29)))
const dateTo = ref(toDateKey(today))
const report = ref<AiUsageReport | null>(null)
const loading = ref(false)
const error = ref('')

function toDateKey(value: Date) {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`
}

function formatTokens(tokens: number) {
  if (tokens < 1000) return String(tokens)
  if (tokens < 1_000_000) return `${(tokens / 1000).toFixed(1)}K`
  return `${(tokens / 1_000_000).toFixed(2)}M`
}

function formatDuration(milliseconds: number) {
  if (milliseconds < 1000) return `${milliseconds}ms`
  const seconds = milliseconds / 1000
  return seconds < 90 ? `${seconds.toFixed(1)}秒` : `${Math.round(seconds / 60)}分`
}

/** 1日あたりの上限に対する消化率。上限なしの場合は表示しない。 */
const dailyUsageRatio = computed(() => {
  const limit = report.value?.rate_limit_per_day ?? 0
  if (!limit) return 0
  return Math.min(100, Math.round(((report.value?.used_today ?? 0) / limit) * 100))
})

const busiestDay = computed(() => Math.max(1, ...(report.value?.by_day ?? []).map((item) => item.calls)))
const totalDuration = computed(() => (report.value?.by_feature ?? []).reduce((total, item) => total + item.total_duration_ms, 0))

async function load() {
  loading.value = true
  error.value = ''
  try {
    report.value = await getAiUsage(dateFrom.value, dateTo.value)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'AI利用状況を取得できませんでした'
    report.value = null
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="page simple-page ai-usage-page">
    <div class="page-heading page-heading--compact">
      <div>
        <div class="eyebrow">AI USAGE</div>
        <h1>AI利用状況</h1>
        <p>日々の記録、チームの記録、記録の見取り図などGeminiを呼ぶ機能の利用回数を集計します。</p>
      </div>
      <div class="heading-actions ai-usage-range">
        <v-text-field v-model="dateFrom" type="date" label="開始日" density="compact" hide-details></v-text-field>
        <v-text-field v-model="dateTo" type="date" label="終了日" density="compact" hide-details></v-text-field>
        <v-btn color="primary" prepend-icon="mdi-refresh" :loading="loading" @click="load">再集計</v-btn>
      </div>
    </div>

    <p v-if="error" class="ai-usage-error"><v-icon size="18">mdi-alert-circle-outline</v-icon>{{ error }}</p>

    <template v-if="report">
      <div class="master-summary">
        <div>
          <span class="master-summary__icon"><v-icon>mdi-counter</v-icon></span>
          <p><strong>{{ report.total_calls }}</strong><span>期間内の呼び出し</span></p>
        </div>
        <div>
          <span class="master-summary__icon master-summary__icon--mint"><v-icon>mdi-alpha-t-box-outline</v-icon></span>
          <p><strong>{{ formatTokens(report.total_tokens) }}</strong><span>合計トークン</span></p>
        </div>
        <div>
          <span class="master-summary__icon"><v-icon>mdi-timer-outline</v-icon></span>
          <p><strong>{{ formatDuration(totalDuration) }}</strong><span>合計処理時間</span></p>
        </div>
        <div>
          <span class="master-summary__icon master-summary__icon--orange"><v-icon>mdi-speedometer</v-icon></span>
          <p><strong>{{ report.used_today }}</strong><span>本日の使用{{ report.rate_limit_per_day ? ` / ${report.rate_limit_per_day}` : '' }}</span></p>
        </div>
        <div class="master-summary__note">
          <v-icon size="17">mdi-information-outline</v-icon>
          <span>
            {{ report.scope === 'tenant' ? 'テナント全体の利用状況を表示しています。' : '自分の利用状況を表示しています。' }}
            上限は1分あたり{{ report.rate_limit_per_minute || '無制限' }}回、1日あたり{{ report.rate_limit_per_day || '無制限' }}回です。
            読み上げのトークン数は記録していません（回数だけを数えます）。
          </span>
        </div>
      </div>

      <div v-if="report.rate_limit_per_day" class="ai-usage-quota">
        <div><span>本日の消化</span><b>{{ dailyUsageRatio }}%</b></div>
        <i><em :style="{ width: `${dailyUsageRatio}%` }" :class="{ warn: dailyUsageRatio >= 80 }"></em></i>
      </div>

      <section class="panel ai-usage-panel">
        <div class="master-pane-title"><span>日別の呼び出し</span><em>{{ report.date_from }} 〜 {{ report.date_to }}</em></div>
        <div v-if="report.by_day.length" class="ai-usage-bars">
          <div v-for="day in report.by_day" :key="day.day" :title="`${day.day}：${day.calls}回 / ${formatTokens(day.total_tokens)}トークン`">
            <i :style="{ height: `${Math.max(4, (day.calls / busiestDay) * 100)}%` }"></i>
            <small>{{ day.day.slice(5) }}</small>
          </div>
        </div>
        <div v-else class="catalog-empty"><v-icon>mdi-chart-bar</v-icon><span>この期間の利用はありません</span></div>
      </section>

      <div class="ai-usage-tables">
        <section class="panel ai-usage-panel">
          <div class="master-pane-title"><span>機能別</span><em>{{ report.by_feature.length }}件</em></div>
          <table class="ai-usage-table">
            <thead><tr><th>機能</th><th>回数</th><th>トークン</th><th>処理時間</th></tr></thead>
            <tbody>
              <tr v-for="row in report.by_feature" :key="row.feature">
                <td>{{ row.feature }}</td>
                <td class="numeric">{{ row.calls }}</td>
                <td class="numeric">{{ formatTokens(row.total_tokens) }}</td>
                <td class="numeric">{{ formatDuration(row.total_duration_ms) }}</td>
              </tr>
              <tr v-if="!report.by_feature.length"><td colspan="4" class="empty">利用はありません</td></tr>
            </tbody>
          </table>
        </section>

        <section class="panel ai-usage-panel">
          <div class="master-pane-title"><span>利用者別</span><em>{{ report.by_user.length }}名</em></div>
          <table class="ai-usage-table">
            <thead><tr><th>利用者</th><th>回数</th><th>入力</th><th>出力</th><th>エラー</th><th>制限</th></tr></thead>
            <tbody>
              <tr v-for="row in report.by_user" :key="row.user_email">
                <td>{{ row.user_email }}</td>
                <td class="numeric">{{ row.calls }}</td>
                <td class="numeric">{{ formatTokens(row.prompt_tokens) }}</td>
                <td class="numeric">{{ formatTokens(row.output_tokens) }}</td>
                <td class="numeric" :class="{ alert: row.errors }">{{ row.errors }}</td>
                <td class="numeric" :class="{ alert: row.rate_limited }">{{ row.rate_limited }}</td>
              </tr>
              <tr v-if="!report.by_user.length"><td colspan="6" class="empty">利用はありません</td></tr>
            </tbody>
          </table>
        </section>
      </div>
    </template>
  </section>
</template>
