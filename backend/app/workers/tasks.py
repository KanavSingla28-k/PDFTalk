from redis import Redis
import uuid
from datetime import datetime, timezone, timedelta
import structlog
from rq import Queue

from app.db.sync_session import SessionLocal
from app.models.document import Document, DocumentStatus
from app.models.job_log import JobLog

logger = structlog.get_logger(__name__)


def _mark_stale_batch(
    db,
    statuses: list[str],
    cutoff: datetime,
    reason: str,
    traceback_detail: str,
) -> list:
    """
    Query documents whose status is in *statuses* and whose updated_at is older
    than *cutoff*, mark them FAILED, write a JobLog entry, and return the list
    of affected documents (for logging).

    Caller is responsible for commit/rollback.
    """
    stale_docs = (
        db.query(Document)
        .filter(
            Document.status.in_(statuses),
            Document.updated_at < cutoff,
        )
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
        doc.updated_at = datetime.now(timezone.utc)

        log = JobLog(
            id=uuid.uuid4(),
            document_id=doc.id,
            attempt=1,
            error=reason,
            traceback=traceback_detail,
        )
        db.add(log)

    return stale_docs


def cleanup_stale_documents_job() -> None:
    """
    Periodic job that marks stuck documents as FAILED.

    Two independent cutoff windows are enforced:

      PENDING_UPLOAD — 15 minutes
          A document stays in PENDING_UPLOAD while the browser is performing
          the S3 PUT using the presigned URL. The presigned URL itself expires
          in 15 minutes, so any document still in PENDING_UPLOAD after that
          window can never be successfully confirmed and should be failed.

      PENDING / PROCESSING — 30 minutes
          A document in PENDING is waiting for the RQ worker to pick it up.
          A document in PROCESSING is being actively ingested. Both should
          complete well within 30 minutes for any supported file size.

    Runs every 5 minutes via self-scheduling (see bottom of function).
    """
    logger.info("cleanup_stale_documents.started")

    now = datetime.now(timezone.utc)
    cutoff_pending_upload = now - timedelta(minutes=15)   # presigned URL expiry
    cutoff_ingest         = now - timedelta(minutes=30)   # ingest pipeline timeout

    with SessionLocal() as db:
        try:
            # --- Batch 1: PENDING_UPLOAD documents older than 15 minutes ---
            stale_pending_upload = _mark_stale_batch(
                db=db,
                statuses=[DocumentStatus.PENDING_UPLOAD.value],
                cutoff=cutoff_pending_upload,
                reason="Upload timed out — presigned URL expired before the file was uploaded.",
                traceback_detail=(
                    "Document remained in PENDING_UPLOAD state for more than 15 minutes. "
                    "The presigned S3 PUT URL has expired. The browser did not complete "
                    "the upload or /confirm-upload was never called."
                ),
            )

            # --- Batch 2: PENDING / PROCESSING documents older than 30 minutes ---
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
    from rq.job import Job

    q = Queue("default", connection=conn)
    try:
        job = Job.fetch("stale_document_cleanup", connection=conn)
        if job.get_status() in ("failed", "canceled", "stopped"):
            job.delete()
            raise ValueError("Inactive job")
        logger.info("Stale document cleanup job is already scheduled.")
    except Exception:
        logger.info("Scheduling initial stale document cleanup job.")
        q.enqueue_in(
            timedelta(seconds=10),
            cleanup_stale_documents_job,
            job_id="stale_document_cleanup",
        )
