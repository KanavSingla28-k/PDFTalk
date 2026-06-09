"""
services/llm.py  (T-38)

Streaming LLM service for RAG query responses.

Responsibilities:
  - Accept a pre-built messages list from services/prompt.py (T-37)
  - Stream tokens from gpt-4o-mini via openai_client._stream_chat_with_usage()
  - Capture API-reported output token count from the final stream chunk
    (stream_options={"include_usage": True}, per T-44)
  - Update the user's daily token quota after the stream completes
  - Propagate circuit breaker / retry errors as-is for the router (T-39)
    to surface as SSE error events

Callers receive an async generator of str token strings. The generator
raises on connection failure (before any tokens are yielded) and propagates
mid-stream errors to the caller if they occur.

Token counting:
  Token counts come directly from the API's usage field on the final chunk
  (stream_options={"include_usage": True}). This is accurate BPE token count
  from the model itself, used for quota purposes.
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

from openai.types.chat import ChatCompletionMessageParam
from app.utils.openai_client import (
    _stream_chat_with_usage,
    check_and_increment_token_usage,
    CircuitBreakerOpenError,
    DailyQuotaExceededError,
    OpenAIRetryExhaustedError,
)

logger = logging.getLogger(__name__)

_MODEL = "gpt-4o-mini"
_MAX_TOKENS = 1024   # cap output; matches chat_complete default


async def stream_llm_response(
    messages: list[ChatCompletionMessageParam],
    user_id: str,
) -> AsyncIterator[str]:
    """
    Async generator that streams token strings from gpt-4o-mini.

    Usage:
        async for token in stream_llm_response(messages, user_id=user_id):
            # send token to client via SSE

    Raises before yielding any tokens:
        CircuitBreakerOpenError   — OpenAI unavailable; router should 503
        OpenAIRetryExhaustedError — rate limit; router should 503
        DailyQuotaExceededError   — user quota full; router should 429

    Mid-stream errors propagate as exceptions from the generator after
    tokens have already been yielded; the SSE router (T-39) catches these
    and emits a terminal error event.
    """
    token_stream = _stream_chat_with_usage(
        messages=messages,
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
    )

    output_tokens = 0

    try:
        async for token, usage in token_stream:
            if token is not None:
                yield token
            elif usage is not None:
                # Final chunk — API-reported completion token count.
                output_tokens = usage.completion_tokens or 0
    finally:
        # Always attempt quota accounting, even if the stream was cut short.
        # A partial response still consumed real tokens.
        if output_tokens > 0:
            try:
                await check_and_increment_token_usage(user_id, output_tokens)
            except DailyQuotaExceededError:
                # Quota exceeded mid-stream. The tokens are already sent to the
                # client so we can't un-yield them. Log and re-raise so the
                # router can emit a terminal SSE error event.
                logger.warning(
                    "User %s exceeded daily token quota mid-stream "
                    "(%d output tokens in this response).",
                    user_id,
                    output_tokens,
                )
                raise
            except Exception:
                # Redis failure: log and swallow. Quota accuracy degrades
                # gracefully — don't crash a completed stream over a counter.
                logger.exception(
                    "Failed to record %d output tokens for user %s. "
                    "Quota counter may be inaccurate.",
                    output_tokens,
                    user_id,
                )

        logger.debug(
            "LLM stream complete for user %s: %d output tokens (API-reported).",
            user_id,
            output_tokens,
        )