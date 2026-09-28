from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from ingestion.models import ParsedDocument
from ingestion.parsers.docx_parser import parse_docx
from ingestion.parsers.html_parser import parse_html
from ingestion.parsers.pdf_parser import parse_pdf

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def detect_mime(data: bytes) -> str:
    if data.lstrip().startswith(b"%PDF-"):
        return PDF
    if data.startswith(b"PK"):
        try:
            with ZipFile(BytesIO(data)) as archive:
                if "word/document.xml" in archive.namelist():
                    if sum(i.file_size for i in archive.infolist()) > 200 * 1024 * 1024:
                        raise ValueError("DOCX expanded size exceeds 200 MB")
                    return DOCX
        except BadZipFile as exc:
            raise ValueError("Broken ZIP/DOCX") from exc
    if data.startswith(bytes.fromhex("d0cf11e0a1b11ae1")):
        return "application/msword"
    head = data[:8192].lstrip().lower()
    if any(tag in head for tag in (b"<!doctype html", b"<html", b"<body", b"<article")):
        return "text/html"
    raise ValueError("Unsupported or damaged file: expected PDF, DOCX or HTML")


def parse(
    data: bytes, mime: str, filename: str, source: str, *, ocr=False, ocr_languages="rus+kaz+eng"
) -> ParsedDocument:
    if mime == PDF:
        return parse_pdf(data, Path(filename).stem, source, ocr=ocr, languages=ocr_languages)
    if mime == DOCX:
        return parse_docx(data, Path(filename).stem)
    if mime == "text/html":
        return parse_html(data, source)
    raise ValueError("Legacy .doc is archived but requires conversion to DOCX (LibreOffice)")
