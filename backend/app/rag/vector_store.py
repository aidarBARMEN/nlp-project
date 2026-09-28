"""Векторная база данных Qdrant (локальный режим или сервер)."""
from __future__ import annotations

from functools import lru_cache

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from ..config import get_settings
from .llm import embed_query

KNOWN_DIMS = {"text-embedding-3-small": 1536, "text-embedding-3-large": 3072, "text-embedding-ada-002": 1536}


class VectorStore:
    def __init__(self):
        s = get_settings()
        self.collection = s.qdrant_collection
        if s.qdrant_url:
            self.client = QdrantClient(url=s.qdrant_url)
        else:
            s.qdrant_local_path.mkdir(parents=True, exist_ok=True)
            self.client = QdrantClient(path=str(s.qdrant_local_path))
        self.mode = "server" if s.qdrant_url else "embedded"

    def ensure_collection(self) -> None:
        if self.client.collection_exists(self.collection):
            return
        model = get_settings().openai_embedding_model
        dim = KNOWN_DIMS.get(model) or len(embed_query("dimension probe"))
        self.client.create_collection(
            self.collection,
            vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE),
        )

    def upsert(self, ids: list[str], vectors: list[list[float]], payloads: list[dict]) -> None:
        self.ensure_collection()
        for i in range(0, len(ids), 128):
            self.client.upsert(
                self.collection,
                points=qm.Batch(ids=ids[i : i + 128], vectors=vectors[i : i + 128], payloads=payloads[i : i + 128]),
            )

    def delete_document(self, doc_id: str) -> None:
        if not self.client.collection_exists(self.collection):
            return
        self.client.delete(
            self.collection,
            points_selector=qm.FilterSelector(
                filter=qm.Filter(must=[qm.FieldCondition(key="doc_id", match=qm.MatchValue(value=doc_id))])
            ),
        )

    def search(self, vector: list[float], limit: int) -> list[tuple[str, float]]:
        if not self.client.collection_exists(self.collection):
            return []
        res = self.client.query_points(self.collection, query=vector, limit=limit, with_payload=False)
        return [(str(p.id), float(p.score)) for p in res.points]

    def all_payloads(self) -> dict[str, dict]:
        if not self.client.collection_exists(self.collection):
            return {}
        out, offset = {}, None
        while True:
            points, offset = self.client.scroll(
                self.collection, limit=512, offset=offset, with_payload=True, with_vectors=False
            )
            for p in points:
                out[str(p.id)] = p.payload
            if offset is None:
                return out

    def reset(self) -> None:
        if self.client.collection_exists(self.collection):
            self.client.delete_collection(self.collection)


@lru_cache
def get_vector_store() -> VectorStore:
    return VectorStore()
