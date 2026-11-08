"""Contract v1.0.0 guarantees (Lead). Expected wire shapes come from Brief §4 and rulebook §9."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from datamate import contracts
from datamate.contracts import (
    CONTRACTS_VERSION,
    ParamProvenance,
    QuestionFrame,
    SubmissionRecord,
    TemporalParams,
    TimeWindow,
    codes,
)

SRC = Path(contracts.__file__).resolve().parents[1]


def test_version_is_the_frozen_major():
    assert re.fullmatch(r"1\.\d+\.\d+", CONTRACTS_VERSION)


def test_frame_round_trips_through_json_with_each_time_kind():
    frame = QuestionFrame.model_validate({
        "expected_type": "list", "list_order": "ranked", "ranking": {"k": 3},
        "time": [
            {"span": "a", "expr": {"kind": "date", "date": "2026-03-04"}},
            {"span": "b", "expr": {"kind": "relative_period", "unit": "week", "offset": -1}},
            {"span": "c", "role": "baseline",
             "expr": {"kind": "calendar_period", "unit": "month", "index": 2}},
            {"span": "d", "expr": {"kind": "rolling", "unit": "day", "count": 7}},
        ]})
    assert QuestionFrame.model_validate_json(frame.model_dump_json()) == frame


@pytest.mark.parametrize("bad", [
    {"expected_type": "number"},  # numeric_kind required (DC-1)
    {"expected_type": "list"},  # list_order required (DC-2)
    {"expected_type": "list", "list_order": "ranked"},  # ranking required when ranked
    {"expected_type": "list", "list_order": "question_order", "ranking": {"k": 1}},
    {"expected_type": "date"},  # date_granularity required
    {"expected_type": "string", "date_granularity": "day"},
    {"expected_type": "string", "surprise": 1},  # unknown fields are rejected
])
def test_frame_invariants(bad):
    with pytest.raises(ValidationError):
        QuestionFrame.model_validate(bad)


def test_contracts_are_frozen_and_windows_ordered():
    w = TimeWindow(ref_index=0, role="primary", start=date(2026, 1, 1), end=date(2026, 1, 1),
                   granularity="day", coverage_ratio=None)
    with pytest.raises(ValidationError):
        w.end = date(2026, 1, 2)
    with pytest.raises(ValidationError):
        TimeWindow(ref_index=0, role="primary", start=date(2026, 1, 2), end=date(2026, 1, 1),
                   granularity="day", coverage_ratio=None)


def test_temporal_provenance_is_per_field():
    assert TemporalParams().uses_generic()
    names = ["week_start", "to_date_end", "rolling_includes_as_of"]
    partly = {n: ParamProvenance(source="rulebook", span="x") for n in names}
    assert TemporalParams(provenance=partly).uses_generic()  # prior_period_full still generic
    full = {**partly, "prior_period_full": ParamProvenance(source="rulebook", span="y")}
    assert not TemporalParams(provenance=full).uses_generic()


@pytest.mark.parametrize("t, answer", [
    ("string", "Sting dâu 330ml"), ("number", 48250000), ("number", Decimal("18.6")),
    ("percent", Decimal("-12.45")), ("date", "2026-08-15"), ("date", "2025-09"),
    ("boolean", True), ("list", ["Cà phê sữa"]), ("list", [3, 10]),
    ("table", {"columns": ["khach_hang", "so_tien_no"], "rows": [["Chị Lan", 3200000]]}),
])
def test_valid_wire_values(t, answer):
    assert SubmissionRecord(id="q", type=t, answer=answer).to_wire()["answer"] == answer


@pytest.mark.parametrize("t, answer", [
    ("number", "48250000"), ("number", True), ("number", None), ("percent", "12,4%"),
    ("date", "15/08/2026"), ("date", "tháng 9/2025"), ("boolean", 1), ("boolean", "có"),
    ("string", ["Sting dâu 330ml"]), ("list", "Cà phê sữa, Bạc xỉu"),
    ("table", {"columns": ["a"], "rows": [["x", 1]]}), ("table", {"columns": ["a"]}),
    ("abstain", 1), ("unanswerable", 1),
])
def test_invalid_wire_values_are_rejected(t, answer):
    with pytest.raises(ValidationError):
        SubmissionRecord(id="q", type=t, answer=answer)


def test_reason_only_on_unanswerable():
    SubmissionRecord(id="q", type="unanswerable", reason="thiếu giá vốn")
    with pytest.raises(ValidationError):
        SubmissionRecord(id="q", type="number", answer=1, reason="x")


def test_every_reason_and_warning_code_is_registered():
    registered = {v for k, v in vars(codes).items() if re.fullmatch(r"[DEW]_[A-Z_]+", k)}
    used: set[str] = set()
    for path in SRC.rglob("*.py"):
        used |= set(re.findall(r"\b[DEW]_[A-Z][A-Z_]+\b", path.read_text(encoding="utf-8")))
    assert used - registered == set()
