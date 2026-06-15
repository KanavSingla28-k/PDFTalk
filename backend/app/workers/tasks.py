from redis import Redis
import uuid
from datetime import datetime, timezone, timedelta
import structlog
from rq import Queue

from app.db.sync_session import SessionLocal
from app.models.document import Document, DocumentStatus
from app.models.job_log import JobLog

logger = structlog.get_logger(__name__)


def cleanup_stale_documents_job() -> None:
    """
    Periodic job that marks PENDING or PROCESSING documents older than 30 minutes as FAILED.
    """
    logger.info("cleanup_stale_documents.started")
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)

    with SessionLocal() as db:
        try:
            stale_docs = (
                db.query(Document)
                .filter(
                    Document.status.in_(
                        [DocumentStatus.PENDING.value, DocumentStatus.PROCESSING.value]
                    ),
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
                )

                doc.status = DocumentStatus.FAILED.value
                doc.error_message = "Ingestion timed out (stale document cleanup)."
                doc.updated_at = datetime.now(timezone.utc)

                log = JobLog(
                    id=uuid.uuid4(),
                    document_id=doc.id,
                    attempt=1,
                    error="Ingestion timed out (stale document cleanup).",
                    traceback="Document remained in PENDING or PROCESSING state for more than 30 minutes.",
                )
                db.add(log)

            db.commit()
            logger.info("cleanup_stale_documents.completed", processed_count=len(stale_docs))
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
