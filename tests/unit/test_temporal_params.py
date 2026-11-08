from __future__ import annotations

import json

import pytest

from datamate.contracts import TemporalParams
from datamate.llm import ScriptedModelClient
from datamate.rules import load_split
from datamate.rules.temporal_params import temporal_candidate_schema, validate_temporal_params

from conftest import REPO, SPLIT

WEEK = "Tuần bắt đầu Chủ nhật"
END = "Tuần này và tháng này tính đến hết ngày hôm qua"
ROLLING = "N ngày gần nhất không tính hôm nay"


def claim(value, span):
    return {"value": value, "span": span}


def test_fixture_rulebook_selectively_verifies_fields():
    rulebook = (SPLIT / "rulebook.md").read_text(encoding="utf-8")
    candidates = {
        "week_start": claim("mon", "Tuần bắt đầu thứ Hai"),
        "to_date_end": claim("as_of", "**Tuần này**, **tháng này**: đến hết hôm nay"),
        "rolling_includes_as_of": claim(True, "**N ngày gần nhất**: N ngày liền nhau, ngày cuối là hôm nay"),
        "prior_period_full": claim(True, "**Tuần rồi**: cả tuần liền trước"),
    }
    params, diagnostics = validate_temporal_params(rulebook, json.dumps(candidates))
    assert params.uses_generic()
    assert {field: prov.span for field, prov in params.provenance.items() if prov.source == "rulebook"} == {
        field: candidate["span"] for field, candidate in candidates.items()
    }
    assert diagnostics == {"year_omitted_policy": "missing_field", "same_period_alignment": "missing_field"}


def test_alternate_fixture_and_split_specific_evidence():
    rulebook = (REPO / "tests/fixtures/rulebooks/temporal_alt/rulebook.md").read_text(encoding="utf-8")
    content = json.dumps({"week_start": claim("sun", WEEK), "to_date_end": claim("day_before_as_of", END),
                          "rolling_includes_as_of": claim(False, ROLLING)})
    params, diagnostics = validate_temporal_params(rulebook, content)
    assert (params.week_start, params.to_date_end, params.rolling_includes_as_of) == ("sun", "day_before_as_of", False)
    assert params.provenance["rolling_includes_as_of"].source == "rulebook"
    assert "prior_period_full" not in params.provenance
    assert (params, diagnostics) == validate_temporal_params(rulebook, content)
    other = (SPLIT / "rulebook.md").read_text(encoding="utf-8")
    assert validate_temporal_params(other, content)[0] == TemporalParams()


def test_explicit_valid_alignment_and_fixed_policy():
    rules = {
        "week_start": claim("sun", "The week starts on Sunday"),
        "to_date_end": claim("day_before_as_of", "To-date periods end yesterday"),
        "rolling_includes_as_of": claim(False, "Rolling periods exclude today"),
        "prior_period_full": claim(True, "Prior periods use the full preceding calendar period"),
        "same_period_alignment": claim("elapsed_days", "Cùng kỳ năm ngoái giữ nguyên số ngày"),
        "year_omitted_policy": claim("most_recent_not_after_as_of", "Dates without a year use the latest occurrence on or before as_of_date"),
    }
    rulebook = "\n".join(f"- {candidate['span']}." for candidate in rules.values())
    params, diagnostics = validate_temporal_params(rulebook, json.dumps(rules))
    assert diagnostics == {} and not params.uses_generic()
    assert params.same_period_alignment == "elapsed_days"
    assert all(p.source == "rulebook" for p in params.provenance.values())
    assert set(temporal_candidate_schema()["required"]) == set(params.provenance)


@pytest.mark.parametrize("bad, reason", [
    (None, "invalid_candidate"),
    (["sun", WEEK], "invalid_candidate"),
    ({"value": "sun"}, "invalid_candidate"),
    (claim(None, WEEK), "missing_value"),
    (claim("tue", WEEK), "invalid_value"),
    (claim(7, WEEK), "invalid_value"),
    (claim("sun", "Bắt đầu tuần từ Chủ nhật"), "unverified_span"),
    (claim("sun", "Chủ nhật"), "insufficient_evidence"),
    (claim("mon", WEEK), "contradictory_rulebook"),
])
def test_invalid_claim_falls_back_without_losing_independent_fields(bad, reason):
    rulebook = f"{WEEK}. {ROLLING}."
    params, diagnostics = validate_temporal_params(rulebook, json.dumps({
        "week_start": bad, "rolling_includes_as_of": claim(False, ROLLING),
    }))
    assert params.week_start == "mon" and "week_start" not in params.provenance
    assert params.rolling_includes_as_of is False
    assert params.provenance["rolling_includes_as_of"].source == "rulebook"
    assert diagnostics["week_start"] == reason


@pytest.mark.parametrize("rulebook, reason", [
    (f"{WEEK}. Tuần bắt đầu thứ Hai.", "contradictory_rulebook"),
    (f"{WEEK}. Tuần không bắt đầu Chủ nhật.", "contradictory_rulebook"),
    (f"{WEEK}. Tuần bắt đầu thứ Ba.", "contradictory_rulebook"),
    (f"Nếu dùng lịch khác, {WEEK}.", "insufficient_evidence"),
    (f"Ví dụ: {WEEK}.", "insufficient_evidence"),
    (f"## Ví dụ\n{WEEK}.", "insufficient_evidence"),
    (f"> {WEEK}.", "insufficient_evidence"),
    (f"```text\n{WEEK}.\n```", "insufficient_evidence"),
])
def test_quoted_text_alone_is_not_sufficient(rulebook, reason):
    params, diagnostics = validate_temporal_params(rulebook, json.dumps({"week_start": claim("sun", WEEK)}))
    assert params == TemporalParams()
    assert diagnostics["week_start"] == reason


def test_normalized_whitespace_supports_a_wrapped_rule():
    rulebook = "- Tuần bắt đầu\n  Chủ nhật. Tuần không bắt đầu thứ Hai."
    params, _ = validate_temporal_params(rulebook, json.dumps({"week_start": claim("sun", WEEK)}))
    assert params.week_start == "sun"


def test_rolling_month_exclusion_requires_temporal_evidence():
    rule = "N tháng gần nhất không tính hôm nay"
    params, _ = validate_temporal_params(rule, json.dumps({"rolling_includes_as_of": claim(False, rule)}))
    assert params.rolling_includes_as_of is False
    assert params.provenance["rolling_includes_as_of"].span == rule


def test_unsupported_prior_period_policy_and_strict_boolean():
    prior = "Prior periods use only the same number of elapsed days"
    params, diagnostics = validate_temporal_params(f"{prior}. {ROLLING}.", json.dumps({
        "prior_period_full": claim(False, prior), "rolling_includes_as_of": claim(0, ROLLING),
    }))
    assert params == TemporalParams()
    assert diagnostics["prior_period_full"] == "unsupported_runtime_value"
    assert diagnostics["rolling_includes_as_of"] == "invalid_value"


@pytest.mark.parametrize("content, reason", [("{", "invalid_json"), ("[]", "invalid_shape"), ("NaN", "invalid_json")])
def test_malformed_payload_is_safe(content, reason):
    assert validate_temporal_params(WEEK, content) == (TemporalParams(), {"profile": reason})


def test_duplicate_claim_is_invalidated_without_affecting_other_fields():
    rolling = json.dumps(claim(False, ROLLING))
    content = '{"week_start":{},"week_start":{},"rolling_includes_as_of":' + rolling + "}"
    params, diagnostics = validate_temporal_params(f"{WEEK}. {ROLLING}.", content)
    assert diagnostics["week_start"] == "invalid_candidate"
    assert params.rolling_includes_as_of is False


@pytest.mark.parametrize("contents", [None, "", " \n\t"])
def test_empty_rulebook_skips_model_call(tmp_path, monkeypatch, contents):
    if contents is not None:
        (tmp_path / "rulebook.md").write_text(contents, encoding="utf-8-sig")
    client = ScriptedModelClient([])
    monkeypatch.setattr(client, "complete", lambda **_: pytest.fail("empty rulebook made a model call"))
    split = load_split(tmp_path, client=client)
    assert split.temporal == TemporalParams()
    assert split.temporal_diagnostics == {"profile": "empty_rulebook"}
    assert split.rule_profile_calls == []


def test_failed_profile_call_keeps_defaults_and_retains_error(tmp_path):
    (tmp_path / "rulebook.md").write_text(WEEK, encoding="utf-8")
    split = load_split(tmp_path, client=ScriptedModelClient([]))
    assert split.temporal == TemporalParams()
    assert split.temporal_diagnostics == {"profile": "model_error"}
    assert len(split.rule_profile_calls) == 1
    assert split.rule_profile_calls[0].error == "E_SCRIPT_MISS"
