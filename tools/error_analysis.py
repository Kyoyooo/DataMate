#!/usr/bin/env python3
"""Error analysis of a training run (TASKS L-14). CPU only; never for test splits.

Usage:  python tools/error_analysis.py --run <result dir> [--run <dir> ...] --answers answers.jsonl
            [--min-share 0.01] [--markdown report.md]

Every question that did not score +1 is put in exactly one class, chosen from what the logs
record (no guessing):
  * outcome-specific classes: ``false_unanswerable`` (we said unanswerable, an answer existed),
    ``missed_unanswerable`` (we answered, the reference is unanswerable), ``type_mismatch:<ours>-><ref>``,
    ``wrong_value:<type>`` (right type, wrong value; split by question type);
  * otherwise ``abstain:<reason code>`` (the reason the pipeline gave).
Each class gets an owning role (M1 data/catalog, M2 rules/time/decision/formatting, M3 model/
prompts/SQL, M4 runtime) from the class itself, so a class above ``--min-share`` of all questions
always has an owner; the lead turns those into tasks. Sample ids are listed for inspection.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

# Owner by reason code (contracts/codes.py). An unknown code falls back to the lead.
OWNER = {
    "E_INPUT_INVALID": "M4", "E_INPUT_BUSINESS_MISSING": "M1", "E_BUSINESS_SETUP": "M1",
    "E_PARSE_INVALID": "M3", "E_SOLVER_OUTPUT_INVALID": "M3", "E_SQL_EXEC": "M3",
    "E_SQL_NOT_SELECT": "M3", "E_SQL_NONDETERMINISTIC": "M3", "E_SQL_TIMEOUT": "M3",
    "E_EMPTY_RESULT": "M3", "E_NO_SUCCESS": "M3", "E_TYPE_CONTRACT": "M3", "E_EXEC_CRASH": "M3",
    "E_CONTEXT_OVERFLOW": "M3", "D_IMPLAUSIBLE": "M3",
    "E_MODEL_ERROR": "M4", "E_MODEL_TIMEOUT": "M4", "E_MODEL_TRANSPORT": "M4",
    "E_REPLICA_DOWN": "M4", "E_DEADLINE": "M4", "E_GLOBAL_STOP": "M4", "E_INTERNAL": "M4",
    "E_DUPLICATE_WRITE": "M4",
    "E_TIME_UNSUPPORTED": "M2", "D_UNCLEAR": "M2", "D_UNANSWERABLE_CONFIRMED": "M2",
    "D_UNANSWERABLE_OUT_OF_RANGE": "M2", "D_ANSWER": "M3",
    "E_SCRIPT_MISS": "dev-only", "E_REPLAY_MISS": "dev-only",
}
OUTCOME_OWNER = {"false_unanswerable": "M2", "missed_unanswerable": "M2", "type_mismatch": "M3",
                 "wrong_value": "M3"}
HINT = {
    "false_unanswerable": "gate said unanswerable (coverage / missing field) but a reference answer exists",
    "missed_unanswerable": "answered a question whose reference is unanswerable",
    "type_mismatch": "parse expected_type or formatter produced the wrong answer type",
    "wrong_value": "right type, wrong value: SQL logic, time window, rounding or ordering",
}


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8-sig").splitlines() if x.strip()]


def classify(pred: dict[str, Any] | None, ref: dict[str, Any], log: dict[str, Any] | None,
             score: int) -> str | None:
    if score == 1:
        return None
    reason = ((log or {}).get("decision") or {}).get("reason_code") or "(no log)"
    ptype = (pred or {}).get("type")
    if ptype in (None, "abstain"):
        return f"abstain:{reason}"
    rtype = ref["type"]
    if ptype == "unanswerable" and rtype != "unanswerable":
        return "false_unanswerable"
    if rtype == "unanswerable":
        return "missed_unanswerable"
    if ptype != rtype:
        return f"type_mismatch:{ptype}->{rtype}"
    return f"wrong_value:{rtype}"


def owner_of(cls: str) -> str:
    head, _, tail = cls.partition(":")
    if head == "abstain":
        return OWNER.get(tail, "L")
    return OUTCOME_OWNER.get(head, "L")


def analyze(runs: list[Path], answers: Path, min_share: float = 0.01, samples: int = 5) -> dict[str, Any]:
    from datamate.eval.score import score_one

    preds: dict[str, dict[str, Any]] = {}
    logs: dict[str, dict[str, Any]] = {}
    for run in runs:
        for r in _jsonl(run / "submission.jsonl"):
            preds.setdefault(r["id"], r)
        for r in _jsonl(run / "logs" / "questions.jsonl"):
            logs.setdefault(r["id"], r)
    refs = [r for r in _jsonl(answers) if r["id"] in preds]
    n = len(refs)
    classes: dict[str, list[str]] = defaultdict(list)
    wrong_or_abstain: Counter[str] = Counter()
    for ref in refs:
        s = score_one(preds.get(ref["id"]), ref)
        cls = classify(preds.get(ref["id"]), ref, logs.get(ref["id"]), s)
        if cls:
            classes[cls].append(ref["id"])
            wrong_or_abstain["wrong" if s == -1 else "abstain"] += 1
    rows = []
    for cls, ids in sorted(classes.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        share = len(ids) / n if n else 0.0
        head = cls.partition(":")[0]
        rows.append({"class": cls, "count": len(ids), "share": share, "owner": owner_of(cls),
                     "pa_cost": len(ids) / n * (2 if head != "abstain" else 1) if n else 0.0,
                     "above_threshold": share > min_share, "hint": HINT.get(head, ""),
                     "sample_ids": sorted(ids)[:samples]})
    return {"questions": n, "not_correct": sum(len(v) for v in classes.values()),
            "wrong": wrong_or_abstain["wrong"], "abstain": wrong_or_abstain["abstain"],
            "min_share": min_share, "classes": rows,
            "unowned_above_threshold": [r["class"] for r in rows if r["above_threshold"] and r["owner"] == "L"]}


def markdown(rep: dict[str, Any]) -> str:
    lines = [f"# Error analysis ({rep['questions']} questions; {rep['wrong']} wrong, {rep['abstain']} abstain)",
             "", f"Classes above {rep['min_share']:.0%} of questions need an owner and a task (TASKS L-14). "
             "`PA cost` = PA gained if the class were fixed (a wrong answer costs 2, an abstain 1).", "",
             "| Class | Count | Share | PA cost | Owner | Task | Sample ids | Hint |", "|---|---|---|---|---|---|---|---|"]
    for r in rep["classes"]:
        flag = "**" if r["above_threshold"] else ""
        lines.append(f"| {flag}{r['class']}{flag} | {r['count']} | {r['share']:.1%} | {r['pa_cost']:.3f} | "
                     f"{r['owner']} | (lead) | {', '.join(r['sample_ids'])} | {r['hint']} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--run", type=Path, action="append", required=True)
    p.add_argument("--answers", type=Path, required=True, help="training answers.jsonl (never test data)")
    p.add_argument("--min-share", type=float, default=0.01)
    p.add_argument("--markdown", type=Path)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    rep = analyze(args.run, args.answers, args.min_share)
    if args.markdown:
        args.markdown.write_text(markdown(rep), encoding="utf-8")
    if args.json:
        print(json.dumps(rep, indent=2, ensure_ascii=False))
    else:
        print(markdown(rep))
    return 1 if rep["unowned_above_threshold"] else 0


if __name__ == "__main__":
    sys.exit(main())
