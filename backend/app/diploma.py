"""Student-owned diploma submissions. Local prototype accounts; no university SSO."""

import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from io import BytesIO

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import Response
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import get_settings

router = APIRouter(prefix="/api/diploma", tags=["Дипломные работы"])

# Prototype catalog, consistent with the existing synthetic student records.
FACULTIES = {
    "ШИТИ": ["Информационные системы", "Вычислительная техника и ПО"],
    "Бизнес-школа": ["Финансы"],
    "ШПМ": ["Прикладная математика", "Математическое моделирование"],
    "Школа энергетики": ["Нефтегазовое дело"],
    "Морская академия": ["Судовождение"],
}


@router.get("/catalog")
def catalog():
    return {"faculties": FACULTIES, "demo": True}


@contextmanager
def database():
    root = get_settings().data_dir / "diploma"
    root.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(root / "records.sqlite3", timeout=15) as db:
        db.row_factory = sqlite3.Row
        db.executescript("""
            CREATE TABLE IF NOT EXISTS accounts (
                student_id TEXT PRIMARY KEY, salt TEXT NOT NULL, password TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY, student_id TEXT NOT NULL, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS submissions (
                student_id TEXT PRIMARY KEY, body TEXT NOT NULL,
                version INTEGER NOT NULL, updated_at TEXT NOT NULL);
        """)
        yield db


class Credentials(BaseModel):
    student_id: str = Field(pattern=r"^[A-Za-z0-9-]{3,30}$")
    password: str = Field(min_length=8, max_length=128)

    @field_validator("student_id")
    @classmethod
    def canonical_id(cls, value):
        return value.upper()


def password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()


def authenticate(body, register=False):
    with database() as db:
        if register:
            salt = secrets.token_hex(16)
            try:
                db.execute(
                    "INSERT INTO accounts VALUES (?, ?, ?)",
                    (body.student_id, salt, password_hash(body.password, salt)),
                )
            except sqlite3.IntegrityError as exc:
                raise HTTPException(
                    409, "Student ID уже зарегистрирован. Войдите в аккаунт."
                ) from exc
        account = db.execute(
            "SELECT * FROM accounts WHERE student_id=?", (body.student_id,)
        ).fetchone()
        salt = account["salt"] if account else "00" * 16
        digest = password_hash(body.password, salt)
        if not account or not hmac.compare_digest(account["password"], digest):
            raise HTTPException(401, "Неверный Student ID или пароль")
        token = secrets.token_urlsafe(32)
        db.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))
        db.execute(
            "INSERT INTO sessions VALUES (?, ?, ?)",
            (hashlib.sha256(token.encode()).hexdigest(), body.student_id, time.time() + 86400),
        )
        return {"token": token, "student_id": body.student_id}


@router.post("/register")
def register(body: Credentials):
    return authenticate(body, True)


@router.post("/login")
def login(body: Credentials):
    return authenticate(body)


def owner(db, authorization):
    token = (authorization or "").removeprefix("Bearer ")
    row = db.execute(
        "SELECT student_id FROM sessions WHERE token=? AND expires>?",
        (hashlib.sha256(token.encode()).hexdigest(), time.time()),
    ).fetchone()
    if not row:
        raise HTTPException(401, "Войдите в аккаунт студента")
    return row["student_id"]


@router.post("/logout")
def logout(authorization: str = Header(default="")):
    with database() as db:
        token = authorization.removeprefix("Bearer ")
        db.execute(
            "DELETE FROM sessions WHERE token=?", (hashlib.sha256(token.encode()).hexdigest(),)
        )
    return {"ok": True}


class Member(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    student_id: str = Field(pattern=r"^[A-Za-z0-9-]{3,30}$")
    full_name: str = Field(min_length=3, max_length=150)

    @field_validator("student_id")
    @classmethod
    def canonical_id(cls, value):
        return value.upper()


class Submission(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    full_name: str = Field(min_length=3, max_length=150)
    study_group: str = Field(min_length=2, max_length=50)
    faculty: str = Field(min_length=1, max_length=150)
    program: str = Field(min_length=1, max_length=150)
    topic: str = Field(min_length=5, max_length=500)
    supervisor: str = Field(min_length=3, max_length=150)
    members: list[Member] = Field(default_factory=list, max_length=9)
    version: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def distinct_members(self):
        if self.program not in FACULTIES.get(self.faculty, []):
            raise ValueError("Выберите специальность выбранного факультета")
        ids = [m.student_id for m in self.members]
        if len(ids) != len(set(ids)):
            raise ValueError("Участники команды не должны повторяться")
        return self


def record(row):
    return {
        "faculty": "",
        "program": "",
        **json.loads(row["body"]),
        "student_id": row["student_id"],
        "version": row["version"],
        "updated_at": row["updated_at"],
    }


@router.get("/me")
def mine(authorization: str = Header(default="")):
    with database() as db:
        student = owner(db, authorization)
        row = db.execute("SELECT * FROM submissions WHERE student_id=?", (student,)).fetchone()
        return {"student_id": student, "submission": record(row) if row else None}


@router.put("/me")
def save(body: Submission, authorization: str = Header(default="")):
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        student = owner(db, authorization)
        if student in [m.student_id for m in body.members]:
            raise HTTPException(
                422, "Вы уже включены в команду; добавляйте только других участников"
            )
        old = db.execute(
            "SELECT version FROM submissions WHERE student_id=?", (student,)
        ).fetchone()
        version = old[0] if old else 0
        if body.version != version:
            raise HTTPException(
                409, "Запись изменена в другой вкладке. Обновите страницу перед редактированием."
            )
        data = body.model_dump(exclude={"version"})
        # Normalize whitespace consistently for all students.
        for key in ("full_name", "study_group", "topic", "supervisor"):
            data[key] = " ".join(data[key].split())
        stamp = datetime.now(UTC).isoformat()
        db.execute(
            "INSERT INTO submissions VALUES (?, ?, ?, ?) ON CONFLICT(student_id) "
            "DO UPDATE SET body=excluded.body, version=excluded.version, updated_at=excluded.updated_at",
            (student, json.dumps(data, ensure_ascii=False), version + 1, stamp),
        )
        return {**data, "student_id": student, "version": version + 1, "updated_at": stamp}


def require_dean(key):
    path = get_settings().data_dir / "diploma-dean-key.txt"
    if not path.exists() or not hmac.compare_digest(key, path.read_text().strip()):
        raise HTTPException(403, "Нужен ключ доступа деканата")


def all_records(faculty="", program=""):
    if faculty == "__missing__":
        if program:
            raise HTTPException(422, "Для записей без факультета специальность не выбирается")
    elif faculty and faculty not in FACULTIES:
        raise HTTPException(422, "Неизвестный факультет")
    if program and (not faculty or program not in FACULTIES.get(faculty, [])):
        raise HTTPException(422, "Специальность не относится к выбранному факультету")
    with database() as db:
        items = [record(r) for r in db.execute("SELECT * FROM submissions ORDER BY rowid")]
    return [
        item
        for item in items
        if (
            not faculty
            or (not item["faculty"] if faculty == "__missing__" else item["faculty"] == faculty)
        )
        and (not program or item["program"] == program)
    ]


def project_groups(items):
    """Merge only agreeing declarations, never silently discard conflicting project data."""
    groups = {}
    for item in items:
        members = [
            {"student_id": item["student_id"], "full_name": item["full_name"]},
            *item["members"],
        ]
        key = (
            item.get("faculty", ""),
            item.get("program", ""),
            tuple(sorted(m["student_id"] for m in members)),
            " ".join(item["topic"].split()).casefold(),
            " ".join(item["supervisor"].split()).casefold(),
        )
        if key not in groups:
            groups[key] = {
                "faculty": item.get("faculty", "") or "Не указан",
                "program": item.get("program", "") or "Не указана",
                "topic": item["topic"],
                "supervisor": item["supervisor"],
                "members": {m["student_id"]: {**m, "study_group": ""} for m in members},
                "updated_at": item["updated_at"],
            }
        group = groups[key]
        # Each author's own declaration supplies their name and group.
        group["members"][item["student_id"]] = {
            "student_id": item["student_id"],
            "full_name": item["full_name"],
            "study_group": item["study_group"],
        }
        group["updated_at"] = max(group["updated_at"], item["updated_at"])
    return list(groups.values())


@router.get("/records")
def records(x_dean_key: str = Header(default=""), faculty: str = "", program: str = ""):
    require_dean(x_dean_key)
    return all_records(faculty, program)


@router.get("/export")
def export(x_dean_key: str = Header(default=""), faculty: str = "", program: str = ""):
    require_dean(x_dean_key)
    wb = Workbook()
    ws = wb.active
    ws.title = "Дипломные работы"
    ws.append(
        [
            "№ проекта",
            "Тема диплома",
            "Руководитель",
            "Student ID",
            "ФИО участника",
            "Группа",
            "Обновлено (UTC)",
            "Факультет",
            "Специальность",
        ]
    )
    edge = Side(style="medium", color="334155")
    inner = Side(style="thin", color="CBD5E1")
    for number, project in enumerate(project_groups(all_records(faculty, program)), start=1):
        start = ws.max_row + 1
        people = list(project["members"].values())
        end = start + len(people) - 1
        for offset, member in enumerate(people):
            values = [
                str(number),
                project["topic"],
                project["supervisor"],
                member["student_id"],
                member["full_name"],
                member["study_group"],
                project["updated_at"],
                project["faculty"],
                project["program"],
            ]
            ws.append(values)
            for col, cell in enumerate(ws[ws.max_row], start=1):
                cell.data_type = "s"  # Never interpret student text as a formula.
                cell.alignment = Alignment(wrap_text=True, vertical="center")
                cell.fill = PatternFill("solid", fgColor="EFF6FF" if number % 2 else "FFFFFF")
                cell.border = Border(
                    left=edge if col == 1 else inner,
                    right=edge if col == 9 else inner,
                    top=edge if offset == 0 else inner,
                    bottom=edge if start + offset == end else inner,
                )
            # Reserve enough space even for long topics and full names.
            topic_lines = (len(project["topic"]) // 45 + 1 + len(people) - 1) // len(people)
            ws.row_dimensions[start + offset].height = max(
                45, topic_lines * 18, (len(member["full_name"]) // 25 + 1) * 18
            )
        if end > start:
            for col in (1, 2, 3, 7, 8, 9):
                ws.cell(start, col).border = Border(
                    left=edge if col == 1 else inner,
                    right=edge if col == 9 else inner,
                    top=edge,
                    bottom=edge,
                )
                ws.merge_cells(start_row=start, end_row=end, start_column=col, end_column=col)
    for cell in ws[1]:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = PatternFill("solid", fgColor="172554")
    for col, width in zip("ABCDEFGHI", [12, 60, 32, 20, 36, 18, 30, 28, 38], strict=True):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = "A2"
    ws.row_dimensions[1].height = 30
    ws.print_title_rows = "1:1"
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A3
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    out = BytesIO()
    wb.save(out)
    return Response(
        out.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="diploma.xlsx"'},
    )
