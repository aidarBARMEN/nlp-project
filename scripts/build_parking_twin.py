"""Строит план цифрового двойника парковки КБТУ из данных OpenStreetMap.

    python scripts/build_parking_twin.py            # из сохранённой выгрузки OSM
    python scripts/build_parking_twin.py --refresh  # заново скачать из Overpass API

Источник: © участники OpenStreetMap, лицензия ODbL (https://www.openstreetmap.org/copyright).
Контуры здания, парковок, проездов и ограждений — из OSM. Места раскладываются алгоритмически
по контурам и проездам (шаг 2,5 м); фактическую разметку нужно сверить на месте.

Выход: backend/app/parking/data/layout.json — координаты в метрах, x — на восток, y — на север,
начало координат — центр здания КБТУ.
"""

from __future__ import annotations

import argparse
import json
import math
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "backend" / "app" / "parking" / "data"
SOURCE = DATA / "osm_source.json"
OUT = DATA / "layout.json"

LAT0, LON0 = 43.2560, 76.9431
KX = math.cos(math.radians(LAT0)) * 111320
KY = 110574

KBTU_RELATION = 3206854
ZONES = {
    # id: (название, OSM way парковки, OSM way проезда или None для уличной парковки)
    # вдоль Казыбек би проезжей части нет: линия, которую OSM подписывает «Казыбек Би» (service),
    # — проезд внутри парковки; машины стоят перпендикулярно по обе стороны от него
    "A": ("Казыбек би", 1458055616, 552797224),
    "B": ("Западное крыло", 1458055628, 1458055635),
    "C": ("Восточное крыло", 1458055631, 1458055636),
}
SERVICE_ROAD = 1458055622
AISLE_IDS = {v[2] for v in ZONES.values() if v[2]}
_IDS = ",".join(str(i) for v in ZONES.values() for i in v[1:] if i)
QUERY = f"""[out:json][timeout:60];
(
  relation({KBTU_RELATION});
  way(id:{_IDS},
      {SERVICE_ROAD},552797224,663356907,1487751962,1509851943);
  way["barrier"](43.2550,76.9412,43.2570,76.9450);
  way["highway"~"footway|pedestrian|steps|service|residential|tertiary|secondary"](43.2545,76.9405,43.2575,76.9460);
  way["building"](43.2545,76.9405,43.2575,76.9460);
  node["barrier"](43.2550,76.9412,43.2570,76.9450);
  node["entrance"](43.2550,76.9412,43.2570,76.9450);
);
out geom;"""

STALL_W, STALL_L = 2.5, 5.0  # перпендикулярное место
PARALLEL_L, PARALLEL_W = 6.0, 2.3  # место вдоль бордюра
AISLE_HALF = 3.0  # половина ширины проезда


def fetch() -> dict:
    data = urllib.parse.urlencode({"data": QUERY}).encode()
    for wait in (0, 10, 30, 60):
        time.sleep(wait)
        req = urllib.request.Request(
            "https://overpass-api.de/api/interpreter",
            data=data,
            headers={"User-Agent": "kbtu-smart-assistant/1.0 (student project)"},
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                body = r.read()
            if body.lstrip().startswith(b"{"):
                return json.loads(body)
        except OSError as e:
            print("Overpass:", e)
    raise SystemExit("Overpass API недоступен — используйте сохранённую выгрузку без --refresh")


def xy(p: dict) -> tuple[float, float]:
    return ((p["lon"] - LON0) * KX, (p["lat"] - LAT0) * KY)


def r1(pts):
    return [[round(x, 1), round(y, 1)] for x, y in pts]


def inside(pt, poly) -> bool:
    x, y = pt
    res = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1], strict=True):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            res = not res
    return res


def in_building(pt, building) -> bool:
    return inside(pt, building["outer"]) and not any(inside(pt, h) for h in building["inner"])


def rect(cx, cy, ux, uy, length, width):
    """Прямоугольник с центром (cx, cy): length вдоль единичного вектора u, width — поперёк."""
    vx, vy = -uy, ux
    hl, hw = length / 2, width / 2
    return [
        (cx + ux * hl + vx * hw, cy + uy * hl + vy * hw),
        (cx - ux * hl + vx * hw, cy - uy * hl + vy * hw),
        (cx - ux * hl - vx * hw, cy - uy * hl - vy * hw),
        (cx + ux * hl - vx * hw, cy + uy * hl - vy * hw),
    ]


def overlaps(a, b) -> bool:
    """Пересечение выпуклых четырёхугольников (теорема о разделяющей оси)."""
    for poly in (a, b):
        for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1], strict=True):
            nx, ny = y1 - y2, x2 - x1
            pa = [nx * x + ny * y for x, y in a]
            pb = [nx * x + ny * y for x, y in b]
            if max(pa) <= min(pb) + 0.05 or max(pb) <= min(pa) + 0.05:
                return False
    return True


def walk(line, step):
    """Точки вдоль ломаной через каждые step метров: (x, y, ux, uy)."""
    out, carry = [], step / 2
    for (x1, y1), (x2, y2) in zip(line, line[1:], strict=False):
        seg = math.hypot(x2 - x1, y2 - y1)
        if seg < 1e-6:
            continue
        ux, uy = (x2 - x1) / seg, (y2 - y1) / seg
        t = carry
        while t <= seg:
            out.append((x1 + ux * t, y1 + uy * t, ux, uy))
            t += step
        carry = t - seg
    return out


def stalls_along_aisle(aisle, lot, building, placed):
    res = []
    for x, y, ux, uy in walk(aisle, STALL_W):
        for side in (1, -1):
            vx, vy = -uy * side, ux * side
            off = AISLE_HALF + STALL_L / 2
            cx, cy = x + vx * off, y + vy * off
            poly = rect(cx, cy, vx, vy, STALL_L, STALL_W)  # длинная сторона — от проезда
            if (
                all(inside(p, lot) for p in poly)
                and not any(in_building(p, building) for p in poly)
                and not any(overlaps(poly, q) for q in placed)
            ):
                placed.append(poly)
                res.append((poly, (cx, cy), math.degrees(math.atan2(vy, vx))))
    return res


def stalls_along_curbs(lot, building, placed):
    """Уличная парковка: параллельные места вдоль длинных сторон контура (бордюров)."""
    res = []
    edges = list(zip(lot, lot[1:] + lot[:1], strict=True))
    longest = sorted(edges, key=lambda e: -math.hypot(e[1][0] - e[0][0], e[1][1] - e[0][1]))[:2]
    for (x1, y1), (x2, y2) in longest:
        seg = math.hypot(x2 - x1, y2 - y1)
        ux, uy = (x2 - x1) / seg, (y2 - y1) / seg
        # нормаль внутрь контура
        nx, ny = -uy, ux
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        if not inside((mx + nx * 2, my + ny * 2), lot):
            nx, ny = -nx, -ny
        for x, y, _ux, _uy in walk([(x1, y1), (x2, y2)], PARALLEL_L):
            cx, cy = x + nx * (PARALLEL_W / 2 + 0.3), y + ny * (PARALLEL_W / 2 + 0.3)
            poly = rect(cx, cy, ux, uy, PARALLEL_L - 0.4, PARALLEL_W)
            if all(inside(p, lot) for p in poly) and not any(overlaps(poly, q) for q in placed):
                placed.append(poly)
                res.append((poly, (cx, cy), math.degrees(math.atan2(uy, ux))))
    return res


def build(osm: dict) -> dict:
    ways = {e["id"]: e for e in osm["elements"] if e["type"] == "way"}
    rel = next(e for e in osm["elements"] if e["type"] == "relation" and e["id"] == KBTU_RELATION)
    building = {
        "outer": [xy(p) for m in rel["members"] if m["role"] == "outer" for p in m["geometry"]][
            :-1
        ],
        "inner": [
            [xy(p) for p in m["geometry"]][:-1] for m in rel["members"] if m["role"] == "inner"
        ],
    }

    placed: list = []
    zones, stalls, aisles = [], [], []
    for zid, (name, lot_id, aisle_id) in ZONES.items():
        lot = [xy(p) for p in ways[lot_id]["geometry"]][:-1]
        if aisle_id:
            aisle = [xy(p) for p in ways[aisle_id]["geometry"]]
            aisles.append({"zone": zid, "line": r1(aisle)})
            found = stalls_along_aisle(aisle, lot, building, placed)
            if zid == "A":  # въезд с проспекта Абылай хана — западный конец
                entry = aisle[0] if aisle[0][0] < aisle[-1][0] else aisle[-1]
            else:  # дворовые зоны — со служебного проезда за корпусом, с севера
                entry = aisle[0] if aisle[0][1] > aisle[-1][1] else aisle[-1]
            # на изгибах проезда места ложатся под случайными углами — оставляем только
            # места, развёрнутые как большинство мест зоны
            angles = sorted(a % 180 for _, _, a in found)
            main = angles[len(angles) // 2] if angles else 0
            kept = [
                s for s in found if min(abs(s[2] % 180 - main), 180 - abs(s[2] % 180 - main)) <= 20
            ]
            for s in found:
                if s not in kept:
                    placed.remove(s[0])
            found = kept
        else:
            found = stalls_along_curbs(lot, building, placed)
            entry = None
        zones.append(
            {
                "id": zid,
                "name": name,
                "osm_way": lot_id,
                "polygon": r1(lot),
                "entry": r1([entry])[0] if entry else None,
                "kind": "street" if not aisle_id else "lot",
                # камеры распознавания номеров стоят на въездах во дворовые зоны;
                # открытая зона вдоль Казыбек би — датчики в каждом месте
                "camera": zid != "A",
            }
        )
        # сортировка: от въезда вглубь, чтобы номера мест шли по порядку
        ref = entry or found[0][1] if found else (0, 0)
        found.sort(
            key=lambda s: math.hypot(s[1][0] - ref[0], s[1][1] - ref[1]) if aisle_id else s[1][0]
        )
        for n, (poly, (cx, cy), angle) in enumerate(found, start=1):
            stalls.append(
                {
                    "id": f"{zid}-{n:03d}",
                    "zone": zid,
                    "polygon": r1(poly),
                    "center": [round(cx, 1), round(cy, 1)],
                    "angle": round(angle, 1),
                    "type": "regular",
                }
            )

    # специальные места: ближайшие к входам в здание — для людей с инвалидностью,
    # по паре мест у въезда во дворовые зоны — зарядка электромобилей, часть зоны B — сотрудники
    entrances = [
        xy(e) for e in osm["elements"] if e["type"] == "node" and "entrance" in e.get("tags", {})
    ]

    def near_entrance(s):
        return min(math.hypot(s["center"][0] - ex, s["center"][1] - ey) for ex, ey in entrances)

    for zid in ("B", "C"):
        zs = [s for s in stalls if s["zone"] == zid]
        for s in sorted(zs, key=near_entrance)[:2]:
            s["type"] = "disabled"
        for s in [s for s in zs if s["type"] == "regular"][:2]:
            s["type"] = "ev"
    for s in [s for s in stalls if s["zone"] == "B" and s["type"] == "regular"][-10:]:
        s["type"] = "staff"

    roads, footways, buildings, fences = [], [], [], []
    for e in osm["elements"]:
        if e["type"] != "way":
            continue
        t = e.get("tags", {})
        line = r1([xy(p) for p in e["geometry"]])
        if (
            t.get("highway") in ("residential", "tertiary", "secondary", "service")
            and t.get("service") != "parking_aisle"
            and e["id"] not in AISLE_IDS
        ):
            roads.append(
                {
                    "name": t.get("name:ru") or t.get("name"),
                    "kind": t["highway"],
                    "line": line,
                    "lanes": int(t.get("lanes", "2")) if str(t.get("lanes", "2")).isdigit() else 2,
                }
            )
        elif t.get("highway") in ("footway", "pedestrian", "steps"):
            footways.append(line)
        elif "building" in t and e["id"] != KBTU_RELATION:
            buildings.append(
                {"polygon": line[:-1], "name": t.get("name"), "levels": t.get("building:levels")}
            )
        elif "barrier" in t:
            fences.append(line)
    points = []
    for e in osm["elements"]:
        if e["type"] == "node":
            t = e["tags"]
            kind = t.get("barrier") or (
                "entrance_main" if t.get("entrance") == "main" else "entrance"
            )
            points.append({"kind": kind, "at": r1([xy(e)])[0]})

    return {
        "meta": {
            "title": "Парковка КБТУ, ул. Казыбек би (Алматы)",
            "origin": {"lat": LAT0, "lon": LON0},
            "units": "m",
            "source": "© участники OpenStreetMap, ODbL",
            "osm": {
                "building_relation": KBTU_RELATION,
                "parking_ways": [v[1] for v in ZONES.values()],
            },
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "note": "Контуры — OpenStreetMap; места разложены алгоритмически "
            "по контурам и проездам "
            "с шагом 2,5 м (уличные — 6 м). Сверить с фактической разметкой.",
        },
        "building": {
            "name": "КБТУ, Толе би 59",
            "outer": r1(building["outer"]),
            "inner": [r1(h) for h in building["inner"]],
        },
        "zones": zones,
        "aisles": aisles,
        "stalls": stalls,
        "roads": roads,
        "footways": footways,
        "buildings": buildings,
        "fences": fences,
        "points": points,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="скачать свежие данные из OpenStreetMap")
    args = ap.parse_args()
    if args.refresh or not SOURCE.exists():
        SOURCE.write_text(json.dumps(fetch(), ensure_ascii=False), encoding="utf-8")
    layout = build(json.loads(SOURCE.read_text(encoding="utf-8")))
    OUT.write_text(json.dumps(layout, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    counts = {z["id"]: sum(s["zone"] == z["id"] for s in layout["stalls"]) for z in layout["zones"]}
    print(f"{OUT}: мест {len(layout['stalls'])} {counts}")


if __name__ == "__main__":
    main()
