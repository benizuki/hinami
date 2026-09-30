export type ViewKey =
  | 'journal'
  | 'organization'
  | 'mining'
  | 'tenants'
  | 'orgUnits'
  | 'users'
  | 'mailRules'
  | 'aiUsage'
  | 'backups'
  | 'systemSettings'

/** サイドメニューの項目。masters はマスター系の画面をまとめた入口で、画面そのものは持たない。 */
export type NavigationKey = ViewKey | 'masters'

export interface NavigationItem<Key extends NavigationKey = ViewKey> {
  key: Key
  label: string
  icon: string
}
