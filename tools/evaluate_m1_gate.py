"""Compare real held-out M1 feature predictions after M3 is available."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from datamate.eval.m1_gate import evaluate_m1_gate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split-dir", type=Path, required=True)
    parser.add_argument("--off", type=Path, required=True)
    parser.add_argument("--on", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--feature", choices=["entity_linker", "compiled_views"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate_m1_gate(args.split_dir, args.off, args.on, args.manifest, args.feature)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))
    return 0 if result["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
