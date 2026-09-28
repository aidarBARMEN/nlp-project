import re
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from langdetect import DetectorFactory, detect_langs
from langdetect.lang_detect_exception import LangDetectException

from ingestion.models import CanonicalDocument, Channel, ParsedDocument
from ingestion.services.normalizer import content_hash, normalize

DetectorFactory.seed = 0

CATEGORIES = {
    "academic_policy": ("academic policy", "академическ", "академиялық саясат"),
    "academic_calendar": ("academic calendar", "академический календар", "күнтізбе"),
    "gpa": ("gpa",),
    "retake": ("retake", "пересдач"),
    "exams": ("exam", "экзамен", "емтихан"),
    "appeals": ("appeal", "апелляц", "аппеляц"),
    "add_drop": ("add/drop", "add-drop", "дроп"),
    "scholarships": ("scholarship", "стипенд", "шәкіртақы"),
    "grants": ("grant", "грант"),
    "payments": ("payment", "оплат", "төлем"),
    "registrar": ("registrar", "регистратор"),
    "certificates": ("certificate", "справк", "анықтама"),
    "dormitory": ("dormitory", "общежити", "obshchezhitie", "жатақхана"),
    "library": ("library", "библиотек", "кітапхана"),
    "student_life": ("student life", "student-life", "студенческая жизнь"),
    "academic_mobility": ("mobility", "мобильност", "ұтқырлық"),
    "uninet": ("uninet",),
    "contacts": ("contacts", "контакт", "байланыс"),
}


def languages(text: str) -> tuple[str | None, list[str]]:
    found: set[str] = set()
    parts = [p for p in text[:6000].splitlines() if len(p.strip()) >= 20]
    for part in parts or [text[:6000]]:
        is_kazakh = bool(re.search("[әіңғүұқөһӘІҢҒҮҰҚӨҺ]", part))
        if is_kazakh:
            found.add("kk")
        try:
            for result in detect_langs(part):
                if result.lang in {"en", "ru"} and result.prob >= 0.8 and not is_kazakh:
                    found.add(result.lang)
        except LangDetectException:
            continue
    if not found:
        try:
            combined = detect_langs(text[:6000])[0]
            if combined.lang in {"en", "ru"} and combined.prob >= 0.8:
                found.add(combined.lang)
        except LangDetectException:
            return None, []
    values = sorted(found)
    return (values[0] if len(values) == 1 else "mixed" if values else None), values


def effective_date(text: str, *, end=False) -> date | None:
    label = (
        r"effective\s+until|действует\s+до"
        if end
        else r"effective\s+(?:from|date)|вступает\s+в\s+силу\s+с|действует\s+с"
    )
    match = re.search(
        rf"(?i)(?:{label})\s*:?\s*(\d{{4}}-\d{{2}}-\d{{2}}|\d{{2}}\.\d{{2}}\.\d{{4}})",
        text,
    )
    if match:
        try:
            return datetime.strptime(match[1], "%Y-%m-%d" if "-" in match[1] else "%d.%m.%Y").date()
        except ValueError:
            return None
    return None


def extract(
    parsed: ParsedDocument,
    *,
    filename: str,
    channel: Channel,
    mime: str,
    binary_hash: str,
    doc_id: str,
    raw_path: str,
    source_url: str | None = None,
    overrides: dict[str, Any] | None = None,
) -> CanonicalDocument:
    body = "\n".join(b.text for b in parsed.blocks)
    title = normalize(parsed.title or Path(filename).stem)
    cues = f"{title}\n{filename}\n{unquote(source_url or '')}\n{body[:6000]}"
    low = cues.lower()
    tags = [key for key, words in CATEGORIES.items() if any(w in low for w in words)]
    # Calendar is more specific than the generic academic adjective.
    category = "academic_calendar" if "academic_calendar" in tags else tags[0] if tags else "other"
    year = re.search(r"\b(20\d{2})\s*[-–/]\s*(20\d{2})\b", cues)
    academic_year = f"{year[1]}-{year[2]}" if year and int(year[2]) == int(year[1]) + 1 else None
    number = re.search(r"(?:№\s*|\b)(\d{2,3}-\d{1,3}-\d{2,4})\b", cues)
    version = re.search(
        r"(?i)(?:version|версия|редакция|rev\.?|\bv)\s*[:.]?\s*(\d+(?:\.\d+)*)", cues
    )
    title_year = re.search(r"\b20\d{2}\b", title + " " + filename)
    language, detected = languages(title + "\n" + body)
    audience = next(
        (
            v
            for k, v in (
                ("бакалав", "bachelor"),
                ("bachelor", "bachelor"),
                ("магистр", "master"),
                ("master", "master"),
                ("phd", "phd"),
            )
            if k in low
        ),
        None,
    )
    family = re.sub(r"\b20\d{2}(?:\s*[-–/]\s*20\d{2})?\b", "", title.lower())
    family = re.sub(r"(?i)(?:version|версия|редакция|rev\.?|\bv)\s*\d+(?:\.\d+)*", "", family)
    family = re.sub(r"[^\w]+", " ", family).strip()
    source_type = {
        "academic_policy": "official_policy",
        "academic_calendar": "academic_calendar",
    }.get(category, "web_page" if mime == "text/html" else "unknown")
    values: dict[str, Any] = dict(
        doc_id=doc_id,
        logical_document_key=f"{family}:{language or 'unknown'}",
        title=title,
        source_type=source_type,
        source_channel=channel,
        source_url=source_url,
        original_filename=filename,
        mime_type=mime,
        language=language,
        category=category,
        section=next((b.section for b in parsed.blocks if b.section), None),
        target_audience=audience,
        academic_year=academic_year,
        document_number=number[1] if number else None,
        version=version[1] if version else academic_year or (title_year[0] if title_year else None),
        effective_from=effective_date(cues),
        effective_to=effective_date(cues, end=True),
        binary_hash=binary_hash,
        content_hash=content_hash(body),
        raw_path=raw_path,
        metadata={"topical_tags": tags, "languages": detected, "parser": parsed.metadata},
    )
    if channel == "kbtu_website":
        if not source_url or urlsplit(source_url).hostname not in {
            "kbtu.edu.kz",
            "www.kbtu.edu.kz",
        }:
            raise ValueError("Website provenance requires an official KBTU URL")
        values["trust_level"] = "official"
    allowed = {
        "title",
        "logical_document_key",
        "language",
        "category",
        "target_audience",
        "academic_year",
        "document_number",
        "version",
        "effective_from",
        "effective_to",
    }
    for key, value in (overrides or {}).items():
        if key not in allowed:
            raise ValueError(f"Unsupported metadata override: {key}")
        values[key] = value
    result = CanonicalDocument(**values)
    if (
        result.effective_from
        and result.effective_to
        and result.effective_from > result.effective_to
    ):
        raise ValueError("effective_from is later than effective_to")
    return result
