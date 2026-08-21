"""
services/llm.py  (T-38)

Streaming LLM service for RAG query responses.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import structlog
from openai.types.chat import ChatCompletionMessageParam

from app.utils.metrics import openai_tokens_used_total
from app.utils.openai_client import (
    DailyQuotaExceededError,
    _stream_chat_with_usage,
    check_and_increment_token_usage,
)

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
        # NOTE: This block runs on generator shutdown — i.e. AFTER the last
        # token has already been yielded back to the caller. By this point
        # the response has already been fully generated and (in the normal
        # case) already rendered to the user. Anything raised from here does
        # NOT propagate as a "the stream failed" exception in the
        # conventional sense — it propagates out of the caller's
        # `token_stream.__anext__()` call, which the SSE generator in
        # query.py cannot distinguish from a genuine mid-stream failure. It
        # gets caught by the generic `except Exception` there and reported
        # to the user as "An unexpected error occurred", even though their
        # answer already streamed in correctly.
        #
        # This is accounting that happens to occur after the work is done,
        # not a gate on the work itself — so it must never raise. Real quota
        # *enforcement* (blocking the request) belongs upstream, before the
        # OpenAI call is made (tracked separately as B-04). By the time we
        # get here, the tokens are already spent and the user already has
        # their answer; raising can only corrupt a successful response, it
        # can't undo the cost or the delivery.
        if output_tokens > 0:
            # Record token consumption regardless of quota outcome so the
            # counter stays accurate even when the user goes over their limit.
            openai_tokens_used_total.labels(kind="completion").inc(output_tokens)

            try:
                await check_and_increment_token_usage(user_id, output_tokens)
            except DailyQuotaExceededError:
                # Log only — do NOT re-raise. The response already completed
                # successfully; this just means the user is now over quota
                # for *next* time. Re-raising here would surface a fake
                # "stream error" on a request that actually succeeded.
                logger.warning(
                    "llm.quota_exceeded_mid_stream",
                    user_id=user_id,
                    output_tokens=output_tokens,
                )
            except Exception:
                # Never let post-hoc bookkeeping failures masquerade as
                # stream failures. Log and move on.
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
