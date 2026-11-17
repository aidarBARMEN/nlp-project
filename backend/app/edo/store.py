"""Хранилище ЭДО: метаданные в SQLite, файлы на диске (DATA_DIR/edo/files), журнал действий.

Персональные и медицинские документы не индексируются в базу знаний RAG и не передаются
во внешние LLM: модуль работает только локально.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from .catalog import (
    ALLOWED_EXTENSIONS,
    CATEGORIES,
    DOC_TYPES,
    MAX_FILE_MB,
    PERSON_ACCESS,
    PERSON_KINDS,
    PERSONAL_FILE_CHECKLIST,
    ROLES,
    STATUSES,
    access,
    readable_categories,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS persons (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    full_name TEXT NOT NULL,
    iin_masked TEXT,
    school TEXT,
    program TEXT,
    course INTEGER,
    study_group TEXT,
    position TEXT,
    status TEXT NOT NULL,
    email TEXT,
    is_demo INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    reg_number TEXT NOT NULL UNIQUE,
    type_code TEXT NOT NULL,
    category TEXT NOT NULL,
    person_id INTEGER REFERENCES persons(id),
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    confidentiality TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    due_date TEXT,
    retention_until TEXT NOT NULL,
    notes TEXT,
    file_name TEXT,
    file_path TEXT,
    file_size INTEGER,
    file_sha256 TEXT,
    is_demo INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id),
    step INTEGER NOT NULL,
    role TEXT NOT NULL,
    status TEXT NOT NULL,
    comment TEXT,
    decided_at TEXT
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY,
    document_id INTEGER REFERENCES documents(id),
    at TEXT NOT NULL,
    role TEXT NOT NULL,
    action TEXT NOT NULL,
    details TEXT
);
CREATE INDEX IF NOT EXISTS ix_documents_category ON documents(category, status);
CREATE INDEX IF NOT EXISTS ix_documents_person ON documents(person_id);
CREATE INDEX IF NOT EXISTS ix_approvals_pending ON approvals(role, status);
CREATE INDEX IF NOT EXISTS ix_audit_document ON audit(document_id);
"""

ACTIONS = {
    "registered": "Документ зарегистрирован",
    "routed": "Отправлен на согласование",
    "approved": "Согласовано",
    "rejected": "Отклонено",
    "file_attached": "Прикреплён файл",
    "downloaded": "Файл скачан",
    "viewed": "Просмотр карточки",
    "archived": "Передан в архив",
    "format_checked": "Автопроверка оформления",
}

# документы, оформление которых проверяется автоматически при регистрации
FORMAT_CHECKED_TYPES = {"practice_report": "report", "practice_diary": "diary"}


class AccessDenied(PermissionError):
    pass


class NotFound(LookupError):
    pass


class Store:
    def __init__(self, root: Path):
        self.root = root
        self.files = root / "files"
        self.db_path = root / "edo.sqlite3"
        self._lock = threading.Lock()
        self.files.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.executescript(SCHEMA)
            columns = {r[1] for r in con.execute("PRAGMA table_info(documents)")}
            if "format_check" not in columns:  # миграция баз, созданных до автопроверки
                con.execute("ALTER TABLE documents ADD COLUMN format_check TEXT")
            if not con.execute("SELECT 1 FROM persons LIMIT 1").fetchone():
                seed_demo(con)

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.db_path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA journal_mode = WAL")
        try:
            yield con
            con.commit()
        finally:
            con.close()

    # ------------------------------------------------------------ чтение
    def _card(self, row: sqlite3.Row, role: str) -> dict:
        level = access(role, row["category"])
        d = dict(row)
        d.pop("file_path", None)
        d["type_name"] = DOC_TYPES[d["type_code"]][0]
        d["category_name"] = CATEGORIES[d["category"]]["name"]
        d["status_name"] = STATUSES[d["status"]]
        d["access"] = level
        d["has_file"] = bool(d["file_name"])
        d["overdue"] = bool(d["status"] == "on_approval" and d["due_date"] and d["due_date"] < today())
        d["format_check"] = json.loads(d["format_check"]) if d.get("format_check") else None
        if level != "full":
            # карточка без содержимого: название остаётся (оно не раскрывает диагноз и т.п.),
            # примечания и файл скрыты
            d["notes"] = None
            d["file_name"] = "доступ ограничен" if d["file_name"] else None
            d["file_sha256"] = None
            d["format_check"] = None
        return d

    def list_documents(self, role: str, category: str | None = None, status: str | None = None,
                       q: str | None = None, person_id: int | None = None, pending_for_me: bool = False,
                       limit: int = 300) -> list[dict]:
        cats = readable_categories(role)
        if category:
            if category not in cats:
                raise AccessDenied("Категория недоступна для этой роли")
            cats = [category]
        if not cats:
            return []
        sql = ["SELECT d.*, p.full_name AS person_name FROM documents d LEFT JOIN persons p ON p.id = d.person_id",
               f"WHERE d.category IN ({','.join('?' * len(cats))})"]
        args: list = list(cats)
        if status:
            sql.append("AND d.status = ?")
            args.append(status)
        if person_id:
            sql.append("AND d.person_id = ?")
            args.append(person_id)
        if q:
            sql.append("AND (d.title LIKE ? OR d.reg_number LIKE ? OR p.full_name LIKE ?)")
            args += [f"%{q}%"] * 3
        if pending_for_me:
            sql.append("AND d.id IN (SELECT document_id FROM approvals a WHERE a.status = 'pending' AND a.role = ? "
                       "AND a.step = (SELECT MIN(step) FROM approvals b WHERE b.document_id = a.document_id "
                       "AND b.status = 'pending'))")
            args.append(role)
        sql.append("ORDER BY d.updated_at DESC LIMIT ?")
        args.append(limit)
        with self.connect() as con:
            rows = con.execute(" ".join(sql), args).fetchall()
            return [self._card(r, role) for r in rows]

    def get_document(self, doc_id: int, role: str) -> dict:
        with self.connect() as con:
            row = con.execute("SELECT d.*, p.full_name AS person_name FROM documents d "
                              "LEFT JOIN persons p ON p.id = d.person_id WHERE d.id = ?", (doc_id,)).fetchone()
            if not row:
                raise NotFound("Документ не найден")
            if not access(role, row["category"]):
                raise AccessDenied("Документ недоступен для этой роли")
            card = self._card(row, role)
            card["route"] = [dict(a) | {"role_name": ROLES[a["role"]]["name"]} for a in con.execute(
                "SELECT * FROM approvals WHERE document_id = ? ORDER BY step", (doc_id,))]
            card["audit"] = [dict(a) | {"role_name": ROLES[a["role"]]["name"], "action_name": ACTIONS[a["action"]]}
                             for a in con.execute("SELECT * FROM audit WHERE document_id = ? ORDER BY at DESC, id DESC",
                                                  (doc_id,))]
            pending = next((a for a in card["route"] if a["status"] == "pending"), None)
            card["can_decide"] = bool(pending and pending["role"] == role)
            card["can_archive"] = role in ("archive", "registrar") and row["status"] == "approved"
            if row["confidentiality"] in ("personal", "medical") and card["access"] == "full":
                # просмотр персональных данных фиксируется в журнале
                self._audit(con, doc_id, role, "viewed")
            return card

    def file_for_download(self, doc_id: int, role: str) -> tuple[Path, str]:
        with self.connect() as con:
            row = con.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
            if not row:
                raise NotFound("Документ не найден")
            if access(role, row["category"]) != "full":
                raise AccessDenied("Файл доступен только подразделению-владельцу")
            if not row["file_path"]:
                raise NotFound("К документу не прикреплён файл")
            self._audit(con, doc_id, role, "downloaded")
            return self.files / row["file_path"], row["file_name"]

    # ------------------------------------------------------------ запись
    def register(self, role: str, type_code: str, title: str, person_id: int | None = None,
                 notes: str | None = None, due_date: str | None = None,
                 file: tuple[str, bytes] | None = None) -> dict:
        if type_code not in DOC_TYPES:
            raise ValueError("Неизвестный тип документа")
        name, category, retention, route = DOC_TYPES[type_code]
        if role not in CATEGORIES[category]["create"]:
            raise AccessDenied(f"Роль «{ROLES[role]['name']}» не регистрирует документы категории "
                               f"«{CATEGORIES[category]['name']}»")
        if file:
            ext = Path(file[0]).suffix.lower()
            if ext not in ALLOWED_EXTENSIONS:
                raise ValueError(f"Недопустимый формат файла: {ext}")
            if len(file[1]) > MAX_FILE_MB * 1024 * 1024:
                raise ValueError(f"Файл больше {MAX_FILE_MB} МБ")
        with self._lock, self.connect() as con:
            if person_id and not con.execute("SELECT 1 FROM persons WHERE id = ?", (person_id,)).fetchone():
                raise ValueError("Персона не найдена")
            doc_id = _insert_document(con, type_code, title.strip() or name, person_id, role, now(),
                                      due_date or None, notes, route)
            if file:
                self._attach(con, doc_id, role, *file)
        return self.get_document(doc_id, role)

    def decide(self, doc_id: int, role: str, decision: str, comment: str | None = None) -> dict:
        if decision not in ("approve", "reject"):
            raise ValueError("Решение: approve или reject")
        with self._lock, self.connect() as con:
            row = con.execute("SELECT status FROM documents WHERE id = ?", (doc_id,)).fetchone()
            if not row:
                raise NotFound("Документ не найден")
            step = con.execute("SELECT * FROM approvals WHERE document_id = ? AND status = 'pending' "
                               "ORDER BY step LIMIT 1", (doc_id,)).fetchone()
            if not step or step["role"] != role:
                raise AccessDenied("Сейчас документ согласует другое подразделение")
            if decision == "reject" and not (comment or "").strip():
                raise ValueError("При отклонении укажите причину")
            _decide(con, doc_id, step["id"], role, decision, comment, now())
        return self.get_document(doc_id, role)

    def archive(self, doc_id: int, role: str) -> dict:
        with self._lock, self.connect() as con:
            row = con.execute("SELECT status FROM documents WHERE id = ?", (doc_id,)).fetchone()
            if not row:
                raise NotFound("Документ не найден")
            if role not in ("archive", "registrar") or row["status"] != "approved":
                raise AccessDenied("В архив передаются только утверждённые документы (Архив, Офис Регистратора)")
            con.execute("UPDATE documents SET status = 'archived', updated_at = ? WHERE id = ?", (now(), doc_id))
            self._audit(con, doc_id, role, "archived")
        return self.get_document(doc_id, role)

    def _attach(self, con, doc_id: int, role: str, file_name: str, data: bytes) -> None:
        safe = re.sub(r"[^\w.\-]+", "_", Path(file_name).name)[-120:]
        rel = Path(str(date.today().year)) / f"{doc_id}_{safe}"
        (self.files / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.files / rel).write_bytes(data)
        con.execute("UPDATE documents SET file_name = ?, file_path = ?, file_size = ?, file_sha256 = ? WHERE id = ?",
                    (Path(file_name).name, rel.as_posix(), len(data), hashlib.sha256(data).hexdigest(), doc_id))
        self._audit(con, doc_id, role, "file_attached", Path(file_name).name)
        type_code = con.execute("SELECT type_code FROM documents WHERE id = ?", (doc_id,)).fetchone()[0]
        kind = FORMAT_CHECKED_TYPES.get(type_code)
        if kind and Path(file_name).suffix.lower() == ".docx":
            from ..practice.checker import check_diary, check_report

            try:
                result = (check_report if kind == "report" else check_diary)(data, Path(file_name).name).to_dict()
            except Exception:  # noqa: BLE001 — повреждённый файл не должен мешать регистрации
                result = None
            if result:
                con.execute("UPDATE documents SET format_check = ? WHERE id = ?",
                            (json.dumps(result, ensure_ascii=False), doc_id))
                c = result["counts"]
                self._audit(con, doc_id, role, "format_checked",
                            "Соответствует требованиям" if result["ready"] else
                            f"Ошибок: {c['fail']}, замечаний: {c['warn']}")

    @staticmethod
    def _audit(con, doc_id: int | None, role: str, action: str, details: str | None = None, at: str | None = None):
        con.execute("INSERT INTO audit (document_id, at, role, action, details) VALUES (?, ?, ?, ?, ?)",
                    (doc_id, at or now(), role, action, details))

    # ------------------------------------------------------------ персоны и личные дела
    def list_persons(self, role: str, kind: str | None = None, q: str | None = None) -> list[dict]:
        kinds = PERSON_ACCESS.get(role, [])
        if kind:
            kinds = [k for k in kinds if k == kind]
        if not kinds:
            return []
        sql, args = [f"SELECT * FROM persons WHERE kind IN ({','.join('?' * len(kinds))})"], list(kinds)
        if q:
            sql.append("AND (full_name LIKE ? OR study_group LIKE ? OR program LIKE ?)")
            args += [f"%{q}%"] * 3
        sql.append("ORDER BY kind, full_name")
        with self.connect() as con:
            persons = [dict(r) for r in con.execute(" ".join(sql), args)]
            counts = dict(con.execute("SELECT person_id, COUNT(*) FROM documents GROUP BY person_id").fetchall())
            have = {}
            for pid, code in con.execute("SELECT person_id, type_code FROM documents WHERE status != 'rejected'"):
                have.setdefault(pid, set()).add(code)
        for p in persons:
            p["kind_name"] = PERSON_KINDS[p["kind"]]
            p["documents"] = counts.get(p["id"], 0)
            if p["kind"] == "student":
                p["completeness"] = round(
                    len(have.get(p["id"], set()) & set(PERSONAL_FILE_CHECKLIST)) / len(PERSONAL_FILE_CHECKLIST), 2)
        return persons

    def personal_file(self, person_id: int, role: str) -> dict:
        with self.connect() as con:
            row = con.execute("SELECT * FROM persons WHERE id = ?", (person_id,)).fetchone()
            if not row:
                raise NotFound("Персона не найдена")
            if row["kind"] not in PERSON_ACCESS.get(role, []):
                raise AccessDenied("Карточка недоступна для этой роли")
            all_codes = {r[0] for r in con.execute(
                "SELECT type_code FROM documents WHERE person_id = ? AND status != 'rejected'", (person_id,))}
            cats = readable_categories(role)
            hidden = con.execute(
                f"SELECT COUNT(*) FROM documents WHERE person_id = ? AND category NOT IN ({','.join('?' * len(cats))})",
                [person_id, *cats]).fetchone()[0] if cats else 0
        person = dict(row) | {"kind_name": PERSON_KINDS[row["kind"]]}
        docs = self.list_documents(role, person_id=person_id)
        groups = []
        for cat, meta in CATEGORIES.items():
            items = [d for d in docs if d["category"] == cat]
            if items:
                groups.append({"category": cat, "name": meta["name"], "documents": items})
        checklist = []
        if row["kind"] == "student":
            # комплектность видна всем, кто видит личное дело: только факт наличия, без содержимого
            checklist = [{"type_code": c, "name": DOC_TYPES[c][0], "present": c in all_codes,
                          "category_name": CATEGORIES[DOC_TYPES[c][1]]["name"]} for c in PERSONAL_FILE_CHECKLIST]
        return {"person": person, "groups": groups, "checklist": checklist, "hidden_documents": hidden}

    # ------------------------------------------------------------ сводка
    def dashboard(self, role: str) -> dict:
        cats = readable_categories(role)
        if not cats:
            return {"totals": {}, "by_category": [], "pending": [], "recent": [], "expiring": []}
        marks = ",".join("?" * len(cats))
        month_ago = (datetime.now(UTC) - timedelta(days=30)).isoformat(timespec="seconds")
        with self.connect() as con:
            totals = dict(con.execute(f"SELECT status, COUNT(*) FROM documents WHERE category IN ({marks}) "
                                      "GROUP BY status", cats).fetchall())
            overdue = con.execute(f"SELECT COUNT(*) FROM documents WHERE category IN ({marks}) AND status = "
                                  "'on_approval' AND due_date < ?", [*cats, today()]).fetchone()[0]
            new30 = con.execute(f"SELECT COUNT(*) FROM documents WHERE category IN ({marks}) AND created_at >= ?",
                                [*cats, month_ago]).fetchone()[0]
            by_cat = dict(con.execute(f"SELECT category, COUNT(*) FROM documents WHERE category IN ({marks}) "
                                      "GROUP BY category", cats).fetchall())
            by_cat_pending = dict(con.execute(f"SELECT category, COUNT(*) FROM documents WHERE category IN ({marks}) "
                                              "AND status = 'on_approval' GROUP BY category", cats).fetchall())
            recent = [dict(r) | {"role_name": ROLES[r["role"]]["name"], "action_name": ACTIONS[r["action"]]}
                      for r in con.execute(
                          f"SELECT a.*, d.reg_number, d.title FROM audit a JOIN documents d ON d.id = a.document_id "
                          f"WHERE d.category IN ({marks}) AND a.action != 'viewed' ORDER BY a.at DESC, a.id DESC "
                          "LIMIT 12", cats)]
            expiring = [dict(r) for r in con.execute(
                f"SELECT id, reg_number, title, retention_until FROM documents WHERE category IN ({marks}) "
                "AND retention_until <= ? ORDER BY retention_until LIMIT 6",
                [*cats, (date.today() + timedelta(days=365)).isoformat()])]
        pending = self.list_documents(role, pending_for_me=True, limit=8)
        return {
            "totals": {"all": sum(totals.values()), "overdue": overdue, "new_30d": new30,
                       **{s: totals.get(s, 0) for s in STATUSES}},
            "pending_for_me": len(self.list_documents(role, pending_for_me=True)),
            "by_category": [{"category": c, "name": CATEGORIES[c]["name"], "count": by_cat.get(c, 0),
                             "on_approval": by_cat_pending.get(c, 0), "access": access(role, c)} for c in cats],
            "pending": pending,
            "recent": recent,
            "expiring": expiring,
        }


# ---------------------------------------------------------------- общие операции
def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def today() -> str:
    return date.today().isoformat()


def _next_reg_number(con, category: str, year: int) -> str:
    prefix = CATEGORIES[category]["prefix"]
    pattern = f"{prefix}-{year}/%"
    last = con.execute("SELECT reg_number FROM documents WHERE reg_number LIKE ? ORDER BY reg_number DESC LIMIT 1",
                       (pattern,)).fetchone()
    seq = int(last[0].rsplit("/", 1)[1]) + 1 if last else 1
    return f"{prefix}-{year}/{seq:05d}"


def _insert_document(con, type_code: str, title: str, person_id: int | None, role: str, created: str,
                     due_date: str | None, notes: str | None, route: list[str], is_demo: bool = False) -> int:
    _name, category, retention, _route = DOC_TYPES[type_code]
    created_dt = datetime.fromisoformat(created)
    retention_until = date(created_dt.year + retention, 12, 31).isoformat()
    reg = _next_reg_number(con, category, created_dt.year)
    status = "on_approval" if route else "approved"
    cur = con.execute(
        "INSERT INTO documents (reg_number, type_code, category, person_id, title, status, confidentiality, "
        "created_by, created_at, updated_at, due_date, retention_until, notes, is_demo) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (reg, type_code, category, person_id, title, status, CATEGORIES[category]["confidentiality"], role,
         created, created, due_date, retention_until, notes, int(is_demo)))
    doc_id = cur.lastrowid
    Store._audit(con, doc_id, role, "registered", reg, at=created)
    for step, r in enumerate(route, start=1):
        con.execute("INSERT INTO approvals (document_id, step, role, status) VALUES (?, ?, ?, 'pending')",
                    (doc_id, step, r))
    if route:
        Store._audit(con, doc_id, role, "routed", " → ".join(ROLES[r]["name"] for r in route), at=created)
    return doc_id


def _decide(con, doc_id: int, approval_id: int, role: str, decision: str, comment: str | None, at: str) -> None:
    status = "approved" if decision == "approve" else "rejected"
    con.execute("UPDATE approvals SET status = ?, comment = ?, decided_at = ? WHERE id = ?",
                (status, comment, at, approval_id))
    Store._audit(con, doc_id, role, status, comment, at=at)
    if decision == "reject":
        con.execute("UPDATE approvals SET status = 'skipped' WHERE document_id = ? AND status = 'pending'", (doc_id,))
        con.execute("UPDATE documents SET status = 'rejected', updated_at = ? WHERE id = ?", (at, doc_id))
    elif not con.execute("SELECT 1 FROM approvals WHERE document_id = ? AND status = 'pending'", (doc_id,)).fetchone():
        con.execute("UPDATE documents SET status = 'approved', updated_at = ? WHERE id = ?", (at, doc_id))
    else:
        con.execute("UPDATE documents SET updated_at = ? WHERE id = ?", (at, doc_id))


# ---------------------------------------------------------------- демонстрационные данные
DEMO_STUDENTS = [
    ("Аманова Айгерим Ерлановна", "ШИТИ", "Информационные системы", 2, "ИС-24-1"),
    ("Бекенов Нурлан Маратович", "ШИТИ", "Вычислительная техника и ПО", 3, "ВТ-23-2"),
    ("Жумабаева Дана Серикқызы", "Бизнес-школа", "Финансы", 1, "ФН-25-1"),
    ("Касымов Тимур Аскарович", "ШПМ", "Прикладная математика", 4, "ПМ-22-1"),
    ("Мухтарова Алия Бауыржановна", "ШИТИ", "Информационные системы", 3, "ИС-23-1"),
    ("Оспанов Ерлан Даниярович", "Школа энергетики", "Нефтегазовое дело", 2, "НГ-24-3"),
    ("Сагинтаева Мадина Нуржановна", "ШПМ", "Математическое моделирование", 1, "ММ-25-1"),
    ("Тулегенов Арман Ерболович", "Морская академия", "Судовождение", 2, "СВ-24-1"),
]
DEMO_APPLICANTS = [
    ("Абдрахманов Санжар Ильясович", "Информационные системы"),
    ("Ермекова Аружан Талгатовна", "Финансы"),
    ("Исаев Даулет Русланович", "Нефтегазовое дело"),
    ("Нурланова Камила Азаматовна", "Прикладная математика"),
]
DEMO_EMPLOYEES = [
    ("Ахметов Бахыт Кайратович", "Доцент, ШИТИ"),
    ("Смагулова Гульнара Ерлановна", "Старший преподаватель, ШПМ"),
    ("Ли Виктор Сергеевич", "Руководитель отдела практики"),
]


def seed_demo(con) -> None:
    """Вымышленные студенты, абитуриенты и сотрудники; все записи помечены is_demo."""
    rng = random.Random(2026)

    def when(days_ago_max: int = 120) -> str:
        return (datetime.now(UTC) - timedelta(days=rng.randint(1, days_ago_max), hours=rng.randint(0, 9),
                                              minutes=rng.randint(0, 59))).isoformat(timespec="seconds")

    def add_person(**kw) -> int:
        kw.setdefault("iin_masked", f"••••••••{rng.randint(1000, 9999)}")
        cols = ", ".join(kw) + ", is_demo"
        cur = con.execute(f"INSERT INTO persons ({cols}) VALUES ({', '.join('?' * len(kw))}, 1)", tuple(kw.values()))
        return cur.lastrowid

    def add_doc(code: str, person: int | None, creator: str, title: str | None = None,
                decide: int | None = None, reject: bool = False, due_in: int | None = None) -> int:
        name, _cat, _ret, route = DOC_TYPES[code]
        created = when()
        due = (date.today() + timedelta(days=due_in)).isoformat() if due_in is not None and route else None
        doc_id = _insert_document(con, code, title or name, person, creator, created, due, None, route, is_demo=True)
        steps = con.execute("SELECT id, role FROM approvals WHERE document_id = ? ORDER BY step", (doc_id,)).fetchall()
        n = len(steps) if decide is None else min(decide, len(steps))
        t = datetime.fromisoformat(created)
        for i, (aid, role) in enumerate(steps[:n]):
            t += timedelta(hours=rng.randint(2, 40))
            last = i == n - 1
            _decide(con, doc_id, aid, role, "reject" if (reject and last) else "approve",
                    "Нет подписи заявителя на второй странице" if (reject and last) else None,
                    min(t, datetime.now(UTC)).isoformat(timespec="seconds"))
        return doc_id

    students, employees = [], []
    for i, (name, school, program, course, group) in enumerate(DEMO_STUDENTS):
        status = "Академический отпуск" if i == 7 else "Обучается"
        pid = add_person(kind="student", full_name=name, school=school, program=program, course=course,
                         study_group=group, status=status, email=f"student{i + 1}@demo.local")
        students.append(pid)
        checklist = list(PERSONAL_FILE_CHECKLIST)
        if i in (2, 6):  # первокурсники с неполным личным делом
            checklist = checklist[:4]
        for code in checklist:
            add_doc(code, pid, "medical" if code == "med_086" else "registrar")
        add_doc("payment_receipt", pid, "accounting", f"Оплата за осенний семестр, {name.split()[0]}")
        if course >= 3:
            add_doc("practice_referral", pid, "practice")
            add_doc("practice_report", pid, "practice", decide=0 if i % 2 else None, due_in=rng.randint(-4, 10))
        if i == 7:
            add_doc("academic_leave", pid, "dean", decide=2, due_in=3)
        if i in (1, 4):
            add_doc("study_reference", pid, "registrar", "Справка с места учёбы для военкомата", decide=0, due_in=1)
        if i == 3:
            add_doc("appeal", pid, "dean", "Апелляция по дисциплине «Численные методы»", decide=1, due_in=-2)
        if i == 5:
            add_doc("sick_leave", pid, "medical", decide=1, due_in=2)
        add_doc("vaccination", pid, "medical")

    for i, (name, program) in enumerate(DEMO_APPLICANTS):
        pid = add_person(kind="applicant", full_name=name, program=program, status="Абитуриент",
                         email=f"applicant{i + 1}@demo.local")
        add_doc("applicant_form", pid, "admissions", decide=0 if i < 2 else None, due_in=rng.randint(-3, 7))
        add_doc("ent_certificate", pid, "admissions")
        if i % 2 == 0:
            add_doc("grant_certificate", pid, "admissions")
        add_doc("med_086", pid, "medical", decide=0 if i == 3 else None, due_in=4)

    for i, (name, position) in enumerate(DEMO_EMPLOYEES):
        pid = add_person(kind="employee", full_name=name, position=position, status="Работает",
                         email=f"staff{i + 1}@demo.local")
        employees.append(pid)
        add_doc("employment_contract", pid, "hr")
        add_doc("vacation_request", pid, "hr", decide=0 if i == 1 else None, due_in=5)
        add_doc("med_checkup", pid, "medical")
    add_doc("trip_memo", employees[0], "hr", "Командировка в Астану: конференция IFLA", decide=1,
            due_in=-1)
    add_doc("trip_order", employees[0], "hr", "Приказ о командировке в Астану")
    add_doc("advance_report", employees[1], "accounting", "Авансовый отчёт: стажировка в Лондоне",
            decide=0, due_in=6)
    add_doc("trip_report", employees[1], "hr", "Отчёт о стажировке в Лондоне", decide=0, due_in=8)

    add_doc("admission_protocol", None, "admissions", "Протокол № 7 заседания приёмной комиссии", decide=1, due_in=2)
    add_doc("curriculum", None, "dean", "РУП «Информационные системы», набор 2025", decide=2, due_in=4)
    add_doc("grade_sheet", None, "dean", "Ведомость: Базы данных, ИС-24-1", decide=0, due_in=1)
    add_doc("grade_sheet", None, "dean", "Ведомость: Алгоритмы, ВТ-23-2")
    add_doc("practice_contract", None, "practice", "Договор о прохождении практики с ТОО «Демо Технолоджи»",
            decide=1, due_in=5)
    add_doc("rector_order", None, "rector", "О начале весеннего семестра")
    add_doc("rector_order", None, "registrar", "О периоде Add/Drop", decide=0, due_in=2)
    add_doc("instruction", None, "rector", "Распоряжение о дежурстве в праздничные дни")
    add_doc("discount_decision", students[0], "accounting", "Скидка 25% за академические успехи", decide=1, due_in=3)
    add_doc("transfer", students[5], "registrar", "Заявление о переводе на другую ОП", decide=1, reject=True)

    # старые квитанции прошлых лет: срок хранения истекает в ближайшие месяцы
    old = con.execute("SELECT id FROM documents WHERE type_code = 'payment_receipt' ORDER BY id LIMIT 3").fetchall()
    for k, (doc_id,) in enumerate(old):
        year = date.today().year - 5
        con.execute("UPDATE documents SET retention_until = ?, title = ?, created_at = ? WHERE id = ?",
                    ((date.today() + timedelta(days=45 + 70 * k)).isoformat(),
                     f"Квитанция об оплате за {year}–{year + 1} учебный год",
                     datetime(year, 9, 1, tzinfo=UTC).isoformat(timespec="seconds"), doc_id))
