import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from sqlalchemy import delete

from app.db.sync_session import SessionLocal
from app.models.document import Document, DocumentStatus
from app.models.chunk import Chunk
from app.services.extraction import extract_text          # T-29
from app.services.chunking import chunk_text             # T-30
from app.services.embedding import embed_texts           # T-33
from app.utils.openai_client import check_and_increment_token_usage

logger = logging.getLogger(__name__)


def _run_async(coro):
    """
    Run an async coroutine from a synchronous RQ worker context.

    Uses a fresh event loop per call instead of asyncio.run() to avoid the
    "cannot run event loop while another is running" error that occurs when
    asyncio.run() is called inside a thread that already has a running loop
    (e.g., some RQ setups or test frameworks).
    """
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        try:
            # Cancel any lingering tasks before closing to prevent ResourceWarning
            pending = asyncio.all_tasks(loop)
            if pending:
                for task in pending:
                    task.cancel()
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        finally:
            loop.close()


def run_ingest(document_id: str) -> None:
    """
    RQ job entrypoint. Called by the worker process — sync only.

    Lifecycle:
        PENDING → PROCESSING → READY
                             → FAILED  (any exception)

    On failure: status set to FAILED, error written to job_logs.
    RQ handles retries (configured at enqueue time in documents.py).

    Retry safety:
        On RQ retry, the document may already be in PROCESSING (from the
        previous failed attempt). _run() handles this gracefully by cleaning
        up any partial state (existing chunks) before re-processing.
        If the document is READY (somehow succeeded on a parallel path),
        the job is skipped.
    """
    doc_uuid = uuid.UUID(document_id)

    with SessionLocal() as db:
        try:
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

    # If the document is already READY (e.g., a duplicate job or a race
    # between the RQ retry and a parallel worker), skip it entirely.
    if doc.status == DocumentStatus.READY:
        logger.warning(
            "ingest.already_ready",
            extra={"document_id": str(document_id)},
        )
        return

    # On retry, the status may already be PROCESSING or FAILED.
    # Reset to PROCESSING and clean up any partial chunks from the previous attempt.
    if doc.status in (DocumentStatus.PROCESSING, DocumentStatus.FAILED):
        logger.info(
            "ingest.retry_detected_cleaning_partial_state",
            extra={"document_id": str(document_id), "previous_status": str(doc.status)},
        )
        # Delete any chunks that were written in the previous failed attempt
        # to avoid duplicates on successful re-insert.
        db.execute(delete(Chunk).where(Chunk.document_id == document_id))

    doc.status = DocumentStatus.PROCESSING
    doc.updated_at = datetime.now(timezone.utc)
    db.commit()

    logger.info("ingest.started", extra={"document_id": str(document_id)})

    # ------------------------------------------------------------------ #
    # 2. Extract text from S3                                             #
    # ------------------------------------------------------------------ #
    # extract_text downloads from S3 using doc.s3_key and returns a
    # single cleaned string. Raises ExtractionError on corrupt/encrypted PDFs.
    raw_text = extract_text(s3_key=doc.s3_key, mime_type=doc.mime_type)

    # ------------------------------------------------------------------ #
    # 3. Chunk                                                            #
    # ------------------------------------------------------------------ #
    # chunk_text returns List[{ chunk_index, text, token_count }]
    chunks_data = chunk_text(raw_text)

    if not chunks_data:
        raise ValueError("Extraction produced no chunks — document may be empty.")

    # ------------------------------------------------------------------ #
    # 4. Cost check (token budget)                                        #
    # ------------------------------------------------------------------ #
    total_tokens = sum(c.token_count for c in chunks_data)
    _check_token_budget(total_tokens)

    # ------------------------------------------------------------------ #
    # 5. Embed                                                            #
    # ------------------------------------------------------------------ #
    # embed_texts handles batching internally (groups of 100).
    texts = [c.text for c in chunks_data]
    embeddings = embed_texts(texts)

    if len(embeddings) != len(chunks_data):
        raise ValueError(
            f"Embedding count mismatch: got {len(embeddings)}, expected {len(chunks_data)}"
        )

    # ------------------------------------------------------------------ #
    # 5b. Per-user daily token quota — charged AFTER embedding succeeds   #
    #                                                                     #
    # Charging BEFORE embedding means retries double-charge users even    #
    # when embedding fails (e.g., OpenAI timeout). We charge here, after  #
    # we know the API call succeeded and the tokens were actually used.    #
    # ------------------------------------------------------------------ #
    _run_async(
        check_and_increment_token_usage(str(doc.user_id), total_tokens)
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

    The original exception is preserved via the implicit exception chain;
    this function does not re-raise so RQ can observe the original exc.
    """
    import traceback
    from app.models.job_log import JobLog

    try:
        doc = db.get(Document, document_id)
        if doc is not None:
            doc.status = DocumentStatus.FAILED
            doc.error_message = str(exc)[:500]  # column is TEXT but be defensive
            doc.updated_at = datetime.now(timezone.utc)

        log = JobLog(
            id=uuid.uuid4(),
            document_id=document_id,
            error=str(exc)[:500],
            traceback=traceback.format_exc()[:5000],
        )
        db.add(log)
        db.commit()

        logger.error(
            "ingest.failed",
            extra={"document_id": str(document_id), "error": str(exc)},
            exc_info=True,
        )
    except Exception as db_exc:
        # If we can't even write the failure, log it and move on.
        # The original exception (exc) will still propagate to RQ via re-raise
        # in run_ingest(). This except block must NOT raise.
        logger.critical(
            "ingest.failed_to_write_failure",
            extra={"document_id": str(document_id), "db_error": str(db_exc)},
        )


# --------------------------------------------------------------------------- #
# Internal helpers                                                             #
# --------------------------------------------------------------------------- #

MAX_TOKENS_PER_DOCUMENT = 500_000  # ~$0.01 at text-embedding-3-small pricing


def _check_token_budget(total_tokens: int) -> None:
    if total_tokens > MAX_TOKENS_PER_DOCUMENT:
        raise ValueError(
            f"Document has {total_tokens:,} tokens; limit is {MAX_TOKENS_PER_DOCUMENT:,}. "
            "Split the document into smaller files."
        )
