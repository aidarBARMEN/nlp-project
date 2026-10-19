"""Оценка качества моделей: датасет вопросов, метрики поиска и генерации.

Запуск — фоновой задачей в процессе backend (встроенный Qdrant однопроцессный):
    POST /api/eval/run {"kind": "dataset" | "retrieval" | "generation"}
    GET  /api/eval/status, GET /api/eval/results

Файлы: DATA_DIR/eval/dataset.json (можно дополнять вручную, "source": "manual"),
       DATA_DIR/eval/results/{retrieval,generation}.json, DATA_DIR/eval/cache/*.npy
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import random
import re
import threading
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from ingestion.services.indexer import knowledge_filter

from ..config import get_settings
from .generator import NO_ANSWER, build_messages
from .knowledge_base import kb
from .llm import get_client
from .models import complete, embed, get_local_embedder, list_embedders, list_llms
from .retriever import RRF_K, hybrid_search
from .vector_store import get_vector_store

log = logging.getLogger("evaluation")

# Вопросы, ответа на которые в документах КБТУ нет: проверяем, что модель честно отказывается.
UNANSWERABLE = [
    "Кто выиграл чемпионат мира по футболу в 2018 году?",
    "Какой сегодня курс доллара к тенге?",
    "Сколько стоит обучение в Массачусетском технологическом институте?",
    "Напиши программу на Python для сортировки списка.",
    "Какая погода будет в Алматы завтра?",
    "Кто написал роман «Война и мир»?",
    "Как приготовить плов?",
    "Какой пароль от моего аккаунта Uninet?",
]

REFUSAL_MARKERS = (
    "нет информации",
    "не содержится",
    "отсутствует информация",
    "информации нет",
    "не найден",
    "не указан",
    "no information",
    "not contain",
    "мәлімет жоқ",
)

# ---------------------------------------------------------------- job state
_lock = threading.Lock()
_job: dict = {"running": False}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _paths() -> dict[str, Path]:
    root = get_settings().eval_dir
    paths = {
        "root": root,
        "dataset": root / "dataset.json",
        "results": root / "results",
        "cache": root / "cache",
    }
    paths["results"].mkdir(parents=True, exist_ok=True)
    paths["cache"].mkdir(parents=True, exist_ok=True)
    return paths


def _progress(stage: str, done: int | None = None, total: int | None = None) -> None:
    with _lock:
        _job.update(stage=stage)
        if done is not None:
            _job.update(done=done, total=total)


def status() -> dict:
    with _lock:
        return dict(_job)


def start(kind: str, models: list[str] | None = None, limit: int | None = None) -> dict:
    with _lock:
        if _job.get("running"):
            raise ValueError(f"Уже выполняется оценка: {_job.get('kind')}")
        _job.clear()
        _job.update(
            running=True,
            kind=kind,
            stage="подготовка",
            done=0,
            total=0,
            started_at=_now(),
            error=None,
        )
    runner = {"dataset": build_dataset, "retrieval": eval_retrieval, "generation": eval_generation}[
        kind
    ]

    def run():
        try:
            runner(models or [], limit)
            with _lock:
                _job.update(running=False, stage="готово", finished_at=_now())
        except Exception as e:  # noqa: BLE001
            log.error("evaluation failed:\n%s", traceback.format_exc())
            with _lock:
                _job.update(running=False, stage="ошибка", error=str(e), finished_at=_now())

    threading.Thread(target=run, daemon=True, name=f"eval-{kind}").start()
    return status()


def results() -> dict:
    p = _paths()
    out = {"dataset": None, "retrieval": None, "generation": None}
    if p["dataset"].exists():
        data = json.loads(p["dataset"].read_text(encoding="utf-8"))
        items = data.get("items", [])
        out["dataset"] = {
            "created_at": data.get("created_at"),
            "total": len(items),
            "answerable": sum(i.get("answerable", True) for i in items),
            "unanswerable": sum(not i.get("answerable", True) for i in items),
            "sample": items[:5],
        }
    for kind in ("retrieval", "generation"):
        f = p["results"] / f"{kind}.json"
        if f.exists():
            out[kind] = json.loads(f.read_text(encoding="utf-8"))
    return out


def _save(name: str, data: dict) -> None:
    f = _paths()["results"] / f"{name}.json"
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _corpus() -> dict[str, dict]:
    kb.reload()
    chunks = {i: c for i, c in kb.chunks.items() if (c.get("text") or "").strip()}
    if not chunks:
        raise ValueError("База знаний пуста — сначала проиндексируйте документы")
    return chunks


def _load_dataset() -> list[dict]:
    f = _paths()["dataset"]
    if not f.exists():
        raise ValueError("Датасет не создан — сначала нажмите «Создать датасет»")
    return json.loads(f.read_text(encoding="utf-8"))["items"]


def _retry(fn, attempts: int = 3, delay: float = 5.0):
    """Повтор при сетевых сбоях и rate limit (429): длинный прогон не должен падать из-за одного запроса."""
    for i in range(attempts):
        try:
            return fn()
        except (ValueError, KeyError):
            raise
        except Exception as e:  # noqa: BLE001
            if i == attempts - 1:
                raise
            log.warning("retry %d/%d after error: %s", i + 1, attempts, e)
            time.sleep(delay * (i + 1))


def _judge_json(system: str, user: str) -> dict:
    resp = _retry(
        lambda: get_client().chat.completions.create(
            model=get_settings().eval_judge_model,
            temperature=0,
            response_format={"type": "json_object"},
            # режим json_object требует слова "json" в промпте
            messages=[
                {"role": "system", "content": f"{system}\nОтвет — только JSON-объект (json)."},
                {"role": "user", "content": user},
            ],
        )
    )
    return json.loads(resp.choices[0].message.content or "{}")


# ---------------------------------------------------------------- dataset
def build_dataset(_models: list[str], limit: int | None) -> None:
    """Синтетический датасет: для случайных чанков LLM формулирует вопрос студента и эталонный ответ.

    Эталонный (gold) чанк известен заранее — по нему считаются метрики поиска.
    """
    target = limit or 40
    chunks = _corpus()
    rng = random.Random(42)

    by_doc: dict[str, list[str]] = {}
    for cid, c in chunks.items():
        if len(c["text"]) >= 300:
            by_doc.setdefault(c["doc_id"], []).append(cid)
    for ids in by_doc.values():
        rng.shuffle(ids)
    # равномерно по документам, чтобы большие PDF не забивали датасет
    order, docs = [], list(by_doc)
    rng.shuffle(docs)
    while len(order) < target * 2 and any(by_doc.values()):
        for d in docs:
            if by_doc[d]:
                order.append(by_doc[d].pop())

    system = (
        "Ты помогаешь составить тестовый набор для RAG-ассистента университета КБТУ. "
        "По фрагменту официального документа придумай ОДИН реалистичный вопрос студента на русском языке, "
        "ответ на который содержится в этом фрагменте, и краткий точный эталонный ответ по фрагменту. "
        "Вопрос не должен ссылаться на «фрагмент» или «текст» и должен быть понятен без него. "
        'Если во фрагменте нет полезных фактов (меню, новости без фактов, оглавление), верни {"question": null}. '
        'Формат: {"question": "...", "answer": "..."}'
    )
    items: list[dict] = []
    failures = 0
    for cid in order:
        if len(items) >= target:
            break
        _progress("генерация вопросов", len(items), target)
        c = chunks[cid]
        try:
            qa = _judge_json(system, f"Документ: {c.get('title')}\n\nФрагмент:\n{c['text'][:3000]}")
            failures = 0
        except Exception as e:  # noqa: BLE001
            log.warning("question generation failed for %s: %s", cid, e)
            failures += 1
            if failures >= 5:
                raise RuntimeError(f"Генерация вопросов не работает: {e}") from e
            continue
        if not qa.get("question"):
            continue
        items.append(
            {
                "id": f"q{len(items) + 1:03d}",
                "question": qa["question"].strip(),
                "answer": (qa.get("answer") or "").strip(),
                "chunk_id": cid,
                "doc_id": c["doc_id"],
                "title": c.get("title"),
                "answerable": True,
                "source": "synthetic",
            }
        )

    if not items:
        raise RuntimeError("Не удалось сгенерировать ни одного вопроса по базе знаний")
    items += [
        {
            "id": f"u{i + 1:03d}",
            "question": q,
            "answer": NO_ANSWER,
            "chunk_id": None,
            "doc_id": None,
            "title": None,
            "answerable": False,
            "source": "synthetic",
        }
        for i, q in enumerate(UNANSWERABLE)
    ]
    # ручные вопросы из прошлого датасета сохраняем
    f = _paths()["dataset"]
    if f.exists():
        old = json.loads(f.read_text(encoding="utf-8")).get("items", [])
        items += [i for i in old if i.get("source") == "manual"]

    f.write_text(
        json.dumps(
            {"created_at": _now(), "corpus_chunks": len(chunks), "items": items},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    _progress("готово", len(items), len(items))


# ---------------------------------------------------------------- retrieval
def _openai_matrix(ids: list[str]) -> np.ndarray:
    """Векторы OpenAI уже лежат в Qdrant — берём их, а не пересчитываем за деньги."""
    store = get_vector_store()
    vectors: dict[str, list[float]] = {}
    with store.lock:
        offset = None
        while True:
            points, offset = store.client.scroll(
                store.collection,
                scroll_filter=knowledge_filter(),
                limit=256,
                offset=offset,
                with_payload=False,
                with_vectors=["dense"],
            )
            for p in points:
                v = p.vector["dense"] if isinstance(p.vector, dict) else p.vector
                vectors[str(p.id)] = v
            if offset is None:
                break
    m = np.array([vectors[i] for i in ids], dtype=np.float32)
    return m / (np.linalg.norm(m, axis=1, keepdims=True) + 1e-12)


def _local_matrix(name: str, ids: list[str], texts: list[str]) -> np.ndarray:
    key = hashlib.sha1((name + "\n".join(ids) + "".join(texts)).encode("utf-8")).hexdigest()[:16]
    cache = _paths()["cache"] / f"{re.sub(r'[^A-Za-z0-9.-]+', '_', name)}_{key}.npy"
    if cache.exists():
        return np.load(cache)
    embedder = get_local_embedder(name)
    m = embedder.encode(
        texts, kind="passage", progress=lambda d, t: _progress(f"индексация корпуса: {name}", d, t)
    )
    np.save(cache, m)
    return m


def _rank_metrics(ranked: list[str], gold: str, ranked_docs: list[str], gold_doc: str) -> dict:
    rank = ranked.index(gold) + 1 if gold in ranked[:10] else None
    return {
        "rank": rank,
        "hit@1": float(rank == 1),
        "hit@3": float(rank is not None and rank <= 3),
        "hit@5": float(rank is not None and rank <= 5),
        "hit@10": float(rank is not None),
        "mrr@10": 1.0 / rank if rank else 0.0,
        # один релевантный документ -> IDCG = 1
        "ndcg@10": 1.0 / math.log2(rank + 1) if rank else 0.0,
        "doc_hit@5": float(gold_doc in ranked_docs[:5]),
    }


def _rrf(*rankings: list[str], k: int = RRF_K) -> list[str]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for r, cid in enumerate(ranking, start=1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + r)
    return sorted(scores, key=scores.get, reverse=True)


def _docs_of(ranked: list[str], chunks: dict[str, dict]) -> list[str]:
    seen, out = set(), []
    for cid in ranked:
        d = chunks[cid]["doc_id"]
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def _aggregate(rows: list[dict], keys: list[str]) -> dict:
    return {
        k: round(float(np.mean([r[k] for r in rows if r.get(k) is not None] or [0])), 4)
        for k in keys
    }


def eval_retrieval(models: list[str], limit: int | None) -> None:
    chunks = _corpus()
    items = [
        i for i in _load_dataset() if i.get("answerable", True) and i.get("chunk_id") in chunks
    ]
    if limit:
        items = items[:limit]
    if not items:
        raise ValueError(
            "В датасете нет вопросов, чьи эталонные чанки есть в текущей базе — пересоздайте датасет"
        )

    ids = list(chunks)
    texts = [chunks[i]["text"] for i in ids]
    questions = [i["question"] for i in items]
    available = [
        m for m in list_embedders() if m["available"] and (not models or m["id"] in models)
    ]
    metric_keys = ["hit@1", "hit@3", "hit@5", "hit@10", "mrr@10", "ndcg@10", "doc_hit@5"]

    # BM25 — общий лексический baseline
    _progress("BM25", 0, len(items))
    bm25_rank = [[cid for cid, _ in kb.bm25_search(q, 20)] for q in questions]

    methods: list[dict] = []
    per_question: dict[str, dict] = {
        i["id"]: {"question": i["question"], "ranks": {}} for i in items
    }

    def add_method(name: str, family: str, rankings: list[list[str]], extra: dict) -> None:
        rows = [
            _rank_metrics(r, it["chunk_id"], _docs_of(r[:20], chunks), it["doc_id"])
            for r, it in zip(rankings, items, strict=True)
        ]
        for row, it in zip(rows, items, strict=True):
            per_question[it["id"]]["ranks"][name] = row["rank"]
        methods.append({"method": name, "family": family, **_aggregate(rows, metric_keys), **extra})

    add_method("BM25", "lexical", bm25_rank, {"model": "bm25", "dimensions": None})

    for m in available:
        model_id, label = m["id"], m["label"]
        provider, _, name = model_id.partition(":")
        t0 = time.perf_counter()
        _progress(f"индексация корпуса: {label}")
        matrix = _openai_matrix(ids) if provider == "openai" else _local_matrix(name, ids, texts)
        index_s = time.perf_counter() - t0

        # латентность — по одному запросу, как в реальном чате
        latencies, qvecs = [], []
        for n, q in enumerate(questions):
            _progress(f"запросы: {label}", n, len(questions))
            t = time.perf_counter()
            qvecs.append(embed(model_id, [q], kind="query")[0])
            latencies.append((time.perf_counter() - t) * 1000)
        scores = np.vstack(qvecs) @ matrix.T
        dense_rank = [[ids[j] for j in np.argsort(-row)[:20]] for row in scores]

        extra = {
            "model": model_id,
            "provider": provider,
            "dimensions": int(matrix.shape[1]),
            "max_seq_length": None
            if provider == "openai"
            else get_local_embedder(name).max_seq_length,
            "query_ms_mean": round(float(np.mean(latencies)), 1),
            "query_ms_p95": round(float(np.percentile(latencies, 95)), 1),
            "index_s": round(index_s, 1),
        }
        add_method(f"{label}", "dense", dense_rank, extra)
        add_method(
            f"{label} + BM25",
            "hybrid",
            [_rrf(d, b) for d, b in zip(dense_rank, bm25_rank, strict=True)],
            extra,
        )

    _save(
        "retrieval",
        {
            "created_at": _now(),
            "questions": len(items),
            "corpus_chunks": len(ids),
            "metrics": metric_keys,
            "methods": methods,
            "per_question": list(per_question.values()),
        },
    )


# ---------------------------------------------------------------- generation
JUDGE_SYSTEM = """Ты — строгий эксперт по оценке ответов RAG-системы университета КБТУ.
Дано: контекст (фрагменты документов), вопрос, эталонный ответ и ответ модели. Оцени ответ модели:
- faithfulness: доля утверждений ответа, которые подтверждаются контекстом (0.0–1.0). Отказ без утверждений = 1.0.
- relevance: насколько ответ отвечает именно на заданный вопрос (1–5).
- correctness: насколько ответ совпадает по смыслу с эталонным ответом (1–5).
Ответ строго в JSON: {"faithfulness": <число>, "relevance": <1-5>, "correctness": <1-5>, "comment": "<кратко>"}"""


def is_refusal(answer: str) -> bool:
    a = answer.lower()
    return any(m in a for m in REFUSAL_MARKERS)


def has_citation(answer: str, n_sources: int) -> bool:
    return any(1 <= int(n) <= n_sources for n in re.findall(r"\[(\d{1,2})\]", answer))


def cyrillic_share(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    return (
        sum("а" <= c.lower() <= "я" or c.lower() in "ёәғқңөұүһі" for c in letters) / len(letters)
        if letters
        else 0.0
    )


def eval_generation(models: list[str], limit: int | None) -> None:
    from .generator import format_context

    items = _load_dataset()
    answerable = [i for i in items if i.get("answerable", True)]
    unanswerable = [i for i in items if not i.get("answerable", True)]
    if limit:
        answerable = answerable[:limit]
        unanswerable = unanswerable[: max(2, limit // 4)]
    items = answerable + unanswerable

    llms = [m for m in list_llms() if m["available"] and (not models or m["id"] in models)]
    if not llms:
        raise ValueError("Нет доступных LLM (проверьте ключ OpenAI и запущен ли Ollama)")

    # один и тот же поиск для всех моделей — сравниваем только генерацию
    contexts: dict[str, list[dict]] = {}
    for n, it in enumerate(items):
        _progress("поиск контекста", n, len(items))
        try:
            contexts[it["id"]] = _retry(lambda q=it["question"]: hybrid_search(q)["results"])
        except Exception as e:  # noqa: BLE001
            log.warning("retrieval failed for %s, question skipped: %s", it["id"], e)
    items = [it for it in items if it["id"] in contexts]
    if not items:
        raise RuntimeError(
            "Поиск контекста не удался ни для одного вопроса — проверьте соединение с OpenAI"
        )

    summary, answers = [], []
    for m in llms:
        rows = []
        for n, it in enumerate(items):
            _progress(f"генерация: {m['label']}", n, len(items))
            ctx = contexts[it["id"]]
            try:
                text, stats = _retry(
                    lambda m_id=m["id"], q=it["question"], c=ctx: complete(
                        m_id, build_messages(q, c, [])
                    )
                )
            except Exception as e:  # noqa: BLE001
                rows.append({"id": it["id"], "model": m["id"], "error": str(e)[:300]})
                continue
            row = {
                "id": it["id"],
                "model": m["id"],
                "answerable": it.get("answerable", True),
                "answer": text,
                "refused": is_refusal(text),
                "cited": has_citation(text, len(ctx)),
                "lang_ok": cyrillic_share(text) >= 0.5,
                "latency_s": round(stats.total_s or 0, 2),
                "ttft_s": round(stats.first_token_s or 0, 2),
                "tokens_per_s": stats.tokens_per_s,
            }
            if row["answerable"]:
                _progress(f"оценка ответов: {m['label']}", n, len(items))
                try:
                    j = _judge_json(
                        JUDGE_SYSTEM,
                        f"Контекст:\n{format_context(ctx)[:12000]}\n\nВопрос: {it['question']}\n\n"
                        f"Эталонный ответ: {it['answer']}\n\nОтвет модели:\n{text[:4000]}",
                    )
                    row.update(
                        faithfulness=max(0.0, min(1.0, float(j.get("faithfulness", 0)))),
                        relevance=max(1.0, min(5.0, float(j.get("relevance", 1)))),
                        correctness=max(1.0, min(5.0, float(j.get("correctness", 1)))),
                        judge_comment=str(j.get("comment", ""))[:300],
                    )
                except Exception as e:  # noqa: BLE001
                    log.warning("judge failed: %s", e)
            rows.append(row)

        ok = [r for r in rows if "error" not in r]
        ans = [r for r in ok if r["answerable"]]
        una = [r for r in ok if not r["answerable"]]

        def mean(values):
            values = [v for v in values if v is not None]
            return round(float(np.mean(values)), 3) if values else None

        summary.append(
            {
                "model": m["id"],
                "label": m["label"],
                "provider": m["provider"],
                "n": len(ok),
                "errors": len(rows) - len(ok),
                "faithfulness": mean([r.get("faithfulness") for r in ans]),
                "relevance": mean([r.get("relevance") for r in ans]),
                "correctness": mean([r.get("correctness") for r in ans]),
                "refusal_accuracy": mean([float(r["refused"]) for r in una]),
                "false_refusal_rate": mean([float(r["refused"]) for r in ans]),
                "citation_rate": mean([float(r["cited"]) for r in ans if not r["refused"]]),
                "language_ok": mean([float(r["lang_ok"]) for r in ok]),
                "latency_s": mean([r["latency_s"] for r in ok]),
                "ttft_s": mean([r["ttft_s"] for r in ok]),
                "tokens_per_s": mean([r["tokens_per_s"] for r in ok]),
            }
        )
        answers += rows
        # промежуточное сохранение: долгий прогон не теряется при ошибке следующей модели
        _save("generation", _generation_report(summary, answers, items))

    _save("generation", _generation_report(summary, answers, items))


def _generation_report(summary: list[dict], answers: list[dict], items: list[dict]) -> dict:
    questions = {i["id"]: {"question": i["question"], "reference": i["answer"]} for i in items}
    return {
        "created_at": _now(),
        "judge": get_settings().eval_judge_model,
        "questions": len(items),
        "answerable": sum(i.get("answerable", True) for i in items),
        "models": summary,
        "answers": [{**a, **questions.get(a["id"], {})} for a in answers],
    }
