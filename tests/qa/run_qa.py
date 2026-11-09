"""QA-прогон KBTU Smart Assistant против запущенного backend.

    python tests/qa/run_qa.py                      # всё, результаты в data/qa/results.json
    python tests/qa/run_qa.py --models openai:gpt-4o-mini --skip-gates

Требуется запущенный сервер (uvicorn backend.app.main:app --port 8000).
Письма проверяются локально через POST /api/email/reply с save_draft=false (n8n не нужен).
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cases import CATEGORIES, EMAILS  # noqa: E402

BASE = "http://127.0.0.1:8000"
OUT = ROOT / "data" / "qa" / "results.json"
DEFAULT_MODELS = ["openai:gpt-4o-mini", "groq:qwen/qwen3.8-27b"]
REFUSAL = re.compile(
    r"нет информации|не содержится|отсутствует информация|информации нет|не могу (помочь|ответить|предоставить|выполнить)"
    r"|no information|not contain|cannot (help|provide|answer)|мәлімет жоқ|ақпарат жоқ",
    re.I,
)


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# ---------------------------------------------------------------- проверки ответа
def detect_lang(text: str) -> str:
    letters = [c.lower() for c in text if c.isalpha()]
    if not letters:
        return "?"
    kaz = sum(c in "әғқңөұүһі" for c in letters)
    cyr = sum("а" <= c <= "я" or c in "ёәғқңөұүһі" for c in letters)
    if kaz / len(letters) > 0.01:
        return "kk"
    return "ru" if cyr / len(letters) > 0.5 else "en"


def evaluate(case: dict, answer: str, sources: list[dict]) -> tuple[bool, list[str]]:
    """Детерминированные проверки; возвращает (passed, список нарушений)."""
    text = answer.lower()
    fails = []
    # отказ — короткий ответ с формулой «нет информации»; фраза о недостающей детали
    # внутри полного ответа (частичный ответ) отказом не считается
    refused = bool(REFUSAL.search(answer)) and len(answer) < 320
    if case.get("refusal") is True and not refused:
        fails.append("ожидался отказ «нет информации», модель ответила по существу")
    factual = bool(case.get("must")) and case.get("refusal") is not True
    if factual and refused and not case.get("must_not"):
        fails.append("ложный отказ: ответ есть в документах")
    for group in case.get("must", []):
        if not any(re.search(p, text, re.I) for p in group):
            fails.append(f"нет ожидаемого факта: {' | '.join(group)}")
    for p in case.get("must_not", []):
        if re.search(p, text, re.I):
            fails.append(f"запрещённое содержимое: {p}")
    if case.get("lang") and detect_lang(answer) != case["lang"]:
        fails.append(f"язык ответа {detect_lang(answer)}, ожидался {case['lang']}")
    if factual and not refused and not re.search(r"\[\d{1,2}\]", answer) and case["id"][0] in "BG":
        fails.append("нет ссылок на источники [n]")
    if case.get("source"):
        titles = " ".join(f"{s.get('title', '')} {s.get('file_name', '')}" for s in sources).lower()
        if not re.search(case["source"], titles, re.I):
            fails.append(f"нужный документ ({case['source']}) не попал в источники")
    return not fails, fails


# ---------------------------------------------------------------- вызовы API
def chat_stream(question: str, history: list[dict], model: str) -> dict:
    t0 = time.perf_counter()
    res = {"answer": "", "sources": [], "error": None, "t_sources": None, "t_first": None}
    event = None
    try:
        with httpx.stream(
            "POST", f"{BASE}/api/chat/stream",
            json={"question": question, "history": history, "model": model}, timeout=240,
        ) as r:
            if r.status_code != 200:
                res["error"] = f"HTTP {r.status_code}: {r.read().decode()[:200]}"
                return res
            for line in r.iter_lines():
                if line.startswith("event: "):
                    event = line[7:]
                elif line.startswith("data: "):
                    data = json.loads(line[6:])
                    if event == "sources":
                        res["t_sources"] = time.perf_counter() - t0
                        res["sources"] = data["sources"]
                        res["query"] = data.get("query")
                    elif event == "token":
                        if res["t_first"] is None:
                            res["t_first"] = time.perf_counter() - t0
                        res["answer"] += data
                    elif event == "done":
                        res["meta"] = data
                    elif event == "error":
                        res["error"] = data.get("detail")
    except httpx.HTTPError as e:
        res["error"] = f"{type(e).__name__}: {e}"
    res["t_total"] = time.perf_counter() - t0
    return res


JUDGE = """Ты — строгий эксперт QA. Оцени ответ чат-бота университета КБТУ.
Дано: вопрос, эталонный факт из официального документа, найденные фрагменты и ответ бота.
- correctness (1–5): совпадает ли ответ с эталоном по смыслу (5 — полностью, 1 — неверно или нет ответа);
- faithfulness (0.0–1.0): доля утверждений ответа, подтверждённых фрагментами;
- comment: одно короткое предложение по-русски.
Ответ — только JSON-объект (json): {"correctness": n, "faithfulness": x, "comment": "..."}"""


def judge(case: dict, answer: str, sources: list[dict]) -> dict | None:
    if not case.get("reference"):
        return None
    from backend.app.rag.llm import get_client

    ctx = "\n\n".join(f"[{s['n']}] {s.get('title')}: {s.get('text', '')[:1500]}" for s in sources)[:9000]
    question = case.get("question") or " → ".join(case.get("turns", []))
    for attempt in range(3):
        try:
            resp = get_client().chat.completions.create(
                model="gpt-4o-mini", temperature=0, response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": JUDGE},
                    {"role": "user", "content": f"Вопрос: {question}\nЭталон: {case['reference']}\n\n"
                                                f"Фрагменты:\n{ctx}\n\nОтвет бота:\n{answer[:4000]}"},
                ],
            )
            j = json.loads(resp.choices[0].message.content)
            return {
                "correctness": max(1.0, min(5.0, float(j.get("correctness", 1)))),
                "faithfulness": max(0.0, min(1.0, float(j.get("faithfulness", 0)))),
                "comment": str(j.get("comment", ""))[:300],
            }
        except Exception as e:  # noqa: BLE001
            if attempt == 2:
                return {"error": str(e)[:200]}
            time.sleep(5)
    return None


def run_chat_case(case: dict, model: str) -> dict:
    turns = case.get("turns") or [case["question"]]
    history: list[dict] = []
    res = {}
    for i, q in enumerate(turns):
        for attempt in range(3):  # сетевые сбои не считаем дефектом бота
            res = chat_stream(q, history, model)
            if not res["error"] or "HTTP 4" in res["error"]:
                break
            time.sleep(5 * (attempt + 1))
        if i < len(turns) - 1:
            history += [{"role": "user", "content": q}, {"role": "assistant", "content": res["answer"]}]
    passed, fails = (False, [f"ошибка: {res['error']}"]) if res["error"] else evaluate(case, res["answer"], res["sources"])
    return {
        "id": case["id"], "model": model, "passed": passed, "fails": fails,
        "question": case.get("question") or " → ".join(turns),
        "rewritten_query": res.get("query"),
        "answer": res["answer"], "error": res["error"],
        "sources": [{"n": s["n"], "title": s.get("title"), "page": s.get("page_start")} for s in res["sources"]],
        "lang": detect_lang(res["answer"]),
        "t_sources": res.get("t_sources"), "t_first": res.get("t_first"), "t_total": res.get("t_total"),
        "tokens_per_s": (res.get("meta") or {}).get("tokens_per_s"),
        "judge": judge(case, res["answer"], res["sources"]) if not res["error"] else None,
    }


# ---------------------------------------------------------------- функциональные тесты API
def api_tests() -> list[dict]:
    out = []

    def check(tid: str, title: str, fn) -> None:
        t0 = time.perf_counter()
        try:
            detail = fn()
            out.append({"id": tid, "title": title, "passed": True, "detail": detail or "",
                        "ms": round((time.perf_counter() - t0) * 1000)})
        except AssertionError as e:
            out.append({"id": tid, "title": title, "passed": False, "detail": str(e),
                        "ms": round((time.perf_counter() - t0) * 1000)})
        except Exception as e:  # noqa: BLE001
            out.append({"id": tid, "title": title, "passed": False, "detail": f"{type(e).__name__}: {e}",
                        "ms": round((time.perf_counter() - t0) * 1000)})

    c = httpx.Client(base_url=BASE, timeout=120)

    def health():
        r = c.get("/api/health")
        assert r.status_code == 200, r.status_code
        h = r.json()
        assert h["status"] == "ok" and h["openai_key"], h
        assert h["chunks"] > 0, "база знаний пуста"
        return f"{h['documents']} док., {h['chunks']} фрагментов, {h['vector_db']}"

    def models():
        m = c.get("/api/models").json()
        llms = [x["id"] for x in m["llms"] if x["available"]]
        emb = [x["id"] for x in m["embedders"] if x["available"]]
        assert len(llms) >= 2, f"доступно LLM: {llms}"
        assert len(emb) >= 2, f"доступно эмбеддеров: {emb}"
        return f"LLM: {len(llms)} ({', '.join(llms)}); эмбеддеры: {len(emb)}"

    def documents():
        d = c.get("/api/documents").json()
        assert isinstance(d, list) and d, "пустой список"
        ready = [x for x in d if x.get("status") == "processed" and x.get("is_current")]
        assert ready, "нет действующих документов"
        return f"{len(d)} документов, действующих: {len(ready)}"

    def search():
        r = c.post("/api/search", json={"query": "стоимость проживания в общежитии", "top_k": 5}).json()
        assert r["results"], "нет результатов"
        top = r["results"][0]
        assert top.get("rrf_score") is not None, "нет RRF-оценки"
        return f"{len(r['results'])} кандидатов, топ-1: {top['title']}"

    def abbreviation():
        r = c.post("/api/search", json={"query": "ДС", "top_k": 3}).json()
        assert "Дом студентов" in r["expanded_query"], r["expanded_query"]
        return f"«ДС» → «{r['expanded_query']}»"

    def tokenize():
        r = c.post("/api/nlp/tokenize", json={"text": "Пересдача (Retake) в КБТУ"}).json()
        assert r["token_count"] > 0 and r["bm25_tokens"], r
        return f"{r['token_count']} BPE-токенов ({r['encoding']}), BM25: {r['bm25_tokens']}"

    def embed_local():
        r = c.post("/api/nlp/embed", json={"texts": ["пересдача экзамена", "retake an exam", "рецепт плова"],
                                           "model": "local:intfloat/multilingual-e5-small"}).json()
        s = r["similarity"]
        assert len(s) == 3 and abs(s[0][0] - 1) < 1e-3, s
        assert s[0][1] > s[0][2], f"кросс-языковое сходство {s[0][1]} не выше нерелевантного {s[0][2]}"
        return f"{r['dimensions']} dim; sim(пересдача, retake)={s[0][1]:.3f} > sim(пересдача, плов)={s[0][2]:.3f}"

    def empty_question():
        r = c.post("/api/chat", json={"question": ""})
        assert r.status_code == 422, r.status_code
        return "HTTP 422"

    def long_question():
        r = c.post("/api/chat", json={"question": "а" * 2001})
        assert r.status_code == 422, r.status_code
        return "HTTP 422 при 2001 символе"

    def bad_model():
        r = chat_stream("Какой график библиотеки?", [], "badprovider:xyz")
        assert r["error"], "ожидалась ошибка"
        return f"событие error: {r['error'][:80]}"

    def bad_history():
        r = c.post("/api/chat", json={"question": "тест", "history": [{"role": "system", "content": "x"}]})
        assert r.status_code == 422, r.status_code
        return "HTTP 422 для роли system в истории"

    def stream_order():
        events = []
        with httpx.stream("POST", f"{BASE}/api/chat/stream", json={"question": "Когда санитарный день в библиотеке?"},
                          timeout=180) as r:
            for line in r.iter_lines():
                if line.startswith("event: ") and (not events or events[-1] != line[7:]):
                    events.append(line[7:])
        assert events[:1] == ["sources"] and events[-1] == "done" and "token" in events, events
        return " → ".join(events)

    def missing_file():
        r = c.get("/api/documents/00000000-0000-0000-0000-000000000000/file")
        assert r.status_code == 404, r.status_code
        return "HTTP 404"

    def frontend():
        r = c.get("/")
        assert r.status_code == 200 and "<div id=\"root\">" in r.text, r.status_code
        return "SPA отдаётся backend"

    def eval_api():
        r = c.get("/api/eval/results").json()
        assert r["dataset"] and r["retrieval"] and r["generation"], "нет результатов оценки"
        return f"датасет {r['dataset']['total']} вопросов, методов поиска {len(r['retrieval']['methods'])}"

    def eval_validation():
        r = c.post("/api/eval/run", json={"kind": "unknown"})
        assert r.status_code == 422, r.status_code
        return "HTTP 422"

    for t in [
        ("A01", "GET /api/health — статус и наполненность базы", health),
        ("A02", "GET /api/models — доступны ≥2 LLM и ≥2 эмбеддера", models),
        ("A03", "GET /api/documents — реестр документов", documents),
        ("A04", "POST /api/search — гибридный поиск с RRF", search),
        ("A05", "Расширение аббревиатур в запросе", abbreviation),
        ("A06", "POST /api/nlp/tokenize — BPE и BM25-токены", tokenize),
        ("A07", "POST /api/nlp/embed — локальная e5, кросс-языковое сходство", embed_local),
        ("A08", "Валидация: пустой вопрос", empty_question),
        ("A09", "Валидация: вопрос длиннее 2000 символов", long_question),
        ("A10", "Валидация: недопустимая роль в истории", bad_history),
        ("A11", "Неизвестная модель → событие error, без падения", bad_model),
        ("A12", "SSE-протокол: sources → token… → done", stream_order),
        ("A13", "Несуществующий документ → 404", missing_file),
        ("A14", "Frontend раздаётся с backend", frontend),
        ("A15", "GET /api/eval/results — результаты оценки", eval_api),
        ("A16", "Валидация: неизвестный тип оценки", eval_validation),
    ]:
        log(f"API {t[0]} {t[1]}")
        check(*t)
    return out


# ---------------------------------------------------------------- письма (локальная симуляция)
def email_tests(token: str) -> list[dict]:
    out = []
    headers = {"X-API-Key": token} if token else {}
    for case in EMAILS:
        payload = dict(case["payload"])
        days = payload.pop("received_at_days_ago", None)
        if days:
            payload["received_at"] = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        payload["save_draft"] = False
        log(f"EMAIL {case['id']} {case['title']}")
        t0 = time.perf_counter()
        r = httpx.post(f"{BASE}/api/email/reply", json=payload, headers=headers, timeout=240)
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        fails = []
        if r.status_code != 200:
            fails.append(f"HTTP {r.status_code}")
        status = body.get("status")
        if status not in case["expect_status"]:
            fails.append(f"статус {status}, ожидался {'/'.join(case['expect_status'])}")
        text = body.get("reply_text") or ""
        for group in case.get("must", []):
            if not any(re.search(p, text, re.I) for p in group):
                fails.append(f"нет ожидаемого факта: {' | '.join(group)}")
        if case.get("lang") and body.get("language") and body["language"] != case["lang"]:
            fails.append(f"язык определён как {body['language']}, ожидался {case['lang']}")
        if case.get("lang") and text:
            # язык самого текста без строки приветствия и блока источников
            core = "\n".join(text.splitlines()[1:]).split("Источник")[0].split("Source")[0]
            if detect_lang(core) != case["lang"]:
                fails.append(f"текст ответа на языке {detect_lang(core)}, письмо на {case['lang']}")
        out.append({"id": case["id"], "title": case["title"], "passed": not fails, "fails": fails,
                    "status": status, "reason": body.get("reason"), "language": body.get("language"),
                    "subject": body.get("subject"), "reply": text, "letter": case["payload"].get("body"),
                    "ms": round((time.perf_counter() - t0) * 1000)})

    log("EMAIL I07 неверный X-API-Key")
    r = httpx.post(f"{BASE}/api/email/reply", json={"body": "test"}, headers={"X-API-Key": "wrong"}, timeout=60)
    out.append({"id": "I07", "title": "Неверный X-API-Key → 401", "passed": r.status_code == 401 or not token,
                "fails": [] if r.status_code == 401 or not token else [f"HTTP {r.status_code}"],
                "status": f"HTTP {r.status_code}", "reply": "", "letter": "test", "ms": 0})
    return out


# ---------------------------------------------------------------- производительность и нагрузка
def perf_tests() -> dict:
    out = {}
    queries = ["стоимость общежития", "график библиотеки", "ритейк", "военная кафедра", "GPA",
               "психолог", "вступительный взнос", "кодекс чести", "оплата обучения", "UniDorm"]

    def timed_search(q):
        t0 = time.perf_counter()
        r = httpx.post(f"{BASE}/api/search", json={"query": q, "top_k": 5}, timeout=180)
        return r.status_code, time.perf_counter() - t0

    log("PERF последовательный поиск")
    seq = [timed_search(q) for q in queries]
    log("PERF 10 параллельных поисков")
    t0 = time.perf_counter()
    with ThreadPoolExecutor(10) as ex:
        par = list(ex.map(timed_search, queries))
    wall = time.perf_counter() - t0
    out["search_sequential"] = {"n": len(seq), "ok": sum(s == 200 for s, _ in seq),
                                "p50": statistics.median(t for _, t in seq), "max": max(t for _, t in seq)}
    out["search_parallel"] = {"n": len(par), "ok": sum(s == 200 for s, _ in par),
                              "p50": statistics.median(t for _, t in par), "max": max(t for _, t in par),
                              "wall": wall}

    log("PERF 4 параллельных чата + опрос /api/health")
    health_times, stop = [], False

    def poll():
        while not stop:
            t = time.perf_counter()
            try:
                ok = httpx.get(f"{BASE}/api/health", timeout=60).status_code == 200
            except httpx.HTTPError:
                ok = False
            health_times.append((ok, time.perf_counter() - t))
            time.sleep(0.5)

    with ThreadPoolExecutor(5) as ex:
        poller = ex.submit(poll)
        t0 = time.perf_counter()
        chats = list(ex.map(lambda q: chat_stream(q, [], DEFAULT_MODELS[0]),
                            ["Какой график библиотеки?", "Сколько стоит общежитие?",
                             "Что такое оценка AW?", "Где принимает психолог?"]))
        wall = time.perf_counter() - t0
        stop = True
        poller.result()
    out["chat_parallel"] = {"n": len(chats), "ok": sum(not c["error"] and bool(c["answer"]) for c in chats),
                            "max": max(c["t_total"] for c in chats), "wall": wall}
    out["health_under_load"] = {"n": len(health_times), "ok": sum(ok for ok, _ in health_times),
                                "p50": statistics.median(t for _, t in health_times) if health_times else None,
                                "max": max((t for _, t in health_times), default=None)}
    return out


# ---------------------------------------------------------------- автотесты и сборка
def quality_gates() -> list[dict]:
    py = str(ROOT / ".venv" / "Scripts" / "python.exe")
    gates = [
        ("Q01", "Модульные и интеграционные тесты (pytest)", [py, "-m", "pytest", "-q", "--ignore=tests/browser",
                                                             "--ignore=tests/qa", "-p", "no:cacheprovider"]),
        ("Q02", "Статический анализ (ruff)", [py, "-m", "ruff", "check", "backend", "ingestion", "tests/qa"]),
        ("Q03", "Проверка типов и сборка frontend (tsc + vite)", ["npm.cmd", "--prefix", "frontend", "run", "build"]),
    ]
    out = []
    for gid, title, cmd in gates:
        log(f"GATE {gid} {title}")
        t0 = time.perf_counter()
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
        tail = (p.stdout + p.stderr).strip().splitlines()
        summary = next((ln for ln in reversed(tail) if re.search(r"passed|failed|error|All checks|built in|Found", ln)),
                       tail[-1] if tail else "")
        out.append({"id": gid, "title": title, "passed": p.returncode == 0,
                    "summary": re.sub(r"\x1b\[[0-9;]*m", "", summary).strip(), "s": round(time.perf_counter() - t0, 1)})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="*", default=DEFAULT_MODELS)
    ap.add_argument("--skip-gates", action="store_true")
    ap.add_argument("--only", help="префиксы категорий, например BCE")
    ap.add_argument("--retest", action="store_true",
                    help="повторная проверка после исправлений: API и письма -> data/qa/retest.json")
    args = ap.parse_args()

    from backend.app.config import get_settings

    if args.retest:
        retest = {"started_at": now(), "api": api_tests(), "email": email_tests(get_settings().email_api_token)}
        retest["finished_at"] = now()
        out = OUT.with_name("retest.json")
        out.write_text(json.dumps(retest, ensure_ascii=False, indent=2), encoding="utf-8")
        ok = [x["passed"] for x in retest["api"] + retest["email"]]
        log(f"ПОВТОРНАЯ ПРОВЕРКА: {sum(ok)}/{len(ok)} PASS, {out}")
        return

    started = time.perf_counter()
    results = {"started_at": now(), "models": args.models}
    results["health"] = httpx.get(f"{BASE}/api/health", timeout=60).json()
    results["api"] = api_tests()

    chat = []
    for prefix, (_title, cases) in CATEGORIES.items():
        if args.only and prefix not in args.only:
            continue
        for case in cases:
            for model in args.models:
                log(f"CHAT {case['id']} [{model}] {case['title']}")
                r = run_chat_case(case, model)
                log(f"      {'PASS' if r['passed'] else 'FAIL'} {'; '.join(r['fails'])[:150]}")
                chat.append(r)
    results["chat"] = chat
    results["email"] = email_tests(get_settings().email_api_token)
    results["perf"] = perf_tests()
    results["gates"] = [] if args.skip_gates else quality_gates()
    results["eval"] = httpx.get(f"{BASE}/api/eval/results", timeout=60).json()
    results["finished_at"] = now()
    results["duration_s"] = round(time.perf_counter() - started)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    total = [x["passed"] for x in results["api"] + chat + results["email"] + results["gates"]]
    log(f"ГОТОВО: {sum(total)}/{len(total)} PASS, результаты: {OUT}")


if __name__ == "__main__":
    main()
