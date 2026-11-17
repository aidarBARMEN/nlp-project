"""Учётные записи и роли, заявления по образцам, посещаемость по фото листа."""

import random
from io import BytesIO
from types import SimpleNamespace

import cv2
import docx
import numpy as np
import pymupdf
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from backend.app import auth
from backend.app.applications import router as applications
from backend.app.attendance import router as attendance
from backend.app.attendance.sheet import PAGE_W, layout


@pytest.fixture
def client(tmp_path, monkeypatch):
    settings = SimpleNamespace(
        data_dir=tmp_path, admin_emails="admin@kbtu.kz", auth_email_domains=""
    )
    for module in (auth, applications, attendance):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    auth._failures.clear()
    app = FastAPI()
    for module in (auth, applications, attendance):
        app.include_router(module.router)
    return TestClient(app)


def register(client, email, name="Тестов Тест Тестович"):
    r = client.post(
        "/api/auth/register", json={"email": email, "password": "password123", "full_name": name}
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()["user"]


def promote(client, admin, user, role):
    assert (
        client.put(
            f"/api/auth/users/{user['id']}/role", json={"role": role}, headers=admin
        ).status_code
        == 200
    )


# ---------------------------------------------------------------- учётные записи
def test_registration_login_and_roles(client):
    admin, admin_user = register(client, "Admin@KBTU.kz")
    assert admin_user["role"] == "admin" and admin_user["email"] == "admin@kbtu.kz"
    student, user = register(client, "student@kbtu.kz")
    assert user["role"] == "student"
    assert (
        client.post(
            "/api/auth/register",
            json={"email": "student@kbtu.kz", "password": "password123", "full_name": "Двойник"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/auth/login", json={"email": "student@kbtu.kz", "password": "wrong-pass"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/auth/login", json={"email": "student@kbtu.kz", "password": "password123"}
        ).status_code
        == 200
    )
    assert client.get("/api/auth/users", headers=student).status_code == 403
    promote(client, admin, user, "dean")
    assert client.get("/api/auth/me", headers=student).json()["role"] == "dean"
    assert (
        client.put(
            f"/api/auth/users/{admin_user['id']}/role", json={"role": "student"}, headers=admin
        ).status_code
        == 400
    )
    client.post("/api/auth/logout", headers=student)
    assert client.get("/api/auth/me", headers=student).status_code == 401


def test_password_guessing_is_throttled(client):
    register(client, "victim@kbtu.kz")
    codes = [
        client.post(
            "/api/auth/login", json={"email": "victim@kbtu.kz", "password": "guess-1234"}
        ).status_code
        for _ in range(6)
    ]
    assert codes[:5] == [401] * 5 and codes[5] == 429


def test_email_domain_restriction(client, monkeypatch):
    restricted = SimpleNamespace(
        data_dir=auth.get_settings().data_dir, admin_emails="", auth_email_domains="kbtu.kz"
    )
    monkeypatch.setattr(auth, "get_settings", lambda: restricted)
    r = client.post(
        "/api/auth/register",
        json={"email": "x@gmail.com", "password": "password123", "full_name": "Ххх Ххх"},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------- заявления
PROFILE = {
    "full_name": "Иванов Иван Иванович",
    "course": "3",
    "program": "6B06101 – Информационные системы",
    "phone": "+7 701 000 00 00",
    "student_id": "23b030001",
}
REGISTRATION = {
    "type": "registration",
    "data": {
        "semester": "spring",
        "disciplines": [
            {"name": "Базы данных", "credits_kz": "3", "ects": "5"},
            {"name": "Алгоритмы", "credits_kz": "3", "ects": "5", "kind": "retake"},
        ],
    },
}


def test_application_flow(client):
    admin, _ = register(client, "admin@kbtu.kz")
    student, _ = register(client, "ivanov@kbtu.kz")
    other, _ = register(client, "petrov@kbtu.kz")
    dean, dean_user = register(client, "dean@kbtu.kz")
    promote(client, admin, dean_user, "dean")

    r = client.post("/api/applications/preview", json=REGISTRATION, headers=student)
    assert r.status_code == 422 and "курс" in r.json()["detail"]  # профиль не заполнен
    assert (
        client.put("/api/auth/me", json=PROFILE, headers=student).json()["student_id"]
        == "23B030001"
    )

    text = " ".join(
        b["text"]
        for b in client.post(
            "/api/applications/preview", json=REGISTRATION, headers=student
        ).json()["blocks"]
    )
    assert "Иванов Иван Иванович" in text and "весеннего семестра" in text
    assert "Алгоритмы (3 кр. KZ, 5 ECTS, ритейк)" in text and "Квитанция" in text

    bad = {"type": "registration", "data": {"semester": "spring", "disciplines": []}}
    assert client.post("/api/applications", json=bad, headers=student).status_code == 422

    submitted = client.post("/api/applications", json=REGISTRATION, headers=student).json()
    assert submitted["status"] == "submitted"
    assert len(client.get("/api/applications/mine", headers=student).json()) == 1
    assert client.get("/api/applications/mine", headers=other).json() == []

    assert client.get("/api/applications/inbox", headers=student).status_code == 403
    inbox = client.get("/api/applications/inbox", headers=dean).json()
    assert inbox["counts"]["submitted"] == 1

    file_url = f"/api/applications/{submitted['id']}/file"
    owner_token = student["Authorization"].split()[1]
    body = client.get(file_url, params={"token": owner_token}).content
    paragraphs = [p.text for p in docx.Document(BytesIO(body)).paragraphs]
    assert "Декану ШИТиИ" in paragraphs and "Заявление" in paragraphs
    assert (
        client.get(file_url, params={"token": other["Authorization"].split()[1]}).status_code == 403
    )
    assert (
        client.get(file_url, params={"token": dean["Authorization"].split()[1]}).status_code == 200
    )

    decision = f"/api/applications/{submitted['id']}/decision"
    assert client.post(decision, json={"decision": "rejected"}, headers=dean).status_code == 422
    done = client.post(
        decision, json={"decision": "approved", "comment": "Согласовано"}, headers=dean
    ).json()
    assert done["status"] == "approved"
    assert (
        client.post(
            decision, json={"decision": "rejected", "comment": "x"}, headers=dean
        ).status_code
        == 409
    )


def test_master_thesis_requires_known_program(client):
    student, _ = register(client, "master@kbtu.kz")
    client.put("/api/auth/me", json={**PROFILE, "course": "1"}, headers=student)
    data = {
        "program": "Неизвестная",
        "topic_kk": "Тақырып атауы",
        "topic_ru": "Тема работы",
        "topic_en": "Thesis topic",
        "supervisor": "Петров П.П.",
    }
    assert (
        client.post(
            "/api/applications/preview",
            json={"type": "master_thesis", "data": data},
            headers=student,
        ).status_code
        == 422
    )
    data["program"] = "7М06105 – Data Science"
    blocks = client.post(
        "/api/applications/preview", json={"type": "master_thesis", "data": data}, headers=student
    ).json()["blocks"]
    assert any("магистранта" in b["text"] for b in blocks)


# ---------------------------------------------------------------- посещаемость
def photograph(pdf: bytes, signed: set[int], students: list[dict], seed: int = 1) -> bytes:
    """Рендер листа, «подписи» в выбранных клетках и съёмка под углом с шумом."""
    page = pymupdf.open(stream=pdf, filetype="pdf")[0].get_pixmap(dpi=150)
    img = np.frombuffer(page.samples, np.uint8).reshape(page.h, page.w, page.n)[:, :, :3].copy()
    k = page.w / PAGE_W
    rng = random.Random(seed)
    for b in layout(students):
        if b["index"] in signed:
            x0, y0, x1, y1 = (v * k for v in b["box"])
            pts = [
                (int(x0 + 8 + i * (x1 - x0 - 16) / 12), int((y0 + y1) / 2 + rng.uniform(-9, 9)))
                for i in range(13)
            ]
            cv2.polylines(img, [np.array(pts)], False, (30, 30, 140), 2)
    h, w = img.shape[:2]
    canvas = np.full((h + 400, w + 400, 3), 90, np.uint8)
    canvas[200 : 200 + h, 200 : 200 + w] = img
    src = np.float32([[200, 200], [200 + w, 200], [200 + w, 200 + h], [200, 200 + h]])
    dst = np.float32([[250, 180], [170 + w, 230], [230 + w, 150 + h], [160, 220 + h]])
    photo = cv2.warpPerspective(
        canvas, cv2.getPerspectiveTransform(src, dst), (w + 400, h + 400), borderValue=(90, 90, 90)
    )
    noise = np.random.default_rng(seed).normal(0, 7, photo.shape)
    photo = np.clip(cv2.GaussianBlur(photo, (3, 3), 0).astype(int) + noise, 0, 255).astype(np.uint8)
    return cv2.imencode(".jpg", photo, [cv2.IMWRITE_JPEG_QUALITY, 75])[1].tobytes()


def test_attendance_from_photo(client):
    admin, _ = register(client, "admin@kbtu.kz")
    student, _ = register(client, "st@kbtu.kz")
    teacher, teacher_user = register(client, "teacher@kbtu.kz")
    promote(client, admin, teacher_user, "teacher")
    students = [{"name": f"Студент {i + 1}", "student_id": f"23B03{i:04d}"} for i in range(12)]
    body = {"course": "Базы данных", "group": "ИС-23-1", "date": "18.11.2026", "students": students}

    assert client.post("/api/attendance/sheets", json=body, headers=student).status_code == 403
    sheet = client.post("/api/attendance/sheets", json=body, headers=teacher).json()
    token = teacher["Authorization"].split()[1]
    pdf = client.get(f"/api/attendance/sheets/{sheet['id']}/pdf", params={"token": token}).content
    assert pdf.startswith(b"%PDF")

    signed = {0, 2, 3, 7, 11}
    r = client.post(
        "/api/attendance/scan",
        files={"photo": ("sheet.jpg", photograph(pdf, signed, students))},
        headers=teacher,
    )
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["qr"] and result["overlay"].startswith("data:image/jpeg")
    statuses = {s["index"]: s["status"] for s in result["sheet"]["students"]}
    assert {i for i, s in statuses.items() if s == "present"} == signed
    assert all(statuses[i] == "absent" for i in range(12) if i not in signed)

    # ручная правка важнее распознавания и не перезаписывается повторным сканом
    client.put(
        f"/api/attendance/sheets/{sheet['id']}/marks",
        json={"marks": {"1": "present"}},
        headers=teacher,
    )
    again = client.post(
        "/api/attendance/scan",
        files={"photo": ("s.jpg", photograph(pdf, signed, students, 2))},
        headers=teacher,
    ).json()
    assert next(s for s in again["sheet"]["students"] if s["index"] == 1)["status"] == "present"

    xlsx = client.get(
        f"/api/attendance/sheets/{sheet['id']}/export", params={"token": token}
    ).content
    rows = list(load_workbook(BytesIO(xlsx)).active.iter_rows(values_only=True))
    assert rows[0][:4] == ("№", "Student ID", "ФИО", "Статус")
    assert rows[1][3] == "Присутствовал" and rows[5][3] == "Отсутствовал"


def test_photo_without_markers_is_rejected(client):
    admin, _ = register(client, "admin@kbtu.kz")
    teacher, teacher_user = register(client, "t@kbtu.kz")
    promote(client, admin, teacher_user, "teacher")
    blank = cv2.imencode(".jpg", np.full((800, 600, 3), 255, np.uint8))[1].tobytes()
    r = client.post("/api/attendance/scan", files={"photo": ("x.jpg", blank)}, headers=teacher)
    assert r.status_code == 422 and "метки" in r.json()["detail"]
