"""Fixtures for warning classes discovered by training audits, without copying train answers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from openpyxl import Workbook

from datamate.catalog import setup_business
from datamate.ingest import DataConfig, decode_source, infer_data_column, source_fragments

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/businesses"


def test_committed_reader_fixtures_and_total_note_ordinals(tmp_path):
    assert next(source_fragments(FIXTURES / "cp1258.csv", DataConfig()))[2]["rows"] == [
        ["Cơm", "001"]
    ]
    assert next(source_fragments(FIXTURES / "utf8_sig.csv", DataConfig()))[2]["rows"] == [
        ["001", "Cà phê", "150k"]
    ]
    catalog = setup_business(FIXTURES, "synthetic", tmp_path)
    assert catalog.status == "ready", catalog.warnings
    codes = {warning.code for warning in catalog.warnings}
    assert {
        "W_ENCODING_DETECTED",
        "W_ENCODING_CP1258_EVIDENCE",
        "W_TOTAL_ROW_DROPPED",
        "W_NOTE_ROW_DROPPED",
    } <= codes
    assert any(
        "row=" in warning.detail
        for warning in catalog.warnings
        if warning.code == "W_TOTAL_ROW_DROPPED"
    )


def test_parse_ambiguity_and_retention_warning_classes():
    numbers = infer_data_column("Amount", ["1,234"], DataConfig())
    assert {"W_NUMERIC_AMBIGUOUS", "W_NUMERIC_RETAINED_TEXT"} <= set(numbers["warnings"])
    dates = infer_data_column("Date", ["13/01/2025", "01/13/2025"], DataConfig())
    assert {"W_DATE_AMBIGUOUS", "W_DATE_RETAINED_TEXT"} <= set(dates["warnings"])
    assumed = infer_data_column("Date", ["01/02/2025"], DataConfig())
    assert "W_DATE_ASSUMED_DMY" in assumed["warnings"]
    assert (
        "W_FLOATING_POINT_COLUMN"
        in infer_data_column("Amount", ["0.1234567"], DataConfig())["warnings"]
    )


def test_encoding_fallback_has_explicit_warning(monkeypatch):
    monkeypatch.setattr(
        "charset_normalizer.from_bytes", lambda *a, **kw: SimpleNamespace(best=lambda: None)
    )
    text, encoding, warnings = decode_source(b"\xff")
    assert text == "ÿ" and encoding == "latin-1" and warnings == ["W_ENCODING_FALLBACK"]


def test_forced_excel_fallback_preserves_native_types(tmp_path, monkeypatch):
    class BrokenCalamine:
        @classmethod
        def from_path(cls, path):
            raise ValueError("forced reader failure")

    monkeypatch.setattr("python_calamine.CalamineWorkbook", BrokenCalamine)
    book = Workbook()
    book.active.append(["Code", "Amount", "Active"])
    book.active.append(["001", 12.5, True])
    path = tmp_path / "source.xlsx"
    book.save(path)
    _, _, block, detail = next(source_fragments(path, DataConfig()))
    assert block["rows"] == [["001", 12.5, True]]
    assert detail["warnings"][0].startswith("W_READER_FALLBACK")


def test_supported_training_date_shapes_do_not_depend_on_business_id(tmp_path):
    dates = infer_data_column("NgayBan", ["1 thg 6 2025", "45658", "01/01/2025"], DataConfig())
    assert dates["sql_type"] == "DATE"
    assert dates["values"][0].isoformat() == "2025-06-01"
    short = infer_data_column("Ngày", ["1/1"], DataConfig(), source_year=2025)
    assert short["values"][0].isoformat() == "2025-01-01"
    without = infer_data_column("Ngày", ["1/1"], DataConfig())
    assert without["sql_type"] == "VARCHAR"
    assert infer_data_column("Số ngày được nợ", [30, 60], DataConfig())["sql_type"] == "BIGINT"
    assert infer_data_column("Hạn nợ (ngày)", [15, 30], DataConfig())["sql_type"] == "BIGINT"
