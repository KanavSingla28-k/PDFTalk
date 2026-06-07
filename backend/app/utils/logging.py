"""
Structured logging configuration for PDFTalk.

Design:
  - Uses structlog for structured, context-aware logging.
  - In development (LOG_FORMAT=pretty or unset + non-production APP_URL):
      human-readable, coloured console output.
  - In production (LOG_FORMAT=json):
      newline-delimited JSON, one object per log line, safe for log
      aggregators (CloudWatch, Datadog, etc.).
  - PII is explicitly excluded. The scrub list below is the canonical
      reference — add to it when adding new sensitive fields.
  - Call configure_logging() once at app startup (in lifespan).

Usage anywhere in the app:
    import structlog
    log = structlog.get_logger()
    log.info("document.uploaded", document_id=str(doc.id), user_id=str(user_id))

Log fields on every request (injected by RequestLoggingMiddleware):
    request_id, method, path, status_code, duration_ms, client_ip
    user_id  (present only when the request carries a valid JWT)

Fields never logged (scrubbed at the processor level):
    password, password_hash, token, access_token, refresh_token,
    token_hash, email, email_lower, authorization, content (document text)
"""

import logging
import sys
import structlog
from structlog.typing import EventDict, WrappedLogger
from app.core.config import settings

# ---------------------------------------------------------------------------
# PII scrubbing processor
# ---------------------------------------------------------------------------

# Canonical list of keys that must NEVER appear in log output.
# Keys are matched case-insensitively.
_SCRUBBED_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "password_hash",
        "token",
        "access_token",
        "refresh_token",
        "token_hash",
        "email",
        "email_lower",
        "authorization",
        "content",          # document text — can be very large and contains user data
        "text",             # chunk text — same reason
        "secret",
        "api_key",
        "openai_api_key",
    }
)

_REDACTED = "[REDACTED]"


def _scrub_pii(
    logger: WrappedLogger,
    method: str,
    event_dict: EventDict,
) -> EventDict:
    """
    structlog processor that replaces sensitive values with [REDACTED].

    Operates on the top-level keys of event_dict only — we intentionally
    do not recurse into nested dicts because log call sites should pass
    scalar values, not raw ORM objects.
    """
    for key in list(event_dict.keys()):
        if key.lower() in _SCRUBBED_KEYS:
            event_dict[key] = _REDACTED
    return event_dict


# ---------------------------------------------------------------------------
# Public configuration entry point
# ---------------------------------------------------------------------------

def configure_logging() -> None:
    """
    Configure structlog and stdlib logging.
    Call exactly once, inside the FastAPI lifespan startup block.

    Log format is controlled by the LOG_FORMAT env var (via settings):
        "json"   → newline-delimited JSON  (production default)
        "pretty" → coloured human output   (development default)

    If LOG_FORMAT is not set, format is inferred from APP_URL:
        localhost → pretty
        anything else → json
    """
    log_format = _resolve_format()

    # Shared processors applied regardless of format
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,   # picks up bind_contextvars()
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _scrub_pii,
        structlog.processors.StackInfoRenderer(),
    ]

    if log_format == "json":
        # Production: machine-readable JSON, one object per line
        structlog.configure(
            processors=shared_processors
            + [
                structlog.processors.dict_tracebacks,
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(sys.stdout),
            cache_logger_on_first_use=True,
        )
    else:
        # Development: coloured, human-friendly output
        structlog.configure(
            processors=shared_processors
            + [
                structlog.dev.ConsoleRenderer(colors=True),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(sys.stdout),
            cache_logger_on_first_use=False,  # reflect config changes without restart
        )

    # Route stdlib logging (uvicorn, sqlalchemy, etc.) through structlog
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO if log_format == "json" else logging.DEBUG,
    )
    logging.getLogger("uvicorn.access").propagate = False  # avoid double-logging requests


def _resolve_format() -> str:
    """Return 'json' or 'pretty' based on settings."""
    fmt = getattr(settings, "LOG_FORMAT", None)
    if fmt in ("json", "pretty"):
        return fmt
    # Infer from APP_URL when LOG_FORMAT is not set
    return "pretty" if "localhost" in settings.APP_URL else "json"