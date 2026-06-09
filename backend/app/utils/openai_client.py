"""
utils/openai_client.py

Single entry point for all OpenAI API calls.

Responsibilities:
  - Retry on RateLimitError (3 attempts, exponential backoff)
  - Circuit breaker on 5xx errors (trips after 3 consecutive failures,
    stays open for 60 s, shared across API + worker via Redis)
  - Per-user daily token quota enforced before any embedding call
  - L2 normalisation is NOT done here — that belongs in embedding.py (T-33)

Exceptions exported from this module (import from here, not openai.*):
  - CircuitBreakerOpenError   — OpenAI unreachable; caller should 503
  - DailyQuotaExceededError   — user has exhausted their daily token budget
  - OpenAIRetryExhaustedError — rate limit persisted across all retries
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import AsyncIterator

from openai import AsyncOpenAI, APIStatusError, RateLimitError
from openai.types.chat import ChatCompletionMessageParam

from app.core.config import settings
from app.utils import redis_client as rc

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Typed exceptions
# ---------------------------------------------------------------------------

class CircuitBreakerOpenError(Exception):
    """Raised when the circuit breaker is open (OpenAI had repeated 5xx errors)."""


class DailyQuotaExceededError(Exception):
    """Raised when a user has consumed their daily token allowance."""


class OpenAIRetryExhaustedError(Exception):
    """Raised when all retry attempts on RateLimitError are consumed."""


# ---------------------------------------------------------------------------
# Client singleton
# ---------------------------------------------------------------------------

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            # Conservative timeout: connect 5 s, read 120 s (streaming needs headroom)
            timeout=120.0,
        )
    return _client


# ---------------------------------------------------------------------------
# Circuit breaker helpers
# ---------------------------------------------------------------------------

_CB_FAILURE_THRESHOLD = 3   # consecutive 5xx before tripping
_CB_OPEN_SECONDS = 60       # how long the circuit stays open
_CB_FAILURE_WINDOW = 120    # TTL on the failure counter (resets if OpenAI is quiet)


async def _is_circuit_open() -> bool:
    """Return True if the circuit breaker is currently open."""
    open_until_str = await rc.get(rc.key_circuit_breaker_open_until())
    if open_until_str is None:
        return False
    return time.time() < float(open_until_str)


async def _record_success() -> None:
    """Reset the consecutive failure counter on any successful call."""
    await rc.delete(rc.key_circuit_breaker_failures())


async def _record_failure() -> None:
    """
    Increment the consecutive failure counter.
    If the threshold is reached, open the circuit for _CB_OPEN_SECONDS.
    """
    failures = await rc.increment_counter(
        rc.key_circuit_breaker_failures(),
        ttl_seconds=_CB_FAILURE_WINDOW,
    )
    logger.warning("OpenAI 5xx recorded. Consecutive failures: %d", failures)

    if failures >= _CB_FAILURE_THRESHOLD:
        open_until = time.time() + _CB_OPEN_SECONDS
        await rc.set_with_ttl(
            rc.key_circuit_breaker_open_until(),
            str(open_until),
            ttl_seconds=_CB_OPEN_SECONDS + 5,   # slight buffer
        )
        logger.error(
            "Circuit breaker OPEN — OpenAI calls blocked for %d s", _CB_OPEN_SECONDS
        )


# ---------------------------------------------------------------------------
# Quota helpers
# ---------------------------------------------------------------------------

async def check_and_increment_token_usage(user_id: str, tokens: int) -> None:
    """
    Atomically increment the user's daily token counter and raise
    DailyQuotaExceededError if the result exceeds MAX_DAILY_TOKENS_PER_USER.

    The quota key has a 25-hour TTL to handle timezone edge cases cleanly
    (consistent with the pattern in T-32 spec).
    """
    key = rc.key_daily_token_quota(user_id)
    # 25 h TTL — covers midnight rollovers across any reasonable offset
    new_total = await rc.increment_counter_by(key, tokens, ttl_seconds=90_000)

    if new_total > settings.MAX_DAILY_TOKENS_PER_USER:
        logger.warning(
            "Daily token quota exceeded for user %s: %d / %d",
            user_id,
            new_total,
            settings.MAX_DAILY_TOKENS_PER_USER,
        )
        raise DailyQuotaExceededError(
            f"Daily token limit of {settings.MAX_DAILY_TOKENS_PER_USER:,} reached."
        )

class DailyQueryQuotaExceededError(Exception):
    """Raised when a user has consumed their daily query allowance."""


async def check_and_increment_query_usage(user_id: str) -> None:
    """
    Atomically increment the user's daily query counter and raise
    DailyQueryQuotaExceededError if the result exceeds MAX_DAILY_QUERIES_PER_USER.

    Each call to /query/ask counts as 1 query regardless of token cost.
    TTL mirrors the token quota: 25 h to handle midnight rollovers.
    """
    key = rc.key_daily_query_quota(user_id)
    new_total = await rc.increment_counter_by(key, 1, ttl_seconds=90_000)

    if new_total > settings.MAX_DAILY_QUERIES_PER_USER:
        logger.warning(
            "Daily query quota exceeded for user %s: %d / %d",
            user_id,
            new_total,
            settings.MAX_DAILY_QUERIES_PER_USER,
        )
        raise DailyQueryQuotaExceededError(
            f"Daily query limit of {settings.MAX_DAILY_QUERIES_PER_USER:,} reached."
        )

# ---------------------------------------------------------------------------
# Internal guarded call wrapper
# ---------------------------------------------------------------------------

_RETRY_ATTEMPTS = 3         # total attempts (1 initial + 2 retries)
_RETRY_BASE_DELAY = 5.0     # seconds; doubles each retry: 5 s → 10 s


async def _guarded_call(coro_factory):
    """
    Execute an async coroutine with:
      1. Circuit breaker pre-check (raises CircuitBreakerOpenError if open)
      2. Retry loop on RateLimitError (up to _RETRY_ATTEMPTS total)
      3. Circuit breaker failure recording on 5xx APIStatusError
      4. Circuit breaker success reset on clean response

    coro_factory: callable that returns a fresh coroutine each time it's called.
    Coroutines can't be re-awaited, so we accept a factory.
    """
    if await _is_circuit_open():
        raise CircuitBreakerOpenError(
            "OpenAI circuit breaker is open. Try again shortly."
        )

    last_exc: Exception | None = None

    for attempt in range(1, _RETRY_ATTEMPTS + 1):   # 1, 2, 3
        try:
            result = await coro_factory()
            await _record_success()
            return result

        except RateLimitError as exc:
            last_exc = exc
            if attempt == _RETRY_ATTEMPTS:
                break
            delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))   # 5 s → 10 s
            logger.warning(
                "OpenAI RateLimitError on attempt %d/%d. Retrying in %.0f s.",
                attempt,
                _RETRY_ATTEMPTS,
                delay,
            )
            await asyncio.sleep(delay)

        except APIStatusError as exc:
            if exc.status_code >= 500:
                await _record_failure()
                # Re-check: the failure we just recorded may have tripped the breaker
                if await _is_circuit_open():
                    raise CircuitBreakerOpenError(
                        "OpenAI circuit breaker tripped after repeated 5xx errors."
                    ) from exc
            raise   # Non-5xx API errors (4xx) propagate immediately

    raise OpenAIRetryExhaustedError(
        f"OpenAI rate limit persisted after {_RETRY_ATTEMPTS} attempts."
    ) from last_exc


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def create_embeddings(texts: list[str]) -> list[list[float]]:
    """
    Embed a list of strings using text-embedding-3-small.
    Returns raw vectors — L2 normalisation is done in services/embedding.py (T-33).

    Does NOT check or update the token quota here — callers (the ingestion
    worker) do that before calling this function, since they have the token
    count from tiktoken already.
    """
    def _factory():
        return get_client().embeddings.create(
            model="text-embedding-3-small",
            input=texts,
        )

    response = await _guarded_call(_factory)
    # Sort by index to guarantee order matches input list
    return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]


async def chat_complete(
    messages: list[ChatCompletionMessageParam],
    *,
    stream: bool = False,
    model: str = "gpt-4o-mini",
    max_tokens: int = 1024,
) -> str | AsyncIterator[str]:
    """
    Call the chat completions endpoint.

    stream=False  → awaits the full response and returns the content string.
    stream=True   → returns an async generator yielding token strings.
                    The circuit breaker + retry wrap only the initial
                    connection; mid-stream errors propagate to the caller.
    """
    if stream:
        return _stream_chat(messages, model=model, max_tokens=max_tokens)

    def _factory():
        return get_client().chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            stream=False,
        )

    response = await _guarded_call(_factory)
    content = response.choices[0].message.content or ""
    return content


async def _stream_chat(
    messages: list[ChatCompletionMessageParam],
    *,
    model: str,
    max_tokens: int,
) -> AsyncIterator[str]:
    """
    Internal async generator for streaming chat.

    Retries the *connection* up to _RETRY_ATTEMPTS total on RateLimitError
    with exponential backoff (5 s → 10 s). The circuit breaker guards the
    connection phase. Mid-stream errors propagate directly to the caller
    (retrying mid-stream is not safe).
    """
    if await _is_circuit_open():
        raise CircuitBreakerOpenError(
            "OpenAI circuit breaker is open. Try again shortly."
        )

    last_exc: Exception | None = None
    stream = None

    for attempt in range(1, _RETRY_ATTEMPTS + 1):   # 1, 2, 3
        try:
            stream = await get_client().chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                stream=True,
            )
            await _record_success()
            break   # connection established — exit retry loop

        except RateLimitError as exc:
            last_exc = exc
            if attempt == _RETRY_ATTEMPTS:
                raise OpenAIRetryExhaustedError(
                    f"OpenAI rate limit persisted after {_RETRY_ATTEMPTS} attempts on stream connection."
                ) from exc
            delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))   # 5 s → 10 s
            logger.warning(
                "OpenAI RateLimitError on stream attempt %d/%d. Retrying in %.0f s.",
                attempt,
                _RETRY_ATTEMPTS,
                delay,
            )
            await asyncio.sleep(delay)

        except APIStatusError as exc:
            if exc.status_code >= 500:
                await _record_failure()
            raise   # 5xx and 4xx both propagate immediately (no retry)

    # Stream connection established — mid-stream errors are not retried
    if stream is None:
        raise OpenAIRetryExhaustedError(
            f"Failed to establish OpenAI stream after {_RETRY_ATTEMPTS} attempts."
        )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


async def _stream_chat_with_usage(
    messages: list[ChatCompletionMessageParam],
    *,
    model: str,
    max_tokens: int,
) -> AsyncIterator[tuple[str | None, object | None]]:
    """
    Streaming chat generator that includes API-reported token usage.

    Yields (token_string, None) for each content delta, then on the final
    usage-only chunk yields (None, chunk.usage) so the caller can record
    accurate token counts from the API instead of a tiktoken estimate.

    stream_options={"include_usage": True} causes OpenAI to append a final
    chunk with choices=[] and usage populated. Content chunks have usage=None.
    """
    if await _is_circuit_open():
        raise CircuitBreakerOpenError(
            "OpenAI circuit breaker is open. Try again shortly."
        )

    last_exc: Exception | None = None
    stream = None

    for attempt in range(1, _RETRY_ATTEMPTS + 1):   # 1, 2, 3
        try:
            stream = await get_client().chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                stream=True,
                stream_options={"include_usage": True},
            )
            await _record_success()
            break   # connection established — exit retry loop

        except RateLimitError as exc:
            last_exc = exc
            if attempt == _RETRY_ATTEMPTS:
                raise OpenAIRetryExhaustedError(
                    f"OpenAI rate limit persisted after {_RETRY_ATTEMPTS} attempts on stream connection."
                ) from exc
            delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))   # 5 s → 10 s
            logger.warning(
                "OpenAI RateLimitError on stream attempt %d/%d. Retrying in %.0f s.",
                attempt,
                _RETRY_ATTEMPTS,
                delay,
            )
            await asyncio.sleep(delay)

        except APIStatusError as exc:
            if exc.status_code >= 500:
                await _record_failure()
            raise   # 5xx and 4xx both propagate immediately (no retry)

    if stream is None:
        raise OpenAIRetryExhaustedError(
            f"Failed to establish OpenAI stream after {_RETRY_ATTEMPTS} attempts."
        )

    async for chunk in stream:
        # Final usage chunk: choices is empty, usage is populated.
        if not chunk.choices:
            yield None, chunk.usage
            continue
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta, None