"""Bake-off helpers (TASKS M3-01, M3-08). Used by notebooks/BAKEOFF_G4.ipynb; CPU-testable.

Nothing here decides DEC-3. It produces evidence: per-candidate license / release-date / parameter
checks, held-out PA on whole training businesses, determinism between two identical runs, and
throughput. Every claim is computed from files; a field that cannot be verified is reported as
``UNVERIFIED`` rather than guessed.
"""

from __future__ import annotations

import hashlib
import json
import os
import statistics
from datetime import date
from pathlib import Path
from typing import Any

RELEASE_CUTOFF = date(2026, 10, 26)  # weights must be public BEFORE this date (Brief §5.2-2)
PARAM_LIMIT = 15_000_000_000
PERMISSIVE = {"apache-2.0", "mit", "bsd-3-clause", "bsd-2-clause", "cc-by-4.0", "openrail",
              "llama3", "llama3.1", "llama3.2", "gemma"}  # starting list; the lead confirms terms


# ------------------------------------------------------------------ candidate verification


def verify_candidate(spec: dict[str, Any], hub: dict[str, Any] | None, params: int | None,
                     other_params: int = 0) -> dict[str, Any]:
    """``hub``: {license, first_commit_date (YYYY-MM-DD), sha} fetched from the model hub or None.

    Returns one record with PASS / FAIL / UNVERIFIED per requirement. ``first_commit_date`` is the
    date of the earliest commit of the repository: an upper bound on the public release date that
    a human still has to confirm against the model card.
    """
    rec: dict[str, Any] = {"name": spec["name"], "repo": spec["repo"], "revision": spec.get("revision")}
    rec["revision_fixed"] = ("PASS" if spec.get("revision") and len(spec["revision"]) == 40 else "FAIL")
    if hub is None:
        rec.update(license="UNVERIFIED", release_date="UNVERIFIED")
    else:
        lic = (hub.get("license") or "").lower()
        rec["license"] = ("PASS" if lic in PERMISSIVE else "UNVERIFIED") if lic else "UNVERIFIED"
        rec["license_text"] = hub.get("license")
        rec["hub_sha"] = hub.get("sha")
        first = hub.get("first_commit_date")
        rec["first_commit_date"] = first
        rec["release_date"] = ("UNVERIFIED" if not first else
                               "PASS" if date.fromisoformat(first) < RELEASE_CUTOFF else "FAIL")
        if hub.get("sha") and spec.get("revision") and hub["sha"] != spec["revision"]:
            rec["revision_fixed"] = "FAIL"
    if params is None:
        rec["parameters"], rec["param_limit"] = None, "UNVERIFIED"
    else:
        rec["parameters"] = params
        rec["param_limit"] = "PASS" if params + other_params <= PARAM_LIMIT else "FAIL"
    rec["all_pass"] = all(rec[k] == "PASS" for k in
                          ("revision_fixed", "license", "release_date", "param_limit"))
    return rec


def gpu_memory_fraction(total_gib: float, cap_gib: float = 32.0) -> float:
    """``gpu_memory_utilization`` that emulates an RTX 5090 (32 GB) on a larger Colab GPU."""
    if total_gib <= 0:
        raise ValueError("total GPU memory must be positive")
    return round(min(0.95, cap_gib / total_gib), 3)


# ------------------------------------------------------------------ folds and subsets


def business_folds(business_ids: list[str], folds: int = 5) -> dict[str, int]:
    """SPEC §7.14: businesses sorted by sha256(business_id), fold = rank mod folds."""
    ranked = sorted(business_ids, key=lambda b: hashlib.sha256(b.encode()).hexdigest())
    return {b: i % folds for i, b in enumerate(ranked)}


def make_fold_split(split_dir: Path, out_dir: Path, fold: int, folds: int = 5,
                    max_per_business: int | None = None) -> list[str]:
    """Split directory containing only the questions of the businesses in ``fold`` (whole
    businesses, never a partial one). Data is symlinked; returns the business ids."""
    lines = [x for x in (split_dir / "questions.jsonl").read_text(encoding="utf-8-sig").splitlines()
             if x.strip()]
    rows = [json.loads(x) for x in lines]
    assign = business_folds(sorted({r["business_id"] for r in rows}), folds)
    chosen = sorted(b for b, f in assign.items() if f == fold)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in ("data", "rulebook.md", "calendar.csv"):
        if (split_dir / name).exists() and not (out_dir / name).exists():
            os.symlink((split_dir / name).resolve(), out_dir / name)
    kept: list[str] = []
    seen: dict[str, int] = {}
    ids = set()
    for line, r in zip(lines, rows, strict=True):
        if r["business_id"] in chosen and (max_per_business is None
                                           or seen.get(r["business_id"], 0) < max_per_business):
            seen[r["business_id"]] = seen.get(r["business_id"], 0) + 1
            kept.append(line)
            ids.add(r["id"])
    (out_dir / "questions.jsonl").write_text("\n".join(kept) + "\n", encoding="utf-8")
    if (split_dir / "answers.jsonl").is_file():
        ans = [x for x in (split_dir / "answers.jsonl").read_text(encoding="utf-8").splitlines()
               if x.strip() and json.loads(x)["id"] in ids]
        (out_dir / "answers.jsonl").write_text("\n".join(ans) + "\n", encoding="utf-8")
    return chosen


# ------------------------------------------------------------------ run analysis


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _calls(run_dir: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for rec in _jsonl(run_dir / "logs" / "questions.jsonl"):
        for c in rec["calls"]:
            out[c["call_id"]] = c
    return out


def compare_determinism(run_a: Path, run_b: Path, answers: Path | None = None) -> dict[str, Any]:
    """Two runs of the same input/config/concurrency. Counts how often an IDENTICAL request
    (same ``request_sha256``) produced a DIFFERENT raw output, and what that did to the answers."""
    a_calls, b_calls = _calls(run_a), _calls(run_b)
    same_request = differing_output = unmatched = 0
    by_stage: dict[str, list[int]] = {}
    for cid, ca in a_calls.items():
        cb = b_calls.get(cid)
        if cb is None or cb["request_sha256"] != ca["request_sha256"]:
            unmatched += 1  # the request itself differed (a different earlier answer changed it)
            continue
        same_request += 1
        diff = int(ca["content"] != cb["content"] or ca.get("reasoning") != cb.get("reasoning"))
        differing_output += diff
        by_stage.setdefault(ca["stage"], [0, 0])
        by_stage[ca["stage"]][0] += 1
        by_stage[ca["stage"]][1] += diff
    sub_a = {r["id"]: r for r in _jsonl(run_a / "submission.jsonl")}
    sub_b = {r["id"]: r for r in _jsonl(run_b / "submission.jsonl")}
    changed = sorted(i for i in sub_a if sub_a[i] != sub_b.get(i))
    report: dict[str, Any] = {
        "questions": len(sub_a), "answers_changed": len(changed), "changed_ids": changed[:20],
        "calls_total": len(a_calls), "calls_same_request": same_request,
        "calls_same_request_different_output": differing_output, "calls_request_differs": unmatched,
        "identical_output_rate": (1 - differing_output / same_request) if same_request else None,
        "by_stage": {k: {"same_request": v[0], "different_output": v[1]} for k, v in sorted(by_stage.items())},
        "submissions_byte_identical": (run_a / "submission.jsonl").read_bytes()
        == (run_b / "submission.jsonl").read_bytes(),
    }
    if answers is not None:
        from datamate.eval.score import score_files

        pa_a = score_files(run_a / "submission.jsonl", answers)["pa"]
        pa_b = score_files(run_b / "submission.jsonl", answers)["pa"]
        report.update(pa_a=pa_a, pa_b=pa_b, delta_pa=abs(pa_a - pa_b))
    return report


def throughput(run_dir: Path) -> dict[str, Any]:
    run = json.loads((run_dir / "logs" / "run.json").read_text(encoding="utf-8"))
    recs = _jsonl(run_dir / "logs" / "questions.jsonl")
    elapsed = sorted(r["elapsed_ms"] for r in recs)
    prompt = completion = 0
    for r in recs:
        for c in r["calls"]:
            body = (c.get("transport") or {}).get("response_body")
            if body:
                try:
                    usage = json.loads(body).get("usage") or {}
                except json.JSONDecodeError:
                    continue
                prompt += usage.get("prompt_tokens", 0)
                completion += usage.get("completion_tokens", 0)
    total_s = run["total_ms"] / 1000
    loads = (run.get("timings") or {}).get("replica_load_ms") or []

    def pct(p: float) -> int | None:
        return elapsed[min(len(elapsed) - 1, int(p * len(elapsed)))] if elapsed else None

    return {"questions": len(recs), "wall_s": total_s, "load_ms": max([x for x in loads if x], default=None),
            "questions_per_min": len(recs) / total_s * 60 if total_s else None,
            "elapsed_ms_p50": pct(0.5), "elapsed_ms_p95": pct(0.95),
            "elapsed_ms_mean": statistics.fmean(elapsed) if elapsed else None,
            "prompt_tokens": prompt, "completion_tokens": completion,
            "completion_tokens_per_s": completion / total_s if total_s else None,
            "projected_500_questions_s": (max([x for x in loads if x], default=0) / 1000
                                          + (total_s - max([x for x in loads if x], default=0) / 1000)
                                          / max(len(recs), 1) * 500)}


def run_summary(run_dir: Path, answers: Path | None) -> dict[str, Any]:
    from datamate.eval.score import score_files

    out: dict[str, Any] = {"throughput": throughput(run_dir)}
    if answers is not None:
        r = score_files(run_dir / "submission.jsonl", answers)
        out["pa"] = {k: r[k] for k in ("pa", "n", "correct", "wrong", "abstain") if k in r}
    run = json.loads((run_dir / "logs" / "run.json").read_text(encoding="utf-8"))
    out["by_reason"] = run["counts"]["by_reason"]
    out["environment"] = run.get("environment")
    return out
