"""Лист посещаемости: генерация PDF с метками и распознавание подписей по фото.

Геометрия листа задаётся в миллиметрах от левого верхнего угла страницы A4.
По углам — четыре залитых квадрата: по ним фото выпрямляется перспективным
преобразованием, после чего положение каждой клетки «Подпись» известно точно.
QR-код содержит номер листа и страницы, поэтому фото не нужно выбирать вручную.
"""

from __future__ import annotations

import base64
from io import BytesIO

import cv2
import numpy as np
import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

PAGE_W, PAGE_H = 210.0, 297.0
MARKER = 10.0  # сторона метки, мм
MARKER_CENTERS = {"tl": (15.0, 15.0), "tr": (195.0, 15.0), "bl": (15.0, 282.0), "br": (195.0, 282.0)}
TABLE_X = 20.0
COLS = [("№", 10.0), ("ФИО", 92.0), ("Student ID", 30.0), ("Подпись", 48.0)]
TABLE_TOP = 62.0
ROW_H = 9.0
ROWS_PER_PAGE = 22
PX_PER_MM = 5  # разрешение выпрямленной страницы при распознавании

# доля «чернил» в клетке: выше PRESENT — подпись есть, ниже ABSENT — пусто, между — проверить вручную
PRESENT, ABSENT = 0.03, 0.012

_FONT = "Helvetica"
for name, path in (("Arial", "C:/Windows/Fonts/arial.ttf"), ("DejaVuSans", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")):
    try:
        pdfmetrics.registerFont(TTFont(name, path))
        _FONT = name
        break
    except Exception:  # noqa: BLE001 — шрифта нет в системе, пробуем следующий
        continue


def layout(students: list[dict]) -> list[dict]:
    """Клетки подписи: страница и прямоугольник в мм для каждого студента."""
    sig_x0 = TABLE_X + sum(w for _, w in COLS[:-1])
    boxes = []
    for i, _ in enumerate(students):
        page, row = divmod(i, ROWS_PER_PAGE)
        y0 = TABLE_TOP + ROW_H * (row + 1)  # первая строка таблицы — шапка
        boxes.append({"index": i, "page": page, "box": [sig_x0, y0, sig_x0 + COLS[-1][1], y0 + ROW_H]})
    return boxes


def _qr(payload: str) -> ImageReader:
    img = qrcode.make(payload, box_size=6, border=2)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return ImageReader(buf)


def render_pdf(sheet: dict) -> bytes:
    students = sheet["students"]
    pages = max(1, -(-len(students) // ROWS_PER_PAGE))
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Посещаемость: {sheet['course']}, {sheet['group']}, {sheet['date']}")

    def y(v):  # мм от верха -> координаты reportlab от низа
        return (PAGE_H - v) * mm

    for page in range(pages):
        for cx, cy in MARKER_CENTERS.values():
            c.rect((cx - MARKER / 2) * mm, y(cy + MARKER / 2), MARKER * mm, MARKER * mm, stroke=0, fill=1)
        c.drawImage(_qr(f"KBTU-ATT:{sheet['id']}:{page}"), 160 * mm, y(52), 28 * mm, 28 * mm)
        c.setFont(_FONT, 15)
        c.drawString(TABLE_X * mm, y(30), "Лист посещаемости")
        c.setFont(_FONT, 10.5)
        c.drawString(TABLE_X * mm, y(38), f"Дисциплина: {sheet['course']}")
        c.drawString(TABLE_X * mm, y(44), f"Группа: {sheet['group']}     Дата: {sheet['date']}")
        c.setFont(_FONT, 8)
        c.drawString(TABLE_X * mm, y(52), f"Лист № {sheet['id']} · стр. {page + 1} из {pages} · "
                                           "расписывайтесь внутри своей клетки, метки по углам не закрывайте")
        # шапка таблицы
        x = TABLE_X
        c.setLineWidth(0.6)
        c.setFont(_FONT, 9.5)
        for title, w in COLS:
            c.rect(x * mm, y(TABLE_TOP + ROW_H), w * mm, ROW_H * mm, stroke=1, fill=0)
            c.drawString((x + 1.8) * mm, y(TABLE_TOP + 6), title)
            x += w
        rows = students[page * ROWS_PER_PAGE:(page + 1) * ROWS_PER_PAGE]
        c.setFont(_FONT, 9.5)
        for r, st in enumerate(rows):
            top = TABLE_TOP + ROW_H * (r + 1)
            x = TABLE_X
            values = [str(page * ROWS_PER_PAGE + r + 1), st["name"], st.get("student_id", ""), ""]
            for (_, w), value in zip(COLS, values, strict=True):
                c.rect(x * mm, y(top + ROW_H), w * mm, ROW_H * mm, stroke=1, fill=0)
                text = value if c.stringWidth(value, _FONT, 9.5) < (w - 3) * mm else value[: int(w / 2.1)] + "…"
                c.drawString((x + 1.8) * mm, y(top + 6), text)
                x += w
        c.showPage()
    c.save()
    return buf.getvalue()


# ---------------------------------------------------------------- распознавание
class ScanError(ValueError):
    pass


def _find_markers(gray: np.ndarray) -> dict[str, tuple[float, float]]:
    h, w = gray.shape
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    _, bw = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    # RETR_LIST: на фото лист лежит на тёмном фоне, и метки оказываются внутри внешнего контура
    contours, _ = cv2.findContours(bw, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    min_area = (min(h, w) / 70) ** 2
    candidates = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area or area > (min(h, w) / 6) ** 2:
            continue
        x, y, cw, ch = cv2.boundingRect(cnt)
        hull_area = cv2.contourArea(cv2.convexHull(cnt))
        # залитый, почти квадратный, выпуклый объект — метка; буквы и линии таблицы не проходят
        if not (0.6 < cw / ch < 1.6) or hull_area == 0 or area / hull_area < 0.9 or area / (cw * ch) < 0.75:
            continue
        m = cv2.moments(cnt)
        candidates.append((m["m10"] / m["m00"], m["m01"] / m["m00"], area))
    if len(candidates) < 4:
        raise ScanError("Не найдены четыре угловые метки. Сфотографируйте лист целиком, сверху, без бликов.")
    pts = np.array([(cx, cy) for cx, cy, _ in candidates])
    s, d = pts.sum(axis=1), pts[:, 0] - pts[:, 1]
    found = {"tl": pts[np.argmin(s)], "br": pts[np.argmax(s)], "tr": pts[np.argmax(d)], "bl": pts[np.argmin(d)]}
    if len({tuple(v) for v in found.values()}) < 4:
        raise ScanError("Угловые метки не распознаны однозначно. Переснимите лист ровнее.")
    return {k: (float(v[0]), float(v[1])) for k, v in found.items()}


def warp_page(image_bytes: bytes) -> np.ndarray:
    data = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise ScanError("Файл не похож на фотографию. Загрузите JPG или PNG.")
    scale = 2600 / max(img.shape[:2])
    if scale < 1:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    markers = _find_markers(gray)
    src = np.float32([markers[k] for k in ("tl", "tr", "br", "bl")])
    dst = np.float32([[x * PX_PER_MM, y * PX_PER_MM] for x, y in
                      (MARKER_CENTERS[k] for k in ("tl", "tr", "br", "bl"))])
    matrix = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(gray, matrix, (int(PAGE_W * PX_PER_MM), int(PAGE_H * PX_PER_MM)),
                               borderValue=255)


def read_qr(page: np.ndarray) -> tuple[int, int] | None:
    text, _, _ = cv2.QRCodeDetector().detectAndDecode(page)
    if text and text.startswith("KBTU-ATT:"):
        try:
            _, sheet_id, page_no = text.split(":")
            return int(sheet_id), int(page_no)
        except ValueError:
            return None
    return None


def score_boxes(page: np.ndarray, boxes: list[dict]) -> list[dict]:
    """Доля тёмных пикселей внутри клетки (с отступом от линий таблицы)."""
    bw = cv2.adaptiveThreshold(page, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 15)
    pad = 1.6 * PX_PER_MM
    out = []
    for b in boxes:
        x0, y0, x1, y1 = (v * PX_PER_MM for v in b["box"])
        roi = bw[int(y0 + pad):int(y1 - pad), int(x0 + pad):int(x1 - pad)]
        ratio = float(roi.mean() / 255) if roi.size else 0.0
        status = "present" if ratio >= PRESENT else "absent" if ratio <= ABSENT else "uncertain"
        out.append({"index": b["index"], "ink": round(ratio, 4), "status": status})
    return out


def overlay(page: np.ndarray, boxes: list[dict], scores: list[dict]) -> str:
    """Выпрямленная страница с рамками: зелёная — подпись есть, красная — нет, жёлтая — проверить."""
    color = {"present": (60, 170, 60), "absent": (40, 40, 220), "uncertain": (0, 190, 240)}
    img = cv2.cvtColor(page, cv2.COLOR_GRAY2BGR)
    for b, s in zip(boxes, scores, strict=True):
        x0, y0, x1, y1 = (int(v * PX_PER_MM) for v in b["box"])
        cv2.rectangle(img, (x0, y0), (x1, y1), color[s["status"]], 4)
    small = cv2.resize(img, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    ok, png = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return "data:image/jpeg;base64," + base64.b64encode(png.tobytes()).decode() if ok else ""
