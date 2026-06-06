import enum
import uuid
from datetime import datetime
import math

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, Index, Text, func
from pydantic import BaseModel, ConfigDict, Field

from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DocumentStatus(str, enum.Enum):
    """
    Valid state transitions:
        PENDING → PROCESSING → READY
        PENDING → PROCESSING → FAILED
    Never go backwards. Never skip PROCESSING.
    """
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"

# Valid forward-only transitions. Any move not in this map is illegal.
_ALLOWED_TRANSITIONS: dict[DocumentStatus, set[DocumentStatus]] = {
    DocumentStatus.PENDING: {DocumentStatus.PROCESSING},
    DocumentStatus.PROCESSING: {DocumentStatus.READY, DocumentStatus.FAILED},
    DocumentStatus.READY: set(),    # terminal
    DocumentStatus.FAILED: set(),   # terminal
}

class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("idx_documents_user_id", "user_id"),
        Index("idx_documents_status", "status"),
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
        Text, nullable=False, default=DocumentStatus.PENDING.value
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


class DocumentListResponse(BaseModel):
    items: list[DocumentStatusResponse]
    total: int          # total matching rows (for the frontend pagination UI)
    limit: int
    offset: int
    pages: int          # math.ceil(total / limit)