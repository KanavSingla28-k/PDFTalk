"""
routers/query.py  (T-39 / T-40)

POST /query/ask — SSE streaming endpoint.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator, Any

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
from app.services.query_validation import validate_documents_for_query
from app.services.retrieval import retrieve_similar_chunks
from app.services.prompt import build_messages
from app.services.llm import stream_llm_response
from app.utils.openai_client import (
    CircuitBreakerOpenError,
    DailyQuotaExceededError,
    DailyQueryQuotaExceededError,
    OpenAIRetryExhaustedError,
    check_and_increment_query_usage,
)
from app.utils.rate_limit import RateLimiter, user_id_from_request
from app.utils.metrics import queries_total, stream_errors_total

logger = logging.getLogger(__name__)

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
    await check_and_increment_query_usage(user_id=str(current_user.id))

    await validate_documents_for_query(
        document_ids=body.document_ids,
        user_id=current_user.id,
        db=db,
    )

    chunks = await retrieve_similar_chunks(
        user_id=current_user.id,
        document_ids=body.document_ids,
        query=body.question,
        db=db,
    )

    messages, _included_chunks = build_messages(chunks, body.question)

    # Increment here — after all pre-stream validation passes, before the
    # stream is opened. This counts queries that reached the LLM, not ones
    # that failed validation.
    queries_total.inc()

    return StreamingResponse(
        _sse_generator(
            messages=messages,
            user_id=str(current_user.id),
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
) -> AsyncIterator[str]:
    token_stream = stream_llm_response(messages=messages, user_id=user_id)

    try:
        while True:
            try:
                token = await asyncio.wait_for(
                    token_stream.__anext__(),
                    timeout=settings.STREAM_CHUNK_TIMEOUT,
                )
            except StopAsyncIteration:
                break
            yield f"data: {token}\n\n"

        yield "data: [DONE]\n\n"

    except asyncio.TimeoutError:
        logger.error(
            "SSE stream timed out for user %s — no token received within %ds.",
            user_id,
            settings.STREAM_CHUNK_TIMEOUT,
        )
        stream_errors_total.labels(error_code="STREAM_TIMEOUT").inc()
        yield _error_event(
            "STREAM_TIMEOUT",
            "The response took too long to generate. Please try again.",
        )

    except APITimeoutError:
        logger.error("OpenAI APITimeoutError mid-stream for user %s.", user_id)
        stream_errors_total.labels(error_code="STREAM_TIMEOUT").inc()
        yield _error_event(
            "STREAM_TIMEOUT",
            "The response took too long to generate. Please try again.",
        )

    except DailyQuotaExceededError:
        logger.warning("Daily token quota exceeded mid-stream for user %s.", user_id)
        stream_errors_total.labels(error_code="DAILY_QUOTA_EXCEEDED").inc()
        yield _error_event(
            "DAILY_QUOTA_EXCEEDED",
            "You have reached your daily usage limit. Please try again tomorrow.",
        )

    except DailyQueryQuotaExceededError:
        logger.warning("Daily query quota exceeded mid-stream for user %s.", user_id)
        stream_errors_total.labels(error_code="DAILY_QUOTA_EXCEEDED").inc()
        yield _error_event(
            "DAILY_QUOTA_EXCEEDED",
            "You have reached your daily query limit. Please try again tomorrow.",
        )

    except (CircuitBreakerOpenError, OpenAIRetryExhaustedError) as exc:
        logger.error(
            "OpenAI unavailable mid-stream for user %s: %s",
            user_id,
            type(exc).__name__,
        )
        stream_errors_total.labels(error_code="AI_SERVICE_UNAVAILABLE").inc()
        yield _error_event(
            "AI_SERVICE_UNAVAILABLE",
            "The AI service is temporarily unavailable. Please try again shortly.",
        )

    except Exception as exc:
        logger.exception(
            "Unexpected error in SSE stream for user %s: %s", user_id, exc
        )
        stream_errors_total.labels(error_code="STREAM_ERROR").inc()
        yield _error_event(
            "STREAM_ERROR",
            "An unexpected error occurred while generating the response.",
        )
