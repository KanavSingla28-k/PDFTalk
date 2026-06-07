"""
services/llm.py  (T-38)

Streaming LLM service for RAG query responses.

Responsibilities:
  - Accept a pre-built messages list from services/prompt.py (T-37)
  - Stream tokens from gpt-4o-mini via openai_client.chat_complete()
  - Count output tokens as they arrive (tiktoken, cl100k_base)
  - Update the user's daily token quota after the stream completes
  - Propagate circuit breaker / retry errors as-is for the router (T-39)
    to surface as SSE error events

Callers receive an async generator of str token strings. The generator
raises on connection failure (before any tokens are yielded) and propagates
mid-stream errors to the caller if they occur.

Token counting note:
  tiktoken does not tokenise delta strings the same way the API does
  (the API counts BPE tokens; we count on raw delta text). The discrepancy
  is typically <2% and acceptable for quota purposes. We do NOT call the
  API's usage field because it is only populated on the final chunk with
  stream_options={"include_usage": True}, which adds latency.
  TODO (T-44): evaluate switching to stream_options usage field if
  quota accuracy becomes important.
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

import tiktoken
from openai.types.chat import ChatCompletionMessageParam
from typing import cast
from app.utils.openai_client import (
    chat_complete,
    check_and_increment_token_usage,
    CircuitBreakerOpenError,
    DailyQuotaExceededError,
    OpenAIRetryExhaustedError,
)

logger = logging.getLogger(__name__)

# Shared encoder — same family as the embedding model; instantiation is cheap
# after the first call (tiktoken caches the vocab internally).
_encoder = tiktoken.get_encoding("cl100k_base")

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
    # chat_complete(stream=True) returns an async generator — connection is
    # established (with retry) inside _stream_chat before the first yield.
    # Any connection-phase exception (CircuitBreakerOpenError,
    # OpenAIRetryExhaustedError, APIStatusError) propagates here before we
    # enter the loop, so the caller sees a clean raise, not a broken generator.
    token_stream = cast(
        AsyncIterator[str],
        await chat_complete(
            messages=messages,
            stream=True,
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
        ),
    )

    output_tokens = 0

    try:
        async for token in token_stream:
            output_tokens += len(_encoder.encode(token))
            yield token
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
            "LLM stream complete for user %s: %d output tokens.",
            user_id,
            output_tokens,
        )