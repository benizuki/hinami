/** Vuetifyテーマの色。tokens.css と対になる単一の配色（ログイン画面と揃えた和紙・墨・苔色）。片方だけ変えない。 */
export function vuetifyThemes() {
  return {
    hinami: {
      dark: false,
      colors: {
        primary: '#4a3b2e',
        secondary: '#4d6f45',
        accent: '#f1a55b',
        background: '#f7f2e8',
        surface: '#fffdf8',
        error: '#bd5146',
        success: '#4d6f45',
      },
    },
  }
}
