"""L-20 (TASKS): two fresh processes on recorded calls produce identical outputs.

The recording ``tests/fixtures/model_calls/split_mini.scripted.jsonl`` was produced by running
the scripted fixture client through ``RecordingModelClient`` (see its header); real-model
recordings follow the same format (docs/runbooks/record-model-calls.md).
Timing fields are the only thing removed before comparing ``questions.jsonl``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from datamate.eval.score import score_files

REPO = Path(__file__).resolve().parents[2]
SPLIT = REPO / "tests" / "fixtures" / "split_mini"


def test_replay_fixture_rulebook_has_pinned_line_endings():
    raw = (SPLIT / "rulebook.md").read_bytes()
    assert b"\r" not in raw, (
        "Replay hashes include verbatim rulebook bytes. This fixture must use LF "
        "on all platforms, as pinned in .gitattributes; re-record after source changes."
    )


def fresh_run(tmp: Path, name: str, *extra: str) -> Path:
    out = tmp / name
    proc = subprocess.run(
        [sys.executable, "-m", "datamate.run", "--dev", "--config", str(REPO / "config" / "replay.json"),
         "--data-dir", str(SPLIT), "--result-dir", str(out), "--set", f"work_dir={tmp / name}-work",
         "--set", f"model.replay_path={REPO / 'tests/fixtures/model_calls/split_mini.scripted.jsonl'}",
         *extra],
        capture_output=True, text=True, cwd=REPO, env={"PYTHONHASHSEED": "0", "PATH": "/usr/bin:/bin"})
    assert proc.returncode == 0, proc.stderr
    return out


def strip_timing(path: Path) -> list[dict]:
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    for r in rows:
        r.pop("elapsed_ms")
        for c in r["calls"]:
            c.pop("latency_ms")
        for a in r["attempts"]:
            a.pop("duration_ms", None)
    return rows


def test_two_fresh_processes_are_byte_identical(tmp_path):
    a, b = fresh_run(tmp_path, "a"), fresh_run(tmp_path, "b")
    assert (a / "submission.jsonl").read_bytes() == (b / "submission.jsonl").read_bytes()
    assert strip_timing(a / "logs" / "questions.jsonl") == strip_timing(b / "logs" / "questions.jsonl")


def test_replayed_run_is_correct_and_has_no_misses(tmp_path):
    out = fresh_run(tmp_path, "a", "--set", "concurrency.questions_per_replica=6")
    result = score_files(out / "submission.jsonl", SPLIT / "answers.jsonl")
    rows = [json.loads(x) for x in (out / "logs" / "questions.jsonl").read_text().splitlines()]
    assert set(result["per_id"].values()) == {1}, {
        row["id"]: row["decision"]["reason_code"] for row in rows
    }
    run_json = json.loads((out / "logs" / "run.json").read_text())
    assert "E_REPLAY_MISS" not in run_json["counts"]["by_reason"]
    assert {c["backend"] for r in rows for c in r["calls"]} == {"replay"}


def test_changed_prompt_without_rerecording_fails_with_replay_miss(tmp_path):
    # A different seed changes every request body exactly as a template edit would.
    out = fresh_run(tmp_path, "a", "--set", "model.seed=1")
    rows = [json.loads(x) for x in (out / "logs" / "questions.jsonl").read_text().splitlines()]
    assert {r["decision"]["reason_code"] for r in rows} == {"E_REPLAY_MISS"}
    assert all(json.loads(x)["type"] == "abstain"
               for x in (out / "submission.jsonl").read_text().splitlines())
