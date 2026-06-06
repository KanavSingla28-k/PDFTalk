import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.chunk_service import ChunkData, ChunkCountMismatchError, store_chunks


def make_chunks(n: int) -> list[ChunkData]:
    return [
        ChunkData(
            chunk_index=i,
            text=f"chunk text {i}",
            token_count=50,
            embedding=[0.1] * 1536,
        )
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_store_chunks_returns_count(db: AsyncSession):
    """Happy path — inserted count matches input."""
    result = await store_chunks(
        document_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        chunks=make_chunks(3),
        db=db,
    )
    assert result == 3


@pytest.mark.asyncio
async def test_store_chunks_empty_input(db: AsyncSession):
    """Empty chunk list returns 0 without touching the DB."""
    result = await store_chunks(
        document_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        chunks=[],
        db=db,
    )
    assert result == 0


@pytest.mark.asyncio
async def test_store_chunks_mismatch_raises(db: AsyncSession):
    """
    Patch db.execute so the COUNT query returns a wrong number.
    Verifies ChunkCountMismatchError is raised before commit.
    """
    original_execute = db.execute

    call_count = 0

    async def fake_execute(stmt, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        # First execute call in store_chunks is the COUNT query.
        # Return a fake result that reports 1 instead of 3.
        if call_count == 1:
            mock_result = MagicMock()
            mock_result.scalar_one.return_value = 1  # wrong — should be 3
            return mock_result
        return await original_execute(stmt, *args, **kwargs)

    db.execute = fake_execute

    with pytest.raises(ChunkCountMismatchError):
        await store_chunks(
            document_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            chunks=make_chunks(3),
            db=db,
        )