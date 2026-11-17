"""Оцифровка поэтажной карты главного корпуса КБТУ (PDF → контуры аудиторий).

    python scripts/build_campus_map.py "Карта КБТУ по этажам.pdf"

Нужны PyMuPDF, opencv-python и numpy (только для сборки, рантайму не нужны).

Как работает:
  1. Из каждой страницы PDF достаётся растровый план этажа и приводится к 1500×1500.
  2. Номера аудиторий и точки подписей переписаны с карты вручную (таблица LABELS ниже,
     координаты — в пикселях рендера 1654×1654, сверены с OCR Tesseract: медианный сдвиг < 1 px).
  3. Маска стен: красные стены + тёмные линии; текст (мелкие изолированные компоненты) убирается.
  4. Из точки подписи делается заливка (flood fill). Если заливка «утекла» через дверной проём
     в коридор, стены утолщаются (3, 5, 7… px) и попытка повторяется.
  5. Если две подписи попали в одно помещение без стены между ними (159/158, 259/257),
     помещение делится между ними по ближайшей подписи.

Выход:
  backend/app/campus/data/floors.json — контуры аудиторий в координатах 1500×1500;
  frontend/public/campus/floor-N.jpg  — подложки этажей.

Расхождения с оригиналом карты (на ней опечатки и повторы номеров), исправлены так:
  3 этаж: «69» → 369, «3496» → 349б, повторные 336/334 у Толе би → 356/354;
  4 этаж: повторные 459 (центр) → 429, 464 (узкая) → 467, 461 (у Толе би) → 469.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import cv2
import fitz
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT_JSON = ROOT / "backend" / "app" / "campus" / "data" / "floors.json"
OUT_IMG = ROOT / "frontend" / "public" / "campus"
SIZE = 1500
SRC_SCALE = SIZE / 1654

# «номер x y» через «|»; координаты точки подписи в рендере 1654 px
LABELS = {
    1: "183 325 262|184 365 240|182 415 243|180 415 285|181 323 324|179 325 385|177 325 461|172 414 461|175 325 494|170 414 520|173 325 534|171 323 575|168 414 575|169 325 613|166 414 613|164 326 684|161 316 792|160 410 832|159 322 1120|158 409 1112|157 370 1239|156 515 1300|151 655 1221|149 710 1219|152 658 1300|153 709 1300|154 772 1117|155 891 1117|148 947 1220|147 944 1309|146 1002 1309|143 1144 1302|142 1214 1246|140 1298 1246|138 1250 1144|136 1333 1150|135 1248 1081|134 1249 1039|133 1332 1041|132 1235 868|131 1248 831|127 1334 768|120 1335 703|118 1332 659|122 1214 702|124 1170 665|125 1118 679|117 1239 612|116 1332 614|114 1332 578|112 1334 537|111 1332 496|110 1242 492|106 1335 413|104 1335 323|103 1335 280|102 1335 240|100 1245 267|Co-working #1 828 693",
    2: "284 314 287|283 406 287|280 314 371|279 313 416|278 406 470|275 406 504|274 406 544|273 406 587|272 406 623|271 311 591|270 313 685|268 469 715|265 313 765|264 314 805|263 309 846|262 399 846|260 314 891|259 400 1068|258 313 1096|256 313 1135|255 313 1181|257 400 1151|254 416 1272|252 510 1326|251 672 1325|249 972 1325|248 972 1240|245 1150 1326|243 1242 1271|242 1302 1271|241 1347 1271|238 1255 1185|237 1255 1143|235 1255 1102|233 1255 1058|232 1343 890|231 1248 844|230 1246 886|227 1343 800|220 1344 707|222 1214 675|218 1342 562|217 1248 596|211 1246 485|208 1345 418|207 1344 361|204 1251 256|202 1344 274|Press Center Abay 831 505|Co-working #2 762 640|Independence Hall 831 973",
    3: "389 386 244|388 287 302|387 386 313|386 386 356|385 287 402|383 386 492|382 287 535|381 384 541|379 287 698|378 516 680|372 287 815|371 377 864|370 391 908|369 281 909|367 287 1035|365 379 1213|364 287 1225|362 302 1321|361 406 1322|359 498 1379|358 593 1287|357 665 1288|355 708 1287|356 657 1379|354 714 1379|351 840 1379|349 1005 1379|349б 778 1177|349а 906 1177|348 972 1287|347 1031 1287|345 1109 1287|344 1191 1379|343 1337 1323|340 1300 1208|338 1300 1113|336 1397 1168|335 1397 1029|334 1397 956|333 1397 913|331 1297 865|321 1394 713|325 1131 680|324 1236 680|323 1302 680|319 1295 625|317 1395 625|318 1295 588|316 1395 587|315 1295 543|314 1395 540|313 1295 498|312 1395 495|311 1293 453|310 1395 452|309 1397 352|303 1298 263|300 1298 217",
    4: "446 311 347|444 387 311|447 310 475|448 310 512|450 310 591|442 406 582|451 307 715|438 459 682|436 591 679|429 775 673|428 831 516|432 775 576|433 775 623|427 887 583|426 887 626|425 887 674|424 838 760|422 1022 683|421 1072 681|420 1129 681|419 1174 681|405 1352 694|404 1330 567|403 1349 454|402 1349 416|401 1347 381|400 1302 267|409 1260 851|411 1341 936|413 1343 1004|414 1330 1124|416 1327 1263|415 1222 1235|417 1169 1234|418 1149 1342|473 1068 1292|476 1020 1245|474 989 1245|471 1002 1317|472 952 1340|464 828 1302|465 636 1245|467 665 1245|463 650 1326|466 585 1292|469 416 1282|461 322 1135|462 397 1196|460 398 1075|459 310 1023|458 310 981|457 310 937|456 310 892|455 310 774|454 397 849",
    5: "522 486 1228|520 588 1239|519 634 1241|516 665 1241|515 695 1241|514 733 1246|513 823 1228|509 952 1246|507 989 1238|505 1021 1238|503 1068 1239|521 504 1329|518 651 1329|517 706 1329|512 764 1329|511 826 1329|510 888 1329|508 952 1329|506 1004 1329|504 1081 1329|502 1163 1329",
}

SPECIAL = {
    # название: (тип, предел площади заливки в px)
    "Co-working #1": ("coworking", 60000),
    "Co-working #2": ("coworking", 30000),
    "Independence Hall": ("hall", 90000),
    "Press Center Abay": ("service", 30000),
}
SPECIAL_NAMES = {
    "Co-working #1": "Коворкинг №1",
    "Co-working #2": "Коворкинг №2",
    "Independence Hall": "Зал Независимости",
    "Press Center Abay": "Пресс-центр «Абай»",
}
MAX_AREA = 42000
SEATS_PER_PX = 0.0075  # грубая оценка вместимости по площади на плане
OFFICE_PX = 1100  # меньше — узкие служебные помещения, занятий там нет


def parse_labels() -> dict[int, list[tuple[str, int, int]]]:
    out = {}
    for floor, s in LABELS.items():
        rows = []
        for item in s.split("|"):
            *name, x, y = item.split()
            rows.append((" ".join(name), round(float(x) * SRC_SCALE), round(float(y) * SRC_SCALE)))
        out[floor] = rows
    return out


def floor_images(pdf: Path) -> list[np.ndarray]:
    doc = fitz.open(pdf)
    images = []
    for page in doc:
        raw = doc.extract_image(page.get_images()[0][0])["image"]
        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if img.shape[:2] != (SIZE, SIZE):
            img = cv2.resize(img, (SIZE, SIZE), interpolation=cv2.INTER_CUBIC)
        images.append(img)
    return images


def wall_mask(img: np.ndarray) -> np.ndarray:
    b, g, r = (c.astype(int) for c in cv2.split(img))
    wall = ((np.minimum(np.minimum(r, g), b) < 215) | ((r - g) > 60)).astype(np.uint8)
    _, lab, st, _ = cv2.connectedComponentsWithStats(wall, 8)
    small = (st[:, 2] < 26) & (st[:, 3] < 26)
    small[0] = False
    wall[small[lab]] = 0
    return wall


def flood(wall: np.ndarray, x: int, y: int, max_area: int) -> np.ndarray | None:
    h, w = wall.shape
    for k in (1, 3, 5, 7, 9, 13):
        wm = cv2.dilate(wall, np.ones((k, k), np.uint8)) if k > 1 else wall
        seed = None
        for rr in range(14):
            ys, xs = np.where(wm[max(0, y - rr):y + rr + 1, max(0, x - rr):x + rr + 1] == 0)
            if len(xs):
                seed = (int(xs[0] + max(0, x - rr)), int(ys[0] + max(0, y - rr)))
                break
        if seed is None:
            continue
        ff = ((1 - wm) * 255).astype(np.uint8)
        cv2.floodFill(ff, np.zeros((h + 2, w + 2), np.uint8), seed, 128)
        reg = (ff == 128).astype(np.uint8)
        if 250 < reg.sum() < max_area:
            return cv2.dilate(reg, np.ones((k + 2, k + 2), np.uint8))
    return None


def to_polygon(reg: np.ndarray) -> list[list[int]]:
    cs, _ = cv2.findContours(reg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    c = max(cs, key=cv2.contourArea)
    return cv2.approxPolyDP(c, 2.5, True)[:, 0, :].tolist()


def red_bbox(img: np.ndarray) -> tuple[int, int, int, int]:
    """Рамка красных стен этажа (подписи улиц чёрные и в неё не попадают)."""
    b, g, r = (c.astype(int) for c in cv2.split(img))
    ys, xs = np.where((r - g) > 60)
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def build(pdf: Path) -> dict:
    labels = parse_labels()
    images = floor_images(pdf)
    OUT_IMG.mkdir(parents=True, exist_ok=True)
    floors = []
    for floor, img in enumerate(images, start=1):
        wall = wall_mask(img)
        regions: list[tuple[str, int, int, np.ndarray | None]] = []
        for name, x, y in labels[floor]:
            max_area = SPECIAL.get(name, (None, MAX_AREA))[1]
            regions.append((name, x, y, flood(wall, x, y, max_area)))

        # помещения без стены между подписями — делим по ближайшей подписи
        yy, xx = np.mgrid[0:SIZE, 0:SIZE]
        for i, (_, xi, yi, ri) in enumerate(regions):
            for j, (_, xj, yj, rj) in enumerate(regions):
                if j <= i or ri is None or rj is None:
                    continue
                both = (ri & rj).astype(bool)
                if both.sum() < 200:
                    continue
                closer_i = (xx - xi) ** 2 + (yy - yi) ** 2 <= (xx - xj) ** 2 + (yy - yj) ** 2
                ri[both & ~closer_i] = 0
                rj[both & closer_i] = 0

        rooms = []
        for name, x, y, reg in regions:
            if reg is None:
                poly = [[x - 22, y - 16], [x + 22, y - 16], [x + 22, y + 16], [x - 22, y + 16]]
                area = 44 * 32
            else:
                poly = to_polygon(reg)
                area = int(cv2.contourArea(np.array(poly)))
            kind = SPECIAL.get(name, ("classroom",))[0]
            if kind == "classroom" and area < OFFICE_PX:
                kind = "office"
            seats = max(6, min(200, round(area * SEATS_PER_PX / 2) * 2))
            rooms.append({
                "id": name if name not in SPECIAL else name.lower().replace(" ", "-").replace("#", ""),
                "name": SPECIAL_NAMES.get(name, f"Аудитория {name}"),
                "number": None if name in SPECIAL else name,
                "floor": floor,
                "kind": kind,
                "seats": seats if kind in ("classroom", "coworking", "hall") else None,
                "label": [x, y],
                "polygon": poly,
            })
        cv2.imwrite(str(OUT_IMG / f"floor-{floor}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 82])
        floors.append({
            "floor": floor,
            "image": f"/campus/floor-{floor}.jpg",
            "size": [SIZE, SIZE],
            "rooms": rooms,
        })
        print(f"этаж {floor}: {len(rooms)} помещений")

    # общая рамка для всех этажей — при переключении план не прыгает
    boxes = [red_bbox(img) for img in images]
    m = 30
    x0, y0 = min(b[0] for b in boxes) - m, min(b[1] for b in boxes) - m
    x1, y1 = max(b[2] for b in boxes) + m, max(b[3] for b in boxes) + m

    ids = [r["id"] for f in floors for r in f["rooms"]]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise SystemExit(f"повторяются номера: {sorted(dupes)}")
    return {
        "meta": {
            "title": "Главный корпус КБТУ, ул. Толе би, 59",
            "source": pdf.name,
            "view": [x0, y0, x1 - x0, y1 - y0],
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "streets": {"top": "ул. Казыбек би", "bottom": "ул. Толе би",
                        "left": "пр. Абылай хана", "right": "ул. Панфилова"},
        },
        "floors": floors,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", type=Path, help="PDF «Карта КБТУ по этажам»")
    args = ap.parse_args()
    data = build(args.pdf)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"-> {OUT_JSON.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
