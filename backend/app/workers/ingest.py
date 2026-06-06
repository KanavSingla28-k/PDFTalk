import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.sync_session import SessionLocal
from app.models.document import Document, DocumentStatus
from app.models.chunk import Chunk
from app.services.extraction import extract_text          # T-29
from app.services.chunking import chunk_text             # T-30
from app.services.embedding import embed_texts           # T-33
from app.utils.openai_client import check_and_increment_token_usage
import asyncio

logger = logging.getLogger(__name__)


def run_ingest(document_id: str) -> None:
    """
    RQ job entrypoint. Called by the worker process — sync only.

    Lifecycle:
        PENDING → PROCESSING → READY
                             → FAILED  (any exception)

    On failure: status set to FAILED, error written to job_logs.
    RQ handles retries (configured at enqueue time in documents.py).
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

    # Per-user daily quota — checked here because we have both user_id and
    # total_tokens available, and openai_client.create_embeddings() explicitly
    # delegates this responsibility to the caller.
    asyncio.run(
        check_and_increment_token_usage(str(doc.user_id), total_tokens)
    )

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