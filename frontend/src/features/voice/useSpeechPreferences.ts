import { ref } from 'vue'

// 読み上げの好みを保存した回数。読み上げのキャッシュはこれを含めて引き、古い声を再生しない。
const preferencesVersion = ref(0)

export function useSpeechPreferences() {
  function markPreferencesChanged() {
    preferencesVersion.value += 1
  }

  return { preferencesVersion, markPreferencesChanged }
}
