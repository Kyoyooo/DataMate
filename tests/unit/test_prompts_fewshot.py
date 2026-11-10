"""M3-04/05/10: template v2, few-shot bank, leakage guard, bank builder (CPU)."""

from __future__ import annotations

import importlib.util
import json

import pytest

from datamate.config import load_config
from datamate.contracts import QuestionFrame
from datamate.prompts import TEMPLATES, render_repair, render_solve, template_sha256
from datamate.prompts.templates import (
    REPAIR_USER_V1,
    SOLVE_SYSTEM_V1,
    SOLVE_USER_V1,
    render_solve_system,
)
from datamate.run import main
from datamate.solver import FewshotBank, FewshotEntry

from conftest import REPO, SCRIPT, SPLIT, question, scripted

BUILDER = REPO / "training_code" / "data_generation" / "build_fewshot.py"


def test_released_v1_templates_are_unchanged_and_v2_ids_are_new():
    # v1 is released: its text is pinned by hash so an accidental edit fails here
    import hashlib
    v1 = hashlib.sha256("\x00".join((SOLVE_SYSTEM_V1, SOLVE_USER_V1)).encode()).hexdigest()
    assert template_sha256()["solve.sql.v1"] == v1
    assert {"solve.sql.v2", "repair.sql.v2"} <= set(TEMPLATES)
    assert template_sha256()["solve.sql.v2"] != v1


def test_v2_system_prompt_states_the_dc1_dc2_and_coalesce_rules(split, catalog):
    text = render_solve_system(split, catalog, "solve.sql.v2")
    for needle in ('list_order "ranked"', 'list_order "question_order"', "Never sort by value",
                   "never ROUND", "money is whole VND", "ONLY for a quantity that is really zero",
                   "NULLIF", "do not LIMIT"):
        assert needle in text, needle
    # business-level prefix is byte-identical for every question (D3)
    frame = QuestionFrame.model_validate({"expected_type": "number", "numeric_kind": "money"})
    a = render_solve(question("a?"), frame, [], split, catalog, "solve.sql.v2")
    b = render_solve(question("b?"), frame, [], split, catalog, "solve.sql.v2")
    assert a[0] == b[0] and a[1] != b[1]


def test_examples_appear_only_in_the_v2_question_block(split, catalog):
    frame = QuestionFrame.model_validate({"expected_type": "number", "numeric_kind": "money"})
    v2 = render_solve(question("a?"), frame, [], split, catalog, "solve.sql.v2", ["EX1\n"])
    assert "SIMILAR SOLVED EXAMPLES:\nEX1" in v2[1]["content"] and "EX1" not in v2[0]["content"]
    assert "EXAMPLES" not in render_solve(question("a?"), frame, [], split, catalog)[1]["content"]
    assert "Fix the statement" in render_repair(v2, "x", "E", "t", "repair.sql.v2")[-1]["content"]
    assert render_repair(v2, "x", "E", "t")[-1]["content"] == REPAIR_USER_V1.format(
        error_code="E", error_text="t")


def entry(i, biz, q, typ="number", metric=""):
    return FewshotEntry(f"e{i}", biz, q, metric, typ, {"expected_type": typ}, f"SELECT {i} AS value")


def test_selection_is_ranked_deterministic_and_tie_broken_by_entry_id():
    bank = FewshotBank([entry(3, "b", "tồn kho hiện tại"), entry(1, "a", "doanh thu tuần rồi"),
                        entry(2, "a", "doanh thu tháng này"), entry(9, "c", "doanh thu tuần rồi", "string")])
    got = bank.select("Doanh thu tuần rồi?", "doanh thu", "number", 3)
    # e1: Jaccard 100 + 10 type bonus; e9: 100, no bonus; e2: partial; e3 none
    assert [e.entry_id for e in got] == ["e1", "e9", "e2"]
    tie = FewshotBank([entry(2, "a", "same words"), entry(1, "b", "same words")])
    assert [e.entry_id for e in tie.select("same words", "", "number", 2)] == ["e1", "e2"]
    assert bank.select("x", "", "number", 0) == []


def test_leakage_guard_excludes_the_evaluated_fold():
    bank = FewshotBank([entry(1, "fold_biz", "doanh thu tuần rồi"), entry(2, "other", "doanh thu tuần rồi")])
    got = bank.select("doanh thu tuần rồi", "", "number", 5, {"fold_biz"})
    assert [e.source_business_id for e in got] == ["other"]
    assert bank.select("doanh thu tuần rồi", "", "number", 5, {"fold_biz", "other"}) == []


@pytest.fixture
def train_run(tmp_path):
    out = tmp_path / "run"
    assert main(["--dev", "--config", str(REPO / "config" / "dev.json"), "--data-dir", str(SPLIT),
                 "--result-dir", str(out), "--set", f"work_dir={tmp_path / 'w'}",
                 "--set", f"model.script_path={SCRIPT}"]) == 0
    return out


def load_builder():
    spec = importlib.util.spec_from_file_location("build_fewshot", BUILDER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_builder_keeps_only_correct_answers_and_is_deterministic(train_run, tmp_path):
    mod = load_builder()
    out1, out2 = tmp_path / "b1.jsonl", tmp_path / "b2.jsonl"
    for out in (out1, out2):
        assert mod.main(["--run-dir", str(train_run), "--split-dir", str(SPLIT), "--out", str(out)]) == 0
    assert out1.read_bytes() == out2.read_bytes()
    rows = [json.loads(x) for x in out1.read_text(encoding="utf-8").splitlines()]
    assert rows and all(r["sql"].lstrip().upper().startswith(("SELECT", "WITH")) for r in rows)
    assert {r["source_business_id"] for r in rows} == {"biz_fx01"}
    assert [r["entry_id"] for r in rows] == sorted(r["entry_id"] for r in rows)
    # a wrong run is not eligible: replace every answer by abstain -> no examples
    wrong = tmp_path / "wrong"
    (wrong / "logs").mkdir(parents=True)
    lines = []
    for x in (train_run / "logs" / "questions.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(x)
        r["answer"] = {"type": "number", "answer": 123456789}
        lines.append(json.dumps(r, ensure_ascii=False))
    (wrong / "logs" / "questions.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert mod.main(["--run-dir", str(wrong), "--split-dir", str(SPLIT), "--out", str(tmp_path / "w.jsonl")]) == 0
    assert (tmp_path / "w.jsonl").read_text() == ""


def test_builder_refuses_test_like_splits_and_foreign_ids(train_run, tmp_path, capsys):
    mod = load_builder()
    no_answers = tmp_path / "public"
    no_answers.mkdir()
    assert mod.main(["--run-dir", str(train_run), "--split-dir", str(no_answers), "--out", str(tmp_path / "x")]) == 2
    assert "training splits only" in capsys.readouterr().err
    other = tmp_path / "other_split"
    other.mkdir()
    (other / "answers.jsonl").write_text('{"id": "zzz", "type": "abstain", "answer": null}\n')
    (other / "questions.jsonl").write_text('{"id": "zzz", "business_id": "b", "question": "q", "as_of_date": "2026-01-01"}\n')
    assert mod.main(["--run-dir", str(train_run), "--split-dir", str(other), "--out", str(tmp_path / "x")]) == 2
    assert "no reference answer" in capsys.readouterr().err


class Capture:
    """Delegates to a scripted client and keeps the messages of every call."""

    backend, dev_only = "scripted", True

    def __init__(self, inner):
        self.inner, self.messages = inner, []

    def complete(self, **kw):
        self.messages.append((kw["stage"], kw["messages"]))
        return self.inner.complete(**kw)


def test_v2_run_puts_bank_examples_in_the_prompt_and_exclusion_removes_them(train_run, tmp_path):
    from datamate.catalog import setup_business
    from datamate.rules import load_split
    from datamate.runtime import answer_question

    bank_path = tmp_path / "bank.jsonl"
    assert load_builder().main(["--run-dir", str(train_run), "--split-dir", str(SPLIT),
                                "--out", str(bank_path)]) == 0
    cfg = load_config(None, [f"work_dir={tmp_path / 'w'}", "model.backend=scripted",
                             'solver.template_version="v2"', "solver.fewshot_k=2"])
    text = "Doanh thu tuần rồi là bao nhiêu?"
    frame = {"expected_type": "number", "numeric_kind": "money", "metric_text": "doanh thu",
             "time": [{"span": "tuần rồi", "role": "primary", "expr": {
                 "kind": "relative_period", "unit": "week", "offset": -1, "to_date": False}}]}
    cat = setup_business(SPLIT / "data" / "biz_fx01", "biz_fx01", tmp_path / "work")
    bank = FewshotBank.from_file(bank_path)

    def run(config):
        client = Capture(scripted(text, frame, {"sql": "SELECT 1 AS value"}))
        _, log = answer_question(question(text), load_split(SPLIT), cat, client, config,
                                 fewshot_bank=bank)
        solve_user = next(m for st, m in client.messages if st == "solve")[1]["content"]
        return log, solve_user

    log, user = run(cfg)
    assert next(c for c in log.calls if c.stage == "solve").template_id == "solve.sql.v2"
    assert user.count("SQL: SELECT") == 2 and "SIMILAR SOLVED EXAMPLES:" in user  # fewshot_k = 2
    assert log.decision["context"]["fewshot"] == 2
    excluded = cfg.model_copy(update={"solver": cfg.solver.model_copy(
        update={"fewshot_exclude_businesses": ["biz_fx01"]})})
    _, user = run(excluded)
    assert "SIMILAR SOLVED EXAMPLES" not in user  # every bank entry came from the excluded business
