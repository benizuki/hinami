<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { OrgUnitRecord, TenantRecord, UserMasterEntry } from '../../../api/hinami'

const props = defineProps<{
  users: UserMasterEntry[]
  tenants: TenantRecord[]
  /** 選択中テナントの組織。所属はテナントごとに持つ。 */
  orgUnits: OrgUnitRecord[]
  activeTenantId: string
  currentUserEmail?: string
  /** システム管理者は全テナント、テナント管理者は自テナントだけを扱う。 */
  isSystemAdmin: boolean
  scopedTenantName: string
  /** システムviewerは閲覧のみ。更新はバックエンドでも拒否される。 */
  canManage: boolean
}>()

// 「未所属」を絞り込めるようにするための、IDとぶつからない番兵。
const UNASSIGNED = '__unassigned__'

// クリア操作でnullが入るため、空値はnullも許容する。
const tenantFilter = ref<string | null>('')
const orgUnitFilter = ref<string | null>('')

function orgUnitName(orgUnitId?: string | null) {
  return props.orgUnits.find((unit) => unit.id === orgUnitId)?.name || ''
}

/** 表示中テナントでの所属。移行前の利用者はテナントを持たない値で補う。 */
function userOrgUnitId(user: UserMasterEntry) {
  const membership = user.tenant_memberships.find((item) => item.tenant_id === props.activeTenantId)
  const target = (membership?.org_unit_id || '').trim() || (user.org_unit_id || '').trim()
  return props.orgUnits.some((unit) => unit.id === target) ? target : ''
}

// テナント絞り込みが効いているときは、そのテナントの組織だけを選択肢にする。
const filterableOrgUnits = computed(() => {
  if (!tenantFilter.value || tenantFilter.value === UNASSIGNED) return props.orgUnits
  return props.orgUnits.filter((unit) => unit.tenant_id === tenantFilter.value)
})

const tenantFilterItems = computed(() => [
  ...props.tenants.map((tenant) => ({ value: tenant.id, title: tenant.name || tenant.id })),
  { value: UNASSIGNED, title: 'テナント権限なし' },
])

// 階層が分かるよう、親からの深さだけ字下げして並べる。
const orgUnitFilterItems = computed(() => {
  const units = filterableOrgUnits.value
  const childrenByParent = new Map<string, OrgUnitRecord[]>()
  for (const unit of units) {
    childrenByParent.set(unit.parent_id, [...(childrenByParent.get(unit.parent_id) || []), unit])
  }
  for (const children of childrenByParent.values()) {
    children.sort((left, right) => left.sort_order - right.sort_order || left.name.localeCompare(right.name))
  }
  const items: Array<{ value: string; title: string }> = []
  const seen = new Set<string>()
  const walk = (parentId: string, depth: number) => {
    for (const unit of childrenByParent.get(parentId) || []) {
      if (seen.has(unit.id)) continue
      seen.add(unit.id)
      items.push({ value: unit.id, title: `${'　'.repeat(depth)}${unit.name}` })
      walk(unit.id, depth + 1)
    }
  }
  walk('', 0)
  // 親が絞り込みで消えた組織も拾えるようにしておく。
  for (const unit of units) {
    if (!seen.has(unit.id)) items.push({ value: unit.id, title: unit.name })
  }
  return [...items, { value: UNASSIGNED, title: '組織未設定' }]
})

// 部門を選んだら配下の課・チームも含めたい。
function orgUnitScope(orgUnitId: string) {
  const collected = new Set<string>([orgUnitId])
  let added = true
  while (added) {
    added = false
    for (const unit of props.orgUnits) {
      if (collected.has(unit.parent_id) && !collected.has(unit.id)) {
        collected.add(unit.id)
        added = true
      }
    }
  }
  return collected
}

const visibleUsers = computed(() => {
  let list = props.users
  if (tenantFilter.value === UNASSIGNED) {
    list = list.filter((user) => user.tenant_memberships.length === 0)
  } else if (tenantFilter.value) {
    list = list.filter((user) => user.tenant_memberships.some((membership) => membership.tenant_id === tenantFilter.value))
  }
  if (orgUnitFilter.value === UNASSIGNED) {
    list = list.filter((user) => !userOrgUnitId(user))
  } else if (orgUnitFilter.value) {
    const scope = orgUnitScope(orgUnitFilter.value)
    list = list.filter((user) => scope.has(userOrgUnitId(user)))
  }
  return list
})

const filtered = computed(() => Boolean(tenantFilter.value || orgUnitFilter.value))

function clearFilters() {
  tenantFilter.value = ''
  orgUnitFilter.value = ''
}

// テナントを変えたとき、そのテナントに無い組織が選ばれたままにならないようにする。
watch(tenantFilter, () => {
  if (!orgUnitFilter.value || orgUnitFilter.value === UNASSIGNED) return
  if (!filterableOrgUnits.value.some((unit) => unit.id === orgUnitFilter.value)) orgUnitFilter.value = ''
})

const emit = defineEmits<{
  reload: []
  manageOrgUnits: []
  add: []
  edit: [user: UserMasterEntry]
  remove: [user: UserMasterEntry]
}>()
</script>

<template>
  <section class="page master-page">
    <div class="page-heading page-heading--compact">
      <div><div class="eyebrow">USER ADMINISTRATION</div><h1>ユーザー管理</h1><p v-if="!props.canManage">登録済みの利用者とテナント権限を閲覧しています。変更はシステム管理者かテナント管理者が行えます。</p><p v-else-if="props.isSystemAdmin">Googleログインと、テナントごとのアクセス権限を管理します。</p><p v-else>「{{ props.scopedTenantName }}」に所属する利用者と、そのテナント内のロールを管理します。</p></div>
      <div class="heading-actions">
        <v-btn variant="outlined" prepend-icon="mdi-refresh" @click="emit('reload')">再読み込み</v-btn>
        <v-btn variant="tonal" color="primary" prepend-icon="mdi-sitemap-outline" @click="emit('manageOrgUnits')">組織マスター</v-btn>
        <v-btn v-if="props.canManage" color="primary" prepend-icon="mdi-account-plus-outline" @click="emit('add')">ユーザーを追加</v-btn>
      </div>
    </div>

    <section class="panel user-admin-panel">
      <div class="user-admin-filters">
        <v-select
          v-if="props.tenants.length > 1"
          v-model="tenantFilter"
          :items="tenantFilterItems"
          label="テナントで絞り込む"
          density="comfortable"
          variant="outlined"
          clearable
          hide-details
        ></v-select>
        <v-select
          v-model="orgUnitFilter"
          :items="orgUnitFilterItems"
          label="組織で絞り込む"
          density="comfortable"
          variant="outlined"
          clearable
          hide-details
          :disabled="props.orgUnits.length === 0"
        ></v-select>
        <span class="user-admin-filters__count">{{ visibleUsers.length }}件 / 全{{ users.length }}件</span>
        <v-btn v-if="filtered" variant="text" size="small" prepend-icon="mdi-filter-remove-outline" @click="clearFilters">絞り込みを解除</v-btn>
      </div>

      <div class="user-admin-table">
        <div class="user-admin-table__head"><span>ユーザー</span><span>所属組織（{{ props.scopedTenantName }}）</span><span>システムロール</span><span>状態</span><span>テナント権限</span><span>操作</span></div>
        <article v-for="user in visibleUsers" :key="user.email" class="user-admin-row">
          <div><b>{{ user.name }}</b><small>{{ user.email }}</small></div>
          <span>{{ orgUnitName(userOrgUnitId(user)) || '未設定' }}</span>
          <em :class="`role-${user.role}`">{{ user.role === 'none' ? 'なし' : user.role }}</em>
          <span>{{ user.enabled ? '有効' : '無効' }}</span>
          <div class="tenant-role-list">
            <span v-for="membership in user.tenant_memberships" :key="membership.tenant_id"><b>{{ tenants.find((tenant) => tenant.id === membership.tenant_id)?.name || membership.tenant_id }}</b><em :class="`role-${membership.role}`">{{ membership.role }}</em></span>
            <small v-if="user.tenant_memberships.length === 0">権限なし</small>
          </div>
          <div v-if="props.canManage" class="user-admin-actions">
            <button @click="emit('edit', user)"><v-icon size="16">mdi-pencil-outline</v-icon>編集</button>
            <button :disabled="user.email === currentUserEmail" :title="props.isSystemAdmin ? 'ユーザーを削除' : 'このテナントから外す'" @click="emit('remove', user)"><v-icon size="16">mdi-delete-outline</v-icon>{{ props.isSystemAdmin ? '削除' : '外す' }}</button>
          </div>
        </article>
        <div v-if="visibleUsers.length === 0" class="catalog-empty">
          <v-icon>mdi-account-search-outline</v-icon>
          <span v-if="filtered">条件に一致する利用者がいません。絞り込みを変えてください。</span>
          <span v-else-if="props.isSystemAdmin">登録ユーザーがありません。最初にGoogleログインしたユーザーは自動的にadminになります。</span>
          <span v-else>このテナントに所属する利用者がまだいません。「ユーザーを追加」から登録してください。</span>
        </div>
      </div>
    </section>
  </section>
</template>
