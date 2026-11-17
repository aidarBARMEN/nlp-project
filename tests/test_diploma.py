from io import BytesIO
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from backend.app import diploma


def test_ownership_updates_and_excel(tmp_path, monkeypatch):
    monkeypatch.setattr(diploma, "get_settings", lambda: SimpleNamespace(data_dir=tmp_path))
    (tmp_path / "diploma-dean-key.txt").write_text("test-dean")
    app = FastAPI()
    app.include_router(diploma.router)
    client = TestClient(app)
    auth = []
    for student in ("STU1", "STU2"):
        r = client.post(
            "/api/diploma/register", json={"student_id": student, "password": "password123"}
        )
        assert r.status_code == 200
        auth.append({"Authorization": "Bearer " + r.json()["token"]})
    body = {
        "full_name": "Test Student",
        "study_group": "IS-22",
        "faculty": "ШИТИ",
        "program": "Информационные системы",
        "topic": "=SUM(1,2)",
        "supervisor": "Test Supervisor",
        "members": [],
        "version": 0,
    }
    assert client.put("/api/diploma/me", json=body).status_code == 401
    assert client.put("/api/diploma/me", json=body, headers=auth[0]).status_code == 200
    assert client.get("/api/diploma/me", headers=auth[1]).json()["submission"] is None
    assert (
        client.put(
            "/api/diploma/me", json={**body, "student_id": "STU1"}, headers=auth[1]
        ).status_code
        == 422
    )
    assert client.put("/api/diploma/me", json=body, headers=auth[0]).status_code == 409
    assert (
        client.put("/api/diploma/me", json={**body, "version": 1}, headers=auth[0]).json()[
            "version"
        ]
        == 2
    )
    assert client.get("/api/diploma/records", headers=auth[0]).status_code == 403
    assert client.get("/api/diploma/export").status_code == 403
    dean = {"X-Dean-Key": "test-dean"}
    assert len(client.get("/api/diploma/records", headers=dean).json()) == 1
    wb = load_workbook(BytesIO(client.get("/api/diploma/export", headers=dean).content))
    assert wb.active["B2"].value == "=SUM(1,2)"
    assert wb.active["B2"].data_type == "s"
    assert wb.active.freeze_panes == "A2"
    assert (
        client.post(
            "/api/diploma/login", json={"student_id": "STU1", "password": "incorrect"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/diploma/register", json={"student_id": "stu1", "password": "password123"}
        ).status_code
        == 409
    )
    assert (
        client.put(
            "/api/diploma/me",
            json={
                **body,
                "members": [{"student_id": "STU1", "full_name": "Test Student"}],
                "version": 2,
            },
            headers=auth[0],
        ).status_code
        == 422
    )
    client.post("/api/diploma/logout", headers=auth[0])
    assert client.get("/api/diploma/me", headers=auth[0]).status_code == 401


def test_team_blocks_and_append_order(tmp_path, monkeypatch):
    monkeypatch.setattr(diploma, "get_settings", lambda: SimpleNamespace(data_dir=tmp_path))
    (tmp_path / "diploma-dean-key.txt").write_text("test-dean")
    app = FastAPI()
    app.include_router(diploma.router)
    client = TestClient(app)
    sessions = []
    for student in ("STU1", "STU2", "STU3"):
        token = client.post(
            "/api/diploma/register",
            json={
                "student_id": student,
                "password": "password123",
            },
        ).json()["token"]
        sessions.append({"Authorization": "Bearer " + token})
    body = {
        "full_name": "First Student",
        "study_group": "IS-22",
        "faculty": "ШИТИ",
        "program": "Информационные системы",
        "topic": "First project",
        "supervisor": "Supervisor Name",
        "members": [{"student_id": "STU2", "full_name": "Second Student"}],
        "version": 0,
    }
    assert client.put("/api/diploma/me", json=body, headers=sessions[0]).status_code == 200
    second = {
        **body,
        "full_name": "Second Student",
        "members": [{"student_id": "STU1", "full_name": "First Student"}],
    }
    assert client.put("/api/diploma/me", json=second, headers=sessions[1]).status_code == 200
    third = {
        **body,
        "topic": "Another project",
        "members": [],
        "faculty": "Бизнес-школа",
        "program": "Финансы",
    }
    assert client.put("/api/diploma/me", json=third, headers=sessions[2]).status_code == 200
    assert (
        client.put("/api/diploma/me", json={**body, "version": 1}, headers=sessions[0]).status_code
        == 200
    )
    ws = load_workbook(
        BytesIO(client.get("/api/diploma/export", headers={"X-Dean-Key": "test-dean"}).content)
    ).active
    assert ws.max_row == 4  # One team of two, then a solo project; no duplicate team.
    assert ws["B2"].value == "First project"
    assert ws["B4"].value == "Another project"
    assert "B2:B3" in {str(r) for r in ws.merged_cells.ranges}
    assert ws["A2"].border.top.style == "medium"
    assert ws["G3"].border.bottom.style == "medium"
    assert ws["F3"].value == "IS-22"
    dean = {"X-Dean-Key": "test-dean"}
    params = {"faculty": "ШИТИ", "program": "Информационные системы"}
    filtered = client.get("/api/diploma/records", headers=dean, params=params)
    assert len(filtered.json()) == 2
    filtered_ws = load_workbook(
        BytesIO(client.get("/api/diploma/export", headers=dean, params=params).content)
    ).active
    assert filtered_ws.max_row == 3
    assert filtered_ws["H2"].value == "ШИТИ"
    assert filtered_ws["I2"].value == "Информационные системы"
    assert filtered_ws["I3"].border.right.style == "medium"
    assert client.get("/api/diploma/records", headers=dean, params={"faculty": "ШПМ"}).json() == []
    assert (
        client.get(
            "/api/diploma/export", headers=dean, params={"faculty": "ШИТИ", "program": "Финансы"}
        ).status_code
        == 422
    )
    assert (
        client.put(
            "/api/diploma/me",
            headers=sessions[0],
            json={**body, "program": "Финансы", "version": 2},
        ).status_code
        == 422
    )
    # Existing records without new fields stay readable and can be exported separately.
    import json

    with diploma.database() as db:
        old = {k: v for k, v in third.items() if k not in ("faculty", "program", "version")}
        db.execute("UPDATE submissions SET body=? WHERE student_id='STU3'", (json.dumps(old),))
    assert client.get("/api/diploma/me", headers=sessions[2]).json()["submission"]["faculty"] == ""
    legacy = client.get("/api/diploma/records", headers=dean, params={"faculty": "__missing__"})
    assert [r["student_id"] for r in legacy.json()] == ["STU3"]
    # Conflicting declarations must remain visible, not overwrite one another.
    assert (
        len(
            diploma.project_groups(
                [
                    {**body, "student_id": "STU1", "updated_at": "2026-01-01"},
                    {
                        **second,
                        "student_id": "STU2",
                        "topic": "Different topic",
                        "updated_at": "2026-01-02",
                    },
                ]
            )
        )
        == 2
    )
