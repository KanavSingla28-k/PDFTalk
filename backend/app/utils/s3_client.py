import boto3
from botocore.exceptions import ClientError
from typing import BinaryIO, cast, Any
from app.core.config import settings
import structlog
from pathlib import Path

logger = structlog.get_logger()


class S3Client:
    def __init__(self) -> None:
        from botocore.client import Config

        self._client = boto3.client(
            "s3",
            region_name=settings.AWS_REGION,
            endpoint_url=f"https://s3.{settings.AWS_REGION}.amazonaws.com",
            config=Config(s3={"addressing_style": "virtual"}),
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
            return cast(bytes, response["Body"].read())
        except ClientError as e:
            logger.error("s3_download_failed", key=s3_key, error=str(e))
            raise

    def download_file_streaming(self, s3_key: str) -> BinaryIO:
        """Download an object and return its content as a streaming body."""
        try:
            response = self._client.get_object(Bucket=self.bucket, Key=s3_key)
            return cast(BinaryIO, response["Body"])
        except ClientError as e:
            logger.error("s3_download_streaming_failed", key=s3_key, error=str(e))
            raise

    def delete_object(self, s3_key: str) -> None:
        """Delete a single object. Silently succeeds if the key doesn't exist."""
        try:
            self._client.delete_object(Bucket=self.bucket, Key=s3_key)
            logger.info("s3_delete_success", key=s3_key)
        except ClientError as e:
            logger.error("s3_delete_failed", key=s3_key, error=str(e))
            raise

    def check_connectivity(self) -> None:
        """Ping S3 by calling HeadBucket. Raises on any error."""
        self._client.head_bucket(Bucket=self.bucket)

    def generate_presigned_download_url(
        self, s3_key: str, expires_in: int = 3600, filename: str | None = None
    ) -> str:
        """Generate a time-limited URL for direct client download."""
        params: dict[str, Any] = {"Bucket": self.bucket, "Key": s3_key}
        if filename:
            # Force the browser to download the file instead of displaying it inline
            params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'

        return cast(
            str,
            self._client.generate_presigned_url(
                "get_object",
                Params=params,
                ExpiresIn=expires_in,
            ),
        )

    def generate_presigned_upload_url(
        self,
        s3_key: str,
        content_type: str,
        expires_in: int = 900,  # 15 minutes — generous for slow connections
    ) -> str:
        """
        Generate a time-limited presigned URL that allows the browser to PUT a
        file directly to S3, bypassing the API server entirely.

        The signed URL is bound to:
          - The specific s3_key (any other key is rejected by S3)
          - The declared content_type (S3 returns 403 on mismatch)
          - The expiry window (default 15 min)

        Encryption note:
          Server-side encryption is NOT embedded in this signature because
          presigned PUT URLs cannot carry SSE headers in the signature without
          requiring the client to echo them back in the PUT request, which
          complicates CORS. Instead, encryption must be enforced at the bucket
          level via a default encryption policy (SSE-S3 / AES-256). This is
          more secure than per-request headers because it is unconditional and
          cannot be bypassed by any caller.

        Args:
            s3_key:       Full S3 object key (path) the client will PUT to.
            content_type: MIME type the client must declare in its PUT request.
            expires_in:   Seconds until the URL expires (default 900 = 15 min).

        Returns:
            A presigned HTTPS URL. Valid for a single PUT operation.
        """
        return cast(
            str,
            self._client.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": self.bucket,
                    "Key": s3_key,
                    "ContentType": content_type,
                },
                ExpiresIn=expires_in,
            ),
        )

    def head_object(self, s3_key: str) -> dict[str, Any]:
        """
        Perform a lightweight S3 HeadObject call to verify an object exists
        without downloading any bytes.

        Used by the confirm-upload endpoint to guard against fake confirm
        requests for objects that were never uploaded. A missing object raises
        ClientError with code '404' or 'NoSuchKey'.

        Args:
            s3_key: The S3 object key to check.

        Returns:
            The HeadObject response dict (contains ContentLength, ETag, etc.).

        Raises:
            ClientError: If the object does not exist or access is denied.
        """
        try:
            response = self._client.head_object(Bucket=self.bucket, Key=s3_key)
            logger.info("s3_head_object_success", key=s3_key)
            return cast(dict[str, Any], response)
        except ClientError as e:
            logger.error("s3_head_object_failed", key=s3_key, error=str(e))
            raise


def build_document_s3_key(user_id: str, document_id: str, filename: str) -> str:
    # Sanitise filename — strip any path components an attacker might sneak in
    safe_filename = Path(filename).name
    return f"{user_id}/{document_id}/{safe_filename}"


# Singleton — import this everywhere
s3_client = S3Client()
