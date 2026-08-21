# Import order matters for forward references in relationships.
# Base must be imported first, then all models so SQLAlchemy can resolve
# the string-based relationship references (e.g. "Document" in User.documents).

from app.db.base import Base
from app.models.auth import EmailVerification, RefreshToken
from app.models.chat import Chat
from app.models.chunk import EMBEDDING_DIMENSIONS, Chunk
from app.models.document import Document, DocumentStatus
from app.models.job_log import JobLog
from app.models.message import Message, MessageRole, MessageStatus
from app.models.query import QueryRequest
from app.models.user import User

__all__ = [
    "EMBEDDING_DIMENSIONS",
    "Base",
    "Chat",
    "Chunk",
    "Document",
    "DocumentStatus",
    "EmailVerification",
    "JobLog",
    "Message",
    "MessageRole",
    "MessageStatus",
    "QueryRequest",
    "RefreshToken",
    "User",
]
