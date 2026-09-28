import json
from datetime import date

import pytest

from ingestion.models import Block, ParsedDocument
from ingestion.services.chunker import Chunker
from ingestion.services.indexer import knowledge_filter
from ingestion.services.normalizer import content_hash
from ingestion.services.versioning import current_version


def ingest(pipeline, data, filename="Academic Policy 2026.pdf", channel="manual_upload"):
    return pipeline.ingest_bytes(
        data,
        filename=filename,
        source=filename,
        channel=channel,
        source_url="https://kbtu.edu.kz/files/policy.pdf" if channel == "kbtu_website" else None,
    )


def test_ingest_same_file_twice(pipeline, pdf_factory):
    data = pdf_factory()
    first = ingest(pipeline, data)
    second = ingest(pipeline, data)
    assert first.status == "processed", first.error
    assert second.status == "duplicate"
    assert first.doc_id == second.doc_id
    assert len(pipeline.registry.all()) == 1
    assert len(pipeline.indexer.points(first.doc_id)) == first.chunks_count
    assert pipeline.verify() == []


def test_hash_deduplication(pipeline, pdf_factory):
    assert content_hash("Some  text\nnext") == content_hash("Some text next")
    first = ingest(pipeline, pdf_factory())
    second = ingest(pipeline, pdf_factory(), filename="renamed.pdf")
    assert second.status == "duplicate"
    assert first.doc_id == second.doc_id
    assert pipeline.registry.db.execute("SELECT count(*) FROM document_sources").fetchone()[0] == 2


def test_chunk_metadata_and_page_numbers_preserved(pipeline, pdf_factory):
    result = ingest(pipeline, pdf_factory(), channel="telegram")
    points = pipeline.indexer.points(result.doc_id)
    assert {p.payload["page_start"] for p in points} == {1, 2}
    for p in points:
        assert p.payload["trust_level"] == "unverified"
        assert p.payload["parent_chunk_id"]
        assert p.payload["source_channel"] == "telegram"
        assert p.payload["title"] == "Academic Policy 2026"
    artifact = json.loads(pipeline.parsed_path(result.doc_id).read_text(encoding="utf-8"))
    assert all(
        p.payload["parent_chunk_id"] in artifact["parsed"]["metadata"]["parents"] for p in points
    )


def test_version_detection(pipeline, pdf_factory):
    old = ingest(
        pipeline,
        pdf_factory("Academic Policy 2025", "Previous official policy applies."),
        "Academic Policy 2025.pdf",
        "kbtu_website",
    )
    new = ingest(pipeline, pdf_factory(), channel="kbtu_website")
    assert new.updated
    assert not pipeline.registry.get(old.doc_id).is_current
    assert pipeline.registry.get(new.doc_id).is_current
    assert pipeline.registry.get(new.doc_id).supersedes_doc_id == old.doc_id
    assert pipeline.indexer.points(old.doc_id)
    assert all(not p.payload["is_current"] for p in pipeline.indexer.points(old.doc_id))
    assert pipeline.verify() == []


def test_unverified_document_does_not_replace_official(pipeline, pdf_factory):
    official = ingest(
        pipeline,
        pdf_factory("Academic Policy 2025", "Official rules for students."),
        "policy2025.pdf",
        "kbtu_website",
    )
    candidate = ingest(pipeline, pdf_factory(), channel="telegram")
    assert pipeline.registry.get(official.doc_id).is_current
    assert not pipeline.registry.get(candidate.doc_id).is_current
    pipeline.set_trust(candidate.doc_id, "official", "Verified by administrator")
    assert pipeline.registry.get(candidate.doc_id).is_current
    assert not pipeline.registry.get(official.doc_id).is_current
    assert pipeline.verify() == []


def test_current_version_selection(pipeline, pdf_factory):
    result = ingest(pipeline, pdf_factory(), channel="kbtu_website")
    doc = pipeline.registry.get(result.doc_id)
    old = doc.model_copy(update={"doc_id": "old", "version": "2024"})
    future = doc.model_copy(update={"doc_id": "future", "effective_from": date(2099, 1, 1)})
    assert current_version([future, old, doc]).doc_id == doc.doc_id
    assert current_version([future]) is None


def test_older_import_does_not_supersede_newer(pipeline, pdf_factory):
    new = ingest(pipeline, pdf_factory(), channel="kbtu_website")
    old = ingest(
        pipeline,
        pdf_factory("Academic Policy 2024", "Rules from the old policy."),
        "Academic Policy 2024.pdf",
        "kbtu_website",
    )
    assert pipeline.registry.get(new.doc_id).is_current
    assert not pipeline.registry.get(old.doc_id).is_current


def test_broken_pdf_does_not_break_batch(pipeline, pdf_factory, tmp_path):
    bad, good = tmp_path / "bad.pdf", tmp_path / "good.pdf"
    bad.write_bytes(b"%PDF-1.7\nbroken")
    good.write_bytes(pdf_factory())
    results = pipeline.ingest_files([bad, good], channel="telegram")
    assert [r.status for r in results] == ["failed", "processed"]
    assert pipeline.registry.runs()[0]["failed"] == 1
    assert len(list((pipeline.data / "manifests").glob("*.json"))) == 2


def test_failure_recovery(pipeline, pdf_factory, monkeypatch):
    data = pdf_factory()
    real = pipeline.indexer.sync_metadata
    monkeypatch.setattr(
        pipeline.indexer,
        "sync_metadata",
        lambda doc: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    first = ingest(pipeline, data)
    assert first.status == "failed"
    assert pipeline.verify()
    monkeypatch.setattr(pipeline.indexer, "sync_metadata", real)
    retry = ingest(pipeline, data)
    assert retry.status == "duplicate"
    assert pipeline.verify() == []


def test_partial_upsert_retry(pipeline, pdf_factory, monkeypatch):
    real = pipeline.indexer.upsert

    def fail_after_upsert(*args):
        real(*args)
        raise RuntimeError("connection dropped after write")

    monkeypatch.setattr(pipeline.indexer, "upsert", fail_after_upsert)
    data = pdf_factory()
    assert ingest(pipeline, data).status == "failed"
    monkeypatch.setattr(pipeline.indexer, "upsert", real)
    retry = ingest(pipeline, data)
    assert retry.status == "processed"
    assert pipeline.verify() == []


def test_official_duplicate_promotes_provenance(pipeline, pdf_factory):
    data = pdf_factory()
    first = ingest(pipeline, data, channel="telegram")
    second = ingest(pipeline, data, channel="kbtu_website")
    assert second.status == "duplicate"
    doc = pipeline.registry.get(first.doc_id)
    assert doc.trust_level == "official"
    assert doc.source_url == "https://kbtu.edu.kz/files/policy.pdf"
    assert pipeline.verify() == []


def test_reindex_and_filters(pipeline, pdf_factory):
    result = ingest(pipeline, pdf_factory(), channel="kbtu_website")
    pipeline.reindex(result.doc_id)
    points, _ = pipeline.indexer.client.scroll(
        pipeline.indexer.collection,
        scroll_filter=knowledge_filter(category="academic_policy", language="en"),
    )
    assert len(points) == result.chunks_count
    assert pipeline.verify() == []


def test_unverified_excluded_by_default_filter(pipeline, pdf_factory):
    ingest(pipeline, pdf_factory(), channel="telegram")
    points, _ = pipeline.indexer.client.scroll(
        pipeline.indexer.collection, scroll_filter=knowledge_filter()
    )
    assert points == []


def test_embedding_model_mismatch_rejected(pipeline, pdf_factory):
    result = ingest(pipeline, pdf_factory())
    pipeline.settings.embedding_model = "different/model"
    with pytest.raises(ValueError, match="Embedding model changed"):
        pipeline.reindex(result.doc_id)


def test_large_unicode_chunks_are_bounded(pipeline, pdf_factory):
    result = ingest(pipeline, pdf_factory())
    doc = pipeline.registry.get(result.doc_id)
    chunker = Chunker(128, 20)
    parsed = ParsedDocument(
        title="Rules",
        blocks=[Block(text="Қазақстанның студенттері. " * 300, section="Rules", page_number=4)],
    )
    chunks = chunker.chunks(doc, parsed)
    assert len(chunks) > 2
    assert all(chunker.count(c.text) <= 128 and "�" not in c.text for c in chunks)
    assert all(c.page_start == 4 and c.section == "Rules" for c in chunks)


def test_pii_redacted_from_vectors(pipeline, pdf_factory):
    result = ingest(
        pipeline,
        pdf_factory(text="Email: student@example.com Student ID: 12345678 Phone: +7 701 123 45 67"),
    )
    payload = str([p.payload for p in pipeline.indexer.points(result.doc_id)])
    assert "student@example.com" not in payload
    assert "12345678" not in payload
    assert "701 123" not in payload


def test_empty_scans_are_not_deduplicated_by_empty_text(pipeline):
    import pymupdf

    results = []
    for title in ("Scan A", "Scan B"):
        with pymupdf.open() as pdf:
            pdf.new_page()
            pdf.set_metadata({"title": title})
            results.append(ingest(pipeline, pdf.tobytes(), filename=title + ".pdf"))
    assert all(result.status == "needs_ocr" for result in results)
    assert len({result.doc_id for result in results}) == 2


def test_sparse_search_finds_document_number(pipeline, pdf_factory):
    from qdrant_client import models as qm

    from ingestion.services.embedder import lexical_vector

    result = ingest(
        pipeline,
        pdf_factory(text="Official regulation number 51-2-25 for students."),
        channel="kbtu_website",
    )
    indices, values = lexical_vector("51-2-25")
    found = pipeline.indexer.client.query_points(
        pipeline.indexer.collection,
        using="sparse",
        query=qm.SparseVector(indices=indices, values=values),
        query_filter=knowledge_filter(),
    ).points
    assert found and all(p.payload["doc_id"] == result.doc_id for p in found)


def test_prepare_without_embedding_service(tmp_path, pdf_factory):
    from ingestion.config import Settings
    from ingestion.pipeline import Pipeline

    data = pdf_factory()
    with Pipeline(
        Settings(_env_file=None, data_dir=tmp_path / "prepared"), parse_only=True
    ) as tool:
        first = ingest(tool, data)
        second = ingest(tool, data)
        assert first.status == "pending"
        assert first.chunks_count > 0
        assert second.status == "duplicate"
        assert tool._embedder is None and tool._indexer is None
        assert tool.registry.row(first.doc_id)["status"] == "pending"
        assert tool.parsed_path(first.doc_id).exists()


def test_prepared_data_can_be_indexed_later(pipeline, pdf_factory):
    pipeline.parse_only = True
    result = ingest(pipeline, pdf_factory())
    assert result.status == "pending"
    indexed = pipeline.reindex(result.doc_id)
    assert indexed.status == "processed"
    assert pipeline.verify() == []
