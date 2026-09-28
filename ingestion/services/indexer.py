from uuid import NAMESPACE_URL, uuid5

from qdrant_client import QdrantClient
from qdrant_client import models as qm

from ingestion.config import Settings
from ingestion.models import CanonicalDocument, Chunk
from ingestion.services.embedder import Embedder, lexical_vector

CONFIG_ID = str(uuid5(NAMESPACE_URL, "kbtu-ingestion/config/v1"))
FILTER_FIELDS = {
    "is_current": qm.PayloadSchemaType.BOOL,
    "trust_level": qm.PayloadSchemaType.KEYWORD,
    "academic_year": qm.PayloadSchemaType.KEYWORD,
    "language": qm.PayloadSchemaType.KEYWORD,
    "category": qm.PayloadSchemaType.KEYWORD,
    "source_channel": qm.PayloadSchemaType.KEYWORD,
    "target_audience": qm.PayloadSchemaType.KEYWORD,
    "doc_id": qm.PayloadSchemaType.KEYWORD,
    "record_type": qm.PayloadSchemaType.KEYWORD,
    "index_status": qm.PayloadSchemaType.KEYWORD,
}


def document_filter(doc_id: str) -> qm.Filter:
    return qm.Filter(must=[qm.FieldCondition(key="doc_id", match=qm.MatchValue(value=doc_id))])


def knowledge_filter(*, current=True, trust_levels=("official",), **fields) -> qm.Filter:
    conditions = [
        qm.FieldCondition(key="record_type", match=qm.MatchValue(value="chunk")),
        qm.FieldCondition(key="index_status", match=qm.MatchValue(value="ready")),
    ]
    if current is not None:
        conditions.append(qm.FieldCondition(key="is_current", match=qm.MatchValue(value=current)))
    conditions.append(
        qm.FieldCondition(key="trust_level", match=qm.MatchAny(any=list(trust_levels)))
    )
    for key, value in fields.items():
        if key not in FILTER_FIELDS:
            raise ValueError(f"Unsupported filter: {key}")
        conditions.append(qm.FieldCondition(key=key, match=qm.MatchValue(value=value)))
    return qm.Filter(must=[condition for condition in conditions])


class Indexer:
    def __init__(
        self,
        settings: Settings,
        client: QdrantClient | None = None,
        *,
        force_disable_check_same_thread: bool = False,
    ):
        self.settings = settings
        self.collection = settings.qdrant_collection
        self._owns_client = client is None
        self.client = client or (
            QdrantClient(
                url=settings.qdrant_url,
                api_key=settings.qdrant_api_key.get_secret_value()
                if settings.qdrant_api_key
                else None,
                timeout=60,
            )
            if settings.qdrant_url
            else QdrantClient(
                path=str(settings.data_dir / "qdrant"),
                force_disable_check_same_thread=force_disable_check_same_thread,
            )
        )

    def ensure(self, dimension: int):
        if not self.client.collection_exists(self.collection):
            self.client.create_collection(
                self.collection,
                vectors_config={
                    "dense": qm.VectorParams(size=dimension, distance=qm.Distance.COSINE)
                },
                sparse_vectors_config={"sparse": qm.SparseVectorParams()},
            )
            if self.settings.qdrant_url:
                for field, schema in FILTER_FIELDS.items():
                    self.client.create_payload_index(self.collection, field, schema, wait=True)
        info = self.client.get_collection(self.collection)
        vectors = info.config.params.vectors
        sparse = info.config.params.sparse_vectors
        if (
            not isinstance(vectors, dict)
            or "dense" not in vectors
            or vectors["dense"].size != dimension
            or not sparse
            or "sparse" not in sparse
        ):
            raise ValueError("Qdrant vector schema mismatch; use a new collection and reindex")
        config = self.client.retrieve(self.collection, [CONFIG_ID])
        signature = self.settings.embedding_signature
        if config:
            if (config[0].payload or {}).get("embedding_signature") != signature:
                raise ValueError("Embedding model changed; use a new collection and reindex")
        elif self.client.count(self.collection).count:
            raise ValueError(
                "Existing collection has no ingestion schema; explicit migration required"
            )
        else:
            self.client.upsert(
                self.collection,
                [
                    qm.PointStruct(
                        id=CONFIG_ID,
                        vector={"dense": [0.0] * dimension},
                        payload={"record_type": "configuration", "embedding_signature": signature},
                    )
                ],
                wait=True,
            )

    def upsert(self, document: CanonicalDocument, chunks: list[Chunk], embedder: Embedder):
        self.ensure(embedder.dimension)
        size = self.settings.embedding_batch_size
        for offset in range(0, len(chunks), size):
            batch = chunks[offset : offset + size]
            # Text has baseline PII suppression before being sent to the embeddings API.
            texts = [
                "\n".join(filter(None, [c.title, c.section, c.subsection, c.text])) for c in batch
            ]
            vectors = embedder.embed(texts)
            if len(vectors) != len(batch):
                raise ValueError("Embedding batch length mismatch")
            points = []
            for chunk, text, dense in zip(batch, texts, vectors, strict=True):
                indices, values = lexical_vector(text)
                payload = chunk.model_dump(mode="json")
                payload.update(
                    {
                        "record_type": "chunk",
                        "original_filename": document.original_filename,
                        "index_status": "staging",
                        "is_current": False,
                        "category": document.category,
                        "target_audience": document.target_audience,
                        "document_number": document.document_number,
                        "effective_from": str(document.effective_from)
                        if document.effective_from
                        else None,
                        "effective_to": str(document.effective_to)
                        if document.effective_to
                        else None,
                        "fetched_at": document.fetched_at.isoformat(),
                        "embedding_signature": self.settings.embedding_signature,
                    }
                )
                points.append(
                    qm.PointStruct(
                        id=chunk.chunk_id,
                        vector={
                            "dense": dense,
                            "sparse": qm.SparseVector(indices=indices, values=values),
                        },
                        payload=payload,
                    )
                )
            self.client.upsert(self.collection, points, wait=True)
        keep = {c.chunk_id for c in chunks}
        stale = [p.id for p in self.points(document.doc_id) if str(p.id) not in keep]
        if stale:
            self.client.delete(self.collection, qm.PointIdsList(points=stale), wait=True)

    def sync_metadata(self, doc: CanonicalDocument):
        self.client.set_payload(
            self.collection,
            {
                "is_current": doc.is_current,
                "trust_level": doc.trust_level,
                "index_status": "ready",
                "supersedes_doc_id": doc.supersedes_doc_id,
                "source_url": doc.source_url,
                "source_channel": doc.source_channel,
            },
            points=document_filter(doc.doc_id),
            wait=True,
        )

    def points(self, doc_id: str):
        if not self.client.collection_exists(self.collection):
            return []
        points = []
        offset = None
        while True:
            batch, offset = self.client.scroll(
                self.collection,
                scroll_filter=document_filter(doc_id),
                offset=offset,
                limit=256,
                with_payload=True,
            )
            points.extend(batch)
            if offset is None:
                return points

    def close(self):
        if self._owns_client:
            self.client.close()
