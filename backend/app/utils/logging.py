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
from typing import Any, cast
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

    stdlib logging is routed through structlog's ProcessorFormatter (I-03)
    so that all log output — including uvicorn, SQLAlchemy, openai SDK, and
    any remaining logging.getLogger() calls — goes through the same pipeline
    (PII scrubbing, JSON rendering).
    """
    log_format = _resolve_format()
    stdlib_level = logging.INFO if log_format == "json" else logging.DEBUG

    # Shared processors applied regardless of format
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,   # picks up bind_contextvars()
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level_number,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _scrub_pii,
        structlog.processors.StackInfoRenderer(),
    ]

    if log_format == "json":
        renderer: Any = structlog.processors.JSONRenderer()
        structlog.configure(
            processors=shared_processors
            + [
                structlog.processors.dict_tracebacks,
                renderer,
            ],
            wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(sys.stdout),
            cache_logger_on_first_use=True,
        )
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)
        structlog.configure(
            processors=shared_processors
            + [
                renderer,
            ],
            wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(sys.stdout),
            cache_logger_on_first_use=False,  # reflect config changes without restart
        )

    # ---------------------------------------------------------------------------
    # Route stdlib logging through structlog's processor chain (I-03)
    #
    # Without this, any logging.getLogger(__name__).warning() call (uvicorn,
    # SQLAlchemy, openai SDK, our own workers) bypasses PII scrubbing and JSON
    # rendering, emitting raw plain-text lines that corrupt structured log streams.
    #
    # ProcessorFormatter bridges stdlib → structlog:
    #   1. A stdlib StreamHandler wraps ProcessorFormatter
    #   2. ProcessorFormatter runs foreign_pre_chain then the same renderer
    #   3. The root logger is set to the same level as structlog
    # ---------------------------------------------------------------------------

    # foreign_pre_chain: processors run on records that arrive via stdlib logging.
    # add_logger_name injects {"logger": "uvicorn.error"} so the source is visible.
    foreign_pre_chain: list[Any] = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level_number,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _scrub_pii,
    ]

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=foreign_pre_chain,
        processor=renderer,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]   # replace any handlers added by earlier basicConfig calls
    root_logger.setLevel(stdlib_level)

    # Suppress uvicorn's access log — RequestLoggingMiddleware owns request logs
    logging.getLogger("uvicorn.access").propagate = False


def _resolve_format() -> str:
    """Return 'json' or 'pretty' based on settings."""
    fmt = getattr(settings, "LOG_FORMAT", None)
    if fmt in ("json", "pretty"):
        return cast(str, fmt)
    # Infer from APP_URL when LOG_FORMAT is not set
    return "pretty" if "localhost" in settings.APP_URL else "json"
