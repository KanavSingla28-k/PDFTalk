from __future__ import annotations
import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Index, Text, func, CheckConstraint
from pydantic import BaseModel, ConfigDict, Field

from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.chunk import Chunk
    from app.models.job_log import JobLog

class DocumentStatus(str, enum.Enum):
    """
    Valid state transitions (presigned URL flow):
        PENDING_UPLOAD → PENDING    (browser finished PUT to S3; confirm-upload called)
        PENDING_UPLOAD → FAILED     (stale cleanup: browser never completed the upload)
        PENDING        → PROCESSING
        PROCESSING     → READY
        PROCESSING     → FAILED
        FAILED         → PROCESSING (retry)
    Never go backwards. Never skip PROCESSING.
    """
    PENDING_UPLOAD = "PENDING_UPLOAD"  # Waiting for browser to PUT file to S3
    PENDING    = "PENDING"             # File confirmed in S3; queued for ingest
    PROCESSING = "PROCESSING"
    READY      = "READY"
    FAILED     = "FAILED"

# Valid forward-only transitions. Any move not in this map is illegal.
_ALLOWED_TRANSITIONS: dict[DocumentStatus, set[DocumentStatus]] = {
    DocumentStatus.PENDING_UPLOAD: {DocumentStatus.PENDING, DocumentStatus.FAILED},
    DocumentStatus.PENDING:        {DocumentStatus.PROCESSING},
    DocumentStatus.PROCESSING:     {DocumentStatus.READY, DocumentStatus.FAILED},
    DocumentStatus.READY:          set(),   # terminal
    DocumentStatus.FAILED:         {DocumentStatus.PROCESSING},  # allowed for retry
}
assert set(DocumentStatus) == set(_ALLOWED_TRANSITIONS.keys()), "All DocumentStatus values must be mapped in _ALLOWED_TRANSITIONS"

class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("idx_documents_user_id", "user_id"),
        Index("idx_documents_status", "status"),
        CheckConstraint(
            f"status IN ({', '.join(repr(v.value) for v in DocumentStatus)})",
            name="check_valid_document_status"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    # S3 object key: {user_id}/{document_id}/{original_filename}
    # Never use the original filename as a path anywhere else.
    s3_key: Mapped[str] = mapped_column(Text, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)

    # Stored as Text. DocumentStatus enum enforced by document_service.transition_status().
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default=DocumentStatus.PENDING_UPLOAD.value
    )

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="documents")
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    job_logs: Mapped[list["JobLog"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    @property
    def status_enum(self) -> DocumentStatus:
        """Typed accessor for the status column."""
        return DocumentStatus(self.status)


class DocumentUploadResponse(BaseModel):
    """Response for POST /documents/upload — 202 Accepted."""
 
    document_id: uuid.UUID
    status: DocumentStatus
 
    model_config = {"from_attributes": True}

class DocumentStatusResponse(BaseModel):
    document_id: uuid.UUID = Field(validation_alias="id")
    filename: str
    status: DocumentStatus
    error_message: str | None = None
    chunk_count: int | None = None
    file_size_bytes: int
    mime_type: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentDownloadUrlResponse(BaseModel):
    url: str

class DocumentListResponse(BaseModel):
    items: list[DocumentStatusResponse]
    total: int          # total matching rows (for the frontend pagination UI)
    limit: int
    offset: int
    pages: int          # math.ceil(total / limit)


# ---------------------------------------------------------------------------
# Presigned URL upload flow — Step 2
# ---------------------------------------------------------------------------

class InitiateUploadRequest(BaseModel):
    """
    Body for POST /documents/initiate-upload.

    The client reports metadata only — no file bytes are sent to the API.
    The server validates size and MIME type, then issues a presigned S3 PUT URL.
    """
    filename: str
    file_size_bytes: int   # Validated server-side against the 50 MB limit
    mime_type: str         # Validated server-side against ALLOWED_MIME_TYPES


class InitiateUploadResponse(BaseModel):
    """
    Response for POST /documents/initiate-upload — 201 Created.

    The client must:
      1. PUT the file directly to `upload_url` with Content-Type = mime_type.
      2. On S3 200 OK, call POST /documents/confirm-upload with `document_id`.
    The presigned URL expires after `expires_in_seconds` (default 900 = 15 min).
    """
    document_id: uuid.UUID
    upload_url: str          # Presigned S3 PUT URL — send file bytes here
    s3_key: str              # Informational; needed if the client wants to verify
    expires_in_seconds: int  # Frontend can show a timeout warning to the user


class ConfirmUploadRequest(BaseModel):
    """
    Body for POST /documents/confirm-upload.

    Called by the client after the S3 PUT succeeds. The server verifies the
    object exists in S3 (HeadObject), transitions PENDING_UPLOAD → PENDING,
    and enqueues the RQ ingest job.
    """
    document_id: uuid.UUID


class ConfirmUploadResponse(BaseModel):
    """
    Response for POST /documents/confirm-upload — 202 Accepted.

    Mirrors DocumentUploadResponse so the frontend can use the same
    post-upload polling logic regardless of which upload path was used.
    """
    document_id: uuid.UUID
    status: DocumentStatus   # Always PENDING at this point
