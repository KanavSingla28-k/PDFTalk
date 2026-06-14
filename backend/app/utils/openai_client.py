"""
utils/openai_client.py

Single entry point for all OpenAI API calls.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import AsyncIterator

from openai import AsyncOpenAI, APIStatusError, RateLimitError
from openai.types.chat import ChatCompletionMessageParam
from openai.types.completion_usage import CompletionUsage

from app.core.config import settings
from app.utils import redis_client as rc
from app.utils.metrics import openai_errors_total, daily_quota_breaches_total

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


class DailyQueryQuotaExceededError(Exception):
    """Raised when a user has consumed their daily query allowance."""


# ---------------------------------------------------------------------------
# Client singleton
# ---------------------------------------------------------------------------

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            timeout=120.0,
        )
    return _client


# ---------------------------------------------------------------------------
# Circuit breaker helpers
# ---------------------------------------------------------------------------

_CB_FAILURE_THRESHOLD = 3
_CB_OPEN_SECONDS = 60
_CB_FAILURE_WINDOW = 120


async def _is_circuit_open() -> bool:
    open_until_str = await rc.get(rc.key_circuit_breaker_open_until())
    if open_until_str is None:
        return False
    return time.time() < float(open_until_str)


async def _record_success() -> None:
    await rc.delete(rc.key_circuit_breaker_failures())


async def _record_failure() -> None:
    failures = await rc.increment_counter(
        rc.key_circuit_breaker_failures(),
        ttl_seconds=_CB_FAILURE_WINDOW,
    )
    logger.warning("OpenAI 5xx recorded. Consecutive failures: %d", failures)
    openai_errors_total.labels(error_type="server_error").inc()

    if failures >= _CB_FAILURE_THRESHOLD:
        open_until = time.time() + _CB_OPEN_SECONDS
        await rc.set_with_ttl(
            rc.key_circuit_breaker_open_until(),
            str(open_until),
            ttl_seconds=_CB_OPEN_SECONDS + 5,
        )
        logger.error(
            "Circuit breaker OPEN — OpenAI calls blocked for %d s", _CB_OPEN_SECONDS
        )


# ---------------------------------------------------------------------------
# Quota helpers
# ---------------------------------------------------------------------------

async def check_and_increment_token_usage(user_id: str, tokens: int) -> None:
    key = rc.key_daily_token_quota(user_id)
    new_total = await rc.increment_counter_by(key, tokens, ttl_seconds=90_000)

    if new_total > settings.MAX_DAILY_TOKENS_PER_USER:
        logger.warning(
            "Daily token quota exceeded for user %s: %d / %d",
            user_id,
            new_total,
            settings.MAX_DAILY_TOKENS_PER_USER,
        )
        daily_quota_breaches_total.inc()
        raise DailyQuotaExceededError(
            f"Daily token limit of {settings.MAX_DAILY_TOKENS_PER_USER:,} reached."
        )


async def check_and_increment_query_usage(user_id: str) -> None:
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

_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY = 5.0


async def _guarded_call(coro_factory):
    if await _is_circuit_open():
        raise CircuitBreakerOpenError(
            "OpenAI circuit breaker is open. Try again shortly."
        )

    last_exc: Exception | None = None

    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            result = await coro_factory()
            await _record_success()
            return result

        except RateLimitError as exc:
            last_exc = exc
            openai_errors_total.labels(error_type="rate_limit").inc()
            if attempt == _RETRY_ATTEMPTS:
                break
            delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
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
                if await _is_circuit_open():
                    raise CircuitBreakerOpenError(
                        "OpenAI circuit breaker tripped after repeated 5xx errors."
                    ) from exc
            raise

    raise OpenAIRetryExhaustedError(
        f"OpenAI rate limit persisted after {_RETRY_ATTEMPTS} attempts."
    ) from last_exc


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def create_embeddings(texts: list[str]) -> list[list[float]]:
    def _factory():
        return get_client().embeddings.create(
            model="text-embedding-3-small",
            input=texts,
        )

    response = await _guarded_call(_factory)
    return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]


async def chat_complete(
    messages: list[ChatCompletionMessageParam],
    *,
    stream: bool = False,
    model: str = "gpt-4o-mini",
    max_tokens: int = 1024,
) -> str | AsyncIterator[str]:
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
    if await _is_circuit_open():
        raise CircuitBreakerOpenError(
            "OpenAI circuit breaker is open. Try again shortly."
        )

    last_exc: Exception | None = None
    stream = None

    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            stream = await get_client().chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                stream=True,
            )
            await _record_success()
            break

        except RateLimitError as exc:
            last_exc = exc
            openai_errors_total.labels(error_type="rate_limit").inc()
            if attempt == _RETRY_ATTEMPTS:
                raise OpenAIRetryExhaustedError(
                    f"OpenAI rate limit persisted after {_RETRY_ATTEMPTS} attempts on stream connection."
                ) from exc
            delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
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
            raise

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
) -> AsyncIterator[tuple[str | None, CompletionUsage | None]]:
    if await _is_circuit_open():
        raise CircuitBreakerOpenError(
            "OpenAI circuit breaker is open. Try again shortly."
        )

    last_exc: Exception | None = None
    stream = None

    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            stream = await get_client().chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                stream=True,
                stream_options={"include_usage": True},
            )
            await _record_success()
            break

        except RateLimitError as exc:
            last_exc = exc
            openai_errors_total.labels(error_type="rate_limit").inc()
            if attempt == _RETRY_ATTEMPTS:
                raise OpenAIRetryExhaustedError(
                    f"OpenAI rate limit persisted after {_RETRY_ATTEMPTS} attempts on stream connection."
                ) from exc
            delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
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
            raise

    if stream is None:
        raise OpenAIRetryExhaustedError(
            f"Failed to establish OpenAI stream after {_RETRY_ATTEMPTS} attempts."
        )

    async for chunk in stream:
        if not chunk.choices:
            yield None, chunk.usage
            continue
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta, None
