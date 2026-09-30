<script setup lang="ts">
import type { TenantRecord, UserMasterEntry } from '../../../api/hinami'

const props = defineProps<{
  tenants: TenantRecord[]
  users: UserMasterEntry[]
  activeTenantId: string
  /** システムviewerは閲覧のみ。更新はバックエンドでも拒否される。 */
  canManage: boolean
}>()

const emit = defineEmits<{
  reload: []
  add: []
  edit: [tenant: TenantRecord]
}>()

function hasTenantAccess(user: UserMasterEntry, tenantId: string) {
  return user.tenant_memberships.some((membership) => membership.tenant_id === tenantId)
}
</script>

<template>
  <section class="page master-page">
    <div class="page-heading page-heading--compact">
      <div><div class="eyebrow">TENANT ADMINISTRATION</div><h1>テナント管理</h1><p v-if="props.canManage">会社や事業所など、データを分けて管理する単位を作成し、利用状態を管理します。</p><p v-else>登録されているテナントを閲覧しています。作成・編集はシステム管理者のみ行えます。</p></div>
      <div class="heading-actions">
        <v-btn variant="outlined" prepend-icon="mdi-refresh" @click="emit('reload')">再読み込み</v-btn>
        <v-btn v-if="props.canManage" color="primary" prepend-icon="mdi-office-building-plus-outline" @click="emit('add')">テナントを追加</v-btn>
      </div>
    </div>
    <section class="tenant-card-grid">
      <article v-for="tenant in tenants" :key="tenant.id" class="panel tenant-card" :class="{ 'tenant-card--active': tenant.id === activeTenantId }">
        <header><span><v-icon>mdi-office-building-outline</v-icon></span><em>{{ tenant.enabled ? '有効' : '無効' }}</em></header>
        <h2>{{ tenant.name }}</h2>
        <code>{{ tenant.id }}</code>
        <p>{{ tenant.description || '説明は未設定です。' }}</p>
        <footer>
          <small>{{ users.filter((user) => hasTenantAccess(user, tenant.id)).length }}ユーザー</small>
          <button v-if="props.canManage" @click="emit('edit', tenant)"><v-icon size="16">mdi-pencil-outline</v-icon>編集</button>
        </footer>
      </article>
    </section>
  </section>
</template>
