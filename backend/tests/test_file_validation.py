"""
tests/services/test_file_validation.py

Unit tests for app/services/file_validation.py.

Strategy:
  - No real file I/O. UploadFile is faked by constructing instances backed
    by io.BytesIO — this is the standard FastAPI pattern for unit tests and
    does not require a running ASGI app or httpx client.
  - python-magic is NOT mocked. It is called with synthetic byte payloads,
    which is the correct level to test at (we want to assert that a real
    %PDF header is detected as application/pdf, not just that we called a
    mock).
  - Each parametrize case covers exactly one observable behaviour so
    failures are unambiguous.
"""

import io
import magic
import pytest

from fastapi import UploadFile

from app.exceptions import FileValidationError
from app.services.file_validation import (
    MAX_FILE_SIZE_BYTES,
    validate_upload,
    _check_magic_bytes,
    _check_mime,
    _read_and_check_size,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_upload(data: bytes, filename: str = "test.bin") -> UploadFile:
    """Return a FastAPI UploadFile backed by an in-memory BytesIO."""
    return UploadFile(filename=filename, file=io.BytesIO(data))


# Minimal valid PDF: magic header + enough structure to satisfy libmagic.
_VALID_PDF = b"%PDF-1.4 fake content"

# Minimal plain-text content.
_VALID_TXT = b"Hello, world."

# Minimal Markdown content (libmagic detects this as text/plain or text/markdown).
_VALID_MD = b"# Heading\n\nSome markdown content."

# A PNG magic header — clearly not an allowed type.
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

# A valid PDF header followed by 1 byte over the limit.
_OVER_LIMIT = b"%PDF-1.4 " + b"x" * (MAX_FILE_SIZE_BYTES + 1)


# ---------------------------------------------------------------------------
# _read_and_check_size
# ---------------------------------------------------------------------------

class TestReadAndCheckSize:

    @pytest.mark.asyncio
    async def test_returns_bytes_within_limit(self):
        upload = _make_upload(_VALID_PDF)
        result = await _read_and_check_size(upload)
        assert result == _VALID_PDF

    @pytest.mark.asyncio
    async def test_raises_on_oversized_file(self):
        upload = _make_upload(_OVER_LIMIT)
        with pytest.raises(FileValidationError) as exc_info:
            await _read_and_check_size(upload)
        assert exc_info.value.reason == "file_too_large"

    @pytest.mark.asyncio
    async def test_exact_limit_is_accepted(self):
        data = b"%PDF-1.4 " + b"x" * (MAX_FILE_SIZE_BYTES - 9)
        assert len(data) == MAX_FILE_SIZE_BYTES
        upload = _make_upload(data)
        result = await _read_and_check_size(upload)
        assert len(result) == MAX_FILE_SIZE_BYTES

    @pytest.mark.asyncio
    async def test_empty_file_is_accepted(self):
        # Size check should not reject an empty file — that's a MIME concern.
        upload = _make_upload(b"")
        result = await _read_and_check_size(upload)
        assert result == b""


# ---------------------------------------------------------------------------
# _check_mime
# ---------------------------------------------------------------------------

class TestCheckMime:

    def test_pdf_accepted(self):
        _check_mime(_VALID_PDF)  # no exception

    def test_plain_text_accepted(self):
        _check_mime(_VALID_TXT)  # no exception

    def test_png_rejected(self):
        with pytest.raises(FileValidationError) as exc_info:
            _check_mime(_PNG_BYTES)
        assert exc_info.value.reason == "unsupported_mime"

    def test_reason_code_is_stable(self):
        with pytest.raises(FileValidationError) as exc_info:
            _check_mime(_PNG_BYTES)
        # Callers and the exception handler rely on this exact string.
        assert exc_info.value.reason == "unsupported_mime"

    def test_message_contains_detected_type(self):
        # libmagic's classification of synthetic bytes varies by platform/version
        # (e.g. Windows reports application/octet-stream, Linux reports image/png).
        # Assert the detected type — whatever it is — appears in the error message.
        with pytest.raises(FileValidationError) as exc_info:
            _check_mime(_PNG_BYTES)
        detected = magic.from_buffer(_PNG_BYTES, mime=True)
        assert detected in str(exc_info.value)


# ---------------------------------------------------------------------------
# _check_magic_bytes
# ---------------------------------------------------------------------------

class TestCheckMagicBytes:

    def test_valid_pdf_passes(self):
        _check_magic_bytes(_VALID_PDF)  # no exception

    def test_pdf_mime_with_wrong_header_fails(self):
        # Construct bytes that libmagic calls application/pdf but lack %PDF.
        # In practice this is hard to trigger with real libmagic, so we test
        # the branch indirectly: patch just the magic.from_buffer call.
        import unittest.mock as mock

        fake_pdf_body = b"NOTPDF fake content body"

        with mock.patch(
            "app.services.file_validation.magic.from_buffer",
            return_value="application/pdf",
        ):
            with pytest.raises(FileValidationError) as exc_info:
                _check_magic_bytes(fake_pdf_body)

        assert exc_info.value.reason == "invalid_magic_bytes"

    def test_txt_skips_magic_check(self):
        # Plain text has no magic bytes — function must not raise.
        _check_magic_bytes(_VALID_TXT)  # no exception

    def test_markdown_skips_magic_check(self):
        _check_magic_bytes(_VALID_MD)  # no exception


# ---------------------------------------------------------------------------
# validate_upload (integration — all three checks in sequence)
# ---------------------------------------------------------------------------

class TestValidateUpload:

    @pytest.mark.asyncio
    async def test_valid_pdf_returns_bytes(self):
        upload = _make_upload(_VALID_PDF)
        result = await validate_upload(upload)
        assert result == _VALID_PDF

    @pytest.mark.asyncio
    async def test_valid_txt_returns_bytes(self):
        upload = _make_upload(_VALID_TXT)
        result = await validate_upload(upload)
        assert result == _VALID_TXT

    @pytest.mark.asyncio
    async def test_oversized_file_raises_before_mime_check(self):
        # Size failure must occur before MIME check (fail-fast order).
        upload = _make_upload(_OVER_LIMIT)
        with pytest.raises(FileValidationError) as exc_info:
            await validate_upload(upload)
        assert exc_info.value.reason == "file_too_large"

    @pytest.mark.asyncio
    async def test_wrong_mime_raises(self):
        upload = _make_upload(_PNG_BYTES)
        with pytest.raises(FileValidationError) as exc_info:
            await validate_upload(upload)
        assert exc_info.value.reason == "unsupported_mime"

    @pytest.mark.asyncio
    async def test_invalid_pdf_magic_raises(self):
        import unittest.mock as mock

        fake_pdf = b"NOTPDF fake pdf body"
        upload = _make_upload(fake_pdf)

        with mock.patch(
            "app.services.file_validation.magic.from_buffer",
            return_value="application/pdf",
        ):
            with pytest.raises(FileValidationError) as exc_info:
                await validate_upload(upload)

        assert exc_info.value.reason == "invalid_magic_bytes"

    @pytest.mark.asyncio
    async def test_returns_full_bytes_not_partial(self):
        # Confirm the caller gets everything, not just the last chunk.
        data = _VALID_PDF * 100  # well within size limit
        upload = _make_upload(data)
        result = await validate_upload(upload)
        assert result == data
