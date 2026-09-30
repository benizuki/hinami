<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  createSQLiteBackup,
  downloadSQLiteBackup,
  getSQLiteBackups,
  getSQLiteDatabaseStatistics,
  type SQLiteDatabaseStatistics,
  type SQLiteBackupRecord,
} from '../../../api/hinami'

const backups = ref<SQLiteBackupRecord[]>([])
const statistics = ref<SQLiteDatabaseStatistics | null>(null)
const selectedBackupId = ref('')
const loading = ref(false)
const creating = ref(false)
const downloading = ref(false)
const error = ref('')

const selectedBackup = computed(() => backups.value.find((backup) => backup.id === selectedBackupId.value) ?? null)
const backupOptions = computed(() => backups.value.map((backup) => ({
  title: `${formatDate(backup.created_at)}（${formatSize(backup.size_bytes)}）`,
  value: backup.id,
})))

function formatDate(value: string) {
  return new Intl.DateTimeFormat('ja-JP', {
    dateStyle: 'medium', timeStyle: 'medium',
  }).format(new Date(value))
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`
}

function formatCount(value: number) {
  return new Intl.NumberFormat('ja-JP').format(value)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [backupRecords, databaseStatistics] = await Promise.all([
      getSQLiteBackups(),
      getSQLiteDatabaseStatistics(),
    ])
    backups.value = backupRecords
    statistics.value = databaseStatistics
    if (!backups.value.some((backup) => backup.id === selectedBackupId.value)) {
      selectedBackupId.value = backups.value[0]?.id ?? ''
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'バックアップ一覧を取得できませんでした。'
  } finally {
    loading.value = false
  }
}

async function createBackup() {
  creating.value = true
  error.value = ''
  try {
    const backup = await createSQLiteBackup()
    await load()
    selectedBackupId.value = backup.id
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'バックアップを作成できませんでした。'
  } finally {
    creating.value = false
  }
}

async function download() {
  if (!selectedBackup.value) return
  downloading.value = true
  error.value = ''
  try {
    await downloadSQLiteBackup(selectedBackup.value)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'バックアップをダウンロードできませんでした。'
  } finally {
    downloading.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="page simple-page backup-page">
    <div class="page-heading page-heading--compact">
      <div>
        <div class="eyebrow">DATABASE BACKUP</div>
        <h1>SQLiteバックアップ</h1>
        <p>現在のSQLiteデータベースの整合性を保ったスナップショットを作成・ダウンロードします。</p>
      </div>
      <div class="heading-actions">
        <v-btn variant="outlined" prepend-icon="mdi-refresh" :loading="loading" @click="load">更新</v-btn>
        <v-btn color="primary" prepend-icon="mdi-database-plus-outline" :loading="creating" @click="createBackup">バックアップを作成</v-btn>
      </div>
    </div>

    <p v-if="error" class="backup-error"><v-icon size="18">mdi-alert-circle-outline</v-icon>{{ error }}</p>

    <section class="panel database-stats-panel">
      <div class="database-stats-heading">
        <div>
          <h2>SQLite データ量</h2>
          <p>稼働中のデータベースと作成済みバックアップの現在量です。</p>
        </div>
        <span v-if="statistics">
          {{ statistics.database_filename }} / {{ statistics.journal_mode }} / 最終更新 {{ formatDate(statistics.last_modified_at) }}
        </span>
      </div>

      <template v-if="statistics">
        <div class="database-stat-cards">
          <article>
            <small>稼働ファイル合計</small>
            <strong>{{ formatSize(statistics.active_files_bytes) }}</strong>
            <span>DB {{ formatSize(statistics.database_bytes) }} / WAL {{ formatSize(statistics.wal_bytes) }} / SHM {{ formatSize(statistics.shm_bytes) }}</span>
          </article>
          <article>
            <small>論理使用量</small>
            <strong>{{ formatSize(statistics.logical_used_bytes) }}</strong>
            <span>未使用 {{ formatSize(statistics.unused_bytes) }} / 割当 {{ formatSize(statistics.allocated_bytes) }}</span>
          </article>
          <article class="database-stat-card--records">
            <small>レコード数</small>
            <strong>{{ formatCount(statistics.total_records) }}</strong>
            <span>{{ statistics.table_count }} テーブル</span>
          </article>
          <article>
            <small>バックアップ</small>
            <strong>{{ formatSize(statistics.backup_bytes) }}</strong>
            <span>{{ statistics.backup_count }} ファイル</span>
          </article>
        </div>

        <div class="database-usage">
          <div>
            <span>割当ページ使用率 {{ statistics.usage_percent.toFixed(1) }}%</span>
            <span>{{ formatSize(statistics.logical_used_bytes) }} / {{ formatSize(statistics.allocated_bytes) }}</span>
          </div>
          <i><em :style="{ width: `${statistics.usage_percent}%` }"></em></i>
        </div>

        <div class="database-table-heading">テーブル別データ量</div>
        <div class="database-table-wrap">
          <table class="database-table">
            <thead>
              <tr><th>テーブル</th><th>レコード</th><th>本体</th><th>インデックス</th><th>合計</th></tr>
            </thead>
            <tbody>
              <tr v-for="table in statistics.tables" :key="table.name">
                <td>{{ table.name }}</td>
                <td>{{ formatCount(table.row_count) }}</td>
                <td>{{ formatSize(table.table_bytes) }}</td>
                <td>{{ formatSize(table.index_bytes) }}</td>
                <td>{{ formatSize(table.total_bytes) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
      <v-progress-linear v-else-if="loading" indeterminate color="primary"></v-progress-linear>
    </section>

    <section class="panel backup-panel">
      <div class="backup-panel__intro">
        <span><v-icon size="22">mdi-database-lock-outline</v-icon></span>
        <div>
          <b>ダウンロードするバックアップを選択</b>
          <p>バックアップには全テナントのSQLiteデータが含まれます。安全な場所に保管してください。</p>
        </div>
      </div>

      <div class="backup-download-form">
        <v-select
          v-model="selectedBackupId"
          :items="backupOptions"
          label="バックアップ"
          placeholder="作成済みバックアップはありません"
          density="comfortable"
          hide-details
          :loading="loading"
          :disabled="!backups.length"
        ></v-select>
        <v-btn color="primary" prepend-icon="mdi-download" :loading="downloading" :disabled="!selectedBackup" @click="download">ダウンロード</v-btn>
      </div>

      <div class="backup-list-heading"><span>作成済みバックアップ</span><em>{{ backups.length }}件</em></div>
      <div v-if="backups.length" class="backup-list">
        <button
          v-for="backup in backups"
          :key="backup.id"
          :class="{ selected: backup.id === selectedBackupId }"
          @click="selectedBackupId = backup.id"
        >
          <v-icon size="19">mdi-database-outline</v-icon>
          <span><b>{{ formatDate(backup.created_at) }}</b><small>{{ backup.filename }}</small></span>
          <em>{{ formatSize(backup.size_bytes) }}</em>
        </button>
      </div>
      <div v-else-if="!loading" class="catalog-empty"><v-icon>mdi-database-off-outline</v-icon><span>作成済みバックアップはありません</span></div>
    </section>
  </section>
</template>
