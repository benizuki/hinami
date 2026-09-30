# Hinami

Hinami（日次）は、AIとの短い対話から一日の仕事を振り返り、日々の記録として残すWebアプリです。
蓄積した記録から、チームのまとめや業務の見取り図も作成できます。

## 主な機能

- AIとの対話による日々の記録作成
- 音声入力、読み上げ、PDF・画像の添付
- チーム単位の記録と期間別まとめ
- 担当者、作業回数、資料の受け渡しを整理する業務の見取り図
- Gemini API または Vertex AI の利用
- Google Calendar、Meet、Gmail、Driveとの読み取り専用連携（任意）

## Quick Start

必要なものは Docker と Docker Compose です。

```bash
cp .env.example .env

docker compose up -d --build
```

起動したら <http://localhost:8080/> を開きます。

ログイン画面では任意のメールアドレスを入力できます。最初にログインしたユーザーが全体管理者になり、以降のユーザーは一般利用者として登録されます。

AIを使うには、ログイン後の「システム設定」からGemini APIキーまたはVertex AIを設定します。AIの接続方法やモデルも同じ画面で変更できます。

終了するには次を実行します。

```bash
docker compose down
```

> Docker Compose構成はローカルで試すためのものです。パスワードなしのデモログインを使い、`127.0.0.1` にだけ公開されます。他の端末やインターネットへ公開しないでください。

## データ

Docker Composeでは、記録や設定をDockerボリューム `hinami-data` に保存します。コンテナを作り直してもデータは残ります。

ローカル実行時のデータは、既定で `backend/app/data/` に保存されます。このディレクトリの実データ、`.env`、APIキー、認証情報はGitの追跡対象外です。

## 設定

利用できる環境変数と既定値は [.env.example](.env.example) を参照してください。主な設定は次のとおりです。

| 変数 | 用途 |
| --- | --- |
| `GOOGLE_OAUTH_CLIENT_ID` | GoogleログインとGoogleサービス連携 |
| `HINAMI_BOOTSTRAP_ADMIN_EMAILS` | 初回ログイン時に管理者とするメールアドレス |
| `APP_AUTH_SECRET` | ログイントークンの署名鍵 |
| `HINAMI_DATA_DIR` | データ保存先 |
| `HINAMI_COMPOSE_PORT` | Docker Composeで公開するポート（既定: `8080`） |

AIのAPIキー、接続方法、モデル、Vertex AI、Google連携は、ログイン後の「システム設定」から変更します。

## Google連携

Google OAuthを設定すると、ログイン中のユーザー本人のCalendar、Meet、Gmail、Driveを振り返りの手がかりとして参照できます。
各連携はシステム設定で個別に無効化できます。

連携データはブラウザから読み取り専用で取得します。会話の全文、メール本文、予定の説明、添付資料の本文、位置情報は保存しません。

`gmail.readonly` はGoogleの制限付きスコープです。

## 開発

必要なもの：Python 3.14、[uv](https://docs.astral.sh/uv/)、Node.js 24。

```bash
uv sync

npm --prefix frontend ci
npm --prefix frontend run build

cp .env.example .env

uv run python -m backend
```

<http://127.0.0.1:8000/> を開きます。

フロントエンドをViteの開発サーバーで動かす場合は、別のターミナルで次を実行します。

```bash
npm --prefix frontend run dev
```

## テスト

```bash
uv run python -m unittest discover -s backend/tests -p 'test_*.py'

npm --prefix frontend run build
```

## 技術構成

- Vue 3 / TypeScript / Vuetify 3 / Vite
- FastAPI / Python 3.14
- SQLite / JSON
- Gemini API / Vertex AI

## ライセンス

[Apache License 2.0](LICENSE)
