"""HTTP API документооборота: /api/edo/*.

Роль пользователя передаётся заголовком X-EDO-Role. Это демонстрация ролевой модели:
в продуктиве роль берётся из учётной записи после входа через университетский SSO.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..config import get_settings
from .catalog import (
    CATEGORIES,
    DOC_TYPES,
    MAX_FILE_MB,
    PERSON_ACCESS,
    PERSON_KINDS,
    PERSONAL_FILE_CHECKLIST,
    ROLES,
    STATUSES,
    access,
    creatable_types,
)
from .store import AccessDenied, NotFound, Store

router = APIRouter(prefix="/api/edo", tags=["Документооборот"])


@lru_cache
def get_store() -> Store:
    return Store(get_settings().data_dir / "edo")


RoleHeader = Annotated[str, Header(alias="X-EDO-Role")]


def _role(role: str) -> str:
    if role not in ROLES:
        raise HTTPException(400, f"Неизвестная роль: {role}")
    return role


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except AccessDenied as e:
        raise HTTPException(403, str(e)) from e
    except NotFound as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


class Decision(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    comment: str | None = Field(default=None, max_length=1000)


@router.get("/meta")
def meta(x_edo_role: RoleHeader = "rector"):
    role = _role(x_edo_role)
    return {
        "roles": [{"code": k, **v} for k, v in ROLES.items()],
        "categories": [
            {"code": k, "name": v["name"], "prefix": v["prefix"], "description": v["description"],
             "confidentiality": v["confidentiality"], "access": v["access"], "create": v["create"],
             "my_access": access(role, k)}
            for k, v in CATEGORIES.items()
        ],
        "doc_types": [
            {"code": k, "name": n, "category": c, "retention_years": r, "route": route,
             "route_names": [ROLES[x]["name"] for x in route]}
            for k, (n, c, r, route) in DOC_TYPES.items()
        ],
        "creatable_types": creatable_types(role),
        "statuses": STATUSES,
        "person_kinds": PERSON_KINDS,
        "person_access": PERSON_ACCESS,
        "checklist": [{"code": c, "name": DOC_TYPES[c][0]} for c in PERSONAL_FILE_CHECKLIST],
        "max_file_mb": MAX_FILE_MB,
    }


@router.get("/dashboard")
def dashboard(x_edo_role: RoleHeader):
    return get_store().dashboard(_role(x_edo_role))


@router.get("/documents")
def documents(x_edo_role: RoleHeader, category: str | None = None, status: str | None = None,
              q: str | None = None, person_id: int | None = None, pending_for_me: bool = False):
    return _call(get_store().list_documents, _role(x_edo_role), category, status, q, person_id, pending_for_me)


@router.post("/documents")
def register(
    x_edo_role: RoleHeader,
    type_code: Annotated[str, Form()],
    title: Annotated[str, Form(max_length=300)] = "",
    person_id: Annotated[int | None, Form()] = None,
    notes: Annotated[str | None, Form(max_length=2000)] = None,
    due_date: Annotated[str | None, Form()] = None,
    file: Annotated[UploadFile | None, File()] = None,
):
    payload = (file.filename or "file", file.file.read()) if file and file.filename else None
    return _call(get_store().register, _role(x_edo_role), type_code, title, person_id or None, notes,
                 due_date or None, payload)


@router.get("/documents/{doc_id}")
def document(doc_id: int, x_edo_role: RoleHeader):
    return _call(get_store().get_document, doc_id, _role(x_edo_role))


@router.post("/documents/{doc_id}/decision")
def decide(doc_id: int, body: Decision, x_edo_role: RoleHeader):
    return _call(get_store().decide, doc_id, _role(x_edo_role), body.decision, body.comment)


@router.post("/documents/{doc_id}/archive")
def archive(doc_id: int, x_edo_role: RoleHeader):
    return _call(get_store().archive, doc_id, _role(x_edo_role))


@router.get("/documents/{doc_id}/file")
def download(doc_id: int, role: str):
    # роль в query: ссылку на файл открывает браузер, заголовок в ней не передать
    path, name = _call(get_store().file_for_download, doc_id, _role(role))
    if not path.exists():
        raise HTTPException(404, "Файл отсутствует в хранилище")
    return FileResponse(path, filename=name, content_disposition_type="inline")


@router.get("/persons")
def persons(x_edo_role: RoleHeader, kind: str | None = None, q: str | None = None):
    return get_store().list_persons(_role(x_edo_role), kind, q)


@router.get("/persons/{person_id}")
def personal_file(person_id: int, x_edo_role: RoleHeader):
    return _call(get_store().personal_file, person_id, _role(x_edo_role))
