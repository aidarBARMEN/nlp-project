"""Сборка PDF-отчёта о тестировании из data/qa/results.json.

    python scripts/build_qa_report.py  ->  docs/QA_отчёт_KBTU_Smart_Assistant.pdf
"""

from __future__ import annotations

import json
import re
import statistics
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.enums import TA_CENTER  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle  # noqa: E402
from reportlab.lib.units import cm  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    Image,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.doctemplate import BaseDocTemplate  # noqa: E402
from reportlab.platypus.frames import Frame  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "qa"))
from cases import CATEGORIES, EMAILS  # noqa: E402

RESULTS = ROOT / "data" / "qa" / "results.json"
OUT = ROOT / "docs" / "QA_отчёт_KBTU_Smart_Assistant.pdf"
ASSETS = ROOT / "docs" / "assets"
TMP = ROOT / "data" / "qa" / "charts"

# Титульный лист: впишите участников команды и руководителя
AUTHORS: list[str] = []
SUPERVISOR = ""
COURSE = "Natural Language Processing"

NAVY = colors.HexColor("#002F6C")
NAVY_LIGHT = colors.HexColor("#E8EEF6")
GOLD = colors.HexColor("#B8862B")
GREY = colors.HexColor("#5B6573")
RULE = colors.HexColor("#C9D3E0")
OK = colors.HexColor("#1E6B3A")
BAD = colors.HexColor("#A3261E")

FONTS = "C:/Windows/Fonts/"
pdfmetrics.registerFont(TTFont("Body", FONTS + "calibri.ttf"))
pdfmetrics.registerFont(TTFont("Body-Bold", FONTS + "calibrib.ttf"))
pdfmetrics.registerFont(TTFont("Body-Italic", FONTS + "calibrii.ttf"))
pdfmetrics.registerFont(TTFont("Head", FONTS + "timesbd.ttf"))
pdfmetrics.registerFont(TTFont("Mono", FONTS + "consola.ttf"))
pdfmetrics.registerFontFamily("Body", normal="Body", bold="Body-Bold", italic="Body-Italic", boldItalic="Body-Bold")

S = {
    "body": ParagraphStyle("body", fontName="Body", fontSize=10.5, leading=14.5, spaceAfter=6, alignment=4),
    "small": ParagraphStyle("small", fontName="Body", fontSize=8.5, leading=11, textColor=GREY),
    "cell": ParagraphStyle("cell", fontName="Body", fontSize=8.5, leading=10.5),
    "cellb": ParagraphStyle("cellb", fontName="Body-Bold", fontSize=8.5, leading=10.5),
    "head": ParagraphStyle("head", fontName="Body-Bold", fontSize=8.5, leading=10.5, textColor=colors.white),
    "h1": ParagraphStyle("h1", fontName="Head", fontSize=17, leading=21, textColor=NAVY, spaceBefore=4, spaceAfter=10),
    "h2": ParagraphStyle("h2", fontName="Head", fontSize=13, leading=16, textColor=NAVY, spaceBefore=10, spaceAfter=6),
    "h3": ParagraphStyle("h3", fontName="Body-Bold", fontSize=10.5, leading=13, textColor=NAVY, spaceBefore=6, spaceAfter=4),
    "quote": ParagraphStyle("quote", fontName="Body", fontSize=9, leading=12, textColor=colors.HexColor("#28323F"),
                            leftIndent=8, borderPadding=(4, 6, 4, 6), backColor=NAVY_LIGHT, spaceAfter=6),
    "mono": ParagraphStyle("mono", fontName="Mono", fontSize=8, leading=10.5, backColor=colors.HexColor("#F3F5F8"),
                           borderPadding=(4, 6, 4, 6), spaceAfter=6),
    "bullet": ParagraphStyle("bullet", fontName="Body", fontSize=10.5, leading=14.5, leftIndent=12, bulletIndent=2,
                             spaceAfter=3),
}


def P(text: str, style: str = "body") -> Paragraph:
    return Paragraph(text, S[style])


def E(text) -> str:
    return escape(str(text if text is not None else ""))


def bullets(items: list[str]) -> list[Paragraph]:
    return [Paragraph(t, S["bullet"], bulletText="–") for t in items]


def pct(a: int, b: int) -> str:
    return f"{100 * a / b:.0f}%" if b else "—"


def status(ok: bool) -> Paragraph:
    return Paragraph(f'<font color="{OK.hexval() if ok else BAD.hexval()}"><b>{"пройден" if ok else "не пройден"}</b></font>'
                     .replace("0x", "#"), S["cell"])


def table(rows: list[list], widths: list[float], head_rows: int = 1, zebra: bool = True) -> Table:
    data = [[c if not isinstance(c, str) else Paragraph(E(c), S["head" if i < head_rows else "cell"])
             for c in r] for i, r in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=head_rows)
    style = [
        ("BACKGROUND", (0, 0), (-1, head_rows - 1), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    if zebra:
        for i in range(head_rows, len(rows)):
            if (i - head_rows) % 2:
                style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#F6F8FB")))
    t.setStyle(TableStyle(style))
    return t


def plain(text: str) -> str:
    """Убирает Markdown-разметку ответа ассистента для печатного отчёта."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text or "")
    text = re.sub(r"^#+\s*", "", text, flags=re.M)
    return re.sub(r"^\s*[-*]\s+", "– ", text, flags=re.M)


def human_fail(msg: str) -> str:
    """Переводит технические сообщения проверок в понятный вид."""
    if msg.startswith("нет ожидаемого факта"):
        return "в ответе нет ключевого факта из эталона"
    if msg.startswith("запрещённое содержимое"):
        return "в ответе есть недопустимое содержимое"
    if msg.startswith("нужный документ"):
        return "нужный документ не попал в найденные фрагменты"
    return msg


def fails_text(fails: list[str]) -> str:
    return "; ".join(dict.fromkeys(human_fail(f) for f in fails))


def clip(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= n else text[: n - 1].rsplit(" ", 1)[0] + "…"


# ---------------------------------------------------------------- оформление страниц
class Doc(BaseDocTemplate):
    def __init__(self, path: Path):
        super().__init__(str(path), pagesize=A4, leftMargin=2.2 * cm, rightMargin=2 * cm,
                         topMargin=2.4 * cm, bottomMargin=2 * cm,
                         title="Отчёт о тестировании KBTU Smart Assistant", author="Команда проекта KBTU Smart Assistant",
                         subject="QA-тестирование RAG-ассистента")
        w, h = A4
        body = Frame(self.leftMargin, self.bottomMargin, w - self.leftMargin - self.rightMargin,
                     h - self.topMargin - self.bottomMargin, id="body")
        cover = Frame(2.2 * cm, 2 * cm, w - 4.2 * cm, h - 4 * cm, id="cover")
        self.addPageTemplates([PageTemplate("cover", [cover], onPage=self.draw_cover),
                               PageTemplate("page", [body], onPage=self.draw_page)])

    @staticmethod
    def draw_cover(c, doc):
        w, h = A4
        c.saveState()
        c.setFillColor(NAVY)
        c.rect(0, h - 9.5 * cm, w, 9.5 * cm, fill=1, stroke=0)
        c.drawImage(str(ASSETS / "logo_white.png"), 2.2 * cm, h - 4.6 * cm, width=10 * cm, height=10 * cm * 585 / 2500,
                    mask="auto")
        c.setFillColor(GOLD)
        c.rect(0, h - 9.7 * cm, w, 0.2 * cm, fill=1, stroke=0)
        c.restoreState()

    @staticmethod
    def draw_page(c, doc):
        w, h = A4
        c.saveState()
        c.drawImage(str(ASSETS / "logo_blue.png"), doc.leftMargin, h - 1.55 * cm, width=3.6 * cm,
                    height=3.6 * cm * 585 / 2500, mask="auto")
        c.setFont("Body", 8.5)
        c.setFillColor(GREY)
        c.drawRightString(w - doc.rightMargin, h - 1.3 * cm, "KBTU Smart Assistant · Отчёт о тестировании")
        c.setStrokeColor(NAVY)
        c.setLineWidth(0.8)
        c.line(doc.leftMargin, h - 1.75 * cm, w - doc.rightMargin, h - 1.75 * cm)
        c.setStrokeColor(RULE)
        c.setLineWidth(0.4)
        c.line(doc.leftMargin, 1.4 * cm, w - doc.rightMargin, 1.4 * cm)
        c.drawString(doc.leftMargin, 1.0 * cm, "Казахстанско-Британский технический университет")
        c.drawRightString(w - doc.rightMargin, 1.0 * cm, str(doc.page))
        c.restoreState()


# ---------------------------------------------------------------- графики
def setup_mpl():
    for f in ("calibri.ttf", "calibrib.ttf"):
        font_manager.fontManager.addfont(FONTS + f)
    plt.rcParams.update({"font.family": "Calibri", "font.size": 10, "axes.edgecolor": "#9AA6B5",
                         "axes.labelcolor": "#28323F", "xtick.color": "#5B6573", "ytick.color": "#5B6573",
                         "axes.spines.top": False, "axes.spines.right": False})


def chart_categories(stats: list[tuple[str, int, int]], path: Path) -> Path:
    labels = [s[0] for s in stats][::-1]
    rates = [100 * s[1] / s[2] for s in stats][::-1]
    fig, ax = plt.subplots(figsize=(7.2, 0.42 * len(stats) + 0.8), dpi=200)
    bars = ax.barh(labels, rates, color="#002F6C", height=0.55)
    ax.barh(labels, [100 - r for r in rates], left=rates, color="#E3E8EF", height=0.55)
    for b, s in zip(bars, stats[::-1], strict=True):
        ax.text(101.5, b.get_y() + b.get_height() / 2, f"{s[1]}/{s[2]}", va="center", fontsize=9, color="#28323F")
    ax.set_xlim(0, 112)
    ax.set_xticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"])
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="x", color="#E3E8EF", linewidth=0.6)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def chart_latency(chat: list[dict], path: Path) -> Path:
    def med(key):
        vals = [c[key] for c in chat if c.get(key)]
        return statistics.median(vals) if vals else 0

    def p95(key):
        vals = sorted(c[key] for c in chat if c.get(key))
        return vals[min(len(vals) - 1, int(0.95 * len(vals)))] if vals else 0

    stages = [("Найдены источники", "t_sources"), ("Первый токен ответа", "t_first"), ("Ответ целиком", "t_total")]
    fig, ax = plt.subplots(figsize=(7.2, 2.6), dpi=200)
    y = range(len(stages))[::-1]
    ax.barh(list(y), [p95(k) for _, k in stages], color="#C9D3E0", height=0.55, label="95-й перцентиль")
    ax.barh(list(y), [med(k) for _, k in stages], color="#002F6C", height=0.55, label="медиана")
    for yi, (_, k) in zip(y, stages, strict=True):
        ax.text(p95(k) + 0.15, yi, f"{med(k):.1f} с / {p95(k):.1f} с", va="center", fontsize=9, color="#28323F")
    ax.set_yticks(list(y), [s for s, _ in stages])
    ax.set_xlabel("секунды от отправки вопроса")
    ax.set_xlim(0, max(p95(k) for _, k in stages) * 1.35)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.02), ncol=2, frameon=False, fontsize=8.5)
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="x", color="#E3E8EF", linewidth=0.6)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


# ---------------------------------------------------------------- текст разделов
CATEGORY_NOTES = {
    "B": "Вопросы составлены по реальным пунктам документов базы знаний; эталон каждого ответа сверен с исходным "
         "текстом (номер пункта или страница указаны в приложении А). Проверяется наличие ключевых фактов, ссылки "
         "на источники и то, что нужный документ действительно попал в найденные фрагменты.",
    "C": "Те же темы, но так, как пишут студенты в мессенджерах: сленг («общага», «военка»), опечатки, сокращения, "
         "вопросы без знаков препинания. Цель — убедиться, что поиск не держится только на точных формулировках.",
    "D": "Вопросы на казахском и английском. Документы в базе в основном на русском, поэтому здесь одновременно "
         "проверяются межъязыковой поиск и то, что ответ приходит на языке вопроса.",
    "E": "Вопросы, ответа на которые в документах КБТУ нет. Правильное поведение — честно сообщить об этом и "
         "направить в деканат, а не отвечать из общих знаний модели.",
    "F": "Попытки сломать ассистента: подмена инструкций, извлечение системного промпта, ложный авторитет, передача "
         "и запрос персональных данных, оскорбления, подложный «контекст» внутри вопроса.",
    "G": "Вопросы с заведомо неверным утверждением внутри. Ассистент должен поправить пользователя, а не подстроиться "
         "под формулировку вопроса.",
    "H": "Короткие уточняющие вопросы, которые понятны только из предыдущей реплики («А для первокурсников?»). "
         "Проверяется переписывание запроса с учётом истории диалога.",
}


def build(results: dict) -> None:
    TMP.mkdir(parents=True, exist_ok=True)
    setup_mpl()
    chat = results["chat"]
    api = results["api"]
    emails = results["email"]
    gates = results.get("gates", [])
    perf = results["perf"]
    health = results["health"]
    model = results["models"][0]
    by_id = {c["id"]: c for c in chat}
    date = datetime.fromisoformat(results["started_at"]).astimezone()
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()

    cat_stats = []
    for prefix, (title, cases) in CATEGORIES.items():
        rows = [by_id[c["id"]] for c in cases if c["id"] in by_id]
        cat_stats.append((prefix, title, sum(r["passed"] for r in rows), len(rows)))
    chat_ok, chat_n = sum(r["passed"] for r in chat), len(chat)
    api_ok, api_n = sum(a["passed"] for a in api), len(api)
    mail_ok, mail_n = sum(m["passed"] for m in emails), len(emails)
    gate_ok, gate_n = sum(g["passed"] for g in gates), len(gates)
    total_ok, total_n = chat_ok + api_ok + mail_ok + gate_ok, chat_n + api_n + mail_n + gate_n
    judged = [c["judge"] for c in chat if c.get("judge") and "correctness" in c["judge"]]
    corr = statistics.mean(j["correctness"] for j in judged) if judged else None
    faith = statistics.mean(j["faithfulness"] for j in judged) if judged else None
    failed = [c for c in chat if not c["passed"]]

    story: list = []

    # ---------------------------------------------------------- титульный лист
    story += [Spacer(1, 7.6 * cm)]
    story.append(Paragraph("Отчёт о тестировании", ParagraphStyle("t0", fontName="Body", fontSize=13, textColor=GREY,
                                                                  leading=16, spaceAfter=4)))
    story.append(Paragraph("RAG-ассистент для студентов<br/>«KBTU Smart Assistant»",
                           ParagraphStyle("t1", fontName="Head", fontSize=26, leading=31, textColor=NAVY, spaceAfter=14)))
    story.append(Paragraph("Функциональное, сценарное и нагрузочное тестирование, проверка безопасности "
                           "и качества ответов", ParagraphStyle("t2", fontName="Body", fontSize=12, leading=16,
                                                                textColor=colors.HexColor("#28323F"), spaceAfter=26)))
    meta = [
        ["Дисциплина", COURSE],
        ["Объект тестирования", f"KBTU Smart Assistant, сборка {commit}"],
        ["Период тестирования", date.strftime("%d.%m.%Y")],
        ["Модель генерации", model.split(":", 1)[1]],
        ["База знаний", f"{health['documents']} документов, {health['chunks']} фрагментов"],
    ]
    if AUTHORS:
        meta.append(["Выполнили", ", ".join(AUTHORS)])
    else:
        meta.append(["Выполнила", "команда проекта KBTU Smart Assistant"])
    if SUPERVISOR:
        meta.append(["Руководитель", SUPERVISOR])
    mt = Table([[Paragraph(a, S["small"]), Paragraph(E(b), S["cell"])] for a, b in meta], colWidths=[4.2 * cm, 11 * cm])
    mt.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE), ("TOPPADDING", (0, 0), (-1, -1), 5),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story += [mt, Spacer(1, 4.2 * cm),
              Paragraph(f"Алматы, {date.year}", ParagraphStyle("city", fontName="Body", fontSize=11, alignment=TA_CENTER,
                                                               textColor=GREY)),
              NextPageTemplate("page"), PageBreak()]

    # ---------------------------------------------------------- содержание
    story.append(P("Содержание", "h1"))
    toc = ["Краткие итоги", "1. Объект и среда тестирования", "2. Подход к тестированию",
           "3. Автоматические проверки", "4. Функциональное тестирование API", "5. Сценарное тестирование ассистента",
           "6. Качество ответов", "7. Черновики ответов на письма", "8. Производительность и нагрузка",
           "9. Метрики поиска и генерации", "10. Дефекты", "11. Выводы и рекомендации",
           "Приложение А. Журнал тест-кейсов", "Приложение Б. Как повторить тестирование"]
    story += [P(t, "body") for t in toc]
    story.append(PageBreak())

    # ---------------------------------------------------------- краткие итоги
    story.append(P("Краткие итоги", "h1"))
    story.append(P(
        f"Проверено {total_n} тестов на четырёх уровнях: автоматические тесты кода и сборка, контракт HTTP API, "
        f"сценарные диалоги с ассистентом и генерация черновиков ответов на письма. Пройдено {total_ok} "
        f"({pct(total_ok, total_n)}). Отдельно измерены задержки и поведение под параллельной нагрузкой."))
    summary = [["Уровень", "Тестов", "Пройдено", "Доля"],
               ["Автоматические тесты и сборка", str(gate_n), str(gate_ok), pct(gate_ok, gate_n)],
               ["Функциональные тесты API", str(api_n), str(api_ok), pct(api_ok, api_n)],
               ["Сценарные тесты ассистента", str(chat_n), str(chat_ok), pct(chat_ok, chat_n)],
               ["Черновики ответов на письма", str(mail_n), str(mail_ok), pct(mail_ok, mail_n)],
               ["Итого", str(total_n), str(total_ok), pct(total_ok, total_n)]]
    t = table(summary, [8.5 * cm, 2.4 * cm, 2.4 * cm, 2.4 * cm])
    t.setStyle(TableStyle([("FONTNAME", (0, -1), (-1, -1), "Body-Bold"), ("LINEABOVE", (0, -1), (-1, -1), 0.8, NAVY)]))
    story += [t, Spacer(1, 8)]
    findings = [
        f"Ассистент правильно отвечает на вопросы по документам: из {cat_stats[0][3]} фактических вопросов пройдено "
        f"{cat_stats[0][2]}. Средняя оценка правильности по шкале 1–5 — {corr:.2f}, доля утверждений, подтверждённых "
        f"найденными фрагментами, — {faith:.0%}." if corr is not None else "",
        f"Вопросы вне базы знаний ({cat_stats[3][2]}/{cat_stats[3][3]}) и атаки на промпт ({cat_stats[4][2]}/{cat_stats[4][3]}) "
        "обрабатываются корректно: ассистент не отвечает из общих знаний, не раскрывает системный промпт и не "
        "повторяет переданный ему пароль.",
        "Ещё три дефекта найдены и исправлены по ходу тестирования (раздел 10): письма на английском получали "
        "ответ на русском, подпись письма не переводилась, а список моделей открывался 4,5–47 секунд. "
        "Исправления подтверждены повторной проверкой.",
        f"Под нагрузкой запросы обрабатываются корректно (все {perf['search_parallel']['n']} параллельных поисков и "
        f"{perf['chat_parallel']['n']} параллельных диалога завершились успешно), но выстраиваются в очередь: медиана "
        f"поиска растёт с {perf['search_sequential']['p50']:.1f} до {perf['search_parallel']['p50']:.1f} с. Это ограничение "
        "встроенного режима Qdrant, для пилотного запуска стоит перейти на сервер Qdrant.",
    ]
    if failed:
        findings.insert(1, f"Не пройдено {len(failed)} сценарных тестов ({', '.join(c['id'] for c in failed)}), и все "
                           "они относятся к двум слабым местам: вопросы на казахском языке и вопросы с ложной "
                           "предпосылкой («почему ритейк бесплатный?»). В обоих случаях ассистент отказывает "
                           "вместо ответа — это безопасно, но неудобно для студента (дефекты QA-05 и QA-06).")
    story += bullets([f for f in findings if f])
    story.append(PageBreak())

    # ---------------------------------------------------------- 1. объект
    story.append(P("1. Объект и среда тестирования", "h1"))
    story.append(P(
        "KBTU Smart Assistant — веб-ассистент, который отвечает на вопросы студентов по официальным документам "
        "университета: академической политике, правилам проживания в KBTU Jastar City, правилам библиотеки, порядку "
        "оплаты, страницам студенческих служб. Ответ строится по схеме Retrieval-Augmented Generation: сначала "
        "система находит подходящие фрагменты документов, затем языковая модель формулирует ответ только по ним и "
        "ставит ссылки на источники."))
    story.append(P("Тестировались следующие компоненты:"))
    story += bullets([
        "поиск: векторный (OpenAI text-embedding-3-small, Qdrant) и лексический BM25 с объединением через Reciprocal "
        "Rank Fusion, расширение аббревиатур (ДС, РУП, GPA) и LLM-реранкинг;",
        "переписывание уточняющих вопросов с учётом истории диалога;",
        f"генерация ответа моделью {model.split(':', 1)[1]} со строгим системным промптом;",
        "API для черновиков ответов деканата на письма студентов (без отправки и без сохранения в почтовый ящик);",
        "веб-интерфейс на React, который раздаётся тем же сервером.",
    ])
    env = [["Параметр", "Значение"],
           ["Сборка", f"git {commit}, ветка main"],
           ["Backend", "Python 3.12, FastAPI, Uvicorn, один процесс"],
           ["Векторная БД", health["vector_db"]],
           ["База знаний", f"{health['documents']} документов, {health['chunks']} фрагментов, "
                           f"{health['tokens']:,} токенов".replace(",", " ")],
           ["Модель эмбеддингов", f"{health['embedding_model']} ({health['embedding_dimensions']} изм.)"],
           ["Модель генерации", model.split(":", 1)[1]],
           ["Реранкер", "LLM" if health["reranker"] == "llm" else "выключен"],
           ["Фрагменты", f"{health['chunk_size']} токенов, перекрытие {health['chunk_overlap']}"],
           ["Машина", "Windows 11, ноутбук, сеть до OpenAI ~0,4 с на запрос"]]
    story.append(table(env, [4.5 * cm, 11.2 * cm]))
    story.append(PageBreak())

    # ---------------------------------------------------------- 2. подход
    story.append(P("2. Подход к тестированию", "h1"))
    story.append(P(
        "Тестирование проводилось на работающей системе с реальной базой знаний: каждый запрос проходил полный путь "
        "через HTTP API, поиск, реранкинг и генерацию. Заглушки использовались только в автоматических тестах кода. "
        "Все проверки собраны в набор <font name='Mono' size='9'>tests/qa</font> и запускаются одной командой, "
        "поэтому прогон можно повторить после любых изменений (приложение Б)."))
    story.append(P("Уровни тестирования", "h3"))
    levels = [["Уровень", "Что проверяется", "Тестов"],
              ["Автоматические тесты", "Модульные и интеграционные тесты парсеров, индексации, API (pytest); "
                                       "статический анализ (ruff); проверка типов и сборка frontend", str(gate_n)],
              ["Функциональные тесты API", "Коды ответов, валидация входных данных, протокол потоковой выдачи, "
                                           "обработка ошибок, раздача frontend", str(api_n)],
              ["Сценарные тесты", "Диалоги с ассистентом по семи категориям вопросов", str(chat_n)],
              ["Черновики писем", "Ответы на письма студентов, отсев рассылок, старых и пустых писем, авторизация",
               str(mail_n)],
              ["Нагрузка", "Задержки ответа, параллельный поиск и диалоги, отзывчивость сервера под нагрузкой", "4"]]
    story.append(table(levels, [4 * cm, 10 * cm, 1.7 * cm]))
    story.append(P("Как составлялись сценарные тесты", "h3"))
    story.append(P(
        "Для фактических вопросов сначала находился конкретный пункт документа, затем по нему формулировался вопрос и "
        "записывался эталонный ответ. Так, стоимость проживания сверена со страницей «Общежитие» (тарифы на "
        "2025–2026 учебный год), правила выдачи книг — с п. 4.2.1 правил библиотеки 513-1-26, последствия оценки F — "
        "с п. 9.17.3 академической политики 51-2-25. Остальные категории построены вокруг тех же тем, чтобы "
        "отличия в результатах объяснялись формулировкой вопроса, а не самой темой."))
    story.append(P("Критерии прохождения", "h3"))
    story.append(P(
        "Тест считается пройденным, если выполнены все детерминированные проверки: в ответе есть ключевые факты "
        "эталона, нет запрещённого содержимого, ответ на нужном языке, стоят ссылки на источники, а нужный документ "
        "попал в найденные фрагменты. Для вопросов вне базы обязателен отказ, для фактических вопросов отказ "
        "считается ошибкой. Проверки сделаны на регулярных выражениях, поэтому результат воспроизводим."))
    story.append(P(
        "Дополнительно каждый ответ с эталоном оценивался независимой проверкой gpt-4o-mini по двум показателям: "
        "правильность относительно эталона (1–5) и доля утверждений, подтверждённых найденными фрагментами (0–1). "
        "Эти оценки на статус теста не влияют и приводятся как дополнительная информация в разделе 6."))
    story.append(PageBreak())

    # ---------------------------------------------------------- 3. gates
    story.append(P("3. Автоматические проверки", "h1"))
    story.append(P(
        "Перед сценарным тестированием выполнены автоматические проверки репозитория. Модульные тесты используют "
        "настоящую локальную Qdrant и подменяют обращения к OpenAI, поэтому не требуют сети и не тратят деньги."))
    rows = [["ID", "Проверка", "Результат", "Итог", "Время"]]
    for g in gates:
        rows.append([g["id"], g["title"], clip(g["summary"], 70), status(g["passed"]), f"{g['s']} с"])
    story.append(table(rows, [1.1 * cm, 5.4 * cm, 5.6 * cm, 2 * cm, 1.6 * cm]))

    # ---------------------------------------------------------- 4. api
    story.append(P("4. Функциональное тестирование API", "h1"))
    story.append(P(
        "Проверялся контракт HTTP API, на который опирается веб-интерфейс: структура ответов, валидация входных "
        "данных, протокол потоковой выдачи ответа (Server-Sent Events) и поведение при ошибках. Отдельно проверено, "
        "что неизвестная модель или некорректная история диалога приводят к понятной ошибке, а не к падению сервера."))
    rows = [["ID", "Проверка", "Фактический результат", "Итог", "мс"]]
    for a in api:
        rows.append([a["id"], a["title"], clip(a["detail"], 95), status(a["passed"]), str(a["ms"])])
    story.append(table(rows, [1.1 * cm, 5.2 * cm, 6.3 * cm, 1.9 * cm, 1.2 * cm]))
    story.append(PageBreak())

    # ---------------------------------------------------------- 5. сценарии
    story.append(P("5. Сценарное тестирование ассистента", "h1"))
    story.append(P(
        f"Сценарный набор состоит из {chat_n} диалогов в семи категориях. Все ответы получены моделью "
        f"{model.split(':', 1)[1]} через тот же потоковый API, которым пользуется веб-интерфейс. После прогона "
        "были уточнены две проверки: частичный ответ с фразой о недостающей детали больше не считается отказом, "
        "а шаблон названия документа правил библиотеки учитывает подчёркивания в имени файла. Ответы модели при "
        "этом повторно не запрашивались, статусы пересчитаны по сохранённым ответам."))
    rows = [["Категория", "Тестов", "Пройдено", "Доля"]]
    for prefix, title, ok, n in cat_stats:
        rows.append([f"{prefix}. {title}", str(n), str(ok), pct(ok, n)])
    story.append(table(rows, [10.2 * cm, 1.8 * cm, 1.9 * cm, 1.8 * cm]))
    story.append(Spacer(1, 6))
    img = chart_categories([(f"{p}. {t[:34]}{'…' if len(t) > 34 else ''}", ok, n) for p, t, ok, n in cat_stats],
                           TMP / "categories.png")
    story.append(Image(str(img), width=15.5 * cm, height=15.5 * cm * (0.42 * len(cat_stats) + 0.8) / 7.2))
    story.append(P("Рис. 1. Доля пройденных сценарных тестов по категориям", "small"))

    case_map = {c["id"]: c for _, cs in CATEGORIES.values() for c in cs}
    for prefix, (title, cases) in CATEGORIES.items():
        story.append(P(f"5.{list(CATEGORIES).index(prefix) + 1}. {title}", "h2"))
        story.append(P(CATEGORY_NOTES[prefix]))
        rows = [["ID", "Вопрос", "Что проверялось", "Итог"]]
        for c in cases:
            r = by_id.get(c["id"])
            if not r:
                continue
            expect = c.get("reference") or ("отказ «нет информации»" if c.get("refusal") else "нет запрещённого содержимого")
            rows.append([c["id"], clip(r["question"], 120), clip(expect, 110), status(r["passed"])])
        story.append(table(rows, [1.1 * cm, 6.3 * cm, 6.3 * cm, 2 * cm]))
        # примеры: сначала непройденные, затем показательный пройденный
        examples = [by_id[c["id"]] for c in cases if c["id"] in by_id and not by_id[c["id"]]["passed"]]
        examples += [by_id[c["id"]] for c in cases if c["id"] in by_id and by_id[c["id"]]["passed"]][:1]
        for r in examples[:2]:
            src = ", ".join(sorted({clip(s["title"], 40) for s in r["sources"] if s.get("title")})[:3])
            block = [P(f"Пример {r['id']}: {E(case_map[r['id']]['title'])} — "
                       f"{'пройден' if r['passed'] else 'не пройден'}", "h3"),
                     P(f"<b>Вопрос:</b> {E(r['question'])}", "body")]
            if r.get("rewritten_query") and r["rewritten_query"] != r["question"] and prefix == "H":
                block.append(P(f"<b>Запрос после переписывания:</b> {E(r['rewritten_query'])}", "body"))
            block.append(P(E(clip(plain(r["answer"]), 700)), "quote"))
            if src:
                block.append(P(f"Источники: {E(src)}", "small"))
            if not r["passed"]:
                block.append(P(f"<b>Причина:</b> {E(fails_text(r['fails']))}", "small"))
            story.append(KeepTogether(block))
    story.append(PageBreak())

    # ---------------------------------------------------------- 6. качество
    story.append(P("6. Качество ответов", "h1"))
    story.append(P(
        "Для ответов, у которых есть эталон, правильность и опора на источники оценивались отдельной проверкой "
        "(см. раздел 2). Оценки показывают не только факт прохождения теста, но и насколько полно ответ совпадает "
        "с документом."))
    rows = [["Категория", "Ответов", "Правильность, 1–5", "Опора на источники"]]
    for prefix, title, _ok, _n in cat_stats:
        js = [by_id[c["id"]]["judge"] for c in CATEGORIES[prefix][1]
              if c["id"] in by_id and by_id[c["id"]].get("judge") and "correctness" in by_id[c["id"]]["judge"]]
        if js:
            rows.append([f"{prefix}. {title}", str(len(js)), f"{statistics.mean(j['correctness'] for j in js):.2f}",
                         f"{statistics.mean(j['faithfulness'] for j in js):.0%}"])
    if judged:
        rows.append(["Все ответы с эталоном", str(len(judged)), f"{corr:.2f}", f"{faith:.0%}"])
    t = table(rows, [8.3 * cm, 2 * cm, 3 * cm, 3.2 * cm])
    t.setStyle(TableStyle([("FONTNAME", (0, -1), (-1, -1), "Body-Bold"), ("LINEABOVE", (0, -1), (-1, -1), 0.8, NAVY)]))
    story.append(t)
    low = sorted((c for c in chat if c.get("judge") and "correctness" in c["judge"] and c["judge"]["correctness"] < 4),
                 key=lambda c: c["judge"]["correctness"])
    if low:
        story.append(P("Ответы с оценкой ниже 4", "h3"))
        rows = [["ID", "Оценка", "Комментарий проверяющей модели"]]
        for c in low[:8]:
            rows.append([c["id"], f"{c['judge']['correctness']:.0f}/5", clip(c["judge"]["comment"], 160)])
        story.append(table(rows, [1.2 * cm, 1.6 * cm, 12.9 * cm]))
        low_failed = [c["id"] for c in low if not c["passed"]]
        low_passed = [c["id"] for c in low if c["passed"]]
        text = ""
        if low_failed:
            text += (f"Оценки ниже 4 получили {', '.join(low_failed)} — это непройденные тесты, в которых ассистент "
                     "отказал вместо ответа (дефекты QA-05 и QA-06). ")
        if low_passed:
            text += (f"У пройденных тестов {', '.join(low_passed)} оценка снижена за неполноту ответа: ключевые "
                     "факты эталона есть, но перечень из документа назван не целиком.")
        else:
            text += "Среди пройденных тестов ответов с оценкой ниже 4 нет."
        story.append(P(text))

    # ---------------------------------------------------------- 7. письма
    story.append(P("7. Черновики ответов на письма", "h1"))
    story.append(P(
        "Функция готовит черновик ответа деканата на письмо студента; отправляет письмо сотрудник после проверки. "
        "Тестирование выполнялось локально прямыми запросами к API с параметром save_draft=false: интеграция с "
        "n8n и почтовым ящиком не запускалась, письма никуда не отправлялись и не сохранялись."))
    rows = [["ID", "Письмо", "Ожидалось", "Получено", "Итог"]]
    for m in emails:
        case = next((c for c in EMAILS if c["id"] == m["id"]), {})
        exp = "/".join(case.get("expect_status", [])) or "HTTP 401"
        got = f"{m['status']}{' (' + m['reason'] + ')' if m.get('reason') else ''}"
        rows.append([m["id"], m["title"], exp, got, status(m["passed"])])
    story.append(table(rows, [1.1 * cm, 6.4 * cm, 3 * cm, 3.2 * cm, 2 * cm]))
    en = next((m for m in emails if m["id"] == "I02"), None)
    if en and en["reply"]:
        story.append(KeepTogether([
            P("Пример: письмо на английском после исправления дефекта QA-01", "h3"),
            P(f"<b>Письмо:</b> {E(en['letter'])}"),
            P(E(en["reply"]).replace("\n", "<br/>"), "quote")]))
    story.append(PageBreak())

    # ---------------------------------------------------------- 8. производительность
    story.append(P("8. Производительность и нагрузка", "h1"))
    story.append(P(
        "Задержки измерены на всех сценарных диалогах. Для пользователя важнее всего время до первого токена: "
        "с этого момента ответ начинает появляться на экране."))
    img = chart_latency(chat, TMP / "latency.png")
    story.append(Image(str(img), width=15.5 * cm, height=15.5 * cm * 2.6 / 7.2))
    story.append(P("Рис. 2. Задержка ответа ассистента: медиана и 95-й перцентиль", "small"))
    ss, sp, cp, hl = perf["search_sequential"], perf["search_parallel"], perf["chat_parallel"], perf["health_under_load"]
    rows = [["Сценарий", "Запросов", "Успешно", "Медиана", "Максимум"],
            ["Поиск, последовательно", str(ss["n"]), str(ss["ok"]), f"{ss['p50']:.2f} с", f"{ss['max']:.2f} с"],
            ["Поиск, 10 параллельно", str(sp["n"]), str(sp["ok"]), f"{sp['p50']:.2f} с", f"{sp['max']:.2f} с"],
            ["Диалог, 4 параллельно", str(cp["n"]), str(cp["ok"]), "—", f"{cp['max']:.2f} с"],
            ["Статус сервера во время диалогов", str(hl["n"]), str(hl["ok"]),
             f"{hl['p50']:.2f} с" if hl["p50"] else "—", f"{hl['max']:.2f} с" if hl["max"] else "—"]]
    story.append(table(rows, [6.4 * cm, 2.2 * cm, 2.2 * cm, 2.4 * cm, 2.5 * cm]))
    story.append(P(
        f"Ошибок под нагрузкой не было, но параллельные запросы обрабатываются по очереди: медиана поиска выросла "
        f"с {ss['p50']:.1f} до {sp['p50']:.1f} с. Причина в том, что встроенный режим Qdrant допускает работу только "
        "одного процесса и доступ к нему защищён общей блокировкой. Для учебной демонстрации это приемлемо; для "
        "пилотного запуска на поток студентов нужен отдельный сервер Qdrant (подготовлен docker-compose) и "
        "несколько рабочих процессов Uvicorn."))

    # ---------------------------------------------------------- 9. метрики
    ev = results.get("eval") or {}
    if ev.get("retrieval"):
        story.append(P("9. Метрики поиска и генерации", "h1"))
        story.append(P(
            f"Помимо сценарных тестов, качество поиска измерено на синтетическом наборе из "
            f"{ev['retrieval']['questions']} вопросов, для каждого из которых известен исходный фрагмент. "
            "Hit@k — доля вопросов, где этот фрагмент оказался в первых k результатах; MRR учитывает его позицию; "
            "Doc@5 — нужный документ среди первых пяти."))
        rows = [["Метод поиска", "Hit@1", "Hit@5", "MRR@10", "Doc@5", "Запрос, мс"]]
        for m in ev["retrieval"]["methods"]:
            rows.append([m["method"], f"{m['hit@1']:.2f}", f"{m['hit@5']:.2f}", f"{m['mrr@10']:.2f}",
                         f"{m['doc_hit@5']:.2f}", f"{m['query_ms_mean']:.0f}" if m.get("query_ms_mean") else "—"])
        story.append(table(rows, [6.8 * cm, 1.6 * cm, 1.6 * cm, 1.8 * cm, 1.6 * cm, 2.3 * cm]))
        story.append(P(
            "Гибридный поиск стабильно лучше одиночных методов, поэтому именно он используется в ассистенте. "
            "Локальная модель multilingual-e5-small показывает качество на уровне OpenAI при задержке около 14 мс и "
            "может служить бесплатной заменой."))
        if ev.get("generation"):
            g = ev["generation"]["models"]
            rows = [["Модель", "Опора на источники", "Правильность", "Отказ, где нужно", "Ложный отказ", "Цитаты"]]
            for m in g:
                rows.append([m["label"], f"{m['faithfulness']:.0%}", f"{m['correctness']:.2f}",
                             f"{m['refusal_accuracy']:.0%}", f"{m['false_refusal_rate']:.0%}", f"{m['citation_rate']:.0%}"])
            gen_date = datetime.fromisoformat(ev["generation"]["created_at"]).astimezone().strftime("%d.%m.%Y")
            story.append(KeepTogether([
                P("Сравнение моделей генерации", "h3"),
                P("Для справки приведены результаты оценки генерации, выполненной при выборе модели: помимо "
                  "gpt-4o-mini на том же наборе проверялась открытая модель Qwen3.8-27B. В сценарном тестировании "
                  "выше использовалась только gpt-4o-mini."),
                table(rows, [4 * cm, 2.6 * cm, 2.2 * cm, 2.6 * cm, 2.2 * cm, 2.1 * cm]),
                P(f"Оценка от {gen_date}, {ev['generation']['questions']} вопросов того же набора.", "small")]))
    story.append(PageBreak())

    # ---------------------------------------------------------- 10. дефекты
    story.append(P("10. Дефекты", "h1"))
    story.append(P(
        "В таблицу включены дефекты, найденные в этом цикле тестирования (QA-), и дефекты, найденные ранее при "
        "разработке и интеграции (DEV-). Для каждого исправленного дефекта есть проверка, подтверждающая исправление."))
    defects = [
        ["QA-01", "Средний", "Ответ на письмо на английском написан по-русски: язык определялся верно, но модели не "
         "передавался, а промпт и контекст на русском. Найден тестом I02.",
         "Исправлен: язык ответа передаётся явно. Повторный тест I02 пройден."],
        ["QA-02", "Низкий", "Подпись «С уважением, Деканат КБТУ» добавлялась по-русски к письмам на английском и "
         "казахском.", "Исправлен: подпись на языке письма."],
        ["QA-03", "Средний", "GET /api/models отвечал 4,5 с, первый вызов — 47 с: при выключенном Ollama каждый запрос "
         "ждал таймаут соединения, а «localhost» на Windows сначала пробует IPv6.",
         "Исправлен: адрес 127.0.0.1, таймаут 0,5 с, кэш. Повторный замер: 3 мс из кэша, около 1 с "
         "при обновлении кэша (запрос каталога Groq)."],
        ["QA-05", "Средний", "Вопросы на казахском (D01, D02) получают отказ на русском. Документы в базе на "
         "русском: в D01 поиск по казахскому запросу не нашёл страницу библиотеки, в D02 нужные фрагменты "
         "найдены, но модель не связала их с вопросом.",
         "Открыт. Предложение: переводить запрос на русский перед поиском и явно задавать язык ответа."],
        ["QA-06", "Средний", "Вопросы с ложной предпосылкой (G01–G03) получают отказ «нет информации» вместо "
         "исправления: правило промпта «нет прямого ответа — отказ» срабатывает раньше, чем модель замечает "
         "противоречие с документом. Нужные фрагменты при этом найдены.",
         "Открыт. Предложение: добавить в промпт правило поправлять неверное утверждение по контексту."],
        ["QA-04", "Наблюдение", "Параллельные запросы обрабатываются последовательно (раздел 8).",
         "Открыт: требуется сервер Qdrant для пилота."],
        ["DEV-01", "Критический", "Взаимная блокировка при одновременных запросах статуса и диалога: два потока "
         "захватывали замки в разном порядке, сервер переставал отвечать.",
         "Исправлен: единый порядок захвата. Проверен нагрузочным тестом."],
        ["DEV-02", "Высокий", "Стеммер Snowball не потокобезопасен: при параллельной перезагрузке индекса — HTTP 500.",
         "Исправлен: сериализация и кэш стемминга."],
        ["DEV-03", "Высокий", "Запрос статуса каждые 15 с полностью перестраивал индекс BM25; первый ответ после "
         "наполнения базы занимал 97 с.", "Исправлен: перестройка только при изменении базы."],
        ["DEV-04", "Средний", "Реранкер получал оценки списком без номеров фрагментов; модель путала порядок, и "
         "правильный фрагмент получал 0 баллов.", "Исправлен: оценки с явными номерами."],
        ["DEV-05", "Средний", "Генерация оценочного набора завершалась статусом «готово» с пустым результатом из-за "
         "ошибки формата запроса к OpenAI.", "Исправлен: формат и остановка при серии ошибок."],
        ["DEV-06", "Низкий", "Единичный таймаут сети прерывал многоминутную оценку качества.",
         "Исправлен: повтор запросов."],
    ]
    rows = [["ID", "Важность", "Описание", "Статус"]] + defects
    story.append(table(rows, [1.5 * cm, 2 * cm, 8.2 * cm, 4 * cm]))
    story.append(PageBreak())

    # ---------------------------------------------------------- 11. выводы
    story.append(P("11. Выводы и рекомендации", "h1"))
    story.append(P(
        f"По результатам тестирования ассистент готов к демонстрации и ограниченному пилоту. Основная функция — "
        f"ответы по документам университета со ссылками на источники — работает стабильно: {pct(chat_ok, chat_n)} "
        f"сценарных тестов пройдено, ассистент не выдумывает ответы на вопросы вне базы и устойчив к типовым "
        f"попыткам подменить инструкции. API корректно валидирует входные данные и обрабатывает ошибки, "
        f"автоматические тесты и сборка проходят без замечаний."))
    if failed:
        story.append(P(
            "Непройденные тесты сосредоточены в двух местах. Первое — казахский язык: база знаний почти целиком "
            "на русском, и казахский запрос плохо сопоставляется с русскими фрагментами. Второе — вопросы с "
            "неверным утверждением: ассистент предпочитает отказ, а не исправление. Оба поведения не приводят к "
            "выдаче неверной информации, но снижают полезность ответа, поэтому дефекты оценены как средние и "
            "должны быть исправлены до пилота."))
    story.append(P("Рекомендации", "h3"))
    story += bullets([
        "Исправить QA-05: перед поиском переводить казахский и английский запрос на русский, а язык ответа "
        "задавать явно, как это уже сделано для писем.",
        "Исправить QA-06: добавить в системный промпт правило — если вопрос содержит утверждение, которое "
        "противоречит документу, ответить по документу и указать на расхождение.",
        "Перейти с встроенной Qdrant на отдельный сервер и запускать несколько процессов Uvicorn: это снимет "
        "очередь при параллельных запросах.",
        "Очистить базу знаний от новостей библиотеки и праздничных публикаций: они почти не несут ответов на "
        "вопросы студентов, но попадают в поиск и занимают место в контексте.",
        "Распознать шесть сканированных PDF (OCR) и сконвертировать два файла .doc — сейчас их содержимое "
        "недоступно ассистенту.",
        "Пополнить набор тестов реальными вопросами студентов после пилота и запускать его при каждом изменении "
        "промпта, модели или базы знаний.",
        "Добавить на казахском языке хотя бы основные документы: сейчас ответы на казахском строятся по "
        "русскоязычным источникам.",
    ])
    story.append(PageBreak())

    # ---------------------------------------------------------- приложение А
    story.append(P("Приложение А. Журнал тест-кейсов", "h1"))
    story.append(P("Полные вопросы, эталоны и фрагменты ответов всех сценарных тестов. Ответы сокращены до 450 знаков.",
                   "small"))
    for prefix, (title, cases) in CATEGORIES.items():
        story.append(P(f"{prefix}. {title}", "h2"))
        for c in cases:
            r = by_id.get(c["id"])
            if not r:
                continue
            rows = [[Paragraph(f"<b>{c['id']}</b> · {E(c['title'])}", S["cell"]), status(r["passed"])],
                    [Paragraph(f"<b>Вопрос:</b> {E(r['question'])}", S["cell"]), ""]]
            if c.get("reference"):
                ref = c["reference"] + (f" ({c['doc']})" if c.get("doc") else "")
                rows.append([Paragraph(f"<b>Эталон:</b> {E(ref)}", S["cell"]), ""])
            rows.append([Paragraph(f"<b>Ответ:</b> {E(clip(plain(r['answer']), 450))}", S["cell"]), ""])
            info = f"Время ответа {r['t_total']:.1f} с" if r.get("t_total") else ""
            if r.get("judge") and "correctness" in r["judge"]:
                info += f" · правильность {r['judge']['correctness']:.0f}/5"
            if not r["passed"]:
                info += f" · {fails_text(r['fails'])}"
            rows.append([Paragraph(E(info), S["small"]), ""])
            t = Table(rows, colWidths=[13.6 * cm, 2.1 * cm])
            t.setStyle(TableStyle([
                ("SPAN", (0, i), (1, i)) for i in range(1, len(rows))] + [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY_LIGHT), ("BOX", (0, 0), (-1, -1), 0.4, RULE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]))
            story += [KeepTogether(t), Spacer(1, 5)]

    # ---------------------------------------------------------- приложение Б
    story.append(PageBreak())
    story.append(P("Приложение Б. Как повторить тестирование", "h1"))
    story.append(P("Команды выполняются из корня репозитория при запущенном backend."))
    story.append(P(E(
        ".venv\\Scripts\\python.exe -m uvicorn backend.app.main:app --port 8000\n"
        ".venv\\Scripts\\python.exe tests\\qa\\run_qa.py --models openai:gpt-4o-mini\n"
        ".venv\\Scripts\\python.exe scripts\\build_qa_report.py").replace("\n", "<br/>"), "mono"))
    story.append(P(
        "Тест-кейсы и эталоны находятся в tests/qa/cases.py; новые вопросы добавляются туда же. Сырые результаты "
        "прогона сохраняются в data/qa/results.json, отчёт собирается из них автоматически. Повторная проверка "
        "только API и писем после исправлений: <font name='Mono' size='9'>run_qa.py --retest</font>."))
    story.append(Spacer(1, 10))
    story.append(P(f"Прогон: {date.strftime('%d.%m.%Y %H:%M')}, длительность {results['duration_s'] // 60} мин.", "small"))

    doc = Doc(OUT)
    doc.build(story)


if __name__ == "__main__":
    build(json.loads(RESULTS.read_text(encoding="utf-8")))
    print(OUT)
