import { ref } from 'vue'
import { getGoogleIntegrations, type GoogleIntegrationSettings } from '../../api/hinami'

// 取得できるまでは何も使わない。取得に失敗した画面でスコープを要求しないため。
const DISABLED: GoogleIntegrationSettings = { calendar: false, meet: false, gmail: false, drive: false }

const settings = ref<GoogleIntegrationSettings>({ ...DISABLED })
let loading: Promise<void> | null = null

async function load() {
  try {
    settings.value = await getGoogleIntegrations()
  } catch {
    settings.value = { ...DISABLED }
    // 次に開いたときに取り直せるよう、失敗は覚えておかない。
    loading = null
  }
}

/** 管理者が決めた、Google連携の機能ごとの有効・無効。画面間で1つを共有する。 */
export function useGoogleIntegrations() {
  function ensureLoaded(): Promise<void> {
    if (!loading) loading = load()
    return loading
  }

  function reload(): Promise<void> {
    loading = load()
    return loading
  }

  function apply(next: GoogleIntegrationSettings) {
    settings.value = next
    loading = Promise.resolve()
  }

  return { googleIntegrations: settings, ensureLoaded, reload, apply }
}
