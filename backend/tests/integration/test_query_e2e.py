import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import patch

from app.models.document import Document, DocumentStatus
from app.models.chunk import Chunk

pytestmark = pytest.mark.integration

@pytest.mark.asyncio
async def test_full_query_pipeline(
    async_client: AsyncClient,
    db: AsyncSession,
    auth_headers: dict,
    verified_user,
    mock_retrieval
):
    """
    Test the full query pipeline:
    Embed -> Retrieve -> Stream
    """
    # 1. Seed a processed document and a chunk
    doc_id = uuid.uuid4()
    doc = Document(
        id=doc_id,
        user_id=verified_user.id,
        filename="test_guide.pdf",
        s3_key=f"{verified_user.id}/{doc_id}/test_guide.pdf",
        file_size_bytes=1000,
        mime_type="application/pdf",
        status=DocumentStatus.READY,
        chunk_count=1
    )
    db.add(doc)
    
    chunk = Chunk(
        id=uuid.uuid4(),
        document_id=doc_id,
        user_id=verified_user.id,
        chunk_index=0,
        text="The main feature of PDFTalk is answering questions based on context.",
        token_count=12,
        embedding=[0.1] * 1536  # fake embedding matching text-embedding-3-small dimension
    )
    db.add(chunk)
    await db.commit()

    from app.services.retrieval import RetrievedChunk
    mock_retrieval.return_value = [
        RetrievedChunk(
            chunk_id=uuid.uuid4(),
            document_id=doc_id,
            chunk_index=0,
            text="The main feature of PDFTalk is answering questions based on context.",
            token_count=12,
            filename="test_guide.pdf",
            distance=0.1
        )
    ]

    # We mock stream_llm_response to simulate OpenAI streaming to avoid network calls during integration
    async def fake_stream_llm(*args, **kwargs):
        yield "The"
        yield " main"
        yield " feature."

    with patch("app.routers.query.stream_llm_response", side_effect=fake_stream_llm):
        
        resp = await async_client.post(
            "/query/ask",
            json={"document_ids": [str(doc_id)], "question": "What is the main feature?"},
            headers=auth_headers
        )
        
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "text/event-stream; charset=utf-8"
        
        # Parse SSE
        events = [line for line in resp.text.split("\n\n") if line.strip()]
        
        assert "data: The" in events[0]
        assert "data:  main" in events[1]
        assert "data:  feature." in events[2]
        
        # Verify custom sources event
        import json
        sources_line = events[3].replace("data: ", "", 1)
        sources_data = json.loads(sources_line)
        assert sources_data["type"] == "sources"
        assert len(sources_data["chunks"]) == 1
        assert sources_data["chunks"][0]["filename"] == "test_guide.pdf"
        assert sources_data["chunks"][0]["chunk_index"] == 0
        assert sources_data["chunks"][0]["document_id"] == str(doc_id)

        assert "data: [DONE]" in events[4]

@pytest.mark.asyncio
async def test_query_document_not_ready(
    async_client: AsyncClient,
    db: AsyncSession,
    auth_headers: dict,
    verified_user
):
    doc_id = uuid.uuid4()
    doc = Document(
        id=doc_id,
        user_id=verified_user.id,
        filename="processing.pdf",
        s3_key=f"{verified_user.id}/{doc_id}/processing.pdf",
        file_size_bytes=1000,
        mime_type="application/pdf",
        status=DocumentStatus.PROCESSING,
        chunk_count=0
    )
    db.add(doc)
    await db.commit()

    resp = await async_client.post(
        "/query/ask",
        json={"document_ids": [str(doc_id)], "question": "Is it ready?"},
        headers=auth_headers
    )
    # T-39: Should raise DocumentNotReadyError -> 409
    assert resp.status_code == 409

@pytest.mark.asyncio
async def test_query_document_not_found(
    async_client: AsyncClient,
    auth_headers: dict
):
    resp = await async_client.post(
        "/query/ask",
        json={"document_ids": [str(uuid.uuid4())], "question": "Are you there?"},
        headers=auth_headers
    )
    # T-39: Should raise DocumentNotFoundError -> 404
    assert resp.status_code == 404

@pytest.mark.asyncio
async def test_query_quota_exceeded(
    async_client: AsyncClient,
    auth_headers: dict
):
    # If the user exceeds 20 queries/min (T-42), rate limiter kicks in.
    # We can either make 21 requests or mock `check_and_increment_query_usage` to raise `DailyQueryQuotaExceededError`.
    from app.utils.openai_client import DailyQueryQuotaExceededError
    with patch("app.routers.query.check_and_increment_query_usage", side_effect=DailyQueryQuotaExceededError):
        resp = await async_client.post(
            "/query/ask",
            json={"document_ids": [str(uuid.uuid4())], "question": "Quota test"},
            headers=auth_headers
        )
        assert resp.status_code == 429
