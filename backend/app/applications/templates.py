"""Виды заявлений и генерация DOCX по образцам ШИТиИ.

Образцы (деканат ШИТиИ): регистрация на дисциплины (осень/весна/лето), снятие с регистрации,
перерегистрация в связи с перезачётом, тема магистерской диссертации. Студент заполняет
профиль один раз, а в заявлении вводит только суть; текст собирается здесь.
"""

from __future__ import annotations

from datetime import date
from io import BytesIO
from typing import Literal

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.shared import Cm, Pt
from pydantic import BaseModel, ConfigDict, Field, field_validator

ADDRESSEE = ("Декану ШИТиИ", "Иманбаеву А.Ж.")
SEMESTERS = {"autumn": "осеннего", "spring": "весеннего", "summer": "летнего"}
MASTER_PROGRAMS = [
    "7М06104 – IT management", "7М06105 – Data Science", "7М06106 – Software Engineering",
    "7М07112 – Computational Neuroscience and Cognitive Robotics", "7М07125 – Electronics and control systems",
    "7М06107 – Computer Science and Data Analytics", "7М07088 – Industrial and Systems Engineering",
    "7М06101 – Information Systems",
]


def default_year(today: date | None = None) -> str:
    """Учебный год: с августа — новый (2026–2027), до — текущий."""
    today = today or date.today()
    start = today.year if today.month >= 8 else today.year - 1
    return f"{start}–{start + 1}"


class Strict(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class Discipline(Strict):
    name: str = Field(min_length=3, max_length=200)
    credits_kz: str = Field(default="", max_length=5)
    ects: str = Field(default="", max_length=5)
    kind: Literal["", "retake", "overcredit"] = ""  # ритейк / сверхкредит — нужна квитанция


class Registration(Strict):
    semester: Literal["autumn", "spring", "summer"]
    academic_year: str = Field(default_factory=default_year, max_length=20)
    disciplines: list[Discipline] = Field(min_length=1, max_length=7)


class Drop(Strict):
    semester: Literal["autumn", "spring", "summer"]
    academic_year: str = Field(default_factory=default_year, max_length=20)
    discipline: str = Field(min_length=3, max_length=200)
    reason: str = Field(default="в связи с непрохождением пререквизита к данной дисциплине", max_length=300)
    replacement: Discipline | None = None


class Recredit(Strict):
    semester: Literal["autumn", "spring", "summer"]
    academic_year: str = Field(default_factory=default_year, max_length=20)
    recredited: str = Field(min_length=3, max_length=200)
    recredited_ects: str = Field(min_length=1, max_length=5)
    disciplines: list[Discipline] = Field(min_length=1, max_length=5)


class MasterThesis(Strict):
    program: str = Field(max_length=200)
    topic_kk: str = Field(min_length=5, max_length=500)
    topic_ru: str = Field(min_length=5, max_length=500)
    topic_en: str = Field(min_length=5, max_length=500)
    supervisor: str = Field(min_length=3, max_length=150)

    @field_validator("program")
    @classmethod
    def known_program(cls, value: str) -> str:
        if value not in MASTER_PROGRAMS:
            raise ValueError("Выберите образовательную программу магистратуры из списка")
        return value


TYPES = {
    "registration": {
        "title": "Регистрация на дисциплины",
        "description": "Добавить дисциплины осеннего, весеннего или летнего семестра, в том числе ритейк и сверхкредиты.",
        "model": Registration,
        "audience": "bachelor",
    },
    "drop": {
        "title": "Снятие с регистрации",
        "description": "Снять дисциплину (например, из-за непройденного пререквизита) и при необходимости заменить другой.",
        "model": Drop,
        "audience": "bachelor",
    },
    "recredit": {
        "title": "Перерегистрация после перезачёта",
        "description": "Дисциплина перезачтена — зарегистрироваться вместо неё на другие.",
        "model": Recredit,
        "audience": "bachelor",
    },
    "master_thesis": {
        "title": "Тема магистерской диссертации",
        "description": "Утвердить тему диссертации на трёх языках и научного руководителя.",
        "model": MasterThesis,
        "audience": "master",
    },
}

PROFILE_REQUIRED = {"full_name": "ФИО", "course": "курс", "program": "образовательная программа",
                    "phone": "сотовый номер", "email": "корпоративная почта"}


def missing_profile(profile: dict) -> list[str]:
    return [label for key, label in PROFILE_REQUIRED.items() if not str(profile.get(key) or "").strip()]


def _credits(d: Discipline) -> str:
    parts = []
    if d.credits_kz:
        parts.append(f"{d.credits_kz} кр. KZ")
    if d.ects:
        parts.append(f"{d.ects} ECTS")
    extra = {"retake": "ритейк", "overcredit": "сверхкредит"}.get(d.kind)
    if extra:
        parts.append(extra)
    return f" ({', '.join(parts)})" if parts else ""


def build_blocks(kind: str, data: BaseModel, profile: dict, today: date | None = None) -> list[dict]:
    """Содержимое заявления как список блоков — общий источник для DOCX и превью на сайте."""
    today = today or date.today()
    blocks: list[dict] = []

    def add(text: str, align: str = "left", style: str = "") -> None:
        blocks.append({"text": text, "align": align, "style": style})

    student_word = "магистранта" if kind == "master_thesis" else "студента"
    # шапка набирается жирным, как в образцах деканата
    add(ADDRESSEE[0], "right", "header")
    add(ADDRESSEE[1], "right", "header")
    add(f"от {student_word} {profile['course']} курса", "right", "header")
    add(f"ОП {profile['program']}", "right", "header")
    add(profile["full_name"], "right", "header")
    add(f"Сот. номер: {profile['phone']}", "right", "header")
    add(f"e-mail: {profile['email']}", "right", "header")
    add("Заявление", "center", "title")

    if isinstance(data, Registration):
        add(f"Прошу Вас разрешить мне зарегистрироваться на следующие дисциплины "
            f"{SEMESTERS[data.semester]} семестра {data.academic_year} учебного года:", "justify", "indent")
        for i, d in enumerate(data.disciplines, start=1):
            add(f"{i}. {d.name}{_credits(d)}", "justify")
        if any(d.kind for d in data.disciplines):
            add("Квитанция об оплате ритейка / сверхкредитов прилагается.", "justify", "indent")
    elif isinstance(data, Drop):
        add(f"Прошу Вас снять с регистрации дисциплину {SEMESTERS[data.semester]} семестра "
            f"{data.academic_year} учебного года: {data.discipline}, {data.reason}.", "justify", "indent")
        if data.replacement:
            add("Вместо данной дисциплины разрешить мне зарегистрироваться на следующую дисциплину: "
                f"{data.replacement.name}{_credits(data.replacement)}.", "justify", "indent")
    elif isinstance(data, Recredit):
        add(f"В связи с перезачётом дисциплины {data.recredited} ({data.recredited_ects} ECTS) прошу Вас "
            f"разрешить мне зарегистрироваться на следующие дисциплины {SEMESTERS[data.semester]} семестра "
            f"{data.academic_year} учебного года:", "justify", "indent")
        for i, d in enumerate(data.disciplines, start=1):
            add(f"{i}. {d.name}{_credits(d)}", "justify")
    elif isinstance(data, MasterThesis):
        add("Прошу Вас разрешить мне написание магистерской диссертации (работы) на тему:", "justify", "indent")
        add(f"На каз.: {data.topic_kk}", "justify")
        add(f"На рус.: {data.topic_ru}", "justify")
        add(f"На англ.: {data.topic_en}", "justify")
        add(f"Образовательная программа: {data.program}", "justify")
        add(f"Под руководством: {data.supervisor}", "justify")

    if kind == "master_thesis":
        add("Подпись магистранта ____________", "left", "signature")
        add("Подпись научного руководителя ____________", "left", "bold")
        add(f"Дата: {today:%d.%m.%Y}", "left", "bold")
    else:
        add(f"Дата: {today:%d.%m.%Y}\tПодпись ____________", "left", "signature")
    return blocks


ALIGN = {"left": WD_ALIGN_PARAGRAPH.LEFT, "right": WD_ALIGN_PARAGRAPH.RIGHT,
         "center": WD_ALIGN_PARAGRAPH.CENTER, "justify": WD_ALIGN_PARAGRAPH.JUSTIFY}


def render_docx(blocks: list[dict]) -> bytes:
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.left_margin, section.right_margin = Cm(3), Cm(1.5)
    section.top_margin = section.bottom_margin = Cm(2)
    normal = doc.styles["Normal"]
    normal.font.name, normal.font.size = "Times New Roman", Pt(14)
    normal.element.rPr.rFonts.set("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}eastAsia",
                                  "Times New Roman")
    normal.paragraph_format.space_after = Pt(0)
    normal.paragraph_format.line_spacing = 1.15
    for block in blocks:
        p = doc.add_paragraph()
        p.alignment = ALIGN[block["align"]]
        if block["style"] == "indent":
            p.paragraph_format.first_line_indent = Cm(1.25)
        if block["style"] == "title":
            p.paragraph_format.space_before = Pt(42)
            p.paragraph_format.space_after = Pt(12)
        if block["style"] == "signature":
            # «Дата … Подпись» по краям строки, с отступом от текста, как в образце
            p.paragraph_format.space_before = Pt(56)
            p.paragraph_format.tab_stops.add_tab_stop(Cm(16.5), WD_TAB_ALIGNMENT.RIGHT)
        run = p.add_run(block["text"])
        run.bold = block["style"] in ("title", "header", "signature", "bold")
    out = BytesIO()
    doc.save(out)
    return out.getvalue()
