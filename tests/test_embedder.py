from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from openai import OpenAIError
from pydantic import ValidationError
from qdrant_client import QdrantClient

from ingestion.config import Settings
from ingestion.pipeline import Pipeline
from ingestion.services.embedder import OpenAIEmbedder, create_embedder
from ingestion.services.indexer import Indexer


def settings(**overrides):
    return Settings(_env_file=None, openai_api_key=None, **overrides)


def response(vectors, indices=None):
    indices = list(range(len(vectors))) if indices is None else indices
    return SimpleNamespace(
        data=[
            SimpleNamespace(index=index, embedding=vector)
            for index, vector in zip(indices, vectors, strict=True)
        ]
    )


def client_mock():
    client = Mock()
    client.embeddings.create.side_effect = lambda **kwargs: response(
        [[1.0] * kwargs["dimensions"] for _ in kwargs["input"]]
    )
    return client


def test_model_dimensions_and_signature():
    small = settings()
    assert small.embedding_provider == "openai"
    assert small.dense_dimensions == 1536
    assert small.embedding_signature == "openai:text-embedding-3-small:1536:lexical-v1"
    assert settings(embedding_dimensions=1536).embedding_signature == small.embedding_signature
    assert settings(embedding_model="text-embedding-3-large").dense_dimensions == 3072
    reduced = settings(embedding_dimensions=256)
    assert reduced.dense_dimensions == 256
    assert reduced.embedding_signature != small.embedding_signature


@pytest.mark.parametrize(
    "overrides",
    [
        {"embedding_dimensions": 0},
        {"embedding_dimensions": 1537},
        {"embedding_model": "text-embedding-3-large", "embedding_dimensions": 3073},
        {"embedding_provider": "unsupported"},
        {"embedding_model": "unsupported"},
    ],
)
def test_invalid_embedding_config(overrides):
    with pytest.raises(ValidationError):
        settings(**overrides)


@pytest.mark.parametrize("key", [None, "", "   "])
def test_key_required_before_creating_sdk_client(key, monkeypatch):
    constructor = Mock()
    monkeypatch.setattr("ingestion.services.embedder.OpenAI", constructor)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        create_embedder(Settings(_env_file=None, openai_api_key=key))
    constructor.assert_not_called()


def test_sdk_config_and_lifecycle_without_probe(monkeypatch):
    client = client_mock()
    constructor = Mock(return_value=client)
    monkeypatch.setattr("ingestion.services.embedder.OpenAI", constructor)
    config = Settings(
        _env_file=None,
        openai_api_key="test-secret-key",
        openai_timeout=15,
        openai_max_retries=2,
    )
    embedder = create_embedder(config)
    constructor.assert_called_once_with(
        api_key="test-secret-key",
        base_url="https://api.openai.com/v1",
        timeout=15,
        max_retries=2,
    )
    assert "test-secret-key" not in repr(config)
    assert embedder.dimension == 1536
    client.embeddings.create.assert_not_called()
    embedder.close()
    client.close.assert_called_once()


def test_batches_sorted_vectors_and_query_share_config():
    client = Mock()
    client.embeddings.create.side_effect = [
        response([[0.0, 1.0], [1.0, 0.0]], [1, 0]),
        response([[0.5, 0.5]]),
        response([[0.2, 0.8]]),
    ]
    embedder = OpenAIEmbedder(
        settings(embedding_dimensions=2, embedding_batch_size=2), client=client
    )
    assert embedder.embed(["first", "second", "third"]) == [[1.0, 0.0], [0.0, 1.0], [0.5, 0.5]]
    assert embedder.query("question") == [0.2, 0.8]
    calls = client.embeddings.create.call_args_list
    assert [call.kwargs["input"] for call in calls] == [
        ["first", "second"],
        ["third"],
        ["question"],
    ]
    for call in calls:
        assert call.kwargs["model"] == "text-embedding-3-small"
        assert call.kwargs["dimensions"] == 2
        assert call.kwargs["encoding_format"] == "float"
    embedder.close()
    client.close.assert_not_called()


def test_pii_masked_before_api():
    client = client_mock()
    embedder = OpenAIEmbedder(settings(embedding_dimensions=2), client=client)
    embedder.query("Email: student@example.com Student ID: 12345678 Phone: +7 701 123 45 67")
    sent = client.embeddings.create.call_args.kwargs["input"][0]
    assert "student@example.com" not in sent
    assert "12345678" not in sent
    assert "701 123" not in sent


def test_empty_batch_and_invalid_inputs_make_no_api_requests():
    client = client_mock()
    embedder = OpenAIEmbedder(settings(embedding_dimensions=2), client=client)
    assert embedder.embed([]) == []
    for bad in ("   ", "token " * 9000):
        with pytest.raises(ValueError, match="1–8191"):
            embedder.embed(["valid first input", bad])
    client.embeddings.create.assert_not_called()


def test_batch_total_token_limit(monkeypatch):
    encoding = Mock()
    encoding.encode.return_value = [0] * 8000
    monkeypatch.setattr("ingestion.services.embedder.tiktoken.get_encoding", lambda _: encoding)
    client = client_mock()
    embedder = OpenAIEmbedder(
        settings(embedding_dimensions=2, embedding_batch_size=256), client=client
    )
    assert len(embedder.embed(["long input"] * 40)) == 40
    assert [len(call.kwargs["input"]) for call in client.embeddings.create.call_args_list] == [
        37,
        3,
    ]


@pytest.mark.parametrize(
    "invalid",
    [
        response([]),
        response([[1.0, 0.0]], [1]),
        response([[1.0, 0.0], [1.0, 0.0]], [0, 0]),
        response([[1.0]]),
        response([[float("nan"), 0.0]]),
        response([[float("inf"), 0.0]]),
    ],
)
def test_invalid_api_responses_rejected(invalid):
    client = Mock()
    client.embeddings.create.return_value = invalid
    with pytest.raises(ValueError, match="OpenAI"):
        OpenAIEmbedder(settings(embedding_dimensions=2), client=client).query("policy")


def test_api_failure_does_not_expose_key_or_request():
    client = Mock()
    client.embeddings.create.side_effect = OpenAIError("test-secret-key private-document-text")
    with pytest.raises(ValueError, match="OpenAI embeddings failed") as error:
        OpenAIEmbedder(settings(embedding_dimensions=2), client=client).query("policy")
    assert "test-secret-key" not in str(error.value)
    assert "private-document-text" not in str(error.value)
    assert error.value.__suppress_context__


def test_openai_adapter_with_pdf_and_real_qdrant(tmp_path, pdf_factory):
    config = settings(data_dir=tmp_path / "store", embedding_dimensions=2)
    client = client_mock()
    embedder = OpenAIEmbedder(config, client=client)
    indexer = Indexer(config, QdrantClient(":memory:"))
    with Pipeline(config, embedder=embedder, indexer=indexer) as pipeline:
        data = pdf_factory()
        first = pipeline.ingest_bytes(
            data, filename="policy.pdf", source="policy.pdf", channel="manual_upload"
        )
        assert first.status == "processed", first.error
        requests = client.embeddings.create.call_count
        assert requests > 0
        second = pipeline.ingest_bytes(
            data, filename="policy.pdf", source="policy.pdf", channel="manual_upload"
        )
        assert second.status == "duplicate"
        assert client.embeddings.create.call_count == requests
        assert pipeline.verify() == []
        config.embedding_dimensions = 1
        with pytest.raises(ValueError, match="vector schema mismatch"):
            pipeline.reindex(first.doc_id)
