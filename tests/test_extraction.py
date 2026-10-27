import pytest

from app.extraction import ExtractionError, extract_text
from tests.conftest import make_docx_bytes, make_pdf_bytes


def test_pdf_extraction(resume_pdf):
    r = extract_text("cv.pdf", resume_pdf)
    assert "jane.tester@example.com" in r.text and r.file_type == "pdf"


def test_docx_extraction(resume_docx):
    r = extract_text("cv.docx", resume_docx)
    assert "Jane Tester" in r.text and r.file_type == "docx"


def test_empty_file_rejected():
    with pytest.raises(ExtractionError, match="empty"):
        extract_text("cv.pdf", b"")


def test_invalid_file_type_rejected():
    with pytest.raises(ExtractionError, match="Unsupported"):
        extract_text("cv.exe", b"MZ...")


def test_renamed_file_rejected():
    with pytest.raises(ExtractionError, match="not a valid PDF"):
        extract_text("cv.pdf", b"this is plain text, not a pdf" * 5)
    with pytest.raises(ExtractionError, match="not a valid DOCX"):
        extract_text("cv.docx", b"plain text" * 10)


def test_oversized_file_rejected(resume_pdf):
    with pytest.raises(ExtractionError, match="too large"):
        extract_text("cv.pdf", resume_pdf, max_bytes=100)


def test_image_only_or_blank_pdf_gives_helpful_error():
    with pytest.raises(ExtractionError, match="OCR"):
        extract_text("scan.pdf", make_pdf_bytes(""))


def test_blank_docx_rejected():
    with pytest.raises(ExtractionError, match="No readable text"):
        extract_text("blank.docx", make_docx_bytes(""))


def test_corrupt_docx_rejected():
    with pytest.raises(ExtractionError, match="Could not open DOCX"):
        extract_text("bad.docx", b"PK\x03\x04garbage")
