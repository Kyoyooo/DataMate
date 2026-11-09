"""Formatter conformance against independently written wire literals."""

from pathlib import Path

import pytest
from pydantic import TypeAdapter

from datamate.config import FormattingConfig
from datamate.contracts import Decision, RankingSpec, TypedValue, dumps, loads_exact
from datamate.eval.score import score_one
from datamate.formatting import to_submission

from conftest import run_one

CASES = [loads_exact(line) for line in Path(__file__).with_name("answers.jsonl").read_text(
    encoding="utf-8").splitlines()]
VALUE = TypeAdapter(TypedValue)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_formatter_wire_golden(case):
    kind = case.get("kind", "answer")
    decision = Decision(kind=kind, reason_code="golden",
                        value=VALUE.validate_python(case["input"]) if "input" in case else None,
                        unanswerable_reason=case.get("reason"))
    ranking = RankingSpec(**case["ranking"]) if "ranking" in case else None
    actual = to_submission(case["id"], decision, ranking, FormattingConfig()).to_wire()
    expected = '{"id":"' + case["id"] + '",' + case["wire"][1:]
    assert dumps(actual) == expected, case["rule"]

    if ranking is not None:
        reversed_value = decision.value.model_copy(update={"items": list(reversed(decision.value.items))})
        repeated = decision.model_copy(update={"value": reversed_value})
        assert dumps(to_submission(case["id"], repeated, ranking, FormattingConfig()).to_wire()) == expected


def test_duckdb_decimal_keeps_all_digits_through_pipeline(cfg, split, catalog):
    text = "Giá trị tổng hợp là bao nhiêu?"
    frame = {"expected_type": "number", "numeric_kind": "measure"}
    sql = {"sql": "SELECT 123456789012345678901234567890123456.12::DECIMAL(38,2) AS value"}
    answer, _ = run_one(text, frame, sql, cfg=cfg, split=split, catalog=catalog)
    assert dumps(answer) == '{"id":"t_q1","type":"number","answer":123456789012345678901234567890123456.12}'


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_scorer_accepts_wire_golden(case):
    wire = loads_exact(case["wire"])
    reference = case.get("reference", wire)
    assert score_one(wire, reference) == case.get("score", 1), case["rule"]


@pytest.mark.parametrize("case", [case for case in CASES if "wrong" in case], ids=lambda case: case["id"])
def test_scorer_rejects_incorrect_wire(case):
    reference = case.get("reference", loads_exact(case["wire"]))
    for wrong in case["wrong"]:
        assert score_one(wrong, reference) == -1, (case["rule"], wrong)
