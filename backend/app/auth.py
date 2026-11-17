"""Учётные записи: регистрация по email и паролю, сессии, роли и проверка доступа.

Роли:
    student — студент: ассистент, заявления, мой диплом, проверка практики;
    teacher — преподаватель: + посещаемость;
    dean    — деканат: + входящие заявления, реестр дипломов, документооборот, база знаний;
    admin   — администратор: всё, включая пользователей и исследовательские разделы.

Новые пользователи получают роль student. Повысить роль может администратор;
адреса из ADMIN_EMAILS становятся администраторами при регистрации.
Пароли хранятся как scrypt с солью, в базе — только SHA-256 токенов сессий.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import get_settings

router = APIRouter(prefix="/api/auth", tags=["Учётные записи"])

Role = Literal["student", "teacher", "dean", "admin"]
ROLE_NAMES = {"student": "Студент", "teacher": "Преподаватель", "dean": "Деканат", "admin": "Администратор"}
SESSION_TTL = 7 * 86400
PROFILE_FIELDS = ("full_name", "student_id", "faculty", "program", "course", "study_group", "phone")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# защита от перебора паролей: 5 ошибок подряд — блокировка на 5 минут
_failures: dict[str, list[float]] = {}
_failures_lock = threading.Lock()


@contextmanager
def database():
    root = get_settings().data_dir / "auth"
    root.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(root / "users.sqlite3", timeout=15) as db:
        db.row_factory = sqlite3.Row
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                salt TEXT NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'student',
                full_name TEXT NOT NULL DEFAULT '',
                student_id TEXT NOT NULL DEFAULT '',
                faculty TEXT NOT NULL DEFAULT '',
                program TEXT NOT NULL DEFAULT '',
                course TEXT NOT NULL DEFAULT '',
                study_group TEXT NOT NULL DEFAULT '',
                phone TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires REAL NOT NULL
            );
        """)
        yield db


def _hash(password: str, salt: str) -> str:
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _public(row: sqlite3.Row) -> dict:
    user = {k: row[k] for k in ("id", "email", "role", *PROFILE_FIELDS)}
    user["role_name"] = ROLE_NAMES.get(row["role"], row["role"])
    return user


def _admin_emails() -> set[str]:
    return {e.strip().lower() for e in get_settings().admin_emails.split(",") if e.strip()}


def _check_rate(email: str) -> None:
    now = time.time()
    with _failures_lock:
        recent = [t for t in _failures.get(email, []) if now - t < 300]
        _failures[email] = recent
        if len(recent) >= 5:
            raise HTTPException(429, "Слишком много неудачных попыток. Попробуйте через 5 минут.")


def _fail(email: str) -> None:
    with _failures_lock:
        _failures.setdefault(email, []).append(time.time())


def _new_session(db, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    db.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))
    db.execute("INSERT INTO sessions VALUES (?, ?, ?)", (_token_hash(token), user_id, time.time() + SESSION_TTL))
    return token


# ---------------------------------------------------------------- модели
class Credentials(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    email: str = Field(max_length=200)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize(cls, value: str) -> str:
        value = value.lower()
        if not EMAIL_RE.match(value):
            raise ValueError("Некорректный email")
        return value


class Registration(Credentials):
    full_name: str = Field(min_length=3, max_length=150)


class Profile(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    full_name: str = Field(min_length=3, max_length=150)
    student_id: str = Field(default="", max_length=30, pattern=r"^[A-Za-z0-9-]*$")
    faculty: str = Field(default="", max_length=150)
    program: str = Field(default="", max_length=200)
    course: str = Field(default="", max_length=10)
    study_group: str = Field(default="", max_length=50)
    phone: str = Field(default="", max_length=30)


class RoleChange(BaseModel):
    role: Role


# ---------------------------------------------------------------- проверка доступа
def user_from_token(token: str) -> dict | None:
    if not token:
        return None
    with database() as db:
        row = db.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ? AND s.expires > ?",
            (_token_hash(token), time.time()),
        ).fetchone()
        return _public(row) if row else None


def optional_user(authorization: Annotated[str, Header()] = "") -> dict | None:
    return user_from_token(authorization.removeprefix("Bearer ").strip())


def current_user(user: Annotated[dict | None, Depends(optional_user)]) -> dict:
    if not user:
        raise HTTPException(401, "Войдите в аккаунт")
    return user


class RoleGuard:
    """Зависимость FastAPI: пропускает только пользователей с перечисленными ролями.

    Экземпляры объявлены на уровне модуля, поэтому в тестах их можно подменить через
    app.dependency_overrides.
    """

    def __init__(self, *roles: str):
        self.roles = set(roles)

    def __call__(self, user: Annotated[dict, Depends(current_user)]) -> dict:
        if user["role"] not in self.roles:
            raise HTTPException(403, "Недостаточно прав для этого раздела")
        return user


require_teacher = RoleGuard("teacher", "dean", "admin")
require_dean = RoleGuard("dean", "admin")
require_admin = RoleGuard("admin")


# ---------------------------------------------------------------- API
@router.post("/register")
def register(body: Registration):
    domains = [d.strip().lower() for d in get_settings().auth_email_domains.split(",") if d.strip()]
    if domains and body.email.rsplit("@", 1)[1] not in domains:
        raise HTTPException(422, f"Регистрация только с адресом {' или '.join('@' + d for d in domains)}")
    salt = secrets.token_hex(16)
    role = "admin" if body.email in _admin_emails() else "student"
    with database() as db:
        try:
            cur = db.execute(
                "INSERT INTO users (email, salt, password, role, full_name, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (body.email, salt, _hash(body.password, salt), role, " ".join(body.full_name.split()),
                 datetime.now(UTC).isoformat(timespec="seconds")),
            )
        except sqlite3.IntegrityError as e:
            raise HTTPException(409, "Этот email уже зарегистрирован. Войдите в аккаунт.") from e
        token = _new_session(db, cur.lastrowid)
        row = db.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
    return {"token": token, "user": _public(row)}


@router.post("/login")
def login(body: Credentials):
    _check_rate(body.email)
    with database() as db:
        row = db.execute("SELECT * FROM users WHERE email = ?", (body.email,)).fetchone()
        # хэш считаем и для несуществующего пользователя — время ответа не выдаёт, есть ли аккаунт
        digest = _hash(body.password, row["salt"] if row else "00" * 16)
        if not row or not hmac.compare_digest(row["password"], digest):
            _fail(body.email)
            raise HTTPException(401, "Неверный email или пароль")
        token = _new_session(db, row["id"])
    return {"token": token, "user": _public(row)}


@router.post("/logout")
def logout(authorization: Annotated[str, Header()] = ""):
    with database() as db:
        db.execute("DELETE FROM sessions WHERE token = ?", (_token_hash(authorization.removeprefix("Bearer ").strip()),))
    return {"ok": True}


@router.get("/me")
def me(user: Annotated[dict, Depends(current_user)]):
    return user


@router.put("/me")
def update_profile(body: Profile, user: Annotated[dict, Depends(current_user)]):
    data = body.model_dump()
    data["student_id"] = data["student_id"].upper()
    data["full_name"] = " ".join(data["full_name"].split())
    with database() as db:
        db.execute(f"UPDATE users SET {', '.join(f'{k} = ?' for k in data)} WHERE id = ?", (*data.values(), user["id"]))
        return _public(db.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone())


@router.get("/users")
def users(_: Annotated[dict, Depends(require_admin)]):
    with database() as db:
        return [_public(r) for r in db.execute("SELECT * FROM users ORDER BY created_at DESC")]


@router.put("/users/{user_id}/role")
def change_role(user_id: int, body: RoleChange, admin: Annotated[dict, Depends(require_admin)]):
    if user_id == admin["id"] and body.role != "admin":
        raise HTTPException(400, "Нельзя снять роль администратора с самого себя")
    with database() as db:
        # роль читается из базы при каждом запросе — новые права действуют сразу
        if not db.execute("UPDATE users SET role = ? WHERE id = ?", (body.role, user_id)).rowcount:
            raise HTTPException(404, "Пользователь не найден")
        return _public(db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


@router.get("/roles")
def roles():
    return ROLE_NAMES
