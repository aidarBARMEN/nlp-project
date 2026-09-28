from __future__ import annotations

from functools import lru_cache

import numpy as np
from openai import OpenAI

from ..config import get_settings


class MissingAPIKey(RuntimeError):
    pass


@lru_cache
def get_client() -> OpenAI:
    settings = get_settings()
    if not settings.has_openai_key:
        raise MissingAPIKey("OPENAI_API_KEY не задан. Вставьте ключ в backend/.env и перезапустите сервер.")
    return OpenAI(api_key=settings.openai_api_key)


def embed_texts(texts: list[str], batch_size: int = 96) -> list[list[float]]:
    """Эмбеддинги OpenAI (векторы уже L2-нормализованы -> cosine = dot product)."""
    client = get_client()
    model = get_settings().openai_embedding_model
    vectors: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = [t.replace("\n", " ")[:30000] for t in texts[i : i + batch_size]]
        resp = client.embeddings.create(model=model, input=batch)
        vectors.extend(d.embedding for d in sorted(resp.data, key=lambda d: d.index))
    return vectors


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]


def cosine_matrix(vectors: list[list[float]]) -> list[list[float]]:
    m = np.array(vectors, dtype=np.float32)
    m /= np.linalg.norm(m, axis=1, keepdims=True) + 1e-12
    return (m @ m.T).round(4).tolist()


def is_flagged(text: str) -> bool:
    resp = get_client().moderations.create(model="omni-moderation-latest", input=text)
    return bool(resp.results[0].flagged)
