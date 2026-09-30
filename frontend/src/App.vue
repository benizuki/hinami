<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import AuthGate from './components/auth/AuthGate.vue'
import AppSidebar from './components/layout/AppSidebar.vue'
import AppTopbar from './components/layout/AppTopbar.vue'
import MasterSettingsTabs from './components/layout/MasterSettingsTabs.vue'
import AiUsagePage from './features/admin/components/AiUsagePage.vue'
import BackupManagementPage from './features/admin/components/BackupManagementPage.vue'
import MailRuleMasterPage from './features/admin/components/MailRuleMasterPage.vue'
import OrgUnitMasterPage from './features/admin/components/OrgUnitMasterPage.vue'
import SystemSettingsPage from './features/admin/components/SystemSettingsPage.vue'
import TenantEditorDialog from './features/admin/components/TenantEditorDialog.vue'
import TenantManagementPage from './features/admin/components/TenantManagementPage.vue'
import UserEditorDialog from './features/admin/components/UserEditorDialog.vue'
import UserManagementPage from './features/admin/components/UserManagementPage.vue'
import { useAuthSession } from './features/admin/useAuthSession'
import OrganizationJournalPage from './features/journals/OrganizationJournalPage.vue'
import WorkJournalPage from './features/journals/WorkJournalPage.vue'
import WorkMiningPage from './features/journals/WorkMiningPage.vue'
import SpeechPreferencesDialog from './features/voice/SpeechPreferencesDialog.vue'
import { useAppShell } from './features/shell/useAppShell'
import { useAppMode } from './features/shell/useAppMode'
import { useNotifier } from './features/shell/useNotifier'

const { snackbar, snackbarMessage } = useNotifier()
const speechSettingsOpen = ref(false)
const { currentView, activeNavKey, inMasterSettings, mobileNav, sidebarHidden, pageTitle, goTo, setSidebarHidden } = useAppShell()

const {
  authConfig,
  authReady,
  authLoading,
  authError,
  currentUser,
  googleButton,
  users,
  tenants,
  orgUnits,
  tenantOrgUnits,
  activeTenantId,
  tenantSwitching,
  tenantEditorOpen,
  editingTenantId,
  tenantForm,
  userEditorOpen,
  editingUserEmail,
  userForm,
  userInitials,
  currentTenant,
  currentTenantRole,
  canManageOrgUnits,
  canManageUsers,
  isSystemAdmin,
  visibleNavItems,
  visibleMasterItems,
  navigate,
  appAccessible,
  initializeAuth,
  handleLogout,
  loadTenants,
  loadUsers,
  loadOrgUnits,
  orgUnitSaving,
  submitOrgUnit,
  removeOrgUnit,
  switchTenant,
  openNewUser,
  editUser,
  openNewTenant,
  editTenant,
  submitTenant,
  submitUser,
  removeUser,
} = useAuthSession()

const { ensureLoaded: ensureAppMode } = useAppMode()

// サイドバーの組織数を出すため、使える状態になったら・テナントを切り替えたら組織を読み直す。
watch([appAccessible, activeTenantId], ([accessible]) => {
  if (accessible) void loadOrgUnits()
})
// 言葉づかいを決める動作モードは、使える状態になったら読む。
watch(appAccessible, (accessible) => {
  if (accessible) void ensureAppMode()
}, { immediate: true })

onMounted(() => {
  void initializeAuth()
})
</script>

<template>
  <v-app>
    <AuthGate
      v-if="authReady && authConfig.google_oauth_enabled && !currentUser"
      :button-ready="Boolean(googleButton)"
      :error="authError"
      :loading="authLoading"
    >
      <div ref="googleButton" class="google-login-button"></div>
    </AuthGate>
    <template v-if="appAccessible">
      <AppSidebar
        :mobile-open="mobileNav"
        :hidden="sidebarHidden"
        :tenant-name="currentTenant?.name || ''"
        :tenant-role="currentTenantRole"
        :org-unit-count="orgUnits.length"
        :tenants="tenants"
        :active-tenant-id="activeTenantId"
        :tenant-switching="tenantSwitching"
        :navigation-items="visibleNavItems"
        :active-key="activeNavKey"
        @toggle-hidden="setSidebarHidden"
        @select-tenant="switchTenant"
        @navigate="navigate"
        @close-mobile="mobileNav = false"
      />

      <main class="main-shell" :class="{ 'main-shell--sidebar-hidden': sidebarHidden }">
        <AppTopbar
          :sidebar-hidden="sidebarHidden"
          :page-title="pageTitle"
          :current-user="currentUser"
          :tenant-role="currentTenantRole"
          :user-initials="userInitials"
          @open-mobile="mobileNav = true"
          @show-sidebar="setSidebarHidden(false)"
          @open-speech-settings="speechSettingsOpen = true"
          @logout="handleLogout"
        />

        <MasterSettingsTabs v-if="inMasterSettings" :items="visibleMasterItems" :current-view="currentView" @navigate="goTo" />

        <!-- 各画面はテナントごとのデータを自分で読み込む。キーにテナントを含め、切り替えたら作り直す。 -->
        <WorkJournalPage v-if="currentView === 'journal'" :key="`journal-${activeTenantId}`" />
        <OrganizationJournalPage v-else-if="currentView === 'organization'" :key="`organization-${activeTenantId}`" />
        <WorkMiningPage v-else-if="currentView === 'mining'" :key="`mining-${activeTenantId}`" />

        <TenantManagementPage
          v-else-if="currentView === 'tenants'"
          :tenants="tenants"
          :users="users"
          :active-tenant-id="activeTenantId"
          :can-manage="isSystemAdmin"
          @reload="loadTenants"
          @add="openNewTenant"
          @edit="editTenant"
        />

        <OrgUnitMasterPage
          v-else-if="currentView === 'orgUnits'"
          :org-units="orgUnits"
          :users="users"
          :active-tenant-id="activeTenantId"
          :saving="orgUnitSaving"
          :can-manage="canManageOrgUnits"
          @reload="loadOrgUnits"
          @save="submitOrgUnit"
          @remove="removeOrgUnit"
        />

        <MailRuleMasterPage
          v-else-if="currentView === 'mailRules'"
          :key="`mail-rules-${activeTenantId}`"
          :can-manage="canManageOrgUnits"
        />

        <UserManagementPage
          v-else-if="currentView === 'users'"
          :users="users"
          :tenants="tenants"
          :org-units="orgUnits"
          :active-tenant-id="activeTenantId"
          :current-user-email="currentUser?.email"
          :is-system-admin="isSystemAdmin"
          :scoped-tenant-name="currentTenant?.name || activeTenantId"
          :can-manage="canManageUsers"
          @reload="loadUsers"
          @manage-org-units="goTo('orgUnits')"
          @add="openNewUser"
          @edit="editUser"
          @remove="removeUser"
        />

        <AiUsagePage v-else-if="currentView === 'aiUsage'" :key="`ai-usage-${activeTenantId}`" />
        <BackupManagementPage v-else-if="currentView === 'backups'" />
        <SystemSettingsPage v-else-if="currentView === 'systemSettings'" :google-oauth-enabled="authConfig.google_oauth_enabled" />
      </main>

      <UserEditorDialog
        v-model="userEditorOpen"
        :editing-email="editingUserEmail"
        :form="userForm"
        :tenants="tenants"
        :org-units="orgUnits"
        :tenant-org-units="tenantOrgUnits"
        :is-system-admin="isSystemAdmin"
        :scoped-tenant-id="activeTenantId"
        @save="submitUser"
      />

      <TenantEditorDialog
        v-model="tenantEditorOpen"
        :editing-id="editingTenantId"
        :active-tenant-id="activeTenantId"
        :form="tenantForm"
        @save="submitTenant"
      />
      <SpeechPreferencesDialog v-model="speechSettingsOpen" />
      <v-snackbar v-model="snackbar" color="primary" timeout="3000">{{ snackbarMessage }}</v-snackbar>
    </template>
  </v-app>
</template>
