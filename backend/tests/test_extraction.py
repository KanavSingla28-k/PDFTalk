# tests/services/test_extraction.py

import pytest
from unittest.mock import patch
from app.services.extraction import extract_text, ExtractionError


def _make_pdf(text: str = "Hello world") -> bytes:
    """Create a minimal real PDF in memory using PyMuPDF."""
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), text)
    return doc.tobytes()


def test_extract_pdf_returns_text():
    pdf_bytes = _make_pdf("Hello PDFTalk")
    with patch("app.services.extraction.s3_client.download_file", return_value=pdf_bytes):
        result = "".join(extract_text("user/doc/file.pdf", "application/pdf"))
    assert "Hello PDFTalk" in result


class MockStreamingBody:
    def __init__(self, content: bytes):
        self.content = content
    def iter_chunks(self, chunk_size=None):
        yield self.content

def test_extract_txt_returns_text():
    with patch("app.services.extraction.s3_client.download_file_streaming", return_value=MockStreamingBody(b"Hello plain text")):
        result = "".join(extract_text("user/doc/file.txt", "text/plain"))
    assert result == "Hello plain text"


def test_extract_txt_replacement_char_on_bad_bytes():
    bad_bytes = b"Hello \xff world"
    with patch("app.services.extraction.s3_client.download_file_streaming", return_value=MockStreamingBody(bad_bytes)):
        result = "".join(extract_text("user/doc/file.txt", "text/plain"))
    assert "Hello" in result
    assert "\xff" not in result


def test_extract_unsupported_mime_raises():
    with pytest.raises(ExtractionError) as exc_info:
        list(extract_text("user/doc/file.html", "text/html"))
    assert "Unsupported MIME type" in exc_info.value.reason


def test_extract_corrupt_pdf_raises():
    with patch("app.services.extraction.s3_client.download_file", return_value=b"not a pdf"):
        with pytest.raises(ExtractionError) as exc_info:
            list(extract_text("user/doc/file.pdf", "application/pdf"))
    assert "Corrupt" in exc_info.value.reason

def test_extract_image_only_pdf_triggers_ocr():
    """A PDF page with no text layer should fall through to OCR."""
    import fitz
    from unittest.mock import patch

    # Build a PDF whose single page has no text (just a blank page)
    doc = fitz.open()
    doc.new_page()  # blank — no text layer
    pdf_bytes = doc.tobytes()

    mock_ocr_result = "Handwritten notes extracted by OCR"

    with patch("app.services.extraction.s3_client.download_file", return_value=pdf_bytes), \
         patch("pytesseract.image_to_string", return_value=mock_ocr_result):
        result = "".join(extract_text("user/doc/scan.pdf", "application/pdf"))

    assert "Handwritten notes extracted by OCR" in result
