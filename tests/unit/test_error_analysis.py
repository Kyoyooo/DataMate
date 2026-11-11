"""L-14: error classes, owners and the markdown table on a deliberately damaged fixture run."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys

from datamate.run import main as run_main

from conftest import REPO, SPLIT


def load():
    spec = importlib.util.spec_from_file_location("error_analysis", REPO / "tools" / "error_analysis.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["error_analysis"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_classes_owners_and_threshold(tmp_path):
    ea = load()
    out = tmp_path / "out"
    assert run_main(["--dev", "--config", str(REPO / "config" / "dev.json"), "--data-dir", str(SPLIT),
                     "--result-dir", str(out), "--set", f"work_dir={tmp_path / 'w'}"]) == 0
    damaged = tmp_path / "damaged"
    shutil.copytree(out, damaged)
    sub = {json.loads(x)["id"]: json.loads(x) for x in (damaged / "submission.jsonl").read_text().splitlines()}
    sub["fx_q01"] = {"id": "fx_q01", "type": "number", "answer": 1}                # wrong value
    sub["fx_q03"] = {"id": "fx_q03", "type": "number", "answer": 16.67}            # wrong type
    sub["fx_q06"] = {"id": "fx_q06", "type": "unanswerable"}                       # false unanswerable
    sub["fx_q07"] = {"id": "fx_q07", "type": "number", "answer": 3}                # missed unanswerable
    sub["fx_q10"] = {"id": "fx_q10", "type": "abstain"}                            # abstain (reason from log)
    (damaged / "submission.jsonl").write_text("".join(json.dumps(v, ensure_ascii=False) + "\n" for v in sub.values()))

    rep = ea.analyze([damaged], SPLIT / "answers.jsonl", min_share=0.01)
    classes = {r["class"]: r for r in rep["classes"]}
    assert rep["questions"] == 13 and rep["not_correct"] == 5 and rep["wrong"] == 4 and rep["abstain"] == 1
    assert classes["wrong_value:number"]["owner"] == "M3"
    assert classes["type_mismatch:number->percent"]["owner"] == "M3"
    assert classes["false_unanswerable"]["owner"] == "M2"
    assert classes["missed_unanswerable"]["owner"] == "M2"
    assert classes["abstain:D_ANSWER"]["sample_ids"] == ["fx_q10"]
    assert all(r["above_threshold"] for r in rep["classes"])  # each is 1/13 > 1 %
    assert rep["unowned_above_threshold"] == []
    assert abs(classes["wrong_value:number"]["pa_cost"] - 2 / 13) < 1e-12
    md = ea.markdown(rep)
    assert "| **false_unanswerable** | 1 |" in md

    # the untouched run has no error class at all
    assert ea.analyze([out], SPLIT / "answers.jsonl")["classes"] == []
    assert ea.main(["--run", str(damaged), "--answers", str(SPLIT / "answers.jsonl"),
                    "--markdown", str(tmp_path / "r.md")]) == 0
    assert (tmp_path / "r.md").read_text().startswith("# Error analysis (13 questions; 4 wrong, 1 abstain)")
