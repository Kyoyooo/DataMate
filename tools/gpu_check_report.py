#!/usr/bin/env python3
"""Verdicts for a GPU check folder saved by notebooks/GPU_CHECK.ipynb (CPU only, no model).

Usage:  python tools/gpu_check_report.py --runs <downloaded gpu_check/<time> folder> [--json]

Prints one line per acceptance check: PASS, FAIL or NOT RUN, with the measured value. Every value
is computed from the saved files; nothing is assumed. Writes ``report.json`` into the folder.
Exit code 0 when no check FAILs (NOT RUN does not fail), 1 otherwise.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
FIXTURE = REPO / "tests" / "fixtures" / "split_mini"
PARSE_VALID_MIN = 0.98      # TASKS M3-04
FIRST_SCORED_MAX_MIN = 20   # TASKS M4-02
DELTA_PA_MAX = 0.03         # reproducibility bound (Brief)
PARAM_LIMIT = 15_000_000_000


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


class Checks:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def add(self, task: str, name: str, status: str, value: Any = None, detail: str = "") -> None:
        self.rows.append({"task": task, "check": name, "status": status, "value": value, "detail": detail})

    def verdict(self, task: str, name: str, ok: bool, value: Any = None, detail: str = "") -> None:
        self.add(task, name, "PASS" if ok else "FAIL", value, detail)

    @property
    def failed(self) -> bool:
        return any(r["status"] == "FAIL" for r in self.rows)


def _run_dir(runs: Path, tag: str) -> Path | None:
    d = runs / "runs" / tag
    return d if (d / "submission.jsonl").is_file() and (d / "logs" / "questions.jsonl").is_file() else None


def parse_stats(run: Path, answers: Path | None) -> dict[str, Any]:
    """M3-04: schema-valid QuestionFrames (pydantic validation of the raw parse output) and the
    final parse outcome (spans checked too), plus expected_type vs the reference answer type."""
    from datamate.contracts import QuestionFrame

    refs = {r["id"]: r for r in _jsonl(answers)} if answers else {}
    n = schema_ok = final_ok = typed = type_ok = 0
    for rec in _jsonl(run / "logs" / "questions.jsonl"):
        parse = [c for c in rec["calls"] if c["stage"] == "parse"]
        if not parse:
            continue
        n += 1
        try:
            frame = QuestionFrame.model_validate_json(parse[0]["content"])
            schema_ok += 1
        except ValueError:
            frame = None
        final_ok += rec["decision"].get("reason_code") != "E_PARSE_INVALID" and frame is not None
        ref = refs.get(rec["id"])
        if frame is not None and ref is not None and ref["type"] != "unanswerable":
            typed += 1
            type_ok += frame.expected_type == ref["type"]
    return {"questions_parsed": n, "schema_valid": schema_ok, "valid_after_checks": final_ok,
            "schema_valid_rate": schema_ok / n if n else None,
            "expected_type_accuracy": type_ok / typed if typed else None, "typed_questions": typed}


def solve_stats(run: Path) -> dict[str, Any]:
    """M3-05: share of questions that reached an executed SQL attempt and succeeded."""
    n = first_ok = ok_any = repairs = 0
    errors: Counter[str] = Counter()
    for rec in _jsonl(run / "logs" / "questions.jsonl"):
        attempts = rec.get("attempts") or []
        if not attempts:
            continue
        n += 1
        first_ok += bool(attempts[0].get("ok"))
        ok_any += any(a.get("ok") for a in attempts)
        repairs += sum(a.get("stage") == "repair" for a in attempts)
        for a in attempts:
            if not a.get("ok") and a.get("error_code"):
                errors[a["error_code"]] += 1
    return {"questions_solved": n, "first_attempt_ok_rate": first_ok / n if n else None,
            "ok_after_repair_rate": ok_any / n if n else None, "repair_attempts": repairs,
            "attempt_errors": dict(errors.most_common())}


def reasons(run: Path) -> Counter[str]:
    return Counter(r["decision"].get("reason_code", "") for r in _jsonl(run / "logs" / "questions.jsonl"))


def precheck(run: Path, data_dir: Path) -> tuple[bool, str]:
    r = subprocess.run([sys.executable, str(HERE / "precheck.py"), "--data-dir", str(data_dir),
                        "--result-dir", str(run)], capture_output=True, text=True)
    fails = [x for x in r.stdout.splitlines() if x.startswith("FAIL")]
    return r.returncode == 0, "; ".join(fails[:3])


def replay_fixture(recording: Path, colab_fixture: Path) -> tuple[bool, str]:
    """M3-13: replaying the real-model recording on CPU must reproduce the Colab fixture answers."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        r = subprocess.run([sys.executable, "-m", "datamate.run", "--dev", "--config",
                            str(REPO / "config" / "replay.json"), "--data-dir", str(FIXTURE),
                            "--result-dir", str(out), "--set", f"work_dir={Path(tmp) / 'work'}",
                            "--set", f"model.replay_path={recording}"],
                           capture_output=True, text=True, cwd=REPO)
        if r.returncode != 0:
            return False, f"replay run exited {r.returncode}: {r.stderr[-300:]}"
        misses = reasons(out).get("E_REPLAY_MISS", 0)
        same = (out / "submission.jsonl").read_bytes() == (colab_fixture / "submission.jsonl").read_bytes()
        return same and misses == 0, f"replay misses {misses}; submission identical to the GPU run: {same}"


def report(runs: Path) -> Checks:
    from datamate.eval.score import score_files

    ck = Checks()
    meta = json.loads((runs / "meta.json").read_text(encoding="utf-8"))
    answers = runs / "answers.jsonl"
    status = meta.get("status", {})

    # environment and model limits
    ck.add("env", "GPU", "INFO", f"{meta.get('gpu')} (cc {meta.get('compute_capability')})",
           "" if meta.get("compute_capability") == "12.0" else "not the competition GPU type: speed/memory indicative only")
    ck.add("env", "commit / vLLM", "INFO", f"{str(meta.get('commit'))[:10]} / {meta.get('vllm')}")
    cp = runs / "env" / "count_params.json"
    if cp.is_file():
        params = json.loads(cp.read_text())["parameters"]
        ck.verdict("DEC-3", "total parameters <= 15 B", params <= PARAM_LIMIT, f"{params / 1e9:.3f} B")
    else:
        ck.add("DEC-3", "total parameters <= 15 B", "NOT RUN")

    # M3-02 / M3-13: fixture with the real model
    fx = _run_dir(runs, "fixture")
    if fx is None:
        ck.add("M3-02", "real HTTP calls on the fixture", "NOT RUN", detail=str(status.get("fixture")))
    else:
        calls = [c for r in _jsonl(fx / "logs" / "questions.jsonl") for c in r["calls"]]
        bad = [c for c in calls if c.get("error") or (c.get("transport") or {}).get("http_status") != 200]
        ck.verdict("M3-02", "real HTTP calls on the fixture", bool(calls) and not bad,
                   f"{len(calls) - len(bad)}/{len(calls)} calls HTTP 200 without error",
                   ", ".join(sorted({str(c.get('error')) for c in bad}))[:200])
        fx_pa = score_files(fx / "submission.jsonl", FIXTURE / "answers.jsonl")["pa"]
        ck.add("M3-02", "fixture PA with the real model", "INFO", round(fx_pa, 4))
        rec = runs / "split_mini.recorded.jsonl"
        if rec.is_file():
            ok, detail = replay_fixture(rec, fx)
            ck.verdict("M3-13", "CPU replay of the real recording reproduces the GPU run", ok, None, detail)
        else:
            ck.add("M3-13", "CPU replay of the real recording", "NOT RUN", detail="recording missing")

    # training runs
    a1, a2 = _run_dir(runs, "train-A1"), _run_dir(runs, "train-A2")
    if a1 is None:
        ck.add("M3-04", "parse validity", "NOT RUN", detail=str(status.get("train-A1")))
    else:
        p = parse_stats(a1, answers)
        ck.verdict("M3-04", f"schema-valid frames >= {PARSE_VALID_MIN:.0%}",
                   p["schema_valid_rate"] is not None and p["schema_valid_rate"] >= PARSE_VALID_MIN,
                   p["schema_valid_rate"], f"{p['schema_valid']}/{p['questions_parsed']}; "
                   f"valid after span checks {p['valid_after_checks']}")
        ck.add("M3-04", "expected_type accuracy vs answers", "INFO", p["expected_type_accuracy"],
               f"over {p['typed_questions']} answerable questions")
        s = solve_stats(a1)
        ck.add("M3-05", "solve success (first attempt / after repair)", "INFO",
               f"{s['first_attempt_ok_rate']} / {s['ok_after_repair_rate']}",
               f"repairs {s['repair_attempts']}; attempt errors {s['attempt_errors']}")
        rc = reasons(a1)
        ck.verdict("M3-03", "no context overflow in the training run", rc.get("E_CONTEXT_OVERFLOW", 0) == 0,
                   rc.get("E_CONTEXT_OVERFLOW", 0))
        ck.add("L-05", "training run reason codes", "INFO", dict(rc.most_common(8)))
        r1 = score_files(a1 / "submission.jsonl", answers)
        ck.add("L-05", "training-subset PA (run 1)", "INFO", round(r1["pa"], 4),
               f"n={r1['n']} correct={r1['correct']} wrong={r1['wrong']} abstain={r1['abstain']}")
        first = (meta.get("times_s") or {}).get("first scored training run")
        if first is not None:
            ck.verdict("M4-02", f"fresh session to first scored run <= {FIRST_SCORED_MAX_MIN} min",
                       first / 60 <= FIRST_SCORED_MAX_MIN, f"{first / 60:.1f} min")
        bake = _load("bakeoff")
        t = bake.throughput(a1)
        ck.add("M4-08", "throughput", "INFO",
               f"{t['questions_per_min']:.1f} q/min; projected 500 questions {t['projected_500_questions_s']:.0f} s",
               "single replica on this GPU; the image runs two")
        if a2 is not None:
            d = bake.compare_determinism(a1, a2, answers)
            ck.verdict("L-15", f"two identical runs |dPA| <= {DELTA_PA_MAX}", d["delta_pa"] <= DELTA_PA_MAX,
                       round(d["delta_pa"], 4), f"answers changed {d['answers_changed']}/{d['questions']}; "
                       f"identical raw output rate {d['identical_output_rate']}")
        else:
            ck.add("L-15", "two identical runs", "NOT RUN", detail=str(status.get("train-A2")))

    # records: every run must pass the submission/log precheck; thinking rule
    inputs = {"fixture": FIXTURE, "train-A1": runs / "subset", "train-A2": runs / "subset",
              "thinking-on": runs / "subset_think", "restart": runs / "subset"}
    for tag, data in inputs.items():
        d = _run_dir(runs, tag)
        if d is None:
            continue
        if not (data / "questions.jsonl").is_file():
            ck.add("M4-07", f"precheck of {tag}", "NOT RUN", detail=f"{data}/questions.jsonl missing")
            continue
        ok, detail = precheck(d, data)
        ck.verdict("M4-07", f"precheck of {tag} (submission + logs)", ok, None, detail)
    off = [r for t in ("fixture", "train-A1") if (d := _run_dir(runs, t)) for r in _jsonl(d / "logs" / "questions.jsonl")]
    if off:
        ck.verdict("M4-19", "thinking off -> thinking is null", all(r["thinking"] is None for r in off),
                   sum(r["thinking"] is not None for r in off), "records with non-null thinking")
    th = _run_dir(runs, "thinking-on")
    if th is None:
        ck.add("M4-19", "thinking on -> thinking logged", "NOT RUN", detail=str(status.get("thinking-on")))
    else:
        recs = _jsonl(th / "logs" / "questions.jsonl")
        with_calls = [r for r in recs if r["calls"]]
        exact = all(r["thinking"] is not None and len(r["thinking"]) == len(r["calls"]) for r in with_calls)
        nonempty = sum(any(x for x in (r["thinking"] or [])) for r in with_calls)
        ck.verdict("M4-19", "thinking on -> one entry per call, generated text", exact and nonempty > 0,
                   f"{nonempty}/{len(with_calls)} records with reasoning text")

    # M4-03 restart
    rs = _run_dir(runs, "restart")
    st = status.get("restart") or {}
    if rs is None or not st.get("killed_at_s"):
        ck.add("M4-03", "replica restart during a run", "NOT RUN",
               detail="server not killed (run finished first?)" if rs is not None else str(st))
    else:
        run_json = json.loads((rs / "logs" / "run.json").read_text())
        events = [e["event"] for e in (run_json.get("replicas") or {}).get("events", [])]
        restarted = "died" in events and "restart" in events and events.count("ready") >= 2
        ck.verdict("M4-03", "replica restart during a run", restarted and st.get("exit") == 0,
                   " -> ".join(events), f"exit {st.get('exit')}; killed at {st.get('killed_at_s')} s")

    # M3-03 real-tokenizer schema budget over all training questions
    ctx = runs / "context_check.json"
    if ctx.is_file():
        c = json.loads(ctx.read_text())
        ck.verdict("M3-03", "all training questions fit the schema budget (real tokenizer)",
                   bool(c.get("valid")) and bool(c.get("production_tokenizer_verified")),
                   f"{c.get('questions')} questions, budget {c.get('schema_budget_tokens')}",
                   f"tokenizer {c.get('tokenizer')}; failures {len(c.get('failures') or [])}")
    else:
        ck.add("M3-03", "schema budget with the real tokenizer", "NOT RUN", detail=str(status.get("context_check")))
    return ck


def show(ck: Checks) -> None:
    for r in ck.rows:
        value = "" if r["value"] is None else f" = {r['value']}"
        print(f"{r['status']:<8} {r['task']:<6} {r['check']}{value}" + (f"  ({r['detail']})" if r["detail"] else ""))
    print("\nNothing here chooses the model (DEC-3) or a template: the team lead decides.")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--runs", type=Path, required=True)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    ck = report(args.runs)
    (args.runs / "report.json").write_text(json.dumps(ck.rows, indent=2, default=str), encoding="utf-8")
    print(json.dumps(ck.rows, indent=2, default=str)) if args.json else show(ck)
    return 1 if ck.failed else 0


if __name__ == "__main__":
    sys.exit(main())
