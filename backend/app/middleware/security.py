from collections.abc import Awaitable, Callable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.path in ["/docs", "/redoc", "/openapi.json"]:
            # These routes only exist in development (settings.is_production=False disables
            # them in main.py). This branch is dead code in production — kept here so that
            # local dev still gets a permissive CSP that lets the Swagger UI load correctly.
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com"
            )
        else:
            # CSP: API returns JSON only — no scripts, styles, or embedded resources.
            # default-src 'none' is the strictest possible policy and safe for a pure JSON API.
            response.headers["Content-Security-Policy"] = "default-src 'none'"
        # NOTE: HSTS is intentionally omitted — Nginx owns it for the full domain (T-57)
        return response
