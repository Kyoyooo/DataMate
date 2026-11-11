"""Regression coverage for lead review: frozen boundaries and bounded real prompts."""

from __future__ import annotations

import json
from datetime import date

import pytest

from datamate.catalog import (
    load_catalog,
    make_fake_catalog,
    make_fake_ingestion_catalog,
    save_catalog,
    setup_business,
    to_runtime_catalog,
)
from datamate.catalog.context import SchemaContextOverflow, select_schema_context
from datamate.config import RunConfig
from datamate.contracts import (
    CONTRACTS_VERSION,
    BusinessCatalog,
    ColumnInfo,
    ParamProvenance,
    Question,
    QuestionFrame,
    TableInfo,
    TemporalParams,
)
from datamate.decision import pre_solve_decision
from datamate.llm import ScriptedModelClient
from datamate.run import _context_builder
from datamate.runtime import answer_question


class BytesTokenizer:
    """Deliberately strict test counter, independent of model-specific merges."""

    name = "test-utf8-bytes"

    def encode(self, text, add_special_tokens=False):
        return list(text.encode("utf-8"))


def test_runtime_catalog_uses_frozen_main_contract_and_string_warnings(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "sales.csv").write_text("Code,Amount\n001,150k\n", encoding="utf-8")
    (source / "note.txt").write_text("An unrelated note", encoding="utf-8")
    cat = setup_business(source, "opaque", tmp_path / "work")
    assert type(cat) is BusinessCatalog and cat.status == "ready"
    assert BusinessCatalog.model_validate_json(cat.model_dump_json()) == cat
    assert cat.warnings and all(type(warning) is str for warning in cat.warnings)
    assert any(warning.startswith("W_DELIMITER_UNRECOGNIZED ") for warning in cat.warnings)
    # Exercises main's warning.split() path, instead of mocking the consumer.
    frame = QuestionFrame(
        expected_type="number",
        numeric_kind="money",
        answerability={"status": "missing_field", "missing_fields": ["profit"]},
    )
    pre_solve_decision(frame, [], cat, RunConfig())
    assert CONTRACTS_VERSION.startswith("1.")
    assert "source" not in TemporalParams.model_fields
    params = TemporalParams(
        provenance={"week_start": ParamProvenance(source="rulebook", span="Monday")}
    )
    assert params.provenance["week_start"].span == "Monday"


def test_public_fake_and_persisted_catalog_use_main_contract(tmp_path):
    fake = make_fake_catalog(tmp_path)
    assert type(fake) is BusinessCatalog
    path = tmp_path / "fake_sales" / "public.json"
    save_catalog(fake, path)
    assert load_catalog(path) == fake
    from datamate.catalog import render_schema_card

    assert "TABLE orders" in render_schema_card(fake.tables, fake.data_range, fake.warnings)


def test_budgeting_retains_join_and_keys_from_audit_sidecar(tmp_path):
    rich = make_fake_ingestion_catalog(tmp_path)
    save_catalog(rich, tmp_path / "fake_sales" / "business_catalog.json")
    public = to_runtime_catalog(rich).model_copy(update={"schema_card": "X" * 370_000})
    text = select_schema_context(public, "orders customers", BytesTokenizer(), budget_tokens=8000)
    assert "KEYS" in text
    assert "JOIN orders.customer_id -> customers.customer_id" in text


def large_catalog():
    tables = []
    for index in range(35):
        columns = [
            ColumnInfo(
                name="code",
                original_name="Mã",
                sql_type="VARCHAR",
                null_count=0,
                distinct_count=1000,
            )
        ]
        columns += [
            ColumnInfo(
                name=f"field_{i}",
                original_name=f"Trường {i}",
                sql_type="BIGINT",
                null_count=0,
                distinct_count=1000,
            )
            for i in range(15)
        ]
        tables.append(
            TableInfo(
                name=f"dimension_{index:02}",
                source_file="synthetic.csv",
                row_count=1000,
                columns=columns,
            )
        )
    tables.append(
        TableInfo(
            name="sales",
            source_file="sales.csv",
            row_count=3,
            columns=[
                ColumnInfo(
                    name="amount",
                    original_name="Doanh thu",
                    sql_type="DECIMAL(38,6)",
                    null_count=0,
                    distinct_count=3,
                ),
                ColumnInfo(
                    name="status",
                    original_name="Trạng thái",
                    sql_type="VARCHAR",
                    null_count=0,
                    distinct_count=2,
                    top_values=[("Hoàn thành", 2), ("Đã hủy", 1)],
                ),
            ],
        )
    )
    return BusinessCatalog(
        business_id="opaque",
        bkey="opaque",
        db_path="unused.duckdb",
        tables=tables,
        data_range=None,
        readme_text=None,
        schema_card="X" * 370_000,
        schema_card_sha256="synthetic",
        warnings=[],
    )


def test_large_schema_has_complete_relevant_table_and_statuses_under_budget():
    cat, tok = large_catalog(), BytesTokenizer()
    text = select_schema_context(cat, "Doanh thu sales", tok, budget_tokens=8000)
    assert len(text.encode("utf-8")) <= 8000
    assert "TABLE sales " in text and "amount DECIMAL(38,6)" in text
    assert "Hoàn thành" in text and "Đã hủy" in text
    assert "SCHEMA_SUBSET" in text
    assert text == select_schema_context(cat, "Doanh thu sales", tok, budget_tokens=8000)
    assert cat.schema_card == "X" * 370_000  # full audit is never mutated
    with pytest.raises(SchemaContextOverflow):
        select_schema_context(cat, "sales", None)
    with pytest.raises(SchemaContextOverflow):
        select_schema_context(cat, "sales", tok, budget_tokens=10)


def test_actual_cli_context_hook_bounds_schema_before_parse(split):
    cat = large_catalog()
    cfg = RunConfig(solver={"tokenizer": "estimate"})
    context = _context_builder(cfg)
    captured = []

    class CaptureClient(ScriptedModelClient):
        def complete(self, **kwargs):
            captured.append(kwargs)
            return super().complete(**kwargs)

    client = CaptureClient(
        [
            {
                "stage": "parse",
                "question": "Doanh thu sales?",
                "content": json.dumps(
                    {"expected_type": "number", "numeric_kind": "money", "time": []}
                ),
            }
        ]
    )
    answer_question(
        Question(
            id="synthetic",
            business_id="opaque",
            question="Doanh thu sales?",
            as_of_date=date(2026, 3, 4),
            line_no=1,
        ),
        split,
        cat,
        client,
        cfg,
        context=context,
    )
    assert captured and captured[0]["stage"] == "parse"
    plan = context.plan(
        Question(
            id="q",
            business_id="opaque",
            question="Doanh thu sales?",
            as_of_date=date(2026, 3, 4),
            line_no=1,
        ),
        split,
        cat,
    )
    assert len(context.tok.encode(plan.catalog.schema_card)) <= cfg.solver.schema_card_budget_tokens
    assert all("X" * 1000 not in message["content"] for message in captured[0]["messages"])
