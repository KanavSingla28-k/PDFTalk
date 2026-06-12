import os
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.document import Document, DocumentStatus
from app.models.chunk import Chunk
from app.workers.ingest import _run, _fail
from app.services.chunking import ChunkData

pytestmark = pytest.mark.integration

@pytest.mark.asyncio
async def test_full_ingestion_pipeline(
    async_client: AsyncClient,
    db: AsyncSession,
    auth_headers: dict,
    verified_user,
    s3_mock,
    mock_ingest_enqueue,
):
    """
    Test the complete ingestion pipeline:
    1. Upload PDF
    2. Simulate RQ worker by calling run_ingest synchronously
    3. Verify status -> READY
    """
    # 1. Upload a PDF
    # We need a sample PDF bytes
    sample_pdf_bytes = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
    
    files = {"file": ("test.pdf", sample_pdf_bytes, "application/pdf")}
    resp = await async_client.post("/documents/upload", files=files, headers=auth_headers)
    assert resp.status_code == 202
    
    doc_id = resp.json()["document_id"]
    
    # Verify it's in the DB as PENDING
    result = await db.execute(select(Document).where(Document.id == uuid.UUID(doc_id)))
    doc = result.scalar_one()
    assert doc.status == DocumentStatus.PENDING

    # 2. Simulate Worker (Synchronously)
    # The `run_ingest` will read from S3 (which is mocked by moto)
    # It will extract text (using real PyMuPDF, which might fail on our fake bytes).
    # Wait, PyMuPDF needs a valid PDF. We should use tests/sample.pdf if available.
    pdf_path = "tests/sample.pdf"
    if os.path.exists(pdf_path):
        with open(pdf_path, "rb") as f:
            sample_pdf_bytes = f.read()
    else:
        # We must mock extract_text if a real PDF is not available, because PyMuPDF will fail on fake bytes.
        pass

    # Actually, we should just mock extract_text and embed_texts to make this a fast and reliable test
    # instead of hitting PyMuPDF and OpenAI, since we're testing the integration flow of the worker & db.
    from unittest.mock import patch, AsyncMock
    with patch("app.workers.ingest.extract_text", return_value="This is some extracted text from the PDF.") as mock_extract, \
         patch("app.workers.ingest.chunk_text", return_value=[ChunkData(chunk_index=0, text="This is some extracted text from the PDF.", token_count=10)]) as mock_chunk, \
         patch("app.workers.ingest.embed_texts", return_value=[[0.1]*1536]) as mock_embed, \
         patch("app.workers.ingest.check_and_increment_token_usage", new_callable=AsyncMock) as mock_check, \
         patch("app.workers.ingest._run_async") as mock_run_async:
        
        # Run worker logic via run_sync to share the in-memory test DB session
        await db.run_sync(_run, uuid.UUID(doc_id))

    # 3. Verify Document is READY
    await db.refresh(doc)
    assert doc.status == DocumentStatus.READY
    assert doc.chunk_count is not None
    assert doc.chunk_count > 0

    # Verify chunks are saved
    chunk_result = await db.execute(select(Chunk).where(Chunk.document_id == doc.id))
    chunks = chunk_result.scalars().all()
    assert len(chunks) == doc.chunk_count

@pytest.mark.asyncio
async def test_ingestion_quota_exceeded(
    async_client: AsyncClient,
    db: AsyncSession,
    auth_headers: dict,
    verified_user,
    s3_mock
):
    """Test what happens when the uploaded file or chunks exceed token quota."""
    sample_pdf_bytes = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
    files = {"file": ("test.pdf", sample_pdf_bytes, "application/pdf")}
    resp = await async_client.post("/documents/upload", files=files, headers=auth_headers)
    assert resp.status_code == 202
    doc_id = resp.json()["document_id"]

    from unittest.mock import patch
    
    # Return massive text that exceeds 500,000 tokens
    # Or just mock `_check_token_budget` to raise ValueError
    with patch("app.workers.ingest.extract_text", return_value="Text."), \
         patch("app.workers.ingest._check_token_budget", side_effect=ValueError("Quota exceeded")):
        
        with pytest.raises(ValueError, match="Quota exceeded"):
            try:
                await db.run_sync(_run, uuid.UUID(doc_id))
            except Exception as exc:
                await db.run_sync(_fail, uuid.UUID(doc_id), exc)
                raise

    # Verify Document is FAILED
    result = await db.execute(select(Document).where(Document.id == uuid.UUID(doc_id)))
    doc = result.scalar_one()
    assert doc.status == DocumentStatus.FAILED
    assert doc.error_message is not None
    assert "Quota exceeded" in doc.error_message

@pytest.mark.asyncio
async def test_upload_missing_file(
    async_client: AsyncClient,
    auth_headers: dict
):
    resp = await async_client.post("/documents/upload", files={}, headers=auth_headers)
    assert resp.status_code == 422
