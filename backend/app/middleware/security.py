from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from typing import Callable, Awaitable


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        # CSP: API returns JSON only — no scripts, styles, or embedded resources.
        # default-src 'none' is the strictest possible policy and safe for a pure JSON API.
        response.headers["Content-Security-Policy"] = "default-src 'none'"
        # NOTE: HSTS is intentionally omitted — Nginx owns it for the full domain (T-57)
        return response
