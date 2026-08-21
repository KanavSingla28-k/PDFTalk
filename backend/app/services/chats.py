import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.exceptions import (
    ChatNotFoundError,
    EmptyDocumentListError,
    MessageNotFoundError,
)
from app.models.chat import Chat

# from app.models.message import Message
from app.models.document import Document
from app.services.query_validation import validate_documents_for_query


async def create_chat(user_id: uuid.UUID, document_ids: list[str], db: AsyncSession) -> Chat:
    if not document_ids:
        raise EmptyDocumentListError()

    doc_uuids = [uuid.UUID(d) for d in document_ids]
    # Reuses existing validation (raises 404/400 if invalid)
    await validate_documents_for_query(document_ids=doc_uuids, user_id=user_id, db=db)

    chat = Chat(user_id=user_id, document_ids=document_ids, title="New Chat")
    db.add(chat)
    await db.commit()
    await db.refresh(chat)
    return chat


async def list_chats(
    user_id: uuid.UUID, limit: int, offset: int, db: AsyncSession
) -> tuple[list[Chat], int]:
    # Need total count as well for pagination
    from sqlalchemy import func

    total_query = select(func.count()).select_from(Chat).where(Chat.user_id == user_id)
    total_result = await db.execute(total_query)
    total = total_result.scalar() or 0

    query = (
        select(Chat)
        .where(Chat.user_id == user_id)
        .order_by(Chat.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(query)
    return list(result.scalars().all()), total


async def get_chat_with_messages(
    chat_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession
) -> tuple[Chat, list[str]]:
    # 1. Fetch chat + messages
    query = (
        select(Chat)
        .options(selectinload(Chat.messages))
        .where(Chat.id == chat_id, Chat.user_id == user_id)
    )
    result = await db.execute(query)
    chat = result.scalar_one_or_none()

    if not chat:
        raise ChatNotFoundError()

    # Sort messages by created_at natively or in python
    chat.messages.sort(key=lambda m: m.created_at)

    # 2. Check missing documents dynamically
    missing_document_ids = []
    if chat.document_ids:
        doc_uuids = [uuid.UUID(d) for d in chat.document_ids]
        doc_query = select(Document.id).where(
            Document.id.in_(doc_uuids),
            Document.user_id == user_id,
        )  # Do not check READY here, just if it exists and is owned. If it's deleted, it's missing.
        doc_result = await db.execute(doc_query)
        found_uuids = {str(d_id) for d_id in doc_result.scalars().all()}

        missing_document_ids = [d for d in chat.document_ids if d not in found_uuids]

    return chat, missing_document_ids


async def rename_chat(
    chat_id: uuid.UUID, user_id: uuid.UUID, new_title: str, db: AsyncSession
) -> Chat:
    # We must bump updated_at explicitly since update() doesn't auto-trigger onupdate hook in asyncpg sometimes,
    # but let's use the ORM to do it safely.
    query = select(Chat).where(Chat.id == chat_id, Chat.user_id == user_id)
    result = await db.execute(query)
    chat = result.scalar_one_or_none()

    if not chat:
        raise ChatNotFoundError()

    chat.title = new_title
    # updated_at is bumped by sqlalchemy onupdate
    await db.commit()
    await db.refresh(chat)
    return chat


async def delete_chat(chat_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession) -> None:
    query = select(Chat).where(Chat.id == chat_id, Chat.user_id == user_id)
    result = await db.execute(query)
    chat = result.scalar_one_or_none()

    if not chat:
        raise ChatNotFoundError()

    await db.delete(chat)
    await db.commit()


async def truncate_chat_from_message(
    chat_id: uuid.UUID, user_id: uuid.UUID, message_id: uuid.UUID, db: AsyncSession
) -> None:
    from sqlalchemy import delete, func, update

    from app.models.message import Message

    # 1. Verify chat ownership
    query = select(Chat).where(Chat.id == chat_id, Chat.user_id == user_id)
    result = await db.execute(query)
    chat = result.scalar_one_or_none()
    if not chat:
        raise ChatNotFoundError()

    # 2. Get target message's created_at
    msg_query = select(Message.created_at).where(
        Message.id == message_id, Message.chat_id == chat_id
    )
    msg_result = await db.execute(msg_query)
    target_created_at = msg_result.scalar_one_or_none()

    if not target_created_at:
        raise MessageNotFoundError()

    # 3. Delete messages from that point onwards
    del_query = delete(Message).where(
        Message.chat_id == chat_id, Message.created_at >= target_created_at
    )
    await db.execute(del_query)

    # 4. Bump chat updated_at
    upd_query = update(Chat).where(Chat.id == chat_id).values(updated_at=func.now())
    await db.execute(upd_query)

    await db.commit()
