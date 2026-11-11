"""M1 regression cases with independently computed expected values."""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal

import duckdb
import pytest

from datamate.catalog import (
    SchemaContextOverflow,
    catalog_artifact,
    make_fake_ingestion_catalog,
    select_schema_context,
    setup_catalog,
)
from datamate.catalog.models import IngestionCatalog as BusinessCatalog
from datamate.config import RunConfig
from datamate.ingest import (
    DataConfig,
    budget_schema_card,
    decode_source,
    infer_data_column,
    parse_numeric,
    render_catalog,
    source_fragments,
    split_blocks,
)
from datamate.lexicon import normalize_question


def test_cp1258_and_bom_dialects_preserve_vietnamese(tmp_path):
    text = "Ten,Ma\nCơm,001\n"
    assert decode_source(text.encode("cp1258"))[0] == text
    text = "Mã;Tên;Tiền\n001;Cà phê;150k\n"
    path = tmp_path / "source.csv"
    path.write_text(text, encoding="utf-8-sig")
    _, _, block, details = next(source_fragments(path, DataConfig()))
    assert block["rows"][0] == ["001", "Cà phê", "150k"]
    assert details["delimiter"] == ";"
    from datamate.ingest import read_csv

    utf16 = tmp_path / "unicode.csv"
    utf16.write_text(text, encoding="utf-16")
    assert read_csv(utf16) == read_csv(path)


def test_valid_record_that_looks_like_labels_is_preserved():
    blocks = split_blocks(
        [["Date", "Product", "Note"], ["2025-01-01", "Giá đỡ điện thoại", "Tên riêng khách"]],
        DataConfig(),
    )
    assert sum(len(b["rows"]) for b in blocks) == 1


def test_large_compound_and_month_timestamp_are_exact():
    assert parse_numeric("123456789012345678901tr23456789")[0] == Decimal(
        "123456789012345678901234567.89"
    )
    column = infer_data_column("Tháng", ["09/2025 12:30"], DataConfig())
    assert column["sql_type"] == "TIMESTAMP"
    assert column["values"][0].isoformat() == "2025-09-01T12:30:00"


def test_runtime_ingestion_ignores_unstructured_txt_and_exposes_raw(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "sales.csv").write_text(
        "Code,Date,Amount\n001,2025-01-01,150k\n002,2025-01-02,200k\n", encoding="utf-8-sig"
    )
    (source / "notes.txt").write_text("An informal note without a delimiter.", encoding="utf-8")
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}
    cat = setup_catalog(source, "opaque", tmp_path / "work")
    assert cat.status == "ready", cat.warnings
    assert BusinessCatalog.model_validate_json(cat.model_dump_json()) == cat
    assert any(w.startswith("W_DELIMITER_UNRECOGNIZED ") for w in cat.warnings)
    assert before == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}
    column = next(c for c in cat.tables[0].columns if c.name == "amount")
    assert column.raw_column == "amount__raw"
    with duckdb.connect(cat.db_path, read_only=True) as connection:
        assert connection.execute(
            "SELECT amount,amount__raw FROM sales ORDER BY code"
        ).fetchall() == [(150000, "150k"), (200000, "200k")]
    assert cat.data_range.start == date(2025, 1, 1)
    assert cat.data_range.end == date(2025, 1, 2)


def test_expiry_and_payment_deadline_are_not_activity_coverage(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "sales.csv").write_text(
        "Code,Date,Expiry,DueDate,Amount\n001,2025-01-01,2028-01-01,2026-01-01,100\n",
        encoding="utf-8",
    )
    cat = setup_catalog(source, "opaque", tmp_path / "work")
    assert cat.status == "ready"
    assert cat.data_range.end == date(2025, 1, 1)
    assert len(cat.date_columns) == 3
    assert sum(not col.included_in_data_range for col in cat.date_columns) == 2
    with duckdb.connect(cat.db_path, read_only=True) as connection:
        assert connection.execute("SELECT MAX(expiry) FROM sales").fetchone()[0] == date(2028, 1, 1)


def test_fake_catalogs_are_independent_and_queryable(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "datamate.catalog.build.build_business_database",
        lambda *a, **k: pytest.fail("Fake used real ingestion"),
    )
    for name in ("sales", "mixed_types", "missing_fields"):
        cat = make_fake_ingestion_catalog(tmp_path, name)
        assert cat.status == "ready"
        with duckdb.connect(cat.db_path, read_only=True) as connection:
            assert (
                connection.execute(f'SELECT COUNT(*) FROM "{cat.tables[0].name}"').fetchone()[0] > 0
            )
    mixed = make_fake_ingestion_catalog(tmp_path, "mixed_types")
    with duckdb.connect(mixed.db_path, read_only=True) as connection:
        assert connection.execute("SELECT price FROM products WHERE code='001'").fetchone()[
            0
        ] == Decimal("12.5")


def test_schema_card_preserves_low_cardinality_status_values(tmp_path):
    cat = make_fake_ingestion_catalog(tmp_path)
    artifact = catalog_artifact(cat)

    class Characters:
        def encode(self, text, add_special_tokens=False):
            return list(text)

    tokenizer = Characters()
    original = render_catalog(artifact)
    limited = budget_schema_card(artifact, DataConfig(schema_card_budget_tokens=10), tokenizer)
    assert limited["needs_relevant_subset"]
    assert "Hoàn thành" in limited["text"] and "Đã hủy" in limited["text"]
    assert limited["full_text"] == original
    assert (
        select_schema_context(
            cat, "amount", tokenizer, RunConfig(solver={"schema_card_budget_tokens": 8000})
        )
        == original
    )
    with pytest.raises(SchemaContextOverflow):
        select_schema_context(
            cat, "amount", tokenizer, budget_tokens=10
        )


def test_whole_token_question_expansion_preserves_codes_and_original():
    text = "  dthu của sp SP001 hnay, so với hqua? "
    assert normalize_question(text) == "doanh thu của sản phẩm SP001 hôm nay, so với hôm qua?"
    assert text == "  dthu của sp SP001 hnay, so với hqua? "
    assert normalize_question("shop_sp_001") == "shop_sp_001"
