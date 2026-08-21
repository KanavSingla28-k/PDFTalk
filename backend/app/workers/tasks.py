"""
workers/tasks.py

Periodic cleanup jobs that run on a self-scheduling RQ loop.

─────────────────────────────────────────────────────────────────────────────
S3 ORPHAN OBJECT ANALYSIS
─────────────────────────────────────────────────────────────────────────────

Two distinct ways an S3 object can become an orphan (no active DB row pointing
to it):

  Scenario A — Abandoned upload (most common)
      1. Browser calls POST /initiate-upload  →  DB row written (PENDING_UPLOAD)
                                              →  presigned URL returned
      2. Browser PUTs the file directly to S3 (or doesn't — either way)
      3. Browser never calls POST /confirm-upload (tab closed, crash, network
         loss, user rage-quit)
      Result: DB row exists in PENDING_UPLOAD, real S3 object may or may not
      exist.  The stale-cleanup job catches the DB row and marks it FAILED, but
      the *previous* implementation never deleted the S3 object.  If the PUT
      completed, the object would sit in S3 forever, billed and invisible.

  Scenario B — Invisible orphan (no DB row at all)
      Theoretically possible if the presigned URL is generated but the DB
      INSERT fails AFTER a commit-flush boundary, or if a future code change
      reverses the ordering of DB-write and URL-generation.  In the current
      implementation the DB commit happens BEFORE the URL is generated, so
      this scenario cannot occur — but it is listed here for completeness and
      future-proofing.

TWO-LAYER DEFENCE:
  1. Code layer  — _cleanup_stale_pending_uploads() (this file)
                   Deletes S3 objects for every stale PENDING_UPLOAD row
                   *before* transitioning the row to FAILED.  Handles
                   Scenario A completely.
  2. S3 lifecycle rule — infra/s3_lifecycle.json
                   An S3 object expiration rule scoped to the upload prefix
                   (set to 1 day) that acts as a belt-and-suspenders catch
                   for Scenario B and for any Scenario A objects that slip
                   through the code layer (e.g., cleanup crashed mid-run).
                   Apply via: aws s3api put-bucket-lifecycle-configuration
─────────────────────────────────────────────────────────────────────────────
"""

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from redis import Redis
from rq import Queue
from sqlalchemy import select
from sqlalchemy.orm import Session

# from typing import cast
from app.db.sync_session import SessionLocal
from app.models.document import Document, DocumentStatus
from app.models.job_log import JobLog

logger = structlog.get_logger(__name__)


def _cleanup_stale_pending_uploads(
    db: Session,
    cutoff: datetime,
) -> list[Document]:
    """
    Find PENDING_UPLOAD documents older than *cutoff*, delete their S3 objects,
    then transition the DB rows to FAILED.

    S3 deletion is **best-effort**: if a single object fails to delete (e.g.
    transient S3 error, object was never PUTted), the error is logged and the
    loop continues so the remaining rows are still cleaned up.  The DB row is
    marked FAILED regardless of whether the S3 delete succeeded — a FAILED row
    can never re-enter the ingest pipeline, so an orphaned object at this point
    is only a billing concern, not a correctness concern.  The S3 lifecycle
    rule (infra/s3_lifecycle.json) acts as the final catch for those cases.

    Caller is responsible for commit/rollback.

    Returns the list of affected Document objects.
    """
    from botocore.exceptions import ClientError

    from app.utils.s3_client import s3_client

    reason = "Upload timed out — presigned URL expired before the file was uploaded."
    traceback_detail = (
        "Document remained in PENDING_UPLOAD state for more than 15 minutes. "
        "The presigned S3 PUT URL has expired. The browser did not complete "
        "the upload or /confirm-upload was never called."
    )

    stale_docs = (
        db.execute(
            select(Document).where(
                Document.status == DocumentStatus.PENDING_UPLOAD.value,
                Document.updated_at < cutoff,
            )
        )
        .scalars()
        .all()
    )

    for doc in stale_docs:
        logger.warning(
            "cleanup_stale_pending_upload.found",
            document_id=str(doc.id),
            filename=doc.filename,
            s3_key=doc.s3_key,
            updated_at=doc.updated_at.isoformat(),
        )

        # ── Step 1: Delete the S3 object (best-effort) ──────────────────── #
        # The object may not exist at all (browser never completed the PUT),
        # which is fine — delete_object on a missing key is a no-op in S3.
        # Any other error (permissions, network) is logged and skipped; the
        # S3 lifecycle rule will catch it later.
        try:
            s3_client.delete_object(s3_key=doc.s3_key)
            logger.info(
                "cleanup_stale_pending_upload.s3_object_deleted",
                document_id=str(doc.id),
                s3_key=doc.s3_key,
            )
        except ClientError as exc:
            error_code = exc.response["Error"]["Code"]
            if error_code in ("NoSuchKey", "404"):
                # Object was never PUT — nothing to delete, that's fine.
                logger.info(
                    "cleanup_stale_pending_upload.s3_object_already_absent",
                    document_id=str(doc.id),
                    s3_key=doc.s3_key,
                )
            else:
                # Unexpected S3 error — log for alerting, but don't abort the
                # cleanup loop.  The lifecycle rule handles residual objects.
                logger.error(
                    "cleanup_stale_pending_upload.s3_delete_failed",
                    document_id=str(doc.id),
                    s3_key=doc.s3_key,
                    error_code=error_code,
                    error=str(exc),
                )

        # ── Step 2: Transition DB row to FAILED ─────────────────────────── #
        doc.status = DocumentStatus.FAILED.value
        doc.error_message = reason
        doc.updated_at = datetime.now(UTC)

        log = JobLog(
            id=uuid.uuid4(),
            document_id=doc.id,
            attempt=0,
            error=reason,
            traceback=traceback_detail,
        )
        db.add(log)

    return list(stale_docs)


def _mark_stale_batch(
    db: Session,
    statuses: list[str],
    cutoff: datetime,
    reason: str,
    traceback_detail: str,
) -> list[Document]:
    """
    Query documents whose status is in *statuses* and whose updated_at is older
    than *cutoff*, mark them FAILED, write a JobLog entry, and return the list
    of affected documents (for logging).

    Used for PENDING and PROCESSING documents — these have confirmed S3 objects
    that must be preserved for retry.  S3 cleanup is NOT performed here.

    Caller is responsible for commit/rollback.
    """
    stale_docs = (
        db.execute(
            select(Document).where(
                Document.status.in_(statuses),
                Document.updated_at < cutoff,
            )
        )
        .scalars()
        .all()
    )

    for doc in stale_docs:
        logger.warning(
            "cleanup_stale_documents.marking_failed",
            document_id=str(doc.id),
            filename=doc.filename,
            previous_status=doc.status,
            updated_at=doc.updated_at.isoformat(),
            reason=reason,
        )

        doc.status = DocumentStatus.FAILED.value
        doc.error_message = reason
        doc.updated_at = datetime.now(UTC)

        log = JobLog(
            id=uuid.uuid4(),
            document_id=doc.id,
            attempt=0,
            error=reason,
            traceback=traceback_detail,
        )
        db.add(log)

    return list(stale_docs)


def cleanup_stale_documents_job() -> None:
    """
    Periodic job that marks stuck documents as FAILED.

    Two independent cutoff windows are enforced:

      PENDING_UPLOAD — 15 minutes
          A document stays in PENDING_UPLOAD while the browser is performing
          the S3 PUT using the presigned URL. The presigned URL itself expires
          in 15 minutes, so any document still in PENDING_UPLOAD after that
          window can never be successfully confirmed and should be failed.
          The S3 object (if any was PUT before abandonment) is deleted here
          to prevent permanent orphaning.

      PENDING / PROCESSING — 30 minutes
          A document in PENDING is waiting for the RQ worker to pick it up.
          A document in PROCESSING is being actively ingested. Both should
          complete well within 30 minutes for any supported file size.
          S3 objects for these rows are preserved (needed for retry).

    Runs every 5 minutes via self-scheduling (see bottom of function).
    """
    logger.info("cleanup_stale_documents.started")

    now = datetime.now(UTC)
    cutoff_pending_upload = now - timedelta(minutes=15)  # presigned URL expiry
    cutoff_ingest = now - timedelta(minutes=30)  # ingest pipeline timeout

    with SessionLocal() as db:
        try:
            # --- Batch 1: PENDING_UPLOAD documents older than 15 minutes ---
            # Uses the dedicated helper that deletes S3 objects first (best-
            # effort), then transitions the DB row to FAILED.  This is the
            # primary defence against permanently-orphaned S3 objects from
            # abandoned presigned-URL uploads.
            stale_pending_upload = _cleanup_stale_pending_uploads(
                db=db,
                cutoff=cutoff_pending_upload,
            )

            # --- Batch 2: PENDING / PROCESSING documents older than 30 minutes ---
            # These have confirmed S3 objects that must NOT be deleted — they
            # are needed if the user triggers a retry via POST /{id}/retry.
            stale_ingest = _mark_stale_batch(
                db=db,
                statuses=[
                    DocumentStatus.PENDING.value,
                    DocumentStatus.PROCESSING.value,
                ],
                cutoff=cutoff_ingest,
                reason="Ingestion timed out (stale document cleanup).",
                traceback_detail=(
                    "Document remained in PENDING or PROCESSING state for more than "
                    "30 minutes. The ingest worker may have crashed or been restarted."
                ),
            )

            db.commit()

            total = len(stale_pending_upload) + len(stale_ingest)
            logger.info(
                "cleanup_stale_documents.completed",
                pending_upload_failed=len(stale_pending_upload),
                ingest_failed=len(stale_ingest),
                total=total,
            )
        except Exception as e:
            db.rollback()
            logger.exception("cleanup_stale_documents.failed", error=str(e))
            raise

    # Self-schedule the next run in 5 minutes
    from app.workers.queues import _redis_conn

    default_q = Queue("default", connection=_redis_conn)
    default_q.enqueue_in(
        timedelta(minutes=5),
        cleanup_stale_documents_job,
        job_id="stale_document_cleanup",
    )


def setup_stale_document_cleanup(conn: Redis) -> None:
    from rq.exceptions import NoSuchJobError
    from rq.job import Job

    q = Queue("default", connection=conn)
    try:
        job = Job.fetch("stale_document_cleanup", connection=conn)
        if job.get_status() in ("failed", "canceled", "stopped"):
            job.delete()
            raise ValueError("Inactive job")
        logger.info("Stale document cleanup job is already scheduled.")
    except (NoSuchJobError, ValueError):
        logger.info("Scheduling initial stale document cleanup job.")
        q.enqueue_in(
            timedelta(seconds=10),
            cleanup_stale_documents_job,
            job_id="stale_document_cleanup",
        )
