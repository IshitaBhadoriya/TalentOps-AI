"""Create synthetic PDF and DOCX sample resumes in sample_data/resumes/ from app/sample_data.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import docx
import pymupdf

from app.sample_data import SAMPLE_RESUMES

OUT = Path(__file__).resolve().parent.parent / "sample_data" / "resumes"
OUT.mkdir(parents=True, exist_ok=True)


def write_pdf(path: Path, text: str) -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(50, 50, 545, 790), text, fontsize=10.5, fontname="helv")
    doc.save(str(path))
    doc.close()


def write_docx(path: Path, text: str) -> None:
    d = docx.Document()
    for line in text.splitlines():
        d.add_paragraph(line)
    d.save(str(path))


if __name__ == "__main__":
    items = list(SAMPLE_RESUMES.items())
    for i, (name, text) in enumerate(items):
        stem = Path(name).stem
        (write_pdf if i % 2 == 0 else write_docx)(OUT / (stem + (".pdf" if i % 2 == 0 else ".docx")), text)
    print("Wrote", len(items), "sample resumes to", OUT)
