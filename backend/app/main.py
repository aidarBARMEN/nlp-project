"""KBTU Smart Assistant — FastAPI backend (RAG)."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAIError

from ingestion.config import PROJECT_DIR
from ingestion.parsers import SUPPORTED_EXTENSIONS

from .config import get_settings
from .rag import generator
from .rag.ingest import (
    get_document_file as document_file,
)
from .rag.ingest import (
    ingest_single,
    remove_document,
    safe_error,
    set_document_trust,
    sync_directory,
)
from .rag.ingest import (
    list_documents as registry_documents,
)
from .rag.knowledge_base import kb
from .rag.llm import MissingAPIKey, close_client, cosine_matrix, embed_texts, is_flagged
from .rag.retriever import hybrid_search, rewrite_with_history
from .rag.tokenization import get_encoding, lexical_tokens
from .rag.vector_store import close_vector_store, get_vector_store
from .schemas import ChatRequest, EmbedRequest, SearchRequest, TokenizeRequest, TrustRequest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.documents_path.mkdir(parents=True, exist_ok=True)
    kb.reload()
    try:
        yield
    finally:
        close_vector_store()
        close_client()


app = FastAPI(title="KBTU Smart Assistant API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(MissingAPIKey)
async def _missing_key(_, exc: MissingAPIKey):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(OpenAIError)
async def _openai_error(_, exc: OpenAIError):
    return JSONResponse(
        status_code=502, content={"detail": "Ошибка OpenAI. Проверьте ключ, квоту и соединение."}
    )


@app.exception_handler(ValueError)
async def _invalid_input(_, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# ---------------------------------------------------------------- system
@app.get("/api/health")
def health():
    kb.reload()
    docs = registry_documents()
    return {
        "status": "ok",
        "openai_key": settings.has_openai_key,
        "chat_model": settings.openai_chat_model,
        "embedding_model": settings.openai_embedding_model,
        "vector_db": f"Qdrant ({get_vector_store().mode})",
        "reranker": settings.reranker,
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        **kb.stats(),
        "documents": len(docs),
        "pending_documents": sum(d["status"] == "pending" for d in docs),
        "embedding_dimensions": settings.dense_dimensions,
    }


# ---------------------------------------------------------------- documents
@app.get("/api/documents")
def list_documents():
    return registry_documents()


@app.post("/api/documents/upload")
def upload_documents(files: Annotated[list[UploadFile], File()]):
    root = settings.documents_path
    results, errors = [], []
    for f in files:
        name = Path(f.filename or "file").name
        if Path(name).suffix.lower() not in SUPPORTED_EXTENSIONS:
            errors.append({"file_name": name, "error": "Неподдерживаемый формат"})
            continue
        name = re.sub(r'[<>:"/\\|?*]', "_", name)
        data = f.file.read(settings.max_file_mb * 1024 * 1024 + 1)
        if len(data) > settings.max_file_mb * 1024 * 1024:
            errors.append({"file_name": name, "error": "Файл превышает MAX_FILE_MB"})
            continue
        dest = root / hashlib.sha256(data).hexdigest() / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        try:
            results.append(ingest_single(dest))
        except MissingAPIKey:
            raise
        except Exception as e:  # noqa: BLE001
            errors.append({"file_name": name, "error": safe_error(e)})
    return {"indexed": results, "errors": errors}


@app.post("/api/documents/sync")
def sync_documents(reset: bool = False):
    """Импорт inbox и индексация подготовленных документов без удаления исходников."""
    return sync_directory(reset=reset)


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str):
    name = remove_document(doc_id)
    if not name:
        raise HTTPException(404, "Документ не найден")
    return {"deleted": name}


@app.get("/api/documents/{doc_id}/file")
def get_document_file(doc_id: str):
    try:
        path, filename, mime = document_file(doc_id)
    except (KeyError, FileNotFoundError):
        raise HTTPException(404, "Документ не найден") from None
    return FileResponse(
        path,
        filename=filename,
        media_type=mime,
        content_disposition_type="inline" if mime == "application/pdf" else "attachment",
    )


@app.post("/api/documents/{doc_id}/trust")
def document_trust(doc_id: str, request: TrustRequest):
    try:
        return set_document_trust(doc_id, request.trust_level, request.reason)
    except KeyError:
        raise HTTPException(404, "Документ не найден") from None


# ---------------------------------------------------------------- RAG
def _source(n: int, c: dict) -> dict:
    keys = (
        "id",
        "doc_id",
        "title",
        "file_name",
        "section",
        "page_start",
        "page_end",
        "url",
        "text",
        "dense_score",
        "dense_rank",
        "bm25_score",
        "bm25_rank",
        "rrf_score",
        "rerank_score",
        "token_count",
    )
    return {"n": n, **{k: c.get(k) for k in keys}}


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def knowledge_not_ready_message() -> str:
    docs = registry_documents()
    if any(d["status"] == "processed" and d["trust_level"] == "unverified" for d in docs):
        return (
            "Документы загружены, но пока не подтверждены. Во вкладке «База знаний» "
            "нажмите «Подтвердить» рядом с официальным документом КБТУ, затем повторите вопрос."
        )
    if any(d["status"] == "pending" for d in docs):
        return (
            "Документы подготовлены, но ещё не проиндексированы. "
            "Нажмите «Обновить базу» во вкладке «База знаний», затем повторите вопрос."
        )
    return (
        "Нет действующих проиндексированных официальных документов. "
        "Подготовьте и подтвердите источники во вкладке «База знаний»."
    )


@app.post("/api/chat/stream")
def chat_stream(req: ChatRequest):
    history = [m.model_dump() for m in req.history]

    def events():
        t0 = time.perf_counter()
        try:
            kb.reload()
            if settings.moderation and is_flagged(req.question):
                yield _sse(
                    "token",
                    "Запрос отклонён фильтром безопасности. Пожалуйста, переформулируйте вопрос.",
                )
                yield _sse("done", {})
                return
            if not kb.chunks:
                yield _sse(
                    "token",
                    knowledge_not_ready_message(),
                )
                yield _sse("done", {})
                return

            query = (
                rewrite_with_history(req.question, history)
                if settings.query_rewrite
                else req.question
            )
            found = hybrid_search(query)
            t_retrieval = time.perf_counter() - t0
            sources = [_source(i, c) for i, c in enumerate(found["results"], start=1)]
            yield _sse(
                "sources",
                {"query": query, "expanded_query": found["expanded_query"], "sources": sources},
            )

            for token in generator.stream_answer(req.question, found["results"], history):
                yield _sse("token", token)
            yield _sse(
                "done",
                {
                    "retrieval_ms": round(t_retrieval * 1000),
                    "total_ms": round((time.perf_counter() - t0) * 1000),
                },
            )
        except (MissingAPIKey, ValueError) as e:
            yield _sse("error", {"detail": str(e)})
        except OpenAIError:
            yield _sse("error", {"detail": "Ошибка OpenAI. Проверьте ключ, квоту и соединение."})
        except Exception:  # noqa: BLE001
            logging.exception("chat failed")
            yield _sse(
                "error", {"detail": "Внутренняя ошибка сервера. Подробности в журнале backend."}
            )

    return StreamingResponse(
        events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )


@app.post("/api/chat")
def chat(req: ChatRequest):
    kb.reload()
    history = [m.model_dump() for m in req.history]
    if not kb.chunks:
        return {"answer": knowledge_not_ready_message(), "sources": []}
    query = rewrite_with_history(req.question, history) if settings.query_rewrite else req.question
    found = hybrid_search(query)
    return {
        "answer": generator.answer(req.question, found["results"], history),
        "query": query,
        "sources": [_source(i, c) for i, c in enumerate(found["results"], start=1)],
    }


@app.post("/api/search")
def search(req: SearchRequest):
    """Отладка поиска: показывает ранги dense / BM25 / RRF / rerank для каждого кандидата."""
    found = hybrid_search(req.query, final_k=req.top_k, rerank=req.rerank)
    return {
        "query": req.query,
        "expanded_query": found["expanded_query"],
        "results": [_source(i, c) for i, c in enumerate(found["candidates"], start=1)],
    }


# ---------------------------------------------------------------- NLP lab
@app.post("/api/nlp/tokenize")
def tokenize(req: TokenizeRequest):
    model = req.model or settings.openai_embedding_model
    enc = get_encoding(model)
    ids = enc.encode(req.text, disallowed_special=())
    return {
        "encoding": enc.name,
        "model": model,
        "token_count": len(ids),
        "char_count": len(req.text),
        "tokens": [
            {"id": i, "text": enc.decode_single_token_bytes(i).decode("utf-8", errors="replace")}
            for i in ids[:2000]
        ],
        "bm25_tokens": lexical_tokens(req.text),
    }


@app.post("/api/nlp/embed")
def embed(req: EmbedRequest):
    texts = [t.strip() for t in req.texts if t.strip()]
    if not texts:
        raise HTTPException(400, "Пустой ввод")
    vectors = embed_texts(texts)
    return {
        "model": settings.openai_embedding_model,
        "dimensions": len(vectors[0]),
        "texts": texts,
        "preview": [[round(x, 4) for x in v[:24]] for v in vectors],
        "similarity": cosine_matrix(vectors),
    }


# A production build can be served from the same origin as the API.
frontend_dist = PROJECT_DIR / "frontend" / "dist"
if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
