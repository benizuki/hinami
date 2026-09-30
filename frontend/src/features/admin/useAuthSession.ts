import { computed, nextTick, ref } from 'vue'
import {
  deleteUser,
  getActiveTenantId,
  getAuthConfig,
  getCurrentUser,
  getTenants,
  deleteOrgUnit,
  getOrgUnits,
  getUsers,
  saveOrgUnit,
  loginWithDemoEmail,
  loginWithGoogleCredential,
  logout,
  saveTenant,
  saveUser,
  setActiveTenantId,
  type AuthConfig,
  type AuthUser,
  type TenantRecord,
  type UserMasterEntry,
  type OrgUnitKind,
  type OrgUnitRecord,
} from '../../api/hinami'
import type { NavigationItem, NavigationKey, ViewKey } from '../../components/layout/types'
import { useAppShell } from '../shell/useAppShell'
import { useNotifier } from '../shell/useNotifier'

declare global {
  interface Window {
    google?: {
      accounts?: {
        id?: {
          initialize: (config: { client_id: string; callback: (response: { credential?: string }) => void; ux_mode?: string }) => void
          renderButton: (element: HTMLElement, options: Record<string, unknown>) => void
        }
        oauth2?: {
          initTokenClient: (config: {
            client_id: string
            scope: string
            callback: (response: { access_token?: string; error?: string; error_description?: string }) => void
            error_callback?: (error: { type?: string }) => void
          }) => {
            requestAccessToken: (options?: { prompt?: string }) => void
          }
        }
      }
    }
  }
}

/**
 * Google sign-in, the active tenant, and the tenant/user master screens.
 * 各画面はテナントごとのデータを自分で読み込む。テナントを切り替えたら
 * App.vue が activeTenantId をキーに画面を作り直し、読み込み直させる。
 */
function createAuthSession() {
  const { notify } = useNotifier()
  const { navItems, mastersNavItem, isMasterView, lastMasterView, goTo, onEnterView } = useAppShell()

  const authConfig = ref<AuthConfig>({ google_oauth_enabled: false, google_client_id: '', demo_login_enabled: false })
  const authReady = ref(false)
  const authLoading = ref(false)
  const authError = ref('')
  const currentUser = ref<AuthUser | null>(null)
  const googleButton = ref<HTMLElement | null>(null)
  const users = ref<UserMasterEntry[]>([])
  const tenants = ref<TenantRecord[]>([])
  const orgUnits = ref<OrgUnitRecord[]>([])
  // 所属はテナントごとに決めるため、ユーザー編集では他テナントの組織も要る。
  const tenantOrgUnits = ref<Record<string, OrgUnitRecord[]>>({})
  const activeTenantId = ref(getActiveTenantId())
  const tenantSwitching = ref(false)
  const tenantEditorOpen = ref(false)
  const editingTenantId = ref('')
  const tenantForm = ref<TenantRecord>({ id: '', name: '', description: '', enabled: true })

  function generateTenantId() {
    let id = ''
    do {
      id = crypto.randomUUID().replaceAll('-', '').slice(0, 8)
    } while (tenants.value.some((tenant) => tenant.id === id))
    return id
  }

  const userEditorOpen = ref(false)
  const editingUserEmail = ref('')
  const userForm = ref<UserMasterEntry>({ email: '', name: '', department: '', role: 'none', tenant_memberships: [], enabled: true, google_subject: '' })

  const userInitials = computed(() => {
    const source = currentUser.value?.name || currentUser.value?.email || 'HN'
    return source.split(/\s+/).map((part) => part[0]).join('').slice(0, 2).toUpperCase()
  })

  const currentTenant = computed(() => tenants.value.find((tenant) => tenant.id === activeTenantId.value))
  // Googleログインとお試しログインのどちらも、ログインして権限で絞る。
  const loginRequired = computed(() => authConfig.value.google_oauth_enabled || Boolean(authConfig.value.demo_login_enabled))
  const currentTenantRole = computed(() => {
    if (!loginRequired.value) return 'admin'
    if (currentUser.value?.role === 'admin') return 'admin'
    return currentUser.value?.tenant_memberships.find((membership) => membership.tenant_id === activeTenantId.value)?.role ?? 'viewer'
  })
  const canEdit = computed(() => currentTenantRole.value !== 'viewer')
  const isSystemAdmin = computed(() => (
    !loginRequired.value || currentUser.value?.role === 'admin'
  ))
  // システムviewerは全テナントの管理画面を閲覧できる。更新はバックエンドが拒否する。
  const isSystemViewer = computed(() => currentUser.value?.role === 'viewer')
  // ユーザー管理はシステム管理者に加えて、そのテナントのadminも使える。
  // 権限の範囲はバックエンドが自テナント内に限定する。
  const canManageUsers = computed(() => isSystemAdmin.value || currentTenantRole.value === 'admin')
  const canViewUsers = computed(() => canManageUsers.value || isSystemViewer.value)
  // 組織の階層はテナント管理者が管理する。バックエンドの判定（テナントロール）と揃える。
  const canManageOrgUnits = computed(() => currentTenantRole.value === 'admin')
  const canManageTenantAssignments = computed(() => isSystemAdmin.value)
  function canOpenView(view: ViewKey) {
    if (view === 'users') return canViewUsers.value
    if (view === 'tenants') return isSystemAdmin.value || isSystemViewer.value
    if (view === 'backups') return isSystemAdmin.value
    if (view === 'systemSettings') return isSystemAdmin.value
    return true
  }
  /** 「マスタ設定」のタブ。開ける画面だけを並べる。 */
  const visibleMasterItems = computed(() => navItems.filter((item) => isMasterView(item.key) && canOpenView(item.key)))
  /** サイドメニュー。マスター系の画面は、最初の1つの位置に「マスタ設定」としてまとめる。 */
  const visibleNavItems = computed(() => {
    const items: NavigationItem<NavigationKey>[] = []
    for (const item of navItems) {
      if (isMasterView(item.key)) {
        if (item.key === visibleMasterItems.value[0]?.key) items.push(mastersNavItem)
        continue
      }
      if (canOpenView(item.key)) items.push(item)
    }
    return items
  })

  function navigate(key: NavigationKey) {
    if (key !== 'masters') {
      goTo(key)
      return
    }
    const remembered = visibleMasterItems.value.find((item) => item.key === lastMasterView.value)
    const target = remembered ?? visibleMasterItems.value[0]
    if (target) goTo(target.key)
  }
  const appAccessible = computed(() => authReady.value && (!loginRequired.value || !!currentUser.value))

  function loadGoogleScript() {
    return new Promise<void>((resolve, reject) => {
      if (window.google?.accounts?.id) {
        resolve()
        return
      }
      const existing = document.querySelector<HTMLScriptElement>('script[src="https://accounts.google.com/gsi/client"]')
      if (existing) {
        existing.addEventListener('load', () => resolve(), { once: true })
        existing.addEventListener('error', () => reject(new Error('Googleログインスクリプトを読み込めませんでした。')), { once: true })
        return
      }
      const script = document.createElement('script')
      script.src = 'https://accounts.google.com/gsi/client'
      script.async = true
      script.defer = true
      script.onload = () => resolve()
      script.onerror = () => reject(new Error('Googleログインスクリプトを読み込めませんでした。'))
      document.head.appendChild(script)
    })
  }

  async function initializeGoogleButton() {
    if (!authConfig.value.google_oauth_enabled || !authConfig.value.google_client_id || currentUser.value) return
    await nextTick()
    if (!googleButton.value) return
    await loadGoogleScript()
    googleButton.value.innerHTML = ''
    window.google?.accounts?.id?.initialize({
      client_id: authConfig.value.google_client_id,
      callback: (response) => void handleGoogleCredential(response.credential || ''),
      ux_mode: 'popup',
    })
    window.google?.accounts?.id?.renderButton(googleButton.value, {
      theme: 'outline',
      size: 'large',
      // 狭い画面ではカードの内幅に合わせる。GISの下限は200px。
      width: Math.max(200, Math.min(320, googleButton.value.clientWidth || 320)),
      text: 'signin_with',
      locale: 'ja',
    })
  }

  async function handleGoogleCredential(credential: string) {
    if (!credential) return
    authLoading.value = true
    authError.value = ''
    try {
      const result = await loginWithGoogleCredential(credential)
      currentUser.value = result.user
      await initializeTenantContext()
    } catch (error) {
      authError.value = error instanceof Error ? error.message : 'Googleログインに失敗しました。'
    } finally {
      authLoading.value = false
      if (!currentUser.value) void initializeGoogleButton()
    }
  }

  async function requestGoogleAccessToken(scope: string) {
    if (!authConfig.value.google_oauth_enabled || !authConfig.value.google_client_id || !currentUser.value) {
      throw new Error('Google連携にはGoogleログインが必要です。')
    }
    await loadGoogleScript()
    return await new Promise<string>((resolve, reject) => {
      const oauth2 = window.google?.accounts?.oauth2
      if (!oauth2) {
        reject(new Error('Googleの認可機能を読み込めませんでした。'))
        return
      }
      const client = oauth2.initTokenClient({
        client_id: authConfig.value.google_client_id,
        scope,
        callback: (response) => {
          if (response.access_token) resolve(response.access_token)
          else reject(new Error(response.error_description || response.error || 'Googleサービスの利用を許可できませんでした。'))
        },
        error_callback: () => reject(new Error('Googleサービスの認可画面を完了できませんでした。')),
      })
      client.requestAccessToken({ prompt: '' })
    })
  }

  async function initializeAuth() {
    authLoading.value = true
    try {
      authConfig.value = await getAuthConfig()
      if (!loginRequired.value) {
        currentUser.value = null
        await initializeTenantContext()
        return
      }
      try {
        currentUser.value = await getCurrentUser()
        await initializeTenantContext()
        return
      } catch {
        await logout()
        currentUser.value = null
      }
    } catch (error) {
      authError.value = error instanceof Error ? error.message : '認証初期化に失敗しました。'
    } finally {
      authReady.value = true
      authLoading.value = false
      if (authConfig.value.google_oauth_enabled && !currentUser.value) void initializeGoogleButton()
    }
  }

  async function handleDemoLogin(email: string) {
    authLoading.value = true
    authError.value = ''
    try {
      const result = await loginWithDemoEmail(email)
      currentUser.value = result.user
      await initializeTenantContext()
    } catch (error) {
      authError.value = error instanceof Error ? error.message : 'ログインに失敗しました。'
    } finally {
      authLoading.value = false
    }
  }

  async function handleLogout() {
    await logout()
    currentUser.value = null
    goTo('journal')
    await initializeGoogleButton()
  }

  async function loadTenants() {
    try {
      tenants.value = await getTenants()
    } catch (error) {
      notify(error instanceof Error ? error.message : 'テナント一覧を取得できませんでした')
    }
  }

  async function initializeTenantContext() {
    await loadTenants()
    const available = tenants.value.filter((tenant) => tenant.enabled)
    const preferred = available.find((tenant) => tenant.id === activeTenantId.value) ?? available[0]
    if (!preferred) throw new Error('利用可能なテナントがありません。管理者へお問い合わせください。')
    activeTenantId.value = preferred.id
    setActiveTenantId(preferred.id)
  }

  async function switchTenant(tenantId: string) {
    if (tenantId === activeTenantId.value || tenantSwitching.value) return
    const tenant = tenants.value.find((item) => item.id === tenantId && item.enabled)
    if (!tenant) return
    tenantSwitching.value = true
    try {
      activeTenantId.value = tenant.id
      setActiveTenantId(tenant.id)
      // 所属組織はテナントごとなので、切り替えたら自分の所属も取り直す。
      try {
        currentUser.value = await getCurrentUser()
      } catch {
        // 取得できない場合は前のまま進み、各画面の所属未設定表示に任せる。
      }
      goTo('journal')
      notify(`「${tenant.name}」へ切り替えました`)
    } catch (error) {
      notify(error instanceof Error ? error.message : 'テナントを切り替えられませんでした')
    } finally {
      tenantSwitching.value = false
    }
  }

  async function loadOrgUnits() {
    try {
      orgUnits.value = await getOrgUnits()
    } catch (error) {
      notify(error instanceof Error ? error.message : '組織マスターを取得できませんでした')
    }
  }

  const orgUnitSaving = ref(false)

  async function submitOrgUnit(payload: {
    id?: string
    parent_id: string
    name: string
    kind: OrgUnitKind
    sort_order: number
  }) {
    orgUnitSaving.value = true
    try {
      await saveOrgUnit(payload)
      await loadOrgUnits()
      notify(payload.id ? '組織を更新しました' : '組織を追加しました')
    } catch (error) {
      notify(error instanceof Error ? error.message : '組織を保存できませんでした')
    } finally {
      orgUnitSaving.value = false
    }
  }

  async function removeOrgUnit(unit: OrgUnitRecord) {
    if (!window.confirm(`${unit.name}を削除しますか？`)) return
    try {
      await deleteOrgUnit(unit.id)
      await loadOrgUnits()
      notify('組織を削除しました')
    } catch (error) {
      notify(error instanceof Error ? error.message : '組織を削除できませんでした')
    }
  }

  async function loadUsers() {
    if (!canViewUsers.value) return
    try {
      users.value = await getUsers()
    } catch (error) {
      notify(error instanceof Error ? error.message : 'ユーザー一覧を取得できませんでした')
    }
  }

  async function loadTenantOrgUnits() {
    const targets = isSystemAdmin.value ? tenants.value.map((tenant) => tenant.id) : [activeTenantId.value]
    const loaded: Record<string, OrgUnitRecord[]> = {}
    await Promise.all(targets.map(async (tenantId) => {
      try {
        loaded[tenantId] = await getOrgUnits(tenantId)
      } catch {
        // 取得できないテナントは選択肢なしにとどめ、他テナントの設定は続けられるようにする。
        loaded[tenantId] = []
      }
    }))
    tenantOrgUnits.value = loaded
  }

  function openNewUser() {
    editingUserEmail.value = ''
    userForm.value = {
      email: '',
      name: '',
      department: '',
      org_unit_id: '',
      // 追加する利用者は既定でシステム権限なし。全体の管理・閲覧が要る場合だけ
      // システム管理者が admin / viewer を選ぶ。
      role: 'none',
      tenant_memberships: [{ tenant_id: activeTenantId.value, role: 'user', org_unit_id: '' }],
      enabled: true,
      google_subject: '',
    }
    userEditorOpen.value = true
    void loadTenantOrgUnits()
  }

  function editUser(user: UserMasterEntry) {
    editingUserEmail.value = user.email
    userForm.value = {
      ...user,
      tenant_memberships: user.tenant_memberships.map((membership) => ({ ...membership })),
    }
    userEditorOpen.value = true
    void loadTenantOrgUnits()
  }

  function openNewTenant() {
    editingTenantId.value = ''
    tenantForm.value = {
      id: generateTenantId(),
      name: '',
      description: '',
      enabled: true,
    }
    tenantEditorOpen.value = true
  }

  function editTenant(tenant: TenantRecord) {
    editingTenantId.value = tenant.id
    tenantForm.value = { ...tenant }
    tenantEditorOpen.value = true
  }

  async function submitTenant() {
    try {
      await saveTenant(tenantForm.value, editingTenantId.value || undefined)
      tenantEditorOpen.value = false
      await loadTenants()
      notify('テナントを保存しました')
    } catch (error) {
      notify(error instanceof Error ? error.message : 'テナントを保存できませんでした')
    }
  }

  async function submitUser() {
    try {
      await saveUser(userForm.value, editingUserEmail.value || undefined)
      userEditorOpen.value = false
      await loadUsers()
      notify('ユーザーを保存しました')
    } catch (error) {
      notify(error instanceof Error ? error.message : 'ユーザーを保存できませんでした')
    }
  }

  async function removeUser(user: UserMasterEntry) {
    // テナント管理者の操作は、そのテナントから外すだけ。他テナントでの利用は残る。
    const message = isSystemAdmin.value
      ? `「${user.email}」を削除しますか？`
      : `「${user.email}」を${currentTenant.value?.name || activeTenantId.value}から外しますか？他のテナントに所属が残っていればアカウントは残ります。`
    if (!window.confirm(message)) return
    try {
      await deleteUser(user.email)
      await loadUsers()
      notify(isSystemAdmin.value ? 'ユーザーを削除しました' : 'ユーザーをテナントから外しました')
    } catch (error) {
      notify(error instanceof Error ? error.message : 'ユーザーを削除できませんでした')
    }
  }
  onEnterView('users', () => {
    void loadUsers()
    void loadOrgUnits()
  })
  onEnterView('orgUnits', () => {
    void loadOrgUnits()
    void loadUsers()
  })
  onEnterView('tenants', () => {
    void loadTenants()
    void loadUsers()
  })

  return {
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
    canEdit,
    canManageTenantAssignments,
    canManageOrgUnits,
    canManageUsers,
    canViewUsers,
    isSystemAdmin,
    isSystemViewer,
    visibleNavItems,
    visibleMasterItems,
    navigate,
    appAccessible,
    initializeAuth,
    handleLogout,
    handleDemoLogin,
    loginRequired,
    requestGoogleAccessToken,
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
  }
}

export type AuthSession = ReturnType<typeof createAuthSession>

let session: AuthSession | null = null

export function useAuthSession(): AuthSession {
  if (!session) session = createAuthSession()
  return session
}
