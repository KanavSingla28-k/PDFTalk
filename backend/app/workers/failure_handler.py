from __future__ import annotations

import traceback
import uuid
from typing import TYPE_CHECKING

from rq.job import Job
from redis import Redis
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document
from app.models.job_log import JobLog

# Sync engine — created lazily on first use so a misconfigured DATABASE_URL
# does not crash the worker process at startup (before any job is processed).
_sync_engine = None


def _get_engine():
    global _sync_engine
    if _sync_engine is None:
        _sync_engine = create_engine(
            settings.DATABASE_URL.replace("+asyncpg", "+psycopg"),
            pool_size=2,
            max_overflow=0,
        )
    return _sync_engine



def handle_ingest_failure(
    job: Job,
    connection: Redis,
    type: type[BaseException],
    value: BaseException,
    tb,
) -> None:
    """
    Called by RQ after max_retries are exhausted.
    Marks the document FAILED and writes a job_logs row.
    """
    document_id: str | None = job.kwargs.get("document_id")
    if not document_id:
        return

    tb_str = "".join(traceback.format_tb(tb))

    with Session(_get_engine()) as session:
        doc = session.get(Document, uuid.UUID(document_id))
        if doc:
            doc.status = "FAILED"
            doc.error_message = str(value)
            session.add(doc)

        log = JobLog(
            document_id=uuid.UUID(document_id),
            attempt=job.retries_left,  # 0 at final failure
            error=str(value),
            traceback=tb_str,
        )
        session.add(log)
        session.commit()
