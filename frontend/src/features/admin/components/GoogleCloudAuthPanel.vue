<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  getGoogleCloudAuth,
  getWorkloadIdentity,
  saveGoogleCloudAuth,
  type GoogleCloudAuthSettings,
  type GoogleCloudSettingsResponse,
  type WorkloadIdentityInfo,
} from '../../../api/hinami'
import { useNotifier } from '../../shell/useNotifier'

const { notify } = useNotifier()

const EMPTY: GoogleCloudAuthSettings = {
  project: '', location: '', wif_project_number: '', wif_pool_id: '', wif_provider_id: '', wif_service_account: '',
}
const saved = ref<GoogleCloudSettingsResponse | null>(null)
const form = ref<GoogleCloudAuthSettings>({ ...EMPTY })
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const showGuide = ref(false)
const identity = ref<WorkloadIdentityInfo | null>(null)
// Kubernetes の外では身元・発行元・公開鍵を読めない。そのときは kubectl で取り出す手順に切り替える。
const identityUnavailable = ref(false)
const identityLoading = ref(false)

const environment = computed(() => saved.value?.environment)
const activeAuthLabel = computed(() => {
  if (!saved.value) return ''
  if (saved.value.active_auth === 'wif') return 'Workload Identity 連携（Kubernetes の ServiceAccount のトークンを交換）'
  return saved.value.running_on_kubernetes
    ? '環境の認証情報（ADC）。WIF の設定が空のため、Pod の環境の認証情報を使っています'
    : '環境の認証情報（ADC）。gcloud のログイン・鍵ファイル・GCE のサービスアカウントなどを自動で探します'
})
const changed = computed(() => !saved.value || (Object.keys(form.value) as (keyof GoogleCloudAuthSettings)[])
  .some((key) => form.value[key] !== saved.value?.[key]))

const poolPath = computed(() => `projects/${form.value.wif_project_number || '<プロジェクト番号>'}/locations/global/`
  + `workloadIdentityPools/${form.value.wif_pool_id || '<プールID>'}`)
// 使うサービスは ② のプロジェクトで有効にする。未入力ならサービスアカウントのプロジェクトを仮に入れる。
const guideProject = computed(() => {
  const account = form.value.wif_service_account.trim()
  return form.value.project || environment.value?.project
    || (account ? account.split('@')[1]?.split('.iam.gserviceaccount.com')[0] : '')
    || '<Vertex AI を使うプロジェクトID>'
})

/** ローカル・Docker で ADC を使うときの手順。 */
const adcCommands = computed(() => {
  const project = guideProject.value
  return [
    '# ローカル：自分の Google アカウントでログインする（ADC が作られる）',
    'gcloud auth application-default login',
    `gcloud auth application-default set-quota-project ${project}`,
    '',
    '# 使うサービスを有効にし、自分のアカウントに権限を付ける（使うものだけ）',
    `gcloud services enable aiplatform.googleapis.com texttospeech.googleapis.com --project=${project}`,
    `gcloud projects add-iam-policy-binding ${project} --role=roles/aiplatform.user \\`,
    '  --member=user:<自分のメールアドレス>',
    '',
    '# Docker：ローカルの ADC をコンテナに読み取り専用で渡す（compose.yaml なら volumes に書く）',
    '#   -v ~/.config/gcloud:/home/hinami/.config/gcloud:ro',
    '# または、サービスアカウントの鍵ファイルや WIF の構成ファイルを渡す',
    '#   -v /path/to/credentials.json:/secrets/credentials.json:ro',
    '#   -e GOOGLE_APPLICATION_CREDENTIALS=/secrets/credentials.json',
  ].join('\n')
})

/** Kubernetes で WIF を使うときの手順。Kubernetes の外では、発行元・公開鍵・身元を kubectl で取り出す形にする。 */
const wifCommands = computed(() => {
  const info = identity.value
  const pool = form.value.wif_pool_id || '<プールID>'
  const provider = form.value.wif_provider_id || '<プロバイダーID>'
  const poolNumber = form.value.wif_project_number || '<プールを置くプロジェクトの番号>'
  const account = form.value.wif_service_account.trim()
  const namespace = info ? info.namespace : '"$NAMESPACE"'
  const serviceAccount = info ? info.service_account : '"$KSA"'
  const subject = info ? info.subject : 'system:serviceaccount:$NAMESPACE:$KSA'
  const issuer = info ? info.issuer : '"$ISSUER"'
  const member = `principal://iam.googleapis.com/${poolPath.value}/subject/${subject}`
  // サービスアカウントを使うなら、権限はそのアカウントに。使わないなら、Hinami の身元に直接付ける。
  const target = account ? `serviceAccount:${account}` : `"${member}"`
  const project = guideProject.value
  const prepare = info
    ? ['# 1. プールとOIDCプロバイダーを作る（jwks.json は上のボタンでダウンロード）']
    : [
        '# 0. Hinami を動かすクラスタで、発行元と公開鍵を取り出す（kubectl の向き先をそのクラスタにして実行）',
        'NAMESPACE=<Hinami を動かす namespace>',
        'KSA=<Hinami の Pod の ServiceAccount 名>',
        'ISSUER=$(kubectl get --raw /.well-known/openid-configuration | python3 -c "import json,sys; print(json.load(sys.stdin)[\'issuer\'])")',
        'kubectl get --raw /openid/v1/jwks > jwks.json',
        '',
        '# 1. プールとOIDCプロバイダーを作る',
      ]
  const access = account
    ? [
        '# 2. Hinami の身元に、サービスアカウントへのなりすましを許す',
        `gcloud iam service-accounts add-iam-policy-binding ${account} --role=roles/iam.workloadIdentityUser \\`,
        `  --member="${member}"`,
      ]
    : [
        '# 2. サービスアカウントは使わず、Hinami の身元に直接権限を付ける（下の 3 で付与）',
        '# Cloud Text-to-Speech の利用量と課金は、このプロジェクトで数える',
        `gcloud projects add-iam-policy-binding ${project} --role=roles/serviceusage.serviceUsageConsumer \\`,
        `  --member="${member}"`,
      ]
  return [
    ...prepare,
    '# プロジェクト番号からプロジェクトIDを引く（workload-identity-pools は ID しか受け付けない）',
    `POOL_PROJECT=$(gcloud projects describe ${poolNumber} --format='value(projectId)')`,
    `gcloud iam workload-identity-pools create ${pool} --location=global --project="$POOL_PROJECT"`,
    `gcloud iam workload-identity-pools providers create-oidc ${provider} --location=global \\`,
    `  --workload-identity-pool=${pool} --project="$POOL_PROJECT" \\`,
    `  --issuer-uri=${issuer} --jwk-json-path=jwks.json \\`,
    '  --attribute-mapping=google.subject=assertion.sub',
    '',
    ...access,
    '',
    '# 3. 使うサービスを有効にし、権限を付ける（使うものだけ）',
    '# Vertex AI（対話・文字起こしの接続方法を ② にする場合）',
    `gcloud services enable aiplatform.googleapis.com --project=${project}`,
    `gcloud projects add-iam-policy-binding ${project} --role=roles/aiplatform.user \\`,
    `  --member=${target}`,
    '# Cloud Text-to-Speech（読み上げの方式を Cloud Text-to-Speech にする場合）',
    `gcloud services enable texttospeech.googleapis.com --project=${project}`,
    '',
    '# 4. Hinami が自分のトークンを発行できるようにする（Kubernetes）',
    `kubectl -n ${namespace} create role hinami-token-request --verb=create \\`,
    `  --resource=serviceaccounts/token --resource-name=${serviceAccount}`,
    `kubectl -n ${namespace} create rolebinding hinami-token-request --role=hinami-token-request \\`,
    `  --serviceaccount=${namespace}:${serviceAccount}`,
  ].join('\n')
})

function apply(response: GoogleCloudSettingsResponse) {
  saved.value = response
  const { environment: _environment, active_auth: _activeAuth, running_on_kubernetes: _onKubernetes, ...settings } = response
  form.value = { ...settings }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    apply(await getGoogleCloudAuth())
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'Vertex AI（Google Cloud）の設定を取得できませんでした。'
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  error.value = ''
  try {
    apply(await saveGoogleCloudAuth(form.value))
    notify('Vertex AI（Google Cloud）の設定を保存しました。')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'Vertex AI（Google Cloud）の設定を保存できませんでした。'
  } finally {
    saving.value = false
  }
}

async function toggleGuide() {
  showGuide.value = !showGuide.value
  if (!showGuide.value || identity.value || identityUnavailable.value) return
  identityLoading.value = true
  try {
    identity.value = await getWorkloadIdentity()
  } catch {
    // Kubernetes の外（ローカル・Docker）では読めない。kubectl で取り出す手順を見せる。
    identityUnavailable.value = true
  } finally {
    identityLoading.value = false
  }
}

function downloadJwks() {
  if (!identity.value) return
  const url = URL.createObjectURL(new Blob([JSON.stringify(identity.value.jwks, null, 2)], { type: 'application/json' }))
  const link = document.createElement('a')
  link.href = url
  link.download = 'jwks.json'
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
}

onMounted(load)
</script>

<template>
  <section class="panel backup-panel settings-panel">
    <div class="settings-panel__heading">
      <div>
        <h2>② Vertex AI（Google Cloud）</h2>
        <p>Vertex AI と Cloud Text-to-Speech を呼ぶときのプロジェクト・リージョン・認証です。① Gemini API キーだけを使う場合は設定不要です。</p>
      </div>
      <v-btn variant="text" size="small" prepend-icon="mdi-refresh" :loading="loading" @click="load">更新</v-btn>
    </div>

    <p v-if="error" class="backup-error"><v-icon size="18">mdi-alert-circle-outline</v-icon>{{ error }}</p>

    <div class="settings-form">
      <div class="settings-grid">
        <v-text-field
          v-model="form.project"
          label="プロジェクトID"
          :placeholder="environment?.project || 'my-project'"
          persistent-placeholder
          hide-details
        ></v-text-field>
        <v-text-field
          v-model="form.location"
          label="Vertex AI のリージョン"
          :placeholder="environment?.location || 'global'"
          persistent-placeholder
          hide-details
        ></v-text-field>
      </div>
      <div v-if="saved" class="google-cloud__auth" role="status">
        <v-icon size="18">{{ saved.active_auth === 'wif' ? 'mdi-kubernetes' : 'mdi-account-key-outline' }}</v-icon>
        <span><b>いまの認証：</b>{{ activeAuthLabel }}</span>
      </div>
      <p class="settings-note">
        認証の方法は、動いている場所で自動で決まります。Kubernetes 上で下の Workload Identity 連携を設定していればそれを、
        それ以外（ローカル・Docker・GCE）は google.auth.default() が見つけた認証情報を使います。
        Docker で WIF を使う場合は、構成ファイルを GOOGLE_APPLICATION_CREDENTIALS で渡せば、この自動判定でそのまま使えます。
      </p>

      <h3 class="google-cloud__subheading">Kubernetes で使う Workload Identity 連携（任意）</h3>
      <div class="settings-grid">
        <v-text-field v-model="form.wif_project_number" label="プールのプロジェクト番号" placeholder="123456789012" persistent-placeholder hide-details></v-text-field>
        <v-text-field v-model="form.wif_pool_id" label="プールID" hide-details></v-text-field>
        <v-text-field v-model="form.wif_provider_id" label="プロバイダーID" hide-details></v-text-field>
        <v-text-field
          v-model="form.wif_service_account"
          label="なりすまし先のサービスアカウント（任意）"
          placeholder="hinami@project.iam.gserviceaccount.com"
          persistent-placeholder
          hide-details
        ></v-text-field>
      </div>

      <v-btn variant="text" size="small" :prepend-icon="showGuide ? 'mdi-chevron-up' : 'mdi-chevron-down'" class="settings-guide-toggle" @click="toggleGuide">GCP側の設定手順</v-btn>
      <div v-if="showGuide" class="settings-guide">
        <v-progress-linear v-if="identityLoading" indeterminate color="primary"></v-progress-linear>
        <template v-else>
          <h4>ローカル・Docker で使う（ADC）</h4>
          <pre>{{ adcCommands }}</pre>

          <h4>Kubernetes で使う（Workload Identity 連携）</h4>
          <template v-if="identity">
            <dl>
              <dt>Hinami の身元</dt><dd><code>{{ identity.subject }}</code></dd>
              <dt>発行元（issuer）</dt><dd><code>{{ identity.issuer }}</code></dd>
            </dl>
            <v-btn variant="outlined" size="small" prepend-icon="mdi-download-outline" @click="downloadJwks">公開鍵（jwks.json）をダウンロード</v-btn>
          </template>
          <p v-else class="settings-note">
            いまは Kubernetes の外で動いているため、クラスタの発行元と公開鍵をこの画面では読めません。
            手順 0 で、Hinami を動かすクラスタから kubectl で取り出してください。Kubernetes 上で開くと、実際の値が埋まった手順になります。
          </p>
          <pre>{{ wifCommands }}</pre>
        </template>
      </div>
    </div>

    <div class="settings-actions">
      <p>保存した直後から、② を使う役割の呼び出しがこの設定になります。つながるかは「AIモデル」の各役割の「接続を確認」で確かめられます。</p>
      <div>
        <v-btn color="primary" prepend-icon="mdi-check" :loading="saving" :disabled="!changed || loading" @click="save">保存</v-btn>
      </div>
    </div>
  </section>
</template>

<style scoped>
.google-cloud__auth { display:flex; align-items:flex-start; gap:8px; padding:10px 12px; border-radius:10px; color:var(--ink-3); background:var(--surface-accent); font-size:13px; line-height:1.6; }
.google-cloud__auth b { font-weight:700; }
.google-cloud__subheading { margin:8px 0 0; color:var(--ink-3); font-size:14px; }
.settings-guide h4 { margin:4px 0 0; color:var(--ink-3); font-size:13px; }
</style>
