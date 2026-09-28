"""Read the canonical ingestion collection; never create a competing vector schema."""

from functools import lru_cache
from threading import RLock

from qdrant_client import QdrantClient

from ingestion.services.indexer import Indexer, knowledge_filter

from ..config import get_settings


class VectorStore:
    def __init__(self, client: QdrantClient | None = None):
        self.settings = get_settings()
        self.indexer = Indexer(self.settings, client, force_disable_check_same_thread=True)
        self.client = self.indexer.client
        self.collection = self.settings.qdrant_collection
        self.mode = "server" if self.settings.qdrant_url else "embedded"
        self.lock = RLock()

    def validate(self) -> bool:
        if not self.client.collection_exists(self.collection):
            return False
        self.indexer.ensure(self.settings.dense_dimensions)
        return True

    def search(self, vector: list[float], limit: int) -> list[tuple[str, float]]:
        with self.lock:
            if not self.validate():
                return []
            res = self.client.query_points(
                self.collection,
                query=vector,
                using="dense",
                limit=limit,
                query_filter=knowledge_filter(),
                with_payload=False,
            )
            return [(str(p.id), float(p.score)) for p in res.points]

    def all_payloads(self) -> dict[str, dict]:
        with self.lock:
            if not self.validate():
                return {}
            out, offset = {}, None
            while True:
                points, offset = self.client.scroll(
                    self.collection,
                    scroll_filter=knowledge_filter(),
                    limit=512,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                for point in points:
                    payload = dict(point.payload or {})
                    # Preserve the frontend contract while retaining canonical metadata.
                    payload.update(
                        {
                            "file_name": payload.get("original_filename")
                            or payload.get("title", ""),
                            "url": payload.get("source_url"),
                            "indexed_at": payload.get("fetched_at"),
                            "token_count": payload.get("metadata", {}).get("token_count", 0),
                        }
                    )
                    out[str(point.id)] = payload
                if offset is None:
                    return out

    def close(self) -> None:
        self.indexer.close()


@lru_cache
def get_vector_store() -> VectorStore:
    return VectorStore()


def close_vector_store() -> None:
    if get_vector_store.cache_info().currsize:
        get_vector_store().close()
        get_vector_store.cache_clear()
