from __future__ import annotations
import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from pydantic import BaseModel, ConfigDict

from sqlalchemy import DateTime, ForeignKey, Index, Text, func, Integer, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.chat import Chat

class MessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"

class MessageStatus(str, enum.Enum):
    COMPLETE = "complete"
    TRUNCATED = "truncated"

class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("idx_messages_chat_id_created_at", "chat_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    chat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chats.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[MessageRole] = mapped_column(
        SQLEnum(MessageRole, name="message_role_enum", native_enum=True), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Token count is stored to avoid re-tokenizing history on every request
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    
    status: Mapped[MessageStatus] = mapped_column(
        SQLEnum(MessageStatus, name="message_status_enum", native_enum=True), 
        nullable=False, 
        default=MessageStatus.COMPLETE
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    chat: Mapped["Chat"] = relationship(back_populates="messages")

class MessageResponse(BaseModel):
    id: uuid.UUID
    role: MessageRole
    content: str
    status: MessageStatus
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)
