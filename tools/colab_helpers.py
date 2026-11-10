"""Helpers for the Colab bootstrap notebook (TASKS M4-02). CPU-testable, standard library only.

``sha256sums``  create / check a deterministic ``SHA256SUMS`` file for a data or model snapshot
                (R2 of IMPLEMENTATION_PLAN §5.3: every snapshot is hashed and checked after copying).
``make_subset_split``  a small training subset (first K questions per business, businesses sorted)
                with symlinked data, for the first scored run.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

SUMS = "SHA256SUMS"


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def _files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file() and p.name != SUMS)


def create_sums(root: Path) -> int:
    lines = [f"{_sha(p)}  {p.relative_to(root).as_posix()}\n" for p in _files(root)]
    (root / SUMS).write_text("".join(lines), encoding="utf-8")
    return len(lines)


def check_sums(root: Path) -> list[str]:
    """Problems found (empty list = snapshot matches its SHA256SUMS exactly, no extra files)."""
    sums = root / SUMS
    if not sums.is_file():
        return [f"{SUMS} missing in {root}"]
    expected: dict[str, str] = {}
    for line in sums.read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, _, name = line.partition("  ")
            expected[name] = digest
    problems = []
    for name, digest in expected.items():
        p = root / name
        if not p.is_file():
            problems.append(f"missing: {name}")
        elif _sha(p) != digest:
            problems.append(f"hash mismatch: {name}")
    problems += [f"not in {SUMS}: {p.relative_to(root).as_posix()}" for p in _files(root)
                 if p.relative_to(root).as_posix() not in expected]
    return problems


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


def main(argv: list[str] | None = None) -> int:
    a = argv if argv is not None else sys.argv[1:]
    if len(a) == 2 and a[0] in ("create", "check"):
        root = Path(a[1])
        if a[0] == "create":
            print(f"wrote {SUMS} with {create_sums(root)} files")
            return 0
        problems = check_sums(root)
        print("OK" if not problems else "\n".join(problems[:20]))
        return 1 if problems else 0
    print("usage: colab_helpers.py create|check <dir>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
