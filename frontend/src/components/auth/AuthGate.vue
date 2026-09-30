<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

/* ログイン画面。平安の日記「日次記」にならい、和紙の地に「今日の一頁」がそっと書かれていく。
   Googleのボタンは呼び出し側がスロットへ置く（ref を App.vue 側で持つため）。

   色は .auth-gate の局所変数で持つ。アプリ本体（tokens.css）の配色はこの画面に揃えてあるが、
   ログイン画面だけは単独で成り立つように、トークンには依存させない。
   挿絵は public/auth/ に置く。未配置でも紙の地だけで成り立つ。 */

defineProps<{
  buttonReady: boolean
  error: string
  loading: boolean
}>()

type Scene = { ask: string; lines: string[] }

const SCENES: Scene[] = [
  {
    ask: '今日は、どんな一日でしたか？',
    lines: [
      '朝は少し慌ただしかったけれど、落ち着いて始められた。',
      'お昼のあと、ひとつ山を越えた気がする。',
      '明日は、今日の続きからゆっくりと。',
    ],
  },
  {
    ask: 'うれしかったことは、ありましたか？',
    lines: [
      'ありがとう、と声をかけてもらえた。',
      '迷ったけれど、思いきってやってみてよかった。',
      '今日はここまで。おつかれさま。',
    ],
  },
  {
    ask: '気になっていることは、ありますか？',
    lines: [
      'まだ少し、頭に引っかかっていることがある。',
      '書き出したら、ちょっと軽くなった。',
      '続きは、また明日考えよう。',
    ],
  },
]

const reducedMotion = typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

const today = new Date().toLocaleDateString('ja-JP', { month: 'long', day: 'numeric', weekday: 'long' })

/* 挿絵。読み込めなかったら外して、紙の地だけにする。 */
const heroBase = `${import.meta.env.BASE_URL}auth/`
const heroFailed = ref(false)

const sceneIndex = ref(0)
const shownLines = ref(0)
const leaving = ref(false)
let timer = 0

const scene = computed(() => SCENES[sceneIndex.value])

/** 問いかけ → 一行ずつ静かに現れる → しばらく読ませる → 頁をめくる（薄れて次の場面）。 */
function step() {
  if (shownLines.value < scene.value.lines.length) {
    timer = window.setTimeout(() => {
      shownLines.value += 1
      step()
    }, shownLines.value === 0 ? 1400 : 1900)
    return
  }
  timer = window.setTimeout(() => {
    leaving.value = true
    timer = window.setTimeout(() => {
      sceneIndex.value = (sceneIndex.value + 1) % SCENES.length
      shownLines.value = 0
      leaving.value = false
      step()
    }, 900)
  }, 5200)
}

onMounted(() => {
  if (reducedMotion) {
    shownLines.value = scene.value.lines.length
    return
  }
  step()
})

onBeforeUnmount(() => window.clearTimeout(timer))

/* 舞う光の粒。位置・大きさ・周期を散らして、揃って動かないようにする。 */
const MOTES = Array.from({ length: 16 }, () => ({
  left: `${(Math.random() * 100).toFixed(1)}%`,
  size: `${(3 + Math.random() * 6).toFixed(1)}px`,
  duration: `${(18 + Math.random() * 20).toFixed(1)}s`,
  delay: `${(-Math.random() * 30).toFixed(1)}s`,
  sway: `${(Math.random() * 60 - 30).toFixed(0)}px`,
}))
</script>

<template>
  <div class="auth-gate">
    <img
      v-if="!heroFailed"
      class="auth-gate__art"
      :src="`${heroBase}hinami-hero-sp.png`"
      alt=""
      aria-hidden="true"
      @error="heroFailed = true"
    >
    <div class="auth-gate__veil" aria-hidden="true"></div>
    <div class="auth-gate__motes" aria-hidden="true">
      <i v-for="(mote, index) in MOTES" :key="index" :style="{ '--left': mote.left, '--size': mote.size, '--duration': mote.duration, '--delay': mote.delay, '--sway': mote.sway }"></i>
    </div>

    <div class="auth-gate__layout">
      <header class="auth-hero">
        <div class="auth-brand">
          <img class="auth-brand__seal" :src="`${heroBase}logo.png`" alt="" aria-hidden="true">
          <div>
            <div class="auth-brand__name">Hinami</div>
            <div class="auth-brand__ruby">ひなみ ・ 日次の記録</div>
          </div>
        </div>
        <h1 class="auth-hero__title">今日のことを、<br>ひとこと話すだけ。</h1>
        <p class="auth-hero__lead">
          むかしの人が日記に「日次記（ひなみき）」と名づけたように、その日のできごとを、その日のうちに。AIとの数分の会話が、あなたの一日の記録になります。
        </p>
      </header>

      <!-- 飾りのデモ。読み上げると本文と混ざるので支援技術からは隠す。 -->
      <section class="auth-page" :class="{ 'is-leaving': leaving }" aria-hidden="true">
        <p class="auth-page__ask" :key="`ask-${sceneIndex}`"><b>問い</b>{{ scene.ask }}</p>
        <div class="auth-page__paper">
          <p class="auth-page__date">{{ today }}</p>
          <p
            v-for="(line, index) in scene.lines"
            :key="`${sceneIndex}-${index}`"
            class="auth-page__line"
            :class="{ 'is-shown': index < shownLines }"
          >{{ line }}</p>
        </div>
      </section>

      <section class="auth-card" aria-labelledby="auth-card-title">
        <p class="auth-card__eyebrow">日次記をひらく</p>
        <h2 id="auth-card-title">おかえりなさい</h2>
        <div class="auth-card__button">
          <slot />
          <button v-if="!buttonReady" class="auth-card__pending" disabled>Googleログインを準備中</button>
        </div>
        <p v-if="error" class="auth-card__error" role="alert">{{ error }}</p>
        <p v-if="loading" class="auth-card__status" role="status"><span class="auth-card__spinner"></span>認証中...</p>
      </section>
    </div>
  </div>
</template>

<style scoped>
.auth-gate {
  --paper: #f8f1e4;
  --paper-deep: #efe3cd;
  --sheet: #fffaf0;
  --ink: #4a3b2f;
  --ink-soft: #75624f;
  --line: #e2d3ba;
  --seal: #b5573f;
  --seal-deep: #9a4530;
  --moss: #6d8a5a;
  --glow: #f4c98a;
  --auth-serif: 'Hiragino Mincho ProN', 'Yu Mincho', 'Noto Serif JP', serif;

  position: fixed; inset: 0; z-index: 9999; overflow: hidden auto;
  color: var(--ink);
  font-family: 'Hiragino Kaku Gothic ProN', 'Hiragino Sans', 'Noto Sans JP', 'Yu Gothic', sans-serif;
  background:
    radial-gradient(ellipse 70% 60% at 12% 8%, color-mix(in srgb, var(--glow) 55%, transparent), transparent 70%),
    linear-gradient(160deg, var(--paper), var(--paper-deep));
}

/* 挿絵。右下に寄せ、ゆっくり息をするように拡縮する。 */
.auth-gate__art {
  position: fixed; inset: 0; width: 100%; height: 100%; object-fit: cover; object-position: 70% 60%;
  pointer-events: none; transform-origin: 70% 60%; animation: auth-breathe 40s ease-in-out infinite alternate;
}
/* 左から紙の色でなじませ、文字の地を確保する。 */
.auth-gate__veil {
  position: fixed; inset: 0; pointer-events: none;
  background: linear-gradient(90deg, var(--paper) 0%, color-mix(in srgb, var(--paper) 82%, transparent) 34%, transparent 68%);
}

/* 舞う光の粒。下からゆっくり昇り、左右にそよぐ。 */
.auth-gate__motes { position: fixed; inset: 0; pointer-events: none; overflow: hidden; }
.auth-gate__motes i {
  position: absolute; bottom: -20px; left: var(--left); width: var(--size); height: var(--size); border-radius: 50%;
  background: radial-gradient(circle, #fff6df, var(--glow) 60%, transparent 72%);
  opacity: 0; animation: auth-mote var(--duration) linear var(--delay) infinite;
}

.auth-gate__layout {
  position: relative; min-height: 100%;
  display: grid; grid-template-columns: minmax(0, 1fr) 400px; grid-template-rows: 1fr auto;
  gap: 24px 56px; padding: 48px 64px;
}

/* ---- 見出し ---- */
.auth-hero { grid-column: 1; grid-row: 1; align-self: start; max-width: 520px; }
.auth-brand { display: flex; align-items: center; gap: 12px; }
.auth-brand__seal {
  width: 60px; height: 60px; margin: -10px; object-fit: contain; transform: rotate(-3deg);
}
.auth-brand__name { font-family: var(--auth-serif); font-size: 20px; font-weight: 700; letter-spacing: .5px; }
.auth-brand__ruby { color: var(--ink-soft); font-size: 11px; letter-spacing: 1.4px; }

.auth-hero__title {
  margin: 56px 0 0; font-family: var(--auth-serif); font-size: clamp(30px, 3.8vw, 46px); font-weight: 600;
  line-height: 1.5; letter-spacing: 1px;
}
.auth-hero__lead { margin: 20px 0 0; max-width: 430px; color: var(--ink-soft); font-size: 14px; line-height: 2; }

/* ---- 今日の一頁（飾り） ---- */
.auth-page { grid-column: 1; grid-row: 2; align-self: end; width: min(440px, 100%); transition: opacity .8s ease; }
.auth-page.is-leaving { opacity: 0; }
.auth-page__ask {
  display: inline-flex; align-items: center; gap: 10px; margin: 0 0 12px; padding: 8px 16px 8px 10px;
  border-radius: 999px; background: color-mix(in srgb, var(--sheet) 80%, transparent);
  border: 1px solid var(--line); color: var(--ink); font-size: 13px; animation: auth-rise .9s ease-out both;
}
.auth-page__ask b {
  padding: 1px 8px; border-radius: 999px; color: #fff8ee; background: var(--moss); font-size: 11px; font-weight: 600; letter-spacing: 1px;
}
.auth-page__paper {
  min-height: 176px; padding: 18px 22px 14px; border: 1px solid var(--line); border-radius: 6px 14px 14px 6px;
  background:
    repeating-linear-gradient(transparent 0 31px, color-mix(in srgb, var(--line) 70%, transparent) 31px 32px) 0 18px / 100% 100% no-repeat padding-box,
    var(--sheet);
  box-shadow: 0 14px 40px color-mix(in srgb, var(--ink) 12%, transparent), inset 6px 0 0 color-mix(in srgb, var(--seal) 14%, transparent);
}
.auth-page__date { margin: 0; color: var(--seal); font-family: var(--auth-serif); font-size: 13px; font-weight: 700; letter-spacing: 1px; line-height: 32px; }
.auth-page__line {
  margin: 0; font-family: var(--auth-serif); font-size: 14px; line-height: 32px;
  opacity: 0; filter: blur(3px); transform: translateY(3px); transition: opacity 1.1s ease, filter 1.1s ease, transform 1.1s ease;
}
.auth-page__line.is-shown { opacity: 1; filter: none; transform: none; }

/* ---- ログインカード ---- */
.auth-card {
  grid-column: 2; grid-row: 1 / span 2; align-self: center; padding: 34px 32px 30px;
  border: 1px solid var(--line); border-radius: 22px;
  background: color-mix(in srgb, var(--sheet) 90%, transparent); backdrop-filter: blur(10px);
  box-shadow: 0 24px 60px color-mix(in srgb, var(--ink) 16%, transparent);
  animation: auth-rise .9s ease-out both;
}
.auth-card__eyebrow { margin: 0 0 10px; color: var(--seal); font-size: 12px; font-weight: 700; letter-spacing: 1.6px; }
.auth-card h2 { margin: 0 0 26px; font-family: var(--auth-serif); font-size: 26px; font-weight: 600; letter-spacing: 1px; }
.auth-card__button { display: grid; min-height: 44px; }
.auth-card__button :slotted(.google-login-button) { min-height: 44px; }
.auth-card__pending {
  width: 100%; height: 44px; border: 1px dashed var(--line); border-radius: 22px;
  color: var(--ink-soft); background: transparent; font-size: 13px;
}
.auth-card__error {
  margin: 14px 0 0; padding: 9px 12px; border-radius: 10px;
  color: #98352a; background: #fbe8e2; font-size: 13px; line-height: 1.7;
}
.auth-card__status { display: flex; align-items: center; gap: 8px; margin: 14px 0 0; color: var(--ink-soft); font-size: 13px; }
.auth-card__spinner {
  width: 14px; height: 14px; border: 2px solid var(--line); border-top-color: var(--seal);
  border-radius: 50%; animation: auth-spin .9s linear infinite;
}

@keyframes auth-breathe { from { transform: scale(1); } to { transform: scale(1.045); } }
@keyframes auth-mote {
  0% { opacity: 0; transform: translate(0, 0); }
  12% { opacity: .75; }
  85% { opacity: .55; }
  100% { opacity: 0; transform: translate(var(--sway), -105vh); }
}
@keyframes auth-rise { from { opacity: 0; transform: translateY(8px); } }
@keyframes auth-spin { to { transform: rotate(360deg); } }

@media (max-width: 1180px) {
  .auth-gate__layout { grid-template-columns: minmax(0, 1fr) 380px; padding: 40px; gap: 24px 32px; }
  .auth-page { display: none; }
}
/* 高さの低い画面（ノートPCなど）。飾りを外してスクロールを出さない。 */
@media (max-height: 720px) {
  .auth-page { display: none; }
}
@media (max-width: 780px) {
  .auth-gate__layout { grid-template-columns: 1fr; grid-template-rows: auto auto; padding: 28px 16px; }
  .auth-gate__veil { background: linear-gradient(90deg, color-mix(in srgb, var(--paper) 70%, transparent), transparent 55%); }
  .auth-gate__art { height: 46vh; object-position: 100% 50%; transform-origin: 100% 50%;
    -webkit-mask-image: linear-gradient(to bottom, #000 55%, transparent); mask-image: linear-gradient(to bottom, #000 55%, transparent); }
  .auth-brand { text-shadow: 0 0 6px var(--paper), 0 0 12px var(--paper); }
  .auth-brand__ruby { color: var(--ink); }
  .auth-hero__title { margin-top: 30vh; font-size: 28px; }
  .auth-card { grid-column: 1; grid-row: 2; padding: 26px 22px; }
}
@media (prefers-reduced-motion: reduce) {
  .auth-gate__art, .auth-card, .auth-page__ask { animation: none; }
  .auth-gate__motes { display: none; }
  .auth-page__line { transition: none; }
}
</style>
