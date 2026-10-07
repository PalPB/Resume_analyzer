"""
pdf_parser.py — PDF text extraction
=====================================
FIXED version. Changes from original:
  - Stops masking pypdf as PyPDF2 — picks one library and uses it correctly.
  - Errors are logged with reasons instead of silently returning "".
  - Returns a named error string ("__PDF_ERROR__") so callers can distinguish
    "empty resume" from "failed to parse" — both returned "" before.
  - Tries pdfminer as a fallback if pypdf returns no text (handles scanned PDFs
    and unusual encodings that PyPDF2/pypdf miss).
"""

import io
import logging

log = logging.getLogger("pdf_parser")

# ── library selection ─────────────────────────────────────────────────────────
# Use pypdf (the maintained fork). Do NOT alias it as PyPDF2 — they have
# diverged and the aliasing hides API mismatch errors.
# Pin to pypdf>=4.0 in requirements.txt.
try:
    from pypdf import PdfReader
    _PDF_LIB = "pypdf"
except ImportError:
    try:
        # PyPDF2 is still around on some older environments
        from PyPDF2 import PdfReader  # type: ignore[no-redef]
        _PDF_LIB = "PyPDF2"
    except ImportError:
        PdfReader = None  # type: ignore[assignment,misc]
        _PDF_LIB = "none"

log.info("PDF library in use: %s", _PDF_LIB)

# Optional: pdfminer.six for scanned/unusual PDFs
try:
    from pdfminer.high_level import extract_text as pdfminer_extract
    _HAS_PDFMINER = True
except ImportError:
    _HAS_PDFMINER = False


def extract_text_from_pdf(file) -> str:
    """
    Extract text from a PDF file.

    Args:
        file: bytes, or a file-like object with a .read() method.

    Returns:
        Extracted text as a string.
        Returns "" if the PDF is empty/image-only.
        Returns "__PDF_ERROR__:reason" if parsing fails — check for this
        prefix in callers to distinguish parse failure from empty content.

    IMPORTANT: The caller (app.py / api.py) must check for "__PDF_ERROR__"
    and surface a meaningful message to the user.
    """
    # ── normalise input to bytes
    if isinstance(file, bytes):
        file_bytes = file
    elif hasattr(file, "read"):
        file_bytes = file.read()
    else:
        log.error("extract_text_from_pdf: unsupported input type %s", type(file))
        return "__PDF_ERROR__:unsupported input type"

    # ── basic validation
    if not file_bytes:
        log.warning("extract_text_from_pdf: empty bytes received")
        return "__PDF_ERROR__:empty file"

    if len(file_bytes) > 5 * 1024 * 1024:
        log.warning("extract_text_from_pdf: file too large (%d bytes)", len(file_bytes))
        return "__PDF_ERROR__:file exceeds 5 MB limit"

    if not file_bytes.startswith(b"%PDF"):
        log.warning("extract_text_from_pdf: file does not start with %%PDF signature")
        return "__PDF_ERROR__:not a valid PDF file"

    if PdfReader is None:
        log.error("No PDF library available (pypdf / PyPDF2 not installed)")
        return "__PDF_ERROR__:PDF library not installed — run: pip install pypdf"

    # ── primary extraction with pypdf / PyPDF2
    text = _extract_with_reader(file_bytes)

    # ── fallback to pdfminer if primary returned nothing
    # (common with scanned PDFs, unusual font encodings, or certain generators)
    if not text.strip() and _HAS_PDFMINER:
        log.info("Primary extraction returned empty text — trying pdfminer fallback.")
        text = _extract_with_pdfminer(file_bytes)

    if not text.strip():
        log.warning(
            "PDF parsed successfully but no text was extracted. "
            "The file may be a scanned image — OCR is required."
        )
        # Return empty string (not an error) — the resume is genuinely text-free
        return ""

    log.info("Extracted %d characters from PDF.", len(text))
    return text


def _extract_with_reader(file_bytes: bytes) -> str:
    """Extract text using pypdf / PyPDF2."""
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        pages = []
        for i, page in enumerate(reader.pages):
            try:
                page_text = page.extract_text() or ""
                pages.append(page_text)
            except Exception as e:
                # A single bad page should not abort the whole document
                log.warning("Page %d extraction failed: %s", i, e)
                pages.append("")

        return "\n".join(pages).strip()

    except Exception as e:
        log.error("PdfReader failed: %s: %s", type(e).__name__, e)
        return ""


def _extract_with_pdfminer(file_bytes: bytes) -> str:
    """Extract text using pdfminer.six (more robust for unusual encodings)."""
    try:
        text = pdfminer_extract(io.BytesIO(file_bytes))
        return (text or "").strip()
    except Exception as e:
        log.warning("pdfminer extraction failed: %s", e)
        return ""