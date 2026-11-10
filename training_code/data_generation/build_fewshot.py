#!/usr/bin/env python3
"""Build the few-shot bank from a TRAINING run (SPEC §7.7.2, §13.2; TASKS M3-10).

Input: the /result directory of a pipeline run on the training split (its logs hold the parsed
frame and the executed SQL) and that split's reference ``answers.jsonl``. An example is kept only
when the logged answer scores correct (+1) against the reference. Output: ``fewshot.jsonl`` with
``{entry_id, source_business_id, question, metric_text, expected_type, frame, sql}``.

Leakage guards: refuses any run whose question ids are not all present in the training answers
(public/private test runs have no answers and are rejected); entries carry ``source_business_id`` so
cross-validation can exclude a fold (``solver.fewshot_exclude_businesses``).
Deterministic: entries sorted by ``entry_id`` = sha256(question + NUL + sql)[:16].

  python training_code/data_generation/build_fewshot.py --run-dir out/train_run \
      --split-dir train --out src/datamate/assets/fewshot.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def build(run_dir: Path, split_dir: Path) -> list[dict]:
    from datamate.contracts.jsonio import loads_exact
    from datamate.eval.score import score_one

    answers = {}
    for line in (split_dir / "answers.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = loads_exact(line)
            answers[row["id"]] = row
    questions = {}
    for line in (split_dir / "questions.jsonl").read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            row = json.loads(line)
            questions[row["id"]] = row
    logs = [loads_exact(x) for x in
            (run_dir / "logs" / "questions.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    unknown = [r["id"] for r in logs if r["id"] not in answers]
    if unknown:
        raise ValueError(f"{len(unknown)} logged ids have no reference answer (not a training run?), "
                         f"e.g. {unknown[0]}")
    entries = {}
    for r in logs:
        code = r.get("code")
        if not isinstance(code, str) or r["answer"].get("type") in ("abstain", "unanswerable"):
            continue  # one executed statement that produced an answer
        if score_one({"id": r["id"], **r["answer"]}, answers[r["id"]]) != 1:
            continue
        parse = next((c for c in r["calls"] if c["stage"] == "parse" and not c.get("error")), None)
        if parse is None:
            continue
        frame = json.loads(parse["content"])
        question = questions[r["id"]]["question"]
        entry_id = hashlib.sha256(f"{question}\0{code}".encode()).hexdigest()[:16]
        entries[entry_id] = {"entry_id": entry_id, "source_business_id": r["business_id"],
                             "question": question, "metric_text": frame.get("metric_text", ""),
                             "expected_type": frame["expected_type"], "frame": frame, "sql": code}
    return [entries[k] for k in sorted(entries)]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--split-dir", type=Path, required=True, help="training split (answers.jsonl required)")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)
    if not (args.split_dir / "answers.jsonl").is_file():
        print("error: refusing: no answers.jsonl in the split (training splits only)", file=sys.stderr)
        return 2
    try:
        rows = build(args.run_dir, args.split_dir)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows),
                        encoding="utf-8")
    print(f"wrote {len(rows)} examples -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
