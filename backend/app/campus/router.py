"""API карты корпуса и занятости аудиторий: /api/campus/*."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from .schedule import (
    DAY_NAMES,
    campus_map,
    day_schedule,
    resolve_moment,
    room_status,
    rooms,
    snapshot,
    suggest,
)

router = APIRouter(prefix="/api/campus", tags=["Карта корпуса"])

Day = Annotated[int | None, Query(ge=0, le=6, description="День недели, 0 — понедельник; по умолчанию сегодня")]
Time = Annotated[str | None, Query(pattern=r"^([01]\d|2[0-3]):[0-5]\d$", description="ЧЧ:ММ; по умолчанию сейчас")]


@router.get("/map")
def floor_map():
    """Оцифрованные планы этажей: контуры аудиторий в координатах подложки 1500×1500."""
    return campus_map()


@router.get("/status")
def status(day: Day = None, time: Time = None):
    """Состояние всех аудиторий в момент времени (по умолчанию — сейчас, Алматы)."""
    return snapshot(day, time)


@router.get("/free")
def free(day: Day = None, time: Time = None,
         min_minutes: Annotated[int, Query(ge=0, le=13 * 60)] = 30,
         floor: Annotated[int | None, Query(ge=1, le=5)] = None,
         limit: Annotated[int, Query(ge=1, le=100)] = 15):
    """Где посидеть: свободные аудитории, отсортированные по тому, сколько они ещё будут свободны."""
    return suggest(day, time, min_minutes=min_minutes, floor=floor, limit=limit)


@router.get("/rooms/{room_id}")
def room(room_id: str, day: Day = None, time: Time = None):
    """Аудитория: расписание на день и текущее состояние."""
    r = rooms().get(room_id)
    if r is None:
        raise HTTPException(404, f"Нет аудитории {room_id}")
    d, t, _ = resolve_moment(day, time)
    meta = {k: v for k, v in r.items() if k not in ("polygon", "label")}
    return {**meta, "day": d, "day_name": DAY_NAMES[d], "status": room_status(r, d, t),
            "lessons": list(day_schedule(room_id, d))}
