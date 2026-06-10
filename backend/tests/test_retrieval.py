"""
Unit tests for services/retrieval.py.

Strategy:
  - Mock embed_texts so no OpenAI calls are made.
  - Mock the AsyncSession so no DB is needed.
  - Test: correct SQL params are assembled, results are mapped correctly,
    edge cases (empty result, empty document_ids) are handled.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.retrieval import RetrievedChunk, retrieve_similar_chunks


FAKE_USER_ID = uuid.uuid4()
FAKE_DOC_ID = uuid.uuid4()
FAKE_CHUNK_ID = uuid.uuid4()

# A minimal 3-dim vector — dimensionality doesn't matter for unit tests
FAKE_VECTOR = [0.1, 0.9, 0.0]


def _make_mock_row(
    chunk_id: uuid.UUID = FAKE_CHUNK_ID,
    document_id: uuid.UUID = FAKE_DOC_ID,
    chunk_index: int = 0,
    text: str = "Test chunk text.",
    distance: float = 0.12,
) -> MagicMock:
    row = MagicMock()
    row.id = chunk_id
    row.document_id = document_id
    row.chunk_index = chunk_index
    row.text = text
    row.distance = distance
    return row


@pytest.mark.asyncio
async def test_returns_mapped_dataclasses():
    """Happy path: DB returns one row → mapped to RetrievedChunk correctly."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [_make_mock_row()]
    mock_db.execute.return_value = mock_result

    with (
        patch("app.services.retrieval.embed_texts", return_value=[FAKE_VECTOR]),
        patch("asyncio.get_running_loop") as mock_loop,
    ):
        # run_in_executor should return the embed result directly in tests
        mock_loop.return_value.run_in_executor = AsyncMock(return_value=[FAKE_VECTOR])

        results = await retrieve_similar_chunks(
            user_id=FAKE_USER_ID,
            document_ids=[FAKE_DOC_ID],
            query="What is this about?",
            db=mock_db,
        )

    assert len(results) == 1
    chunk = results[0]
    assert isinstance(chunk, RetrievedChunk)
    assert chunk.chunk_id == FAKE_CHUNK_ID
    assert chunk.document_id == FAKE_DOC_ID
    assert chunk.chunk_index == 0
    assert chunk.text == "Test chunk text."
    assert chunk.distance == pytest.approx(0.12)


@pytest.mark.asyncio
async def test_empty_result_returns_empty_list():
    """DB returns no rows → empty list, no error."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    mock_db.execute.return_value = mock_result

    with patch("asyncio.get_running_loop") as mock_loop:
        mock_loop.return_value.run_in_executor = AsyncMock(return_value=[FAKE_VECTOR])

        results = await retrieve_similar_chunks(
            user_id=FAKE_USER_ID,
            document_ids=[FAKE_DOC_ID],
            query="anything",
            db=mock_db,
        )

    assert results == []


@pytest.mark.asyncio
async def test_empty_document_ids_raises():
    """Passing an empty document_ids list must raise ValueError immediately."""
    mock_db = AsyncMock()

    with pytest.raises(ValueError, match="document_ids must be non-empty"):
        await retrieve_similar_chunks(
            user_id=FAKE_USER_ID,
            document_ids=[],
            query="anything",
            db=mock_db,
        )

    # DB must not be touched
    mock_db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_respects_custom_k():
    """k parameter is forwarded to the SQL LIMIT."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    mock_db.execute.return_value = mock_result

    with patch("asyncio.get_running_loop") as mock_loop:
        mock_loop.return_value.run_in_executor = AsyncMock(return_value=[FAKE_VECTOR])

        await retrieve_similar_chunks(
            user_id=FAKE_USER_ID,
            document_ids=[FAKE_DOC_ID],
            query="anything",
            db=mock_db,
            k=10,
        )

    call_kwargs = mock_db.execute.call_args
    bound_params = call_kwargs[0][1]  # second positional arg is the params dict
    assert bound_params["k"] == 10


@pytest.mark.asyncio
async def test_results_ordered_by_distance():
    """Rows come back in DB order — verify mapping preserves that order."""
    mock_db = AsyncMock()
    rows = [
        _make_mock_row(chunk_index=0, distance=0.05),
        _make_mock_row(chunk_index=1, distance=0.18),
        _make_mock_row(chunk_index=2, distance=0.31),
    ]
    mock_result = MagicMock()
    mock_result.fetchall.return_value = rows
    mock_db.execute.return_value = mock_result

    with patch("asyncio.get_running_loop") as mock_loop:
        mock_loop.return_value.run_in_executor = AsyncMock(return_value=[FAKE_VECTOR])

        results = await retrieve_similar_chunks(
            user_id=FAKE_USER_ID,
            document_ids=[FAKE_DOC_ID],
            query="anything",
            db=mock_db,
        )

    distances = [r.distance for r in results]
    assert distances == sorted(distances)
