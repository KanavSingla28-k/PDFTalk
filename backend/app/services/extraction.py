from __future__ import annotations

import io
import structlog
import unicodedata
from dataclasses import dataclass
from enum import Enum

import fitz  # PyMuPDF

from app.utils.s3_client import s3_client

logger = structlog.get_logger()

class MimeType(str, Enum):
    PDF = "application/pdf"
    TXT = "text/plain"
    MD = "text/markdown"


@dataclass
class ExtractionError(Exception):
    """Raised when a file cannot be extracted."""
    reason: str
    s3_key: str

    def __str__(self) -> str:
        return f"ExtractionError({self.reason!r}) for key={self.s3_key!r}"


def extract_text(s3_key: str, mime_type: str) -> str:
    """
    Download file from S3 and extract its full text content.

    Returns a single cleaned string ready for chunking.
    Raises ExtractionError on any unrecoverable failure.
    """
    raw: bytes = _download(s3_key)

    try:
        mime = MimeType(mime_type)
    except ValueError:
        raise ExtractionError(
            reason=f"Unsupported MIME type: {mime_type}",
            s3_key=s3_key,
        )

    match mime:
        case MimeType.PDF:
            return _extract_pdf(raw, s3_key)
        case MimeType.TXT | MimeType.MD:
            return _extract_plaintext(raw, s3_key)
        case _:
            raise ExtractionError(reason=f"Unsupported MIME type: {mime_type}", s3_key=s3_key)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _download(s3_key: str) -> bytes:
    """Delegate to the S3 client wrapper."""
    return s3_client.download_file(s3_key)

def _extract_pdf(raw: bytes, s3_key: str) -> str:
    """
    Extract text from a PDF using PyMuPDF.
    Pages with no embedded text are OCR'd via pytesseract.
    """
    try:
        doc = fitz.open(stream=raw, filetype="pdf")
    except fitz.FileDataError as exc:
        raise ExtractionError(reason=f"Corrupt or unreadable PDF: {exc}", s3_key=s3_key) from exc

    if doc.is_encrypted:
        if doc.authenticate("") == 0:
            raise ExtractionError(reason="PDF is encrypted and could not be decrypted", s3_key=s3_key)

    try:
        pages: list[str] = []
        for page_num, page in enumerate(doc, start=1):   # type: ignore[arg-type]
            try:
                text = page.get_text("text").strip()
            except Exception as exc:
                logger.warning("Failed to extract page %d from %s: %s", page_num, s3_key, exc)
                text = ""

            if not text:
                # Page has no embedded text — render it and OCR
                logger.info("Page %d of %s has no text layer — running OCR", page_num, s3_key)
                text = _ocr_page(page, page_num, s3_key)

            pages.append(text)
    finally:
        doc.close()

    full_text = "\n\n".join(pages)
    return _clean(full_text)

def _ocr_page(page: fitz.Page, page_num: int, s3_key: str) -> str:
    """
    Render a PDF page to an image and extract text via tesseract.
    Returns empty string (with a warning) on OCR failure — never raises,
    since a single bad page should not fail the whole document.
    """
    import pytesseract
    from PIL import Image

    try:
        # 2x scale (matrix) gives tesseract enough resolution to work accurately
        # 150 DPI is the minimum tesseract needs; 2x on a standard 72dpi PDF = 144dpi, close enough
        # Use 3x if you expect small handwriting
        mat = fitz.Matrix(2, 2)
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)

        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        text = pytesseract.image_to_string(img, lang="eng")
        return text.strip()

    except Exception as exc:
        logger.warning("OCR failed on page %d of %s: %s", page_num, s3_key, exc)
        return ""

def _extract_plaintext(raw: bytes, s3_key: str) -> str:
    """Decode TXT/MD bytes to a string with a safe UTF-8 fallback."""
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception as exc:
        raise ExtractionError(reason=f"Failed to decode file: {exc}", s3_key=s3_key) from exc

    return _clean(text)

def _clean(text: str) -> str:
    """
    Normalise whitespace and strip control characters.
    Keeps newlines (structurally meaningful) but collapses runs of blank lines.
    """
    # Normalise unicode to NFC (handles accented chars, ligatures, etc.)
    text = unicodedata.normalize("NFC", text)

    # Strip non-printable control characters except \n and \t
    text = "".join(
        ch for ch in text
        if ch in ("\n", "\t") or not unicodedata.category(ch).startswith("C")
    )

    # Collapse runs of 3+ newlines down to 2 (preserve paragraph breaks, kill blank page gaps)
    import re
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()