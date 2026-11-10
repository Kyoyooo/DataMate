#!/usr/bin/env python3
"""Write training_code/data_manifest.json (DG §8, SPEC §13.2).

Lists every file under training_code/data (and training_code/configs) with path, SHA-256,
size, source, split and record count. Run on the build host after staging data:
    python training_code/data_generation/build_manifest.py
Deterministic: files sorted by path, no timestamps. Standard library only.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {  # first matching prefix wins; extend when new data is packaged
    "data/train/": ("Zalo AI Challenge 2026 DataMate training split, organizer-provided", "train"),
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def records(path: Path) -> int | None:
    if path.suffix == ".jsonl":
        with open(path, "rb") as fh:
            return sum(1 for line in fh if line.strip())
    return None


def build(root: Path = ROOT) -> dict:
    files = []
    for sub in ("data", "configs"):
        for p in sorted((root / sub).rglob("*")):
            if not p.is_file() or p.name == ".gitkeep":
                continue
            rel = p.relative_to(root).as_posix()
            source, split = next(((s, sp) for pre, (s, sp) in SOURCES.items()
                                  if rel.startswith(pre)), ("this repository", None))
            files.append({"path": rel, "sha256": sha256(p), "size_bytes": p.stat().st_size,
                          "source": source, "version": None, "split": split,
                          "record_count": records(p)})
    return {"format": "datamate.data_manifest.v1", "files": files,
            "omitted_base_checkpoints": [],
            "notes": "No model was trained or fine-tuned; inference weights are packaged under "
                     "/code/models. Public/private test data is not part of this manifest."}


if __name__ == "__main__":
    out = ROOT / "data_manifest.json"
    out.write_text(json.dumps(build(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(json.loads(out.read_text())['files'])} files)", file=sys.stderr)
