import pytest
import boto3
from moto import mock_aws
from io import BytesIO
from app.utils.s3_client import S3Client

BUCKET = "test-bucket"
REGION = "ap-south-1"

@pytest.fixture
def s3(monkeypatch):
    from app.utils import s3_client

    monkeypatch.setattr(
        s3_client.settings,
        "S3_BUCKET_NAME",
        BUCKET
    )

    monkeypatch.setattr(
        s3_client.settings,
        "AWS_REGION",
        REGION
    )

    with mock_aws():
        boto3.client("s3", region_name=REGION).create_bucket(
            Bucket=BUCKET,
            CreateBucketConfiguration={
                "LocationConstraint": REGION
            }
        )

        yield s3_client.S3Client()

def test_upload_and_download(s3):
    content = b"hello world"
    s3.upload_file(BytesIO(content), "user1/doc1/test.pdf", "application/pdf")
    result = s3.download_file("user1/doc1/test.pdf")
    assert result == content


def test_delete_object(s3):
    s3.upload_file(BytesIO(b"data"), "user1/doc2/file.txt", "text/plain")
    s3.delete_object("user1/doc2/file.txt")
    # Downloading after delete should raise
    with pytest.raises(Exception):
        s3.download_file("user1/doc2/file.txt")


def test_presigned_url_is_string(s3):
    s3.upload_file(BytesIO(b"data"), "user1/doc3/file.pdf", "application/pdf")
    url = s3.generate_presigned_download_url("user1/doc3/file.pdf", expires_in=300)
    assert url.startswith("https://")


def test_delete_nonexistent_key_does_not_raise(s3):
    # S3 deletes are idempotent — this should not raise
    s3.delete_object("nonexistent/key/file.pdf")