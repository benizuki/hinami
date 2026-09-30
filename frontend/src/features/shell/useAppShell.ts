import { computed, ref } from 'vue'
import type { NavigationItem, NavigationKey, ViewKey } from '../../components/layout/types'

const navItems: NavigationItem[] = [
  { key: 'journal', label: '日々の記録', icon: 'mdi-calendar-check-outline' },
  { key: 'organization', label: 'チームの記録', icon: 'mdi-account-group-outline' },
  { key: 'mining', label: '記録の見取り図', icon: 'mdi-file-search-outline' },
  { key: 'tenants', label: 'テナント管理', icon: 'mdi-office-building-cog-outline' },
  { key: 'orgUnits', label: '組織マスター', icon: 'mdi-sitemap-outline' },
  { key: 'users', label: 'ユーザー管理', icon: 'mdi-account-cog-outline' },
  { key: 'mailRules', label: 'メール分類マスター', icon: 'mdi-email-search-outline' },
  { key: 'aiUsage', label: 'AI利用状況', icon: 'mdi-chart-timeline-variant' },
  { key: 'backups', label: 'SQLiteバックアップ', icon: 'mdi-database-export-outline' },
  { key: 'systemSettings', label: 'システム設定', icon: 'mdi-cog-outline' },
]

/** サイドメニューでは「マスタ設定」1つにまとめ、画面上部のタブで切り替える画面。 */
const MASTER_VIEWS: readonly ViewKey[] = ['tenants', 'orgUnits', 'users', 'mailRules']
const mastersNavItem: NavigationItem<'masters'> = { key: 'masters', label: 'マスタ設定', icon: 'mdi-folder-cog-outline' }

function isMasterView(view: ViewKey) {
  return MASTER_VIEWS.includes(view)
}

function createAppShell() {
  const currentView = ref<ViewKey>('journal')
  const mobileNav = ref(false)
  const sidebarHidden = ref(false)
  // 「マスタ設定」を開き直したとき、前回見ていたタブへ戻す。
  const lastMasterView = ref<ViewKey | null>(null)

  /**
   * Side effects each domain wants to run when its view opens (loading users,
   * syncing sessions, …). Registered by the owning composable so that `goTo`
   * does not have to know about every feature.
   */
  const enterHooks = new Map<ViewKey, (() => void)[]>()

  function onEnterView(view: ViewKey, handler: () => void) {
    const handlers = enterHooks.get(view) ?? []
    handlers.push(handler)
    enterHooks.set(view, handlers)
  }

  function goTo(view: ViewKey) {
    currentView.value = view
    if (isMasterView(view)) lastMasterView.value = view
    mobileNav.value = false
    enterHooks.get(view)?.forEach((handler) => handler())
  }

  function setSidebarHidden(hidden: boolean) {
    sidebarHidden.value = hidden
  }

  /** サイドメニューで強調する項目。マスター系の画面では「マスタ設定」を光らせる。 */
  const activeNavKey = computed<NavigationKey>(() => (isMasterView(currentView.value) ? 'masters' : currentView.value))
  const inMasterSettings = computed(() => isMasterView(currentView.value))
  const pageTitle = computed(() => {
    const label = navItems.find((item) => item.key === currentView.value)?.label ?? ''
    return inMasterSettings.value ? `${mastersNavItem.label} / ${label}` : label
  })

  return {
    navItems,
    mastersNavItem,
    isMasterView,
    currentView,
    activeNavKey,
    inMasterSettings,
    lastMasterView,
    mobileNav,
    sidebarHidden,
    pageTitle,
    goTo,
    onEnterView,
    setSidebarHidden,
  }
}

export type AppShell = ReturnType<typeof createAppShell>

let shell: AppShell | null = null

/** Navigation and chrome state shared by the app shell and every feature. */
export function useAppShell(): AppShell {
  if (!shell) shell = createAppShell()
  return shell
}
