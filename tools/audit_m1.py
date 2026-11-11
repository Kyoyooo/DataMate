"""Run M1-01/M1-14 against an explicitly declared training split."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from datamate.catalog.audit import audit_training


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--role", choices=["train"], required=True)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    report = audit_training(args.split_dir, args.output_dir, role=args.role, limit=args.limit)
    print(json.dumps(report, ensure_ascii=False, default=str))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
