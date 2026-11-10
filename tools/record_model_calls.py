#!/usr/bin/env python3
"""Record real model calls for CPU replay CI (TASKS M3-13).

Run on Colab (or any host) with an OpenAI-compatible vLLM server already running, or with
``serving.mode=managed`` in the config. It runs the normal pipeline on a small, deterministic
subset of a TRAINING split and records every ModelCall through ``RecordingModelClient``.

Refuses a split without ``answers.jsonl`` (public/private test data must never be used to
build fixtures). Subset rule, independent of ids: businesses sorted by id, the first K
questions (by input line) of each business, until ``--max-questions``.

Example (see docs/runbooks/record-model-calls.md):
  python tools/record_model_calls.py --config config/colab.json --data-dir /content/train \
      --out tests/fixtures/model_calls/train_sample.jsonl --per-business 2 --max-questions 30
The replay config must use the same ``model.*`` sampling values as the recording config.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from datamate.run import main as run_main


def subset(lines: list[str], per_business: int, max_questions: int) -> list[str]:
    by_biz: dict[str, list[str]] = {}
    for line in lines:
        if line.strip():
            by_biz.setdefault(json.loads(line)["business_id"], []).append(line)
    chosen: list[str] = []
    for biz in sorted(by_biz):
        chosen += by_biz[biz][:per_business]
        if len(chosen) >= max_questions:
            break
    return chosen[:max_questions]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--config", type=Path, required=True, help="HTTP (or managed) run config")
    p.add_argument("--data-dir", type=Path, required=True, help="training split directory")
    p.add_argument("--out", type=Path, required=True, help="recording JSONL to write")
    p.add_argument("--per-business", type=int, default=2)
    p.add_argument("--max-questions", type=int, default=30)
    p.add_argument("--result-dir", type=Path, default=None, help="keep the run's /result here")
    p.add_argument("--set", dest="sets", action="append", default=[], metavar="KEY=VALUE")
    args = p.parse_args(argv)
    if not (args.data_dir / "answers.jsonl").is_file():
        print("error: refusing: data-dir has no answers.jsonl (training splits only)",
              file=sys.stderr)
        return 2
    lines = (args.data_dir / "questions.jsonl").read_text(encoding="utf-8").splitlines()
    chosen = subset(lines, args.per_business, args.max_questions)
    with tempfile.TemporaryDirectory(prefix="record-split-") as tmp:
        split = Path(tmp)
        for name in ("data", "rulebook.md", "calendar.csv"):
            if (args.data_dir / name).exists():
                os.symlink((args.data_dir / name).resolve(), split / name)
        (split / "questions.jsonl").write_text("\n".join(chosen) + "\n", encoding="utf-8")
        result = args.result_dir or Path(tmp) / "result"
        code = run_main(["--dev", "--config", str(args.config), "--data-dir", str(split),
                         "--result-dir", str(result), "--set", f"model.record_path={args.out}",
                         *[x for s in args.sets for x in ("--set", s)]])
    print(f"recorded {len(chosen)} questions -> {args.out} (run exit code {code})")
    return code


if __name__ == "__main__":
    sys.exit(main())
