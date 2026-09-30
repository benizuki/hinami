"""② Vertex AI（Google Cloud）への接続：プロジェクト、リージョン、認証。

Vertex AI と Cloud Text-to-Speech で共通に使う。設定はシステム全体で1つで、システム管理者が画面から変える。
プロジェクトとリージョンは、画面で空なら GOOGLE_CLOUD_PROJECT / GOOGLE_CLOUD_LOCATION（既定 global）に従う。

認証の方法は選ばせず、動いている場所で自動で決める。
- Kubernetes 上で、Workload Identity 連携（WIF）の識別子が設定されている → WIF
  （Pod の ServiceAccount のトークンを、画面の audience で取得して Google の一時的な認証に交換する）
- それ以外 → google.auth.default()（ADC）
  （ローカルの gcloud ログイン、鍵ファイル、GCE のサービスアカウント、
   GOOGLE_APPLICATION_CREDENTIALS で渡した WIF の構成ファイルのどれか）
WIF の識別子は秘密ではないので、そのまま保存する（鍵もトークンも保存しない）。
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from .paths import RUNTIME_DATA_DIR

GOOGLE_CLOUD_AUTH_FILE = RUNTIME_DATA_DIR / "settings" / "google_cloud.json"
DEFAULT_VERTEX_LOCATION = "global"
CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
DEFAULT_GOOGLE_CLOUD_AUTH: dict[str, str] = {
    "project": "",
    "location": "",
    # Kubernetes 上でだけ使う Workload Identity 連携の識別子。どれも空なら使わない。
    "wif_project_number": "",
    "wif_pool_id": "",
    "wif_provider_id": "",
    "wif_service_account": "",
}
WIF_REQUIRED_KEYS = ("wif_project_number", "wif_pool_id", "wif_provider_id")
PROJECT_NUMBER_PATTERN = re.compile(r"\d{6,20}")
POOL_ID_PATTERN = re.compile(r"[a-z0-9-]{4,32}")
PROJECT_ID_PATTERN = re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]")
LOCATION_PATTERN = re.compile(r"[a-z0-9-]{2,40}")
SERVICE_ACCOUNT_PATTERN = re.compile(r"[a-z0-9-]{6,30}@[a-z0-9-]+\.iam\.gserviceaccount\.com")
ActiveAuth = Literal["adc", "wif"]
logger = logging.getLogger(__name__)


def load_google_cloud_auth() -> dict[str, str]:
    try:
        raw = json.loads(GOOGLE_CLOUD_AUTH_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raw = {}
    except (OSError, json.JSONDecodeError):
        logger.warning("Google Cloud auth settings could not be read; using defaults.", exc_info=True)
        raw = {}
    settings = dict(DEFAULT_GOOGLE_CLOUD_AUTH)
    if isinstance(raw, dict):
        settings.update({key: str(raw[key]) for key in DEFAULT_GOOGLE_CLOUD_AUTH if isinstance(raw.get(key), str)})
    return settings


def validate_google_cloud_auth(values: Mapping[str, object]) -> dict[str, str]:
    """保存する前に形を確かめる。問題があれば ValueError（利用者向けの文言）。"""
    settings = {
        key: str(values.get(key, default) or "").strip() for key, default in DEFAULT_GOOGLE_CLOUD_AUTH.items()
    }
    if settings["project"] and not PROJECT_ID_PATTERN.fullmatch(settings["project"]):
        raise ValueError("プロジェクトIDの形式が正しくありません（プロジェクト番号ではなくIDです）。")
    if settings["location"] and not LOCATION_PATTERN.fullmatch(settings["location"]):
        raise ValueError("リージョンの形式が正しくありません（例: global、asia-northeast1）。")
    # WIF は任意。使うなら、プール番号・プール・プロバイダーをそろえる。
    if any(settings[key] for key in (*WIF_REQUIRED_KEYS, "wif_service_account")):
        if not PROJECT_NUMBER_PATTERN.fullmatch(settings["wif_project_number"]):
            raise ValueError("プールのプロジェクト番号は数字で入力してください（プロジェクトIDではありません）。")
        if not POOL_ID_PATTERN.fullmatch(settings["wif_pool_id"]):
            raise ValueError("プールIDは英小文字・数字・ハイフンの4〜32文字で入力してください。")
        if not POOL_ID_PATTERN.fullmatch(settings["wif_provider_id"]):
            raise ValueError("プロバイダーIDは英小文字・数字・ハイフンの4〜32文字で入力してください。")
        # なりすまし先は任意。空なら Kubernetes の身元に直接権限を付ける（koyorina と同じ）。
        account = settings["wif_service_account"]
        if account and not SERVICE_ACCOUNT_PATTERN.fullmatch(account):
            raise ValueError("なりすまし先のサービスアカウントは、メールアドレスの形式で入力してください（使わない場合は空欄）。")
    return settings


def environment_google_cloud() -> dict[str, str]:
    """画面で空のときに使われるプロジェクトとリージョン。"""
    return {
        "project": os.getenv("GOOGLE_CLOUD_PROJECT", "").strip(),
        "location": os.getenv("GOOGLE_CLOUD_LOCATION", "").strip() or DEFAULT_VERTEX_LOCATION,
    }


def effective_google_cloud() -> dict[str, str]:
    """画面の値を優先し、空のプロジェクトとリージョンを環境変数で埋めたもの。"""
    settings = load_google_cloud_auth()
    environment = environment_google_cloud()
    return {**settings, **{key: settings[key] or environment[key] for key in ("project", "location")}}


def save_google_cloud_auth(values: Mapping[str, object]) -> dict[str, str]:
    settings = validate_google_cloud_auth(values)
    write_settings_file(GOOGLE_CLOUD_AUTH_FILE, settings)
    return settings


def write_settings_file(path: Path, settings: Mapping[str, object]) -> None:
    """書き終えてから置き換える。読み手が書きかけの設定を読むことはない。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(settings), handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def wif_configured(settings: Mapping[str, str]) -> bool:
    return all(settings[key] for key in WIF_REQUIRED_KEYS)


def active_auth() -> ActiveAuth:
    """いま使う認証。Kubernetes 上で WIF が設定されていれば wif、それ以外は adc（google.auth.default）。"""
    from .k8s_token import running_on_kubernetes

    if wif_configured(load_google_cloud_auth()) and running_on_kubernetes():
        return "wif"
    return "adc"


def wif_pool_path(settings: Mapping[str, str]) -> str:
    return (
        f"projects/{settings['wif_project_number']}/locations/global/"
        f"workloadIdentityPools/{settings['wif_pool_id']}"
    )


def wif_audience(settings: Mapping[str, str]) -> str:
    """STS に渡す audience。Kubernetes のトークンもこの audience で発行してもらう。"""
    return f"//iam.googleapis.com/{wif_pool_path(settings)}/providers/{settings['wif_provider_id']}"


def wif_credential_config(settings: Mapping[str, str]) -> dict:
    """google-auth の external_account の設定。トークンの取り方は k8s_token が差し替える。

    なりすまし先が空なら、交換したトークンをそのまま使う（Kubernetes の身元に直接付けた権限で呼ぶ）。
    """
    config = {
        "type": "external_account",
        "audience": wif_audience(settings),
        "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
        "token_url": "https://sts.googleapis.com/v1/token",
    }
    if settings["wif_service_account"]:
        config["service_account_impersonation_url"] = (
            "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/"
            f"{settings['wif_service_account']}:generateAccessToken"
        )
    return config


def quota_project() -> str | None:
    """サービスアカウントを使わない WIF のとき、利用量と課金を数えるプロジェクト。

    外部の身元のトークンにはプロジェクトが付かないため、Cloud Text-to-Speech のように
    プロジェクトを引数に取らない API では明示する必要がある。② のプロジェクト、無ければプールの
    プロジェクトを使う。それ以外は None。
    """
    settings = effective_google_cloud()
    if active_auth() == "wif" and not settings["wif_service_account"]:
        return settings["project"] or settings["wif_project_number"] or None
    return None


def credentials_key() -> tuple[str, ...]:
    """いまの認証を表すキー。クライアントを認証ごとに作り分けるのに使う。"""
    if active_auth() == "wif":
        settings = load_google_cloud_auth()
        return ("wif", wif_audience(settings), settings["wif_service_account"])
    return ("adc",)


def google_cloud_credentials() -> Any:
    """adc なら None（各クライアントが google.auth.default() で探す）。wif なら Kubernetes のトークンを交換する認証情報。"""
    return _credentials_for(credentials_key())


@lru_cache(maxsize=4)
def _credentials_for(key: tuple[str, ...]) -> Any:
    if key[0] != "wif":
        return None
    from . import k8s_token

    return k8s_token.credentials(
        wif_credential_config(load_google_cloud_auth()), k8s_token.KubernetesTokenSupplier(key[1])
    )


def refresh_google_cloud_credentials() -> None:
    """いまの認証で、実際にアクセストークンを取れるかを確かめる。

    wif ならトークンの交換（STS となりすまし）まで、adc なら google.auth.default() が見つけた
    認証情報（gcloud のログインや鍵ファイル）でトークンを取るところまで進める。
    """
    import google.auth
    import google.auth.transport.requests

    credentials = google_cloud_credentials()
    if credentials is None:
        credentials, _ = google.auth.default(scopes=[CLOUD_PLATFORM_SCOPE])
    credentials.refresh(google.auth.transport.requests.Request())


def describe_auth_error(exc: Exception) -> str:
    """アクセストークンを取れなかった理由を、次に何をすればよいか分かる言葉にする。"""
    name = type(exc).__name__
    if name == "DefaultCredentialsError":
        return (
            "Google Cloud の認証情報が見つかりません。ローカルでは `gcloud auth application-default login` を実行してください。"
            "Docker では鍵ファイルや WIF の構成ファイルを GOOGLE_APPLICATION_CREDENTIALS で渡すか、"
            "~/.config/gcloud をコンテナにマウントしてください。"
        )
    if name == "RefreshError":
        return f"アクセストークンを取得できませんでした。ログインの期限切れや権限を確認してください。（{str(exc)[:300]}）"
    return str(exc)[:500]
