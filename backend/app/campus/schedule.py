"""Демо-расписание аудиторий главного корпуса и расчёт «занято / свободно».

Карта — настоящая (оцифрована из PDF, см. scripts/build_campus_map.py), расписание — синтетическое:
детерминированно генерируется из номера аудитории и дня недели, поэтому каждую неделю одно и то же,
как у настоящего расписания. Днём в будни заняты почти все аудитории, утром и вечером — меньше,
в субботу — меньше половины, в воскресенье корпус закрыт.

Сетка занятий: пары по 50 минут, начало каждый час с 08:00 до 20:00; корпус открыт 08:00–21:00.
"""

from __future__ import annotations

import hashlib
import json
import random
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

ALMATY = timezone(timedelta(hours=5))
DATA = Path(__file__).parent / "data" / "floors.json"

OPEN_MIN = 8 * 60
CLOSE_MIN = 21 * 60
LESSON_MIN = 50
FIRST_HOUR, LAST_HOUR = 8, 20
DAY_NAMES = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]

# вероятность занятия в аудитории по часу начала (будни)
WEEKDAY_LOAD = {8: 0.55, 9: 0.8, 10: 0.9, 11: 0.92, 12: 0.88, 13: 0.7, 14: 0.88,
                15: 0.86, 16: 0.78, 17: 0.6, 18: 0.45, 19: 0.3, 20: 0.15}
SATURDAY_FACTOR = 0.45

SUBJECTS = [
    "Calculus I", "Calculus II", "Linear Algebra", "Discrete Mathematics", "Probability and Statistics",
    "Physics I", "Physics II", "Algorithms and Data Structures", "Object-Oriented Programming",
    "Database Systems", "Operating Systems", "Computer Networks", "Web Development",
    "Machine Learning", "Natural Language Processing", "Computer Vision", "Information Security",
    "Software Engineering", "Microeconomics", "Macroeconomics", "Financial Accounting",
    "Corporate Finance", "Marketing", "Business Statistics", "Petroleum Geology",
    "Drilling Engineering", "Reservoir Engineering", "Chemical Thermodynamics", "Organic Chemistry",
    "Academic English", "Kazakh Language", "Russian Language", "History of Kazakhstan",
    "Philosophy", "Sociology", "Political Science", "Physical Education Theory",
]
FACULTIES = ["IT", "SE", "CSS", "BA", "FIN", "PE", "CHE", "GEO", "MATH", "ISE"]
TEACHERS = [
    "Абдрахманова А.", "Байжанов Е.", "Ким Д.", "Сейткали Н.", "Оспанов Р.", "Жумабекова Г.",
    "Смагулов Т.", "Ли В.", "Нургалиева С.", "Ахметов Б.", "Каримова Л.", "Тлеубаев М.",
    "Петрова И.", "Исмаилов Ж.", "Мукашева Д.", "Есенов А.", "Джексенбаев К.", "Wilson J.",
    "Brown K.", "Сарсенова Ж.",
]


def _rng(*parts: object) -> random.Random:
    digest = hashlib.sha256("|".join(map(str, parts)).encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


@lru_cache(maxsize=1)
def campus_map() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def rooms() -> dict[str, dict]:
    return {r["id"]: r for f in campus_map()["floors"] for r in f["rooms"]}


def _lessons_for(room: dict, day: int) -> list[dict]:
    """Занятия аудитории в данный день недели (0 — понедельник)."""
    kind = room["kind"]
    if day == 6 or kind in ("office", "service", "coworking"):
        return []
    rng = _rng(room["id"], day)
    if kind == "hall":
        # зал — под мероприятия: пара событий в неделю
        if day in (2, 4):
            start = 15 * 60 if day == 2 else 12 * 60
            title = "Открытая лекция приглашённого спикера" if day == 2 else "Встреча студенческих клубов"
            return [{"start": _hhmm(start), "end": _hhmm(start + 110), "subject": title,
                     "type": "Мероприятие", "group": "Все желающие", "teacher": "Офис студенческой жизни"}]
        return []

    seats = room.get("seats") or 20
    lessons: list[dict] = []
    hour = FIRST_HOUR
    while hour <= LAST_HOUR:
        p = WEEKDAY_LOAD[hour] * (SATURDAY_FACTOR if day == 5 else 1)
        if rng.random() >= p:
            hour += 1
            continue
        # большие аудитории — лекции, маленькие — практики и лабораторные; часто сдвоенные пары
        length = 2 if rng.random() < 0.55 and hour < LAST_HOUR else 1
        if seats >= 70:
            kind_name = "Лекция"
        else:
            kind_name = rng.choice(["Практика", "Практика", "Лабораторная", "Лекция"])
        faculty = rng.choice(FACULTIES)
        year = rng.choice([22, 23, 24, 25])
        group = (f"{faculty}-{year} поток" if kind_name == "Лекция"
                 else f"{faculty}-{year}{rng.randint(1, 9):02d}")
        subject = rng.choice(SUBJECTS)
        teacher = rng.choice(TEACHERS)
        for h in range(hour, hour + length):
            lessons.append({"start": _hhmm(h * 60), "end": _hhmm(h * 60 + LESSON_MIN),
                            "subject": subject, "type": kind_name, "group": group, "teacher": teacher})
        hour += length
    return lessons


@lru_cache(maxsize=2048)
def day_schedule(room_id: str, day: int) -> tuple[dict, ...]:
    return tuple(_lessons_for(rooms()[room_id], day))


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def now_local() -> datetime:
    return datetime.now(ALMATY).replace(tzinfo=None)


def resolve_moment(day: int | None, time: str | None) -> tuple[int, int, bool]:
    """(день недели, минуты от полуночи, «сейчас ли это»)."""
    now = now_local()
    live = day is None and time is None
    d = now.weekday() if day is None else day
    t = now.hour * 60 + now.minute if time is None else _minutes(time)
    return d, t, live


def is_open(day: int, minute: int) -> bool:
    return day != 6 and OPEN_MIN <= minute < CLOSE_MIN


def room_status(room: dict, day: int, minute: int) -> dict:
    """Состояние аудитории в момент времени: busy / free / open (коворкинг) / service / closed."""
    if not is_open(day, minute):
        return {"state": "closed"}
    if room["kind"] in ("office", "service"):
        return {"state": "service"}
    lessons = day_schedule(room["id"], day)
    current = next((ls for ls in lessons if _minutes(ls["start"]) <= minute < _minutes(ls["end"])), None)
    upcoming = [ls for ls in lessons if _minutes(ls["start"]) > minute]
    if current:
        # до какого времени занята подряд (сдвоенные пары, перемена 10 минут не в счёт)
        busy_until = _minutes(current["end"])
        for ls in lessons:
            if busy_until <= _minutes(ls["start"]) <= busy_until + 10:
                busy_until = _minutes(ls["end"])
        return {"state": "busy", "lesson": current, "busy_until": _hhmm(busy_until),
                "busy_minutes": busy_until - minute}
    free_until = _minutes(upcoming[0]["start"]) if upcoming else CLOSE_MIN
    state = "open" if room["kind"] == "coworking" else "free"
    return {"state": state, "free_until": _hhmm(free_until), "free_minutes": free_until - minute,
            "next": upcoming[0] if upcoming else None}


def snapshot(day: int | None = None, time: str | None = None) -> dict:
    d, t, live = resolve_moment(day, time)
    statuses = {rid: room_status(r, d, t) for rid, r in rooms().items()}
    floors = []
    for f in campus_map()["floors"]:
        ids = [r["id"] for r in f["rooms"] if r["kind"] in ("classroom", "hall")]
        free = sum(statuses[i]["state"] == "free" for i in ids)
        busy = sum(statuses[i]["state"] == "busy" for i in ids)
        floors.append({"floor": f["floor"], "total": len(ids), "free": free, "busy": busy})
    total = sum(f["total"] for f in floors)
    busy = sum(f["busy"] for f in floors)
    return {
        "at": {"day": d, "day_name": DAY_NAMES[d], "time": _hhmm(t), "live": live},
        "open": is_open(d, t),
        "hours": {"open": _hhmm(OPEN_MIN), "close": _hhmm(CLOSE_MIN)},
        "totals": {"total": total, "busy": busy, "free": sum(f["free"] for f in floors),
                   "load": round(busy / total, 3) if total else 0},
        "floors": floors,
        "rooms": statuses,
    }


def suggest(day: int | None = None, time: str | None = None, *, min_minutes: int = 30,
            floor: int | None = None, limit: int = 15) -> dict:
    """Где посидеть: свободные аудитории, где можно провести не меньше min_minutes."""
    d, t, live = resolve_moment(day, time)
    out = []
    for rid, room in rooms().items():
        if floor is not None and room["floor"] != floor:
            continue
        st = room_status(room, d, t)
        if st["state"] not in ("free", "open") or st["free_minutes"] < min_minutes:
            continue
        out.append({"id": rid, "name": room["name"], "number": room["number"], "floor": room["floor"],
                    "kind": room["kind"], "seats": room["seats"], **st})
    # коворкинги — всегда первыми, дальше — где дольше никто не помешает, ниже этаж — ближе
    out.sort(key=lambda r: (r["kind"] != "coworking", -r["free_minutes"], r["floor"], r["id"]))
    return {"at": {"day": d, "day_name": DAY_NAMES[d], "time": _hhmm(t), "live": live},
            "open": is_open(d, t), "count": len(out), "rooms": out[:limit]}
