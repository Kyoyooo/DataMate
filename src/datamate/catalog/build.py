"""Runtime M1 catalog adapter and SchemaCard public API (SPEC 7.2)."""

from __future__ import annotations

import hashlib
import re
import time
from datetime import date
from pathlib import Path

from datamate.catalog.io import save_catalog
from datamate.config import RunConfig
from datamate.contracts import (
    BusinessCatalog,
    ColumnInfo,
    DateColumn,
    DateRange,
    DroppedRows,
    JoinEdge,
    TableInfo,
)
from datamate.ingest import DataConfig, build_business_database, catalog_date_range, render_catalog


def business_key(business_id: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_-]", "_", business_id) or "business"
    return (
        clean
        if clean == business_id
        else clean + "_" + hashlib.sha256(business_id.encode()).hexdigest()[:12]
    )


def catalog_from_artifact(artifact: dict, database: Path, *, setup_ms: int = 0) -> BusinessCatalog:
    tables = []
    for table in artifact["tables"]:
        columns = []
        declared = {row[1]: row[2] for row in table["source_details"].get("declared_columns", [])}
        for column in table["columns"]:
            note = column.get("format_note")
            if column["original_name"] in declared:
                note = ";".join(filter(None, ["sqlite:" + declared[column["original_name"]], note]))
            columns.append(
                ColumnInfo(
                    **{
                        key: column[key]
                        for key in (
                            "name",
                            "original_name",
                            "sql_type",
                            "null_count",
                            "distinct_count",
                            "min",
                            "max",
                            "top_values",
                            "semantic_hint",
                            "null_rate",
                            "raw_column",
                            "parse_rate",
                            "status_column",
                            "unit_column",
                            "observed_units",
                        )
                    },
                    format_note=note,
                )
            )
        indices = table.get("dropped_source_indices", {})
        dropped = DroppedRows(
            total_rows=sum(len(v) for v in indices.values()),
            note_rows=len(indices.get("note", [])),
            blank_rows=len(indices.get("blank", [])),
            summary_rows=len(indices.get("summary", [])),
            source_indices=indices,
        )
        tables.append(
            TableInfo(
                name=table["name"],
                source_file=table["source_file"],
                source_part=table["source_part"],
                row_count=table["row_count"],
                columns=columns,
                candidate_keys=table["candidate_keys"],
                dropped_rows=dropped,
                source_details=table["source_details"],
            )
        )
    joins = [
        JoinEdge(
            left=e["left_table"] + "." + e["left_column"],
            right=e["right_table"] + "." + e["right_column"],
            cardinality=e.get("cardinality", "n:1"),
            match_rate=e["match_rate"],
        )
        for e in artifact["joins"]
    ]
    dates = [
        DateColumn(
            column=r["table"] + "." + r["column"],
            min=date.fromisoformat(r["start"]),
            max=date.fromisoformat(r["end"]),
            included_in_data_range=r["included_in_data_range"],
            exclusion_reason=r.get("exclusion_reason"),
        )
        for r in artifact["date_columns"]
    ]
    bounds = DateRange(**artifact["data_range"]) if artifact["data_range"] else None
    card = render_catalog(artifact)
    budget = artifact.get("schema_card_budget", {})
    return BusinessCatalog(
        business_id=artifact["business_id"],
        bkey=business_key(artifact["business_id"]),
        db_path=str(database.resolve()),
        tables=tables,
        joins=joins,
        date_columns=dates,
        data_range=bounds,
        readme_text=artifact["readme_text"],
        schema_card=card,
        schema_card_sha256=hashlib.sha256(card.encode()).hexdigest(),
        warnings=artifact["warnings"],
        setup_ms=setup_ms,
        status=artifact["status"],
        schema_card_budget_verified=budget.get("budget_verified", False),
        schema_card_needs_subset=bool(budget.get("needs_relevant_subset")),
    )


def catalog_artifact(catalog: BusinessCatalog) -> dict:
    tables = []
    for table in catalog.tables:
        columns = []
        for column in table.columns:
            data = column.model_dump()
            data["top_values"] = [[v.value, v.count] for v in column.top_values]
            columns.append(data)
        tables.append({**table.model_dump(), "columns": columns})
    return {
        "tables": tables,
        "joins": [
            dict(
                left_table=e.left.rsplit(".", 1)[0],
                left_column=e.left.rsplit(".", 1)[1],
                right_table=e.right.rsplit(".", 1)[0],
                right_column=e.right.rsplit(".", 1)[1],
                match_rate=e.match_rate,
            )
            for e in catalog.joins
        ],
        "date_columns": [
            dict(
                table=d.column.rsplit(".", 1)[0],
                column=d.column.rsplit(".", 1)[1],
                start=d.min.isoformat(),
                end=d.max.isoformat(),
                included_in_data_range=d.included_in_data_range,
                exclusion_reason=d.exclusion_reason,
            )
            for d in catalog.date_columns
        ],
        "warnings": [str(w) for w in catalog.warnings],
        "low_cardinality_max": 50,
        "views": [
            {"name": v.name, "purpose": v.purpose, "ddl": v.ddl} for v in catalog.views if v.enabled
        ],
    }


def render_schema_card(
    tables: list[TableInfo], data_range: DateRange | None = None, warnings: list | None = None
) -> str:
    temporary = BusinessCatalog(
        business_id="",
        bkey="",
        db_path="",
        tables=tables,
        data_range=data_range,
        readme_text=None,
        schema_card="",
        schema_card_sha256="",
        warnings=warnings or [],
    )
    text = render_catalog(catalog_artifact(temporary))
    if data_range is not None:
        lines = text.splitlines()
        index = next((i for i, line in enumerate(lines) if line.startswith("WARN ")), len(lines))
        lines.insert(index, f"DATES {data_range.start.isoformat()}..{data_range.end.isoformat()}")
        text = "\n".join(lines) + "\n"
    return text


def refresh_catalog_coverage(catalog: BusinessCatalog) -> BusinessCatalog:
    dates, bounds = catalog_date_range(catalog_artifact(catalog)["tables"])
    columns = [
        DateColumn(
            column=r["table"] + "." + r["column"],
            min=date.fromisoformat(r["start"]),
            max=date.fromisoformat(r["end"]),
            included_in_data_range=r["included_in_data_range"],
            exclusion_reason=r.get("exclusion_reason"),
        )
        for r in dates
    ]
    updated = catalog.model_copy(
        update={"date_columns": columns, "data_range": DateRange(**bounds) if bounds else None}
    )
    card = render_catalog(catalog_artifact(updated))
    return updated.model_copy(
        update={
            "schema_card": card,
            "schema_card_sha256": hashlib.sha256(card.encode()).hexdigest(),
        }
    )


def setup_business(
    business_dir: Path, business_id: str, cfg: RunConfig | Path | str, *, tokenizer=None
) -> BusinessCatalog:
    """Accept RunConfig, or the legacy work-dir argument; return failed catalogs on setup errors."""
    started = time.monotonic()
    runtime = cfg if isinstance(cfg, RunConfig) else RunConfig(work_dir=str(cfg))
    destination = Path(runtime.work_dir) / "biz" / business_key(business_id)
    if destination.resolve().is_relative_to(business_dir.resolve()):
        raise ValueError("Scratch must be outside input")
    config = DataConfig(
        **runtime.ingest.model_dump(),
        schema_card_budget_tokens=runtime.solver.schema_card_budget_tokens,
    )
    try:
        artifact = build_business_database(
            business_dir, business_id, destination, config, tokenizer
        )
        result = catalog_from_artifact(
            artifact,
            destination / "catalog.duckdb",
            setup_ms=int((time.monotonic() - started) * 1000),
        )
        save_catalog(result, destination / "business_catalog.json")
        return result
    except Exception as error:
        return BusinessCatalog(
            business_id=business_id,
            bkey=business_key(business_id),
            db_path=str(destination / "catalog.duckdb"),
            tables=[],
            data_range=None,
            readme_text=None,
            schema_card="",
            schema_card_sha256=hashlib.sha256(b"").hexdigest(),
            warnings=[f"E_BUSINESS_SETUP {type(error).__name__}: {error}"],
            status="failed",
            setup_ms=int((time.monotonic() - started) * 1000),
        )
