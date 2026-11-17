"""Заявления студентов: генерация по образцу, подача в деканат, рассмотрение."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, ValidationError

from ..auth import current_user, require_dean, user_from_token
from ..config import get_settings
from .templates import (
    MASTER_PROGRAMS,
    SEMESTERS,
    TYPES,
    build_blocks,
    default_year,
    missing_profile,
    render_docx,
)

router = APIRouter(prefix="/api/applications", tags=["Заявления"])
STATUSES = {"submitted": "На рассмотрении", "approved": "Одобрено", "rejected": "Отклонено"}
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@contextmanager
def database():
    root = get_settings().data_dir / "applications"
    root.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(root / "applications.sqlite3", timeout=15) as db:
        db.row_factory = sqlite3.Row
        db.executescript("""
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                type TEXT NOT NULL,
                data TEXT NOT NULL,
                profile TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'submitted',
                comment TEXT,
                created_at TEXT NOT NULL,
                decided_at TEXT,
                decided_by TEXT
            );
        """)
        yield db


class Draft(BaseModel):
    type: str
    data: dict


class Decision(BaseModel):
    decision: Literal["approved", "rejected"]
    comment: str = Field(default="", max_length=1000)


def _validate(draft: Draft, user: dict):
    if draft.type not in TYPES:
        raise HTTPException(400, "Неизвестный вид заявления")
    missing = missing_profile(user)
    if missing:
        raise HTTPException(422, f"Заполните в профиле: {', '.join(missing)}")
    try:
        return TYPES[draft.type]["model"](**draft.data)
    except ValidationError as e:
        first = e.errors()[0]
        field = ".".join(str(x) for x in first["loc"])
        raise HTTPException(422, f"Проверьте поле «{field}»: {first['msg']}") from e


def _row(row: sqlite3.Row) -> dict:
    profile = json.loads(row["profile"])
    return {
        "id": row["id"],
        "type": row["type"],
        "type_title": TYPES[row["type"]]["title"],
        "data": json.loads(row["data"]),
        "student": {k: profile.get(k) for k in ("full_name", "email", "program", "course", "study_group")},
        "status": row["status"],
        "status_name": STATUSES[row["status"]],
        "comment": row["comment"],
        "created_at": row["created_at"],
        "decided_at": row["decided_at"],
        "decided_by": row["decided_by"],
    }


def _file_response(row: sqlite3.Row) -> Response:
    profile = json.loads(row["profile"])
    model = TYPES[row["type"]]["model"](**json.loads(row["data"]))
    created = datetime.fromisoformat(row["created_at"]).date()
    body = render_docx(build_blocks(row["type"], model, profile, created))
    surname = (profile.get("full_name") or "student").split()[0]
    name = f"Заявление_{TYPES[row['type']]['title']}_{surname}_№{row['id']}.docx".replace(" ", "_")
    return Response(body, media_type=DOCX,
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


@router.get("/types")
def types():
    return {
        "types": [{"id": k, "title": v["title"], "description": v["description"], "audience": v["audience"]}
                  for k, v in TYPES.items()],
        "semesters": SEMESTERS,
        "default_year": default_year(),
        "master_programs": MASTER_PROGRAMS,
        "statuses": STATUSES,
    }


@router.post("/preview")
def preview(draft: Draft, user: Annotated[dict, Depends(current_user)]):
    """Текст заявления для просмотра на сайте до отправки."""
    model = _validate(draft, user)
    return {"blocks": build_blocks(draft.type, model, user)}


@router.post("/docx")
def download_draft(draft: Draft, user: Annotated[dict, Depends(current_user)]):
    """Скачать заявление без отправки — например, чтобы подписать и отнести самостоятельно."""
    model = _validate(draft, user)
    return Response(render_docx(build_blocks(draft.type, model, user)), media_type=DOCX,
                    headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote("Заявление.docx")})


@router.post("")
def submit(draft: Draft, user: Annotated[dict, Depends(current_user)]):
    model = _validate(draft, user)
    snapshot = {k: user.get(k) for k in ("full_name", "email", "program", "course", "phone", "study_group",
                                          "student_id", "faculty")}
    with database() as db:
        cur = db.execute(
            "INSERT INTO applications (user_id, type, data, profile, created_at) VALUES (?, ?, ?, ?, ?)",
            (user["id"], draft.type, model.model_dump_json(), json.dumps(snapshot, ensure_ascii=False),
             datetime.now(UTC).isoformat(timespec="seconds")),
        )
        return _row(db.execute("SELECT * FROM applications WHERE id = ?", (cur.lastrowid,)).fetchone())


@router.get("/mine")
def mine(user: Annotated[dict, Depends(current_user)]):
    with database() as db:
        return [_row(r) for r in db.execute(
            "SELECT * FROM applications WHERE user_id = ? ORDER BY id DESC", (user["id"],))]


@router.get("/inbox")
def inbox(_: Annotated[dict, Depends(require_dean)], status: str = "", type: str = ""):
    sql, args = ["SELECT * FROM applications WHERE 1=1"], []
    if status:
        sql.append("AND status = ?")
        args.append(status)
    if type:
        sql.append("AND type = ?")
        args.append(type)
    with database() as db:
        rows = [_row(r) for r in db.execute(" ".join(sql) + " ORDER BY id DESC", args)]
        counts = dict(db.execute("SELECT status, COUNT(*) FROM applications GROUP BY status").fetchall())
    return {"items": rows, "counts": {s: counts.get(s, 0) for s in STATUSES}}


@router.post("/{app_id}/decision")
def decide(app_id: int, body: Decision, dean: Annotated[dict, Depends(require_dean)]):
    if body.decision == "rejected" and not body.comment.strip():
        raise HTTPException(422, "Укажите причину отказа — студент увидит её в своём кабинете")
    with database() as db:
        row = db.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Заявление не найдено")
        if row["status"] != "submitted":
            raise HTTPException(409, "Решение по заявлению уже принято")
        db.execute("UPDATE applications SET status = ?, comment = ?, decided_at = ?, decided_by = ? WHERE id = ?",
                   (body.decision, body.comment.strip() or None, datetime.now(UTC).isoformat(timespec="seconds"),
                    dean["full_name"] or dean["email"], app_id))
        return _row(db.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone())


@router.get("/{app_id}/file")
def file(app_id: int, token: str = ""):
    """DOCX поданного заявления: владельцу и деканату. Токен в query — ссылку открывает браузер."""
    user = user_from_token(token)
    if not user:
        raise HTTPException(401, "Войдите в аккаунт")
    with database() as db:
        row = db.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Заявление не найдено")
    if row["user_id"] != user["id"] and user["role"] not in ("dean", "admin"):
        raise HTTPException(403, "Это заявление другого студента")
    return _file_response(row)

