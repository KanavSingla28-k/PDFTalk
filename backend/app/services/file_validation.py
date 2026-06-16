"""
services/file_validation.py

Two validation paths are provided here:

  1. validate_upload(file: UploadFile) -> bytes
       Legacy path used by POST /documents/upload.
       Reads the entire file into memory, checks size, MIME (via libmagic),
       and magic bytes. Returns raw bytes ready for S3 upload.

  2. validate_upload_metadata(filename, mime_type, file_size_bytes) -> None
       Presigned URL path used by POST /documents/initiate-upload.
       No file bytes are available — validates only client-reported metadata
       (size and declared MIME type). Magic-byte verification is deferred to
       the ingest worker, which runs it after downloading the file from S3.

Raises:
    FileValidationError — with a stable `reason` code and a human-readable
                          message. The centralised exception handler in
                          exceptions.py maps this to HTTP 422.
"""

import sys

if sys.platform == "win32":
    from magic import magic
else:
    import magic

from fastapi import UploadFile

from app.exceptions import FileValidationError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_FILE_SIZE_BYTES: int = 50 * 1024 * 1024  # 50 MB

ALLOWED_MIME_TYPES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "text/plain",
        "text/markdown",
    }
)

# Chunk size for streaming reads — 64 KB balances memory use vs syscall count.
_READ_CHUNK: int = 64 * 1024

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def validate_upload(file: UploadFile) -> bytes:
    """
    Validate *file* and return its raw bytes.

    The returned bytes are safe to pass directly to the S3 upload helper
    without any further reading of the (now-exhausted) UploadFile stream.

    Args:
        file: The FastAPI UploadFile from the multipart request.

    Returns:
        Raw file bytes (guaranteed ≤ 50 MB, allowed MIME, valid magic).

    Raises:
        FileValidationError: On any validation failure.
    """
    raw = await _read_and_check_size(file)
    _check_mime(raw)
    _check_magic_bytes(raw)
    return raw


def validate_upload_metadata(
    filename: str,
    mime_type: str,
    file_size_bytes: int,
) -> None:
    """
    Validate file metadata reported by the client *before* any bytes are
    transferred — used by the presigned URL initiate-upload endpoint.

    Because no file content is available at this stage, only size and the
    client-declared MIME type can be checked here. Magic-byte verification
    (i.e. confirming the file content actually matches the declared type) is
    deferred to the ingest worker, which runs it after downloading from S3.

    Validation order (fail-fast):
        1. Size  — reject if file_size_bytes > MAX_FILE_SIZE_BYTES (50 MB).
        2. MIME  — reject if mime_type is not in ALLOWED_MIME_TYPES.

    Args:
        filename:        Original filename as reported by the browser.
        mime_type:       MIME type as reported by the browser (e.g. "application/pdf").
                         Cannot be trusted for content correctness — only used to
                         pre-screen obviously wrong types before issuing the URL.
        file_size_bytes: File size in bytes as reported by the browser.
                         S3 enforces the actual size when the object is PUT;
                         this check is a fast fail to catch obvious over-limit
                         uploads without generating a presigned URL.

    Returns:
        None on success.

    Raises:
        FileValidationError(reason="file_too_large"):  file_size_bytes > 50 MB.
        FileValidationError(reason="unsupported_mime"): mime_type not allowed.
    """
    if file_size_bytes > MAX_FILE_SIZE_BYTES:
        raise FileValidationError(
            reason="file_too_large",
            message=(
                f"File size {file_size_bytes // (1024 * 1024)} MB exceeds the "
                f"maximum allowed size of {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB."
            ),
        )

    if mime_type not in ALLOWED_MIME_TYPES:
        raise FileValidationError(
            reason="unsupported_mime",
            message=(
                f"File type '{mime_type}' is not supported. "
                f"Allowed types: PDF, plain text, Markdown."
            ),
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _read_and_check_size(file: UploadFile) -> bytes:
    """
    Stream-read *file* in 64 KB chunks, enforcing the 50 MB limit.

    Raises FileValidationError(reason="file_too_large") as soon as the
    running byte total exceeds MAX_FILE_SIZE_BYTES — we never buffer more
    than MAX_FILE_SIZE_BYTES + _READ_CHUNK bytes in memory.
    """
    chunks: list[bytes] = []
    total = 0

    while True:
        chunk = await file.read(_READ_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_FILE_SIZE_BYTES:
            raise FileValidationError(
                reason="file_too_large",
                message=(
                    f"File exceeds the maximum allowed size of "
                    f"{MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB."
                ),
            )
        chunks.append(chunk)

    return b"".join(chunks)


def _check_mime(data: bytes) -> None:
    """
    Use libmagic to detect the MIME type from file content (not headers).

    Raises FileValidationError(reason="unsupported_mime") if the detected
    type is not in ALLOWED_MIME_TYPES.
    """
    detected: str = magic.from_buffer(data, mime=True)

    if detected not in ALLOWED_MIME_TYPES:
        raise FileValidationError(
            reason="unsupported_mime",
            message=(
                f"File type '{detected}' is not supported. "
                f"Allowed types: PDF, plain text, Markdown."
            ),
        )


def _check_magic_bytes(data: bytes) -> None:
    """
    For PDFs: assert the file starts with the %PDF magic signature.

    libmagic already catches most disguised files, but an explicit magic-byte
    check provides a second, independent layer of defence — a malformed
    libmagic database or edge-case buffer could theoretically mis-classify a
    file that has the wrong header.

    TXT and Markdown have no standardised magic bytes; the MIME check alone
    is sufficient for those types.

    Raises FileValidationError(reason="invalid_magic_bytes") on mismatch.
    """
    mime: str = magic.from_buffer(data, mime=True)

    if mime == "application/pdf":
        if not data[:4] == b"%PDF":
            raise FileValidationError(
                reason="invalid_magic_bytes",
                message="File does not appear to be a valid PDF (missing %PDF header).",
            )
