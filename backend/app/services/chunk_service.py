"""
Chunk persistence service.

Responsibilities:
  - Accept a merged list of chunk data (text + metadata + embedding)
  - Bulk-insert all Chunk rows in a single transaction
  - Update document.chunk_count after insert
  - Verify row count matches input length before committing

Called by the RQ ingest worker after embedding generation.
Never called from a FastAPI route directly — this is a worker-side service.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk


@dataclass
class ChunkData:
    """
    One chunk with its embedding attached.

    The worker zips chunking output + embedding output into this
    structure immediately after the embedding call, with a length
    check, before calling store_chunks().
    """
    chunk_index: int
    text: str
    token_count: int
    embedding: list[float]


class ChunkCountMismatchError(Exception):
    """
    Raised when the DB row count after insert doesn't match the input.

    This should never happen — if it does, something is wrong with the
    DB session or a partial flush occurred. The worker should treat this
    as a hard failure and mark the document FAILED.
    """


async def store_chunks(
    *,
    document_id: uuid.UUID,
    user_id: uuid.UUID,
    chunks: list[ChunkData],
    db: AsyncSession,
) -> int:
    """
    Bulk-insert all chunks for a document in a single transaction.

    The caller (worker) is responsible for:
      - Passing chunks that already have embeddings attached
      - Wrapping this call in the worker's try/except that sets FAILED on error
      - Committing or rolling back the session

    Args:
        document_id: UUID of the parent Document row.
        user_id:     UUID of the owning user (denormalised onto each chunk row).
        chunks:      Merged list of ChunkData — text, metadata, and embedding together.
        db:          Active async SQLAlchemy session (worker manages the session lifecycle).

    Returns:
        Number of chunks inserted.

    Raises:
        ChunkCountMismatchError: If the verified row count doesn't match input length.
        SQLAlchemyError:         Propagated — let the worker catch and mark FAILED.
    """
    if not chunks:
        return 0

    # Build ORM objects. SQLAlchemy will batch these into an efficient
    # INSERT when session.flush() is called.
    chunk_objects = [
        Chunk(
            document_id=document_id,
            user_id=user_id,
            chunk_index=c.chunk_index,
            text=c.text,
            token_count=c.token_count,
            embedding=c.embedding,
        )
        for c in chunks
    ]

    db.add_all(chunk_objects)

    # Flush to send the INSERT to Postgres without committing.
    # This lets us verify the row count within the same transaction
    # before handing control back to the worker for the final commit.
    await db.flush()

    # Verify — count rows in DB for this document.
    # If this doesn't match, something went wrong with the bulk insert.
    result = await db.execute(
        select(func.count()).select_from(Chunk).where(Chunk.document_id == document_id)
    )
    actual_count = result.scalar_one()

    if actual_count != len(chunks):
        # Roll back is handled by the worker's exception handler.
        raise ChunkCountMismatchError(
            f"Expected {len(chunks)} chunks for document {document_id}, "
            f"found {actual_count} after flush."
        )

    # Don't update document.chunk_count here — the worker does it alongside
    # setting status = READY in one atomic commit. This keeps store_chunks
    # free of Document FK dependencies and testable without a Document row.
    return actual_count
