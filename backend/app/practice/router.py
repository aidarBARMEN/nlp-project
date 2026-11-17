"""POST /api/practice/check — проверка отчёта и/или дневника практики до сдачи в деканат."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile

from . import requirements as R
from .checker import check_diary, check_report, cross_check

router = APIRouter(prefix="/api/practice", tags=["Проверка практики"])
MAX_MB = 25


def _read(upload: UploadFile | None, what: str) -> tuple[bytes, str] | None:
    if upload is None or not upload.filename:
        return None
    name = upload.filename
    if not name.lower().endswith(".docx"):
        raise HTTPException(400, f"{what}: нужен файл Word в формате .docx (сейчас: {name}). "
                                 "Файл → Сохранить как → Документ Word (*.docx)")
    data = upload.file.read()
    if len(data) > MAX_MB * 1024 * 1024:
        raise HTTPException(400, f"{what}: файл больше {MAX_MB} МБ")
    return data, name


def run_check(report: tuple[bytes, str] | None, diary: tuple[bytes, str] | None) -> dict:
    out: dict = {"documents": [], "cross": []}
    reps = {}
    for kind, payload, fn in (("report", report, check_report), ("diary", diary, check_diary)):
        if not payload:
            continue
        try:
            reps[kind] = fn(*payload)
        except Exception as e:  # noqa: BLE001 — повреждённый или не-Word файл
            raise HTTPException(400, f"Не удалось открыть {payload[1]}: файл повреждён или это не документ Word") from e
        out["documents"].append(reps[kind].to_dict())
    if len(reps) == 2:
        out["cross"] = cross_check(reps["report"], reps["diary"])
    out["ready"] = all(d["ready"] for d in out["documents"]) and all(c["status"] != "fail" for c in out["cross"])
    return out


@router.post("/check")
def check(
    report: Annotated[UploadFile | None, File()] = None,
    diary: Annotated[UploadFile | None, File()] = None,
):
    r, d = _read(report, "Отчёт"), _read(diary, "Дневник")
    if not r and not d:
        raise HTTPException(400, "Загрузите отчёт и/или дневник практики")
    return run_check(r, d)


@router.get("/requirements")
def requirements():
    """Требования в читаемом виде — показываются студенту рядом с кнопкой проверки."""
    def margins(spec):
        names = {"left": "левое", "right": "правое", "top": "верхнее", "bottom": "нижнее"}
        def value(lo, hi):
            # узкий диапазон — это допуск вокруг одного значения: 1.9–2.1 -> «2»
            return f"{(lo + hi) / 2:g}" if hi - lo <= 0.25 else f"{lo:g}–{hi:g}"

        return ", ".join(f"{names[k]} {value(lo, hi)}" for k, (lo, hi) in spec["margins_cm"].items()) + " см"

    return {
        "report": {
            "title": R.REPORT["title"],
            "items": [
                "Формат .docx, лист A4, книжная ориентация",
                f"Поля: {margins(R.REPORT)}",
                f"Шрифт {R.REPORT['font']}, {R.REPORT['body_size_pt']} пт (в таблицах и подписях — 12 пт)",
                f"Интервал {R.REPORT['line_spacing'][0]:g}–{R.REPORT['line_spacing'][1]:g}, "
                f"абзацный отступ {R.REPORT['first_line_indent_cm']:g} см, выравнивание по ширине",
                "Нумерация страниц, содержание",
                "Разделы: " + " → ".join(label for label, _ in R.REPORT["sections"]),
                "Подписи «Table N – Название» над таблицей и «Figure N – Название» под рисунком",
                f"Не менее {R.REPORT['min_references']} источников, у ссылок — дата обращения",
            ],
        },
        "diary": {
            "title": R.DIARY["title"],
            "items": [
                "Бланк дневника деканата, формат .docx",
                f"Поля: {margins(R.DIARY)}",
                f"Шрифт {R.DIARY['font']}, {R.DIARY['body_size_pt']} пт",
                "Заполнены ФИО, курс, шифр ОП, место и даты практики",
                f"Не менее {R.DIARY['min_entries']} датированных записей о работах в пределах периода практики",
                "Список собранных материалов и характеристика с рекомендуемой оценкой",
            ],
        },
    }
