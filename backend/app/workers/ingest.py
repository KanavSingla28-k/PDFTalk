import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from sqlalchemy import delete
from typing import TypeVar, Coroutine, Any

from app.db.sync_session import SessionLocal
from app.models.document import Document, DocumentStatus
from app.models.chunk import Chunk
from app.services.extraction import extract_text
from app.services.chunking import chunk_text
from app.services.embedding import embed_texts
from app.utils.openai_client import (
    check_and_increment_token_usage,
    CircuitBreakerOpenError,
    DailyQuotaExceededError,
    OpenAIRetryExhaustedError,
)
from app.utils.metrics import (
    documents_processed_total,
    documents_failed_total,
    processing_duration_seconds,
    openai_tokens_used_total,
)

logger = logging.getLogger(__name__)


T = TypeVar("T")

def _run_async(coro: Coroutine[Any, Any, T]) -> T:
    """
    Run an async coroutine from a synchronous RQ worker context.
    """
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        try:
            pending = asyncio.all_tasks(loop)
            if pending:
                for task in pending:
                    task.cancel()
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        finally:
            loop.close()


def _classify_error(exc: Exception) -> str:
    """Map an exception to a label string for documents_failed_total."""
    if isinstance(exc, (DailyQuotaExceededError,)):
        return "quota_exceeded"
    if isinstance(exc, (CircuitBreakerOpenError, OpenAIRetryExhaustedError)):
        return "embedding_error"
    # ValueError from extraction ("no chunks", corrupt PDF, etc.)
    if isinstance(exc, ValueError) and any(
        kw in str(exc).lower() for kw in ("extract", "chunk", "empty", "corrupt")
    ):
        return "extraction_error"
    return "unknown"


def run_ingest(document_id: str) -> None:
    """
    RQ job entrypoint. Called by the worker process — sync only.

    Lifecycle:
        PENDING → PROCESSING → READY
                             → FAILED  (any exception)
    """
    doc_uuid = uuid.UUID(document_id)

    with SessionLocal() as db:
        try:
            with processing_duration_seconds.time():
                _run(db, doc_uuid)
        except Exception as exc:
            _fail(db, doc_uuid, exc)
            raise  # Re-raise so RQ records the failure and triggers retry logic


def _run(db: Session, document_id: uuid.UUID) -> None:
    # ------------------------------------------------------------------ #
    # 1. Fetch document + mark PROCESSING                                 #
    # ------------------------------------------------------------------ #
    doc = db.get(Document, document_id)
    if doc is None:
        raise ValueError(f"Document {document_id} not found in DB.")

    if doc.status == DocumentStatus.READY:
        logger.warning(
            "ingest.already_ready",
            extra={"document_id": str(document_id)},
        )
        return

    if doc.status in (DocumentStatus.PROCESSING, DocumentStatus.FAILED):
        logger.info(
            "ingest.retry_detected_cleaning_partial_state",
            extra={"document_id": str(document_id), "previous_status": str(doc.status)},
        )
        db.execute(delete(Chunk).where(Chunk.document_id == document_id))

    doc.status = DocumentStatus.PROCESSING
    doc.updated_at = datetime.now(timezone.utc)
    db.commit()

    logger.info("ingest.started", extra={"document_id": str(document_id)})

    # ------------------------------------------------------------------ #
    # 2. Extract text from S3                                             #
    # ------------------------------------------------------------------ #
    raw_text = extract_text(s3_key=doc.s3_key, mime_type=doc.mime_type)

    # ------------------------------------------------------------------ #
    # 3. Chunk                                                            #
    # ------------------------------------------------------------------ #
    chunks_data = chunk_text(raw_text)

    if not chunks_data:
        raise ValueError("Extraction produced no chunks — document may be empty.")

    # ------------------------------------------------------------------ #
    # 4. Cost check (token budget)                                        #
    # ------------------------------------------------------------------ #
    total_tokens = sum(c.token_count for c in chunks_data)
    _check_token_budget(total_tokens)

    # ------------------------------------------------------------------ #
    # 4b. Per-user daily token quota — charged BEFORE calling OpenAI      #
    #     so we never bill the account if the user is already over quota. #
    # ------------------------------------------------------------------ #
    _run_async(
        check_and_increment_token_usage(str(doc.user_id), total_tokens)
    )

    # ------------------------------------------------------------------ #
    # 5. Embed                                                            #
    # ------------------------------------------------------------------ #
    texts = [c.text for c in chunks_data]
    embeddings = embed_texts(texts)

    if len(embeddings) != len(chunks_data):
        raise ValueError(
            f"Embedding count mismatch: got {len(embeddings)}, expected {len(chunks_data)}"
        )

    # ------------------------------------------------------------------ #
    # 6. Bulk-insert chunks + embeddings                                  #
    # ------------------------------------------------------------------ #
    chunk_rows = [
        Chunk(
            id=uuid.uuid4(),
            document_id=document_id,
            user_id=doc.user_id,
            chunk_index=c.chunk_index,
            text=c.text,
            token_count=c.token_count,
            embedding=embeddings[i],
        )
        for i, c in enumerate(chunks_data)
    ]

    db.add_all(chunk_rows)

    # ------------------------------------------------------------------ #
    # 7. Mark READY                                                       #
    # ------------------------------------------------------------------ #
    doc.status = DocumentStatus.READY
    doc.chunk_count = len(chunk_rows)
    doc.updated_at = datetime.now(timezone.utc)

    db.commit()  # Single commit — chunks + status update are atomic

    # Metrics — after commit so we only count genuinely successful ingestions
    documents_processed_total.labels(user_id=str(doc.user_id)).inc()
    openai_tokens_used_total.labels(kind="embedding").inc(total_tokens)

    logger.info(
        "ingest.completed",
        extra={
            "document_id": str(document_id),
            "chunk_count": len(chunk_rows),
            "total_tokens": total_tokens,
        },
    )


def _fail(db: Session, document_id: uuid.UUID, exc: Exception) -> None:
    """
    Mark document FAILED and write a job_log row.
    Best-effort — if the DB itself is down, this will also fail (acceptable).
    """
    import traceback
    from app.models.job_log import JobLog

    try:
        doc = db.get(Document, document_id)
        if doc is not None:
            doc.status = DocumentStatus.FAILED
            doc.error_message = str(exc)[:500]
            doc.updated_at = datetime.now(timezone.utc)

        log = JobLog(
            id=uuid.uuid4(),
            document_id=document_id,
            error=str(exc)[:500],
            traceback=traceback.format_exc()[:5000],
        )
        db.add(log)
        db.commit()

        documents_failed_total.labels(reason=_classify_error(exc)).inc()

        logger.error(
            "ingest.failed",
            extra={"document_id": str(document_id), "error": str(exc)},
            exc_info=True,
        )
    except Exception as db_exc:
        logger.critical(
            "ingest.failed_to_write_failure",
            extra={"document_id": str(document_id), "db_error": str(db_exc)},
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

MAX_TOKENS_PER_DOCUMENT = 500_000


def _check_token_budget(total_tokens: int) -> None:
    if total_tokens > MAX_TOKENS_PER_DOCUMENT:
        raise ValueError(
            f"Document has {total_tokens:,} tokens; limit is {MAX_TOKENS_PER_DOCUMENT:,}. "
            "Split the document into smaller files."
        )
