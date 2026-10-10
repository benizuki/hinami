<script setup lang="ts">
import { toRef } from 'vue'
import { computed } from 'vue'
import type { OrgUnitRecord, TenantRecord, UserMasterEntry } from '../../../api/hinami'

const props = defineProps<{
  editingEmail: string
  form: UserMasterEntry
  tenants: TenantRecord[]
  /** 選択中テナントの組織。所属はテナントごとなので表示にだけ使う。 */
  orgUnits: OrgUnitRecord[]
  /** テナントIDごとの組織マスター。所属の選択肢に使う。 */
  tenantOrgUnits: Record<string, OrgUnitRecord[]>
  /** システムロールと全テナントの権限を編集できるのはシステム管理者だけ。 */
  isSystemAdmin: boolean
  /** テナント管理者が扱えるテナント。システム管理者は空文字。 */
  scopedTenantId: string
}>()

const open = defineModel<boolean>({ required: true })
const form = toRef(props, 'form')
const emit = defineEmits<{ save: [] }>()

// 階層が読み取れるよう、親からの深さでインデントした選択肢にする。
function orgUnitOptionsOf(units: OrgUnitRecord[]) {
  const byParent = new Map<string, OrgUnitRecord[]>()
  for (const unit of units) {
    byParent.set(unit.parent_id, [...(byParent.get(unit.parent_id) || []), unit])
  }
  const options: Array<{ id: string; label: string }> = [{ id: '', label: '未設定' }]
  const walk = (parentId: string, depth: number) => {
    for (const unit of byParent.get(parentId) || []) {
      options.push({ id: unit.id, label: `${'　'.repeat(depth)}${unit.name}（${unit.kind}）` })
      walk(unit.id, depth + 1)
    }
  }
  walk('', 0)
  return options
}

function tenantOrgUnitOptions(tenantId: string) {
  // 読み込みが終わるまでは、画面が既に持っている選択中テナントの一覧で埋める。
  const units = props.tenantOrgUnits[tenantId] || (tenantId === props.scopedTenantId ? props.orgUnits : [])
  return orgUnitOptionsOf(units)
}

const ROLE_OPTIONS = [
  { value: 'admin', label: 'admin（全テナントを管理）' },
  { value: 'viewer', label: 'viewer（全テナントを閲覧）' },
  { value: 'none', label: 'なし（所属テナントのみ）' },
]
// managerはuser相当の編集権限に加えて、自組織配下の業務日報を閲覧できる。
const TENANT_ROLE_OPTIONS = ['admin', 'manager', 'user', 'viewer']

// テナント管理者には自分が管理するテナントだけを見せる。他テナントの所属は
// バックエンドでも保持されるため、ここで編集対象から外しても失われない。
// メール・表示名・Google連携・有効/無効はアカウント全体に効くため、テナント管理者は
// 追加時のメールと表示名を除いて変えられない（バックエンドも受け付けない）。
const accountLocked = computed(() => !props.isSystemAdmin && !!props.editingEmail)

const editableTenants = computed(() => (
  props.isSystemAdmin
    ? props.tenants
    : props.tenants.filter((tenant) => tenant.id === props.scopedTenantId)
))

function tenantRole(tenantId: string) {
  return form.value.tenant_memberships.find((membership) => membership.tenant_id === tenantId)?.role
}

function setTenantAccess(tenantId: string, enabled: boolean) {
  const memberships = form.value.tenant_memberships
  const index = memberships.findIndex((membership) => membership.tenant_id === tenantId)
  if (enabled && index < 0) memberships.push({ tenant_id: tenantId, role: 'viewer', org_unit_id: '' })
  if (!enabled && index >= 0) memberships.splice(index, 1)
}

function tenantOrgUnitId(tenantId: string) {
  return form.value.tenant_memberships.find((membership) => membership.tenant_id === tenantId)?.org_unit_id || ''
}

function setTenantOrgUnit(tenantId: string, orgUnitId: string) {
  const membership = form.value.tenant_memberships.find((item) => item.tenant_id === tenantId)
  if (membership) membership.org_unit_id = orgUnitId || ''
}

function setTenantRole(tenantId: string, role: string) {
  const membership = form.value.tenant_memberships.find((item) => item.tenant_id === tenantId)
  if (membership && (role === 'admin' || role === 'manager' || role === 'user' || role === 'viewer')) membership.role = role
}
</script>

<template>
  <v-dialog v-model="open" max-width="720">
    <v-card class="dialog-card user-editor-dialog">
      <v-card-title>{{ editingEmail ? 'ユーザーを編集' : 'ユーザーを追加' }}</v-card-title>
      <v-card-subtitle>Googleログインと、利用できるテナントごとのロール・所属組織を登録します。</v-card-subtitle>
      <v-card-text>
        <div class="user-editor-grid">
          <label><span>メールアドレス</span><input v-model="form.email" type="email" placeholder="user@example.com" :readonly="accountLocked" /></label>
          <label><span>表示名</span><input v-model="form.name" placeholder="山田 太郎" :readonly="accountLocked" /></label>
          <small v-if="!isSystemAdmin" class="user-editor-grid__wide tenant-access-hint">{{ editingEmail ? 'メールアドレスと表示名の変更はシステム管理者のみ行えます。' : '登録済みのメールアドレスなら、このテナントへの所属だけを追加します。' }}</small>
          <div class="user-editor-field user-editor-grid__wide">
            <v-select
              v-model="form.role"
              :items="ROLE_OPTIONS"
              item-title="label"
              item-value="value"
              label="システムロール"
              density="comfortable"
              :disabled="!isSystemAdmin"
              :hint="isSystemAdmin ? undefined : 'システムロールの変更はシステム管理者のみ行えます。'"
              :persistent-hint="!isSystemAdmin"
              :hide-details="isSystemAdmin"
            ></v-select>
          </div>
          <label v-if="isSystemAdmin" class="user-editor-grid__wide"><span>Google Subject（任意）</span><input v-model="form.google_subject" placeholder="未入力なら初回ログイン時にメールで照合します" /></label>
          <section class="user-editor-grid__wide tenant-access-editor">
            <div><b>テナント権限と所属</b><small>利用を許可するテナントごとに、ロールと所属組織を選択します。組織はテナントごとに別なので、所属もテナントごとに決めます。</small></div>
            <article v-for="tenant in editableTenants" :key="tenant.id">
              <label class="tenant-access-check"><input type="checkbox" :checked="!!tenantRole(tenant.id)" @change="setTenantAccess(tenant.id, ($event.target as HTMLInputElement).checked)" /><span><b>{{ tenant.name }}</b><small>{{ tenant.id }}</small></span></label>
              <v-select
                :items="TENANT_ROLE_OPTIONS"
                :model-value="tenantRole(tenant.id) || 'viewer'"
                :disabled="!tenantRole(tenant.id)"
                aria-label="テナント内のロール"
                density="compact"
                hide-details
                @update:model-value="(value: string) => setTenantRole(tenant.id, value)"
              ></v-select>
              <v-select
                class="tenant-access-org"
                :items="tenantOrgUnitOptions(tenant.id)"
                :model-value="tenantOrgUnitId(tenant.id)"
                :disabled="!tenantRole(tenant.id)"
                item-title="label"
                item-value="id"
                label="このテナントでの所属組織"
                density="compact"
                hide-details
                @update:model-value="(value: string) => setTenantOrgUnit(tenant.id, value)"
              ></v-select>
            </article>
            <small class="tenant-access-hint">所属が未設定の利用者は、そのテナントで記録を保存できません。全部門を統括する場合は、組織マスターで種別「全社」の組織を作って選びます。</small>
          </section>
          <label v-if="isSystemAdmin" class="user-enabled-toggle"><input v-model="form.enabled" type="checkbox" /><span>有効にする</span></label>
        </div>
      </v-card-text>
      <v-card-actions><v-spacer></v-spacer><v-btn variant="text" @click="open = false">キャンセル</v-btn><v-btn color="primary" prepend-icon="mdi-content-save-outline" @click="emit('save')">保存</v-btn></v-card-actions>
    </v-card>
  </v-dialog>
</template>
