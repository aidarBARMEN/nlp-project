"""Data Ingestion Pipeline: парсинг -> чанкинг -> эмбеддинги -> Qdrant.

Запуск из CLI (сервер должен быть остановлен, если Qdrant работает во встроенном режиме):
    python -m app.rag.ingest            # проиндексировать новые/изменённые файлы
    python -m app.rag.ingest --reset    # переиндексировать всё с нуля
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..config import get_settings
from .chunking import chunk_blocks
from .knowledge_base import kb
from .llm import embed_texts
from .parsing import SUPPORTED_EXTENSIONS, parse_document
from .tokenization import lexical_tokens
from .vector_store import get_vector_store

log = logging.getLogger("ingest")
METADATA_FILE = "_metadata.json"
_ingest_lock = threading.Lock()


def doc_id_for(rel_path: str) -> str:
    return hashlib.sha1(rel_path.replace("\\", "/").lower().encode()).hexdigest()[:16]


def fingerprint(path: Path, meta: dict) -> str:
    """Хэш содержимого файла + его метаданных: меняется что-то одно -> документ переиндексируется."""
    h = hashlib.sha256(json.dumps(meta, sort_keys=True, ensure_ascii=False).encode())
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()[:16]


def load_metadata(root: Path) -> dict[str, dict]:
    meta_path = root / METADATA_FILE
    if not meta_path.exists():
        return {}
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return {k.replace("\\", "/"): v for k, v in data.items() if not k.startswith("_")}
    except json.JSONDecodeError as e:
        log.warning("Не удалось прочитать %s: %s", meta_path, e)
        return {}


def list_source_files(root: Path) -> list[Path]:
    return sorted(
        p for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS and not p.name.startswith(("_", "~$", "."))
        and p.name.lower() != "readme.md"
    )


def ingest_file(path: Path, root: Path, meta: dict | None = None) -> dict:
    s = get_settings()
    rel = path.relative_to(root).as_posix()
    meta = meta or {}
    doc_id = doc_id_for(rel)
    fhash = fingerprint(path, meta)
    title = meta.get("title") or path.stem.replace("_", " ")
    category = meta.get("category") or (rel.split("/")[0] if "/" in rel else None)

    blocks = parse_document(path)
    chunks = chunk_blocks(blocks, s.chunk_size, s.chunk_overlap)
    if not chunks:
        raise ValueError(f"В файле {rel} не найден текст (возможно, это скан без OCR)")

    # контекстный заголовок улучшает эмбеддинг коротких чанков
    embed_inputs = [f"Документ: {title}\nРаздел: {c.section or '-'}\n\n{c.text}" for c in chunks]
    vectors = embed_texts(embed_inputs)

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ids, payloads = [], []
    for c in chunks:
        ids.append(str(uuid.uuid5(uuid.NAMESPACE_URL, f"{doc_id}:{fhash}:{c.index}")))
        payloads.append({
            "doc_id": doc_id,
            "file_name": rel,
            "file_hash": fhash,
            "title": title,
            "category": category,
            "academic_year": meta.get("academic_year"),
            "target_audience": meta.get("target_audience"),
            "url": meta.get("url"),
            "section": c.section,
            "page_start": c.page_start,
            "page_end": c.page_end,
            "chunk_index": c.index,
            "token_count": c.token_count,
            "text": c.text,
            "bm25_tokens": lexical_tokens(f"{c.section or ''} {c.text}"),
            "indexed_at": now,
        })

    store = get_vector_store()
    store.delete_document(doc_id)
    store.upsert(ids, vectors, payloads)
    return {"file_name": rel, "doc_id": doc_id, "chunks": len(chunks), "tokens": sum(c.token_count for c in chunks)}


def sync_directory(reset: bool = False) -> dict:
    """Синхронизирует папку документов с базой: новые/изменённые -> индексируются, удалённые -> удаляются."""
    s = get_settings()
    root = s.documents_path
    root.mkdir(parents=True, exist_ok=True)
    store = get_vector_store()

    with _ingest_lock:
        if reset:
            store.reset()
        kb.reload()
        indexed = {d["doc_id"]: d for d in kb.documents()}
        metadata = load_metadata(root)

        report = {"indexed": [], "skipped": [], "removed": [], "errors": []}
        seen = set()
        for path in list_source_files(root):
            rel = path.relative_to(root).as_posix()
            doc_id = doc_id_for(rel)
            seen.add(doc_id)
            meta = metadata.get(rel, {})
            existing = indexed.get(doc_id)
            if existing and existing["file_hash"] == fingerprint(path, meta):
                report["skipped"].append(rel)
                continue
            try:
                report["indexed"].append(ingest_file(path, root, meta))
                log.info("indexed %s", rel)
            except Exception as e:  # noqa: BLE001
                log.exception("failed %s", rel)
                report["errors"].append({"file_name": rel, "error": str(e)})

        for doc_id, d in indexed.items():
            if doc_id not in seen:
                store.delete_document(doc_id)
                report["removed"].append(d["file_name"])

        kb.reload()
    return report


def ingest_single(path: Path) -> dict:
    root = get_settings().documents_path
    with _ingest_lock:
        rel = path.relative_to(root).as_posix()
        result = ingest_file(path, root, load_metadata(root).get(rel))
        kb.reload()
    return result


def remove_document(doc_id: str) -> str | None:
    root = get_settings().documents_path
    with _ingest_lock:
        doc = next((d for d in kb.documents() if d["doc_id"] == doc_id), None)
        get_vector_store().delete_document(doc_id)
        if doc:
            file = root / doc["file_name"]
            if file.exists():
                file.unlink()
        kb.reload()
    return doc["file_name"] if doc else None


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Индексация документов КБТУ")
    parser.add_argument("--reset", action="store_true", help="удалить коллекцию и проиндексировать заново")
    args = parser.parse_args()
    print(json.dumps(sync_directory(reset=args.reset), ensure_ascii=False, indent=2))
    get_vector_store().client.close()
