"""Synthetic PDF -> OpenAI embeddings API -> local Qdrant -> duplicate check.

Requires OPENAI_API_KEY in .env or the environment. Uses the configured OpenAI model.
Uses a separate DATA_DIR so synthetic fixtures never enter the production collection.
"""

import json

import pymupdf

from ingestion.config import Settings
from ingestion.pipeline import Pipeline


def main():
    configured = Settings()
    if not configured.openai_api_key or not configured.openai_api_key.get_secret_value().strip():
        print(json.dumps({"error": "Set OPENAI_API_KEY in .env before running the API smoke test"}))
        return 1
    data = (configured.data_dir / "smoke-openai").resolve()
    inbox = data / "inbox" / "telegram"
    inbox.mkdir(parents=True, exist_ok=True)
    sample = inbox / "Synthetic Academic Calendar 2026-2027.pdf"
    if not sample.exists():
        with pymupdf.open() as document:
            document.set_metadata({"title": "Synthetic Academic Calendar 2026-2027"})
            page = document.new_page()
            page.insert_text((72, 70), "Synthetic integration test. Not an official KBTU document.")
            page.insert_text((72, 100), "GPA, FX, Retake, Add/Drop and policy number 51-2-25.")
            page.insert_text(
                (72, 130), "This sample only verifies document processing and citations."
            )
            document.save(sample)
    settings = configured.model_copy(
        update={
            "data_dir": data,
            "qdrant_url": None,
            "qdrant_api_key": None,
            "qdrant_collection": "kbtu_smoke_openai",
        }
    )
    with Pipeline(settings) as pipeline:
        first = pipeline.ingest_files([sample], channel="telegram")[0]
        second = pipeline.ingest_files([sample], channel="telegram")[0]
        issues = pipeline.verify()
        report = {
            "first": first.model_dump(),
            "repeat": second.model_dump(),
            "issues": issues,
            "model": settings.embedding_model,
            "qdrant": "persistent local",
            "data_dir": str(data),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return int(
            first.status not in {"processed", "duplicate"}
            or second.status != "duplicate"
            or bool(issues)
        )


if __name__ == "__main__":
    raise SystemExit(main())
