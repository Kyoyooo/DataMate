"""Helper for the Colab bootstrap notebook: a small training subset (first K questions per business)."""

from __future__ import annotations

import json
import os
from pathlib import Path


def make_subset_split(split_dir: Path, out_dir: Path, per_business: int, max_questions: int) -> int:
    if not (split_dir / "answers.jsonl").is_file():
        raise ValueError("training splits only: answers.jsonl is missing")
    by_biz: dict[str, list[str]] = {}
    for line in (split_dir / "questions.jsonl").read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            by_biz.setdefault(json.loads(line)["business_id"], []).append(line)
    chosen: list[str] = []
    for biz in sorted(by_biz):
        chosen += by_biz[biz][:per_business]
        if len(chosen) >= max_questions:
            break
    chosen = chosen[:max_questions]
    ids = {json.loads(x)["id"] for x in chosen}
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in ("data", "rulebook.md", "calendar.csv"):
        if (split_dir / name).exists() and not (out_dir / name).exists():
            os.symlink((split_dir / name).resolve(), out_dir / name)
    (out_dir / "questions.jsonl").write_text("\n".join(chosen) + "\n", encoding="utf-8")
    answers = [x for x in (split_dir / "answers.jsonl").read_text(encoding="utf-8").splitlines()
               if x.strip() and json.loads(x)["id"] in ids]
    (out_dir / "answers.jsonl").write_text("\n".join(answers) + "\n", encoding="utf-8")
    return len(chosen)
