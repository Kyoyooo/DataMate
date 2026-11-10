#!/usr/bin/env python3
"""Count model parameters from shipped safetensors files (SPEC §13.1, TASKS M4-13).

Sums the element count of EVERY tensor in every ``*.safetensors`` file under a directory
(vision towers, embeddings and all MoE experts included), reading only the file headers: no
torch, no weights loaded. This is the number to declare for the 15 B total limit.

Usage:  python tools/count_params.py /code/models/<model> [--json]
Also reports tensors listed in ``model.safetensors.index.json`` but missing on disk, and
tied tensors that appear in more than one shard (counted once per name).
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from pathlib import Path

LIMIT = 15_000_000_000


def read_header(path: Path) -> dict:
    with open(path, "rb") as fh:
        raw = fh.read(8)
        if len(raw) != 8:
            raise ValueError(f"{path}: too short to be a safetensors file")
        (n,) = struct.unpack("<Q", raw)
        if n > 100 * 1024 * 1024:
            raise ValueError(f"{path}: implausible header length {n}")
        return json.loads(fh.read(n))


def count_dir(root: Path) -> dict:
    files = sorted(root.rglob("*.safetensors"))
    if not files:
        raise FileNotFoundError(f"no *.safetensors under {root}")
    seen: dict[str, int] = {}
    per_file: dict[str, int] = {}
    dtypes: dict[str, int] = {}
    duplicates: list[str] = []
    for f in files:
        total = 0
        for name, meta in read_header(f).items():
            if name == "__metadata__":
                continue
            n = math.prod(meta["shape"])  # a scalar tensor has shape [] -> 1
            total += n
            dtypes[meta["dtype"]] = dtypes.get(meta["dtype"], 0) + n
            if name in seen:
                duplicates.append(name)
            else:
                seen[name] = n
        per_file[str(f.relative_to(root))] = total
    missing: list[str] = []
    index = root / "model.safetensors.index.json"
    if index.is_file():
        missing = sorted(set(json.loads(index.read_text())["weight_map"]) - set(seen))
    return {"parameters": sum(seen.values()), "files": per_file, "tensors": len(seen),
            "parameters_by_dtype": dict(sorted(dtypes.items())),
            "duplicate_tensor_names": sorted(set(duplicates)),
            "missing_from_disk": missing, "limit": LIMIT, "within_limit": sum(seen.values()) <= LIMIT}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("model_dir", type=Path)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    try:
        result = count_dir(args.model_dir)
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"{result['parameters']:,} parameters in {result['tensors']} tensors "
              f"({result['parameters'] / 1e9:.3f} B); limit {LIMIT:,}: "
              f"{'OK' if result['within_limit'] else 'EXCEEDED'}")
        for name, n in result["files"].items():
            print(f"  {name}: {n:,}")
        if result["missing_from_disk"]:
            print(f"WARNING: {len(result['missing_from_disk'])} indexed tensors missing on disk")
    return 0 if result["within_limit"] and not result["missing_from_disk"] else 1


if __name__ == "__main__":
    sys.exit(main())
