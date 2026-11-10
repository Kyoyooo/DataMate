"""M4-14: tools/precheck.sh passes a good result dir and fails deliberately broken ones."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from datamate.run import main

from conftest import REPO, SCRIPT, SPLIT

PRECHECK = REPO / "tools" / "precheck.sh"


def run_precheck(*args: str):
    return subprocess.run(["bash", str(PRECHECK), *args], capture_output=True, text=True,
                          env={**os.environ, "PYTHON": sys.executable})


@pytest.fixture
def good(tmp_path):
    out = tmp_path / "good"
    assert main(["--dev", "--config", str(REPO / "config" / "dev.json"), "--data-dir", str(SPLIT),
                 "--result-dir", str(out), "--set", f"work_dir={tmp_path / 'w'}",
                 "--set", f"model.script_path={SCRIPT}"]) == 0
    return out


def test_good_result_passes_every_check(good):
    r = run_precheck("--data-dir", str(SPLIT), "--result-dir", str(good), "--answers",
                     str(SPLIT / "answers.jsonl"))
    assert r.returncode == 0, r.stdout
    assert "PASS C1" in r.stdout and "PASS C2" in r.stdout and "PASS C3" in r.stdout
    assert "PA: 1.0000" in r.stdout and r.stdout.strip().endswith("all checks passed")


def broken(good: Path, tmp_path: Path, name: str, edit) -> Path:
    out = tmp_path / name
    shutil.copytree(good, out)
    edit(out)
    return out


def edit_lines(path: Path, fn):
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in fn(rows)),
                    encoding="utf-8")


@pytest.mark.parametrize("name,edit,expect", [
    ("missing_line", lambda o: edit_lines(o / "submission.jsonl", lambda r: r[:-1]), "FAIL C1"),
    ("duplicate", lambda o: edit_lines(o / "submission.jsonl", lambda r: r + [r[0]]), "FAIL C1"),
    ("bad_type", lambda o: edit_lines(o / "submission.jsonl",
                                      lambda r: [{**r[0], "answer": [1]}] + r[1:]), "FAIL C1"),
    ("no_thinking", lambda o: edit_lines(o / "logs" / "questions.jsonl",
                                         lambda r: [{k: v for k, v in r[0].items() if k != "thinking"}]
                                         + r[1:]), "FAIL C2"),
    ("negative_elapsed", lambda o: edit_lines(o / "logs" / "questions.jsonl",
                                              lambda r: [{**r[0], "elapsed_ms": -1}] + r[1:]), "FAIL C2"),
    ("log_missing", lambda o: edit_lines(o / "logs" / "questions.jsonl", lambda r: r[1:]), "FAIL C2"),
    ("log_answer_differs", lambda o: edit_lines(
        o / "logs" / "questions.jsonl",
        lambda r: [{**r[0], "answer": {"type": "abstain"}}] + r[1:]), "FAIL C2"),
    ("no_run_json", lambda o: (o / "logs" / "run.json").unlink(), "FAIL C3"),
])
def test_deliberately_broken_result_dirs_fail(good, tmp_path, name, edit, expect):
    out = broken(good, tmp_path, name, edit)
    r = run_precheck("--data-dir", str(SPLIT), "--result-dir", str(out))
    assert r.returncode == 1, r.stdout
    assert expect in r.stdout and "FAILED" in r.stdout


def test_compare_detects_differences_and_accepts_identical(good, tmp_path):
    same = tmp_path / "same"
    shutil.copytree(good, same)
    assert run_precheck("--data-dir", str(SPLIT), "--result-dir", str(good),
                        "--compare", str(same)).returncode == 0
    def first_line_abstain(o: Path) -> None:  # touch one line only; keep the other bytes as written
        lines = (o / "submission.jsonl").read_text(encoding="utf-8").splitlines(keepends=True)
        qid = json.loads(lines[0])["id"]
        lines[0] = json.dumps({"id": qid, "type": "abstain"}) + "\n"
        (o / "submission.jsonl").write_text("".join(lines), encoding="utf-8")

    diff = broken(good, tmp_path, "diff", first_line_abstain)
    r = run_precheck("--data-dir", str(SPLIT), "--result-dir", str(good), "--compare", str(diff))
    assert r.returncode == 1 and "FAIL C5" in r.stdout and "1 ids differ" in r.stdout


def test_usage_errors():
    assert run_precheck().returncode == 2
    assert run_precheck("--result-dir", "x").returncode == 2


def test_missing_submission_fails(tmp_path):
    (tmp_path / "empty").mkdir()
    r = run_precheck("--data-dir", str(SPLIT), "--result-dir", str(tmp_path / "empty"))
    assert r.returncode == 1 and "FAIL C1 submission.jsonl exists" in r.stdout
