from __future__ import annotations
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentStatus
from app.exceptions import (
    DocumentNotFoundError,
    DocumentNotReadyError,
)
from app.models.chat import Chat

async def validate_documents_for_query(
    document_ids: list[uuid.UUID],
    user_id: uuid.UUID,
    db: AsyncSession,
) -> list[Document]:
    """
    For each document_id in the request:
      - Must exist
      - Must be owned by the requesting user (returns 404 if not — never 403,
        to avoid leaking that the document exists at all)
      - Must be in READY status

    Returns the list of Document ORM objects on success.
    Raises DocumentNotFoundError or DocumentNotReadyError on failure.
    """
    # Fetch only documents owned by this user — ownership enforced at DB level,
    # not just in Python. This prevents loading other users' documents into the
    # ORM session even temporarily.
    result = await db.execute(
        select(Document).where(
            Document.id.in_(document_ids),
            Document.user_id == user_id,
        )
    )
    documents = result.scalars().all()

    # Build a lookup by id for O(1) access
    found = {doc.id: doc for doc in documents}

    for doc_id in document_ids:
        doc = found.get(doc_id)

        # Not found OR belongs to a different user → 404
        # The 404 (not 403) is intentional: a 403 would reveal the resource exists
        if doc is None:
            raise DocumentNotFoundError(document_id=doc_id)

        if doc.status != DocumentStatus.READY:
            raise DocumentNotReadyError(document_id=doc_id, status=doc.status)

    return list(found.values())

async def validate_chat_for_query(
    chat_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> tuple["Chat", list[uuid.UUID], list[str]]:
    """
    Fetches the chat, filters its document_ids to only those that still exist
    and are owned by the user. If none remain, raises AllDocumentsDeletedError.
    Returns (chat, valid_document_uuids, missing_document_ids).
    """
    from app.models.chat import Chat
    from app.exceptions import ChatNotFoundError, AllDocumentsDeletedError
    
    from sqlalchemy.orm import selectinload
    result = await db.execute(select(Chat).options(selectinload(Chat.messages)).where(Chat.id == chat_id, Chat.user_id == user_id))
    chat = result.scalar_one_or_none()
    
    if not chat:
        raise ChatNotFoundError()
        
    if not chat.document_ids:
        from app.utils.metrics import chat_query_blocked_total
        chat_query_blocked_total.labels(reason="all_documents_deleted").inc()
        raise AllDocumentsDeletedError()
        
    doc_uuids = [uuid.UUID(d) for d in chat.document_ids]
    
    # Check which documents still exist and are owned
    doc_result = await db.execute(
        select(Document.id, Document.status).where(
            Document.id.in_(doc_uuids),
            Document.user_id == user_id,
        )
    )
    docs = doc_result.all()
    
    valid_uuids = []
    found_ids_str = set()
    for d_id, d_status in docs:
        found_ids_str.add(str(d_id))
        if d_status == DocumentStatus.READY:
            valid_uuids.append(d_id)
            
    if not valid_uuids:
        from app.utils.metrics import chat_query_blocked_total
        chat_query_blocked_total.labels(reason="all_documents_deleted").inc()
        raise AllDocumentsDeletedError()
        
    missing_ids = [d for d in chat.document_ids if d not in found_ids_str]
    return chat, valid_uuids, missing_ids
