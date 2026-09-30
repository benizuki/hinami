<script setup lang="ts">
import type { AuthRole, AuthUser } from '../../api/hinami'
defineProps<{
  sidebarHidden: boolean
  pageTitle: string
  currentUser: AuthUser | null
  tenantRole: AuthRole
  userInitials: string
}>()

const emit = defineEmits<{
  openMobile: []
  showSidebar: []
  openSpeechSettings: []
  logout: []
}>()
</script>

<template>
  <header class="topbar">
    <button class="mobile-menu" @click="emit('openMobile')"><v-icon>mdi-menu</v-icon></button>
    <button
      v-if="sidebarHidden"
      class="sidebar-show-button"
      title="サイドメニューを展開"
      aria-label="サイドメニューを展開"
      @click="emit('showSidebar')"
    >
      <v-icon size="20">mdi-menu-open</v-icon>
    </button>
    <div class="breadcrumbs">
      <span>Hinami</span>
      <v-icon size="15">mdi-chevron-right</v-icon>
      <strong>{{ pageTitle }}</strong>
    </div>

    <div class="topbar__actions">
      <button class="theme-toggle" title="読み上げの設定" aria-label="読み上げの設定" @click="emit('openSpeechSettings')">
        <v-icon size="18">mdi-account-voice</v-icon>
      </button>
      <div class="topbar-user">
        <div class="avatar topbar-user__avatar" :title="currentUser?.name || 'ローカル利用'">
          {{ currentUser ? userInitials : 'HN' }}
        </div>
        <div class="topbar-user__details">
          <strong>{{ currentUser?.name || 'ローカル利用' }}</strong>
          <span>{{ currentUser ? `${tenantRole}｜${currentUser.department || '所属未設定'}` : 'ログインなし（開発モード）' }}</span>
        </div>
        <button
          v-if="currentUser"
          class="topbar-user__logout"
          title="ログアウト"
          aria-label="ログアウト"
          @click="emit('logout')"
        >
          <v-icon size="18">mdi-logout</v-icon>
        </button>
        <v-icon v-else class="topbar-user__more" size="18">mdi-dots-horizontal</v-icon>
      </div>
    </div>
  </header>
</template>
