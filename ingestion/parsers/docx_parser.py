from io import BytesIO

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from ingestion.models import Block, BlockKind, ParsedDocument
from ingestion.services.normalizer import normalize


def parse_docx(data: bytes, fallback_title: str) -> ParsedDocument:
    document = Document(BytesIO(data))
    title = document.core_properties.title or fallback_title
    blocks = []
    section = subsection = None
    for item in document.iter_inner_content():
        if isinstance(item, Table):
            text = "\n".join(" | ".join(normalize(c.text) for c in row.cells) for row in item.rows)
            blocks.append(Block(text=text, kind="table", section=section, subsection=subsection))
        elif isinstance(item, Paragraph) and item.text.strip():
            text = normalize(item.text)
            style = item.style.name if item.style else ""
            kind: BlockKind = "paragraph"
            if style == "Title":
                title = text
                kind = "heading"
            elif style.startswith("Heading"):
                if style.endswith("1") or style.endswith("2"):
                    section, subsection = text, None
                else:
                    subsection = text
                kind = "heading"
            elif "List" in style or item._p.xpath("./w:pPr/w:numPr"):
                kind = "list"
            blocks.append(Block(text=text, kind=kind, section=section, subsection=subsection))
    return ParsedDocument(title=title, blocks=blocks)
