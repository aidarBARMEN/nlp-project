"""KBTU Smart Assistant — FastAPI backend (RAG)."""
from __future__ import annotations

import json
import logging
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from openai import OpenAIError

from .config import get_settings
from .rag import generator
from .rag.ingest import ingest_single, remove_document, sync_directory
from .rag.knowledge_base import kb
from .rag.llm import MissingAPIKey, cosine_matrix, embed_texts, is_flagged
from .rag.parsing import SUPPORTED_EXTENSIONS
from .rag.retriever import hybrid_search, rewrite_with_history
from .rag.tokenization import get_encoding, lexical_tokens
from .rag.vector_store import get_vector_store
from .schemas import ChatRequest, EmbedRequest, SearchRequest, TokenizeRequest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.documents_path.mkdir(parents=True, exist_ok=True)
    kb.reload()
    yield
    get_vector_store().client.close()


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
    return JSONResponse(status_code=502, content={"detail": f"Ошибка OpenAI: {exc}"})


# ---------------------------------------------------------------- system
@app.get("/api/health")
def health():
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
    }


# ---------------------------------------------------------------- documents
@app.get("/api/documents")
def list_documents():
    return kb.documents()


@app.post("/api/documents/upload")
def upload_documents(files: list[UploadFile] = File(...)):
    root = settings.documents_path
    results, errors = [], []
    for f in files:
        name = Path(f.filename or "file").name
        if Path(name).suffix.lower() not in SUPPORTED_EXTENSIONS:
            errors.append({"file_name": name, "error": "Неподдерживаемый формат"})
            continue
        name = re.sub(r'[<>:"/\\|?*]', "_", name)
        dest = root / name
        dest.write_bytes(f.file.read())
        try:
            results.append(ingest_single(dest))
        except MissingAPIKey:
            raise
        except Exception as e:  # noqa: BLE001
            errors.append({"file_name": name, "error": str(e)})
    return {"indexed": results, "errors": errors}


@app.post("/api/documents/sync")
def sync_documents(reset: bool = False):
    """Переиндексировать папку data/documents (новые, изменённые и удалённые файлы)."""
    return sync_directory(reset=reset)


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str):
    name = remove_document(doc_id)
    if not name:
        raise HTTPException(404, "Документ не найден")
    return {"deleted": name}


@app.get("/api/documents/{doc_id}/file")
def get_document_file(doc_id: str):
    doc = next((d for d in kb.documents() if d["doc_id"] == doc_id), None)
    if not doc:
        raise HTTPException(404, "Документ не найден")
    path = (settings.documents_path / doc["file_name"]).resolve()
    if not path.is_relative_to(settings.documents_path) or not path.exists():
        raise HTTPException(404, "Файл не найден на диске")
    return FileResponse(path, filename=path.name, content_disposition_type="inline")


# ---------------------------------------------------------------- RAG
def _source(n: int, c: dict) -> dict:
    keys = ("id", "doc_id", "title", "file_name", "section", "page_start", "page_end", "url", "text",
            "dense_score", "dense_rank", "bm25_score", "bm25_rank", "rrf_score", "rerank_score", "token_count")
    return {"n": n, **{k: c.get(k) for k in keys}}


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/api/chat/stream")
def chat_stream(req: ChatRequest):
    history = [m.model_dump() for m in req.history]

    def events():
        t0 = time.perf_counter()
        try:
            if settings.moderation and is_flagged(req.question):
                yield _sse("token", "Запрос отклонён фильтром безопасности. Пожалуйста, переформулируйте вопрос.")
                yield _sse("done", {})
                return
            if not kb.chunks:
                yield _sse("token", "База знаний пока пуста — загрузите документы во вкладке «База знаний».")
                yield _sse("done", {})
                return

            query = rewrite_with_history(req.question, history) if settings.query_rewrite else req.question
            found = hybrid_search(query)
            t_retrieval = time.perf_counter() - t0
            sources = [_source(i, c) for i, c in enumerate(found["results"], start=1)]
            yield _sse("sources", {"query": query, "expanded_query": found["expanded_query"], "sources": sources})

            for token in generator.stream_answer(req.question, found["results"], history):
                yield _sse("token", token)
            yield _sse("done", {"retrieval_ms": round(t_retrieval * 1000), "total_ms": round((time.perf_counter() - t0) * 1000)})
        except (MissingAPIKey, OpenAIError) as e:
            yield _sse("error", {"detail": str(e)})
        except Exception as e:  # noqa: BLE001
            logging.exception("chat failed")
            yield _sse("error", {"detail": f"Внутренняя ошибка: {e}"})

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.post("/api/chat")
def chat(req: ChatRequest):
    history = [m.model_dump() for m in req.history]
    if not kb.chunks:
        return {"answer": "База знаний пуста.", "sources": []}
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
    ids = enc.encode(req.text)
    return {
        "encoding": enc.name,
        "model": model,
        "token_count": len(ids),
        "char_count": len(req.text),
        "tokens": [{"id": i, "text": enc.decode_single_token_bytes(i).decode("utf-8", errors="replace")} for i in ids[:2000]],
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
