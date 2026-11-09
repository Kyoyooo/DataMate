"""Independent fake catalogs for M2/M3/M4; does not call ingestion (M1-11)."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb

from datamate.catalog.build import catalog_artifact
from datamate.contracts import BusinessCatalog, ColumnInfo, DateColumn, DateRange, TableInfo
from datamate.ingest import render_catalog, sql_quote


def make_fake_catalog(
    work_dir: Path, scenario: str = "sales", *, fixture_root: Path | None = None
) -> BusinessCatalog:
    fixtures = fixture_root or Path(__file__).resolve().parents[3] / "tests/fixtures/catalogs"
    if scenario not in {"sales", "mixed_types", "missing_fields"}:
        raise ValueError("Unknown fake catalog scenario")
    spec = json.loads((fixtures / (scenario + ".json")).read_text(encoding="utf-8"))
    destination = work_dir / ("fake_" + scenario)
    destination.mkdir(parents=True, exist_ok=True)
    database = destination / "catalog.duckdb"
    tables, dates = [], []
    with duckdb.connect(
        str(database),
        config={
            "threads": 1,
            "autoinstall_known_extensions": False,
            "autoload_known_extensions": False,
        },
    ) as connection:
        for table in spec["tables"]:
            name = sql_quote(table["name"])
            connection.execute(f"DROP TABLE IF EXISTS {name}")
            ddl = ",".join(f"{sql_quote(column)} {dtype}" for column, dtype, _ in table["columns"])
            connection.execute(f"CREATE TABLE {name} ({ddl})")
            rows = []
            for row in table["rows"]:
                rows.append(
                    [
                        date.fromisoformat(v)
                        if dtype == "DATE" and v is not None
                        else Decimal(v)
                        if dtype.startswith("DECIMAL") and v is not None
                        else v
                        for v, (_, dtype, _) in zip(row, table["columns"], strict=True)
                    ]
                )
            if rows:
                connection.executemany(
                    f"INSERT INTO {name} VALUES ({','.join('?' for _ in table['columns'])})", rows
                )
            columns, keys = [], []
            for column, dtype, hint in table["columns"]:
                field = sql_quote(column)
                nulls, unique, lo, hi = connection.execute(
                    f"SELECT COUNT(*)-COUNT({field}),COUNT(DISTINCT {field}),MIN({field})::VARCHAR,MAX({field})::VARCHAR FROM {name}"
                ).fetchone()
                top = connection.execute(
                    f"SELECT {field}::VARCHAR,COUNT(*) FROM {name} WHERE {field} IS NOT NULL GROUP BY {field} ORDER BY COUNT(*) DESC,{field}"
                ).fetchall()
                columns.append(
                    ColumnInfo(
                        name=column,
                        original_name=column,
                        sql_type=dtype,
                        null_count=nulls,
                        distinct_count=unique,
                        min=lo,
                        max=hi,
                        top_values=top,
                        semantic_hint=hint,
                        null_rate=nulls / len(rows) if rows else 0,
                    )
                )
                if unique == len(rows) and not nulls:
                    keys.append([column])
                if dtype == "DATE" and lo:
                    dates.append(
                        DateColumn(
                            column=table["name"] + "." + column,
                            min=date.fromisoformat(lo),
                            max=date.fromisoformat(hi),
                        )
                    )
            tables.append(
                TableInfo(
                    name=table["name"],
                    source_file="synthetic:" + scenario,
                    row_count=len(rows),
                    columns=columns,
                    candidate_keys=keys,
                )
            )
        connection.execute("CHECKPOINT")
    bounds = (
        DateRange(start=min(d.min for d in dates), end=max(d.max for d in dates)) if dates else None
    )
    cat = BusinessCatalog(
        business_id="fake_" + scenario,
        bkey="fake_" + scenario,
        db_path=str(database.resolve()),
        tables=tables,
        joins=spec["joins"],
        date_columns=dates,
        data_range=bounds,
        readme_text=spec["readme"],
        schema_card="",
        schema_card_sha256="",
    )
    text = render_catalog(catalog_artifact(cat))
    return cat.model_copy(
        update={
            "schema_card": text,
            "schema_card_sha256": hashlib.sha256(text.encode()).hexdigest(),
        }
    )
