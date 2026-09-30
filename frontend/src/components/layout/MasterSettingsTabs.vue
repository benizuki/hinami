<script setup lang="ts">
import type { NavigationItem, ViewKey } from './types'

defineProps<{
  items: NavigationItem[]
  currentView: ViewKey
}>()

const emit = defineEmits<{
  navigate: [view: ViewKey]
}>()
</script>

<template>
  <nav class="master-tabs" aria-label="マスタ設定">
    <div class="master-tabs__inner">
      <v-tabs
        :model-value="currentView"
        color="primary"
        density="comfortable"
        show-arrows
        @update:model-value="emit('navigate', $event as ViewKey)"
      >
        <v-tab v-for="item in items" :key="item.key" :value="item.key" :prepend-icon="item.icon">{{ item.label }}</v-tab>
      </v-tabs>
    </div>
  </nav>
</template>

<style scoped>
.master-tabs { border-bottom:1px solid var(--border-default); background:var(--surface-card); }
.master-tabs__inner { max-width:1540px; margin:0 auto; padding:0 36px; }
.master-tabs :deep(.v-tab) { font-size:13px; letter-spacing:0; text-transform:none; }
@media (max-width: 780px) {
  .master-tabs__inner { padding:0 8px; }
}
</style>
