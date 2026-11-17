"""Цифровой двойник парковки: план из OSM, симуляция, подбор места, события датчиков."""

import math

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.parking import router as parking_router
from backend.app.parking.twin import ParkingTwin


@pytest.fixture
def twin():
    return ParkingTwin(seed=1)


def _inside(pt, poly):
    x, y = pt
    res = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1], strict=True):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            res = not res
    return res


def test_layout_stalls_are_inside_their_zones_and_outside_building(twin):
    layout = twin.layout
    zones = {z["id"]: z["polygon"] for z in layout["zones"]}
    building = layout["building"]
    assert len(layout["stalls"]) > 100
    for s in layout["stalls"]:
        assert _inside(s["center"], zones[s["zone"]]), s["id"]
        in_building = _inside(s["center"], building["outer"]) and not any(
            _inside(s["center"], h) for h in building["inner"]
        )
        assert not in_building, s["id"]
    assert len({s["id"] for s in layout["stalls"]}) == len(layout["stalls"])


def test_occupancy_follows_day_profile(twin):
    twin.control(scenario="exam", jump_to="03:00")  # сценарий не зависит от дня недели
    assert twin.snapshot()["totals"]["rate"] < 0.3
    twin.control(jump_to="10:30")
    assert twin.snapshot()["totals"]["rate"] > 0.8


def test_recommendation_is_free_and_close(twin):
    twin.control(jump_to="20:00")
    rec = twin.recommend()
    state = {s["id"]: s for s in twin.snapshot()["stalls"]}
    assert not state[rec["stall"]]["occupied"]
    assert rec["walk_m"] < 80
    # маршрут заканчивается в центре места
    center = next(s["center"] for s in twin.layout["stalls"] if s["id"] == rec["stall"])
    assert math.dist(rec["drive"][-1], center) < 0.01


def test_plates_are_masked(twin):
    occupied = [s for s in twin.snapshot()["stalls"] if s["occupied"]]
    assert occupied
    assert all(
        s["plate"].startswith("•••") and not any(c.isdigit() for c in s["plate"][:6])
        for s in occupied
    )


def test_sensor_events_require_token_and_switch_to_live(twin, monkeypatch):
    monkeypatch.setattr(parking_router, "get_twin", lambda: twin)
    app = FastAPI()
    app.include_router(parking_router.router)
    client = TestClient(app)
    stall = twin.layout["stalls"][0]["id"]

    from backend.app.config import get_settings

    monkeypatch.setattr(get_settings(), "parking_api_token", "")
    assert (
        client.post("/api/parking/events", json={"stall_id": stall, "occupied": True}).status_code
        == 403
    )
    monkeypatch.setattr(get_settings(), "parking_api_token", "secret")
    bad = client.post(
        "/api/parking/events",
        json={"stall_id": stall, "occupied": True},
        headers={"X-API-Key": "nope"},
    )
    assert bad.status_code == 401
    for occupied in (False, True):
        r = client.post(
            "/api/parking/events",
            json={"stall_id": stall, "occupied": occupied},
            headers={"X-API-Key": "secret"},
        )
        assert r.status_code == 200
    state = client.get("/api/parking/state").json()
    assert state["mode"] == "live"
    assert next(s for s in state["stalls"] if s["id"] == stall)["occupied"]
    assert (
        client.post(
            "/api/parking/events",
            json={"stall_id": "Z-999", "occupied": True},
            headers={"X-API-Key": "secret"},
        ).status_code
        == 404
    )
