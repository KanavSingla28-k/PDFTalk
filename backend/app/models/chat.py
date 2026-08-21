from __future__ import annotations
import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from pydantic import BaseModel, ConfigDict, Field

from sqlalchemy import DateTime, ForeignKey, Index, Text, func, JSON
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.message import Message

from app.models.message import MessageResponse


class Chat(Base):
    __tablename__ = "chats"
    __table_args__ = (
        Index(
            "idx_chats_user_id_updated_at",
            "user_id",
            "updated_at",
            postgresql_using="btree",
            postgresql_ops={"updated_at": "DESC"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False, default="New Chat")
    document_ids: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, server_default="[]"
    )

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
    user: Mapped["User"] = relationship(back_populates="chats")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="chat", cascade="all, delete-orphan"
    )


class ChatCreateRequest(BaseModel):
    document_ids: list[str]


class ChatRenameRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)


class ChatResponse(BaseModel):
    id: uuid.UUID
    title: str
    document_ids: list[str]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatDetailResponse(ChatResponse):
    messages: list["MessageResponse"] = Field(default_factory=list)
    missing_document_ids: list[str] = Field(default_factory=list)


class ChatListResponse(BaseModel):
    items: list[ChatResponse]
    total: int
    limit: int
    offset: int
    pages: int
