import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.user import User
from app.models.document import Document
# Dimensions must match your embedding model's output.
# OpenAI text-embedding-3-small = 1536.
# If you ever change models, you must drop + recreate this column and re-embed everything.
EMBEDDING_DIMENSIONS = 1536


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        Index("idx_chunks_document_id", "document_id"),
        # Direct user_id index lets the vector similarity query filter by user
        # without joining through documents. Critical for query performance.
        Index("idx_chunks_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Denormalised from document.user_id for fast single-table vector queries.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)

    # The vector column. NULL until the embedding worker populates it.
    # pgvector stores this as a fixed-length binary array on disk.
    # Do NOT add an IVFFlat index here — wait until migration 002
    # once you have real data to build clusters from.
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIMENSIONS), nullable=True
    )

    # Relationships
    document: Mapped["Document"] = relationship(back_populates="chunks")
