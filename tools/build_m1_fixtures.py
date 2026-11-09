"""Build small reproducible ingestion fixtures and independent fake catalog artifacts."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from openpyxl import Workbook

from datamate.catalog import make_fake_catalog, save_catalog

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    folder = ROOT / "tests/fixtures/businesses"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "cp1258.csv").write_bytes("Ten,Ma\nCơm,001\n".encode("cp1258"))
    (folder / "utf8_sig.csv").write_text("Mã;Tên;Tiền\n001;Cà phê;150k\n", encoding="utf-8-sig")
    (folder / "utf16.csv").write_text("Mã;Tên;Tiền\n001;Cà phê;150k\n", encoding="utf-16")
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Blocks"
    for row in [
        ["Sales", None, "Stock"],
        ["Ngày", "SL", None],
        ["01/02/2025", 2, 3],
        [None] * 3,
        [None] * 3,
        ["Mã", "Tên", "Tiền"],
        ["001", "Cà phê", 100],
        ["002", "Trà đào", 200],
        ["Tổng cộng", None, 300],
        ["First note", None, None],
        ["Second note", None, None],
    ]:
        sheet.append(row)
    workbook.create_sheet("Empty").append(["Code", "Name"])
    workbook.save(folder / "blocks.xlsx")
    database = folder / "wal.sqlite"
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.executescript(
            "DROP TABLE IF EXISTS sales; DROP VIEW IF EXISTS totals; CREATE TABLE sales(code TEXT, amount INTEGER); INSERT INTO sales VALUES('001',100); CREATE VIEW totals AS SELECT SUM(amount) AS amount FROM sales;"
        )
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()
    manifests = []
    for scenario in ("sales", "mixed_types", "missing_fields"):
        catalog = make_fake_catalog(ROOT / "tests/fixtures/catalogs/generated", scenario)
        path = Path(catalog.db_path).parent / "catalog.json"
        save_catalog(catalog, path)
        manifests.append(
            {
                "scenario": scenario,
                "catalog": str(path.relative_to(ROOT)),
                "database": str(Path(catalog.db_path).relative_to(ROOT)),
            }
        )
    (ROOT / "tests/fixtures/catalogs/manifest.json").write_text(
        json.dumps(manifests, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifests))


if __name__ == "__main__":
    main()
