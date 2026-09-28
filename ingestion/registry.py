import json
import sqlite3
from pathlib import Path

from ingestion.models import CanonicalDocument, utcnow

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS knowledge_documents (
 logical_document_key TEXT PRIMARY KEY, title TEXT NOT NULL, category TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS knowledge_document_versions (
 id TEXT PRIMARY KEY, logical_document_key TEXT NOT NULL REFERENCES knowledge_documents,
 binary_hash TEXT NOT NULL, content_hash TEXT NOT NULL,
 status TEXT NOT NULL, index_dirty INTEGER NOT NULL DEFAULT 1,
 chunks_count INTEGER NOT NULL DEFAULT 0, document_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_binary ON knowledge_document_versions(binary_hash);
CREATE INDEX IF NOT EXISTS idx_content ON knowledge_document_versions(content_hash);
CREATE TABLE IF NOT EXISTS document_sources (
 id INTEGER PRIMARY KEY, doc_id TEXT NOT NULL REFERENCES knowledge_document_versions,
 source TEXT NOT NULL, binary_hash TEXT NOT NULL, provenance_json TEXT NOT NULL,
 UNIQUE(doc_id, source, binary_hash)
);
CREATE TABLE IF NOT EXISTS ingestion_runs (
 id TEXT PRIMARY KEY, source TEXT NOT NULL, started_at TEXT NOT NULL,
 finished_at TEXT, documents_discovered INTEGER NOT NULL DEFAULT 0,
 documents_added INTEGER NOT NULL DEFAULT 0, documents_updated INTEGER NOT NULL DEFAULT 0,
 duplicates INTEGER NOT NULL DEFAULT 0, failed INTEGER NOT NULL DEFAULT 0,
 status TEXT NOT NULL, results_json TEXT NOT NULL DEFAULT '[]'
);
PRAGMA user_version=1;
"""


class Registry:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=60)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def get(self, doc_id: str) -> CanonicalDocument:
        row = self.db.execute(
            "SELECT document_json FROM knowledge_document_versions WHERE id=?", (doc_id,)
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown document: {doc_id}")
        return CanonicalDocument.model_validate_json(row[0])

    def row(self, doc_id: str):
        return self.db.execute(
            "SELECT * FROM knowledge_document_versions WHERE id=?", (doc_id,)
        ).fetchone()

    def duplicate(self, binary_hash: str, content_hash: str | None = None):
        row = self.db.execute(
            "SELECT id FROM knowledge_document_versions WHERE binary_hash=? OR content_hash=? "
            "OR id IN (SELECT doc_id FROM document_sources WHERE binary_hash=?) LIMIT 1",
            (binary_hash, content_hash, binary_hash),
        ).fetchone()
        return self.get(row[0]) if row else None

    def all(self):
        return [
            CanonicalDocument.model_validate_json(r[0])
            for r in self.db.execute(
                "SELECT document_json FROM knowledge_document_versions ORDER BY rowid"
            )
        ]

    def family(self, key: str):
        return [d for d in self.all() if d.logical_document_key == key]

    def save(self, doc: CanonicalDocument, status="processing", chunks_count=0, dirty=True):
        now = utcnow().isoformat()
        with self.db:
            self.db.execute(
                "INSERT INTO knowledge_documents VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(logical_document_key) DO UPDATE SET updated_at=excluded.updated_at",
                (doc.logical_document_key, doc.title, doc.category, now, now),
            )
            self.db.execute(
                "INSERT INTO knowledge_document_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET status=excluded.status, "
                "index_dirty=excluded.index_dirty, "
                "content_hash=excluded.content_hash, "
                "chunks_count=excluded.chunks_count, document_json=excluded.document_json",
                (
                    doc.doc_id,
                    doc.logical_document_key,
                    doc.binary_hash,
                    doc.content_hash,
                    status,
                    int(dirty),
                    chunks_count,
                    doc.model_dump_json(),
                ),
            )

    def observe(self, doc_id: str, source: str, binary_hash: str, provenance: dict):
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO document_sources "
                "(doc_id, source, binary_hash, provenance_json) VALUES (?, ?, ?, ?)",
                (doc_id, source, binary_hash, json.dumps(provenance, ensure_ascii=False)),
            )

    def start_run(self, run_id: str, source: str):
        with self.db:
            self.db.execute(
                "INSERT INTO ingestion_runs (id, source, started_at, status) "
                "VALUES (?, ?, ?, 'processing')",
                (run_id, source, utcnow().isoformat()),
            )

    def finish_run(self, run_id: str, results: list):
        failures = sum(r.status in {"failed", "needs_ocr"} for r in results)
        with self.db:
            self.db.execute(
                "UPDATE ingestion_runs SET finished_at=?, "
                "documents_discovered=?, documents_added=?, "
                "documents_updated=?, duplicates=?, failed=?, status=?, results_json=? WHERE id=?",
                (
                    utcnow().isoformat(),
                    len(results),
                    sum(r.status in {"processed", "pending"} and not r.updated for r in results),
                    sum(r.status in {"processed", "pending"} and r.updated for r in results),
                    sum(r.status == "duplicate" for r in results),
                    failures,
                    "partial" if failures else "success",
                    json.dumps([r.model_dump() for r in results]),
                    run_id,
                ),
            )

    def runs(self):
        return [
            dict(r)
            for r in self.db.execute(
                "SELECT * FROM ingestion_runs ORDER BY started_at DESC LIMIT 20"
            )
        ]

    def close(self):
        self.db.close()
