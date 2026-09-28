import hashlib
import math
import re
from collections import Counter
from typing import Protocol

import tiktoken
from openai import OpenAI, OpenAIError

from ingestion.config import Settings
from ingestion.services.normalizer import redact


class Embedder(Protocol):
    @property
    def dimension(self) -> int: ...
    def embed(self, texts: list[str]) -> list[list[float]]: ...
    def query(self, text: str) -> list[float]: ...


def lexical_vector(text: str) -> tuple[list[int], list[float]]:
    """Stable lexical vocabulary, including numbers/hyphenated identifiers, no mutable IDF."""
    terms = re.findall(r"[^\W_]+(?:[-/][^\W_]+)*", text.lower(), flags=re.UNICODE)
    counts: Counter[int] = Counter()
    for term in terms:
        index = int.from_bytes(hashlib.blake2s(term.encode(), digest_size=4).digest(), "big")
        counts[index] += 1
    indices = sorted(counts)
    return indices, [1 + math.log(counts[i]) for i in indices]


class OpenAIEmbedder:
    """Shared document/query encoder; API clients are created lazily by the pipeline."""

    def __init__(self, settings: Settings, *, client: OpenAI | None = None):
        key = settings.openai_api_key
        if client is None and (key is None or not key.get_secret_value().strip()):
            raise ValueError(
                "Set OPENAI_API_KEY in .env to index documents; --parse-only needs no key"
            )
        self.settings = settings
        self._owns_client = client is None
        self.client = (
            client
            if client is not None
            else OpenAI(
                api_key=key.get_secret_value() if key else None,
                base_url="https://api.openai.com/v1",
                timeout=settings.openai_timeout,
                max_retries=settings.openai_max_retries,
            )
        )

    @property
    def dimension(self) -> int:
        # No paid probe request to determine a known model dimension.
        return self.settings.dense_dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        prepared = [redact(text).strip() for text in texts]
        encoding = tiktoken.get_encoding("cl100k_base")
        counts = [len(encoding.encode(text, disallowed_special=())) for text in prepared]
        if any(not text or count > 8191 for text, count in zip(prepared, counts, strict=True)):
            raise ValueError(
                "Embedding inputs must contain 1–8191 tokens; reduce chunk/context size"
            )
        batches: list[list[str]] = []
        batch: list[str] = []
        tokens = 0
        for text, count in zip(prepared, counts, strict=True):
            if batch and (
                len(batch) >= self.settings.embedding_batch_size or tokens + count > 300_000
            ):
                batches.append(batch)
                batch, tokens = [], 0
            batch.append(text)
            tokens += count
        batches.append(batch)
        output: list[list[float]] = []
        for batch in batches:
            try:
                response = self.client.embeddings.create(
                    model=self.settings.embedding_model,
                    input=batch,
                    dimensions=self.dimension,
                    encoding_format="float",
                )
            except OpenAIError as exc:
                status = getattr(exc, "status_code", None)
                detail = f"HTTP {status}" if status is not None else type(exc).__name__
                raise ValueError(
                    f"OpenAI embeddings failed ({detail}); check API key, quota and connection"
                ) from None
            items = sorted(response.data, key=lambda item: item.index)
            if [item.index for item in items] != list(range(len(batch))):
                raise ValueError(
                    "OpenAI embedding response count or indices do not match the batch"
                )
            for item in items:
                if len(item.embedding) != self.dimension or not all(
                    math.isfinite(value) for value in item.embedding
                ):
                    raise ValueError("OpenAI returned an invalid embedding dimension or value")
                output.append(item.embedding)
        return output

    def query(self, text: str) -> list[float]:
        return self.embed([text])[0]

    def close(self) -> None:
        if self._owns_client:
            self.client.close()


def create_embedder(settings: Settings) -> OpenAIEmbedder:
    return OpenAIEmbedder(settings)
