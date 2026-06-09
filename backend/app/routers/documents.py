import math
import uuid
from rq import Retry

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.auth.dependencies import get_verified_user
from app.db.session import get_db
from app.exceptions import FileValidationError, QuotaExceededError
from app.models.document import (
    DocumentListResponse,
    DocumentStatus,
    DocumentStatusResponse,
    DocumentUploadResponse,
)
from app.models.user import User
from app.exceptions import DocumentNotFoundError
from app.services.document_service import (
    count_user_documents,
    delete_document,
    get_document_for_user,
    get_user_documents,
    upload_document,
)
from app.utils.rate_limit import RateLimiter, user_id_from_request
from app.workers.queues import ingest_queue
from app.workers.failure_handler import handle_ingest_failure
from app.workers.worker import RETRY_DELAYS

router = APIRouter(prefix="/documents", tags=["documents"])

_MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Rate limiter — defined once at module level, reused per request.
# 5 uploads per user per minute (T-42 spec).
# Uses user_id_from_request so each user has an independent counter;
# a shared office IP won't cause colleagues to hit each other's limits.
# ---------------------------------------------------------------------------

_upload_limiter = RateLimiter(
    limit=5,
    window_seconds=60,
    key_prefix="upload",
    identifier_fn=user_id_from_request,
)

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
    _rate: None = Depends(_upload_limiter), 
) -> DocumentUploadResponse:
    """
    Upload a document for RAG ingestion.
    """
    document = await upload_document(current_user=current_user, file=file, db=db)

    try:
        ingest_queue.enqueue(
            "app.workers.ingest.run_ingest",
            kwargs={"document_id": str(document.id)},
            retry=Retry(max=3, interval=RETRY_DELAYS),
            on_failure=handle_ingest_failure,
            job_timeout=600,
        )
    except Exception:
        # RQ enqueue failed — roll back the document so the user can retry
        logger.error(
            "ingest_enqueue_failed",
            document_id=str(document.id),
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
        status=document.status,
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


# --------------------------------------------------------------------------- #
# Internal helpers                                                             #
# --------------------------------------------------------------------------- #

async def _list_with_count(
    db: AsyncSession,
    user_id: uuid.UUID,
    status: DocumentStatus | None,
    limit: int,
    offset: int,
) -> tuple[list, int]:
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