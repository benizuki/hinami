import { computed, ref } from 'vue'
import { getAppMode, type AppMode } from '../../api/hinami'

/* 動作モードごとの画面の言葉。データ構造（work_items など）は変えず、見せる言葉だけを切り替える。
   日記寄りは既定。取得できるまで・取得に失敗したときも日記寄りで出す。 */
const LABELS = {
  diary: {
    sidebarTag: 'DAILY JOURNAL',
    todayItems: '今日のできごと',
    itemField: 'できごと',
    prevItem: '前のできごと',
    nextItem: '次のできごと',
    itemPicker: 'できごとの選択',
    itemsHint: 'できごとの内容と、どこまで進んだかが伝わる箇条書きです',
    itemsEmpty: '記録するできごとはありません。',
    startHint: '覚えておきたいことを、話しやすいところから教えてください。',
    memberCount: (days: number, count: number) => `${days}日分・できごと ${count}件`,
    team: {
      digestGroups: {
        progress: { label: '進んだこと', hint: 'チームで前に進んだこと' },
        ingenuity: { label: '共有したい気づき', hint: '他のメンバーにも役立ちそうな気づき・工夫' },
        unplanned_work: { label: '思いがけないこと', hint: '突然のできごとや予定の変更' },
        support_needed: { label: '声を掛けたいこと', hint: '本人が助けがほしいと話していたこと' },
      },
      digestLoading: 'チームのまとめを作成しています',
      hintsTitle: 'チームでできそうなこと',
      mailNote: '件数は忙しさの大小ではなく、どの種類の連絡がどこに集まっているかを見るための目安です。',
    },
    mining: {
      lead: 'これまでの記録を見渡して、資料のやりとりの流れと、1人に集まっていることを見つけます。',
      tabDocuments: '資料の流れ',
      tabTasks: 'テーマと偏り',
      tabLeverage: '見直せそうなこと',
      documentsTitle: '複数人で回している資料',
      documentsLead: '同じ資料が複数の記録に現れた順に並べています。やりとりの回数が多いものほど上に表示します。',
      handoff: 'やりとり',
      tasksTitle: '記録のまとまりと担当のかたより',
      tasksLead: '記録したできごとをテーマごとにまとめ、記録している人が1人だけのテーマを先に表示します。',
      tasksButton: 'テーマごとにまとめる',
      tasksLoading: '記録したできごとをテーマごとにまとめています',
      singleHeading: '1人だけが記録しているテーマ',
      sharedHeading: '複数人で関わっているテーマ',
      tasksEmpty: 'この期間に、まとめられるできごとの記録がありませんでした。',
      tasksPrompt: '「テーマごとにまとめる」を押すと、記録したできごとをテーマごとに整理します。',
      leverageTitle: '見直せそうなこと',
      leverageLead: 'これまでの記録とやりとりから、影響の大きい順に並べています。判断の根拠になる数字をそのまま添えています。',
      leverageLoading: 'テーマのつながりを読み込んでいます',
      automationHeading: 'AI Agentを入れると助かりそうなこと',
      riskHeading: '1人に集まっていて、止まると影響が大きいこと',
      leverageEmpty: 'まだテーマのまとまりがありません。「テーマと偏り」タブで一度まとめると、ここに見直せそうなことが並びます。',
    },
    insightSummary: '進んだこと・気づき・思いがけないこと・助けがほしいこと',
    insightGroups: {
      progressed_items: { label: '進んだこと', empty: 'まだ記録がありません。' },
      ingenuity: { label: '気づき・工夫', empty: '気づきや工夫として残した記録はまだありません。' },
      unplanned_work: { label: '思いがけないこと', empty: '思いがけないできごとは記録されていません。' },
      support_needed: { label: '助けがほしいこと', empty: '助けがほしいと話した記録はありません。' },
    },
  },
  work: {
    sidebarTag: 'DAILY WORK JOURNAL',
    todayItems: '今日やった仕事',
    itemField: '仕事',
    prevItem: '前の仕事',
    nextItem: '次の仕事',
    itemPicker: '仕事の選択',
    itemsHint: '仕事の内容と進み具合が伝わる箇条書きです',
    itemsEmpty: '記録する仕事はありません。',
    startHint: '覚えておきたい仕事を、話しやすいところから教えてください。',
    memberCount: (days: number, count: number) => `${days}日分・仕事 ${count}件`,
    team: {
      digestGroups: {
        progress: { label: '進んだこと', hint: '組織として前に進んだこと' },
        ingenuity: { label: '共有したい工夫', hint: '他のメンバーにも真似してもらいたい工夫' },
        unplanned_work: { label: '予定外の対応', hint: '割り込みや突発の対応' },
        support_needed: { label: '声を掛けたいこと', hint: '本人が必要と話していた支援' },
      },
      digestLoading: '組織のサマリーを作成しています',
      hintsTitle: '組織として取れそうなこと',
      mailNote: '件数は業務量の大小ではなく、どの種類の依頼がどこに集まっているかを見るための目安です。',
    },
    mining: {
      lead: '積み重ねた記録を俯瞰して、資料の受け渡しの流れと、1人に集中していることを見つけます。',
      tabDocuments: '資料の流れ',
      tabTasks: '業務と属人化',
      tabLeverage: '手を入れる場所',
      documentsTitle: '複数人で回している資料',
      documentsLead: '同じ資料が複数の記録に現れた順に並べています。受け渡しの回数が多いものほど上に表示します。',
      handoff: '受け渡し',
      tasksTitle: '記録のまとまりと担当のかたより',
      tasksLead: '記録した仕事を業務ごとにまとめ、記録している人が1人だけの業務を先に表示します。',
      tasksButton: '業務をまとめる',
      tasksLoading: '記録した仕事を業務ごとにまとめています',
      singleHeading: '1人だけが記録している業務',
      sharedHeading: '複数人で担当している業務',
      tasksEmpty: 'この期間に、まとめられる仕事の記録がありませんでした。',
      tasksPrompt: '「業務をまとめる」を押すと、記録した仕事を業務ごとに整理します。',
      leverageTitle: '手を入れる場所',
      leverageLead: '蓄積した業務辞書と資料の受け渡しから、波及の大きい順に並べています。判断の根拠になる数字をそのまま添えています。',
      leverageLoading: '業務のつながりを読み込んでいます',
      automationHeading: 'AI Agentを入れると波及が大きい業務',
      riskHeading: '止まると影響が大きい属人化業務',
      leverageEmpty: 'まだ業務辞書がありません。「業務と属人化」タブで一度まとめると、ここに手を入れる場所が並びます。',
    },
    insightSummary: '進んだこと・工夫・予定外の対応・必要な支援',
    insightGroups: {
      progressed_items: { label: '進んだこと', empty: 'まだ記録がありません。' },
      ingenuity: { label: '工夫・判断', empty: '工夫として残した記録はまだありません。' },
      unplanned_work: { label: '予定外の対応', empty: '予定外の対応は記録されていません。' },
      support_needed: { label: '必要と話した支援', empty: '支援が必要と話した記録はありません。' },
    },
  },
} as const

const mode = ref<AppMode>('diary')
let loading: Promise<void> | null = null

async function load() {
  try {
    mode.value = await getAppMode()
  } catch {
    mode.value = 'diary'
    // 次に開いたときに取り直せるよう、失敗は覚えておかない。
    loading = null
  }
}

/** 管理者が決めた動作モード。画面間で1つを共有する。 */
export function useAppMode() {
  function ensureLoaded(): Promise<void> {
    if (!loading) loading = load()
    return loading
  }

  function apply(next: AppMode) {
    mode.value = next
    loading = Promise.resolve()
  }

  const labels = computed(() => LABELS[mode.value])

  return { appMode: mode, labels, ensureLoaded, apply }
}
