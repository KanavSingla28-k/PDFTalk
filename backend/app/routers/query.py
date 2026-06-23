"""
routers/query.py  (T-39 / T-40)

POST /query/ask — SSE streaming endpoint.
"""

from __future__ import annotations

import asyncio
import json
import structlog
from typing import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from openai import APITimeoutError
from openai.types.chat import ChatCompletionMessageParam
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_verified_user
from app.core.config import settings
from app.db.session import get_db
from app.models.query import QueryRequest
from app.models.user import User
from app.models.message import Message, MessageRole, MessageStatus
from app.services.query_validation import validate_chat_for_query
from app.services.retrieval import retrieve_similar_chunks, RetrievedChunk
from app.services.prompt import build_messages, _count_tokens
from app.services.llm import stream_llm_response
from app.utils.openai_client import (
    CircuitBreakerOpenError,
    DailyQuotaExceededError,
    DailyQueryQuotaExceededError,
    OpenAIRetryExhaustedError,
    check_and_increment_query_usage,
)
from app.utils.rate_limit import RateLimiter, user_id_from_request
from app.utils.metrics import queries_total, stream_errors_total, messages_total

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/query", tags=["query"])

_query_limiter = RateLimiter(
    limit=20,
    window_seconds=60,
    key_prefix="query",
    identifier_fn=user_id_from_request,
)


def _error_event(code: str, message: str) -> str:
    return "data: " + json.dumps({"error": code, "message": message}) + "\n\n"


@router.post("/ask")
async def ask(
    request: Request,
    body: QueryRequest,
    current_user: User = Depends(get_verified_user),
    db: AsyncSession = Depends(get_db),
    _rate: None = Depends(_query_limiter),
) -> StreamingResponse:
    chat, valid_uuids, missing_ids = await validate_chat_for_query(
        chat_id=body.chat_id,
        user_id=current_user.id,
        db=db,
    )

    # Only decrement quota after verifying the chat exists and belongs to the user
    await check_and_increment_query_usage(user_id=str(current_user.id))

    chunks = await retrieve_similar_chunks(
        user_id=current_user.id,
        document_ids=valid_uuids,
        query=body.question,
        db=db,
    )

    # Sort chat messages to pass to prompt builder
    chat.messages.sort(key=lambda m: m.created_at)
    
    messages, _included_chunks = build_messages(chunks, body.question, history_messages=chat.messages)

    # Detect whether the LLM is going to use its graceful Rule-5 fallback.
    # Two signals indicate a low/no-relevance response:
    #   1. No chunks fit the token budget (included_chunks is empty).
    #   2. Every retrieved chunk exceeded the configured distance ceiling,
    #      meaning retrieval returned its "full-list fallback" (all irrelevant).
    _is_fallback = (
        not _included_chunks
        or (bool(chunks) and all(c.distance > settings.RETRIEVAL_MAX_DISTANCE for c in chunks))
    )

    # Pre-stream message save
    user_msg = Message(
        chat_id=chat.id,
        role=MessageRole.USER,
        content=body.question,
        token_count=_count_tokens(body.question),
        status=MessageStatus.COMPLETE,
    )
    db.add(user_msg)
    messages_total.labels(role="user").inc()
    
    if chat.title == "New Chat":
        chat.title = body.question[:50].strip()
        
    from sqlalchemy import func
    chat.updated_at = func.now()
    await db.commit()

    # Increment here — after all pre-stream validation passes, before the
    # stream is opened. This counts queries that reached the LLM, not ones
    # that failed validation.
    queries_total.inc()

    return StreamingResponse(
        _sse_generator(
            messages=messages,
            user_id=str(current_user.id),
            included_chunks=_included_chunks,
            chat_id=str(chat.id),
            missing_ids=missing_ids,
            is_fallback=_is_fallback,
            db=db,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def _sse_generator(
    messages: list[ChatCompletionMessageParam],
    user_id: str,
    included_chunks: list[RetrievedChunk],
    chat_id: str,
    missing_ids: list[str],
    is_fallback: bool,
    db: AsyncSession,
) -> AsyncIterator[str]:
    if missing_ids:
        yield f"event: meta\ndata: {json.dumps({'missing_document_ids': missing_ids})}\n\n"

    token_stream = stream_llm_response(messages=messages, user_id=user_id)
    generation_completed = False
    accumulated_content = ""

    try:
        while True:
            try:
                token = await asyncio.wait_for(
                    token_stream.__anext__(),
                    timeout=settings.STREAM_CHUNK_TIMEOUT,
                )
            except StopAsyncIteration:
                generation_completed = True
                break
            accumulated_content += token
            # Wrap token in JSON to safely encode newlines and special characters
            token_data = {"type": "token", "content": token}
            yield f"data: {json.dumps(token_data)}\n\n"

        # Stream source citations before the terminal DONE event
        sources_data = {
            "type": "sources",
            "chunks": [
                {
                    "document_id": str(c.document_id),
                    "filename": c.filename,
                    "chunk_index": c.chunk_index,
                }
                for c in included_chunks
            ]
        }
        yield f"data: {json.dumps(sources_data)}\n\n"

        # Emit the fallback signal BEFORE [DONE] so the client can attach
        # suggestion chips as soon as the stream closes.
        if is_fallback:
            yield f"data: {json.dumps({'type': 'fallback'})}\n\n"

        yield "data: [DONE]\n\n"

    except asyncio.TimeoutError:
        if generation_completed:
            logger.warning(
                "sse.post_completion_cleanup_timeout",
                user_id=user_id,
            )
            yield "data: [DONE]\n\n"
            return
        logger.error(
            "sse.stream_timeout",
            user_id=user_id,
            timeout_seconds=settings.STREAM_CHUNK_TIMEOUT,
        )
        stream_errors_total.labels(error_code="STREAM_TIMEOUT").inc()
        yield _error_event(
            "STREAM_TIMEOUT",
            "The response took too long to generate. Please try again.",
        )

    except APITimeoutError:
        if generation_completed:
            logger.warning("sse.post_completion_cleanup_api_timeout", user_id=user_id)
            yield "data: [DONE]\n\n"
            return
        logger.error("sse.openai_api_timeout", user_id=user_id)
        stream_errors_total.labels(error_code="STREAM_TIMEOUT").inc()
        yield _error_event(
            "STREAM_TIMEOUT",
            "The response took too long to generate. Please try again.",
        )

    except DailyQuotaExceededError:
        if generation_completed:
            # Quota was exceeded by THIS response's own token usage, surfaced
            # during post-completion accounting. The answer already rendered
            # successfully — don't retroactively mark it as an error. The
            # quota state itself is recorded regardless (see llm.py); this
            # only affects what we tell the client about THIS request.
            logger.warning(
                "sse.quota_exceeded_post_completion",
                user_id=user_id,
            )
            yield "data: [DONE]\n\n"
            return
        logger.warning("sse.daily_token_quota_exceeded", user_id=user_id)
        stream_errors_total.labels(error_code="DAILY_QUOTA_EXCEEDED").inc()
        yield _error_event(
            "DAILY_QUOTA_EXCEEDED",
            "You have reached your daily usage limit. Please try again tomorrow.",
        )

    except DailyQueryQuotaExceededError:
        if generation_completed:
            logger.warning("sse.query_quota_exceeded_post_completion", user_id=user_id)
            yield "data: [DONE]\n\n"
            return
        logger.warning("sse.daily_query_quota_exceeded", user_id=user_id)
        stream_errors_total.labels(error_code="DAILY_QUOTA_EXCEEDED").inc()
        yield _error_event(
            "DAILY_QUOTA_EXCEEDED",
            "You have reached your daily query limit. Please try again tomorrow.",
        )

    except (CircuitBreakerOpenError, OpenAIRetryExhaustedError) as exc:
        if generation_completed:
            logger.warning(
                "sse.post_completion_cleanup_openai_error",
                user_id=user_id,
                exc_type=type(exc).__name__,
            )
            yield "data: [DONE]\n\n"
            return
        logger.error(
            "sse.openai_unavailable",
            user_id=user_id,
            exc_type=type(exc).__name__,
        )
        stream_errors_total.labels(error_code="AI_SERVICE_UNAVAILABLE").inc()
        yield _error_event(
            "AI_SERVICE_UNAVAILABLE",
            "The AI service is temporarily unavailable. Please try again shortly.",
        )

    except Exception as exc:
        if generation_completed:
            # Generation succeeded; this is an unanticipated failure in
            # post-completion cleanup (sources payload, metrics, etc).
            # Log loudly so it's not silently lost, but don't lie to the
            # user by telling them their (already-successful) answer failed.
            logger.exception(
                "sse.post_completion_cleanup_error",
                user_id=user_id,
                exc_type=type(exc).__name__,
            )
            yield "data: [DONE]\n\n"
            return
        logger.exception(
            "sse.unexpected_error",
            user_id=user_id,
            exc_type=type(exc).__name__,
        )
        stream_errors_total.labels(error_code="STREAM_ERROR").inc()
        yield _error_event(
            "STREAM_ERROR",
            "An unexpected error occurred while generating the response.",
        )

    finally:
        if accumulated_content:
            import uuid
            from sqlalchemy import update
            from sqlalchemy import func
            from app.models.chat import Chat
            from app.models.message import Message, MessageRole, MessageStatus
            
            status = MessageStatus.COMPLETE if generation_completed else MessageStatus.TRUNCATED
            assistant_msg = Message(
                chat_id=uuid.UUID(chat_id),
                role=MessageRole.ASSISTANT,
                content=accumulated_content,
                token_count=_count_tokens(accumulated_content),
                status=status,
            )
            db.add(assistant_msg)
            messages_total.labels(role="assistant").inc()
            
            # Use execute(update(...)) to bump updated_at without needing to load the chat
            await db.execute(
                update(Chat)
                .where(Chat.id == uuid.UUID(chat_id))
                .values(updated_at=func.now())
            )
            await db.commit()
