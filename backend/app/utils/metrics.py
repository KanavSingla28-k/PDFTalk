"""
app/utils/metrics.py

All Prometheus metric objects are defined here as module-level singletons.

Rules:
  - Import from this module everywhere — never instantiate Counter/Gauge/Histogram
    inside a function. Prometheus raises ValueError on duplicate registration,
    which happens the moment a module is imported more than once.
  - Add .inc() / .observe() calls at the call site (services, workers, utils).
  - Labels with high cardinality (e.g. user_id) are only used on low-frequency
    metrics (documents_processed_total). Never on queries_total or stream errors.
"""

from prometheus_client import Counter, Gauge, Histogram

# ── Ingestion pipeline ────────────────────────────────────────────────────────

documents_processed_total = Counter(
    "pdftalk_documents_processed_total",
    "Documents that completed ingestion successfully",
    ["user_id"],
)

documents_failed_total = Counter(
    "pdftalk_documents_failed_total",
    "Documents that entered FAILED state",
    ["reason"],  # "extraction_error" | "quota_exceeded" | "embedding_error" | "unknown"
)

processing_duration_seconds = Histogram(
    "pdftalk_processing_duration_seconds",
    "Wall-clock time for the full ingest pipeline (extract→chunk→embed→store)",
    buckets=[5, 10, 30, 60, 120, 300, 600],
)

document_end_to_end_latency_seconds = Histogram(
    "pdftalk_document_end_to_end_latency_seconds",
    "Wall-clock time from document creation to READY status, including queue time",
    buckets=[5, 10, 30, 60, 120, 300, 600],
)

queue_length = Gauge(
    "pdftalk_queue_length",
    "Current number of jobs waiting in the RQ ingest queue",
)

dead_letter_queue_length = Gauge(
    "pdftalk_dead_letter_queue_length",
    "Jobs in the RQ FailedJobRegistry (exhausted all retries)",
)

# ── External service errors ───────────────────────────────────────────────────

openai_errors_total = Counter(
    "pdftalk_openai_errors_total",
    "Errors returned by the OpenAI API",
    ["error_type"],  # "rate_limit" | "timeout" | "server_error" | "quota_exceeded"
)

s3_errors_total = Counter(
    "pdftalk_s3_errors_total",
    "Errors returned by AWS S3",
    ["operation"],  # "upload" | "download" | "delete"
)

# ── Auth & user activity ──────────────────────────────────────────────────────

user_registrations_total = Counter(
    "pdftalk_user_registrations_total",
    "Total user registrations (includes unverified)",
)

user_logins_total = Counter(
    "pdftalk_user_logins_total",
    "Successful logins",
)

login_failures_total = Counter(
    "pdftalk_login_failures_total",
    "Failed login attempts",
    ["reason"],  # "wrong_password" | "locked" | "unverified" | "not_found" | "inactive"
)

emails_sent_total = Counter(
    "pdftalk_emails_sent_total",
    "Emails dispatched via Resend",
    ["type"],  # "verification" | "password_reset"
)

# ── Token quota ───────────────────────────────────────────────────────────────

openai_tokens_used_total = Counter(
    "pdftalk_openai_tokens_used_total",
    "Cumulative OpenAI tokens consumed",
    ["kind"],  # "embedding" | "completion"
)

daily_quota_breaches_total = Counter(
    "pdftalk_daily_quota_breaches_total",
    "Times a user hit their daily token quota ceiling",
)

# ── Query / streaming ─────────────────────────────────────────────────────────

queries_total = Counter(
    "pdftalk_queries_total",
    "Total RAG queries submitted",
)

stream_errors_total = Counter(
    "pdftalk_stream_errors_total",
    "SSE stream errors",
    [
        "error_code"
    ],  # "STREAM_TIMEOUT" | "DAILY_QUOTA_EXCEEDED" | "AI_SERVICE_UNAVAILABLE" | "STREAM_ERROR"
)

messages_total = Counter(
    "pdftalk_messages_total",
    "Total messages saved to the database",
    ["role"],  # "user" | "assistant"
)

chat_query_blocked_total = Counter(
    "pdftalk_chat_query_blocked_total",
    "Times a chat query was blocked",
    ["reason"],  # "all_documents_deleted"
)
