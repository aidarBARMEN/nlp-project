"""Exercise the actual UI API contract and persistent Qdrant; only OpenAI is mocked."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.config import Settings
from backend.app.rag import (
    email_reply,
    ingest,
    llm,
    mailbox,
    retriever,
    tokenization,
    vector_store,
)
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
    for module in (main, email_reply, ingest, llm, mailbox, retriever, tokenization, vector_store):
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
                choices=[SimpleNamespace(delta=SimpleNamespace(content="Register for exams. [1]"))],
                usage=None,
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


def test_chat_explains_unconfirmed_documents_without_calling_llm(application, pdf_factory):
    api, _, sdk = application
    upload(api, pdf_factory())
    response = api.post("/api/chat", json={"question": "Какие правила?"})
    assert response.status_code == 200
    assert "Подтвердить" in response.json()["answer"]
    assert response.json()["sources"] == []
    stream = api.post("/api/chat/stream", json={"question": "Какие правила?"})
    assert "Подтвердить" in stream.text and "event: done" in stream.text
    sdk.chat.completions.create.assert_not_called()


def test_sync_retries_ocr_from_retained_raw_without_api_key(application, monkeypatch):
    import json

    import pymupdf

    from ingestion.services.normalizer import content_hash

    api, config, sdk = application
    config.openai_api_key = None
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        pixmap = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 40, 40), 0)
        pixmap.clear_with(255)
        page.insert_image(page.rect, pixmap=pixmap)
        data = pdf.tobytes()
    uploaded = api.post("/api/documents/upload", files={"files": ("scan.pdf", data)})
    assert uploaded.json()["errors"]
    doc = api.get("/api/documents").json()[0]
    assert doc["status"] == "needs_ocr"
    trust(api, doc["doc_id"])
    # Recovery must work from immutable raw, even if the inbox copy is gone.
    for path in config.documents_path.rglob("scan.pdf"):
        path.unlink()

    def recognize(page, **kwargs):
        page.insert_text((72, 90), "Students register for exams in the university portal.")
        return page.get_textpage()

    monkeypatch.setattr(pymupdf.Page, "get_textpage_ocr", recognize)
    monkeypatch.setattr("ingestion.parsers.pdf_parser.ocr_data_directory", lambda *_: "test-data")
    config.ocr_enabled = True
    report = api.post("/api/documents/sync").json()
    assert report["errors"] == [], report
    assert report["indexed"][0]["status"] == "pending"
    recovered = api.get("/api/documents").json()[0]
    assert recovered["doc_id"] == doc["doc_id"]
    assert recovered["trust_level"] == "official"
    assert recovered["chunks"] > 0
    with ingest.ingestion_session() as pipeline:
        canonical = pipeline.registry.get(doc["doc_id"])
        artifact = json.loads(pipeline.parsed_path(doc["doc_id"]).read_text(encoding="utf-8"))
        assert canonical.content_hash == content_hash(
            "\n".join(block["text"] for block in artifact["parsed"]["blocks"])
        )
    sdk.embeddings.create.assert_not_called()


def test_email_reply_draft_for_dean_office(application, pdf_factory, monkeypatch):
    api, config, sdk = application
    monkeypatch.setattr(config, "email_own_address", "dean@kbtu.kz")
    letter = {
        "sender": "student@kbtu.kz",
        "sender_name": "Aruzhan Bekova",
        "subject": "Exam registration",
        "body": "<p>Hello! How do I register for exams?</p>"
        "<div>On Mon, 1 Sep 2026 Dean wrote:</div><blockquote>old text</blockquote>",
    }

    pending = api.post("/api/email/reply", json=letter).json()
    assert pending["status"] == "needs_review" and pending["subject"] == "Re: Exam registration"
    assert "forwarded" in pending["reply_text"] and pending["sources"] == []
    sdk.chat.completions.create.assert_not_called()

    trust(api, upload(api, pdf_factory())["doc_id"])
    draft = api.post("/api/email/reply", json=letter).json()
    assert draft["status"] == "answered" and draft["language"] == "en"
    assert draft["reply_text"].startswith("Dear Aruzhan,")
    assert "Register for exams." in draft["reply_text"]
    assert "Academic Policy 2026" in draft["reply_text"] and draft["sources"]
    assert "<p>" in draft["reply_html"]
    prompt = sdk.chat.completions.create.call_args.kwargs["messages"][-1]["content"]
    assert "How do I register" in prompt and "old text" not in prompt

    for sender in ("no-reply@service.com", "Dean <dean@kbtu.kz>"):
        skipped = api.post("/api/email/reply", json={**letter, "sender": sender}).json()
        assert skipped["status"] == "skipped"

    monkeypatch.setattr(config, "email_api_token", "secret")
    assert api.post("/api/email/reply", json=letter).status_code == 401
    ok = api.post("/api/email/reply", json=letter, headers={"X-API-Key": "secret"})
    assert ok.status_code == 200


def test_email_reply_escalates_when_documents_have_no_answer(application, pdf_factory):
    api, _, sdk = application
    trust(api, upload(api, pdf_factory())["doc_id"])
    sdk.chat.completions.create.side_effect = lambda **kwargs: iter(
        [
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="ESCALATE"))], usage=None
            )
        ]
    )
    letter = {"sender": "s@kbtu.kz", "subject": "Общежитие", "body": "Можно ли заселиться?"}
    draft = api.post("/api/email/reply", json=letter).json()
    assert draft["status"] == "needs_review" and draft["language"] == "ru"
    assert draft["reply_text"].startswith("Здравствуйте!")
    assert "передан специалисту" in draft["reply_text"] and "ESCALATE" not in draft["reply_text"]
    assert draft["reply_text"].endswith("Деканат КБТУ")


def test_email_reply_saves_draft_once_into_thread(application, pdf_factory, monkeypatch):
    api, config, _ = application
    monkeypatch.setattr(config, "email_own_address", "dean@gmail.com")
    monkeypatch.setattr(config, "email_app_password", "abcd efgh ijkl mnop")
    trust(api, upload(api, pdf_factory())["doc_id"])
    imap = Mock()
    imap.__enter__ = Mock(return_value=imap)
    imap.__exit__ = Mock(return_value=False)
    imap.list.return_value = (
        "OK",
        [rb'(\HasNoChildren) "/" "INBOX"', rb'(\Drafts \HasNoChildren) "/" "[Gmail]/Drafts"'],
    )
    monkeypatch.setattr(mailbox.imaplib, "IMAP4_SSL", Mock(return_value=imap))
    letter = {
        "sender": "student@kbtu.kz",
        "sender_name": "Aruzhan",
        "subject": "Exams",
        "body": "How do I register for exams?",
        "message_id": "<q1@kbtu.kz>",
        "references": "<q0@kbtu.kz>",
        "save_draft": True,
    }

    draft = api.post("/api/email/reply", json=letter).json()
    assert draft["status"] == "answered" and draft["draft_saved"] is True
    imap.login.assert_called_once_with("dean@gmail.com", "abcdefghijklmnop")
    folder, flags, _, raw = imap.append.call_args.args
    assert folder == '"[Gmail]/Drafts"' and flags == r"(\Draft)"
    assert b"In-Reply-To: <q1@kbtu.kz>" in raw and b"Subject: Re: Exams" in raw
    assert b"References: <q0@kbtu.kz> <q1@kbtu.kz>" in raw and b"To: student@kbtu.kz" in raw

    again = api.post("/api/email/reply", json=letter).json()
    assert again == {"status": "skipped", "reason": "duplicate", "draft_saved": False}
    assert imap.append.call_count == 1

    imap.append.side_effect = OSError("network down")
    failed = api.post("/api/email/reply", json={**letter, "message_id": "<q2@kbtu.kz>"})
    assert failed.status_code == 502
    imap.append.side_effect = None
    retried = api.post("/api/email/reply", json={**letter, "message_id": "<q2@kbtu.kz>"})
    assert retried.json()["draft_saved"] is True


def test_email_reply_skips_mailing_lists_and_old_mail(application, monkeypatch):
    api, config, sdk = application
    monkeypatch.setattr(
        config, "email_start_after", datetime.fromisoformat("2026-10-12T18:00:00+05:00")
    )
    letter = {"sender": "shop@store.com", "subject": "Скидки", "body": "Только сегодня!"}
    for extra, reason in (
        ({"headers": {"list-unsubscribe": "<mailto:u@store.com>"}}, "automated"),
        ({"headers": {"precedence": "bulk"}}, "automated"),
        ({"received_at": "2026-10-12T12:59:00Z"}, "old"),
    ):
        skipped = api.post("/api/email/reply", json={**letter, **extra}).json()
        assert (skipped["status"], skipped["reason"]) == ("skipped", reason)
    fresh = api.post(
        "/api/email/reply", json={**letter, "received_at": "2026-10-12T13:01:00Z"}
    ).json()
    assert fresh["status"] == "needs_review"
    sdk.chat.completions.create.assert_not_called()
