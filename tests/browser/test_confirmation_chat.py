"""Real frontend clicks, isolated API responses; no real document is approved by tests.

Run a built app, install Playwright + Chromium, then:
    python -m pytest tests/browser -m browser -q
"""

import json
import os
from urllib.parse import urlsplit

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")
expect = playwright_api.expect
pytestmark = pytest.mark.browser


@pytest.fixture
def ui():
    with playwright_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.route("https://fonts.googleapis.com/**", lambda route: route.abort())
        page.route("https://fonts.gstatic.com/**", lambda route: route.abort())
        state = {
            "trust_requests": [],
            "chat_requests": [],
            "trust_error": False,
            "incomplete": False,
        }
        doc = {
            "doc_id": "ui-fixture",
            "file_name": "Test Policy.pdf",
            "title": "Test Policy",
            "status": "processed",
            "trust_level": "unverified",
            "is_current": True,
            "source_channel": "manual_upload",
            "chunks": 6,
            "tokens": 100,
            "pages": 1,
            "category": "academic_policy",
            "academic_year": None,
            "target_audience": None,
            "url": None,
            "indexed_at": None,
        }

        def respond(route):
            path = urlsplit(route.request.url).path
            if path.endswith("/health"):
                value = {
                    "status": "ok",
                    "openai_key": True,
                    "chat_model": "gpt-4o-mini",
                    "embedding_model": "text-embedding-3-small",
                    "vector_db": "Qdrant",
                    "reranker": "none",
                    "chunk_size": 700,
                    "chunk_overlap": 100,
                    "documents": 1,
                    "chunks": 6 if doc["trust_level"] == "official" else 0,
                    "tokens": 100,
                }
            elif path.endswith("/documents"):
                value = [doc]
            elif path.endswith("/trust"):
                body = route.request.post_data_json
                state["trust_requests"].append(body)
                if state["trust_error"]:
                    route.fulfill(status=503, json={"detail": "Не удалось сохранить подтверждение"})
                    return
                doc["trust_level"] = body["trust_level"]
                value = doc
            elif path.endswith("/chat/stream"):
                state["chat_requests"].append(route.request.post_data_json)
                body = (
                    "event: sources\ndata: "
                    + json.dumps({"query": "rules", "sources": []})
                    + "\n\n"
                )
                if not state["incomplete"]:
                    body += (
                        "event: token\ndata: "
                        + json.dumps("Ответ по подтверждённому документу.")
                        + "\n\n"
                    )
                    body += 'event: done\ndata: {"total_ms": 20}\n\n'
                route.fulfill(status=200, content_type="text/event-stream", body=body)
                return
            else:
                raise AssertionError(f"Unexpected API call: {path}")
            route.fulfill(status=200, json=value)

        page.route("**/api/**", respond)
        base = os.environ.get("KBTU_UI_TEST_URL", "http://127.0.0.1:8000")
        # Match a preview without native dialogs, form submissions or a secure context.
        page.set_content(
            '<iframe sandbox="allow-scripts allow-same-origin" '
            f'src="{base}" style="width:1400px;height:950px"></iframe>'
        )
        frame = page.frame_locator("iframe")
        errors, dialogs = [], []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.on("dialog", lambda dialog: (dialogs.append(dialog.type), dialog.dismiss()))
        yield frame, state, doc
        assert not dialogs, "Confirmation must not depend on native browser dialogs"
        assert not errors
        browser.close()


@pytest.mark.parametrize("submit", ["click", "enter"])
def test_confirmation_click_then_assistant_answer(ui, submit):
    frame, state, doc = ui
    frame.get_by_role("button", name="База знаний", exact=True).click()
    frame.get_by_role("button", name="Подтвердить", exact=True).click()
    expect(frame.get_by_text("Официальный · действующий", exact=True)).to_be_visible()
    expect(frame.get_by_role("button", name="На проверку", exact=True)).to_be_enabled()
    assert len(state["trust_requests"]) == 1
    assert state["trust_requests"][0]["trust_level"] == "official"
    assert doc["trust_level"] == "official"
    frame.get_by_role("button", name="Ассистент", exact=True).click()
    frame.locator("textarea").fill("Какие правила в документе?")
    if submit == "click":
        frame.get_by_role("button", name="Отправить", exact=True).click()
    else:
        frame.locator("textarea").press("Enter")
    expect(frame.get_by_text("Ответ по подтверждённому документу.", exact=True)).to_be_visible()
    assert len(state["chat_requests"]) == 1
    expect(frame.get_by_title("Остановить", exact=True)).to_have_count(0)


def test_confirmation_error_allows_retry(ui):
    frame, state, _ = ui
    state["trust_error"] = True
    frame.get_by_role("button", name="База знаний", exact=True).click()
    frame.get_by_role("button", name="Подтвердить", exact=True).click()
    expect(frame.get_by_text("Не удалось сохранить подтверждение", exact=True)).to_be_visible()
    expect(frame.get_by_role("button", name="Подтвердить", exact=True)).to_be_enabled()
    state["trust_error"] = False
    frame.get_by_role("button", name="Подтвердить", exact=True).click()
    expect(frame.get_by_text("Официальный · действующий", exact=True)).to_be_visible()
    assert len(state["trust_requests"]) == 2


def test_interrupted_stream_reports_error_and_releases_send(ui):
    frame, state, doc = ui
    doc["trust_level"] = "official"
    state["incomplete"] = True
    frame.locator("textarea").fill("Вопрос")
    frame.get_by_role("button", name="Отправить", exact=True).click()
    expect(
        frame.get_by_text(
            "Соединение прервалось до завершения ответа. Повторите вопрос.", exact=True
        )
    ).to_be_visible()
    expect(frame.get_by_title("Остановить", exact=True)).to_have_count(0)
    frame.locator("textarea").fill("Новый вопрос")
    expect(frame.get_by_role("button", name="Отправить", exact=True)).to_be_enabled()
