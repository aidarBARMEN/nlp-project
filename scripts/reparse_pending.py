"""Refresh prepared (not published) artifacts after a parser upgrade. No models/network."""

from pathlib import Path

from ingestion.config import Settings
from ingestion.models import utcnow
from ingestion.parsers import parse
from ingestion.pipeline import Pipeline
from ingestion.services.chunker import Chunker
from ingestion.services.normalizer import content_hash
from ingestion.storage import write_json


def main():
    settings = Settings()
    with Pipeline(settings, parse_only=True) as pipeline, pipeline.lock:
        for doc in pipeline.registry.all():
            if pipeline.registry.row(doc.doc_id)["status"] != "pending":
                continue
            parsed = parse(
                Path(doc.raw_path).read_bytes(),
                doc.mime_type,
                doc.original_filename or doc.doc_id,
                doc.source_url or doc.raw_path,
                ocr=settings.ocr_enabled,
                ocr_languages=settings.ocr_languages,
            )
            doc.content_hash = content_hash("\n".join(b.text for b in parsed.blocks))
            chunks = (
                []
                if parsed.needs_ocr
                else Chunker(settings.chunk_tokens, settings.chunk_overlap).chunks(doc, parsed)
            )
            write_json(
                pipeline.parsed_path(doc.doc_id),
                {
                    "document": doc.model_dump(mode="json"),
                    "parsed": parsed.model_dump(mode="json"),
                    "chunks": [c.model_dump(mode="json") for c in chunks],
                },
            )
            status = "needs_ocr" if parsed.needs_ocr else "pending"
            pipeline.registry.save(doc, status, len(chunks))
            write_json(
                pipeline.data / "manifests" / f"reparse-{doc.doc_id}.json",
                {
                    "doc_id": doc.doc_id,
                    "source": doc.source_url or doc.raw_path,
                    "status": status,
                    "binary_hash": doc.binary_hash,
                    "content_hash": doc.content_hash,
                    "parser_version": parsed.parser_version,
                    "ingested_at": utcnow().isoformat(),
                    "chunks_count": len(chunks),
                    "pages_count": len(parsed.pages),
                    "error": None,
                },
            )
            print(f"{doc.doc_id}: {status}, chunks={len(chunks)}")


if __name__ == "__main__":
    main()
