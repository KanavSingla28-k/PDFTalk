"""
routers/query.py  (T-39 / T-40)

POST /query/ask — SSE streaming endpoint.

Request lifecycle:
    1. get_verified_user dependency  — auth + account status (401/403)
    2. QueryRequest validation       — Pydantic, document_ids + question (422)
    3. validate_documents_for_query  — ownership + READY check (404/409)
    4. retrieve_similar_chunks       — embed query, pgvector search
    5. build_messages                — assemble OpenAI messages list
    6. StreamingResponse returned    — 200 OK + SSE headers sent to client
    7. _sse_generator consumed       — token stream, quota accounting

Pre-stream errors (steps 1–5) raise domain exceptions mapped to HTTP responses
by register_exception_handlers() in main.py.

Mid-stream errors (step 7) cannot change the status code (200 OK already
sent). The generator emits a terminal SSE error event and closes.

SSE format:
    Token:  data: {token}\n\n
    Done:   data: [DONE]\n\n
    Error:  data: {"error": "CODE", "message": "..."}\n\n

Per-chunk timeout (settings.STREAM_CHUNK_TIMEOUT):
    asyncio.wait_for() wraps each __anext__() call on the token stream.
    This bounds the worst-case time between successive tokens, covering:
      - Hung async generators that never raise
      - Network stalls not caught by the OpenAI client's read timeout
      - Future provider swaps with different timeout behaviour
    openai.APITimeoutError is caught separately — it fires when the OpenAI
    SDK's own read timeout expires, which may be shorter than our chunk
    timeout on slow connections.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from openai import APITimeoutError
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
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/query", tags=["query"])

# ---------------------------------------------------------------------------
# Rate limiter — 20 queries per user per minute (T-42 spec).
# ---------------------------------------------------------------------------

_query_limiter = RateLimiter(
    limit=20,
    window_seconds=60,
    key_prefix="query",
    identifier_fn=user_id_from_request,
)

# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------

def _error_event(code: str, message: str) -> str:
    """Format a terminal SSE error event."""
    return "data: " + json.dumps({"error": code, "message": message}) + "\n\n"


# ---------------------------------------------------------------------------
# Route handler
# ---------------------------------------------------------------------------

@router.post("/ask")
async def ask(
    request: Request,
    body: QueryRequest,
    current_user: User = Depends(get_verified_user),
    db: AsyncSession = Depends(get_db),
    _rate: None = Depends(_query_limiter), 
) -> StreamingResponse:
    """
    Stream a RAG-grounded answer to the user's question.

    All pre-stream validation runs before StreamingResponse is returned,
    so failures here produce normal HTTP error responses (not SSE events).
    """
    # Step 2b: Daily query quota check (T-44).
    # Runs before any embedding/LLM calls so over-quota users are rejected
    # cheaply, before any OpenAI spend occurs. Raises DailyQueryQuotaExceededError
    # which is mapped to 429 by register_exception_handlers().
    await check_and_increment_query_usage(user_id=str(current_user.id))

    # Step 3: ownership + READY check
    # Raises DocumentNotFoundError (404) or DocumentNotReadyError (409).
    await validate_documents_for_query(
        document_ids=body.document_ids,
        user_id=current_user.id,
        db=db,
    )

    # Step 4: embed query + pgvector retrieval
    # Raises CircuitBreakerOpenError (503) if OpenAI is down.
    chunks = await retrieve_similar_chunks(
        user_id=current_user.id,
        document_ids=body.document_ids,
        query=body.question,
        db=db,
    )

    # Step 5: build OpenAI messages list
    messages, _included_chunks = build_messages(chunks, body.question)

    # Step 6: return StreamingResponse — generator is not entered until
    # FastAPI begins consuming it, after 200 OK + headers are flushed.
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


# ---------------------------------------------------------------------------
# SSE generator
# ---------------------------------------------------------------------------

async def _sse_generator(
    messages: list,
    user_id: str,
) -> AsyncIterator[str]:
    """
    Async generator consumed by StreamingResponse.

    Token loop uses asyncio.wait_for() per chunk to enforce
    settings.STREAM_CHUNK_TIMEOUT between successive tokens.
    This catches hung generators and network stalls that the OpenAI
    SDK's own read timeout would not surface as APITimeoutError.

    Error precedence (all emit a terminal SSE event then close):
        asyncio.TimeoutError        → STREAM_TIMEOUT   (504 semantic)
        APITimeoutError             → STREAM_TIMEOUT   (504 semantic)
        DailyQuotaExceededError     → DAILY_QUOTA_EXCEEDED  (429 semantic)
        CircuitBreakerOpenError     → AI_SERVICE_UNAVAILABLE (503 semantic)
        OpenAIRetryExhaustedError   → AI_SERVICE_UNAVAILABLE (503 semantic)
        Exception                   → STREAM_ERROR     (catch-all)
    """
    token_stream = stream_llm_response(messages=messages, user_id=user_id)

    try:
        while True:
            try:
                token = await asyncio.wait_for(
                    token_stream.__anext__(),
                    timeout=settings.STREAM_CHUNK_TIMEOUT,
                )
            except StopAsyncIteration:
                # Clean end of stream.
                break
            yield f"data: {token}\n\n"

        yield "data: [DONE]\n\n"

    except asyncio.TimeoutError:
        logger.error(
            "SSE stream timed out for user %s — no token received within %ds.",
            user_id,
            settings.STREAM_CHUNK_TIMEOUT,
        )
        yield _error_event(
            "STREAM_TIMEOUT",
            "The response took too long to generate. Please try again.",
        )

    except APITimeoutError:
        # OpenAI SDK's own read timeout — covers the case where the SDK
        # fires before our per-chunk timeout does (e.g. slow first token).
        logger.error("OpenAI APITimeoutError mid-stream for user %s.", user_id)
        yield _error_event(
            "STREAM_TIMEOUT",
            "The response took too long to generate. Please try again.",
        )

    except DailyQuotaExceededError:
        # Re-raised from llm.py's finally block after quota counter crosses
        # the limit. Tokens already yielded cannot be un-sent.
        logger.warning("Daily token quota exceeded mid-stream for user %s.", user_id)
        yield _error_event(
            "DAILY_QUOTA_EXCEEDED",
            "You have reached your daily usage limit. Please try again tomorrow.",
        )

    except DailyQueryQuotaExceededError:
        # Theoretically fires mid-stream only if quota rolled over mid-response.
        logger.warning("Daily query quota exceeded mid-stream for user %s.", user_id)
        yield _error_event(
            "DAILY_QUOTA_EXCEEDED",
            "You have reached your daily query limit. Please try again tomorrow.",
        )

    except (CircuitBreakerOpenError, OpenAIRetryExhaustedError) as exc:
        # Theoretically possible if the breaker trips between connection and
        # first token, or on a reconnect attempt inside the SDK.
        logger.error(
            "OpenAI unavailable mid-stream for user %s: %s",
            user_id,
            type(exc).__name__,
        )
        yield _error_event(
            "AI_SERVICE_UNAVAILABLE",
            "The AI service is temporarily unavailable. Please try again shortly.",
        )

    except Exception as exc:
        logger.exception(
            "Unexpected error in SSE stream for user %s: %s", user_id, exc
        )
        yield _error_event(
            "STREAM_ERROR",
            "An unexpected error occurred while generating the response.",
        )