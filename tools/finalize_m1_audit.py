"""Verify completed training artifacts against current M1 contracts and warning fixtures."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

import duckdb

from datamate.catalog import refresh_catalog_coverage, save_catalog
from datamate.catalog.audit import readme_observations
from datamate.catalog.models import IngestionCatalog as BusinessCatalog
from datamate.contracts import CONTRACTS_VERSION
from datamate.ingest.common import verify_inventory


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-dir", type=Path, required=True)
    args = parser.parse_args()
    folder = args.audit_dir
    audit = json.loads((folder / "training_audit.json").read_text(encoding="utf-8"))
    source = Path(audit["source"])
    inventory = json.loads((folder / "source_inventory.json").read_text(encoding="utf-8"))
    paths = sorted((folder / "catalogs").glob("*.json"))
    rows, tables = 0, 0
    readme_ranges = []
    for path in paths:
        record = json.loads(path.read_text(encoding="utf-8"))
        record.pop("readme_audit", None)
        catalog = BusinessCatalog.model_validate_json(json.dumps(record, ensure_ascii=False))
        catalog = refresh_catalog_coverage(catalog)
        record = catalog.model_dump(mode="json")
        record["readme_audit"] = readme_observations(catalog)
        readme = "".join(
            ch
            for ch in unicodedata.normalize("NFD", (catalog.readme_text or "").replace("đ", "d"))
            if not unicodedata.combining(ch)
        ).casefold()
        cutoff = re.search(r"du lieu co den het\s+(\d{1,2})/(\d{1,2})/(\d{4})", readme)
        if cutoff:
            declared = f"{int(cutoff[3]):04d}-{int(cutoff[2]):02d}-{int(cutoff[1]):02d}"
            actual = catalog.data_range.end.isoformat() if catalog.data_range else None
            readme_ranges.append(
                {
                    "business_id": catalog.business_id,
                    "declared": declared,
                    "observed_activity_end": actual,
                    "matches": declared == actual,
                }
            )
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        with duckdb.connect(catalog.db_path, read_only=True) as connection:
            for table in catalog.tables:
                name = '"' + table.name.replace('"', '""') + '"'
                actual = connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                if actual != table.row_count:
                    raise ValueError(f"Row count mismatch: {catalog.business_id}/{table.name}")
                rows += actual
                tables += 1
        save_catalog(catalog, Path(catalog.db_path).parent / "business_catalog.json")
    root = Path(__file__).resolve().parents[1]
    coverage = json.loads(
        (root / "tests/fixtures/businesses/warning_coverage.json").read_text(encoding="utf-8")
    )
    missing = sorted(set(audit["warning_counts"]) - set(coverage))
    for code in audit["warning_counts"]:
        if code in coverage:
            filename, function = coverage[code].split("::")
            if f"def {function}(" not in (root / filename).read_text(encoding="utf-8"):
                raise ValueError(f"Warning fixture node not found: {coverage[code]}")
    unchanged = verify_inventory(source, inventory)
    result = {
        "contracts_version": CONTRACTS_VERSION,
        "source_role": "train",
        "businesses_verified": len(paths),
        "tables_verified": tables,
        "rows_verified": rows,
        "uncovered_warning_codes": missing,
        "input_unchanged": unchanged,
        "valid": audit["valid"]
        and len(paths) == audit["businesses_total"]
        and not missing
        and unchanged["valid"],
    }
    result["readme_range_checks"] = readme_ranges
    result["readme_range_mismatches"] = [row for row in readme_ranges if not row["matches"]]
    result["valid"] = result["valid"] and not result["readme_range_mismatches"]
    (folder / "m1_verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
