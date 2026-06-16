"""
services/llm.py  (T-38)

Streaming LLM service for RAG query responses.
"""

from __future__ import annotations

import structlog
from typing import AsyncIterator

from openai.types.chat import ChatCompletionMessageParam
from app.utils.openai_client import (
    _stream_chat_with_usage,
    check_and_increment_token_usage,
    DailyQuotaExceededError,
)
from app.utils.metrics import openai_tokens_used_total

logger = structlog.get_logger(__name__)

_MODEL = "gpt-4o-mini"
_MAX_TOKENS = 1024


async def stream_llm_response(
    messages: list[ChatCompletionMessageParam],
    user_id: str,
) -> AsyncIterator[str]:
    """
    Async generator that streams token strings from gpt-4o-mini.
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
                output_tokens = usage.completion_tokens or 0
    finally:
        if output_tokens > 0:
            # Record token consumption before quota check so the counter
            # is accurate even when the user goes over their limit.
            openai_tokens_used_total.labels(kind="completion").inc(output_tokens)

            try:
                await check_and_increment_token_usage(user_id, output_tokens)
            except DailyQuotaExceededError:
                logger.warning(
                    "llm.quota_exceeded_mid_stream",
                    user_id=user_id,
                    output_tokens=output_tokens,
                )
                raise
            except Exception:
                logger.exception(
                    "llm.token_recording_failed",
                    output_tokens=output_tokens,
                    user_id=user_id,
                )

        logger.debug(
            "llm.stream_complete",
            user_id=user_id,
            output_tokens=output_tokens,
        )
