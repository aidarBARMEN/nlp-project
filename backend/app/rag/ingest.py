"""UI/CLI bridge to the shared ingestion pipeline and immutable document registry."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

from ingestion.models import IngestResult, Trust
from ingestion.parsers import SUPPORTED_EXTENSIONS
from ingestion.pipeline import Pipeline
from ingestion.services.indexer import Indexer

from ..config import BACKEND_DIR, get_settings
from .knowledge_base import kb
from .llm import MissingAPIKey
from .vector_store import close_vector_store, get_vector_store


@contextmanager
def ingestion_session(*, parse_only: bool | None = None):
    settings = get_settings()
    store = get_vector_store()
    # SQLite connections belong to the worker thread; only the Qdrant client is shared.
    with (
        store.lock,
        Pipeline(
            settings,
            indexer=Indexer(settings, store.client),
            parse_only=(not settings.has_openai_key) if parse_only is None else parse_only,
        ) as pipeline,
    ):
        yield pipeline


def document_info(pipeline: Pipeline, doc) -> dict:
    row = pipeline.registry.row(doc.doc_id)
    artifact_path = pipeline.parsed_path(doc.doc_id)
    artifact = (
        json.loads(artifact_path.read_text(encoding="utf-8")) if artifact_path.exists() else {}
    )
    chunks = artifact.get("chunks", [])
    return {
        "doc_id": doc.doc_id,
        "file_name": doc.original_filename or doc.title,
        "title": doc.title,
        "category": doc.category,
        "academic_year": doc.academic_year,
        "target_audience": doc.target_audience,
        "url": doc.source_url,
        "indexed_at": doc.fetched_at.isoformat(),
        "file_hash": doc.binary_hash,
        "chunks": row["chunks_count"],
        "tokens": sum(c.get("metadata", {}).get("token_count", 0) for c in chunks),
        "pages": len(artifact.get("parsed", {}).get("pages", [])) or None,
        "status": row["status"],
        "trust_level": doc.trust_level,
        "is_current": doc.is_current,
        "source_channel": doc.source_channel,
    }


def list_documents() -> list[dict]:
    with ingestion_session(parse_only=True) as pipeline:
        return sorted(
            [
                document_info(pipeline, doc)
                for doc in pipeline.registry.all()
                if not doc.metadata.get("archived_at")
            ],
            key=lambda doc: doc["title"].lower(),
        )


def get_document_file(doc_id: str) -> tuple[Path, str, str]:
    with ingestion_session(parse_only=True) as pipeline:
        doc = pipeline.registry.get(doc_id)
        if doc.metadata.get("archived_at"):
            raise KeyError(doc_id)
        path = Path(doc.raw_path).resolve()
        if not path.is_relative_to(pipeline.data / "raw") or not path.is_file():
            raise FileNotFoundError("Оригинал документа не найден")
        return path, doc.original_filename or path.name, doc.mime_type


def _result(pipeline: Pipeline, result: IngestResult) -> dict:
    if result.status in {"failed", "needs_ocr"} or not result.doc_id:
        raise ValueError(result.error or "Документ не удалось обработать")
    return document_info(pipeline, pipeline.registry.get(result.doc_id))


def ingest_single(path: Path) -> dict:
    with ingestion_session() as pipeline:
        info = _result(pipeline, pipeline.ingest_file(path, channel="manual_upload"))
        kb.reload()
        return info


def sync_directory(reset: bool = False) -> dict:
    """Import inboxes and index prepared documents. Reindex never drops a collection."""
    settings = get_settings()
    if reset and not settings.has_openai_key:
        raise MissingAPIKey("Для индексации укажите OPENAI_API_KEY в корневом .env.")
    report = {"indexed": [], "skipped": [], "removed": [], "errors": []}
    with ingestion_session() as pipeline:
        for doc in pipeline.registry.all():
            row = pipeline.registry.row(doc.doc_id)
            if doc.metadata.get("archived_at") or row["status"] == "needs_ocr":
                continue
            if settings.has_openai_key and (reset or row["status"] != "processed"):
                try:
                    report["indexed"].append(_result(pipeline, pipeline.reindex(doc.doc_id)))
                except Exception as exc:
                    report["errors"].append(
                        {"file_name": doc.original_filename or doc.title, "error": safe_error(exc)}
                    )
        roots = {
            settings.documents_path,
            settings.data_dir / "inbox" / "telegram",
            BACKEND_DIR / "data" / "documents",
        }
        paths = sorted(
            {
                path.resolve()
                for root in roots
                if root.is_dir()
                for path in root.rglob("*")
                if path.is_file()
                and not path.is_symlink()
                and path.suffix.lower() in SUPPORTED_EXTENSIONS
                and not path.name.startswith(("_", "~$", "."))
            }
        )
        for path in paths:
            try:
                result = pipeline.ingest_file(path)
                if result.status == "duplicate":
                    report["skipped"].append(path.name)
                else:
                    report["indexed"].append(_result(pipeline, result))
            except Exception as exc:
                report["errors"].append({"file_name": path.name, "error": safe_error(exc)})
        pipeline.refresh_current()
        kb.reload()
    return report


def safe_error(exc: Exception) -> str:
    return (
        str(exc) if isinstance(exc, (ValueError, MissingAPIKey)) else "Ошибка обработки документа"
    )


def set_document_trust(doc_id: str, trust: Trust, reason: str) -> dict:
    with ingestion_session(parse_only=True) as pipeline:
        doc = pipeline.registry.get(doc_id)
        if doc.metadata.get("archived_at"):
            raise KeyError(doc_id)
        doc = pipeline.set_trust(doc_id, trust, reason)
        kb.reload()
        return document_info(pipeline, doc)


def remove_document(doc_id: str) -> str | None:
    with ingestion_session(parse_only=True) as pipeline:
        try:
            doc = pipeline.registry.get(doc_id)
        except KeyError:
            return None
        if doc.metadata.get("archived_at"):
            return None
        pipeline.archive(doc_id)
        kb.reload()
        return doc.original_filename or doc.title


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Импорт и индексация общей базы КБТУ")
    parser.add_argument(
        "--reset", action="store_true", help="переиндексировать сохранённые документы"
    )
    args = parser.parse_args()
    try:
        report = sync_directory(reset=args.reset)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(int(bool(report["errors"])))
    finally:
        close_vector_store()
