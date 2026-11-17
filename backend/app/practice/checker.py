"""Проверка оформления отчёта и дневника практики (DOCX) по требованиям из requirements.py.

Каждая проверка возвращает статус:
    fail — нарушение, с которым документ не примут;
    warn — рекомендация, лучше исправить;
    info — подсказка, что проверяется вручную (подписи, печать);
    pass — требование выполнено.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date
from io import BytesIO

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Length

from . import requirements as R

MONTHS = {"января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6, "июля": 7, "августа": 8,
          "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12}
DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")
RU_DATE_RE = re.compile(r"«?\s*(\d{1,2})\s*»?\s+(" + "|".join(MONTHS) + r")\s+(\d{4})", re.I)
FIG_RE = re.compile(r"^(figure|fig\.|рисунок|рис\.|сурет)\s*(\d+)\s*[–—\-.:]", re.I)
TAB_RE = re.compile(r"^(table|таблица|кесте)\s*(\d+)\s*[–—\-.:]", re.I)
PLACEHOLDER_RE = re.compile(r"lorem ipsum|\bTODO\b|<\s*(вставить|insert)|\[\s*(вставить|insert|фио|name)\s*\]|XXX", re.I)


@dataclass
class Finding:
    id: str
    group: str
    title: str
    status: str
    message: str
    where: list[str] = field(default_factory=list)


@dataclass
class Report:
    kind: str
    file_name: str
    findings: list[Finding] = field(default_factory=list)
    facts: dict = field(default_factory=dict)

    def add(self, id_, group, title, status, message, where=None):
        self.findings.append(Finding(id_, group, title, status, message, list(where or [])[:5]))

    def to_dict(self) -> dict:
        counts = Counter(f.status for f in self.findings)
        return {
            "kind": self.kind,
            "title": R.REPORT["title"] if self.kind == "report" else R.DIARY["title"],
            "file_name": self.file_name,
            "ready": counts["fail"] == 0,
            "counts": {s: counts.get(s, 0) for s in ("fail", "warn", "info", "pass")},
            "facts": self.facts,
            "findings": [asdict(f) for f in self.findings],
        }


# ---------------------------------------------------------------- эффективные свойства (как в Word)
def _styles(style):
    while style is not None:
        yield style
        style = style.base_style


def _doc_defaults(document) -> dict:
    out = {"font": None, "size": None, "spacing": None}
    defaults = document.styles.element.find(qn("w:docDefaults"))
    if defaults is None:
        return out
    rpr = defaults.find(f"{qn('w:rPrDefault')}/{qn('w:rPr')}")
    if rpr is not None:
        fonts = rpr.find(qn("w:rFonts"))
        if fonts is not None:
            out["font"] = fonts.get(qn("w:ascii")) or fonts.get(qn("w:hAnsi"))
        sz = rpr.find(qn("w:sz"))
        if sz is not None:
            out["size"] = int(sz.get(qn("w:val"))) / 2
    ppr = defaults.find(f"{qn('w:pPrDefault')}/{qn('w:pPr')}")
    if ppr is not None:
        sp = ppr.find(qn("w:spacing"))
        if sp is not None and sp.get(qn("w:line")) and sp.get(qn("w:lineRule"), "auto") == "auto":
            out["spacing"] = int(sp.get(qn("w:line"))) / 240
    return out


class Props:
    def __init__(self, document):
        self.defaults = _doc_defaults(document)

    def font(self, run, para) -> str | None:
        if run.font.name:
            return run.font.name
        for st in [*(_styles(run.style) if run.style is not None else []), *_styles(para.style)]:
            if st.font.name:
                return st.font.name
        return self.defaults["font"]

    def size(self, run, para) -> float | None:
        if run.font.size:
            return run.font.size.pt
        for st in [*(_styles(run.style) if run.style is not None else []), *_styles(para.style)]:
            if st.font.size:
                return st.font.size.pt
        return self.defaults["size"]

    @staticmethod
    def _pf(para, attr):
        value = getattr(para.paragraph_format, attr)
        if value is not None:
            return value
        for st in _styles(para.style):
            value = getattr(st.paragraph_format, attr)
            if value is not None:
                return value
        return None

    def alignment(self, para):
        return self._pf(para, "alignment") or WD_ALIGN_PARAGRAPH.LEFT

    def first_indent_cm(self, para) -> float:
        value = self._pf(para, "first_line_indent")
        return round(value.cm, 2) if value is not None else 0.0

    def line_spacing(self, para, size_pt: float) -> float:
        value = self._pf(para, "line_spacing")
        if value is None:
            return self.defaults["spacing"] or 1.0
        if isinstance(value, Length):  # точный интервал в пунктах -> множитель от кегля
            return round(value.pt / (size_pt * 1.15), 2)
        return round(float(value), 2)


def _excerpt(text: str, n: int = 60) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return f"«{text[:n]}{'…' if len(text) > n else ''}»"


def _norm(text: str) -> str:
    """Название раздела без нумерации, номера страницы из оглавления и знаков препинания."""
    text = text.split("\t")[0]
    text = re.sub(r"^\s*(\d+(\.\d+)*\.?|[IVX]+\.)\s*", "", text)
    return re.sub(r"[\s.:,;]+$", "", text).strip().upper().replace("Ё", "Е")


def _is_toc(para) -> bool:
    return para.style.name.lower().startswith(("toc", "оглавление")) or bool(re.search(r"\t\s*\d+\s*$", para.text))


def _has_page_numbers(document) -> bool:
    for section in document.sections:
        for part in (section.footer, section.header, section.first_page_footer, section.even_page_footer):
            try:
                xml = part._element.xml
            except Exception:  # noqa: BLE001
                continue
            if re.search(r"(instrText[^>]*>\s*PAGE\b|w:instr=\"\s*PAGE\b)", xml):
                return True
    return False


# ---------------------------------------------------------------- общие проверки оформления
def _check_layout(rep: Report, document, spec: dict, prefix: str) -> None:
    s = document.sections[0]
    w, h, tol = spec["page"]["width_cm"], spec["page"]["height_cm"], spec["page"]["tolerance_cm"]
    pw, ph = s.page_width.cm, s.page_height.cm
    ok = abs(pw - w) <= tol and abs(ph - h) <= tol
    rep.add(f"{prefix}02", "Страница", "Формат A4, книжная ориентация", "pass" if ok else "fail",
            f"Размер страницы {pw:.1f}×{ph:.1f} см" + ("" if ok else f", требуется {w}×{h} см (A4, книжная)"))

    bad = []
    names = {"left": "левое", "right": "правое", "top": "верхнее", "bottom": "нижнее"}
    actual = {"left": s.left_margin.cm, "right": s.right_margin.cm, "top": s.top_margin.cm, "bottom": s.bottom_margin.cm}
    for side, (lo, hi) in spec["margins_cm"].items():
        if not lo - 0.05 <= actual[side] <= hi + 0.05:
            need = f"{lo:g}" if lo == hi else f"{lo:g}–{hi:g}"
            bad.append(f"{names[side]} {actual[side]:.2f} см (нужно {need} см)")
    rep.add(f"{prefix}03", "Страница", "Поля страницы", "fail" if bad else "pass",
            "Поля: " + ", ".join(bad) if bad else
            "Поля: " + ", ".join(f"{names[k]} {v:.2f}" for k, v in actual.items()) + " см")


def _check_typography(rep: Report, document, spec: dict, prefix: str, props: Props, body: list) -> None:
    fonts, sizes, odd_sizes = Counter(), Counter(), []
    for p in document.paragraphs:
        for r in p.runs:
            n = len(r.text.strip())
            if not n:
                continue
            fonts[props.font(r, p) or "не указан"] += n
    total = sum(fonts.values()) or 1
    share = fonts.get(spec["font"], 0) / total
    others = ", ".join(f"{f} ({c / total:.0%})" for f, c in fonts.most_common() if f != spec["font"])[:120]
    rep.add(f"{prefix}04", "Шрифт", f"Шрифт {spec['font']}",
            "pass" if share >= spec["font_share_min"] else "fail",
            f"{share:.0%} текста набрано шрифтом {spec['font']}" + (f"; также: {others}" if others else ""))

    for p in body:
        for r in p.runs:
            n = len(r.text.strip())
            if n:
                sz = props.size(r, p)
                sizes[sz] += n
                if sz not in spec["allowed_sizes_pt"] and len(odd_sizes) < 5:
                    odd_sizes.append(f"{_excerpt(p.text)} — {sz:g} пт" if sz else _excerpt(p.text))
    total = sum(sizes.values()) or 1
    share = sizes.get(spec["body_size_pt"], 0) / total
    rep.add(f"{prefix}05", "Шрифт", f"Кегль основного текста {spec['body_size_pt']} пт",
            "pass" if share >= spec["body_size_share_min"] else "fail",
            f"{share:.0%} основного текста набрано кеглем {spec['body_size_pt']} пт", odd_sizes)

    lo, hi = spec["line_spacing"]
    bad = []
    for p in body:
        size = next((props.size(r, p) for r in p.runs if r.text.strip()), spec["body_size_pt"]) or spec["body_size_pt"]
        ls = props.line_spacing(p, size)
        if not lo - 0.05 <= ls <= hi + 0.05:
            bad.append(f"{_excerpt(p.text)} — {ls:g}")
    rep.add(f"{prefix}06", "Абзацы", f"Межстрочный интервал {lo:g}–{hi:g}",
            "warn" if bad else "pass",
            f"Интервал вне диапазона в {len(bad)} абзацах" if bad else "Интервал в норме во всём основном тексте", bad)


# ---------------------------------------------------------------- отчёт
def _find_sections(paragraphs, sections) -> dict:
    found = {}
    for i, p in enumerate(paragraphs):
        if not p.text.strip() or _is_toc(p):
            continue
        name = _norm(p.text)
        for label, variants in sections:
            # «СПИСОК МАТЕРИАЛОВ, СОБРАННЫХ…» тоже считается заголовком «СПИСОК МАТЕРИАЛОВ»
            if label not in found and any(re.match(rf"{re.escape(v)}(\W|$)", name) for v in variants):
                found[label] = (i, p)
    return found


def check_report(data: bytes, file_name: str) -> Report:
    spec = R.REPORT
    rep = Report("report", file_name)
    document = docx.Document(BytesIO(data))
    props = Props(document)
    paras = document.paragraphs
    texts = [p.text for p in paras]

    toc_idx = next((i for i, p in enumerate(paras) if _norm(p.text) in spec["toc_titles"]), None)
    title_end = toc_idx if toc_idx is not None else min(len(paras), 25)
    body = [p for p in paras[title_end:] if len(p.text.strip()) >= 150 and not _is_toc(p)
            and not FIG_RE.match(p.text.strip()) and not TAB_RE.match(p.text.strip())]

    _check_layout(rep, document, spec, "R")
    _check_typography(rep, document, spec, "R", props, body)

    target, tol = spec["first_line_indent_cm"], spec["indent_tolerance_cm"]
    bad = [f"{_excerpt(p.text)} — {props.first_indent_cm(p):g} см" for p in body
           if abs(props.first_indent_cm(p) - target) > tol]
    share = 1 - len(bad) / (len(body) or 1)
    rep.add("R07", "Абзацы", f"Абзацный отступ {target:g} см", "pass" if share >= 0.9 else "warn",
            f"Отступ {target:g} см у {share:.0%} абзацев основного текста", bad)

    bad = [_excerpt(p.text) for p in body if props.alignment(p) != WD_ALIGN_PARAGRAPH.JUSTIFY]
    share = 1 - len(bad) / (len(body) or 1)
    rep.add("R08", "Абзацы", "Выравнивание основного текста по ширине",
            "pass" if share >= spec["justify_share_min"] else "warn",
            f"По ширине выровнено {share:.0%} абзацев основного текста", bad)

    has_pages = _has_page_numbers(document)
    rep.add("R09", "Страница", "Нумерация страниц", "pass" if has_pages else "fail",
            "Номера страниц вставлены полем Word" if has_pages else
            "Нет номеров страниц: Вставка → Номер страницы → внизу страницы")

    # титульный лист
    title_text = "\n".join(texts[:title_end]).lower()
    missing = [label for label, rx in spec["title_page"] if not re.search(rx, title_text, re.I)]
    critical = {"Название университета", "Вид документа «Отчёт»", "ФИО студента"}
    rep.add("R10", "Титульный лист", "Обязательные сведения на титульном листе",
            "fail" if critical & set(missing) else ("warn" if missing else "pass"),
            "Не найдено: " + ", ".join(missing) if missing else
            "Есть университет, вид документа, место практики, студент, руководитель, город и год")
    period = re.search(r"(\d{1,2}\.\d{1,2}\.\d{4})\s*[–—\-]\s*(\d{1,2}\.\d{1,2}\.\d{4})", "\n".join(texts[:title_end]))
    if period:
        rep.facts["period"] = [period.group(1), period.group(2)]
    student = re.search(r"(prepared by|performed by|выполнил[а]?|студент[а]?)\s*:?\s*([A-ZА-ЯЁӘҒҚҢӨҰҮҺІ][^\n,]{3,60})",
                        "\n".join(texts[:title_end]), re.I)
    if student:
        rep.facts["student"] = student.group(2).strip()

    has_toc = toc_idx is not None or any(p.style.name.lower().startswith("toc") for p in paras)
    rep.add("R11", "Структура", "Содержание (оглавление)", "pass" if has_toc else "fail",
            "Содержание есть" if has_toc else "Нет содержания: Ссылки → Оглавление")

    found = _find_sections(paras, spec["sections"])
    for k, (label, variants) in enumerate(spec["sections"], start=1):
        ok = label in found
        rep.add(f"R12.{k}", "Структура", f"Раздел «{label}»", "pass" if ok else "fail",
                f"Найден: {_excerpt(found[label][1].text, 40)}" if ok else
                f"Раздел не найден. Ожидается заголовок: {variants[0]} / {variants[1]}")
    order = [found[label][0] for label, _ in spec["sections"] if label in found]
    if order != sorted(order):
        rep.add("R13", "Структура", "Порядок разделов", "warn",
                "Разделы идут не по порядку: " + " → ".join(label for label, _ in spec["sections"]))
    for label, _variants in spec["optional_sections"]:
        if label not in _find_sections(paras, spec["optional_sections"]):
            rep.add("R14", "Структура", f"Раздел «{label}»", "info", "Рекомендуемый раздел отсутствует")
    lower = [_excerpt(p.text, 40) for _i, p in found.values() if p.text.strip() != p.text.strip().upper()]
    rep.add("R15", "Структура", "Заголовки разделов прописными буквами", "warn" if lower else "pass",
            "Заголовки разделов набираются прописными: " + ", ".join(lower) if lower else
            "Заголовки основных разделов набраны прописными", [])

    # рисунки и таблицы
    for rid, rx, what in (("R16", FIG_RE, "рисунков"), ("R17", TAB_RE, "таблиц")):
        nums = [int(m.group(2)) for t in texts if (m := rx.match(t.strip()))]
        expected = list(range(1, len(nums) + 1))
        rep.add(rid, "Иллюстрации", f"Сквозная нумерация {what}", "pass" if nums == expected else "warn",
                (f"Подписано {what}: {len(nums)}, нумерация 1–{len(nums)} без пропусков" if nums else
                 f"Подписей {what} не найдено") if nums == expected else
                f"Нумерация {what} с пропусками или повторами: {', '.join(map(str, nums))}")
        if rx is FIG_RE:
            rep.facts["figures"] = len(nums)
        else:
            rep.facts["tables"] = len(nums)
    images = len(document.inline_shapes)
    uncaptioned = images - rep.facts.get("figures", 0) - 1  # логотип на титульном листе
    rep.add("R18", "Иллюстрации", "Подписи у всех рисунков", "warn" if uncaptioned > 0 else "pass",
            f"Изображений {images}, подписей рисунков {rep.facts.get('figures', 0)}: у части рисунков нет подписи "
            "«Figure N – Название»" if uncaptioned > 0 else f"Изображений {images}, все подписаны")
    # рамки 1×1 — это обычно листинги кода, их не подписывают
    data_tables = [t for t in document.tables if len(t.rows) > 1 or len(t.columns) > 1]
    if len(data_tables) > rep.facts.get("tables", 0) + 1:
        rep.add("R19", "Иллюстрации", "Названия у таблиц", "warn",
                f"Таблиц с данными {len(data_tables)}, подписанных {rep.facts.get('tables', 0)}. "
                "Над таблицей пишется «Table N – Название». Листинги кода в рамке-таблице подписывать не нужно.")

    # список источников
    if "Список источников" in found:
        start = found["Список источников"][0] + 1
        refs = [p.text.strip() for p in paras[start:] if p.text.strip()]
        numbered = [t for t in refs if re.match(r"^\d+[\).]\s", t)] or refs
        no_date = [_excerpt(t, 50) for t in numbered if re.search(r"https?://", t)
                   and not re.search(r"дата обращения|accessed|қаралған күні|\d{2}\.\d{2}\.\d{4}", t, re.I)]
        n = len(numbered)
        rep.facts["references"] = n
        rep.add("R20", "Источники", f"Не менее {spec['min_references']} источников",
                "pass" if n >= spec["min_references"] else ("fail" if n == 0 else "warn"), f"Источников: {n}")
        rep.add("R21", "Источники", "Дата обращения у электронных источников", "warn" if no_date else "pass",
                f"У {len(no_date)} ссылок нет даты обращения, например: «URL: … (дата обращения: 15.08.2026)»"
                if no_date else "У всех электронных источников указана дата обращения", no_date)

    words = sum(len(t.split()) for t in texts) + sum(len(c.text.split()) for t in document.tables for r in t.rows
                                                      for c in r.cells)
    rep.facts["words"] = words
    rep.add("R22", "Объём", f"Объём не менее {spec['min_words']} слов", "pass" if words >= spec["min_words"] else "warn",
            f"В отчёте {words} слов")

    run, worst = 0, 0
    for p in paras[title_end:]:
        run = run + 1 if not p.text.strip() and not p._element.findall(f".//{qn('w:drawing')}") else 0
        worst = max(worst, run)
    rep.add("R23", "Абзацы", "Нет пустых строк вместо разрывов страниц", "warn" if worst >= 4 else "pass",
            f"Найдено {worst} пустых строк подряд: для перехода на новую страницу используйте Ctrl+Enter"
            if worst >= 4 else "Лишних пустых строк нет")

    holders = [_excerpt(t) for t in texts if PLACEHOLDER_RE.search(t)]
    rep.add("R24", "Содержание", "Нет незаполненных шаблонных фрагментов", "fail" if holders else "pass",
            "Найдены заготовки шаблона" if holders else "Шаблонных заготовок не найдено", holders)
    return rep


# ---------------------------------------------------------------- дневник
def _parse_ru_date(text: str) -> date | None:
    m = RU_DATE_RE.search(text)
    if m:
        return date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
    m = DATE_RE.search(text)
    return date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None


def _parse_date(text: str) -> date | None:
    m = DATE_RE.search(text or "")
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None
    except ValueError:
        return None


def _after(texts: list[str], pattern: str) -> str:
    """Текст строки, следующей за меткой, или остаток самой строки после метки."""
    for i, t in enumerate(texts):
        m = re.search(pattern, t, re.I)
        if m:
            rest = t[m.end():].strip(" :_\t")
            if rest:
                return rest
            return texts[i + 1].strip() if i + 1 < len(texts) else ""
    return ""


def _blank(value: str) -> bool:
    return not re.sub(r"[_\s«»().,\-–—]", "", value)


def check_diary(data: bytes, file_name: str) -> Report:
    spec = R.DIARY
    rep = Report("diary", file_name)
    document = docx.Document(BytesIO(data))
    props = Props(document)
    paras = document.paragraphs
    texts = [p.text.strip() for p in paras if p.text.strip()]
    body = [p for p in paras if len(p.text.strip()) >= 80]

    _check_layout(rep, document, spec, "D")
    _check_typography(rep, document, spec, "D", props, body)

    found = _find_sections(paras, spec["sections"])
    for k, (label, variants) in enumerate(spec["sections"], start=1):
        ok = label in found
        rep.add(f"D10.{k}", "Структура", f"Раздел «{label}»", "pass" if ok else "fail",
                "Раздел есть" if ok else f"Не найден раздел «{variants[0]}». Используйте бланк дневника деканата.")

    student = _after(texts, r"^студента\b")
    student = re.sub(r"\(.*?\)", "", student).strip()
    rep.facts["student"] = student
    rep.add("D11", "Титул", "ФИО студента", "fail" if _blank(student) else "pass",
            f"Студент: {student}" if not _blank(student) else "ФИО студента на титульном листе не заполнено")
    program = re.search(r"\b6B\d{5}\b", "\n".join(texts[:15]), re.I)
    rep.add("D12", "Титул", "Шифр и название образовательной программы", "pass" if program else "fail",
            f"Программа: {program.group(0)}" if program else "Не указан шифр ОП (например, 6B06101 – Информационные системы)")
    course = re.search(r"года обучения\s+(\d)", "\n".join(texts[:15]), re.I)
    rep.add("D13", "Титул", "Курс (год обучения)", "pass" if course else "fail",
            f"Курс: {course.group(1)}" if course else "Не указан год обучения на титульном листе")

    company = _after(texts, r"прибыл на место практики")
    start = _parse_ru_date(_after(texts, r"приступил[а]? к практике") or "")
    end = _parse_ru_date(_after(texts, r"завершил[а]? практику") or "")
    for t in texts:  # дата часто стоит в той же строке: «Приступил к практике «20» июля 2026 г.»
        if re.search(r"приступил[а]? к практике", t, re.I):
            start = _parse_ru_date(t) or start
        if re.search(r"завершил[а]? практику", t, re.I):
            end = _parse_ru_date(t) or end
    rep.add("D14", "Справка", "Место практики", "fail" if _blank(company) else "pass",
            f"Место практики: {company}" if not _blank(company) else "Не указано, куда студент прибыл на практику")
    if start and end:
        rep.facts["period"] = [start.strftime("%d.%m.%Y"), end.strftime("%d.%m.%Y")]
        ok = start <= end
        rep.add("D15", "Справка", "Даты начала и окончания практики", "pass" if ok else "fail",
                f"Практика с {start:%d.%m.%Y} по {end:%d.%m.%Y} ({(end - start).days + 1} дн.)" if ok else
                f"Дата окончания {end:%d.%m.%Y} раньше даты начала {start:%d.%m.%Y}")
    else:
        rep.add("D15", "Справка", "Даты начала и окончания практики", "fail",
                "Не заполнены даты «Приступил к практике» и/или «Завершил практику»")
    rep.add("D16", "Справка", "Подпись и печать предприятия в справке", "info",
            "Проверяется на бумажном оригинале: подпись руководителя и печать организации")

    # таблица ежедневных записей
    table = next((t for t in document.tables if any("наименование" in c.text.lower() for c in t.rows[0].cells)),
                 document.tables[0] if document.tables else None)
    entries, problems = [], []
    if table is not None:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            d1, d2 = _parse_date(cells[0]), _parse_date(cells[1] if len(cells) > 1 else "")
            text = cells[2] if len(cells) > 2 else ""
            if not d1 and not text:
                continue
            if not d1:
                continue  # строки шапки
            entries.append((d1, d2, text))
            if d2 and d2 < d1:
                problems.append(f"{cells[0]}: дата окончания раньше начала")
            if len(text) < spec["min_entry_chars"]:
                problems.append(f"{cells[0]}: нет описания работы" if not text else f"{cells[0]}: описание слишком краткое")
            if start and end and not (start <= d1 <= end):
                problems.append(f"{cells[0]}: дата вне периода практики {start:%d.%m}–{end:%d.%m.%Y}")
        dates = [e[0] for e in entries]
        if dates != sorted(dates):
            problems.append("записи идут не по порядку дат")
    rep.facts["entries"] = len(entries)
    if table is None:
        rep.add("D17", "Записи", "Таблица ежедневных записей", "fail", "В дневнике нет таблицы записей о работах")
    else:
        rep.add("D17", "Записи", f"Не менее {spec['min_entries']} записей о работах",
                "pass" if len(entries) >= spec["min_entries"] else "fail", f"Записей с датами: {len(entries)}")
        rep.add("D18", "Записи", "Даты и описания записей", "fail" if problems else "pass",
                f"Ошибок в записях: {len(problems)}" if problems else
                "Все записи датированы, идут по порядку и попадают в период практики", problems)
        rep.add("D19", "Записи", "Подписи руководителя в таблице записей", "info",
                "Колонку «Подпись руководителя» руководитель заполняет от руки")

    if "Список собранных материалов" in found:
        i = found["Список собранных материалов"][0]
        stop = found.get("Характеристика работы студента", (len(paras), None))[0]
        items = [p.text for p in paras[i + 1:stop] if re.match(r"^\s*\d+[\).]", p.text) or p.text.strip()]
        rep.add("D20", "Материалы", f"Не менее {spec['min_materials']} собранных материалов",
                "pass" if len(items) >= spec["min_materials"] else "warn", f"Пунктов в списке: {len(items)}")

    if "Характеристика работы студента" in found:
        i = found["Характеристика работы студента"][0]
        text = " ".join(p.text for p in paras[i + 1:] if p.text.strip())
        size_ok = len(text) >= spec["min_characteristic_chars"]
        grade = re.search(r"оценк", text, re.I)
        rep.add("D21", "Характеристика", "Характеристика заполнена", "pass" if size_ok else "fail",
                f"Объём характеристики: {len(text)} знаков" if size_ok else "Характеристика не заполнена или слишком краткая")
        rep.add("D22", "Характеристика", "Рекомендуемая оценка руководителя", "pass" if grade else "warn",
                "Оценка указана" if grade else "В заключении руководителя не указана рекомендуемая оценка")
    return rep


# ---------------------------------------------------------------- сверка отчёта и дневника
TRANSLIT = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюяәғқңөұүһі",
                    ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "i", "k", "l", "m", "n", "o", "p", "r", "s",
                     "t", "u", "f", "kh", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya", "a", "g", "k", "n",
                     "o", "u", "u", "h", "i"], strict=True))


def _latin(text: str) -> str:
    return "".join(TRANSLIT.get(c, c) for c in text.lower())


def cross_check(report: Report, diary: Report) -> list[dict]:
    out = []
    r_name, d_name = report.facts.get("student", ""), diary.facts.get("student", "")
    if r_name and d_name:
        r_tokens = {_latin(w)[:5] for w in re.findall(r"\w{3,}", r_name)}
        d_tokens = {_latin(w)[:5] for w in re.findall(r"\w{3,}", d_name)}
        ok = bool(r_tokens & d_tokens)
        out.append(asdict(Finding("X01", "Сверка", "ФИО совпадает в отчёте и дневнике", "pass" if ok else "fail",
                                  f"Отчёт: {r_name}; дневник: {d_name}")))
    r_period, d_period = report.facts.get("period"), diary.facts.get("period")
    if r_period and d_period:
        ok = r_period == d_period
        out.append(asdict(Finding("X02", "Сверка", "Период практики совпадает", "pass" if ok else "fail",
                                  f"Отчёт: {' – '.join(r_period)}; дневник: {' – '.join(d_period)}")))
    elif not r_period:
        out.append(asdict(Finding("X02", "Сверка", "Период практики на титуле отчёта", "warn",
                                  "На титульном листе отчёта не найден период в виде «20.07.2026 – 16.08.2026»")))
    return out
