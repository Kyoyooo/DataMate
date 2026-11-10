"""M3-03 acceptance: deterministic counters/fixtures, no model weights or network."""

from __future__ import annotations

import copy
import json
import sys
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from datamate.catalog import render_schema_card
from datamate.config import ModelConfig, RunConfig, load_config
from datamate.contracts import QuestionFrame, codes
from datamate.llm import get_token_counter, server_arguments
from datamate.prompts import complete_prompt, prepare_parse, prepare_solve, render_parse
from datamate.run import main
from datamate.solver import solve

from conftest import REPO, SPLIT, question, scripted


class CharacterCounter:
    """Deterministic test units, explicitly not production model tokens."""

    fingerprint = {"mode": "test_characters"}

    def count_text(self, text):
        return len(text)

    def count_messages(self, messages, *, thinking):
        return 3 + sum(len(m["content"]) + 5 for m in messages)


COUNTER = CharacterCounter()
FRAME = QuestionFrame(expected_type="number", numeric_kind="money", metric_text="doanh thu")


def test_shared_profile_and_derived_limits():
    cfg = load_config(REPO / "config/runtime_defaults.json")
    assert [cfg.input_budget(s) for s in ("parse", "solve", "repair")] == [7104, 6080, 6080]
    dev = load_config(REPO / "config/dev.json")
    assert dev.serving == cfg.serving and dev.prompt_budget == cfg.prompt_budget
    changed = load_config(REPO / "config/dev.json", ["serving.max_model_len=16384"])
    assert changed.input_budget("solve") == 14272 and changed.sha256() != dev.sha256()


def test_config_inheritance_merges_sections_and_rejects_cycles(tmp_path):
    (tmp_path / "base.json").write_text(json.dumps({"model": {"seed": 10, "top_p": 0.8}}))
    (tmp_path / "child.json").write_text(json.dumps({"extends": "base.json", "model": {"seed": 20}}))
    cfg = load_config(tmp_path / "child.json")
    assert cfg.model.seed == 20 and cfg.model.top_p == 0.8
    (tmp_path / "base.json").write_text('{"extends":"child.json"}')
    with pytest.raises(ValueError, match="cyclic"):
        load_config(tmp_path / "child.json")


@pytest.mark.parametrize("overrides", [
    ["serving.max_model_len=2000"], ["model.max_tokens.solve=0"],
    ["prompt_budget.safety_margin_tokens=-1"], ["prompt_budget.context_budget_tokens=0"],
])
def test_invalid_context_config_fails_early(overrides):
    with pytest.raises(ValidationError):
        load_config(None, overrides)


def test_server_arguments_use_same_context_config():
    cfg = load_config(REPO / "config/runtime_defaults.json", [
        "model.path=/local/model", "model.base_url=http://127.0.0.1:8000/v1",
        "serving.max_model_len=16384"])
    args = server_arguments(cfg, total_vram_mib=80 * 1024)
    assert args[args.index("--max-model-len") + 1] == "16384"
    assert args[args.index("--max-num-seqs") + 1] == "4"
    assert float(args[args.index("--gpu-memory-utilization") + 1]) == pytest.approx(0.36)
    assert args[args.index("--model") + 1] == args[args.index("--tokenizer") + 1]


def test_normal_render_and_business_prefix_are_stable(cfg, split, catalog):
    q1, q2 = question("Doanh thu?"), question("Số đơn?")
    a = prepare_parse(q1, split, catalog, cfg, counter=COUNTER)
    b = prepare_parse(q2, split, catalog, cfg, counter=COUNTER)
    assert a.messages == render_parse(q1, split, catalog)
    assert a.messages == prepare_parse(q1, split, catalog, cfg, counter=COUNTER).messages
    assert a.messages[0] == b.messages[0] and a.messages[-1] != b.messages[-1]
    assert a.diagnostics["prefix_scope"] == "business"
    assert a.diagnostics["prefix_sha256"] == b.diagnostics["prefix_sha256"]


def test_solve_keeps_rulebook_frame_windows_and_catalog_unchanged(cfg, split, catalog):
    before = catalog.model_dump()
    q = question("Doanh thu tháng này?")
    plan = prepare_solve(q, FRAME, [], split, catalog, cfg, counter=COUNTER)
    assert plan.error_code is None
    assert split.rulebook_text in plan.messages[0]["content"]
    assert FRAME.model_dump_json() in plan.messages[-1]["content"]
    assert q.question in plan.messages[-1]["content"]
    assert catalog.model_dump() == before
    assert plan.diagnostics["input_tokens"] + 2048 + 64 <= 8192


def test_readme_section_cap_has_marker_and_preserves_unicode(cfg, split, catalog):
    cat = catalog.model_copy(update={"readme_text": "Thông tin doanh nghiệp. " * 100})
    small = load_config(None, ["prompt_budget.readme_budget_tokens=80"])
    plan = prepare_solve(question("Doanh thu?"), FRAME, [], split, cat, small, counter=COUNTER)
    assert plan.diagnostics["readme_tokens"] <= 80
    assert "[README truncated by prompt budget]" in plan.messages[0]["content"]
    assert "Thông tin" in plan.messages[0]["content"]
    assert cat.readme_text == "Thông tin doanh nghiệp. " * 100


def test_drop_fewshots_last_first_before_readme(cfg, split, catalog):
    q = question("Doanh thu?")
    base = prepare_solve(q, FRAME, [], split, catalog, cfg, counter=COUNTER)
    cap = base.diagnostics["input_tokens"] + 20
    limited = load_config(None, [f"prompt_budget.context_budget_tokens={cap}"])
    examples = [{"role": "user", "content": "first"},
                {"role": "assistant", "content": "second" * 100},
                {"role": "user", "content": "last" * 100}]
    before = copy.deepcopy(examples)
    plan = prepare_solve(q, FRAME, [], split, catalog, limited, counter=COUNTER, fewshots=examples)
    assert plan.error_code is None and plan.diagnostics["fewshots_kept"] == 1
    assert plan.messages[1] == examples[0] and examples == before
    assert plan.diagnostics["actions"].count("drop_last_fewshot") == 2
    assert not any(a.startswith("reduce_readme") for a in plan.diagnostics["actions"])


def test_readme_reduction_follows_fewshots(cfg, split, catalog):
    q = question("Doanh thu?")
    cat = catalog.model_copy(update={"readme_text": "R" * 1000})
    empty = cat.model_copy(update={"readme_text": None})
    baseline = prepare_solve(q, FRAME, [], split, empty, cfg, counter=COUNTER)
    small = load_config(None, ["prompt_budget.readme_budget_tokens=1000",
        f'prompt_budget.context_budget_tokens={baseline.diagnostics["input_tokens"] + 100}'])
    plan = prepare_solve(q, FRAME, [], split, cat, small, counter=COUNTER,
                         fewshots=[{"role": "user", "content": "EXAMPLE" * 1000}])
    actions = plan.diagnostics["actions"]
    assert actions.index("drop_last_fewshot") < next(i for i, a in enumerate(actions) if a.startswith("reduce_readme"))
    assert plan.error_code is None and plan.diagnostics["prefix_scope"] == "reduced"


def test_relevant_schema_uses_metadata_and_stable_ties(cfg, split, catalog):
    prototype = catalog.tables[0]
    tables = [prototype.model_copy(update={"name": f"table_{i:02d}", "columns": prototype.columns[:3]})
              for i in range(20)]
    tables.append(prototype.model_copy(update={"name": "sales_target", "columns": prototype.columns[:3]}))
    cat = catalog.model_copy(update={"tables": tables, "schema_card": render_schema_card(
        tables, catalog.data_range, []), "warnings": []})
    cfg = load_config(None, ["prompt_budget.schema_card_budget_tokens=1800"])
    q = question("sales_target doanh thu")
    plan = prepare_solve(q, FRAME, [], split, cat, cfg, counter=COUNTER)
    assert "schema_relevant_subset" in plan.diagnostics["actions"]
    assert plan.diagnostics["selected_tables"][0] == "sales_target"
    assert plan.diagnostics["prefix_scope"] == "reduced"
    assert "OTHER TABLES" in plan.messages[0]["content"]
    assert plan.messages == prepare_solve(q, FRAME, [], split, cat, cfg, counter=COUNTER).messages
    assert len(cat.tables) == 21  # full catalog is not replaced for execution/logging


def test_exact_boundary_and_one_unit_overflow(cfg, split, catalog):
    cat = catalog.model_copy(update={"readme_text": None, "schema_card": "", "tables": [],
                                     "data_range": None, "warnings": []})
    q = question("Mandatory question")
    base = prepare_parse(q, split, cat, cfg, counter=COUNTER)
    n = base.diagnostics["input_tokens"]
    exact = load_config(None, [f"prompt_budget.context_budget_tokens={n}"])
    assert prepare_parse(q, split, cat, exact, counter=COUNTER).error_code is None
    short = load_config(None, [f"prompt_budget.context_budget_tokens={n - 1}"])
    assert prepare_parse(q, split, cat, short, counter=COUNTER).error_code == codes.E_CONTEXT_OVERFLOW


def test_overflow_preserves_mandatory_context_and_does_not_call_client(cfg, split, catalog):
    big = split.model_copy(update={"rulebook_text": "MANDATORY RULEBOOK " * 1000})
    history = [{"role": "assistant", "content": "previous generated SQL"},
               {"role": "user", "content": "actual execution error"}]
    q = question("Do not lose this question")
    plan = prepare_solve(q, FRAME, [], big, catalog, cfg, stage="repair", history=history, counter=COUNTER)
    assert plan.error_code == codes.E_CONTEXT_OVERFLOW
    assert big.rulebook_text in plan.messages[0]["content"]
    assert plan.messages[-2:] == history
    assert q.question in plan.messages[-3]["content"]

    class NeverCalled:
        backend = "http"
        def complete(self, **kwargs):
            raise AssertionError("overflow must not invoke model")
    call = complete_prompt(plan, NeverCalled(), cfg, stage="repair", template_id="repair.sql.v1",
                           json_schema={}, call_id="not-sent")
    assert call.error == codes.E_CONTEXT_OVERFLOW and call.finish_reason == "not_sent"
    assert call.request_sha256 == "" and call.reasoning is None
    assert call.prompt_budget["client_called"] is False


def test_repair_history_is_recounted_before_next_call(cfg, split, catalog, monkeypatch):
    monkeypatch.setattr("datamate.prompts.budget.get_token_counter", lambda cfg: COUNTER)
    text = "Doanh thu?"
    bad = {"sql": "SELECT missing_column FROM ban_hang", "notes": "X" * 7000}
    client = scripted(text, {}, bad)
    attempts = solve(question(text), FRAME, [], catalog, split, client, cfg)
    assert len(attempts) == 2
    assert attempts[0].error_code == codes.E_SOLVER_OUTPUT_INVALID
    assert attempts[1].error_code == codes.E_CONTEXT_OVERFLOW
    assert attempts[1].model_call.prompt_budget["history_messages"] == 2
    assert attempts[1].model_call.finish_reason == "not_sent"


def test_local_counter_is_offline_cached_and_uses_chat_template(tmp_path, monkeypatch):
    from datamate.llm import tokenizer as module
    loads = []
    observations = []
    class FakeTokenizer:
        chat_template = "test template"
        def encode(self, text, **kwargs):
            assert kwargs == {"add_special_tokens": False}
            return list(text)
        def apply_chat_template(self, messages, **kwargs):
            observations.append(kwargs)
            return [0] * 17
    def load(path, **kwargs):
        loads.append(path)
        assert kwargs == {"local_files_only": True, "trust_remote_code": False}
        return FakeTokenizer()
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(
        AutoTokenizer=SimpleNamespace(from_pretrained=load)))
    (tmp_path / "tokenizer_config.json").write_text('{"chat_template":"test template"}')
    cfg = RunConfig(model=ModelConfig(path=str(tmp_path)))
    a, b = get_token_counter(cfg), get_token_counter(cfg)
    assert a is b and len(loads) == 1
    assert a.count_text("abc") == 3
    assert a.count_messages([{"role": "user", "content": "test"}], thinking=True) == 17
    assert observations == [
        {"tokenize": True, "add_generation_prompt": True, "enable_thinking": False},
        {"tokenize": True, "add_generation_prompt": True, "enable_thinking": True},
    ]
    assert a.fingerprint["mode"] == "local_tokenizer" and len(a.fingerprint["files_sha256"]) == 64
    module._local_counter.cache_clear()


def test_missing_tokenizer_fails_before_outputs(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"model": {"backend": "http", "base_url": "http://127.0.0.1:8000/v1",
                                         "path": str(tmp_path / "absent")}}))
    out = tmp_path / "result"
    assert main(["--config", str(path), "--data-dir", str(SPLIT), "--result-dir", str(out)]) == 2
    assert not out.exists()


def test_development_counter_is_explicit_and_not_used_for_http(cfg):
    assert get_token_counter(cfg).fingerprint["mode"] == "development_utf8_bytes_not_model_tokens"
    with pytest.raises(ValueError, match="model.path is required"):
        get_token_counter(RunConfig())
