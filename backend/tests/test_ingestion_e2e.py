# tests/test_ingestion_e2e.py
"""
T-36 — End-to-end ingestion integration test.

Requires:
  - pdftalk-postgres Docker container running on localhost:5433
  - OPENAI_API_KEY set in .env.local (loaded by root conftest.py)
  - tests/fixtures/sample.pdf present

Run with:
  pytest -m integration tests/integration/test_ingestion_e2e.py -v

Skip during normal unit test runs:
  pytest -m "not integration"
"""
import io
import os
import uuid
import pytest
import boto3
from moto import mock_aws
from sqlalchemy import text

from app.models.document import Document, DocumentStatus
from app.models.chunk import Chunk

# ---------------------------------------------------------------------------
# Pull in the real-PG fixtures from the integration conftest
# ---------------------------------------------------------------------------
pytest_plugins = ["tests.conftest_integration"]

# ---------------------------------------------------------------------------
# Locate sample.pdf relative to this test file (common pattern)
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAMPLE_PDF_PATH = os.path.join(BASE_DIR, "sample.pdf")


# ---------------------------------------------------------------------------
# S3 mock fixture (moto) — we don't need real S3 for this test
# ---------------------------------------------------------------------------
@pytest.fixture()
def mock_s3(monkeypatch):
    with mock_aws():
        s3 = boto3.client("s3", region_name="ap-south-1")
        bucket = "pdftalk-documents"

        s3.create_bucket(
            Bucket=bucket,
            CreateBucketConfiguration={"LocationConstraint": "ap-south-1"},
        )

        # ADD THIS
        import app.utils.s3_client as s3_module

        s3_module.s3_client._client = s3
        s3_module.s3_client.bucket = bucket

        with open(SAMPLE_PDF_PATH, "rb") as f:
            pdf_bytes = f.read()

        yield s3, bucket, pdf_bytes

@pytest.fixture(autouse=True)
def mock_embeddings(monkeypatch):
    def fake_embed_texts(texts):
        return [[0.001] * 1536 for _ in texts]

    monkeypatch.setattr(
        "app.workers.ingest.embed_texts",
        fake_embed_texts,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_user(db) -> uuid.UUID:
    """Insert a minimal user row directly — we're not testing auth here."""
    user_id = uuid.uuid4()
    db.execute(
        text("""
            INSERT INTO users (id, email, email_lower, password_hash, is_verified, is_active)
            VALUES (:id, :email, :email_lower, 'irrelevant', TRUE, TRUE)
        """),
        {
            "id": str(user_id),
            "email": f"test-{user_id}@example.com",
            "email_lower": f"test-{user_id}@example.com",
        },
    )
    db.commit()
    return user_id


def _make_document(db, user_id: uuid.UUID, s3_key: str) -> uuid.UUID:
    """Insert a PENDING document row."""
    doc_id = uuid.uuid4()
    db.execute(
        text("""
            INSERT INTO documents
                (id, user_id, filename, s3_key, file_size_bytes, mime_type, status)
            VALUES
                (:id, :user_id, 'sample.pdf', :s3_key, 1024, 'application/pdf', 'PENDING')
        """),
        {
            "id": str(doc_id),
            "user_id": str(user_id),
            "s3_key": s3_key,
        },
    )
    db.commit()
    return doc_id


# ---------------------------------------------------------------------------
# The test
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_full_ingestion_pipeline(pg_session, mock_s3):
    """
    T-36: upload PDF → run_ingest() → assert READY + chunks + similarity search.
    """
    s3_client, bucket, pdf_bytes = mock_s3

    # 1. Seed user + document
    user_id = _make_user(pg_session)
    s3_key = f"{user_id}/{uuid.uuid4()}/sample.pdf"

    # 2. Put file in mocked S3
    s3_client.put_object(Bucket=bucket, Key=s3_key, Body=pdf_bytes)

    doc_id = _make_document(pg_session, user_id, s3_key)

    # 3. Run the worker job synchronously (bypasses RQ entirely)
    from app.workers.ingest import run_ingest
    run_ingest(str(doc_id))

    # Refresh session to see committed changes from run_ingest
    pg_session.expire_all()

    # ------------------------------------------------------------------
    # Assertion 1: document status is READY
    # ------------------------------------------------------------------
    doc = pg_session.get(Document, doc_id)
    assert doc is not None
    assert doc.status == DocumentStatus.READY, (
        f"Expected READY, got {doc.status}. error_message: {doc.error_message}"
    )
    assert doc.chunk_count is not None and doc.chunk_count > 0, (
        "chunk_count should be > 0 after successful ingestion"
    )

    # ------------------------------------------------------------------
    # Assertion 2: chunk rows exist with non-null embeddings
    # ------------------------------------------------------------------
    chunks = (
        pg_session.query(Chunk)
        .filter(Chunk.document_id == doc_id)
        .all()
    )
    assert len(chunks) == doc.chunk_count, (
        f"DB has {len(chunks)} chunks but doc.chunk_count says {doc.chunk_count}"
    )
    assert all(c.embedding is not None for c in chunks), (
        "Some chunks have null embeddings — embedding step may have failed"
    )
    assert all(len(c.embedding) == 1536 for c in chunks), (
        "Embeddings should be 1536-dimensional (text-embedding-3-small)"
    )

    # ------------------------------------------------------------------
    # Assertion 3: pgvector similarity search returns results
    # ------------------------------------------------------------------
    # Use the first chunk's own embedding as the query vector —
    # it should be its own nearest neighbour, which is a tight correctness check.
    query_vector = chunks[0].embedding
    query_vec_str = "[" + ",".join(map(str, query_vector)) + "]"

    result = pg_session.execute(
        text("""
            SELECT id, chunk_index, text,
                   embedding <=> CAST(:query_vec AS vector) AS distance
            FROM chunks
            WHERE user_id = :user_id
              AND document_id = :doc_id
              AND embedding IS NOT NULL
            ORDER BY embedding <=> CAST(:query_vec AS vector)
            LIMIT 3
        """),
        {
            "user_id": str(user_id),
            "doc_id": str(doc_id),
            "query_vec": query_vec_str,
        },
    )
    rows = result.fetchall()

    assert len(rows) > 0, "pgvector similarity search returned no results"

    top_hit = rows[0]
    assert top_hit.distance < 0.01, (
        f"Top hit should be the query chunk itself (distance ≈ 0), got {top_hit.distance:.6f}"
    )
    assert top_hit.chunk_index == chunks[0].chunk_index, (
        "Top similarity hit should be chunk 0 (we queried with its own embedding)"
    )
