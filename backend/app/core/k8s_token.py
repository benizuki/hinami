"""Hinami が、自分の Kubernetes ServiceAccount のトークンを audience 付きで取得する（WIF 用）。

Workload Identity 連携の audience は画面（システム設定）で変えられる。投影ボリュームだと
audience が Pod の定義に固定されるので、TokenRequest API で都度取得する。
必要な権限は、自分の ServiceAccount に対する serviceaccounts/token の create だけ。
"""

from __future__ import annotations

import base64
import json
import ssl
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

SERVICE_ACCOUNT_DIR = Path("/var/run/secrets/kubernetes.io/serviceaccount")
API = "https://kubernetes.default.svc"
LIFETIME = 3600
# 期限の少し前に取り直す。STS との往復の途中で切れないように。
MARGIN = 300


class TokenUnavailable(RuntimeError):
    pass


def running_on_kubernetes() -> bool:
    """Pod に ServiceAccount のトークンがマウントされているか。ローカルや素の Docker では False。"""
    return (SERVICE_ACCOUNT_DIR / "token").is_file()


def identity(directory: Path = SERVICE_ACCOUNT_DIR) -> tuple[str, str]:
    """自分の namespace と ServiceAccount 名。マウントされたトークンの sub から読む。"""
    try:
        token = (directory / "token").read_text().strip()
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        _, _, namespace, name = claims["sub"].split(":", 3)
        return namespace, name
    except (OSError, IndexError, KeyError, ValueError):
        raise TokenUnavailable("Kubernetes の ServiceAccount を確認できません。Kubernetes 上で動かしてください。") from None


def subject(directory: Path = SERVICE_ACCOUNT_DIR) -> str:
    namespace, name = identity(directory)
    return f"system:serviceaccount:{namespace}:{name}"


def _request(method: str, path: str, directory: Path, body: dict | None = None) -> dict:
    own = (directory / "token").read_text().strip()
    context = ssl.create_default_context(cafile=str(directory / "ca.crt"))
    request = urllib.request.Request(
        API + path,
        method=method,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers={"Authorization": "Bearer " + own, "Content-Type": "application/json"},
    )
    # プロキシの環境変数に左右されず、クラスタ内の API へ直接つなぐ。
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
    with opener.open(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


class KubernetesTokenSupplier:
    """google-auth から呼ばれ、audience 付きのトークンを返す。期限まで使い回す。"""

    def __init__(self, audience: str, directory: Path = SERVICE_ACCOUNT_DIR):
        self.audience, self.directory = audience, directory
        self._token, self._expires, self._lock = "", 0.0, threading.Lock()

    def get_subject_token(self, context: Any, request: Any) -> str:
        with self._lock:
            if self._token and time.time() < self._expires - MARGIN:
                return self._token
            namespace, name = identity(self.directory)
            try:
                body = _request(
                    "POST",
                    f"/api/v1/namespaces/{namespace}/serviceaccounts/{name}/token",
                    self.directory,
                    {
                        "apiVersion": "authentication.k8s.io/v1",
                        "kind": "TokenRequest",
                        "spec": {"audiences": [self.audience], "expirationSeconds": LIFETIME},
                    },
                )
                self._token = body["status"]["token"]
            except (OSError, urllib.error.URLError, KeyError, ValueError):
                raise TokenUnavailable(
                    "Kubernetes からトークンを取得できませんでした。serviceaccounts/token の権限を確認してください。"
                ) from None
            self._expires = time.time() + LIFETIME
            return self._token


def credentials(config: dict, supplier: KubernetesTokenSupplier) -> Any:
    """external_account の設定のうち、トークンの取り方だけをこのプロセスに差し替える。"""
    from google.auth import identity_pool

    class _Supplier(identity_pool.SubjectTokenSupplier):
        def get_subject_token(self, context, request):  # noqa: D401 - google-auth の呼び出し口
            return supplier.get_subject_token(context, request)

    return identity_pool.Credentials(
        audience=config["audience"],
        subject_token_type=config["subject_token_type"],
        token_url=config["token_url"],
        subject_token_supplier=_Supplier(),
        service_account_impersonation_url=config.get("service_account_impersonation_url"),
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )


def cluster_get(path: str, directory: Path = SERVICE_ACCOUNT_DIR) -> dict:
    """OIDC の発見用の読み取り（発行元と公開鍵）。秘密ではない。"""
    try:
        return _request("GET", path, directory)
    except (OSError, urllib.error.URLError, ValueError):
        raise TokenUnavailable("クラスタの OIDC 情報を読めませんでした。") from None
