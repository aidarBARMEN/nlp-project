"""API посещаемости: листы, распознавание фото, ручная правка, выгрузка Excel для портала."""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from io import BytesIO
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, Side
from pydantic import BaseModel, ConfigDict, Field

from ..auth import require_teacher, user_from_token
from ..config import get_settings
from .sheet import (
    ROWS_PER_PAGE,
    ScanError,
    layout,
    overlay,
    read_qr,
    render_pdf,
    score_boxes,
    warp_page,
)

router = APIRouter(prefix="/api/attendance", tags=["Посещаемость"])
Teacher = Annotated[dict, Depends(require_teacher)]
MAX_PHOTO_MB = 15
STATUS_NAMES = {"present": "Присутствовал", "absent": "Отсутствовал", "uncertain": "Проверить"}


@contextmanager
def database():
    root = get_settings().data_dir / "attendance"
    root.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(root / "attendance.sqlite3", timeout=15) as db:
        db.row_factory = sqlite3.Row
        db.executescript("""
            CREATE TABLE IF NOT EXISTS sheets (
                id INTEGER PRIMARY KEY,
                owner_id INTEGER NOT NULL,
                course TEXT NOT NULL,
                study_group TEXT NOT NULL,
                date TEXT NOT NULL,
                students TEXT NOT NULL,
                marks TEXT NOT NULL DEFAULT '{}',
                scanned_pages TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        yield db


class Student(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=150)
    student_id: str = Field(default="", max_length=30)


class NewSheet(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    course: str = Field(min_length=2, max_length=200)
    group: str = Field(min_length=1, max_length=50)
    date: str = Field(pattern=r"^\d{2}\.\d{2}\.\d{4}$")
    students: list[Student] = Field(min_length=1, max_length=200)


class Marks(BaseModel):
    # номер студента в списке -> статус; правка преподавателя важнее распознавания
    marks: dict[str, Literal["present", "absent"]]


def _sheet(row: sqlite3.Row) -> dict:
    students = json.loads(row["students"])
    marks = json.loads(row["marks"])
    rows = []
    for i, st in enumerate(students):
        mark = marks.get(str(i), {})
        rows.append({**st, "index": i, "status": mark.get("status"), "ink": mark.get("ink"),
                     "manual": mark.get("manual", False)})
    counts = {s: sum(r["status"] == s for r in rows) for s in ("present", "absent", "uncertain")}
    counts["unknown"] = sum(r["status"] is None for r in rows)
    pages = max(1, -(-len(students) // ROWS_PER_PAGE))
    return {"id": row["id"], "course": row["course"], "group": row["study_group"], "date": row["date"],
            "students": rows, "counts": counts, "pages": pages,
            "scanned_pages": json.loads(row["scanned_pages"]), "created_at": row["created_at"],
            "updated_at": row["updated_at"]}


def _load(db, sheet_id: int, user: dict) -> sqlite3.Row:
    row = db.execute("SELECT * FROM sheets WHERE id = ?", (sheet_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Лист не найден")
    if row["owner_id"] != user["id"] and user["role"] not in ("dean", "admin"):
        raise HTTPException(403, "Это лист другого преподавателя")
    return row


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@router.post("/roster")
async def parse_roster(_: Teacher, file: Annotated[UploadFile, File()]):
    """Список группы из Excel: ищем колонки с ФИО и ID по заголовкам."""
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(400, "Нужен файл Excel .xlsx")
    try:
        ws = load_workbook(BytesIO(await file.read()), read_only=True, data_only=True).active
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, "Не удалось открыть Excel-файл") from e
    rows = [[str(c).strip() if c is not None else "" for c in r] for r in ws.iter_rows(values_only=True)]
    header_i = next((i for i, r in enumerate(rows[:10]) if any(re.search(r"фио|name|студент", c, re.I) for c in r)), None)
    if header_i is None:
        raise HTTPException(422, "Не найдена колонка «ФИО»: добавьте строку заголовков")
    header = rows[header_i]
    name_col = next(i for i, c in enumerate(header) if re.search(r"фио|name|студент", c, re.I))
    id_col = next((i for i, c in enumerate(header) if re.search(r"\bid\b|айди|номер|student id", c, re.I)), None)
    students = []
    for r in rows[header_i + 1:]:
        name = r[name_col] if name_col < len(r) else ""
        if len(name) >= 2:
            students.append({"name": " ".join(name.split()),
                             "student_id": r[id_col] if id_col is not None and id_col < len(r) else ""})
    if not students:
        raise HTTPException(422, "В файле нет студентов")
    return {"students": students}


@router.post("/sheets")
def create_sheet(body: NewSheet, user: Teacher):
    with database() as db:
        cur = db.execute(
            "INSERT INTO sheets (owner_id, course, study_group, date, students, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user["id"], body.course, body.group, body.date,
             json.dumps([s.model_dump() for s in body.students], ensure_ascii=False), _now(), _now()),
        )
        return _sheet(db.execute("SELECT * FROM sheets WHERE id = ?", (cur.lastrowid,)).fetchone())


@router.get("/sheets")
def list_sheets(user: Teacher):
    with database() as db:
        rows = db.execute("SELECT * FROM sheets WHERE owner_id = ? ORDER BY id DESC", (user["id"],)).fetchall()
        return [_sheet(r) for r in rows]


@router.get("/sheets/{sheet_id}")
def get_sheet(sheet_id: int, user: Teacher):
    with database() as db:
        return _sheet(_load(db, sheet_id, user))


@router.get("/sheets/{sheet_id}/pdf")
def sheet_pdf(sheet_id: int, token: str = ""):
    """PDF для печати. Токен в query: ссылку открывает браузер."""
    user = user_from_token(token)
    if not user or user["role"] not in ("teacher", "dean", "admin"):
        raise HTTPException(401, "Войдите как преподаватель")
    with database() as db:
        row = _load(db, sheet_id, user)
    sheet = {"id": row["id"], "course": row["course"], "group": row["study_group"], "date": row["date"],
             "students": json.loads(row["students"])}
    name = f"Посещаемость_{row['study_group']}_{row['date']}.pdf"
    return Response(render_pdf(sheet), media_type="application/pdf",
                    headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(name)}"})


@router.post("/scan")
async def scan(user: Teacher, photo: Annotated[UploadFile, File()], sheet_id: int | None = None):
    """Фото подписанного листа: номер листа и страницы берутся из QR-кода."""
    data = await photo.read()
    if len(data) > MAX_PHOTO_MB * 1024 * 1024:
        raise HTTPException(400, f"Фото больше {MAX_PHOTO_MB} МБ")
    try:
        page_img = warp_page(data)
    except ScanError as e:
        raise HTTPException(422, str(e)) from e
    qr = read_qr(page_img)
    if qr:
        sheet_id, page_no = qr
    elif sheet_id is None:
        raise HTTPException(422, "QR-код на листе не прочитан. Откройте лист в списке и загрузите фото в нём.")
    else:
        page_no = 0
    with database() as db:
        row = _load(db, sheet_id, user)
        students = json.loads(row["students"])
        boxes = [b for b in layout(students) if b["page"] == page_no]
        if not boxes:
            raise HTTPException(422, "На этой странице листа нет студентов")
        scores = score_boxes(page_img, boxes)
        marks = json.loads(row["marks"])
        for s in scores:
            old = marks.get(str(s["index"]), {})
            if old.get("manual"):  # ручную отметку преподавателя повторный скан не перезаписывает
                continue
            marks[str(s["index"])] = {"status": s["status"], "ink": s["ink"]}
        pages = sorted(set(json.loads(row["scanned_pages"])) | {page_no})
        db.execute("UPDATE sheets SET marks = ?, scanned_pages = ?, updated_at = ? WHERE id = ?",
                   (json.dumps(marks), json.dumps(pages), _now(), sheet_id))
        sheet = _sheet(db.execute("SELECT * FROM sheets WHERE id = ?", (sheet_id,)).fetchone())
    return {"sheet": sheet, "page": page_no, "qr": bool(qr), "overlay": overlay(page_img, boxes, scores)}


@router.put("/sheets/{sheet_id}/marks")
def set_marks(sheet_id: int, body: Marks, user: Teacher):
    with database() as db:
        row = _load(db, sheet_id, user)
        count = len(json.loads(row["students"]))
        marks = json.loads(row["marks"])
        for key, status in body.marks.items():
            if not key.isdigit() or int(key) >= count:
                raise HTTPException(422, f"Нет студента с номером {key}")
            marks[key] = {**marks.get(key, {}), "status": status, "manual": True}
        db.execute("UPDATE sheets SET marks = ?, updated_at = ? WHERE id = ?", (json.dumps(marks), _now(), sheet_id))
        return _sheet(db.execute("SELECT * FROM sheets WHERE id = ?", (sheet_id,)).fetchone())


@router.get("/sheets/{sheet_id}/export")
def export(sheet_id: int, token: str = ""):
    """Excel для импорта в портал: одна строка на студента, белое оформление для печати."""
    user = user_from_token(token)
    if not user or user["role"] not in ("teacher", "dean", "admin"):
        raise HTTPException(401, "Войдите как преподаватель")
    with database() as db:
        sheet = _sheet(_load(db, sheet_id, user))
    if sheet["counts"]["uncertain"] or sheet["counts"]["unknown"]:
        raise HTTPException(409, "Сначала проверьте студентов со статусом «Проверить» и отсканируйте все страницы")
    wb = Workbook()
    ws = wb.active
    ws.title = "Посещаемость"
    ws.append(["№", "Student ID", "ФИО", "Статус", "Дата", "Дисциплина", "Группа"])
    for r in sheet["students"]:
        ws.append([r["index"] + 1, r["student_id"], r["name"], STATUS_NAMES[r["status"]], sheet["date"],
                   sheet["course"], sheet["group"]])
    thin = Side(style="thin", color="000000")
    for row in ws.iter_rows():
        for cell in row:
            cell.data_type = "s" if isinstance(cell.value, str) else cell.data_type
            cell.border = Border(left=thin, right=thin, top=thin, bottom=thin)
            cell.font = Font(name="Times New Roman", size=11, bold=cell.row == 1)
            cell.alignment = Alignment(vertical="center", horizontal="center" if cell.column in (1, 4, 5) else "left")
    for col, width in zip("ABCDEFG", [6, 16, 40, 16, 12, 34, 14], strict=True):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = "A2"
    out = BytesIO()
    wb.save(out)
    name = f"Посещаемость_{sheet['group']}_{sheet['date']}.xlsx"
    return Response(out.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})
