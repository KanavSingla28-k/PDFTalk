"""
services/file_validation.py

Validates an uploaded file before it touches S3 or the database.

Validation order (fail-fast):
    1. Size     — stream-read with a byte counter; reject at 50 MB.
                  Done first so we never buffer a huge file for subsequent checks.
    2. MIME     — python-magic inspects the buffered bytes (not the
                  Content-Type header, which the client controls and cannot
                  be trusted).
    3. Magic    — for PDFs, assert the first 4 bytes are b'%PDF'.
                  TXT / MD have no standardised magic bytes; MIME check
                  is sufficient for those types.

Returns the raw file bytes on success so the caller (upload endpoint)
does not need to re-read the already-consumed UploadFile stream.

Raises:
    FileValidationError — with a stable `reason` code and a human-readable
                          message. The centralised exception handler in
                          exceptions.py maps this to HTTP 422.
"""

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
