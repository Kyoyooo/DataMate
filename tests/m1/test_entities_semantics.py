"""P2 implementation tests; these do not claim held-out model accuracy."""

from __future__ import annotations

import asyncio
import json

import duckdb

from datamate.catalog import make_fake_catalog
from datamate.config import EntityConfig, RunConfig
from datamate.contracts import ModelCall, SplitContext, TemporalParams
from datamate.entities import build_entity_index, load_entity_index, save_entity_index
from datamate.semantics import attach_semantics, compile_semantics, compile_semantics_sync


class ResponseClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        return ModelCall(
            call_id=kwargs["call_id"],
            stage=kwargs["stage"],
            template_id=kwargs["template_id"],
            backend="synthetic-test",
            request_sha256="test",
            params={},
            content=json.dumps(self.payload),
            reasoning=None,
            finish_reason="stop",
            latency_ms=0,
        )


def split():
    return SplitContext(
        rulebook_text="Exclude cancelled orders.",
        rulebook_sha256="test",
        temporal=TemporalParams(),
        calendar_path=None,
    )


def enabled(**kwargs):
    return RunConfig(features={"compiled_views": True, **kwargs})


def view(name, query, **kwargs):
    return {
        "name": name,
        "purpose": "Synthetic validation example",
        "ddl": f"CREATE VIEW {name} AS {query}",
        "depends_on": ["orders"],
        "category": "revenue",
        **kwargs,
    }


def test_entity_exact_fuzzy_code_mapping_and_determinism(tmp_path):
    cat = make_fake_catalog(tmp_path, "mixed_types")
    index = build_entity_index(cat)
    config = EntityConfig(top_k=5, weak_threshold=70, strong_threshold=85)
    results = index.query("ca phe sua", config)
    best = next(c for c in results if c.column == "name")
    assert best.value == "Cà phê sữa" and best.code == "001"
    assert best.score == 100 and best.strength == "strong"
    assert index.query("ca phe sua", config) == results
    assert index.query("", config) == []
    assert index.query("cà phê sữa", config)[0].value == "Cà phê sữa"
    path = tmp_path / "entities.json"
    save_entity_index(index, path)
    assert load_entity_index(path).query("ca phe sua", config) == results


def test_disabled_compiler_never_calls_model(tmp_path):
    client = ResponseClient({})
    cat = make_fake_catalog(tmp_path)
    assert not compile_semantics_sync(cat, split(), client).views
    assert client.calls == []


def test_valid_view_exclusion_and_actual_call_logging(tmp_path):
    cat = make_fake_catalog(tmp_path)
    proposal = view(
        "v_valid",
        "SELECT * FROM orders WHERE status='Hoàn thành'",
        key_columns=["order_id"],
        exclusion_check={
            "source_table": "orders",
            "source_column": "amount",
            "view_column": "amount",
            "span": "Exclude cancelled orders.",
        },
    )
    client = ResponseClient({"views": [proposal]})
    result = asyncio.run(compile_semantics(cat, split(), client, cfg=enabled()))
    assert len(client.calls) == 1 and client.calls[0]["stage"] == "compile"
    assert result.views[0].enabled
    assert result.views[0].validation.row_count == 2
    assert result.compile_calls[0].content == json.dumps({"views": [proposal]})
    with duckdb.connect(cat.db_path, read_only=True) as connection:
        assert connection.execute("SELECT SUM(amount) FROM v_valid").fetchone()[0] == 150


def test_bad_views_are_disabled_without_modifying_source(tmp_path):
    cat = make_fake_catalog(tmp_path)
    proposals = [
        view("v_empty", "SELECT * FROM orders WHERE FALSE"),
        view("v_duplicate", "SELECT customer_id FROM orders", key_columns=["customer_id"]),
        view("v_wrong_source", "SELECT * FROM unknown"),
        {**view("v_write", "SELECT * FROM orders"), "ddl": "DROP TABLE orders"},
        view(
            "v_excess",
            "SELECT *, amount*10 AS inflated FROM orders",
            exclusion_check={
                "source_table": "orders",
                "source_column": "amount",
                "view_column": "inflated",
                "span": "Exclude cancelled orders.",
            },
        ),
    ]
    result = compile_semantics_sync(
        cat, split(), ResponseClient({"views": proposals}), cfg=enabled()
    )
    assert len(result.views) == 5 and not any(v.enabled for v in result.views)
    assert all(any(not c.passed for c in v.validation.checks) for v in result.views)
    with duckdb.connect(cat.db_path, read_only=True) as connection:
        assert connection.execute("SELECT SUM(amount) FROM orders").fetchone()[0] == 350
        assert not connection.execute(
            "SELECT table_name FROM information_schema.views WHERE table_schema='main' AND starts_with(table_name,'v_')"
        ).fetchall()


def test_category_kill_switch_and_untrusted_self_validation(tmp_path):
    cat = make_fake_catalog(tmp_path)
    proposal = view("v_disabled", "SELECT * FROM orders")
    result = compile_semantics_sync(
        cat,
        split(),
        ResponseClient({"views": [proposal]}),
        cfg=enabled(compiled_views_categories=["inventory"]),
    )
    assert not result.views[0].enabled and not result.views[0].validation.executed
    client = ResponseClient({"views": [{**proposal, "enabled": True}]})
    invalid = compile_semantics_sync(cat, split(), client, cfg=enabled())
    assert not invalid.views and invalid.warnings[0].startswith("SEMANTICS_INVALID")


def test_view_context_and_executed_view_hash_are_handed_off(tmp_path):
    import hashlib
    from datetime import date

    from datamate.contracts import Question
    from datamate.llm import ScriptedModelClient
    from datamate.runtime import answer_question

    cat = make_fake_catalog(tmp_path)
    proposal = view("v_revenue", "SELECT * FROM orders WHERE amount<200")
    annotations = compile_semantics_sync(
        cat, split(), ResponseClient({"views": [proposal]}), cfg=enabled()
    )
    cat = attach_semantics(cat, annotations)
    assert proposal["ddl"] in cat.schema_card
    client = ScriptedModelClient(
        [
            {
                "stage": "parse",
                "question": "Revenue?",
                "content": json.dumps(
                    {"expected_type": "number", "numeric_kind": "money", "time": []}
                ),
            },
            {
                "stage": "solve",
                "question": "Revenue?",
                "content": json.dumps({"sql": "SELECT SUM(amount) AS value FROM v_revenue"}),
            },
        ]
    )
    record, log = answer_question(
        Question(
            id="q",
            business_id=cat.business_id,
            question="Revenue?",
            as_of_date=date(2025, 1, 3),
            line_no=1,
        ),
        split(),
        cat,
        client,
        RunConfig(),
    )
    assert record.answer == 150
    assert log.views_used == [
        {"name": "v_revenue", "ddl_sha256": hashlib.sha256(proposal["ddl"].encode()).hexdigest()}
    ]
