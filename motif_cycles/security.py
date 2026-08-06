from __future__ import annotations

import hmac
import secrets
from urllib.parse import urlparse

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response


class LocalGuard:
    def __init__(self):
        self.token = secrets.token_urlsafe(32)

    def valid(self, value: str | None) -> bool:
        return bool(value) and hmac.compare_digest(value, self.token)

    @staticmethod
    def local_origin(value: str) -> bool:
        try:
            return urlparse(value).hostname in {"127.0.0.1", "localhost", "::1"}
        except ValueError:
            return False


class LocalSecurityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, guard: LocalGuard):
        super().__init__(app)
        self.guard = guard

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path.startswith(
            "/api/"
        ):
            origin = request.headers.get("origin")
            if origin and not self.guard.local_origin(origin):
                return JSONResponse({"detail": "Untrusted browser origin."}, status_code=403)
            if not self.guard.valid(request.headers.get("x-motif-cycles-token")):
                return JSONResponse({"detail": "Missing or invalid local token."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; "
            "form-action 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
            "connect-src 'self'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response
