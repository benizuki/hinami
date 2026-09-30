import { ref } from 'vue'

// 画面下に出す一行の通知。どの画面からでも同じ1つを使う。
const snackbar = ref(false)
const snackbarMessage = ref('')

function notify(message: string) {
  snackbarMessage.value = message
  snackbar.value = true
}

export function useNotifier() {
  return { snackbar, snackbarMessage, notify }
}
