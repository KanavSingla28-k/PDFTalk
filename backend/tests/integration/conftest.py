import os
import boto3
import pytest
from moto import mock_aws
from unittest.mock import patch, AsyncMock

@pytest.fixture(autouse=True)
def s3_mock(monkeypatch):
    """Mock S3 bucket for all integration tests."""
    with mock_aws():
        # Re-initialize the global s3_client's internal boto3 client
        # so it gets wrapped by moto correctly.
        from app.utils.s3_client import s3_client
        s3_client._client = boto3.client(
            "s3",
            region_name="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test"    # pragma: allowlist secret
        )
        bucket = os.environ.get("S3_BUCKET_NAME", "pdftalk-test-bucket")
        s3_client._client.create_bucket(Bucket=bucket)
        
        yield s3_client

@pytest.fixture(autouse=True)
def mock_ingest_enqueue():
    with patch(
        "app.routers.documents.ingest_queue.enqueue"
    ) as mock_enqueue:
        yield mock_enqueue

@pytest.fixture(autouse=True)
def mock_query_usage():
    with patch(
        "app.routers.query.check_and_increment_query_usage",
        new=AsyncMock()
    ) as mock_usage:
        yield mock_usage

@pytest.fixture
def mock_retrieval():
    with patch(
        "app.routers.query.retrieve_similar_chunks",
        new=AsyncMock(),
    ) as mock:
        yield mock
