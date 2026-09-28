import os
import statistics

import pymupdf

# Keep CLI stdout machine-readable on versions that print a layout recommendation.
os.environ.setdefault("PYMUPDF_SUGGEST_LAYOUT_ANALYZER", "0")

from ingestion.models import Block, Page, ParsedDocument
from ingestion.services.normalizer import normalize


def parse_pdf(
    data: bytes, fallback_title: str, source: str, *, ocr=False, languages="rus+kaz+eng"
) -> ParsedDocument:
    blocks = []
    pages = []
    missing = []
    section = None
    with pymupdf.open(stream=data, filetype="pdf") as document:
        if document.needs_pass:
            raise ValueError("Encrypted PDF requires a password-free copy")
        title = (document.metadata or {}).get("title") or fallback_title
        for page in document:
            text = page.get_text(sort=True)
            textpage = None
            if len(text.strip()) < 20 and page.get_images():
                if ocr:
                    textpage = page.get_textpage_ocr(language=languages, dpi=200, full=True)
                    text = page.get_text(textpage=textpage, sort=True)
                if len(text.strip()) < 20:
                    missing.append(page.number + 1)
            pages.append(
                Page(
                    page_number=page.number + 1,
                    text=normalize(text),
                    document_title=title,
                    source=source,
                )
            )
            table_rects = []
            entries = []
            if textpage is None and text.strip():
                for table in page.find_tables().tables:
                    table_rects.append(pymupdf.Rect(table.bbox))
                    entries.append(
                        (
                            table.bbox[1],
                            Block(
                                text=table.to_markdown(), kind="table", page_number=page.number + 1
                            ),
                        )
                    )
            layout = page.get_text("dict", textpage=textpage, sort=True)
            sizes = [
                s["size"]
                for b in layout["blocks"]
                if "lines" in b
                for line in b["lines"]
                for s in line["spans"]
                if s["text"].strip()
            ]
            normal_size = statistics.median(sizes) if sizes else 12
            for block in layout["blocks"]:
                if "lines" not in block:
                    continue
                rect = pymupdf.Rect(block["bbox"])
                if any((rect & r).get_area() / max(rect.get_area(), 1) > 0.6 for r in table_rects):
                    continue
                spans = [s for line in block["lines"] for s in line["spans"]]
                value = normalize(
                    "\n".join("".join(s["text"] for s in line["spans"]) for line in block["lines"])
                )
                heading = len(value) < 180 and any(s["size"] > normal_size * 1.15 for s in spans)
                if value:
                    entries.append(
                        (
                            rect.y0,
                            Block(
                                text=value,
                                kind="heading" if heading else "paragraph",
                                page_number=page.number + 1,
                            ),
                        )
                    )
            for _, block in sorted(entries, key=lambda pair: pair[0]):
                if block.kind == "heading":
                    section = block.text
                block.section = section
                blocks.append(block)
    needs_ocr = bool(missing) or not any(b.text.strip() for b in blocks)
    return ParsedDocument(
        title=title,
        blocks=blocks,
        pages=pages,
        needs_ocr=needs_ocr,
        metadata={"ocr_pages": missing},
    )
