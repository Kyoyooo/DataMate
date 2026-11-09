"""Generate a synthetic XLSX and measure only M1 setup, with independent result checks."""

from __future__ import annotations

import argparse
import json
import platform
import time
from datetime import date, timedelta
from pathlib import Path

import duckdb
from openpyxl import Workbook

from datamate.catalog import setup_business
from datamate.config import RunConfig


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--rows", type=int, default=300000)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    source = args.output_dir / "input"
    source.mkdir(exist_ok=True)
    path = source / "sales.xlsx"
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("Sales")
    sheet.append(["Order ID", "Date", "Name", "Quantity", "Amount", "Status"])
    for index in range(1, args.rows + 1):
        sheet.append(
            [
                f"O{index:07d}",
                date(2025, 1, 1) + timedelta(days=index % 365),
                f"Product {index % 10}",
                index % 5 + 1,
                index * 100,
                "Completed" if index % 2 else "Cancelled",
            ]
        )
    workbook.save(path)
    print(json.dumps({"generated_rows": args.rows, "bytes": path.stat().st_size}), flush=True)
    start = time.perf_counter()
    catalog = setup_business(source, "benchmark", RunConfig(work_dir=str(args.output_dir / "work")))
    elapsed = time.perf_counter() - start
    if catalog.status != "ready":
        raise RuntimeError(str(catalog.warnings))
    with duckdb.connect(catalog.db_path, read_only=True) as connection:
        table = catalog.tables[0].name
        actual = connection.execute(f'SELECT COUNT(*), SUM(amount) FROM "{table}"').fetchone()
    expected = (args.rows, args.rows * (args.rows + 1) // 2 * 100)
    result = {
        "rows": args.rows,
        "elapsed_s": elapsed,
        "budget_s": 60,
        "within_60s_on_this_host": elapsed <= 60,
        "actual": list(actual),
        "expected": list(expected),
        "correct": actual == expected,
        "platform": platform.platform(),
        "processor": platform.processor(),
        "reference_hardware_verified": False,
    }
    (args.output_dir / "benchmark.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)
    return 0 if result["correct"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
