"""
services/retrieval.py

Responsible for:
  - Embedding a query string (via embedding service)
  - Running a pgvector cosine similarity search filtered by user_id + document_ids
  - Returning the top-K most similar chunks as typed RetrievedChunk dataclasses

Public surface:
  retrieve_similar_chunks(
      user_id: uuid.UUID,
      document_ids: list[uuid.UUID],
      query: str,
      db: AsyncSession,
      k: int = settings.RETRIEVAL_TOP_K,
  ) -> list[RetrievedChunk]

Design notes:
  - Session is injected by the caller (matches T-35 bulk-insert pattern).
  - embed_texts() is called with asyncio.run() internally — this service is
    intended to be called from the RQ worker (sync context) via a sync wrapper,
    OR from async FastAPI route handlers via await on the async variant.
  - document_ids must be non-empty; caller should validate before calling.
  - Only chunks with non-null embeddings are considered (WHERE embedding IS NOT NULL).
"""

from __future__ import annotations

import structlog
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.utils.openai_client import create_embeddings
from app.core.config import settings

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    text: str
    token_count: int  # needed by prompt builder for budget accounting
    filename: str  # joined from documents.filename — used for citations
    distance: float


# ---------------------------------------------------------------------------
# Public entry point (async — called from FastAPI route handlers)
# ---------------------------------------------------------------------------


async def retrieve_similar_chunks(
    *,
    user_id: uuid.UUID,
    document_ids: list[uuid.UUID],
    query: str,
    db: AsyncSession,
    k: int | None = None,
) -> list[RetrievedChunk]:
    """
    Embed `query` and return the top-K most similar chunks owned by `user_id`
    within the given `document_ids`.

    Args:
        user_id:      Filters chunks to this user only (ownership enforcement).
        document_ids: Non-empty list of document UUIDs to search within.
        query:        Raw question string. Will be embedded internally.
        db:           Injected AsyncSession from the caller.
        k:            Number of results to return. Defaults to settings.RETRIEVAL_TOP_K.

    Returns:
        List of RetrievedChunk, ordered by ascending cosine distance (most
        relevant first). May be shorter than k if fewer matching chunks exist.

    Raises:
        ValueError: If document_ids is empty.
        CircuitBreakerOpenError: Propagated from embed_texts if OpenAI is down.
    """
    if not document_ids:
        raise ValueError("document_ids must be non-empty.")

    effective_k = k if k is not None else settings.RETRIEVAL_TOP_K

    logger.debug(
        "retrieval.start",
        user_id=str(user_id),
        document_count=len(document_ids),
        k=effective_k,
    )

    vectors = await create_embeddings([query])
    query_vector = vectors[0]  # single query → single vector

    rows = await _run_similarity_search(
        user_id=user_id,
        document_ids=document_ids,
        query_vector=query_vector,
        k=effective_k,
        db=db,
    )

    logger.debug(
        "retrieval.complete",
        user_id=str(user_id),
        results_returned=len(rows),
    )

    return rows


# ---------------------------------------------------------------------------
# Sync wrapper (called from RQ worker — sync context)
# ---------------------------------------------------------------------------


def retrieve_similar_chunks_sync(
    *,
    user_id: uuid.UUID,
    document_ids: list[uuid.UUID],
    query: str,
    db: Session,
    k: int | None = None,
) -> list[RetrievedChunk]:
    """
    Sync entry point for use in the RQ worker.
    Executes the async OpenAI embedding call, validates the vector,
    and runs the sync database query.
    """
    import asyncio
    import math

    if not document_ids:
        raise ValueError("document_ids must be non-empty.")

    effective_k = k if k is not None else settings.RETRIEVAL_TOP_K

    # 1. Fetch embeddings asynchronously using asyncio.run
    # Safe because create_embeddings does not use the DB connection
    vectors = asyncio.run(create_embeddings([query]))
    query_vector = vectors[0]

    # HIGH-6: Validate embedding vectors
    if not all(math.isfinite(x) for x in query_vector):
        raise ValueError("Invalid query embedding vector: contains NaN or inf.")

    # 2. Run the synchronous DB query using the sync Session
    vector_literal = "[" + ",".join(str(x) for x in query_vector) + "]"

    result = db.execute(
        text("""
            SELECT
                c.id,
                c.document_id,
                c.chunk_index,
                c.text,
                c.token_count,
                d.filename,
                c.embedding <=> CAST(:query_vec AS vector) AS distance
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE c.user_id   = :user_id
            AND c.document_id = ANY(CAST(:doc_ids AS uuid[]))
            AND c.embedding IS NOT NULL
            ORDER BY distance ASC
            LIMIT :k
        """),
        {
            "query_vec": vector_literal,
            "user_id": str(user_id),
            "doc_ids": [str(d) for d in document_ids],
            "k": effective_k,
        },
    )

    rows = result.fetchall()
    chunks = [
        RetrievedChunk(
            chunk_id=uuid.UUID(str(row.id)),
            document_id=uuid.UUID(str(row.document_id)),
            chunk_index=row.chunk_index,
            text=row.text,
            token_count=row.token_count,
            filename=row.filename,
            distance=float(row.distance),
        )
        for row in rows
    ]

    max_distance = settings.RETRIEVAL_MAX_DISTANCE
    relevant = [c for c in chunks if c.distance <= max_distance]
    return relevant if relevant else chunks


# ---------------------------------------------------------------------------
# SQL execution
# ---------------------------------------------------------------------------


async def _run_similarity_search(
    *,
    user_id: uuid.UUID,
    document_ids: list[uuid.UUID],
    query_vector: list[float],
    k: int,
    db: AsyncSession,
) -> list[RetrievedChunk]:
    """
    Execute the pgvector cosine similarity search.

    Uses the <=> operator (cosine distance). Works correctly because:
      - embed_texts() L2-normalises all vectors (including the query).
      - <=> measures angle between vectors, not magnitude.

    Binds document_ids as a UUID array using PostgreSQL's ARRAY[]::uuid[] cast,
    which asyncpg handles correctly without ORM involvement.
    """
    # Format vector as pgvector literal: '[0.1, 0.2, ...]'
    vector_literal = "[" + ",".join(str(x) for x in query_vector) + "]"

    result = await db.execute(
        text("""
            SELECT
                c.id,
                c.document_id,
                c.chunk_index,
                c.text,
                c.token_count,
                d.filename,
                c.embedding <=> CAST(:query_vec AS vector) AS distance
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE c.user_id   = :user_id
            AND c.document_id = ANY(CAST(:doc_ids AS uuid[]))
            AND c.embedding IS NOT NULL
            ORDER BY distance ASC
            LIMIT :k
        """),
        {
            "query_vec": vector_literal,
            "user_id": str(user_id),
            "doc_ids": [str(d) for d in document_ids],
            "k": k,
        },
    )

    rows = result.fetchall()
    chunks = [
        RetrievedChunk(
            chunk_id=uuid.UUID(str(row.id)),
            document_id=uuid.UUID(str(row.document_id)),
            chunk_index=row.chunk_index,
            text=row.text,
            token_count=row.token_count,
            filename=row.filename,
            distance=float(row.distance),
        )
        for row in rows
    ]

    # Drop off-topic chunks whose cosine distance exceeds the configured ceiling.
    # If *all* chunks are too distant (completely unrelated query) we return the
    # full list anyway — the prompt builder's degenerate-path handler will emit
    # the right hint to the LLM, which will then trigger its graceful Rule 5
    # fallback rather than inventing an answer.
    max_distance = settings.RETRIEVAL_MAX_DISTANCE
    relevant = [c for c in chunks if c.distance <= max_distance]
    return relevant if relevant else chunks
