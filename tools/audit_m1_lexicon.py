"""Record training-only alias coverage and ambiguity hints without rewriting data values."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from datamate.lexicon import abbreviation_hints, fold, load_abbreviations


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split-dir", type=Path, required=True)
    parser.add_argument("--role", choices=["train"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    path = args.split_dir / "questions.jsonl"
    questions = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]
    aliases, used, ambiguous = load_abbreviations(), Counter(), Counter()
    for question in questions:
        used.update(
            fold(m.group())
            for m in re.finditer(r"(?<!\w)[^\W\d_]+(?!\w)", question["question"])
            if fold(m.group()) in aliases
        )
        ambiguous.update(hint["token"] for hint in abbreviation_hints(question["question"]))
    report = {
        "source_role": args.role,
        "questions_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "questions": len(questions),
        "expanded_alias_counts": dict(used),
        "contextual_alias_counts": dict(ambiguous),
        "automatic_contextual_expansion": False,
        "policy": "Only declared whole-token aliases expand; original questions remain authoritative. Units, product codes, proper names and ambiguous tokens remain available unchanged.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
