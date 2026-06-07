"""
RequestLoggingMiddleware — per-request structured logging for PDFTalk.

Responsibilities:
  1. Generate a UUID request_id and attach it to the response as
     X-Request-ID so callers can correlate client-side errors with
     server-side logs.
  2. Bind request_id into structlog's contextvars so EVERY log call
     inside the request (services, utilities, workers) automatically
     includes it — no manual passing required.
  3. Log a single summary line after the response is sent with:
       request_id, method, path, status_code, duration_ms, client_ip
       user_id  (extracted from JWT if present — no DB call)
  4. Log exceptions at ERROR level with traceback before re-raising,
     so the existing exception handlers in exceptions.py still form
     the HTTP response.

What is NOT logged:
  - Request/response bodies (may contain document text or credentials)
  - Query strings that could carry tokens (e.g. /verify-email?token=...)
    → path is logged but query string is stripped
  - Any key in the _SCRUBBED_KEYS set in utils/logging.py

Execution order in the middleware stack (last added = outermost):
  RequestLogging → SecurityHeaders → CORS → route handler
  (RequestLogging is added last in main.py so it wraps everything)
"""

import time
import uuid

import structlog
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.auth.tokens import _decode_token_unverified

log = structlog.get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = str(uuid.uuid4())
        start = time.perf_counter()

        # Bind request_id into contextvars — all log calls in this request
        # will automatically include it, regardless of call depth.
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        # Best-effort user_id extraction — read JWT without a DB round-trip.
        # On any failure we simply omit user_id from the log (not an error).
        user_id = _extract_user_id(request)
        if user_id:
            structlog.contextvars.bind_contextvars(user_id=user_id)

        try:
            response: Response = await call_next(request)
        except Exception as exc:
            duration_ms = _elapsed_ms(start)
            log.error(
                "request.error",
                method=request.method,
                path=request.url.path,           # query string intentionally excluded
                client_ip=_get_client_ip(request),
                duration_ms=duration_ms,
                error=type(exc).__name__,
                exc_info=True,                   # includes traceback in JSON output
            )
            raise  # existing exception handlers in exceptions.py form the response

        duration_ms = _elapsed_ms(start)

        # Attach request_id to response so clients can reference it in
        # support requests / bug reports.
        response.headers["X-Request-ID"] = request_id

        log.info(
            "request.completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            client_ip=_get_client_ip(request),
        )

        return response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _get_client_ip(request: Request) -> str:
    """
    Return the real client IP, preferring X-Forwarded-For set by Nginx.
    Falls back to the direct connection IP (useful in local dev without Nginx).
    """
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # X-Forwarded-For can be a comma-separated list; first entry is the client
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _extract_user_id(request: Request) -> str | None:
    """
    Pull user_id from the Bearer token without hitting the DB.
    Returns None on any failure (missing header, bad token, etc.).
    Never raises.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header.removeprefix("Bearer ").strip()
    try:
        return _decode_token_unverified(token)
    except Exception:
        return None