import os
import boto3
import pytest
from moto import mock_aws
from unittest.mock import patch, AsyncMock

# Single source of truth for the test bucket name.
# Must match what s3_client._bucket will be set to.
_TEST_BUCKET = "pdftalk-test-bucket"


@pytest.fixture(autouse=True)
def s3_mock(monkeypatch):
    with mock_aws():
        from app.utils.s3_client import s3_client

        moto_client = boto3.client(
            "s3",
            region_name="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test",  # pragma: allowlist secret
        )
        moto_client.create_bucket(Bucket=_TEST_BUCKET)

        original_client = s3_client._client
        original_bucket = s3_client.bucket          # ← was _bucket
        s3_client._client = moto_client
        s3_client.bucket = _TEST_BUCKET             # ← was _bucket

        yield s3_client

        s3_client._client = original_client
        s3_client.bucket = original_bucket          # ← was _bucket

@pytest.fixture(autouse=True)
def mock_ingest_enqueue():
    with patch("app.routers.documents.ingest_queue.enqueue") as mock_enqueue:
        yield mock_enqueue


@pytest.fixture(autouse=True)
def mock_query_usage():
    with patch(
        "app.routers.query.check_and_increment_query_usage",
        new=AsyncMock(),
    ) as mock_usage:
        yield mock_usage


@pytest.fixture
def mock_retrieval():
    with patch(
        "app.routers.query.retrieve_similar_chunks",
        new=AsyncMock(),
    ) as mock:
        yield mock
