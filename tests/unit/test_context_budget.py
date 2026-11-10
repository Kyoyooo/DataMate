"""M3-03: deterministic context budgeting with very large SchemaCards (CPU)."""

from __future__ import annotations

from pathlib import Path

import pytest

from datamate.config import SolverConfig
from datamate.contracts import codes
from datamate.llm.tokenizer import CharEstimateTokenizer, count_tokens, load_tokenizer
from datamate.prompts.budget import README_MARKER, ContextBuilder, ContextOverflow, truncate_head
from datamate.prompts.templates import render_solve_system
from datamate.runtime import answer_question

from conftest import REPO, question

TOK = CharEstimateTokenizer(chars_per_token=2.0)  # 1 token = 2 chars: easy hand arithmetic


def cfg(**kw) -> SolverConfig:
    base = dict(tokenizer="estimate", context_budget_tokens=4000, readme_budget_tokens=100,
                question_block_reserve_tokens=100, fewshot_k=3)
    base.update(kw)
    return SolverConfig(**base)


def big_catalog(catalog, card_chars=370_000, readme_chars=1000):
    return catalog.model_copy(update={"schema_card": "T" * card_chars,
                                      "readme_text": "R" * readme_chars})


def test_truncate_head_fits_exactly_and_keeps_short_text():
    assert truncate_head("abc", TOK, 10) == "abc"
    out = truncate_head("x" * 1000, TOK, 100)
    assert out.endswith(README_MARKER) and count_tokens(TOK, out) <= 100
    assert count_tokens(TOK, out[: -len(README_MARKER)] + "x" + README_MARKER) > 100  # maximal prefix
    assert truncate_head("x" * 1000, TOK, 1) == ""  # not even the marker fits


def test_no_reduction_when_everything_fits(split, catalog):
    plan = ContextBuilder(TOK, cfg(context_budget_tokens=100_000, readme_budget_tokens=50_000)).plan(
        question("Doanh thu?"), split, catalog, ["shot1", "shot2"])
    assert plan.reductions == [] and plan.fewshot == ["shot1", "shot2"]
    assert plan.catalog.schema_card == catalog.schema_card
    assert plan.total_tokens == plan.system_tokens + 100 + 2 * count_tokens(TOK, "shot1")


def test_reduction_order_fewshot_then_readme_then_schema_subset(split, catalog):
    cat = big_catalog(catalog, card_chars=200, readme_chars=1000)
    shots = ["S" * 400] * 3  # 200 tokens each
    # Reference: no budget pressure. The README is already head-truncated to its own 100-token
    # budget (business level), which is the first reduction.
    ref = ContextBuilder(TOK, cfg(context_budget_tokens=100_000)).plan(question("x"), split, cat, shots)
    assert ref.reductions == ["readme_truncated"] and len(ref.fewshot) == 3
    sys_tokens = ref.system_tokens
    # one token short of fitting all three examples: only the LAST example is dropped
    one = ContextBuilder(TOK, cfg(context_budget_tokens=sys_tokens + 100 + 600 - 1)).plan(
        question("x"), split, cat, shots)
    assert one.reductions == ["readme_truncated", "fewshot_dropped"] and one.fewshot == shots[:2]
    # no room for any example: all dropped first, the README is still intact (truncated) ...
    none = ContextBuilder(TOK, cfg(context_budget_tokens=sys_tokens + 100)).plan(
        question("x"), split, cat, shots)
    assert none.fewshot == [] and none.reductions.count("fewshot_dropped") == 3
    assert "readme_dropped" not in none.reductions
    # ... and only when the system prompt itself no longer fits is the README dropped
    tight = ContextBuilder(TOK, cfg(context_budget_tokens=sys_tokens + 100 - 1)).plan(
        question("x"), split, cat, shots)
    assert tight.reductions.index("fewshot_dropped") < tight.reductions.index("readme_dropped")
    assert tight.catalog.readme_text is None


def test_huge_schema_card_uses_subset_hook_then_overflows_without_it(split, catalog):
    cat = big_catalog(catalog)  # 370,000-character card: ~185,000 tokens here
    subset_calls = []

    def subset(c, question_text):
        subset_calls.append(question_text)
        return "TABLE ban_hang (relevant subset)"

    plan = ContextBuilder(TOK, cfg(), schema_subset_fn=subset).plan(question("Doanh thu?"), split, cat)
    assert plan.reductions[-1] == "schema_subset" and subset_calls == ["Doanh thu?"]
    assert plan.catalog.schema_card == "TABLE ban_hang (relevant subset)"
    assert plan.total_tokens <= 4000
    with pytest.raises(ContextOverflow, match="budget 4000"):
        ContextBuilder(TOK, cfg()).plan(question("Doanh thu?"), split, cat)


def test_rulebook_is_never_truncated(split, catalog):
    huge_rulebook = split.model_copy(update={"rulebook_text": "Q" * 20_000})
    with pytest.raises(ContextOverflow):
        ContextBuilder(TOK, cfg(), schema_subset_fn=lambda c, q: "x").plan(
            question("x"), huge_rulebook, catalog)


def test_plan_is_deterministic_and_business_prefix_is_byte_identical(split, catalog):
    cat = big_catalog(catalog, card_chars=300, readme_chars=5000)
    b = ContextBuilder(TOK, cfg(context_budget_tokens=100_000))
    a1 = render_solve_system(split, b.plan(question("a?"), split, cat).catalog)
    a2 = render_solve_system(split, b.plan(question("b? khác"), split, cat).catalog)
    assert a1 == a2 and README_MARKER in a1  # sections 1-5 identical for every question (D3)


def test_pipeline_abstains_with_context_overflow_and_makes_no_model_call(cfg, split, catalog):
    from conftest import scripted
    cat = big_catalog(catalog)
    client = scripted("Doanh thu tuần rồi là bao nhiêu?", {"expected_type": "number",
                                                          "numeric_kind": "money", "time": []})
    ctx = ContextBuilder(TOK, cfg_solver := SolverConfig(tokenizer="estimate",
                                                         context_budget_tokens=4000))
    assert cfg_solver.context_budget_tokens == 4000
    record, log = answer_question(question("Doanh thu tuần rồi là bao nhiêu?"), split, cat, client,
                                  cfg, context=ctx)
    assert record.type == "abstain" and log.decision["reason_code"] == codes.E_CONTEXT_OVERFLOW
    assert log.calls == [] and "overflow" in log.decision["context"]


def test_pipeline_records_context_info_when_it_fits(cfg, split, catalog):
    from conftest import scripted
    text = "Doanh thu tuần rồi là bao nhiêu?"
    client = scripted(text, {"expected_type": "number", "numeric_kind": "money",
                             "time": [{"span": "tuần rồi", "role": "primary", "expr": {
                                 "kind": "relative_period", "unit": "week", "offset": -1,
                                 "to_date": False}}]},
                      {"sql": "SELECT 1 AS value"})
    ctx = ContextBuilder(TOK, SolverConfig(tokenizer="estimate"))
    _, log = answer_question(question(text), split, catalog, client, cfg, context=ctx)
    assert log.decision["context"]["tokenizer"] == "chars-estimate"
    assert log.decision["context"]["reductions"] == [] and log.decision["context"]["tokens"] > 0


def test_tokenizer_loading_is_local_only_and_optional(tmp_path):
    assert load_tokenizer(None) is None and load_tokenizer(str(tmp_path / "absent")) is None
    assert load_tokenizer(str(tmp_path)) is None  # directory without tokenizer files


def test_real_tokenizer_if_a_local_model_is_present():
    pytest.importorskip("transformers")
    candidates = [p for p in (REPO / "models").glob("*/tokenizer*") if p.exists()] \
        if (REPO / "models").is_dir() else []
    if not candidates:
        pytest.skip("no local tokenizer under models/ (gitignored); runs on the build host")
    tok = load_tokenizer(str(Path(candidates[0]).parent))
    assert tok is not None and count_tokens(tok, "Doanh thu tháng này là bao nhiêu?") > 0
