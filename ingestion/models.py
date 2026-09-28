from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Trust = Literal["official", "verified_internal", "unverified"]
Channel = Literal["kbtu_website", "telegram", "manual_upload", "internal_kbtu"]
Status = Literal["pending", "processing", "processed", "duplicate", "needs_ocr", "failed"]
BlockKind = Literal["paragraph", "heading", "list", "table"]


def utcnow() -> datetime:
    return datetime.now(UTC)


class Block(BaseModel):
    text: str
    kind: BlockKind = "paragraph"
    section: str | None = None
    subsection: str | None = None
    page_number: int | None = None


class Page(BaseModel):
    page_number: int
    text: str
    document_title: str
    source: str


class ParsedDocument(BaseModel):
    title: str
    blocks: list[Block]
    pages: list[Page] = Field(default_factory=list)
    needs_ocr: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    parser_version: str = "1"


class CanonicalDocument(BaseModel):
    doc_id: str
    logical_document_key: str
    title: str
    source_type: str = "unknown"
    source_channel: Channel
    source_url: str | None = None
    original_filename: str | None = None
    mime_type: str
    language: str | None = None
    category: str | None = None
    section: str | None = None
    target_audience: str | None = None
    academic_year: str | None = None
    document_number: str | None = None
    version: str | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    fetched_at: datetime = Field(default_factory=utcnow)
    binary_hash: str
    content_hash: str
    is_current: bool = False
    supersedes_doc_id: str | None = None
    trust_level: Trust = "unverified"
    raw_path: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class Chunk(BaseModel):
    chunk_id: str
    doc_id: str
    text: str
    title: str
    section: str | None = None
    subsection: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    language: str | None = None
    source_url: str | None = None
    source_channel: Channel
    academic_year: str | None = None
    version: str | None = None
    is_current: bool = False
    trust_level: Trust
    parent_chunk_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestResult(BaseModel):
    source: str
    doc_id: str | None = None
    status: Status
    error: str | None = None
    chunks_count: int = 0
    pages_count: int = 0
    updated: bool = False
