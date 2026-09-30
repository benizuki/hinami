# Hinami

Hinami（日並）は、AIとの数分の対話で今日の仕事を振り返り、日々の記録として残すWebアプリです。
積み重ねた記録から、チームのまとめや記録の見取り図（1人への集中・資料の受け渡し）を集計します。

> Hinami is an AI-assisted daily work journal. A short conversation with Gemini turns your day into a structured journal entry, and accumulated journals roll up into organization summaries and a work inventory. The UI is Japanese.

## できること

- **日々の記録**：AIが問いかけ、話すか書くだけで「今日のまとめ」と仕事単位の記録を作成。音声入力と読み上げ（ストリーミング）、PDF・画像の添付に対応。
- **振り返りの手がかり**（任意）：Googleログイン時に、本人のGoogleカレンダー・Meet・Gmail・Driveを読み取り専用で参照。本文は保存しません。使う機能はシステム管理者が「システム設定」で選べます。
- **チームの記録**：manager が自組織と配下の記録を期間でまとめて確認。
- **記録の見取り図**：記録から業務を名寄せし、担当者数・回数・資料の受け渡しを集計。属人化の候補を示します。
- **管理機能**：マスタ設定（テナント、組織マスター、ユーザーとロール、メール分類マスター）、AI利用状況、SQLiteバックアップ、システム設定（接続方法：① Gemini APIキー／② Vertex AI、役割ごとのAIモデル、Google連携）。

## 構成

| 層 | 技術 |
| --- | --- |
| フロントエンド | Vue 3 + TypeScript + Vuetify 3 + Vite |
| バックエンド | FastAPI（Python 3.12） |
| AI | Gemini API（Google AI Studio の APIキー） |
| 保存 | SQLite（WAL）、ユーザーとテナントはJSON |

バックエンドのエンドポイントは `backend/app/api/` に1機能1ファイルで置き、`backend/app/main.py` はミドルウェアとルーターの登録だけを行います。

## はじめに

必要なもの：Python 3.12、[uv](https://docs.astral.sh/uv/)、Node.js 22、Gemini APIキー。

```bash
uv sync
npm --prefix frontend ci
npm --prefix frontend run build
cp .env.example .env   # GEMINI_API_KEY を設定する（起動後に画面の「AI設定」から登録してもよい）
uv run python -m backend
```

<http://127.0.0.1:8000/> を開きます。`GOOGLE_OAUTH_CLIENT_ID` を設定しない間は、ログインなしの開発モードで動きます。
開発モードは安全のため `127.0.0.1` でしか起動せず、接続元もこの端末（ループバック）に限ります。

フロントエンドを開発サーバーで動かす場合は、バックエンドを起動したうえで次を実行します（`/api` はバックエンドへ中継されます）。

```bash
npm --prefix frontend run dev
```

## 設定

主な環境変数です。すべての値は [.env.example](.env.example) にあります。

| 変数 | 既定 | 内容 |
| --- | --- | --- |
| `GEMINI_API_KEY` | なし | Gemini APIキー。未設定ならシステム管理者が画面の「AI設定」から登録できます（設定するとこちらが優先されます） |
| `GEMINI_MODEL` | `gemini-3.5-flash` | 対話・記録の作成のモデル |
| `GEMINI_BACKEND` | `gemini-api` | 対話・記録の作成（名寄せも同じ）の接続方法。`gemini-api`（① APIキー）か `vertex`（② Vertex AI） |
| `GOOGLE_CLOUD_PROJECT` / `GOOGLE_CLOUD_LOCATION` | なし / `global` | ② Vertex AI のプロジェクトとリージョン（Cloud Text-to-Speech と共通） |
| `GEMINI_TRANSCRIPTION_BACKEND` / `GEMINI_TRANSCRIPTION_MODEL` | 対話と同じ | 音声入力の文字起こしの接続方法とモデル |
| `HINAMI_TTS_ENGINE` | `gemini-tts` | 読み上げの方式。`gemini-tts`（① APIキー）か `cloud-tts`（② Google Cloud Text-to-Speech） |
| `GEMINI_TTS_MODEL` | `gemini-3.8-flash-lite-tts` | `gemini-tts` のときの読み上げのモデル |
| `CLOUD_TTS_MODEL` | `gemini-2.5-flash-tts` | `cloud-tts` のときの読み上げのモデル |
| `CLOUD_TTS_SPEAKING_RATE` | `1.0` | `cloud-tts` のときの基準の速さ（0.25〜2.0） |

接続方法とモデルは、役割ごとに画面の「システム設定」でも変えられます（画面の値が優先されます）。
| `GEMINI_TTS_VOICE` | `Sulafat` | 読み上げの既定の声。各利用者は画面上部の「読み上げの設定」で声・トーン・ペースを変えられます |
| `GEMINI_TTS_SEED` | 固定値 | 読み上げの生成の乱数。固定すると呼び出しごとの声質の揺れを抑えます。空にすると固定しません |
| `GEMINI_EMBEDDING_MODEL` | `gemini-embedding-001` | 業務名の名寄せ |
| `GOOGLE_OAUTH_CLIENT_ID` | なし | 設定するとGoogleログインが有効になります |
| `APP_AUTH_SECRET` | 自動生成 | ログイントークンの署名鍵。未設定なら初回起動時に生成して `auth/app_auth_secret` に保存します。Cloud Run など再起動でファイルが消える環境では必ず設定してください |
| `HINAMI_BOOTSTRAP_ADMIN_EMAILS` | なし | 最初にログインしたときに管理者にするメールアドレス |
| `HINAMI_DATA_DIR` | `backend/app/data` | データの保存先 |
| `HINAMI_LOCAL_CLIENT_HOSTS` | なし | ログインなしの開発モードで追加で受け付ける接続元IP（プライベートアドレスのみ）。`compose.yaml` が使います |
| `HINAMI_TRUST_FORWARDED_FOR` | 無効 | リバースプロキシ配下でだけ有効にする（`X-Forwarded-For` を信頼） |

### Googleログインと連携

1. Google Cloud で OAuth クライアント（ウェブアプリケーション）を作り、承認済みの JavaScript 生成元に公開URLを登録します。
2. `GOOGLE_OAUTH_CLIENT_ID` と `HINAMI_BOOTSTRAP_ADMIN_EMAILS` を設定します。`APP_AUTH_SECRET` は未設定なら自動で生成・保存されます（データ保存先を永続化していない環境では設定が必要です）。
3. 振り返りの手がかりを使う場合は、同じプロジェクトで Calendar / Gmail / Meet / Drive の各APIを有効にします。
4. 使わない機能は、システム管理者が画面の「システム設定」→「Google連携」で無効にできます。無効にした機能のスコープは要求しません（Meetはカレンダーが有効なときだけ使えます）。

日々の記録の画面が要求するスコープ（すべて読み取り専用で、利用者本人のブラウザから直接取得します）：

- `calendar.events.owned.readonly`
- `meetings.space.readonly`
- `gmail.readonly`
- `drive.readonly`

### AIの接続方法とモデル

「システム設定」は次のように分かれています。

- **接続方法**：① Gemini API キー／② Vertex AI（Google Cloud のプロジェクト・リージョン・認証）。使うものだけ設定します。
- **役割ごとの接続方法とモデル**：
  - 対話・記録の作成（業務名の名寄せも同じ接続）：① か ②
  - 文字起こし：① か ②（空なら対話と同じ）
  - 読み上げ：Gemini TTS（① 固定）か Cloud Text-to-Speech（② 固定）

各役割の「接続を確認」は、モデルの情報を引くだけで、生成や音声合成はしません。

② の認証は、動いている場所で自動で決まります（画面で選ぶ必要はありません）。

```
                 ② の認証
                    │
          ┌─────────┴──────────┐
          ↓                    ↓
 ローカル・Docker・GCE      Kubernetes（WIF を設定済み）
 google.auth.default()     Workload Identity 連携
 （ADC）
```

- **ADC（google.auth.default()）**：ローカルの `gcloud auth application-default login`、鍵ファイル（`GOOGLE_APPLICATION_CREDENTIALS`）、GCE のサービスアカウントのどれかを自動で探します。Docker で WIF を使う場合も、構成ファイル（`gcloud iam workload-identity-pools create-cred-config` で作るもの）を `GOOGLE_APPLICATION_CREDENTIALS` で渡せばこちらで動きます。
- **Kubernetes の Workload Identity 連携**：画面で WIF の識別子を設定し、Kubernetes 上で動かすと使われます。Pod の ServiceAccount のトークンを Google の一時的な認証に交換します。なりすまし先のサービスアカウントは任意で、空なら Pod の身元に直接権限を付けます。GCP 側で必要な設定（プール・プロバイダーの作成、権限の付与、API の有効化、Kubernetes の権限）は、同じ画面の「GCP側の設定手順」に、実際の値を埋めたコマンドで表示されます。

いま使われている認証は、画面の「② Vertex AI（Google Cloud）」に表示されます。

`gmail.readonly` は Google の制限付きスコープです。組織外の利用者に公開するアプリでは Google の審査が必要になります。
社内（Google Workspace の内部アプリ）で使う場合は不要です。

## データの扱い

- **Gemini API の利用規約を確認してください。** 無料枠では、送信した内容がGoogleのサービス改善に使われることがあります。業務の記録を扱うため、**有料枠のAPIキー**の利用を強く勧めます。
- 保存するのは確定した記録、組織別の業務辞書、メール分類ごとの件数、AIの利用件数とトークン数です。
- 会話の全文、メール本文、予定の説明、添付資料の本文、位置情報は保存しません。
- AIは、予定やメールの多寡を能力・負担・余裕の評価に使いません。件数・時間・通数を人の評価として扱わない設計です。

## Docker

ログインなしで試すだけなら Docker Compose を使います（1人用・この端末のみ）。

```bash
cp .env.example .env   # GEMINI_API_KEY を設定する
docker compose up -d --build
```

<http://localhost:8080/> を開きます。ホストの `127.0.0.1` にだけ公開し、アプリ側でも接続元を
Docker網のゲートウェイ（このホスト）に限ります。ポートは `HINAMI_COMPOSE_PORT` で、網のアドレス `172.29.90.0/24` が他と重なる場合は
`HINAMI_COMPOSE_SUBNET` と `HINAMI_COMPOSE_GATEWAY` で変えられます。他の人に公開する用途には使わないでください。

公開用に動かす場合は次のとおりです。

```bash
docker build -t hinami .
docker run -p 8080:8080 --env-file .env -v hinami-data:/app/data hinami
```

コンテナは `0.0.0.0` で待ち受けるため、`GOOGLE_OAUTH_CLIENT_ID` の設定（Googleログイン）が必要です。

## テスト

```bash
uv run python -m unittest discover -s backend/tests -p 'test_*.py'
npm --prefix frontend run build   # 型チェックを含む
```

## 今後の課題

- 画面文言の多言語化

## ライセンス

[Apache License 2.0](LICENSE)
