<script setup lang="ts">
import type { AuthRole, TenantRecord } from '../../api/hinami'
import { useAppMode } from '../../features/shell/useAppMode'
import type { NavigationItem, NavigationKey } from './types'

const { labels } = useAppMode()

defineProps<{
  mobileOpen: boolean
  hidden: boolean
  tenantName: string
  tenantRole: AuthRole
  orgUnitCount: number
  tenants: TenantRecord[]
  activeTenantId: string
  tenantSwitching: boolean
  navigationItems: NavigationItem<NavigationKey>[]
  /** 強調する項目。マスター系の画面を開いている間は masters になる。 */
  activeKey: NavigationKey
}>()

/* 机の挿絵のノートの上に舞う花びら。位置・大きさ・周期を散らして、揃って落ちないようにする。 */
const PETALS = [
  { x: '30%', s: '8px', d: '12s', delay: '0s', sway: '-12px' },
  { x: '38%', s: '6px', d: '15s', delay: '-4s', sway: '10px' },
  { x: '46%', s: '7px', d: '13s', delay: '-8s', sway: '-9px' },
  { x: '54%', s: '5px', d: '16s', delay: '-11s', sway: '12px' },
  { x: '42%', s: '7px', d: '14s', delay: '-2s', sway: '-14px' },
]

const emit = defineEmits<{
  toggleHidden: [hidden: boolean]
  selectTenant: [tenantId: string]
  navigate: [key: NavigationKey]
  closeMobile: []
}>()

function selectTenant(tenantId: string) {
  emit('selectTenant', tenantId)
}
</script>

<template>
  <aside class="sidebar" :class="{ 'sidebar--open': mobileOpen, 'sidebar--hidden': hidden }">
    <button
      class="sidebar-hide-button"
      :title="hidden ? 'サイドメニューを展開' : 'サイドメニューを折りたたむ'"
      :aria-label="hidden ? 'サイドメニューを展開' : 'サイドメニューを折りたたむ'"
      @click="emit('toggleHidden', !hidden)"
    >
      <v-icon size="19">{{ hidden ? 'mdi-chevron-right' : 'mdi-chevron-left' }}</v-icon>
    </button>

    <div class="brand">
      <div class="brand__mark"><span></span><span></span><span></span></div>
      <div>
        <div class="brand__name">Hinami</div>
        <div class="brand__tag">{{ labels.sidebarTag }}</div>
      </div>
    </div>

    <div class="workspace-label">WORKSPACE</div>
    <div class="workspace-switcher" :title="hidden ? tenantName || 'テナントを選択' : undefined">
      <span class="workspace-switcher__icon"><v-icon size="18">mdi-office-building-outline</v-icon></span>
      <span>
        <strong>{{ tenantName || 'テナントを選択' }}</strong>
        <small>{{ tenantRole }}｜{{ orgUnitCount }}組織</small>
      </span>
      <v-select
        class="workspace-switcher__select"
        :model-value="activeTenantId"
        :items="tenants.filter((item) => item.enabled)"
        item-title="name"
        item-value="id"
        variant="plain"
        density="compact"
        hide-details
        menu-icon=""
        :disabled="tenantSwitching"
        aria-label="利用するテナント"
        @update:model-value="selectTenant"
      ></v-select>
      <v-icon size="18">mdi-chevron-down</v-icon>
    </div>

    <nav class="main-nav">
      <button
        v-for="item in navigationItems"
        :key="item.key"
        :class="{ active: activeKey === item.key }"
        :title="hidden ? item.label : undefined"
        @click="emit('navigate', item.key)"
      >
        <v-icon size="21">{{ item.icon }}</v-icon>
        <span>{{ item.label }}</span>
      </button>
    </nav>

    <div class="sidebar-petals" aria-hidden="true">
      <i v-for="(petal, index) in PETALS" :key="index" :style="{ '--x': petal.x, '--s': petal.s, '--d': petal.d, '--delay': petal.delay, '--sway': petal.sway }"></i>
    </div>
  </aside>
  <div v-if="mobileOpen" class="nav-backdrop" @click="emit('closeMobile')"></div>
</template>
