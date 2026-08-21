import math
import uuid
from typing import Any
from rq import Retry, Callback

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.auth.dependencies import get_verified_user
from app.core.sentinel import upload_guard
from app.db.session import get_db
from app.models.document import (
    ConfirmUploadRequest,
    ConfirmUploadResponse,
    DocumentListResponse,
    DocumentStatus,
    DocumentStatusResponse,
    DocumentUploadResponse,
    InitiateUploadRequest,
    InitiateUploadResponse,
    DocumentDownloadUrlResponse,
)
from app.models.user import User
from app.exceptions import DocumentNotFoundError
from app.services.document_service import (
    confirm_upload,
    count_user_documents,
    delete_document,
    get_document_for_user,
    get_user_documents,
    initiate_upload,
    upload_document,
    transition_status,
    get_document_download_url,
)
from app.workers.queues import ingest_queue
from app.workers.failure_handler import handle_ingest_failure

router = APIRouter(prefix="/documents", tags=["documents"])

_MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB

RETRY_DELAYS = [60, 300, 900]

logger = structlog.get_logger()

@router.post(
    "/upload",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DocumentUploadResponse,
)
async def upload_document_endpoint(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_verified_user),
    db: AsyncSession = Depends(get_db),
    _rate: None = Depends(upload_guard),
) -> DocumentUploadResponse:
    """
    Upload a document for RAG ingestion.
    """
    document = await upload_document(current_user=current_user, file=file, db=db)

    try:
        from app.workers.ingest import run_ingest
        ingest_queue.enqueue(
            run_ingest,
            kwargs={"document_id": str(document.id)},
            retry=Retry(max=3, interval=RETRY_DELAYS),
            on_failure=Callback(handle_ingest_failure),
            job_timeout=600,
        )
    except Exception as e:
        # RQ enqueue failed — roll back the document so the user can retry
        logger.exception(
            "ingest_enqueue_failed",
            document_id=str(document.id),
            error=str(e),
        )
        await delete_document(
            db=db,
            document_id=document.id,
            user_id=current_user.id,
        )
        raise HTTPException(
            status_code=503,
            detail="Processing queue unavailable. Please try again shortly.",
        )
    return DocumentUploadResponse(
        document_id=document.id,
        status=DocumentStatus(document.status),
    )


@router.get(
    "/{document_id}/status",
    response_model=DocumentStatusResponse,
)
async def get_document_status(
    document_id: uuid.UUID,
    current_user: User = Depends(get_verified_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentStatusResponse:
    """
    Return status + metadata for a single document.

    Returns 404 if the document doesn't exist OR isn't owned by the caller —
    ownership check and existence check are the same query (no resource enumeration).
    """
    try:
        doc = await get_document_for_user(
            db=db,
            document_id=document_id,
            user_id=current_user.id,
        )
    except DocumentNotFoundError:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Document not found.")

    return DocumentStatusResponse.model_validate(doc)


@router.get(
    "/{document_id}/download-url",
    response_model=DocumentDownloadUrlResponse,
)
async def get_document_download_url_endpoint(
    document_id: uuid.UUID,
    current_user: User = Depends(get_verified_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentDownloadUrlResponse:
    """
    Return a presigned S3 GET URL to download the document.
    """
    try:
        url = await get_document_download_url(
            db=db,
            document_id=document_id,
            user_id=current_user.id,
        )
    except DocumentNotFoundError:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Document not found.")

    return DocumentDownloadUrlResponse(url=url)


@router.get(
    "",
    response_model=DocumentListResponse,
)
async def list_documents(
    status_filter: DocumentStatus | None = Query(
        default=None,
        alias="status",
        description="Filter by document status (PENDING, PROCESSING, READY, FAILED).",
    ),
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_verified_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentListResponse:
    """
    Paginated document list for the authenticated user.

    ?status=READY&limit=10&offset=0
    """
    items, total = await _list_with_count(
        db=db,
        user_id=current_user.id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return DocumentListResponse(
        items=[DocumentStatusResponse.model_validate(d) for d in items],
        total=total,
        limit=limit,
        offset=offset,
        pages=math.ceil(total / limit),  # limit >= 1 validated by Query(ge=1)
    )


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_document_endpoint(
    document_id: uuid.UUID,
    current_user: User = Depends(get_verified_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """
    Delete a document and all its chunks.

    - Ownership verified via 404 (not 403).
    - S3 object deleted first; DB row removed only on S3 success.
    - If the S3 object is already missing, treated as success (idempotent).
    - Returns 204 No Content on success.
    """
    from botocore.exceptions import ClientError
    from fastapi import HTTPException

    try:
        await delete_document(
            db=db,
            document_id=document_id,
            user_id=current_user.id,
        )
    except DocumentNotFoundError:
        raise HTTPException(status_code=404, detail="Document not found.")
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        raise HTTPException(
            status_code=502,
            detail=f"Storage deletion failed (code={error_code}). Document not deleted.",
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{document_id}/retry",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DocumentUploadResponse,
)
async def retry_document_endpoint(
    document_id: uuid.UUID,
    current_user: User = Depends(get_verified_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
    """
    Retry a failed document ingestion.
    """
    try:
        document = await get_document_for_user(
            db=db,
            document_id=document_id,
            user_id=current_user.id,
        )
    except DocumentNotFoundError:
        raise HTTPException(status_code=404, detail="Document not found.")

    if document.status_enum != DocumentStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only FAILED documents can be retried. Current status is {document.status}.",
        )

    # Transition to PROCESSING to signal the retry has started
    await transition_status(db, document, DocumentStatus.PROCESSING)
    await db.commit()

    try:
        from app.workers.ingest import run_ingest
        ingest_queue.enqueue(
            run_ingest,
            kwargs={"document_id": str(document.id)},
            retry=Retry(max=3, interval=RETRY_DELAYS),
            on_failure=Callback(handle_ingest_failure),
            job_timeout=600,
        )
    except Exception as e:
        logger.exception(
            "ingest_retry_enqueue_failed",
            document_id=str(document.id),
            error=str(e),
        )
        # Roll back status to FAILED
        await transition_status(
            db,
            document,
            DocumentStatus.FAILED,
            error_message="Processing queue unavailable. Please try again shortly.",
        )
        await db.commit()
        raise HTTPException(
            status_code=503,
            detail="Processing queue unavailable. Please try again shortly.",
        )

    return DocumentUploadResponse(
        document_id=document.id,
        status=DocumentStatus(document.status),
    )



# --------------------------------------------------------------------------- #
# Presigned URL upload endpoints — Step 4                                      #
# --------------------------------------------------------------------------- #

@router.post(
    "/initiate-upload",
    status_code=status.HTTP_201_CREATED,
    response_model=InitiateUploadResponse,
)
async def initiate_upload_endpoint(
    body: InitiateUploadRequest,
    request: Request,
    current_user: User = Depends(get_verified_user),
    db: AsyncSession = Depends(get_db),
    _rate: None = Depends(upload_guard),
) -> InitiateUploadResponse:
    """
    Phase 1 of the presigned URL upload flow.

    Accepts file metadata (name, size, MIME type) from the browser — **no file
    bytes are sent here**. Returns a presigned S3 PUT URL the browser must use
    to upload the file directly to S3, along with the `document_id` needed for
    the follow-up call to POST /documents/confirm-upload.

    The presigned URL expires in 15 minutes. If the browser does not complete
    the S3 PUT within that window, the document row stays in PENDING_UPLOAD and
    the stale cleanup job will mark it FAILED after 15 minutes.

    Status codes:
      201  Created    — presigned URL issued; document row in PENDING_UPLOAD
      422  Unproc.    — file too large or MIME type not allowed
      429  Too Many   — rate limit exceeded
      507  Quota      — user is at MAX_DOCS_PER_USER
    """
    from app.exceptions import QuotaExceededError
    # from app.services.file_validation import FileValidationError  # type: ignore[attr-defined]

    try:
        document, upload_url = await initiate_upload(
            current_user=current_user,
            filename=body.filename,
            mime_type=body.mime_type,
            file_size_bytes=body.file_size_bytes,
            db=db,
        )
    except QuotaExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail=str(exc),
        )

    logger.info(
        "initiate_upload_endpoint_success",
        user_id=str(current_user.id),
        document_id=str(document.id),
    )

    return InitiateUploadResponse(
        document_id=document.id,
        upload_url=upload_url,
        s3_key=document.s3_key,
        expires_in_seconds=900,  # must match _PRESIGNED_URL_EXPIRES_IN in document_service
    )


@router.post(
    "/confirm-upload",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ConfirmUploadResponse,
)
async def confirm_upload_endpoint(
    body: ConfirmUploadRequest,
    current_user: User = Depends(get_verified_user),
    db: AsyncSession = Depends(get_db),
) -> ConfirmUploadResponse:
    """
    Phase 2 of the presigned URL upload flow.

    Called by the browser **after** the S3 PUT to the presigned URL succeeds.
    The server performs a lightweight HeadObject check to confirm the file
    actually landed in S3, transitions the document to PENDING, and enqueues
    the RQ ingest job.

    Status codes:
      202  Accepted   — document is now PENDING; ingest job enqueued
      404  Not Found  — document_id not found or not owned by caller
      409  Conflict   — document is not in PENDING_UPLOAD state (double-confirm
                        or file was never uploaded to S3)
      502  Bad Gateway — unexpected S3 error during HeadObject
      503  Unavailable — RQ queue is down; document rolled back to PENDING_UPLOAD
    """
    from botocore.exceptions import ClientError
    from app.exceptions import DocumentNotFoundError

    try:
        document = await confirm_upload(
            document_id=body.document_id,
            user_id=current_user.id,
            db=db,
        )
    except DocumentNotFoundError:
        raise HTTPException(status_code=404, detail="Document not found.")
    except ValueError as exc:
        # Document is not in PENDING_UPLOAD (already confirmed or wrong state)
        raise HTTPException(status_code=409, detail=str(exc))
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        if error_code in ("404", "NoSuchKey"):
            raise HTTPException(
                status_code=409,
                detail="File not found in storage. Complete the S3 upload before confirming.",
            )
        raise HTTPException(
            status_code=502,
            detail=f"Storage verification failed (code={error_code}). Please try again.",
        )

    # Enqueue the ingest job — same pattern as the legacy /upload endpoint
    try:
        _enqueue_ingest(document.id)
    except Exception as e:
        logger.exception(
            "confirm_upload_enqueue_failed",
            document_id=str(document.id),
            error=str(e),
        )
        # The document is already PENDING at this point; PENDING → FAILED is a
        # valid transition. The user can retry processing via POST /{id}/retry.
        await transition_status(
            db,
            document,
            DocumentStatus.FAILED,
            error_message="Processing queue unavailable. Please retry.",
        )
        await db.commit()
        raise HTTPException(
            status_code=503,
            detail="Processing queue unavailable. The document has been saved — use the retry option to reprocess.",
        )

    logger.info(
        "confirm_upload_endpoint_success",
        user_id=str(current_user.id),
        document_id=str(document.id),
    )

    return ConfirmUploadResponse(
        document_id=document.id,
        status=DocumentStatus(document.status),
    )


def _enqueue_ingest(document_id: uuid.UUID) -> None:
    """
    Enqueue an RQ ingest job. Extracted into a helper so both the legacy
    /upload endpoint and the new /confirm-upload endpoint share the same
    enqueue configuration (timeout, retries, failure callback).
    """
    from app.workers.ingest import run_ingest
    ingest_queue.enqueue(
        run_ingest,
        kwargs={"document_id": str(document_id)},
        retry=Retry(max=3, interval=RETRY_DELAYS),
        on_failure=Callback(handle_ingest_failure),
        job_timeout=600,
    )


# --------------------------------------------------------------------------- #
# Internal helpers                                                             #
# --------------------------------------------------------------------------- #

async def _list_with_count(
    db: AsyncSession,
    user_id: uuid.UUID,
    status: DocumentStatus | None,
    limit: int,
    offset: int,
) -> tuple[list[Any], int]:
    """
    Run the paginated query then the COUNT query sequentially on the same session.

    asyncio.gather() on a shared AsyncSession is NOT safe — SQLAlchemy's async
    session is not designed for concurrent use from multiple coroutines.
    Sequential awaits are the correct pattern here.
    """
    items = await get_user_documents(
        db=db, user_id=user_id, status=status, limit=limit, offset=offset
    )
    total = await count_user_documents(db=db, user_id=user_id, status=status)
    return items, total
