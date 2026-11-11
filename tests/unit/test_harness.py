"""L-10 / L-12: per-reason scoring, harness folds, run records, resume and compare_runs (CPU)."""

from __future__ import annotations

import importlib.util
import json
import sys

import pytest

from datamate.eval import harness
from datamate.eval.score import by_reason, score_files

from conftest import REPO, SPLIT

TRAIN = REPO / "train"


def test_folds_are_whole_businesses_and_match_the_bakeoff_rule(tmp_path):
    spec = importlib.util.spec_from_file_location("bakeoff", REPO / "tools" / "bakeoff.py")
    bake = importlib.util.module_from_spec(spec)
    sys.modules["bakeoff"] = bake
    spec.loader.exec_module(bake)
    ids = [f"biz_{i:03d}" for i in range(17)]
    assert harness.business_folds(ids, 5) == bake.business_folds(ids, 5)
    assert sorted(harness.business_folds(ids, 5).values()).count(0) == 4  # 17 = 4+4+3+3+3
    assert harness.fold_split(SPLIT, tmp_path / "f0", 0, 1) == ["biz_fx01"]
    assert (tmp_path / "f0" / "questions.jsonl").read_text() == (SPLIT / "questions.jsonl").read_text()


def run_harness(out, *extra):
    return harness.main(["run", "--config", str(REPO / "config" / "dev.json"), "--data-dir", str(SPLIT),
                         "--answers", str(SPLIT / "answers.jsonl"), "--out", str(out), "--folds", "1",
                         "--dev", "--set", f"work_dir={out}-work", *extra])


def test_run_record_resume_and_compare(tmp_path, capsys):
    a, b = tmp_path / "a", tmp_path / "b"
    assert run_harness(a) == 0 and run_harness(b) == 0
    rec = json.loads((a / "run_record.json").read_text())
    assert rec["report"]["pa"] == 1.0 and rec["report"]["n"] == 13
    assert rec["report"]["coverage"] == 1.0 and rec["report"]["unanswerable_recall"] == 1.0
    assert rec["report"]["by_reason"]["D_ANSWER"]["correct"] == 11
    for key in ("config_sha256", "template_sha256", "environment", "model", "data_snapshot_sha256",
                "contracts_version", "fold_businesses"):
        assert rec[key], key
    # resume: a complete fold is not run again
    assert run_harness(a, "--resume") == 0
    assert json.loads((a / "run_record.json").read_text())["resumed_folds"] == [0]
    # compare: identical runs are within the bound
    assert harness.main(["compare", str(a), str(b)]) == 0
    r = harness.compare_runs(rec, json.loads((b / "run_record.json").read_text()))
    assert r["changed"] == 0 and r["delta_pa"] == 0 and r["within_bound"]
    # different data snapshot or environment -> refused unless allowed
    other = {**rec, "data_snapshot_sha256": "0" * 64}
    with pytest.raises(harness.Incomparable, match="data_snapshot_sha256"):
        harness.compare_runs(rec, other)
    assert harness.compare_runs(rec, other, allow_env_diff=True)["differs_in"] == ["data_snapshot_sha256"]
    env = {**rec, "environment": {**rec["environment"], "packages": {"duckdb": "0"}}}
    with pytest.raises(harness.Incomparable, match="environment"):
        harness.compare_runs(rec, env)


def test_harness_requires_training_answers(tmp_path):
    assert harness.main(["run", "--config", str(REPO / "config" / "dev.json"), "--data-dir", str(SPLIT),
                         "--answers", str(tmp_path / "missing.jsonl"), "--out", str(tmp_path / "o"),
                         "--dev"]) == 2


def test_per_reason_code_report(tmp_path):
    from datamate.run import main
    out = tmp_path / "out"
    assert main(["--dev", "--config", str(REPO / "config" / "dev.json"), "--data-dir", str(SPLIT),
                 "--result-dir", str(out), "--set", f"work_dir={tmp_path / 'w'}"]) == 0
    res = score_files(out / "submission.jsonl", SPLIT / "answers.jsonl")
    rep = by_reason(res["per_id"], out / "logs" / "questions.jsonl")
    assert sum(c["correct"] + c["wrong"] + c["abstain"] for c in rep.values()) == 13
    assert rep["D_ANSWER"] == {"correct": 11, "wrong": 0, "abstain": 0}


@pytest.mark.skipif(not (TRAIN / "answers.jsonl").is_file(), reason="train/answers.jsonl not available")
def test_training_answers_score_1_against_themselves():
    assert score_files(TRAIN / "answers.jsonl", TRAIN / "answers.jsonl")["pa"] == 1.0
