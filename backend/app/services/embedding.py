"""
services/embedding.py

Responsible for:
  - Batching texts into groups of 100 before calling the OpenAI API
  - L2-normalising each returned vector (stdlib math, no numpy)
  - Bridging the async OpenAI client into the sync RQ worker via asyncio.run()

Public surface:
  embed_texts(texts: list[str]) -> list[list[float]]

The caller (workers/ingest.py) is responsible for:
  - Checking the per-user daily token quota BEFORE calling embed_texts()
  - Verifying that len(embeddings) == len(texts) after the call
"""

from __future__ import annotations

import asyncio
import structlog
import math
from typing import TypeVar

from app.utils.openai_client import create_embeddings

logger = structlog.get_logger(__name__)

_BATCH_SIZE = 100  # OpenAI recommends <= 2048 inputs, 100 is a safe conservative default


# ---------------------------------------------------------------------------
# Public sync entry point (called from the RQ worker — sync context)
# ---------------------------------------------------------------------------

def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Embed a list of strings and return L2-normalised vectors.

    - Batches internally (groups of _BATCH_SIZE) to avoid OpenAI request limits.
    - Vectors are L2-normalised so cosine similarity == dot product, which is
      required for pgvector's <=> operator to rank correctly.
    - Uses asyncio.run() to call the async OpenAI client from the sync worker.
      Do NOT call this from an already-running event loop (i.e. async tests
      should mock this function, not call it directly).

    Args:
        texts: Non-empty list of strings to embed. Empty strings are allowed
               by the API but will produce a near-zero vector — callers should
               filter them out upstream (chunking service already does this).

    Returns:
        List of L2-normalised float vectors, same length and order as `texts`.

    Raises:
        CircuitBreakerOpenError: OpenAI is unreachable (propagated from openai_client).
        OpenAIRetryExhaustedError: Rate limit persisted across all retries.
        ValueError: If the API returns a different number of vectors than inputs.
    """
    if not texts:
        return []

    return asyncio.run(_embed_texts_async(texts))


# ---------------------------------------------------------------------------
# Async implementation
# ---------------------------------------------------------------------------

async def _embed_texts_async(texts: list[str]) -> list[list[float]]:
    """
    Async core — batches texts, calls create_embeddings(), normalises results.
    Called exclusively via asyncio.run() from embed_texts().
    """
    batches = _make_batches(texts, _BATCH_SIZE)
    raw_vectors: list[list[float]] = []

    batch_results = await asyncio.gather(
        *[create_embeddings(batch) for batch in batches],
        return_exceptions=False,
    )

    for batch_index, (batch, batch_vectors) in enumerate(zip(batches, batch_results)):
        if len(batch_vectors) != len(batch):
            raise ValueError(
                f"Batch {batch_index}: expected {len(batch)} vectors, "
                f"got {len(batch_vectors)} from OpenAI."
            )
        raw_vectors.extend(batch_vectors)

    # Normalise all vectors — done after all batches to keep the hot path simple
    return [_l2_normalize(v) for v in raw_vectors]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

T = TypeVar("T")

def _make_batches(items: list[T], size: int) -> list[list[T]]:
    """Split a list into consecutive sublists of at most `size` elements."""
    return [items[i : i + size] for i in range(0, len(items), size)]


def _l2_normalize(vector: list[float]) -> list[float]:
    """
    Return the L2-normalised form of `vector`.

    L2 norm = sqrt(sum of squares). Divides each component by the norm so the
    resulting vector has unit length (magnitude == 1.0).

    If the vector is all zeros (degenerate case from a blank input), returns
    it unchanged to avoid division by zero — pgvector will store it but it
    will never rank highly in similarity searches.
    """
    norm = math.sqrt(sum(x * x for x in vector))
    if norm == 0.0:
        logger.warning("embedding.zero_vector", note="L2 norm is 0 — vector left unnormalised")
        return vector
    return [x / norm for x in vector]
