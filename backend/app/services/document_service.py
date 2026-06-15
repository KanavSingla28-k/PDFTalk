"""
services/document_service.py

Owns all business logic for the Document domain:
  - Status transition enforcement (state machine)
  - Document ownership verification
  - Convenience query helpers used by upload / status / delete endpoints

State machine (transitions enforced here, not at the DB layer):
    PENDING → PROCESSING → READY
    PENDING → PROCESSING → FAILED
    READY   → (terminal, no transitions)
    FAILED  → (terminal, no transitions)

The DB stores status as Text. This layer is the authority on valid values
and valid moves between them.
"""
from __future__ import annotations
from fastapi import UploadFile


import uuid
import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.exceptions import QuotaExceededError, DocumentNotFoundError, InvalidStatusTransitionError
from app.models.user import User
from app.models.document import Document, DocumentStatus, _ALLOWED_TRANSITIONS
from app.services.file_validation import validate_upload
from app.core.config import settings
from app.utils.s3_client import build_document_s3_key, s3_client


logger = structlog.get_logger()



async def get_document_for_user(
    db: AsyncSession,
    document_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    include_chunks: bool = False,
    include_job_logs: bool = False,
) -> Document:
    """
    Fetch a document by ID and assert ownership in one query.

    Raises:
        DocumentNotFoundError: document doesn't exist or isn't owned by user_id.
            Callers surface this as 404 (not 403) to avoid resource enumeration.
    """
    stmt = select(Document).where(
        Document.id == document_id,
        Document.user_id == user_id,
    )
    if include_chunks:
        stmt = stmt.options(selectinload(Document.chunks))
    if include_job_logs:
        stmt = stmt.options(selectinload(Document.job_logs))

    result = await db.execute(stmt)
    doc = result.scalar_one_or_none()
    if doc is None:
        raise DocumentNotFoundError(document_id=document_id)
    return doc

async def transition_status(
    db: AsyncSession,
    document: Document,
    to_status: DocumentStatus,
    *,
    error_message: str | None = None,
    chunk_count: int | None = None,
    flush: bool = True,
) -> Document:
    """
    Move a document to a new status, enforcing the state machine.

    Args:
        db: active async session (caller owns commit/rollback)
        document: the Document ORM instance to update
        to_status: target status
        error_message: populated when transitioning to FAILED
        chunk_count: populated when transitioning to READY
        flush: if True, flush to DB within the caller's transaction so the
               change is visible to subsequent queries in the same session.
               Set False only when the caller wants to batch multiple flushes.

    Returns:
        The mutated Document instance (same object, updated in place).

    Raises:
        InvalidStatusTransitionError: if the transition is not in _ALLOWED_TRANSITIONS.
    """
    from_status = document.status_enum
    allowed = _ALLOWED_TRANSITIONS[from_status]

    if to_status not in allowed:
        raise InvalidStatusTransitionError(
            document_id=document.id,
            from_status=from_status,
            to_status=to_status,
        )

    document.status = to_status.value

    if to_status == DocumentStatus.FAILED:
        document.error_message = error_message

    if to_status == DocumentStatus.READY and chunk_count is not None:
        document.chunk_count = chunk_count

    if flush:
        await db.flush()

    return document

async def count_user_documents(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    status: DocumentStatus | None = None,
    exclude_failed: bool = False,
) -> int:
    """
    Count documents for a user, optionally filtered by status.
    Used by GET /documents to populate DocumentListResponse.total,
    and by the quota check in upload_document.

    Args:
        exclude_failed: When True, FAILED documents are excluded from the
            count. Used during quota enforcement so failed uploads don't
            permanently reduce a user's quota capacity.
    """
    stmt = select(func.count(Document.id)).where(Document.user_id == user_id)
    if status is not None:
        stmt = stmt.where(Document.status == status.value)
    if exclude_failed:
        stmt = stmt.where(Document.status != DocumentStatus.FAILED.value)
    result = await db.execute(stmt)
    return result.scalar_one()

async def get_user_documents(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    status: DocumentStatus | None = None,
    limit: int = 10,
    offset: int = 0,
    include_chunks: bool = False,
    include_job_logs: bool = False,
) -> list[Document]:
    """
    Paginated list of documents for a user, optionally filtered by status.
    Used by GET /documents.
    """
    stmt = select(Document).where(Document.user_id == user_id)
    if status is not None:
        stmt = stmt.where(Document.status == status.value)
        
    if include_chunks:
        stmt = stmt.options(selectinload(Document.chunks))
    if include_job_logs:
        stmt = stmt.options(selectinload(Document.job_logs))

    stmt = (
        stmt.order_by(
            Document.created_at.desc(), 
            Document.id.desc()
        )
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())

async def upload_document(
    *,
    current_user: User,
    file: UploadFile,
    db: AsyncSession,
) -> Document:
    """
    Validate, upload, and register a document for the authenticated user.
 
    Steps (in order — fail fast on each):
      1. Quota check — COUNT non-FAILED docs for this user
      2. File validation — MIME type, magic bytes, size
      3. S3 upload
      4. DB insert (status=PENDING)
      5. Return the Document — caller (router) enqueues the RQ ingest job
 
    Returns:
        The newly created Document ORM object (id and status populated).
 
    Raises:
        QuotaExceededError    — user is at or over MAX_DOCS_PER_USER
        FileValidationError   — invalid MIME type, magic bytes, or size
        ClientError           — S3 upload failure (let it propagate)
    """
    # ------------------------------------------------------------------ #
    # 1. Quota check — before reading a single byte of the upload         #
    # Exclude FAILED documents: a user whose uploads consistently fail    #
    # (e.g., corrupt PDFs) should not be permanently blocked.            #
    # ------------------------------------------------------------------ #
    active_count = await count_user_documents(
        db=db,
        user_id=current_user.id,
        exclude_failed=True,
    )
    if active_count >= settings.MAX_DOCS_PER_USER:
        logger.warning(
            "document_quota_exceeded",
            user_id=str(current_user.id),
            active_count=active_count,
            limit=settings.MAX_DOCS_PER_USER,
        )
        raise QuotaExceededError(
            f"Document limit reached ({settings.MAX_DOCS_PER_USER}). "
            "Delete existing documents to upload more."
        )
 
    # ------------------------------------------------------------------ #
    # 2. File validation                                                   #
    # ------------------------------------------------------------------ #
    # validate_upload raises FileValidationError with a typed reason on
    # any failure. Let it propagate — the router's exception handler maps
    # it to 422.
    file_data: bytes = await validate_upload(file=file)
 
    # ------------------------------------------------------------------ #
    # 3. S3 upload                                                         #
    # ------------------------------------------------------------------ #
    document_id = uuid.uuid4()
    s3_key = build_document_s3_key(
        user_id=str(current_user.id),
        document_id=str(document_id),
        filename=file.filename or "upload",
    )
 
    import io
    s3_client.upload_file(
        file_obj=io.BytesIO(file_data),
        s3_key=s3_key,
        content_type=file.content_type or "application/octet-stream",
    )
    logger.info(
        "document_s3_uploaded",
        user_id=str(current_user.id),
        document_id=str(document_id),
        s3_key=s3_key,
        size_bytes=len(file_data),
    )
 
    # ------------------------------------------------------------------ #
    # 4. DB insert                                                         #
    # ------------------------------------------------------------------ #
    document = Document(
        id=document_id,
        user_id=current_user.id,
        filename=file.filename or "upload",
        s3_key=s3_key,
        file_size_bytes=len(file_data),
        mime_type=file.content_type or "application/octet-stream",
        status=DocumentStatus.PENDING,
    )
    db.add(document)

    try:
        await db.commit()
        await db.refresh(document)
        logger.info(
            "document_db_created",
            user_id=str(current_user.id),
            document_id=str(document_id),
            status=document.status,
        )
    except Exception:
        logger.error(
            "document_db_insert_failed_cleaning_s3",
            user_id=str(current_user.id),
            document_id=str(document_id),
            s3_key=s3_key,
        )
        try:
            s3_client.delete_object(s3_key=s3_key)
        except Exception:
            # S3 cleanup also failed — log for manual remediation.
            # A periodic S3 orphan sweep (T-62 territory) can catch this.
            logger.critical(
                "document_s3_orphan_unrecoverable",
                user_id=str(current_user.id),
                document_id=str(document_id),
                s3_key=s3_key,
            )
        raise

    return document

async def delete_document(
    db: AsyncSession,
    document_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    """
    Delete a document: S3 first, then DB row.

    Ownership is verified via get_document_for_user (raises
    DocumentNotFoundError → 404 if not found or not owned).

    S3 deletion policy:
      - Object missing (NoSuchKey / 404)  → treat as success (idempotent)
      - Any other S3 error                → raise, keep DB row intact
    DB row is only removed after S3 deletion succeeds.

    Cascade in the schema handles chunk deletion automatically.

    Raises:
        DocumentNotFoundError: document doesn't exist or isn't owned by user_id.
        ClientError: non-404 S3 failure. DB row is NOT deleted.
    """
    from botocore.exceptions import ClientError

    doc = await get_document_for_user(db=db, document_id=document_id, user_id=user_id)

    # ------------------------------------------------------------------ #
    # 1. S3 deletion — fail-fast before touching the DB                   #
    # ------------------------------------------------------------------ #
    try:
        s3_client.delete_object(s3_key=doc.s3_key)
        logger.info(
            "document_s3_deleted",
            user_id=str(user_id),
            document_id=str(document_id),
            s3_key=doc.s3_key,
        )
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        if error_code in ("NoSuchKey", "404"):
            # Object already gone — S3 and DB were out of sync.
            # Treat as success so the user can clean up their document list.
            logger.warning(
                "document_s3_already_missing",
                user_id=str(user_id),
                document_id=str(document_id),
                s3_key=doc.s3_key,
            )
        else:
            logger.error(
                "document_s3_delete_failed",
                user_id=str(user_id),
                document_id=str(document_id),
                s3_key=doc.s3_key,
                error_code=error_code,
            )
            raise  # DB row untouched

    # ------------------------------------------------------------------ #
    # 2. DB deletion — only reached if S3 step succeeded / was missing    #
    # ------------------------------------------------------------------ #
    await db.delete(doc)
    await db.commit()

    logger.info(
        "document_db_deleted",
        user_id=str(user_id),
        document_id=str(document_id),
    )
