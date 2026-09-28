from io import BytesIO

import pytest
from openpyxl import Workbook

from ingestion.parsers import detect_mime, parse


@pytest.mark.parametrize(
    ("name", "data", "expected"),
    [
        ("rules.txt", "Students register for exams.\n\nПравила регистрации.".encode(), "Students"),
        ("rules.md", b"# Registration\nRegister for exams.\n\n## Retake\nRetake rules.", "Retake"),
        ("grades.csv", b"Grade,Points\nA,4.0\nB,3.0\n", "4.0"),
    ],
)
def test_text_formats_flow_through_pipeline(pipeline, name, data, expected):
    result = pipeline.ingest_bytes(data, filename=name, source=name, channel="manual_upload")
    assert result.status == "processed", result.error
    points = pipeline.indexer.points(result.doc_id)
    assert any(expected in point.payload["text"] for point in points)
    assert pipeline.registry.get(result.doc_id).raw_path.endswith(name[name.rfind(".") :])
    assert pipeline.verify() == []


def test_xlsx_tables_keep_sheet_and_headers(pipeline):
    book = Workbook()
    sheet = book.active
    sheet.title = "Grades"
    sheet.append(["Grade", "Points"])
    sheet.append(["A", 4.0])
    output = BytesIO()
    book.save(output)
    book.close()
    data = output.getvalue()
    parsed = parse(data, detect_mime(data, "grades.xlsx"), "grades.xlsx", "grades.xlsx")
    assert parsed.blocks[0].section == "Grades"
    assert "Grade" in parsed.blocks[0].text and parsed.blocks[0].kind == "table"
    result = pipeline.ingest_bytes(
        data, filename="grades.xlsx", source="grades.xlsx", channel="manual_upload"
    )
    assert result.status == "processed", result.error


def test_binary_file_cannot_masquerade_as_text():
    with pytest.raises(ValueError):
        detect_mime(b"invalid\x00binary", "rules.txt")
