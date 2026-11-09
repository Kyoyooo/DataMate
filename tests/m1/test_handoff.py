"""Consumer contracts, independent fake catalogs and held-out leakage checks."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from datamate.catalog import load_catalog, make_fake_catalog, save_catalog, setup_business
from datamate.config import RunConfig
from datamate.contracts import BusinessCatalog
from datamate.eval.m1_gate import evaluate_m1_gate


def test_catalog_portable_snapshot_and_strict_boundary(tmp_path):
    cat = make_fake_catalog(tmp_path)
    file = Path(cat.db_path).parent / "business_catalog.json"
    save_catalog(cat, file)
    assert json.loads(file.read_text(encoding="utf-8"))["db_path"] == "catalog.duckdb"
    assert load_catalog(file) == cat
    row = cat.model_dump()
    row["tables"][0]["row_count"] = "3"
    with pytest.raises(ValueError):
        BusinessCatalog.model_validate(row)
    from datamate.catalog import render_schema_card
    assert "DATES 2025-01-01..2025-01-03" in render_schema_card(cat.tables, cat.data_range, cat.warnings)


def test_context_overflow_abstains_before_model_calls(tmp_path):
    from datetime import date

    from datamate.contracts import Question, SplitContext, TemporalParams
    from datamate.llm import ScriptedModelClient
    from datamate.runtime import answer_question

    class Characters:
        def encode(self, text, add_special_tokens=False):
            return list(text)

    cat = make_fake_catalog(tmp_path)
    context = SplitContext(
        rulebook_text="", rulebook_sha256="", temporal=TemporalParams(), calendar_path=None
    )
    record, log = answer_question(
        Question(
            id="q",
            business_id=cat.business_id,
            question="Amount?",
            as_of_date=date(2025, 1, 3),
            line_no=1,
        ),
        context,
        cat,
        ScriptedModelClient([]),
        RunConfig(solver={"schema_card_budget_tokens": 10}),
        tokenizer=Characters(),
    )
    assert record.type == "abstain" and log.calls == []
    assert log.decision["reason_code"] == "E_CONTEXT_OVERFLOW"


def test_schema_snapshots_match_exports():
    path = Path(__file__).resolve().parents[2] / "contracts/schemas/BusinessCatalog.json"
    assert json.loads(path.read_text(encoding="utf-8")) == BusinessCatalog.model_json_schema()


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX read-only directory enforcement is verified by Linux CI, not Windows chmod",
)
def test_wal_fixture_in_readonly_source_directory(tmp_path):
    import shutil

    root = Path(__file__).resolve().parents[1] / "fixtures/businesses/wal.sqlite"
    source = tmp_path / "source"
    source.mkdir()
    file = source / "wal.sqlite"
    shutil.copyfile(root, file)
    file.chmod(0o444)
    source.chmod(0o555)
    try:
        cat = setup_business(source, "synthetic", tmp_path / "work")
        assert cat.status == "ready", cat.warnings
        assert sorted(p.name for p in source.iterdir()) == ["wal.sqlite"]
    finally:
        source.chmod(0o755)
        file.chmod(0o644)


def test_gate_checks_business_leakage_and_exact_feature_toggle(tmp_path):
    split = tmp_path / "train"
    split.mkdir()
    questions = [{"id": "q1", "business_id": "one"}, {"id": "q2", "business_id": "two"}]
    (split / "questions.jsonl").write_text(
        "\n".join(json.dumps(q) for q in questions), encoding="utf-8"
    )
    answers = [{"id": q["id"], "type": "number", "answer": 1} for q in questions]
    (split / "answers.jsonl").write_text(
        "\n".join(json.dumps(q) for q in answers), encoding="utf-8"
    )
    before, after = tmp_path / "off.jsonl", tmp_path / "on.jsonl"
    before.write_text(
        "\n".join(json.dumps({"id": q["id"], "type": "abstain"}) for q in questions),
        encoding="utf-8",
    )
    after.write_text("\n".join(json.dumps(q) for q in answers), encoding="utf-8")
    baseline, enabled = (
        RunConfig().model_dump(mode="json"),
        RunConfig(features={"entity_linker": True}).model_dump(mode="json"),
    )
    manifest = {
        "source_role": "train",
        "off_config": baseline,
        "on_config": enabled,
        "folds": [
            {
                "held_out_business_ids": ["one"],
                "training_business_ids": ["two"],
                "fewshot_business_ids": ["two"],
                "question_ids": ["q1"],
            },
            {
                "held_out_business_ids": ["two"],
                "training_business_ids": ["one"],
                "question_ids": ["q2"],
            },
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    result = evaluate_m1_gate(split, before, after, path, "entity_linker")
    assert result["off_pa"] == 0 and result["on_pa"] == 1 and result["gate_passed"]
    manifest["folds"][0]["fewshot_business_ids"].append("one")
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="leaked"):
        evaluate_m1_gate(split, before, after, path, "entity_linker")
