from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from starlette.datastructures import Headers, MutableHeaders

ASGIApp = Callable[
    [dict[str, Any], Callable[..., Awaitable[dict[str, Any]]], Callable[..., Awaitable[None]]],
    Awaitable[None],
]


CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "base-uri 'self'",
        "object-src 'none'",
        "frame-ancestors 'none'",
        "form-action 'self'",
        "script-src 'self' https://accounts.google.com",
        "style-src 'self' 'unsafe-inline' https://accounts.google.com https://fonts.googleapis.com",
        "img-src 'self' data: blob: https://*.googleusercontent.com https://ssl.gstatic.com https://www.gstatic.com",
        "font-src 'self' data: https://fonts.gstatic.com",
        "connect-src 'self' https://accounts.google.com https://www.googleapis.com https://gmail.googleapis.com https://meet.googleapis.com https://api.open-meteo.com",
        "frame-src https://accounts.google.com",
        "media-src 'self' blob:",
        "worker-src 'self' blob:",
        "manifest-src 'self'",
    ]
)

SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": (
        "accelerometer=(), camera=(), display-capture=(), geolocation=(self), "
        "gyroscope=(), magnetometer=(), microphone=(self), payment=(), usb=()"
    ),
    "X-Permitted-Cross-Domain-Policies": "none",
    "X-XSS-Protection": "0",
}


def is_https_scope(scope: dict[str, Any]) -> bool:
    if scope.get("scheme") == "https":
        return True
    request_headers = Headers(scope=scope)
    forwarded_proto = request_headers.get("x-forwarded-proto", "")
    return forwarded_proto.split(",", 1)[0].strip().lower() == "https"


class SecurityHeadersMiddleware:
    """全HTTPレスポンスへブラウザ向けセキュリティヘッダーを付与する。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Callable, send: Callable) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    headers[name] = value

                if is_https_scope(scope):
                    headers["Strict-Transport-Security"] = "max-age=31536000"

                path = str(scope.get("path", ""))
                if path == "/api" or path.startswith("/api/"):
                    headers["Cache-Control"] = "no-store, max-age=0"
                    headers["Pragma"] = "no-cache"
                    headers["Expires"] = "0"
                elif path.startswith("/assets/") and message.get("status") == 200:
                    headers["Cache-Control"] = "public, max-age=31536000, immutable"
                elif headers.get("content-type", "").lower().startswith("text/html"):
                    headers["Cache-Control"] = "no-cache, max-age=0, must-revalidate"

            await send(message)

        await self.app(scope, receive, send_with_security_headers)
