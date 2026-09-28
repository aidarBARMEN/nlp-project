"""In-memory зеркало коллекции: payload'ы всех чанков + BM25-индекс для лексического поиска."""

from __future__ import annotations

import threading
from collections import defaultdict

from rank_bm25 import BM25Okapi

from .tokenization import lexical_tokens
from .vector_store import get_vector_store


class KnowledgeBase:
    def __init__(self):
        self._lock = threading.RLock()
        self.chunks: dict[str, dict] = {}
        self._ids: list[str] = []
        self._bm25: BM25Okapi | None = None

    def reload(self) -> None:
        chunks = get_vector_store().all_payloads()
        ids = list(chunks)
        corpus = [
            chunks[i].get("bm25_tokens") or lexical_tokens(chunks[i]["text"]) or ["__empty__"]
            for i in ids
        ]
        bm25 = BM25Okapi(corpus) if corpus else None
        with self._lock:
            self.chunks, self._ids, self._bm25 = chunks, ids, bm25

    def bm25_search(self, query: str, limit: int) -> list[tuple[str, float]]:
        with self._lock:
            if not self._bm25:
                return []
            q = lexical_tokens(query)
            if not q:
                return []
            scores = self._bm25.get_scores(q)
            ids = self._ids
        ranked = sorted(range(len(ids)), key=lambda i: scores[i], reverse=True)[:limit]
        return [(ids[i], float(scores[i])) for i in ranked if scores[i] > 0]

    def documents(self) -> list[dict]:
        docs: dict[str, dict] = {}
        pages = defaultdict(set)
        with self._lock:
            for c in self.chunks.values():
                d = docs.setdefault(
                    c["doc_id"],
                    {
                        "doc_id": c["doc_id"],
                        "file_name": c["file_name"],
                        "title": c.get("title") or c["file_name"],
                        "category": c.get("category"),
                        "academic_year": c.get("academic_year"),
                        "target_audience": c.get("target_audience"),
                        "url": c.get("url"),
                        "indexed_at": c.get("indexed_at"),
                        "file_hash": c.get("file_hash"),
                        "chunks": 0,
                        "tokens": 0,
                    },
                )
                d["chunks"] += 1
                d["tokens"] += c.get("token_count", 0)
                if c.get("page_end"):
                    pages[c["doc_id"]].add(c["page_end"])
        for doc_id, d in docs.items():
            d["pages"] = max(pages[doc_id], default=None)
        return sorted(docs.values(), key=lambda d: d["title"].lower())

    def stats(self) -> dict:
        with self._lock:
            chunks = list(self.chunks.values())
        return {
            "documents": len({c["doc_id"] for c in chunks}),
            "chunks": len(chunks),
            "tokens": sum(c.get("token_count", 0) for c in chunks),
        }


kb = KnowledgeBase()
