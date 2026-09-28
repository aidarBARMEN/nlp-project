"""Exercise the actual UI API contract and persistent Qdrant; only OpenAI is mocked."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.config import Settings
from backend.app.rag import ingest, llm, retriever, tokenization, vector_store
from ingestion.config import Settings as IngestionSettings
from ingestion.services import embedder


@pytest.fixture
def application(tmp_path, monkeypatch):
    config = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        embedding_dimensions=4,
        openai_api_key="test-only-key",
        reranker="none",
        query_rewrite=False,
    )
    for module in (main, ingest, llm, retriever, tokenization, vector_store):
        monkeypatch.setattr(module, "get_settings", lambda: config)
    monkeypatch.setattr(main, "settings", config)
    monkeypatch.setattr(ingest, "BACKEND_DIR", tmp_path / "legacy-backend")
    client = Mock()
    client.embeddings.create.side_effect = lambda **kwargs: SimpleNamespace(
        data=[
            SimpleNamespace(index=i, embedding=[1.0, 0.5, 0.25, 0.125])
            for i in range(len(kwargs["input"]))
        ]
    )
    client.chat.completions.create.side_effect = lambda **kwargs: iter(
        [
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="Register for exams. [1]"))]
            )
        ]
    )
    monkeypatch.setattr(llm, "OpenAI", Mock(return_value=client))
    monkeypatch.setattr(embedder, "OpenAI", Mock(return_value=client))
    vector_store.close_vector_store()
    llm.close_client()
    with TestClient(main.app) as api:
        yield api, config, client


def upload(api, data, name="policy.pdf"):
    response = api.post("/api/documents/upload", files={"files": (name, data)})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["errors"] == [], body
    return body["indexed"][0]


def trust(api, doc_id, level="official"):
    response = api.post(
        f"/api/documents/{doc_id}/trust",
        json={
            "trust_level": level,
            "reason": "Checked original source by operator",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_upload_trust_search_chat_archive(application, pdf_factory):
    api, config, sdk = application
    data = pdf_factory()
    doc = upload(api, data)
    assert doc["status"] == "processed" and doc["trust_level"] == "unverified"
    count = sdk.embeddings.create.call_count
    assert upload(api, data)["doc_id"] == doc["doc_id"]
    assert sdk.embeddings.create.call_count == count
    assert api.post("/api/search", json={"query": "exam registration"}).json()["results"] == []
    assert not sdk.chat.completions.create.called

    assert trust(api, doc["doc_id"])["is_current"]
    assert sdk.embeddings.create.call_count == count
    results = api.post("/api/search", json={"query": "exam registration"}).json()["results"]
    assert results and {result["doc_id"] for result in results} == {doc["doc_id"]}
    assert all(result["page_start"] in (1, 2) for result in results)
    assert all(result["file_name"] for result in results)
    answer = api.post("/api/chat", json={"question": "How to register for exams?"}).json()
    assert "[1]" in answer["answer"] and answer["sources"]
    stream = api.post("/api/chat/stream", json={"question": "Exam rules?"})
    assert "event: sources" in stream.text and "event: token" in stream.text
    assert "event: done" in stream.text and "event: error" not in stream.text
    assert api.get(f"/api/documents/{doc['doc_id']}/file").content == data
    assert api.get("/api/health").json()["chunks"] > 0

    assert api.delete(f"/api/documents/{doc['doc_id']}").status_code == 200
    assert api.get("/api/documents").json() == []
    assert api.post("/api/search", json={"query": "exam"}).json()["results"] == []
    assert api.post("/api/documents/sync").json()["errors"] == []
    assert api.get("/api/documents").json() == []
    assert list((config.data_dir / "raw").rglob("*.pdf"))
    with ingest.ingestion_session() as pipeline:
        assert pipeline.verify() == []


def test_prepare_without_key_then_index_existing_data(application, pdf_factory):
    api, config, sdk = application
    from pydantic import SecretStr

    config.openai_api_key = None
    doc = upload(api, pdf_factory())
    assert doc["status"] == "pending"
    sdk.embeddings.create.assert_not_called()
    assert api.get("/api/documents").json()[0]["status"] == "pending"
    trust(api, doc["doc_id"])
    assert api.post("/api/documents/sync?reset=true").status_code == 503
    assert api.post("/api/nlp/embed", json={"texts": ["exam"]}).status_code == 503
    config.openai_api_key = SecretStr("test-only-key")
    report = api.post("/api/documents/sync").json()
    assert not report["errors"] and report["indexed"]
    assert api.get("/api/documents").json()[0]["status"] == "processed"
    assert api.post("/api/search", json={"query": "exam"}).json()["results"]


def test_cli_sources_remain_when_inbox_is_empty(application, pdf_factory):
    api, config, sdk = application
    with ingest.ingestion_session() as pipeline:
        result = pipeline.ingest_bytes(
            pdf_factory(),
            filename="web-policy.pdf",
            source="https://kbtu.edu.kz/files/rules.pdf",
            source_url="https://kbtu.edu.kz/files/rules.pdf",
            channel="kbtu_website",
        )
        assert result.status == "processed", result.error
    assert api.get("/api/documents").json()[0]["source_channel"] == "kbtu_website"
    for reset in ("false", "true"):
        response = api.post(f"/api/documents/sync?reset={reset}").json()
        assert response["errors"] == [] and response["removed"] == []
    assert api.get("/api/documents").json()[0]["doc_id"] == result.doc_id
    assert api.post("/api/search", json={"query": "policy"}).json()["results"]
    trust(api, result.doc_id, "unverified")
    assert api.post("/api/search", json={"query": "policy"}).json()["results"] == []


def test_changed_model_refuses_existing_index(application, pdf_factory):
    api, config, _ = application
    doc = upload(api, pdf_factory())
    trust(api, doc["doc_id"])
    config.embedding_model = "text-embedding-3-large"
    response = api.post("/api/search", json={"query": "policy"})
    assert response.status_code == 400
    assert "Embedding model changed" in response.json()["detail"]


def test_shared_settings_independent_of_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ingestion_settings = IngestionSettings(_env_file=None)
    backend_settings = Settings(_env_file=None)
    assert backend_settings.data_dir == ingestion_settings.data_dir
    assert backend_settings.qdrant_collection == ingestion_settings.qdrant_collection
    assert backend_settings.embedding_signature == ingestion_settings.embedding_signature
    assert backend_settings.documents_path == ingestion_settings.data_dir / "inbox" / "manual"


def test_upload_limits_and_unknown_document(application):
    api, config, sdk = application
    config.max_file_mb = 1
    response = api.post(
        "/api/documents/upload", files={"files": ("too-big.txt", b"a" * (1024 * 1024 + 1))}
    )
    assert response.json()["errors"] and not response.json()["indexed"]
    assert api.get("/api/documents/unknown/file").status_code == 404
    assert api.delete("/api/documents/unknown").status_code == 404
    assert (
        api.post(
            "/api/documents/unknown/trust", json={"trust_level": "official", "reason": "checked"}
        ).status_code
        == 404
    )
    sdk.embeddings.create.assert_not_called()


def test_tokenizer_accepts_literal_special_tokens(application):
    api, _, _ = application
    response = api.post("/api/nlp/tokenize", json={"text": "Policy <|endoftext|> rules"})
    assert response.status_code == 200
    assert response.json()["token_count"] > 0
