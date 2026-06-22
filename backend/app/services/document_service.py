"""
services/document_service.py

Owns all business logic for the Document domain:
  - Status transition enforcement (state machine)
  - Document ownership verification
  - Convenience query helpers used by upload / status / delete endpoints

Two upload paths are supported here simultaneously:

  Legacy path  — upload_document()
      Validates, uploads to S3, and inserts a PENDING DB row in one call.
      Used by POST /documents/upload (multipart/form-data).

  Presigned URL path — initiate_upload() + confirm_upload()
      initiate_upload(): quota + metadata check → writes PENDING_UPLOAD row →
                         returns presigned S3 PUT URL to the caller.
      confirm_upload():  HeadObject verify → PENDING_UPLOAD → PENDING → enqueue job.
      Used by POST /documents/initiate-upload and POST /documents/confirm-upload.

State machine (transitions enforced here, not at the DB layer):
    PENDING_UPLOAD → PENDING    (browser PUT confirmed)
    PENDING_UPLOAD → FAILED     (stale cleanup)
    PENDING        → PROCESSING
    PROCESSING     → READY
    PROCESSING     → FAILED
    FAILED         → PROCESSING (retry)

The DB stores status as Text. This layer is the authority on valid values
and valid moves between them.

─────────────────────────────────────────────────────────────────────────────
QUOTA ENFORCEMENT — WHICH STATUSES COUNT AGAINST THE LIMIT?
─────────────────────────────────────────────────────────────────────────────

The quota check in both upload_document() and initiate_upload() uses
count_user_documents(..., exclude_statuses=frozenset({DocumentStatus.FAILED})).

This deliberately includes PENDING_UPLOAD rows in the count.  That is
intentional and critical for correctness:

  If PENDING_UPLOAD rows were excluded:
    A malicious or buggy client could call POST /initiate-upload in a tight
    loop, minting thousands of presigned URLs and thousands of DB rows,
    without ever confirming a single one.  The quota gate would see zero
    "real" documents and pass every time.  The PENDING_UPLOAD rows would
    accumulate indefinitely (until the 15-min stale cleanup fires), the DB
    would bloat, and the quota limit would be meaningless.

  With PENDING_UPLOAD included (current behaviour):
    Each call to initiate_upload() burns one slot in the user's quota.
    A client that opens 20 concurrent presigned-URL requests hits the limit
    after 20 initiate-upload calls, exactly as if they had uploaded 20 real
    documents.  Slots are returned after the stale cleanup marks those rows
    FAILED (15 minutes), which is an acceptable natural rate-limit window.

  FAILED rows are excluded so that a user whose uploads repeatedly fail
  (corrupt PDF, wrong MIME type, size mismatch) is not permanently blocked.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations
from fastapi import UploadFile


import io
import uuid
import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.exceptions import QuotaExceededError, DocumentNotFoundError, InvalidStatusTransitionError
from app.models.user import User
from app.models.document import Document, DocumentStatus, _ALLOWED_TRANSITIONS
from app.services.file_validation import validate_upload, validate_upload_metadata
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
    exclude_statuses: frozenset[DocumentStatus] = frozenset(),
) -> int:
    """
    Count documents for a user, optionally filtered by status.

    Used by:
      - GET /documents pagination (no exclusions — counts all statuses)
      - Quota enforcement in upload_document() and initiate_upload()
        (excludes only FAILED — see module docstring for the full rationale
        on why PENDING_UPLOAD is intentionally NOT excluded)

    Args:
        status:           If set, count only documents in this single status.
                          Mutually exclusive with exclude_statuses in practice
                          (combining them is valid but unusual).
        exclude_statuses: Set of statuses to exclude from the count.
                          Pass frozenset({DocumentStatus.FAILED}) for quota
                          enforcement.  An empty frozenset (the default) means
                          all statuses are counted.

                          IMPORTANT: Do NOT add DocumentStatus.PENDING_UPLOAD
                          to this set in quota contexts.  Excluding PENDING_UPLOAD
                          would allow a client to mint unlimited presigned URLs
                          without ever consuming quota — see module docstring.
    """
    stmt = select(func.count(Document.id)).where(Document.user_id == user_id)
    if status is not None:
        stmt = stmt.where(Document.status == status.value)
    if exclude_statuses:
        stmt = stmt.where(
            Document.status.notin_([s.value for s in exclude_statuses])
        )
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
    #                                                                     #
    # Exclude only FAILED documents.  PENDING_UPLOAD rows are             #
    # intentionally counted — see the module-level docstring for why.    #
    # ------------------------------------------------------------------ #
    active_count = await count_user_documents(
        db=db,
        user_id=current_user.id,
        exclude_statuses=frozenset({DocumentStatus.FAILED}),
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


# ---------------------------------------------------------------------------
# Presigned URL upload flow — Step 3
# ---------------------------------------------------------------------------

_PRESIGNED_URL_EXPIRES_IN: int = 900  # 15 minutes


async def initiate_upload(
    *,
    current_user: User,
    filename: str,
    mime_type: str,
    file_size_bytes: int,
    db: AsyncSession,
) -> tuple[Document, str]:
    """
    Phase 1 of the presigned URL upload flow.

    Validates file metadata (size + MIME type — no bytes read), checks the
    user's document quota, generates an S3 key, writes a PENDING_UPLOAD DB row,
    and returns a presigned S3 PUT URL that the browser uses to upload the file
    directly to S3 without proxying through this server.

    Steps (in order — fail-fast):
      1. Quota check  — COUNT non-FAILED docs for this user
      2. Metadata validation — size ≤ 50 MB, MIME type in allowed list
      3. DB insert    — status=PENDING_UPLOAD (file not yet in S3)
      4. Generate presigned S3 PUT URL (no bytes transferred here)

    Args:
        current_user:    Authenticated user making the request.
        filename:        Original filename as reported by the browser.
        mime_type:       MIME type declared by the browser.
        file_size_bytes: File size in bytes declared by the browser.
        db:              Active async database session.

    Returns:
        (document, upload_url) — the newly created Document ORM object
        (status=PENDING_UPLOAD) and the presigned PUT URL string.

    Raises:
        QuotaExceededError   — user is at or over MAX_DOCS_PER_USER
        FileValidationError  — size too large or MIME type not allowed
    """
    # ------------------------------------------------------------------ #
    # 1. Quota check — before touching S3 or writing any DB row           #
    #                                                                     #
    # Exclude only FAILED documents.  PENDING_UPLOAD rows are             #
    # intentionally counted — each initiate-upload call burns one quota  #
    # slot whether or not the user ever completes the upload.  This       #
    # prevents a client from minting unlimited presigned URLs in a loop   #
    # without consuming quota (the slot is returned when the stale        #
    # cleanup marks abandoned rows FAILED after ~15 minutes).             #
    # See the module-level docstring for the full rationale.              #
    # ------------------------------------------------------------------ #
    active_count = await count_user_documents(
        db=db,
        user_id=current_user.id,
        exclude_statuses=frozenset({DocumentStatus.FAILED}),
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
    # 2. Metadata validation — no bytes read here                         #
    # Magic-byte check is deferred to the ingest worker (extraction.py). #
    # ------------------------------------------------------------------ #
    validate_upload_metadata(
        filename=filename,
        mime_type=mime_type,
        file_size_bytes=file_size_bytes,
    )

    # ------------------------------------------------------------------ #
    # 3. Build key + DB insert (status=PENDING_UPLOAD)                    #
    # The document row is created before the presigned URL is issued so   #
    # the document_id is stable and can be referenced in confirm_upload.  #
    # ------------------------------------------------------------------ #
    document_id = uuid.uuid4()
    s3_key = build_document_s3_key(
        user_id=str(current_user.id),
        document_id=str(document_id),
        filename=filename,
    )

    document = Document(
        id=document_id,
        user_id=current_user.id,
        filename=filename,
        s3_key=s3_key,
        file_size_bytes=file_size_bytes,
        mime_type=mime_type,
        status=DocumentStatus.PENDING_UPLOAD,
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)

    logger.info(
        "document_initiate_upload_db_created",
        user_id=str(current_user.id),
        document_id=str(document_id),
        s3_key=s3_key,
        file_size_bytes=file_size_bytes,
        mime_type=mime_type,
    )

    # ------------------------------------------------------------------ #
    # 4. Generate presigned S3 PUT URL                                    #
    # The URL is bound to the exact s3_key and content_type. S3 rejects  #
    # any PUT that doesn't match both. No bytes travel through this       #
    # server at any point.
    # ------------------------------------------------------------------ #
    upload_url = s3_client.generate_presigned_upload_url(
        s3_key=s3_key,
        content_type=mime_type,
        expires_in=_PRESIGNED_URL_EXPIRES_IN,
    )

    logger.info(
        "document_presigned_url_issued",
        user_id=str(current_user.id),
        document_id=str(document_id),
        expires_in=_PRESIGNED_URL_EXPIRES_IN,
    )

    return document, upload_url


# ---------------------------------------------------------------------------
# Size-tolerance used during confirm_upload() to catch payload-size abuse.
#
# A client can declare file_size_bytes=2MB at initiate-upload time, then PUT
# a 500MB file to the presigned URL.  S3 only enforces the Content-Type bound
# in the signature; it does NOT enforce Content-Length from the initiation
# request.  head_object() would happily confirm the 500MB object.
#
# We compare the real ContentLength (from HeadObject) to the client-claimed
# doc.file_size_bytes.  Any deviation beyond this fraction is treated as an
# abuse attempt: the S3 object is deleted, the DB row is marked FAILED, and a
# ValueError is raised (→ 409 Conflict at the router layer).
#
# 10% covers legitimate variation sources:
#   - Multipart upload overhead (part headers): negligible (<1 KB)
#   - Browser File.size rounding: none, it's exact
#   - S3 metadata overhead: not included in ContentLength
# In practice any honest upload will be within 1 byte.  The 10% band is
# intentionally generous to avoid false positives on legitimate files while
# still catching the MB → GB substitution attack.
# ---------------------------------------------------------------------------
_CONFIRM_SIZE_TOLERANCE = 0.10  # 10 %


async def confirm_upload(
    *,
    document_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> Document:
    """
    Phase 2 of the presigned URL upload flow.

    Called by the browser after the S3 PUT succeeds. Performs three guards
    before transitioning the document to PENDING:

      1. Fetch document + ownership check (404 if not found / not owned)
      2. HeadObject — verify file exists in S3 (lightweight, no bytes)
      3. ContentLength check — actual S3 size must be within ±10% of the
         client-declared file_size_bytes.  If it's outside this band the S3
         object is deleted, the document is marked FAILED, and a ValueError
         is raised (router maps it to 409 Conflict).  This closes the
         payload-substitution attack where a client initiates with a tiny
         declared size but PUTs a giant file.
      4. Transition PENDING_UPLOAD → PENDING
      5. Commit and return Document — router enqueues the ingest job

    Args:
        document_id: UUID of the document to confirm.
        user_id:     ID of the authenticated user (ownership check).
        db:          Active async database session.

    Returns:
        The updated Document ORM object (status=PENDING).

    Raises:
        DocumentNotFoundError — document not found or not owned by user_id.
        ValueError            — document is not in PENDING_UPLOAD state, or
                                the real S3 object size is outside the allowed
                                tolerance band (router maps both to 409).
        ClientError           — S3 HeadObject failed (object not in S3 yet;
                                the router maps this to 409 / 502).
    """
    from botocore.exceptions import ClientError

    # ------------------------------------------------------------------ #
    # 1. Fetch + ownership check                                          #
    # ------------------------------------------------------------------ #
    doc = await get_document_for_user(
        db=db,
        document_id=document_id,
        user_id=user_id,
    )

    if doc.status_enum != DocumentStatus.PENDING_UPLOAD:
        # Already confirmed, processing, or failed — do not re-trigger.
        # Raise a ValueError; the router maps it to 409 Conflict.
        raise ValueError(
            f"Document {document_id} is in status '{doc.status}' — "
            "only PENDING_UPLOAD documents can be confirmed."
        )

    # ------------------------------------------------------------------ #
    # 2. HeadObject — verify the file actually landed in S3               #
    # Without this check, a malicious caller could confirm a document_id  #
    # for which they never uploaded anything, causing the ingest worker   #
    # to crash on a missing S3 object.                                   #
    # ------------------------------------------------------------------ #
    try:
        head = s3_client.head_object(s3_key=doc.s3_key)
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        logger.warning(
            "document_confirm_s3_missing",
            user_id=str(user_id),
            document_id=str(document_id),
            s3_key=doc.s3_key,
            error_code=error_code,
        )
        # Re-raise; the router maps ClientError to 409 or 502 as appropriate.
        raise

    # ------------------------------------------------------------------ #
    # 3. ContentLength size-integrity check                               #
    #                                                                     #
    # S3 does NOT enforce Content-Length from the presigned URL request;  #
    # it only enforces Content-Type.  A client could therefore declare    #
    # file_size_bytes=2_000_000 at initiate-upload and then PUT a 500 MB  #
    # video to the presigned URL.  Without this check, quota and storage  #
    # limits would be computed from the *claimed* size, not the real one. #
    #                                                                     #
    # We read ContentLength from HeadObject (the authoritative S3 value)  #
    # and reject the upload if it deviates from the declared size by more #
    # than _CONFIRM_SIZE_TOLERANCE (10 %).  On rejection:                 #
    #   a) The rogue S3 object is deleted immediately.                    #
    #   b) The DB row is transitioned to FAILED with an explanatory       #
    #      error_message so the user sees a clear failure reason.         #
    #   c) A ValueError is raised so the router returns 409 Conflict.     #
    # ------------------------------------------------------------------ #
    actual_size: int = head.get("ContentLength", 0)
    claimed_size: int = doc.file_size_bytes

    # Allow the claimed size to be 0 only if the actual file is also 0
    # (empty file edge case — both are zero, delta is fine).
    if claimed_size > 0:
        delta = abs(actual_size - claimed_size) / claimed_size
    else:
        # claimed_size == 0: only accept an actual empty file.
        delta = 0.0 if actual_size == 0 else float("inf")

    logger.info(
        "document_confirm_s3_size_check",
        user_id=str(user_id),
        document_id=str(document_id),
        s3_key=doc.s3_key,
        claimed_size_bytes=claimed_size,
        actual_size_bytes=actual_size,
        delta_fraction=round(delta, 4),
        tolerance=_CONFIRM_SIZE_TOLERANCE,
    )

    if delta > _CONFIRM_SIZE_TOLERANCE:
        # ---- Cleanup: delete the rogue S3 object ---- #
        try:
            s3_client.delete_object(s3_key=doc.s3_key)
            logger.warning(
                "document_confirm_size_mismatch_s3_cleaned",
                user_id=str(user_id),
                document_id=str(document_id),
                s3_key=doc.s3_key,
                claimed_size_bytes=claimed_size,
                actual_size_bytes=actual_size,
            )
        except ClientError:
            # S3 delete failed — log for manual remediation; the document
            # will still be marked FAILED so the user cannot use it.
            logger.error(
                "document_confirm_size_mismatch_s3_cleanup_failed",
                user_id=str(user_id),
                document_id=str(document_id),
                s3_key=doc.s3_key,
            )

        # ---- Transition DB row to FAILED ---- #
        error_msg = (
            f"Uploaded file size ({actual_size:,} bytes) does not match the "
            f"declared size ({claimed_size:,} bytes). "
            "Please re-upload the correct file."
        )
        await transition_status(
            db,
            doc,
            DocumentStatus.FAILED,
            error_message=error_msg,
        )
        await db.commit()

        logger.warning(
            "document_confirm_size_mismatch_failed",
            user_id=str(user_id),
            document_id=str(document_id),
            claimed_size_bytes=claimed_size,
            actual_size_bytes=actual_size,
            delta_pct=round(delta * 100, 1),
        )
        raise ValueError(error_msg)

    # ------------------------------------------------------------------ #
    # 4. Transition PENDING_UPLOAD → PENDING                              #
    # ------------------------------------------------------------------ #
    await transition_status(db, doc, DocumentStatus.PENDING)
    await db.commit()
    await db.refresh(doc)

    logger.info(
        "document_confirm_upload_pending",
        user_id=str(user_id),
        document_id=str(document_id),
        actual_size_bytes=actual_size,
    )

    return doc
