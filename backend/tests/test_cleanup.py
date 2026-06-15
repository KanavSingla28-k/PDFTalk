import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.document import Document, DocumentStatus
from app.models.job_log import JobLog
from app.workers.tasks import cleanup_stale_documents_job, setup_stale_document_cleanup

# Setup a sync SQLite database for testing the sync job
sync_engine = create_engine("sqlite:///:memory:")
Base.metadata.create_all(sync_engine)
SyncSession = sessionmaker(bind=sync_engine)


def test_cleanup_stale_documents_job() -> None:
    # Seed various documents
    user_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    # 1. Stale PENDING document (updated 31 minutes ago)
    doc_stale_pending = Document(
        id=uuid.uuid4(),
        user_id=user_id,
        filename="stale_pending.pdf",
        s3_key=f"{user_id}/stale_pending.pdf",
        file_size_bytes=100,
        mime_type="application/pdf",
        status=DocumentStatus.PENDING.value,
        updated_at=now - timedelta(minutes=31),
        created_at=now - timedelta(minutes=31),
    )

    # 2. Stale PROCESSING document (updated 45 minutes ago)
    doc_stale_processing = Document(
        id=uuid.uuid4(),
        user_id=user_id,
        filename="stale_processing.pdf",
        s3_key=f"{user_id}/stale_processing.pdf",
        file_size_bytes=100,
        mime_type="application/pdf",
        status=DocumentStatus.PROCESSING.value,
        updated_at=now - timedelta(minutes=45),
        created_at=now - timedelta(minutes=45),
    )

    # 3. Fresh PENDING document (updated 10 minutes ago)
    doc_fresh_pending = Document(
        id=uuid.uuid4(),
        user_id=user_id,
        filename="fresh_pending.pdf",
        s3_key=f"{user_id}/fresh_pending.pdf",
        file_size_bytes=100,
        mime_type="application/pdf",
        status=DocumentStatus.PENDING.value,
        updated_at=now - timedelta(minutes=10),
        created_at=now - timedelta(minutes=10),
    )

    # 4. READY document (updated 60 minutes ago - should NOT be touched)
    doc_ready = Document(
        id=uuid.uuid4(),
        user_id=user_id,
        filename="ready.pdf",
        s3_key=f"{user_id}/ready.pdf",
        file_size_bytes=100,
        mime_type="application/pdf",
        status=DocumentStatus.READY.value,
        updated_at=now - timedelta(minutes=60),
        created_at=now - timedelta(minutes=60),
    )

    stale_pending_id = doc_stale_pending.id
    stale_processing_id = doc_stale_processing.id
    fresh_pending_id = doc_fresh_pending.id
    ready_id = doc_ready.id

    with SyncSession() as db:
        db.add_all([doc_stale_pending, doc_stale_processing, doc_fresh_pending, doc_ready])
        db.commit()

    # Run the cleanup job while patching SessionLocal and Queue
    with patch("app.workers.tasks.SessionLocal", SyncSession), \
         patch("app.workers.tasks.Queue") as mock_queue_class:
        
        mock_queue = MagicMock()
        mock_queue_class.return_value = mock_queue

        cleanup_stale_documents_job()

        # Check that the next run is enqueued in default queue
        mock_queue_class.assert_called_once()
        assert mock_queue_class.call_args[0][0] == "default"
        mock_queue.enqueue_in.assert_called_once()
        args, kwargs = mock_queue.enqueue_in.call_args
        assert args[0] == timedelta(minutes=5)
        assert args[1] == cleanup_stale_documents_job
        assert kwargs["job_id"] == "stale_document_cleanup"

    # Verify changes in DB
    with SyncSession() as db:
        # 1. Stale PENDING should be transitioned to FAILED
        stale_pending = db.get(Document, stale_pending_id)
        assert stale_pending.status == DocumentStatus.FAILED.value
        assert "timed out" in stale_pending.error_message

        # 2. Stale PROCESSING should be transitioned to FAILED
        stale_processing = db.get(Document, stale_processing_id)
        assert stale_processing.status == DocumentStatus.FAILED.value
        assert "timed out" in stale_processing.error_message

        # 3. Fresh PENDING should remain PENDING
        fresh_pending = db.get(Document, fresh_pending_id)
        assert fresh_pending.status == DocumentStatus.PENDING.value

        # 4. READY should remain READY
        ready = db.get(Document, ready_id)
        assert ready.status == DocumentStatus.READY.value

        # 5. Check JobLogs
        logs = db.query(JobLog).all()
        assert len(logs) == 2
        doc_ids_in_logs = {log.document_id for log in logs}
        assert doc_ids_in_logs == {stale_pending_id, stale_processing_id}
        assert all(log.attempt == 1 for log in logs)
        assert all("timed out" in log.error for log in logs)


def test_setup_stale_document_cleanup_already_scheduled() -> None:
    mock_conn = MagicMock()
    with patch("rq.job.Job.fetch") as mock_fetch, \
         patch("app.workers.tasks.Queue") as mock_queue_class:
        
        mock_job = MagicMock()
        mock_job.get_status.return_value = "scheduled"
        mock_fetch.return_value = mock_job
        
        mock_queue = MagicMock()
        mock_queue_class.return_value = mock_queue

        setup_stale_document_cleanup(mock_conn)

        mock_fetch.assert_called_once_with("stale_document_cleanup", connection=mock_conn)
        mock_queue.enqueue_in.assert_not_called()


def test_setup_stale_document_cleanup_not_scheduled() -> None:
    mock_conn = MagicMock()
    with patch("rq.job.Job.fetch", side_effect=Exception("Job not found")), \
         patch("app.workers.tasks.Queue") as mock_queue_class:
        
        mock_queue = MagicMock()
        mock_queue_class.return_value = mock_queue

        setup_stale_document_cleanup(mock_conn)

        mock_queue.enqueue_in.assert_called_once_with(
            timedelta(seconds=10),
            cleanup_stale_documents_job,
            job_id="stale_document_cleanup",
        )
