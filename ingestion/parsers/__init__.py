from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from ingestion.models import ParsedDocument
from ingestion.parsers.docx_parser import parse_docx
from ingestion.parsers.html_parser import parse_html
from ingestion.parsers.office_text import parse_csv, parse_text, parse_xlsx
from ingestion.parsers.pdf_parser import parse_pdf

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".html",
    ".htm",
    ".md",
    ".markdown",
    ".txt",
    ".xlsx",
    ".csv",
}


def detect_mime(data: bytes, filename: str = "") -> str:
    if data.lstrip().startswith(b"%PDF-"):
        return PDF
    if data.startswith(b"PK"):
        try:
            with ZipFile(BytesIO(data)) as archive:
                if sum(i.file_size for i in archive.infolist()) > 200 * 1024 * 1024:
                    raise ValueError("Office archive expanded size exceeds 200 MB")
                if "word/document.xml" in archive.namelist():
                    return DOCX
                if "xl/workbook.xml" in archive.namelist():
                    return XLSX
        except BadZipFile as exc:
            raise ValueError("Broken ZIP/DOCX") from exc
    if data.startswith(bytes.fromhex("d0cf11e0a1b11ae1")):
        return "application/msword"
    head = data[:8192].lstrip().lower()
    if any(tag in head for tag in (b"<!doctype html", b"<html", b"<body", b"<article")):
        return "text/html"
    suffix = Path(filename).suffix.lower()
    if suffix in {".txt", ".md", ".markdown", ".csv"}:
        text = data.decode("utf-8-sig")
        if any(ord(char) < 32 and char not in "\t\r\n" for char in text):
            raise ValueError("Text file contains binary control characters")
        return "text/csv" if suffix == ".csv" else "text/plain"
    raise ValueError("Unsupported or damaged document format")


def parse(
    data: bytes, mime: str, filename: str, source: str, *, ocr=False, ocr_languages="rus+kaz+eng"
) -> ParsedDocument:
    if mime == PDF:
        return parse_pdf(data, Path(filename).stem, source, ocr=ocr, languages=ocr_languages)
    if mime == DOCX:
        return parse_docx(data, Path(filename).stem)
    if mime == "text/html":
        return parse_html(data, source)
    if mime == "text/plain":
        return parse_text(data, Path(filename).stem)
    if mime == "text/csv":
        return parse_csv(data, Path(filename).stem)
    if mime == XLSX:
        return parse_xlsx(data, Path(filename).stem)
    raise ValueError("Legacy .doc is archived but requires conversion to DOCX (LibreOffice)")
