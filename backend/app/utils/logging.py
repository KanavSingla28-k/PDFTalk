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

from typing import List
import logging
from typing import cast
import structlog
from structlog.types import Processor
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
        "content",  # document text — can be very large and contains user data
        "text",  # chunk text — same reason
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


def _copy_stdlib_extras(
    logger: WrappedLogger,
    method: str,
    event_dict: EventDict,
) -> EventDict:
    """
    Copy stdlib LogRecord extra attributes into the structlog event dict.

    This ensures that fields logged via stdlib's `extra=` (like Sentinel's
    `identity_mode`, `identity_hash`, `endpoint_id`, `decision_reason`,
    `latency_micro`, `breaker_state`) are preserved in the JSON output.
    """
    # structlog passes the stdlib LogRecord as `record` in the event dict
    # when using ProcessorFormatter with foreign_pre_chain.
    record = event_dict.get("record")
    if record is not None:
        for key, value in record.__dict__.items():
            if key not in event_dict and not key.startswith("_"):
                event_dict[key] = value
    return event_dict


# ---------------------------------------------------------------------------
# Public configuration entry point
# ---------------------------------------------------------------------------


def configure_logging() -> None:
    shared_processors: List[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,  # safe once stdlib is wired
        structlog.processors.TimeStamper(fmt="iso"),
        _copy_stdlib_extras,
        _scrub_pii,
    ]

    structlog.configure(
        processors=shared_processors
        + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),  # ← THIS is the missing line
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)


def _resolve_format() -> str:
    """Return 'json' or 'pretty' based on settings."""
    fmt = getattr(settings, "LOG_FORMAT", None)
    if fmt in ("json", "pretty"):
        return cast(str, fmt)
    # Infer from APP_URL when LOG_FORMAT is not set
    return "pretty" if "localhost" in settings.APP_URL else "json"
