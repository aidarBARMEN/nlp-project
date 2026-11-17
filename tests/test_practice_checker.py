"""Автопроверка документов практики: правильные документы проходят, типичные ошибки находятся."""

from io import BytesIO

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

from backend.app.practice.checker import check_diary, check_report, cross_check

BODY = (
    "During the practice I studied the business processes of the company, designed the database "
    "and prepared the analytical reports for the management of the enterprise. "
) * 3


def _page_number(section):
    p = section.footer.paragraphs[0]
    run = p.add_run()
    for tag, attr in (("w:fldChar", "begin"), ("w:instrText", None), ("w:fldChar", "end")):
        el = OxmlElement(tag)
        if attr:
            el.set(qn("w:fldCharType"), attr)
        else:
            el.text = "PAGE"
        run._r.append(el)


def make_report(
    font="Times New Roman", left=2.25, page_numbers=True, sections=None, refs=6, size=14
):
    d = docx.Document()
    s = d.sections[0]
    s.page_width, s.page_height = Cm(21), Cm(29.7)
    s.left_margin, s.right_margin, s.top_margin, s.bottom_margin = Cm(left), Cm(1.25), Cm(2), Cm(2)
    normal = d.styles["Normal"]
    normal.font.name, normal.font.size = font, Pt(size)
    normal.paragraph_format.first_line_indent = Cm(1.25)
    normal.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    if page_numbers:
        _page_number(s)
    for line in [
        "“Kazakh-British Technical University” JSC",
        "REPORT",
        "on industrial practice",
        "Company: Demo LLP",
        "Practice period: 20.07.2026 – 16.08.2026",
        "Prepared By: Testov Arman",
        "Practice supervisor from the enterprise: Director",
        "Almaty, 2026",
        "CONTENT",
    ]:
        d.add_paragraph(line)
    for name in sections or [
        "INTRODUCTION",
        "ABOUT COMPANY",
        "INDIVIDUAL TASK",
        "RESULTS",
        "CONCLUSION",
    ]:
        d.add_paragraph(name)
        for _ in range(8):
            d.add_paragraph(BODY)
    d.add_paragraph("REFERENCES")
    for i in range(1, refs + 1):
        d.add_paragraph(f"{i}) Source {i}. — URL: https://example.org/{i} (accessed: 15.08.2026)")
    buf = BytesIO()
    d.save(buf)
    return buf.getvalue()


def make_diary(entries=12, start="«20» июля 2026 г.", entry_month="07"):
    d = docx.Document()
    s = d.sections[0]
    s.page_width, s.page_height = Cm(21), Cm(29.7)
    s.left_margin, s.right_margin, s.top_margin, s.bottom_margin = Cm(3), Cm(1.5), Cm(2), Cm(2)
    d.styles["Normal"].font.name, d.styles["Normal"].font.size = "Times New Roman", Pt(12)
    for line in [
        "ДНЕВНИК",
        "по производственной практике",
        "студента Тестова Армана",
        "года обучения  3  специальности/образовательные программы",
        "6B06101 – Информационные системы",
        "СПРАВКА О ПРОХОЖДЕНИИ ПРАКТИКИ",
        "Прибыл на место практики ТОО «Демо»",
        f"Приступил к практике {start}",
        "Завершил практику «16» августа 2026 г.",
        "ЗАПИСИ О РАБОТАХ,",
    ]:
        d.add_paragraph(line)
    t = d.add_table(rows=1, cols=4)
    for c, h in zip(
        t.rows[0].cells, ["Начало", "Завершение", "Наименование работ", "Подпись"], strict=True
    ):
        c.text = h
    for i in range(entries):
        day = f"{21 + i:02d}.{entry_month}.2026"
        row = t.add_row().cells
        row[0].text, row[1].text, row[2].text = (
            day,
            day,
            "Изучение бизнес-процессов и подготовка данных",
        )
    d.add_paragraph("СПИСОК МАТЕРИАЛОВ, СОБРАННЫХ СТУДЕНТОМ")
    for i in range(1, 5):
        d.add_paragraph(f"{i}. Материал {i}")
    d.add_paragraph("ХАРАКТЕРИСТИКА РАБОТЫ СТУДЕНТА")
    d.add_paragraph(
        "Студент добросовестно выполнял задания руководителя. " * 6
        + "Рекомендуемая оценка — отлично."
    )
    buf = BytesIO()
    d.save(buf)
    return buf.getvalue()


def statuses(rep):
    return {f.id: f.status for f in rep.findings}


def test_correct_report_is_ready():
    rep = check_report(make_report(), "r.docx")
    assert rep.to_dict()["ready"], [f for f in rep.findings if f.status == "fail"]


def test_report_errors_are_detected():
    s = statuses(
        check_report(make_report(font="Arial", left=1.0, page_numbers=False, refs=0), "r.docx")
    )
    assert s["R03"] == "fail"  # поля
    assert s["R04"] == "fail"  # шрифт
    assert s["R09"] == "fail"  # нумерация страниц
    assert s["R20"] == "fail"  # нет источников


def test_missing_section_and_size():
    rep = check_report(
        make_report(sections=["INTRODUCTION", "ABOUT COMPANY", "INDIVIDUAL TASK"], size=12),
        "r.docx",
    )
    s = statuses(rep)
    assert s["R12.4"] == "fail"  # нет заключения
    assert s["R05"] == "fail"  # кегль 12 вместо 14


def test_correct_diary_is_ready():
    rep = check_diary(make_diary(), "d.docx")
    assert rep.to_dict()["ready"], [f for f in rep.findings if f.status == "fail"]
    assert rep.facts["period"] == ["20.07.2026", "16.08.2026"]


def test_diary_errors_are_detected():
    s = statuses(check_diary(make_diary(entries=4, start="«__» ______ 2026 г."), "d.docx"))
    assert s["D15"] == "fail"  # дата начала не заполнена
    assert s["D17"] == "fail"  # мало записей
    s = statuses(check_diary(make_diary(entry_month="09"), "d.docx"))
    assert s["D18"] == "fail"  # записи вне периода практики


def test_cross_check_catches_other_student():
    report = check_report(make_report(), "r.docx")
    diary = check_diary(make_diary(), "d.docx")
    assert all(x["status"] == "pass" for x in cross_check(report, diary))
    diary.facts["student"] = "Иванова Мария"
    assert cross_check(report, diary)[0]["status"] == "fail"
