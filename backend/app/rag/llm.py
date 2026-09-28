from __future__ import annotations

from functools import lru_cache

import numpy as np
from openai import OpenAI

from ingestion.services.embedder import OpenAIEmbedder

from ..config import get_settings


class MissingAPIKey(RuntimeError):
    pass


@lru_cache
def get_client() -> OpenAI:
    settings = get_settings()
    if not settings.has_openai_key:
        raise MissingAPIKey(
            "OPENAI_API_KEY не задан. Вставьте ключ в корневой .env и перезапустите сервер."
        )
    return OpenAI(
        api_key=settings.openai_api_key.get_secret_value(),
        base_url="https://api.openai.com/v1",
        timeout=settings.openai_timeout,
        max_retries=settings.openai_max_retries,
    )


def embed_texts(texts: list[str], batch_size: int = 96) -> list[list[float]]:
    """Use the exact same model, dimensions and redaction as document ingestion."""
    return OpenAIEmbedder(get_settings(), client=get_client()).embed(texts)


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]


def cosine_matrix(vectors: list[list[float]]) -> list[list[float]]:
    m = np.array(vectors, dtype=np.float32)
    m /= np.linalg.norm(m, axis=1, keepdims=True) + 1e-12
    return (m @ m.T).round(4).tolist()


def is_flagged(text: str) -> bool:
    resp = get_client().moderations.create(model="omni-moderation-latest", input=text)
    return bool(resp.results[0].flagged)


def close_client() -> None:
    if get_client.cache_info().currsize:
        get_client().close()
        get_client.cache_clear()
