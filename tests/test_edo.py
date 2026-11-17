"""Документооборот: ролевой доступ, маршруты согласования, регистрация, журнал."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.edo import router as edo_router
from backend.app.edo.store import Store


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = Store(tmp_path / "edo")
    monkeypatch.setattr(edo_router, "get_store", lambda: store)
    app = FastAPI()
    app.include_router(edo_router.router)
    return TestClient(app)


def h(role):
    return {"X-EDO-Role": role}


def test_unknown_role_is_rejected(client):
    assert client.get("/api/edo/dashboard", headers=h("hacker")).status_code == 400


def test_medical_content_hidden_from_rector_and_closed_for_hr(client):
    docs = client.get(
        "/api/edo/documents", headers=h("rector"), params={"category": "medical"}
    ).json()
    assert docs and all(d["access"] == "meta" and d["notes"] is None for d in docs)
    assert (
        client.get(
            "/api/edo/documents", headers=h("hr"), params={"category": "medical"}
        ).status_code
        == 403
    )
    medical = client.get(
        "/api/edo/documents", headers=h("medical"), params={"category": "medical"}
    ).json()
    assert all(d["access"] == "full" for d in medical)


def test_person_cards_follow_role(client):
    kinds = {p["kind"] for p in client.get("/api/edo/persons", headers=h("admissions")).json()}
    assert kinds == {"applicant"}
    student = client.get("/api/edo/persons", headers=h("dean"), params={"kind": "student"}).json()[
        0
    ]
    assert (
        client.get(f"/api/edo/persons/{student['id']}", headers=h("admissions")).status_code == 403
    )
    file = client.get(f"/api/edo/persons/{student['id']}", headers=h("registrar")).json()
    assert len(file["checklist"]) == 7


def test_route_is_followed_step_by_step(client):
    form = {"type_code": "trip_memo", "title": "Командировка"}
    doc = client.post("/api/edo/documents", headers=h("hr"), data=form).json()
    assert doc["status"] == "on_approval" and [s["role"] for s in doc["route"]] == [
        "hr",
        "accounting",
        "rector",
    ]
    doc_id = doc["id"]
    # шаг бухгалтерии ещё не наступил
    r = client.post(
        f"/api/edo/documents/{doc_id}/decision",
        headers=h("accounting"),
        json={"decision": "approve"},
    )
    assert r.status_code == 403
    for role in ("hr", "accounting", "rector"):
        r = client.post(
            f"/api/edo/documents/{doc_id}/decision", headers=h(role), json={"decision": "approve"}
        )
        assert r.status_code == 200
    assert r.json()["status"] == "approved"


def test_reject_requires_reason_and_stops_route(client):
    doc = client.post("/api/edo/documents", headers=h("hr"), data={"type_code": "trip_memo"}).json()
    url = f"/api/edo/documents/{doc['id']}/decision"
    assert client.post(url, headers=h("hr"), json={"decision": "reject"}).status_code == 400
    r = client.post(
        url, headers=h("hr"), json={"decision": "reject", "comment": "Нет сметы"}
    ).json()
    assert r["status"] == "rejected"
    assert [s["status"] for s in r["route"]] == ["rejected", "skipped", "skipped"]


def test_registration_rules_and_file_access(client):
    denied = client.post("/api/edo/documents", headers=h("hr"), data={"type_code": "med_086"})
    assert denied.status_code == 403
    bad = client.post(
        "/api/edo/documents",
        headers=h("hr"),
        data={"type_code": "trip_report"},
        files={"file": ("virus.exe", b"MZ")},
    )
    assert bad.status_code == 400
    doc = client.post(
        "/api/edo/documents",
        headers=h("hr"),
        data={"type_code": "trip_report"},
        files={"file": ("report.pdf", b"%PDF-1.4 demo")},
    ).json()
    assert doc["reg_number"].startswith("КМ-") and doc["has_file"] and doc["file_sha256"]
    assert (
        client.get(f"/api/edo/documents/{doc['id']}/file", params={"role": "hr"}).status_code == 200
    )
    assert (
        client.get(f"/api/edo/documents/{doc['id']}/file", params={"role": "archive"}).status_code
        == 403
    )
    audit = client.get(f"/api/edo/documents/{doc['id']}", headers=h("hr")).json()["audit"]
    assert {"registered", "file_attached", "downloaded"} <= {a["action"] for a in audit}


def test_reg_numbers_are_sequential(client):
    a = client.post(
        "/api/edo/documents", headers=h("rector"), data={"type_code": "instruction"}
    ).json()
    b = client.post(
        "/api/edo/documents", headers=h("rector"), data={"type_code": "instruction"}
    ).json()
    na, nb = (int(x["reg_number"].rsplit("/", 1)[1]) for x in (a, b))
    assert nb == na + 1
