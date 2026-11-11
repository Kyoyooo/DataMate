"""Development evaluation harness (SPEC §7.14, TASKS L-12). Owner: Lead. Not used at inference.

Runs the production entry point (``datamate.run.main``) on whole-business folds of a TRAINING
split, scores each fold and writes a run record that makes two runs comparable.

    python -m datamate.eval.harness run --config CFG --data-dir SPLIT --answers ANSWERS --out DIR
        [--folds 5] [--fold K | --all-folds] [--resume] [--dev --set key=value ...]
    python -m datamate.eval.harness compare RUN_A RUN_B [--allow-env-diff]

Folds: businesses sorted by sha256(business_id), fold = rank mod ``--folds`` (no randomness, no
business-specific rule). ``--resume`` skips a fold whose submission already covers every question.
``compare`` refuses runs whose environment, data or model differ unless ``--allow-env-diff``.
Never point this at public or private test data: it needs ``answers.jsonl`` (training only).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from datamate.contracts import CONTRACTS_VERSION
from datamate.eval.score import score_files

DELTA_PA_BOUND = 0.03  # organizers' reproducibility bound |PA(uploaded) - PA(rerun)| <= 0.03


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8-sig").splitlines() if x.strip()]


def business_folds(business_ids: list[str], folds: int = 5) -> dict[str, int]:
    """SPEC §7.14: businesses sorted by sha256(business_id), fold = rank mod folds."""
    ranked = sorted(business_ids, key=lambda b: hashlib.sha256(b.encode()).hexdigest())
    return {b: i % folds for i, b in enumerate(ranked)}


def fold_split(split_dir: Path, out_dir: Path, fold: int, folds: int) -> list[str]:
    """A split directory with only the questions (and answers) of the businesses in ``fold``.
    Data, rulebook and calendar are symlinked, never copied or modified."""
    lines = [x for x in (split_dir / "questions.jsonl").read_text(encoding="utf-8-sig").splitlines()
             if x.strip()]
    rows = [json.loads(x) for x in lines]
    chosen = sorted(b for b, f in business_folds(sorted({r["business_id"] for r in rows}), folds).items()
                    if f == fold)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in ("data", "rulebook.md", "calendar.csv"):
        if (split_dir / name).exists() and not (out_dir / name).exists():
            os.symlink((split_dir / name).resolve(), out_dir / name)
    kept = [x for x, r in zip(lines, rows, strict=True) if r["business_id"] in chosen]
    (out_dir / "questions.jsonl").write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    return chosen


def data_snapshot_sha256(split_dir: Path) -> str:
    """Hash of every input file of the split (relative path + content), in path order."""
    h = hashlib.sha256()
    files = [split_dir / n for n in ("questions.jsonl", "rulebook.md", "calendar.csv")]
    if (split_dir / "data").is_dir():
        files += sorted(p for p in (split_dir / "data").rglob("*") if p.is_file())
    for p in files:
        if p.is_file():
            h.update(str(p.relative_to(split_dir)).encode() + b"\0")
            with open(p, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
    return h.hexdigest()


def _git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True,
                              cwd=Path(__file__).resolve().parent).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def comparable_environment(env: dict[str, Any] | None) -> dict[str, Any]:
    """The fingerprint fields that change results: interpreter, packages, GPUs, lock."""
    env = env or {}
    gpus = [{k: g.get(k) for k in ("name", "driver_version", "compute_cap")} for g in env.get("gpus") or []]
    return {"python": env.get("python"), "packages": env.get("packages"), "gpus": gpus,
            "lock_sha256": env.get("lock_sha256")}


def fold_complete(result_dir: Path, questions: Path) -> bool:
    sub = result_dir / "submission.jsonl"
    if not sub.is_file() or not (result_dir / "logs" / "run.json").is_file():
        return False
    want = {r["id"] for r in _jsonl(questions)}
    return {r["id"] for r in _jsonl(sub)} == want


def _pct(values: list[int], p: float) -> int | None:
    v = sorted(values)
    return v[min(len(v) - 1, int(p * len(v)))] if v else None


def evaluate(result_dirs: list[Path], answers: Path) -> dict[str, Any]:
    """Merged report over fold result directories (SPEC §7.14 reports, P1 subset)."""
    preds: dict[str, dict[str, Any]] = {}
    logs: dict[str, dict[str, Any]] = {}
    total_ms = 0
    for d in result_dirs:
        for r in _jsonl(d / "submission.jsonl"):
            preds.setdefault(r["id"], r)
        for r in _jsonl(d / "logs" / "questions.jsonl"):
            logs.setdefault(r["id"], r)
        total_ms += json.loads((d / "logs" / "run.json").read_text(encoding="utf-8"))["total_ms"]
    refs = [r for r in _jsonl(answers) if r["id"] in preds]
    merged = Path(result_dirs[0]).parent / ".merged_submission.jsonl"
    merged.write_text("".join(json.dumps(preds[r["id"]], ensure_ascii=False) + "\n" for r in refs),
                      encoding="utf-8")
    ref_file = merged.with_name(".merged_answers.jsonl")
    ref_file.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in refs), encoding="utf-8")
    try:
        score = score_files(merged, ref_file)
    finally:
        merged.unlink()
        ref_file.unlink()
    per_id = score["per_id"]
    reasons: dict[str, Counter[int]] = {}
    for qid, s in per_id.items():
        reason = (logs.get(qid) or {}).get("decision", {}).get("reason_code", "(no log)")
        reasons.setdefault(reason, Counter())[s] += 1
    answered = [q for q in per_id if preds[q]["type"] not in ("abstain",)]
    ref_type = {r["id"]: r["type"] for r in refs}
    pred_unans = {q for q in per_id if preds[q]["type"] == "unanswerable"}
    true_unans = {q for q, t in ref_type.items() if t == "unanswerable"}
    elapsed = [r["elapsed_ms"] for r in logs.values() if r["id"] in per_id]
    n = len(per_id)
    return {
        "n": n, "pa": score["pa"], "correct": score["correct"], "wrong": score["wrong"],
        "abstain": score["abstain"], "by_type": score["by_type"],
        "coverage": len(answered) / n if n else None,
        "accuracy_on_answered": (sum(per_id[q] == 1 for q in answered) / len(answered)) if answered else None,
        "unanswerable_precision": (len(pred_unans & true_unans) / len(pred_unans)) if pred_unans else None,
        "unanswerable_recall": (len(pred_unans & true_unans) / len(true_unans)) if true_unans else None,
        "by_reason": {k: {"correct": c[1], "wrong": c[-1], "abstain": c[0]}
                      for k, c in sorted(reasons.items())},
        "elapsed_ms_p50": _pct(elapsed, 0.5), "elapsed_ms_p95": _pct(elapsed, 0.95),
        "projected_s": {str(k): (total_ms / 1000 / n * k if n else None) for k in (500, 1000)},
        "per_id": per_id,
    }


def run(args: argparse.Namespace) -> int:
    from datamate.run import main as run_main

    if not args.answers.is_file():
        print("error: --answers is required (training splits only)", file=sys.stderr)
        return 2
    folds = list(range(args.folds)) if args.all_folds else [args.fold]
    args.out.mkdir(parents=True, exist_ok=True)
    result_dirs, skipped, exit_codes = [], [], {}
    businesses: dict[str, list[str]] = {}
    for k in folds:
        split = args.out / f"split-fold{k}"
        businesses[str(k)] = fold_split(args.data_dir, split, k, args.folds)
        res = args.out / f"fold{k}"
        if args.resume and fold_complete(res, split / "questions.jsonl"):
            skipped.append(k)
        else:
            argv = ["--config", str(args.config), "--data-dir", str(split), "--result-dir", str(res)]
            argv += (["--dev"] if args.dev else []) + [x for s in args.set for x in ("--set", s)]
            exit_codes[str(k)] = run_main(argv)
            if exit_codes[str(k)] != 0:
                print(f"error: fold {k} exited {exit_codes[str(k)]}", file=sys.stderr)
                return exit_codes[str(k)]
        result_dirs.append(res)
    first = json.loads((result_dirs[0] / "logs" / "run.json").read_text(encoding="utf-8"))
    report = evaluate(result_dirs, args.answers)
    record = {
        "config": str(args.config), "overrides": list(args.set), "dev": bool(args.dev),
        "config_sha256": first.get("config_sha256"), "git_commit": _git_commit(),
        "contracts_version": CONTRACTS_VERSION, "template_sha256": first.get("template_sha256"),
        "environment": first.get("environment"), "model": first.get("model"),
        "data_snapshot_sha256": data_snapshot_sha256(args.data_dir), "folds": args.folds,
        "fold_ids": folds, "fold_businesses": businesses, "resumed_folds": skipped,
        "exit_codes": exit_codes, "report": report,
    }
    (args.out / "run_record.json").write_text(json.dumps(record, indent=2, ensure_ascii=False, default=str),
                                              encoding="utf-8")
    print(f"PA = {report['pa']:.4f} (n={report['n']}, correct={report['correct']}, wrong={report['wrong']}, "
          f"abstain={report['abstain']}); coverage {report['coverage']}; record: {args.out / 'run_record.json'}")
    for reason, c in report["by_reason"].items():
        print(f"  {reason:32s} correct={c['correct']:4d} wrong={c['wrong']:4d} abstain={c['abstain']:4d}")
    return 0


class Incomparable(ValueError):
    """Two run records differ in environment, data or model."""


def compare_runs(a: dict[str, Any], b: dict[str, Any], allow_env_diff: bool = False) -> dict[str, Any]:
    diffs = []
    if comparable_environment(a.get("environment")) != comparable_environment(b.get("environment")):
        diffs.append("environment")
    if a.get("data_snapshot_sha256") != b.get("data_snapshot_sha256"):
        diffs.append("data_snapshot_sha256")
    ma, mb = a.get("model") or {}, b.get("model") or {}
    if (ma.get("revision"), ma.get("sha256sums_sha256")) != (mb.get("revision"), mb.get("sha256sums_sha256")):
        diffs.append("model revision")
    if diffs and not allow_env_diff:
        raise Incomparable("runs differ in: " + ", ".join(diffs) + " (use --allow-env-diff)")
    pa_ids, pb_ids = a["report"]["per_id"], b["report"]["per_id"]
    common = sorted(set(pa_ids) & set(pb_ids))
    changed = [q for q in common if pa_ids[q] != pb_ids[q]]
    delta = abs(a["report"]["pa"] - b["report"]["pa"])
    return {"differs_in": diffs, "questions_compared": len(common), "identical": len(common) - len(changed),
            "changed": len(changed), "changed_ids": changed[:50], "pa_a": a["report"]["pa"],
            "pa_b": b["report"]["pa"], "delta_pa": delta, "within_bound": delta <= DELTA_PA_BOUND}


def compare(args: argparse.Namespace) -> int:
    a, b = (json.loads((d / "run_record.json").read_text(encoding="utf-8")) for d in (args.run_a, args.run_b))
    try:
        r = compare_runs(a, b, args.allow_env_diff)
    except Incomparable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({k: v for k, v in r.items() if k != "changed_ids"}, indent=2))
    return 0 if r["within_bound"] else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m datamate.eval.harness", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--config", type=Path, required=True)
    r.add_argument("--data-dir", type=Path, required=True)
    r.add_argument("--answers", type=Path, required=True)
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--folds", type=int, default=5)
    g = r.add_mutually_exclusive_group()
    g.add_argument("--fold", type=int, default=0)
    g.add_argument("--all-folds", action="store_true")
    r.add_argument("--resume", action="store_true")
    r.add_argument("--dev", action="store_true")
    r.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    c = sub.add_parser("compare")
    c.add_argument("run_a", type=Path)
    c.add_argument("run_b", type=Path)
    c.add_argument("--allow-env-diff", action="store_true")
    args = p.parse_args(argv)
    if args.cmd == "run" and not 0 <= args.fold < args.folds:
        p.error("--fold must be in [0, --folds)")
    return run(args) if args.cmd == "run" else compare(args)


if __name__ == "__main__":
    raise SystemExit(main())
