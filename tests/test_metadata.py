from datetime import date

from ingestion.services.metadata import effective_date, languages


def test_mixed_language_detection():
    text = (
        "Студенты должны зарегистрироваться на экзамены в установленные сроки.\n"
        "Қазақстан студенттері үшін маңызды оқу ережелері мен құжаттар.\n"
        "Students must register for their examinations before the deadline."
    )
    language, detected = languages(text)
    assert language == "mixed"
    assert set(detected) == {"ru", "kk", "en"}


def test_only_explicit_effective_dates_are_extracted():
    assert effective_date("Effective from: 2026-09-01") == date(2026, 9, 1)
    assert effective_date("Действует до 31.08.2027", end=True) == date(2027, 8, 31)
    assert effective_date("Printed on 2026-09-01") is None
    assert effective_date("Effective from: 2026-99-99") is None
