from itertools import groupby
from uuid import NAMESPACE_URL, uuid5

import tiktoken

from ingestion.models import CanonicalDocument, Chunk, ParsedDocument
from ingestion.services.normalizer import redact


class Chunker:
    def __init__(self, size=700, overlap=100):
        self.size = size
        self.overlap = overlap
        self.encoding = tiktoken.get_encoding("cl100k_base")

    def count(self, text: str) -> int:
        return len(self.encoding.encode(text, disallowed_special=()))

    def split_long(self, text: str) -> list[str]:
        tokens = self.encoding.encode(text, disallowed_special=())
        result = []
        start = 0
        while start < len(tokens):
            end = min(start + self.size, len(tokens))
            while end > start:
                try:
                    value = self.encoding.decode(tokens[start:end], errors="strict")
                    break
                except UnicodeDecodeError:
                    end -= 1
            result.append(value)
            if end == len(tokens):
                break
            start = max(start + 1, end - self.overlap)
            while start < end:
                try:
                    self.encoding.decode(tokens[start:end], errors="strict")
                    break
                except UnicodeDecodeError:
                    start += 1
        return result

    def chunks(self, doc: CanonicalDocument, parsed: ParsedDocument) -> list[Chunk]:
        chunks: list[Chunk] = []
        parents = {}
        for group_index, (key, group) in enumerate(
            groupby(parsed.blocks, key=lambda b: (b.section, b.subsection, b.page_number))
        ):
            section, subsection, page = key
            blocks = list(group)
            parent_id = str(uuid5(NAMESPACE_URL, f"{doc.doc_id}/parent/{group_index}"))
            parents[parent_id] = {
                "text": redact("\n\n".join(b.text for b in blocks)),
                "section": section,
                "subsection": subsection,
                "page_start": page,
                "page_end": page,
            }
            units = []
            for block in blocks:
                value = redact(block.text)
                if block.kind == "table" and self.count(value) > self.size:
                    rows = value.splitlines()
                    header = rows[0]
                    for row in rows[1:]:
                        units.extend(self.split_long(header + "\n" + row))
                else:
                    units.extend(self.split_long(value))
            pieces: list[str] = []
            current: list[str] = []
            for unit in units:
                if current and self.count("\n\n".join([*current, unit])) > self.size:
                    pieces.append("\n\n".join(current))
                    tail: list[str] = []
                    for part in reversed(current):
                        if self.count("\n\n".join([part, *tail])) > self.overlap:
                            break
                        tail.insert(0, part)
                    current = tail if self.count("\n\n".join([*tail, unit])) <= self.size else []
                current.append(unit)
            if current:
                pieces.append("\n\n".join(current))
            for text in pieces:
                chunks.append(
                    Chunk(
                        chunk_id=str(uuid5(NAMESPACE_URL, f"{doc.doc_id}/chunk/{len(chunks)}")),
                        doc_id=doc.doc_id,
                        text=text,
                        title=redact(doc.title),
                        section=redact(section) if section else None,
                        subsection=redact(subsection) if subsection else None,
                        page_start=page,
                        page_end=page,
                        language=doc.language,
                        source_url=doc.source_url,
                        source_channel=doc.source_channel,
                        academic_year=doc.academic_year,
                        version=doc.version,
                        is_current=doc.is_current,
                        trust_level=doc.trust_level,
                        parent_chunk_id=parent_id,
                        metadata={
                            "token_count": self.count(text),
                            "tokenizer": "cl100k_base",
                            "document_number": doc.document_number,
                            "category": doc.category,
                            "target_audience": doc.target_audience,
                        },
                    )
                )
        parsed.metadata["parents"] = parents
        return chunks
