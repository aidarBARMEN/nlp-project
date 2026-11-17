"""API цифрового двойника парковки: /api/parking/*."""

from __future__ import annotations

import hmac
import time
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from ..config import get_settings
from .twin import get_twin

router = APIRouter(prefix="/api/parking", tags=["Умная парковка"])


class Control(BaseModel):
    speed: float | None = Field(default=None, ge=1, le=600)
    paused: bool | None = None
    scenario: Literal["weekday", "exam", "weekend"] | None = None
    mode: Literal["simulation", "live"] | None = None
    jump_to: str | None = Field(default=None, pattern=r"^\d{1,2}:\d{2}$")


class SensorEvent(BaseModel):
    stall_id: str = Field(max_length=10)
    occupied: bool
    plate: str | None = Field(default=None, max_length=20)


_google_session: dict = {}


def _google_tiles(key: str) -> dict | None:
    """Сессия официального Google Map Tiles API (спутник). Сессия живёт ~2 недели — кэшируем."""
    if _google_session.get("expiry", 0) > time.time() + 3600:
        return _google_session["value"]
    try:
        r = httpx.post(f"https://tile.googleapis.com/v1/createSession?key={key}", timeout=15,
                       json={"mapType": "satellite", "language": "ru-RU", "region": "KZ"})
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPError:
        return None
    value = {
        "id": "google",
        "name": "Google — спутник",
        "url": f"https://tile.googleapis.com/v1/2dtiles/{{z}}/{{x}}/{{y}}?session={data['session']}&key={key}",
        "viewport_url": f"https://tile.googleapis.com/tile/v1/viewport?session={data['session']}&key={key}",
        "attribution": "© Google",
        "max_zoom": 22,
    }
    _google_session.update(value=value, expiry=int(data.get("expiry", time.time() + 86400)))
    return value


@router.get("/basemaps")
def basemaps():
    """Подложки для спутникового вида: Google при наличии ключа, иначе бесплатные Esri и OSM."""
    out = []
    key = get_settings().google_maps_api_key.strip()
    if key and (google := _google_tiles(key)):
        out.append(google)
    out += [
        {"id": "esri", "name": "Esri — спутник",
         "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
         "attribution": "Снимок © Esri, Maxar, Earthstar Geographics", "max_zoom": 19},
        {"id": "osm", "name": "OpenStreetMap — схема",
         "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
         "attribution": "© участники OpenStreetMap", "max_zoom": 19},
    ]
    return {"basemaps": out, "google_configured": bool(key)}


@router.get("/layout")
def layout():
    return get_twin().layout


@router.get("/state")
def state():
    return get_twin().snapshot()


@router.post("/control")
def control(body: Control):
    try:
        get_twin().control(**body.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return get_twin().snapshot()


@router.get("/recommend")
def recommend(need: Literal["regular", "disabled", "ev", "staff"] = "regular"):
    result = get_twin().recommend(need)
    if not result:
        raise HTTPException(404, "Свободных мест нужного типа нет")
    return result


@router.post("/events")
def sensor_event(body: SensorEvent, x_api_key: Annotated[str | None, Header()] = None):
    """Приём событий от датчиков мест и камер распознавания номеров (переводит двойник в режим live)."""
    token = get_settings().parking_api_token
    if not token:
        raise HTTPException(403, "Приём событий выключен: задайте PARKING_API_TOKEN в .env")
    if not hmac.compare_digest(x_api_key or "", token):
        raise HTTPException(401, "Неверный X-API-Key")
    try:
        get_twin().sensor_event(body.stall_id, body.occupied, body.plate)
    except KeyError as e:
        raise HTTPException(404, f"Нет места {body.stall_id}") from e
    return {"ok": True}
