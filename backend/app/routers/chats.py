import math
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.auth.dependencies import get_current_user
from app.models.user import User
from app.models.chat import (
    ChatCreateRequest,
    ChatRenameRequest,
    ChatResponse,
    ChatDetailResponse,
    ChatListResponse,
)
from app.models.message import MessageResponse  # required for ChatDetailResponse typing
from app.services import chats
from app.utils.rate_limit import RateLimiter

router = APIRouter(prefix="/chats", tags=["chats"])

# 10/min/user rate limit for chat creation
chat_create_limiter = RateLimiter(limit=10, window_seconds=60, key_prefix="chat_create")

@router.post(
    "",
    response_model=ChatResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(chat_create_limiter)]
)
async def create_chat(
    request: ChatCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ChatResponse:
    chat = await chats.create_chat(
        user_id=current_user.id,
        document_ids=request.document_ids,
        db=db,
    )
    return ChatResponse.model_validate(chat)

@router.get("", response_model=ChatListResponse)
async def list_chats(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> ChatListResponse:
    chat_list, total = await chats.list_chats(
        user_id=current_user.id, limit=limit, offset=offset, db=db
    )
    pages = math.ceil(total / limit) if limit > 0 else 0
    return ChatListResponse(
        items=[ChatResponse.model_validate(c) for c in chat_list],
        total=total,
        limit=limit,
        offset=offset,
        pages=pages,
    )

@router.get("/{chat_id}", response_model=ChatDetailResponse)
async def get_chat(
    chat_id: uuid.UUID = Path(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatDetailResponse:
    chat, missing_document_ids = await chats.get_chat_with_messages(
        chat_id=chat_id, user_id=current_user.id, db=db
    )
    
    # We construct the response explicitly because we need to inject missing_document_ids
    # which is not an attribute of the Chat ORM model
    return ChatDetailResponse(
        id=chat.id,
        title=chat.title,
        document_ids=chat.document_ids,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
        messages=[MessageResponse.model_validate(m) for m in chat.messages],
        missing_document_ids=missing_document_ids
    )

@router.patch("/{chat_id}", response_model=ChatResponse)
async def rename_chat(
    request: ChatRenameRequest,
    chat_id: uuid.UUID = Path(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    chat = await chats.rename_chat(
        chat_id=chat_id, user_id=current_user.id, new_title=request.title, db=db
    )
    return ChatResponse.model_validate(chat)

@router.delete("/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat(
    chat_id: uuid.UUID = Path(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await chats.delete_chat(chat_id=chat_id, user_id=current_user.id, db=db)
