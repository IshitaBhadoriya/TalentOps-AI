import sys
from pathlib import Path

import docx
import pymupdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

RESUME_TEXT = """Jane Tester
jane.tester@example.com
+91 90000 11111

Skills
Python, SQL, Docker

Education
B.Tech Computer Science, Example University

Projects
Built REST APIs in Python and stored results in SQL databases
Trained a machine learning classifier with scikit-learn
"""


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Every test gets its own database, TF-IDF backend (no model download) and no webhook."""
    monkeypatch.setenv("TALENTOPS_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("TALENTOPS_EMBEDDING_BACKEND", "tfidf")
    monkeypatch.setenv("N8N_WEBHOOK_URL", "")
    from app import db, matching

    matching._cached = None
    db.init_db()
    yield


def make_pdf_bytes(text: str) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    if text:
        page.insert_textbox(pymupdf.Rect(50, 50, 545, 790), text, fontsize=10)
    data = doc.tobytes()
    doc.close()
    return data


def make_docx_bytes(text: str) -> bytes:
    import io

    d = docx.Document()
    for line in text.splitlines():
        d.add_paragraph(line)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


@pytest.fixture
def resume_text():
    return RESUME_TEXT


@pytest.fixture
def resume_pdf():
    return make_pdf_bytes(RESUME_TEXT)


@pytest.fixture
def resume_docx():
    return make_docx_bytes(RESUME_TEXT)
