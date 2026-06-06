import boto3
from botocore.exceptions import ClientError
from typing import BinaryIO
from app.core.config import settings
import structlog
from pathlib import Path

logger = structlog.get_logger()


class S3Client:
    def __init__(self):
        self._client = boto3.client(
            "s3",
            region_name=settings.AWS_REGION,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        )
        self.bucket = settings.S3_BUCKET_NAME

    def upload_file(self, file_obj: BinaryIO, s3_key: str, content_type: str) -> None:
        """Upload a file-like object to S3."""
        try:
            self._client.upload_fileobj(
                file_obj,
                self.bucket,
                s3_key,
                ExtraArgs={"ContentType": content_type, "ServerSideEncryption": "AES256"},
            )
            logger.info("s3_upload_success", key=s3_key)
        except ClientError as e:
            logger.error("s3_upload_failed", key=s3_key, error=str(e))
            raise

    def download_file(self, s3_key: str) -> bytes:
        """Download an object and return its content as bytes."""
        try:
            response = self._client.get_object(Bucket=self.bucket, Key=s3_key)
            return response["Body"].read()
        except ClientError as e:
            logger.error("s3_download_failed", key=s3_key, error=str(e))
            raise

    def delete_object(self, s3_key: str) -> None:
        """Delete a single object. Silently succeeds if the key doesn't exist."""
        try:
            self._client.delete_object(Bucket=self.bucket, Key=s3_key)
            logger.info("s3_delete_success", key=s3_key)
        except ClientError as e:
            logger.error("s3_delete_failed", key=s3_key, error=str(e))
            raise

    def generate_presigned_download_url(self, s3_key: str, expires_in: int = 3600) -> str:
        """Generate a time-limited URL for direct client download."""
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": s3_key},
            ExpiresIn=expires_in,
        )

def build_document_s3_key(user_id: str, document_id: str, filename: str) -> str:
    # Sanitise filename — strip any path components an attacker might sneak in
    safe_filename = Path(filename).name
    return f"{user_id}/{document_id}/{safe_filename}"


# Singleton — import this everywhere
s3_client = S3Client()

