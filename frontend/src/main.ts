import { createApp } from 'vue'
import { createVuetify } from 'vuetify'
import {
  VApp,
  VBtn,
  VCard,
  VCardActions,
  VCardSubtitle,
  VCardText,
  VCardTitle,
  VDialog,
  VIcon,
  VMenu,
  VProgressCircular,
  VProgressLinear,
  VSelect,
  VSnackbar,
  VSpacer,
  VSwitch,
  VTab,
  VTabs,
  VTextField,
  VTextarea,
} from 'vuetify/components'
import { aliases, mdi } from 'vuetify/iconsets/mdi'
import 'vuetify/styles'
import '@mdi/font/css/materialdesignicons.css'
import './styles/tokens.css'
import './styles/base.css'
import './styles/master.css'
import './styles/readability.css'
import './styles/journal.css'
import { vuetifyThemes } from './features/shell/themePalettes'

const vuetify = createVuetify({
  components: {
    VApp,
    VBtn,
    VCard,
    VCardActions,
    VCardSubtitle,
    VCardText,
    VCardTitle,
    VDialog,
    VIcon,
    VMenu,
    VProgressCircular,
    VProgressLinear,
    VSelect,
    VSnackbar,
    VSpacer,
    VSwitch,
    VTab,
    VTabs,
    VTextField,
    VTextarea,
  },
  icons: {
    defaultSet: 'mdi',
    aliases,
    sets: { mdi },
  },
  theme: {
    defaultTheme: 'hinami',
    // 単一テーマ。色は themePalettes.ts（tokens.css と対）。
    themes: vuetifyThemes(),
  },
  defaults: {
    VBtn: { rounded: 'lg', elevation: 0 },
    VCard: { rounded: 'xl', elevation: 0 },
    VTextField: { variant: 'outlined', density: 'comfortable' },
    VSelect: { variant: 'outlined', density: 'comfortable' },
  },
})

async function bootstrap() {
  const { default: App } = await import('./App.vue')
  createApp(App).use(vuetify).mount('#app')
}

void bootstrap().catch((error: unknown) => {
  console.error('Hinami bootstrap failed', error)
  const appElement = document.querySelector<HTMLElement>('#app')
  if (!appElement) return
  const message = error instanceof Error ? error.message : '不明なエラー'
  appElement.textContent = `Hinamiを起動できませんでした。${message}`
  appElement.setAttribute('role', 'alert')
})
