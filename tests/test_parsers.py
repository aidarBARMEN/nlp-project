from pathlib import Path

import pymupdf
import pytest

from ingestion.parsers import DOCX, PDF, detect_mime, parse
from ingestion.parsers.html_parser import parse_html


def test_pdf_parser(pdf_factory):
    parsed = parse(pdf_factory(), PDF, "policy.pdf", "fixture.pdf")
    assert not parsed.needs_ocr
    assert len(parsed.pages) == 2
    assert parsed.pages[1].page_number == 2
    assert parsed.pages[0].source == "fixture.pdf"
    assert any(b.kind == "heading" for b in parsed.blocks)
    assert "GPA" in parsed.pages[0].text


def test_docx_parser(docx_bytes):
    parsed = parse(docx_bytes, DOCX, "calendar.docx", "fixture.docx")
    assert parsed.title == "Academic calendar 2026-2027"
    table_index = next(i for i, b in enumerate(parsed.blocks) if b.kind == "table")
    assert "Grade | Points" in parsed.blocks[table_index].text
    assert "After table" in parsed.blocks[table_index + 1].text
    assert parsed.blocks[table_index].section == "Examinations"


def test_html_parser():
    parsed = parse_html(
        Path("tests/fixtures/student_page.html").read_bytes(),
        "https://kbtu.edu.kz/ru/studentam/library",
    )
    text = "\n".join(b.text for b in parsed.blocks)
    assert "garbage" not in text
    assert "Accept cookies" not in text
    assert "Grade | Points" in text
    block = next(b for b in parsed.blocks if b.text.startswith("Students"))
    assert block.section == "Admission"
    assert block.subsection == "Required documents"
    assert parsed.metadata["document_links"][0]["url"] == "https://kbtu.edu.kz/files/policy.pdf"


def test_mime_by_bytes_not_extension(pdf_factory, docx_bytes):
    assert detect_mime(pdf_factory()) == PDF
    assert detect_mime(docx_bytes) == DOCX
    with pytest.raises(ValueError, match="Unsupported"):
        detect_mime(b"not actually a PDF")


def test_scanned_pdf_needs_ocr():
    with pymupdf.open() as doc:
        page = doc.new_page()
        pixmap = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 40, 40), 0)
        pixmap.clear_with(255)
        page.insert_image(page.rect, pixmap=pixmap)
        parsed = parse(doc.tobytes(), PDF, "scan.pdf", "scan")
    assert parsed.needs_ocr
    assert parsed.metadata["ocr_pages"] == [1]


def test_broken_pdf():
    with pytest.raises(pymupdf.FileDataError):
        parse(b"%PDF-1.7\nbroken", PDF, "broken.pdf", "broken")


def test_joomla_sections_and_standalone_document_links():
    parsed = parse_html(
        b'<html><main><p>{spoiler=Rules}</p><div><a href="/files/rules.pdf">'
        b"Academic rules</a></div><p>{/spoilers}</p></main></html>",
        "https://kbtu.edu.kz/ru/studentam/library",
    )
    assert parsed.blocks[0].text == "Rules"
    assert parsed.blocks[1].section == "Rules"
    assert "Academic rules" in parsed.blocks[1].text
    assert "https://kbtu.edu.kz/files/rules.pdf" in parsed.blocks[1].text
    assert all("spoiler" not in block.text for block in parsed.blocks)


def test_ocr_recognizes_scan_and_keeps_page_numbers(monkeypatch):
    calls = []

    def recognize(page, **kwargs):
        calls.append((page.number, kwargs))
        page.insert_text((72, 90), "Recognized official university registration rules.")
        return page.get_textpage()

    monkeypatch.setattr(pymupdf.Page, "get_textpage_ocr", recognize)
    monkeypatch.setattr(
        "ingestion.parsers.pdf_parser.ocr_data_directory", lambda *_: "test-tessdata"
    )
    with pymupdf.open() as doc:
        doc.new_page().insert_text((72, 90), "This page already contains native PDF text.")
        scanned = doc.new_page()
        pixmap = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 40, 40), 0)
        pixmap.clear_with(255)
        scanned.insert_image(scanned.rect, pixmap=pixmap)
        parsed = parse(doc.tobytes(), PDF, "scan.pdf", "scan", ocr=True)
    assert not parsed.needs_ocr
    assert [call[0] for call in calls] == [1]
    assert calls[0][1]["tessdata"] == "test-tessdata"
    assert calls[0][1]["language"] == "rus+kaz+eng"
    assert parsed.metadata["ocr_completed_pages"] == [2]
    assert parsed.metadata["ocr_pages"] == []
    assert "Recognized" in parsed.pages[1].text
    assert any(b.page_number == 2 and "Recognized" in b.text for b in parsed.blocks)


def test_missing_ocr_languages_have_actionable_error(tmp_path):
    from ingestion.parsers.pdf_parser import ocr_data_directory

    with pytest.raises(ValueError, match="setup_ocr.py"):
        ocr_data_directory("rus+kaz+eng", tmp_path)


def test_native_pdf_needs_no_ocr_installation(pdf_factory, tmp_path):
    parsed = parse(
        pdf_factory(),
        PDF,
        "policy.pdf",
        "policy",
        ocr=True,
        ocr_tessdata=tmp_path / "not-installed",
    )
    assert not parsed.needs_ocr
    assert parsed.metadata["ocr_completed_pages"] == []
