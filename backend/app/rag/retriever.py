"""Retrieval: обработка запроса -> гибридный поиск (Dense + BM25) -> RRF -> реранкинг."""
from __future__ import annotations

import json
import logging
import re
from functools import lru_cache

from ..config import BACKEND_DIR, get_settings
from .knowledge_base import kb
from .llm import embed_query, get_client
from .vector_store import get_vector_store

log = logging.getLogger("retriever")
RRF_K = 60


@lru_cache
def _abbreviations() -> dict[str, str]:
    path = BACKEND_DIR / "data" / "abbreviations.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k.lower(): v for k, v in data.items() if not k.startswith("_")}


def expand_abbreviations(query: str) -> str:
    abbr = _abbreviations()
    found = []
    for token in re.findall(r"[\w/]+", query):
        exp = abbr.get(token.lower())
        if exp and exp.lower() not in query.lower():
            found.append(f"{token} = {exp}")
    return f"{query} ({'; '.join(found)})" if found else query


def rewrite_with_history(question: str, history: list[dict]) -> str:
    """Превращает уточняющий вопрос ("а для магистров?") в самостоятельный поисковый запрос."""
    if not history:
        return question
    dialog = "\n".join(f"{m['role']}: {m['content'][:500]}" for m in history[-6:])
    resp = get_client().chat.completions.create(
        model=get_settings().openai_chat_model,
        temperature=0,
        messages=[
            {"role": "system", "content": (
                "Перепиши последний вопрос пользователя в самостоятельный поисковый запрос по документам КБТУ, "
                "раскрыв местоимения и контекст из диалога. Сохрани язык вопроса. Верни только запрос."
            )},
            {"role": "user", "content": f"Диалог:\n{dialog}\n\nПоследний вопрос: {question}"},
        ],
    )
    return (resp.choices[0].message.content or question).strip()


def llm_rerank(query: str, candidates: list[dict]) -> list[dict]:
    """Переранжировка кандидатов LLM-судьёй (аналог cross-encoder): оценка релевантности 0–10."""
    passages = "\n\n".join(
        f"[{i}] ({c['title']}; {c.get('section') or '-'})\n{c['text'][:900]}" for i, c in enumerate(candidates)
    )
    resp = get_client().chat.completions.create(
        model=get_settings().openai_chat_model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": (
                "Ты — реранкер для поисковой системы. Оцени, насколько каждый фрагмент помогает ответить на вопрос, "
                "по шкале 0–10 (10 — содержит прямой ответ, 0 — не относится). "
                'Ответ строго в JSON: {"scores": [{"i": <номер>, "s": <оценка>}, ...]} для всех фрагментов.'
            )},
            {"role": "user", "content": f"Вопрос: {query}\n\nФрагменты:\n{passages}"},
        ],
    )
    try:
        scores = {int(x["i"]): float(x["s"]) for x in json.loads(resp.choices[0].message.content)["scores"]}
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        log.warning("reranker returned invalid JSON, keeping RRF order")
        return candidates
    for i, c in enumerate(candidates):
        c["rerank_score"] = scores.get(i, 0.0)
    return sorted(candidates, key=lambda c: (c["rerank_score"], c["rrf_score"]), reverse=True)


def hybrid_search(query: str, final_k: int | None = None, rerank: bool | None = None) -> dict:
    s = get_settings()
    final_k = final_k or s.final_k
    rerank = (s.reranker == "llm") if rerank is None else rerank
    expanded = expand_abbreviations(query)

    dense = get_vector_store().search(embed_query(expanded), s.candidates_k)
    sparse = kb.bm25_search(expanded, s.candidates_k)

    # Reciprocal Rank Fusion
    fused: dict[str, dict] = {}
    for kind, results in (("dense", dense), ("bm25", sparse)):
        for rank, (pid, score) in enumerate(results, start=1):
            entry = fused.setdefault(pid, {"id": pid, "rrf_score": 0.0})
            entry[f"{kind}_score"] = round(score, 4)
            entry[f"{kind}_rank"] = rank
            entry["rrf_score"] += 1.0 / (RRF_K + rank)

    candidates = []
    for entry in sorted(fused.values(), key=lambda e: e["rrf_score"], reverse=True)[: s.rerank_k]:
        payload = kb.chunks.get(entry["id"])
        if not payload:
            continue
        candidates.append({**entry, **{k: v for k, v in payload.items() if k != "bm25_tokens"}})

    if rerank and len(candidates) > 1:
        candidates = llm_rerank(query, candidates)

    return {"query": query, "expanded_query": expanded, "results": candidates[:final_k], "candidates": candidates}
