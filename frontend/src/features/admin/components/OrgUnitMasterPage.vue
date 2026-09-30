<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { OrgUnitKind, OrgUnitRecord } from '../../../api/hinami'

type TreeRow = {
  unit: OrgUnitRecord
  depth: number
  hasChildren: boolean
  memberCount: number
}

const props = defineProps<{
  orgUnits: OrgUnitRecord[]
  users: Array<{
    org_unit_id?: string | null
    tenant_memberships?: Array<{ tenant_id: string; org_unit_id?: string }>
  }>
  activeTenantId: string
  saving: boolean
  canManage: boolean
}>()

const emit = defineEmits<{
  reload: []
  save: [payload: { id?: string; parent_id: string; name: string; kind: OrgUnitKind; sort_order: number }]
  remove: [unit: OrgUnitRecord]
}>()

const KINDS: OrgUnitKind[] = ['全社', '部門', '課', 'チーム', 'その他']
// 種別ごとに、その下へ追加するときの既定を決めておく。
const CHILD_KIND: Record<OrgUnitKind, OrgUnitKind> = {
  全社: '部門',
  部門: '課',
  課: 'チーム',
  チーム: 'その他',
  その他: 'その他',
}

const collapsed = ref<Set<string>>(new Set())
const selectedId = ref('')
const draftParentId = ref<string | null>(null)
const form = ref<{
  parent_id: string
  name: string
  kind: OrgUnitKind
  sort_order: number
}>({
  parent_id: '',
  name: '',
  kind: '部門',
  sort_order: 0,
})

const childrenByParent = computed(() => {
  const map = new Map<string, OrgUnitRecord[]>()
  for (const unit of props.orgUnits) {
    map.set(unit.parent_id, [...(map.get(unit.parent_id) || []), unit])
  }
  for (const units of map.values()) {
    units.sort((left, right) => left.sort_order - right.sort_order || left.name.localeCompare(right.name))
  }
  return map
})

const memberCounts = computed(() => {
  const counts = new Map<string, number>()
  for (const user of props.users) {
    // 所属はテナントごとなので、このテナントでの所属だけを数える。
    const membership = user.tenant_memberships?.find((item) => item.tenant_id === props.activeTenantId)
    const key = (membership?.org_unit_id || '').trim() || (user.org_unit_id || '').trim()
    if (key) counts.set(key, (counts.get(key) || 0) + 1)
  }
  return counts
})

// 折りたたまれた組織の配下は行に含めない。
const rows = computed(() => {
  const result: TreeRow[] = []
  const walk = (parentId: string, depth: number) => {
    for (const unit of childrenByParent.value.get(parentId) || []) {
      const children = childrenByParent.value.get(unit.id) || []
      result.push({
        unit,
        depth,
        hasChildren: children.length > 0,
        memberCount: memberCounts.value.get(unit.id) || 0,
      })
      if (!collapsed.value.has(unit.id)) walk(unit.id, depth + 1)
    }
  }
  walk('', 0)
  return result
})

const selectedUnit = computed(() => props.orgUnits.find((unit) => unit.id === selectedId.value))
const editing = computed(() => Boolean(selectedUnit.value))

function descendantIds(orgUnitId: string) {
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

// 自分自身と配下を親にすると循環するため、選択肢から外す。
const parentOptions = computed(() => {
  const excluded = selectedId.value ? descendantIds(selectedId.value) : new Set<string>()
  const options: Array<{ id: string; label: string }> = []
  const walk = (parentId: string, depth: number) => {
    for (const unit of childrenByParent.value.get(parentId) || []) {
      if (!excluded.has(unit.id)) {
        options.push({ id: unit.id, label: `${'　'.repeat(depth)}${unit.name}` })
        walk(unit.id, depth + 1)
      }
    }
  }
  walk('', 0)
  return options
})

const parentSelectItems = computed(() => [
  { id: '', label: '（最上位）' },
  ...parentOptions.value,
])

const parentName = computed(() => {
  const parentId = form.value.parent_id
  return props.orgUnits.find((unit) => unit.id === parentId)?.name || ''
})

function toggle(orgUnitId: string) {
  const next = new Set(collapsed.value)
  if (next.has(orgUnitId)) next.delete(orgUnitId)
  else next.add(orgUnitId)
  collapsed.value = next
}

function selectUnit(unit: OrgUnitRecord) {
  selectedId.value = unit.id
  draftParentId.value = null
  form.value = {
    parent_id: unit.parent_id,
    name: unit.name,
    kind: unit.kind,
    sort_order: unit.sort_order,
  }
}

function startAdd(parent: OrgUnitRecord | null) {
  selectedId.value = ''
  draftParentId.value = parent?.id ?? ''
  const siblings = childrenByParent.value.get(parent?.id ?? '') || []
  form.value = {
    parent_id: parent?.id ?? '',
    name: '',
    kind: parent ? CHILD_KIND[parent.kind] : '部門',
    sort_order: siblings.length,
  }
}


function submit() {
  if (!form.value.name.trim()) return
  emit('save', { id: selectedId.value || undefined, ...form.value, name: form.value.name.trim() })
  // 続けて兄弟を追加できるよう、追加モードでは名前だけ空にする。
  if (!selectedId.value) form.value.name = ''
}

watch(() => props.orgUnits, (units) => {
  // 削除された組織を選んだままにしない。
  if (selectedId.value && !units.some((unit) => unit.id === selectedId.value)) {
    startAdd(null)
  }
})
</script>

<template>
  <section class="page org-unit-page">
    <div class="page-heading page-heading--compact">
      <div>
        <div class="eyebrow">ORGANIZATION MASTER</div>
        <h1>組織マスター</h1>
        <p>利用者の所属を表す組織です。テナントの下に部門・課・チームを階層で登録します。チームの記録と記録の見取り図は、この階層で集計します。</p>
      </div>
      <div class="heading-actions">
        <span v-if="!props.canManage" class="org-unit-readonly"><v-icon size="16">mdi-lock-outline</v-icon>閲覧のみ</span>
        <v-btn variant="outlined" prepend-icon="mdi-refresh" @click="emit('reload')">再読み込み</v-btn>
        <v-btn v-if="props.canManage" color="primary" prepend-icon="mdi-plus" @click="startAdd(null)">最上位の組織を追加</v-btn>
      </div>
    </div>

    <div class="org-unit-page__layout">
      <section class="panel org-unit-tree">
        <div class="panel__header"><div><h2>組織の階層</h2><p>行を押すと右側で編集できます。名前の左の記号で開閉します。</p></div></div>
        <p v-if="!rows.length" class="org-unit-empty">{{ props.canManage ? 'まだ組織がありません。「最上位の組織を追加」から登録してください。' : 'まだ組織がありません。管理者に登録を依頼してください。' }}</p>
        <div v-else class="org-unit-tree__rows">
          <div
            v-for="row in rows"
            :key="row.unit.id"
            class="org-unit-tree__row"
            :class="{ active: selectedId === row.unit.id }"
            :style="{ '--depth': row.depth }"
          >
            <button
              v-if="row.hasChildren"
              type="button"
              class="org-unit-tree__toggle"
              :aria-label="collapsed.has(row.unit.id) ? '配下を開く' : '配下を閉じる'"
              @click="toggle(row.unit.id)"
            >
              <v-icon size="18">{{ collapsed.has(row.unit.id) ? 'mdi-chevron-right' : 'mdi-chevron-down' }}</v-icon>
            </button>
            <span v-else class="org-unit-tree__leaf"></span>
            <button type="button" class="org-unit-tree__label" @click="selectUnit(row.unit)">
              <b>{{ row.unit.name }}</b>
              <em>{{ row.unit.kind }}</em>
              <small v-if="row.memberCount">所属 {{ row.memberCount }}名</small>
            </button>
            <div v-if="props.canManage" class="org-unit-tree__actions">
              <button type="button" aria-label="この組織の下に追加" @click="startAdd(row.unit)"><v-icon size="17">mdi-plus</v-icon></button>
              <button type="button" aria-label="削除" @click="emit('remove', row.unit)"><v-icon size="17">mdi-trash-can-outline</v-icon></button>
            </div>
          </div>
        </div>
      </section>

      <aside class="panel org-unit-editor">
        <div class="panel__header">
          <div>
            <h2>{{ !props.canManage ? '組織の詳細' : editing ? '組織を編集' : '組織を追加' }}</h2>
            <p v-if="!props.canManage">変更できるのは管理者だけです。所属の変更はユーザー管理から行います。</p>
            <p v-else-if="!editing && parentName">{{ parentName }}の下に追加します</p>
            <p v-else-if="!editing">最上位の組織として追加します</p>
            <p v-else>所属している利用者の設定は変わりません</p>
          </div>
        </div>
        <v-text-field v-model="form.name" label="名称" placeholder="例：〇〇部、△△チーム" density="comfortable" hide-details :disabled="!props.canManage"></v-text-field>
        <v-select v-model="form.kind" :items="KINDS" label="種別" density="comfortable" hide-details :disabled="!props.canManage"></v-select>
        <v-select
          v-model="form.parent_id"
          :items="parentSelectItems"
          item-title="label"
          item-value="id"
          label="上位の組織"
          density="comfortable"
          :disabled="!props.canManage"
          hint="ここを変えると組織を別の階層へ移動できます。自分自身と配下は選べません。"
          persistent-hint
        ></v-select>
        <v-text-field
          v-model.number="form.sort_order"
          type="number"
          min="0"
          label="並び順"
          density="comfortable"
          :disabled="!props.canManage"
          hint="同じ階層の中での表示順です。"
          persistent-hint
        ></v-text-field>
        <div v-if="props.canManage" class="org-unit-editor__actions">
          <v-btn v-if="editing" variant="text" @click="startAdd(null)">新規追加に切り替える</v-btn>
          <v-spacer></v-spacer>
          <v-btn color="primary" :loading="saving" :disabled="!form.name.trim()" @click="submit">{{ editing ? '更新' : '追加' }}</v-btn>
        </div>
        <p v-if="props.canManage" class="org-unit-editor__note">
          <v-icon size="16">mdi-information-outline</v-icon>
          配下の組織がある場合や、記録が紐づいている場合は削除できません。
        </p>
      </aside>
    </div>
  </section>
</template>
