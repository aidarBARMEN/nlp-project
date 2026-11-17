"""Карта корпуса: оцифрованные этажи, демо-расписание, свободные аудитории."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.campus import schedule
from backend.app.campus.router import router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _inside(pt, poly):
    x, y = pt
    res = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1], strict=True):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            res = not res
    return res


def test_map_has_all_floors_with_unique_rooms():
    data = schedule.campus_map()
    assert [f["floor"] for f in data["floors"]] == [1, 2, 3, 4, 5]
    ids = [r["id"] for f in data["floors"] for r in f["rooms"]]
    assert len(ids) == len(set(ids)) > 200
    for f in data["floors"]:
        for r in f["rooms"]:
            assert r["floor"] == f["floor"]
            if r["number"]:
                assert r["number"][0] == str(f["floor"]), r["id"]
            # подпись лежит внутри своего контура — контур выделен правильно
            assert _inside(r["label"], r["polygon"]), r["id"]


def test_schedule_is_deterministic_and_on_the_grid():
    a = list(schedule.day_schedule("303", 1))
    assert a == schedule._lessons_for(schedule.rooms()["303"], 1)
    assert a
    for ls in a:
        assert ls["start"].endswith(":00") and ls["end"].endswith(":50")


def test_midday_weekday_is_mostly_busy_and_sunday_closed():
    noon = schedule.snapshot(day=1, time="11:20")
    assert noon["open"]
    assert noon["totals"]["load"] > 0.75
    sunday = schedule.snapshot(day=6, time="12:00")
    assert not sunday["open"]
    assert all(s["state"] == "closed" for s in sunday["rooms"].values())
    evening = schedule.snapshot(day=1, time="19:20")
    assert evening["totals"]["load"] < noon["totals"]["load"]


def test_free_room_window_is_consistent_with_schedule():
    snap = schedule.snapshot(day=2, time="10:15")
    for rid, st in snap["rooms"].items():
        lessons = schedule.day_schedule(rid, 2)
        if st["state"] == "free":
            nxt = next((ls for ls in lessons if ls["start"] > "10:15"), None)
            assert st["free_until"] == (nxt["start"] if nxt else "21:00")
        if st["state"] == "busy":
            assert st["lesson"]["start"] <= "10:15" < st["lesson"]["end"]


def test_free_endpoint_respects_min_minutes_and_puts_coworkings_first():
    params = {"day": 0, "time": "12:10", "min_minutes": 40, "limit": 100}
    res = _client().get("/api/campus/free", params=params)
    assert res.status_code == 200
    rooms = res.json()["rooms"]
    assert rooms and rooms[0]["kind"] == "coworking"
    assert all(r["free_minutes"] >= 40 for r in rooms)
    rest = [r["free_minutes"] for r in rooms if r["kind"] != "coworking"]
    assert rest == sorted(rest, reverse=True)


def test_room_endpoint_and_validation():
    c = _client()
    res = c.get("/api/campus/rooms/159", params={"day": 3, "time": "09:30"})
    assert res.status_code == 200
    body = res.json()
    assert body["floor"] == 1 and body["day_name"] == "Четверг"
    assert "polygon" not in body
    assert c.get("/api/campus/rooms/999").status_code == 404
    assert c.get("/api/campus/status", params={"time": "25:00"}).status_code == 422
