import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from filelock import FileLock

from ingestion.config import Settings
from ingestion.logging import event
from ingestion.models import (
    CanonicalDocument,
    Channel,
    Chunk,
    IngestResult,
    ParsedDocument,
    Trust,
    utcnow,
)
from ingestion.parsers import detect_mime, parse
from ingestion.registry import Registry
from ingestion.services.chunker import Chunker
from ingestion.services.embedder import Embedder, create_embedder
from ingestion.services.indexer import Indexer
from ingestion.services.metadata import extract
from ingestion.services.normalizer import sha256
from ingestion.services.versioning import TRUST_RANK, current_version
from ingestion.storage import save_raw, write_json


class Pipeline:
    def __init__(
        self,
        settings: Settings,
        *,
        embedder: Embedder | None = None,
        indexer: Indexer | None = None,
        parse_only: bool = False,
    ):
        self.settings = settings
        self.data = settings.data_dir.resolve()
        self.data.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(str(self.data / ".ingestion.lock"), timeout=60)
        self.registry = Registry(self.data / "registry.sqlite3")
        self._embedder = embedder
        self._indexer = indexer
        self.parse_only = parse_only

    @property
    def indexer(self) -> Indexer:
        if self._indexer is None:
            self._indexer = Indexer(self.settings)
        return self._indexer

    @property
    def embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = create_embedder(self.settings)
        return self._embedder

    def parsed_path(self, doc_id: str) -> Path:
        # Public CLI identifiers must resolve through registry before reaching this helper.
        return self.data / "parsed" / f"{doc_id}.json"

    def _artifact(self, doc_id: str):
        return json.loads(self.parsed_path(doc_id).read_text(encoding="utf-8"))

    def _reconcile(self, key: str) -> None:
        docs = [
            d
            for d in self.registry.family(key)
            if self.registry.row(d.doc_id)["status"] == "processed"
        ]
        winner = current_version(docs)
        old = next(
            (d for d in docs if d.is_current and (not winner or d.doc_id != winner.doc_id)), None
        )
        for doc in docs:
            doc.is_current = bool(winner and winner.doc_id == doc.doc_id)
            if doc.is_current and old:
                doc.supersedes_doc_id = old.doc_id
                event("DOCUMENT_VERSION_CHANGED", doc_id=doc.doc_id, supersedes=old.doc_id)
            row = self.registry.row(doc.doc_id)
            self.registry.save(doc, "processed", row["chunks_count"], dirty=True)
        # Fail-closed publication: disable superseded entries before activating the new version.
        for doc in sorted(docs, key=lambda d: d.is_current):
            self.indexer.sync_metadata(doc)
            self.registry.save(
                doc, "processed", self.registry.row(doc.doc_id)["chunks_count"], dirty=False
            )

    def refresh_current(self):
        with self.lock:
            for key in {d.logical_document_key for d in self.registry.all()}:
                self._reconcile(key)

    def _index(self, doc: CanonicalDocument, parsed: ParsedDocument, chunks: list[Chunk]):
        self.indexer.ensure(self.embedder.dimension)
        self.registry.save(doc, "processing", len(chunks))
        self.indexer.upsert(doc, chunks, self.embedder)
        event("QDRANT_UPSERT", doc_id=doc.doc_id, chunks_count=len(chunks))
        self.registry.save(doc, "processed", len(chunks))
        self._reconcile(doc.logical_document_key)

    def _observe(
        self,
        doc: CanonicalDocument,
        source: str,
        binary: str,
        provenance: dict,
        channel: Channel,
        url: str | None,
    ):
        self.registry.observe(
            doc.doc_id,
            source,
            binary,
            {
                **provenance,
                "source_channel": channel,
                "source_url": url,
                "observed_at": utcnow().isoformat(),
            },
        )
        if channel == "kbtu_website" and TRUST_RANK[doc.trust_level] < TRUST_RANK["official"]:
            doc.trust_level = "official"
            # Preserve all earlier provenance in document_sources.
            doc.source_url, doc.source_channel = url, channel
            row = self.registry.row(doc.doc_id)
            self.registry.save(doc, row["status"], row["chunks_count"])
        if self.registry.row(doc.doc_id)["status"] == "processed" and not self.parse_only:
            self._reconcile(doc.logical_document_key)

    def ingest_bytes(
        self,
        data: bytes,
        *,
        filename: str,
        source: str,
        channel: Channel = "manual_upload",
        source_url: str | None = None,
        provenance: dict | None = None,
        overrides: dict | None = None,
    ) -> IngestResult:
        attempt_id = str(uuid4())
        doc = None
        raw_path = None
        binary = sha256(data)
        provenance = provenance or {}
        with self.lock:
            event("INGEST_START", attempt_id=attempt_id, binary_hash=binary)
            try:
                if len(data) > self.settings.max_file_mb * 1024 * 1024:
                    raise ValueError("File exceeds MAX_FILE_MB")
                if channel == "kbtu_website":
                    from ingestion.crawler.filters import in_scope

                    if not source_url or not in_scope(source_url):
                        raise ValueError("Website source must be an allowed public KBTU URL")
                extension = Path(filename).suffix.lower()
                extension = (
                    extension if extension in {".pdf", ".docx", ".doc", ".html", ".htm"} else ".bin"
                )
                raw_path = self.data / "raw" / channel / f"{binary}{extension}"
                save_raw(raw_path, data)
                provenance = {
                    **provenance,
                    "raw_path": str(raw_path),
                    "original_filename": filename,
                }
                duplicate = self.registry.duplicate(binary)
                if duplicate and self.registry.row(duplicate.doc_id)["status"] in (
                    {"processed", "pending"} if self.parse_only else {"processed"}
                ):
                    doc = duplicate
                    self._observe(duplicate, source, binary, provenance, channel, source_url)
                    result = IngestResult(
                        source=source,
                        doc_id=duplicate.doc_id,
                        status="duplicate",
                        chunks_count=self.registry.row(duplicate.doc_id)["chunks_count"],
                    )
                    event("DOCUMENT_DUPLICATE", doc_id=duplicate.doc_id, reason="binary_hash")
                else:
                    mime = detect_mime(data)
                    parsed = parse(
                        data,
                        mime,
                        filename,
                        source,
                        ocr=self.settings.ocr_enabled,
                        ocr_languages=self.settings.ocr_languages,
                    )
                    event("DOCUMENT_PARSED", attempt_id=attempt_id, pages_count=len(parsed.pages))
                    doc = extract(
                        parsed,
                        filename=filename,
                        channel=channel,
                        mime=mime,
                        binary_hash=binary,
                        doc_id=str(uuid5(NAMESPACE_URL, f"kbtu/{binary}")),
                        raw_path=str(raw_path),
                        source_url=source_url,
                        overrides=overrides,
                    )
                    doc.metadata["provenance"] = provenance
                    duplicate = self.registry.duplicate(
                        binary, doc.content_hash if parsed.blocks and not parsed.needs_ocr else None
                    )
                    if duplicate and self.registry.row(duplicate.doc_id)["status"] in (
                        {"processed", "pending"} if self.parse_only else {"processed"}
                    ):
                        self._observe(duplicate, source, binary, provenance, channel, source_url)
                        result = IngestResult(
                            source=source,
                            doc_id=duplicate.doc_id,
                            status="duplicate",
                            chunks_count=self.registry.row(duplicate.doc_id)["chunks_count"],
                        )
                        event("DOCUMENT_DUPLICATE", doc_id=duplicate.doc_id, reason="content_hash")
                        doc = duplicate
                    else:
                        previous = self.registry.family(doc.logical_document_key)
                        if duplicate:
                            # Retry retains identity, administrative trust and declared metadata.
                            if duplicate.binary_hash != binary:
                                # Page citations must still refer to the retained original.
                                parsed = ParsedDocument.model_validate(
                                    self._artifact(duplicate.doc_id)["parsed"]
                                )
                            doc = duplicate
                        if not parsed.blocks and not parsed.needs_ocr:
                            raise ValueError("No useful document content found")
                        if parsed.needs_ocr:
                            chunks = []
                        else:
                            chunks = Chunker(
                                self.settings.chunk_tokens, self.settings.chunk_overlap
                            ).chunks(doc, parsed)
                        write_json(
                            self.parsed_path(doc.doc_id),
                            {
                                "document": doc.model_dump(mode="json"),
                                "parsed": parsed.model_dump(mode="json"),
                                "chunks": [c.model_dump(mode="json") for c in chunks],
                            },
                        )
                        target_status = (
                            "needs_ocr"
                            if parsed.needs_ocr
                            else "pending"
                            if self.parse_only
                            else "processing"
                        )
                        self.registry.save(doc, target_status, len(chunks))
                        self.registry.observe(doc.doc_id, source, binary, provenance)
                        if not parsed.needs_ocr and not self.parse_only:
                            event("CHUNKS_CREATED", doc_id=doc.doc_id, count=len(chunks))
                            self._index(doc, parsed, chunks)
                        result = IngestResult(
                            source=source,
                            doc_id=doc.doc_id,
                            status="needs_ocr"
                            if parsed.needs_ocr
                            else "pending"
                            if self.parse_only
                            else "processed",
                            error="PDF needs OCR; enable OCR_ENABLED and Tesseract language packs"
                            if parsed.needs_ocr
                            else None,
                            pages_count=len(parsed.pages),
                            chunks_count=len(chunks),
                            updated=any(d.doc_id != doc.doc_id for d in previous),
                        )
            except Exception as exc:
                # Network/model exceptions may contain credentials: only log their type.
                error = (
                    str(exc)
                    if isinstance(exc, (ValueError, FileNotFoundError))
                    else f"{type(exc).__name__}: check configuration and source format"
                )
                result = IngestResult(
                    source=source, doc_id=doc.doc_id if doc else None, status="failed", error=error
                )
                event("INGEST_FAILED", attempt_id=attempt_id, error_type=type(exc).__name__)
            manifest = {
                **result.model_dump(),
                "attempt_id": attempt_id,
                "original_path": source,
                "raw_path": str(raw_path) if raw_path else None,
                "binary_hash": binary,
                "content_hash": doc.content_hash if doc else None,
                "parser_version": "1",
                "ingested_at": utcnow().isoformat(),
                "provenance": provenance,
            }
            write_json(self.data / "manifests" / f"{attempt_id}.json", manifest)
            if result.status in {"processed", "duplicate", "pending"}:
                event("INGEST_SUCCESS", doc_id=result.doc_id, status=result.status)
            return result

    def ingest_file(
        self, path: Path, channel: Channel | None = None, overrides: dict | None = None
    ) -> IngestResult:
        path = path.resolve()
        channel = channel or (
            "telegram" if "telegram" in [p.lower() for p in path.parts] else "manual_upload"
        )
        event("SOURCE_DISCOVERED", source_channel=channel)
        try:
            if path.stat().st_size > self.settings.max_file_mb * 1024 * 1024:
                raise ValueError("File exceeds MAX_FILE_MB")
            result = self.ingest_bytes(
                path.read_bytes(),
                filename=path.name,
                source=str(path),
                channel=channel,
                overrides=overrides,
            )
            if result.status in {"processed", "duplicate"}:
                # The inbox is left untouched; a persistent marker records completion.
                marker = sha256(str(path).encode())
                write_json(self.data / "processed" / f"{marker}.json", result.model_dump())
            return result
        except (OSError, ValueError) as exc:
            result = IngestResult(source=str(path), status="failed", error=str(exc))
            write_json(self.data / "manifests" / f"{uuid4()}.json", result.model_dump())
            return result

    def ingest_files(
        self, paths: list[Path], *, channel: Channel | None = None, overrides: dict | None = None
    ) -> list[IngestResult]:
        run_id = str(uuid4())
        with self.lock:
            self.registry.start_run(run_id, channel or "local_files")
            results = [
                self.ingest_file(path, channel=channel, overrides=overrides) for path in paths
            ]
            self.registry.finish_run(run_id, results)
        return results

    def reindex(self, doc_id: str) -> IngestResult:
        with self.lock:
            doc = self.registry.get(doc_id)
            artifact = self._artifact(doc_id)
            parsed = ParsedDocument.model_validate(artifact["parsed"])
            if parsed.needs_ocr:
                raise ValueError("Document needs OCR; re-ingest the original with OCR_ENABLED=true")
            chunks = Chunker(self.settings.chunk_tokens, self.settings.chunk_overlap).chunks(
                doc, parsed
            )
            write_json(
                self.parsed_path(doc_id),
                {
                    "document": doc.model_dump(mode="json"),
                    "parsed": parsed.model_dump(mode="json"),
                    "chunks": [c.model_dump(mode="json") for c in chunks],
                },
            )
            self._index(doc, parsed, chunks)
            return IngestResult(
                source=doc.raw_path,
                doc_id=doc_id,
                status="processed",
                chunks_count=len(chunks),
                pages_count=len(parsed.pages),
            )

    def set_trust(self, doc_id: str, trust: Trust, reason: str):
        with self.lock:
            doc = self.registry.get(doc_id)
            doc.trust_level = trust
            doc.metadata.setdefault("trust_audit", []).append(
                {"trust_level": trust, "reason": reason, "at": utcnow().isoformat()}
            )
            row = self.registry.row(doc_id)
            self.registry.save(doc, row["status"], row["chunks_count"])
            self._reconcile(doc.logical_document_key)
            return self.registry.get(doc_id)

    def verify(self) -> list[dict]:
        issues = []
        with self.lock:
            docs = self.registry.all()
            for doc in docs:
                row = self.registry.row(doc.doc_id)
                raw = Path(doc.raw_path)
                if not raw.exists() or sha256(raw.read_bytes()) != doc.binary_hash:
                    issues.append({"doc_id": doc.doc_id, "issue": "raw_hash_mismatch"})
                if row["status"] != "processed":
                    issues.append({"doc_id": doc.doc_id, "issue": row["status"]})
                    continue
                points = self.indexer.points(doc.doc_id)
                artifact = self._artifact(doc.doc_id)
                if {str(p.id) for p in points} != {c["chunk_id"] for c in artifact["chunks"]}:
                    issues.append({"doc_id": doc.doc_id, "issue": "chunk_ids_mismatch"})
                if row["index_dirty"] or any(
                    (p.payload or {}).get("is_current") != doc.is_current
                    or (p.payload or {}).get("trust_level") != doc.trust_level
                    or (p.payload or {}).get("index_status") != "ready"
                    for p in points
                ):
                    issues.append({"doc_id": doc.doc_id, "issue": "payload_out_of_sync"})
            for key in {d.logical_document_key for d in docs}:
                family = [
                    d
                    for d in docs
                    if d.logical_document_key == key
                    and self.registry.row(d.doc_id)["status"] == "processed"
                ]
                winner = current_version(family)
                if {d.doc_id for d in family if d.is_current} != (
                    {winner.doc_id} if winner else set()
                ):
                    issues.append({"logical_document_key": key, "issue": "current_selection_stale"})
        return issues

    def close(self):
        self.registry.close()
        if self._indexer:
            self._indexer.close()
        close_embedder = getattr(self._embedder, "close", None)
        if close_embedder:
            close_embedder()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
