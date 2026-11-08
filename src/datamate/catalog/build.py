"""Business setup: files → DuckDB database + BusinessCatalog (SPEC §7.2). Owner: M1.

BOOTSTRAP SCOPE: CSV files only (via ``ingest.read_csv``), row-by-row insert,
basic profiling, and a plain-text SchemaCard. Excel and SQLite files are
reported as warnings and skipped; a business with no readable file is marked
``failed`` so its questions abstain instead of being answered from partial data.

Deferred (TASKS M1-04, M1-05, M1-08, M1-09, M1-10): Excel/SQLite readers,
header/total-row detection, Arrow bulk load, joins, keys, token-budgeted card.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path

import duckdb

from datamate.contracts import BusinessCatalog, ColumnInfo, DateRange, TableInfo, codes
from datamate.ingest import convert, infer_column_type, read_csv
from datamate.lexicon import nfc, to_identifier

DUCKDB_SAFE_CONFIG = {
    # SPEC SC-3: never download or auto-load extensions (inference runs with --network none).
    "autoinstall_known_extensions": False,
    "autoload_known_extensions": False,
    "threads": 1,
}
LOW_CARDINALITY_MAX = 20
_UNSUPPORTED = {".xlsx", ".xlsm", ".xls", ".sqlite", ".sqlite3", ".db", ".tsv", ".txt"}


def business_key(business_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", business_id) or "_"


def _unique(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for n in names:
        if n in seen:
            seen[n] += 1
            out.append(f"{n}_{seen[n]}")
        else:
            seen[n] = 1
            out.append(n)
    return out


def _q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def _profile_column(con: duckdb.DuckDBPyConnection, table: str, col: str, original: str,
                    sql_type: str) -> ColumnInfo:
    nulls, distinct, lo, hi = con.execute(
        f"SELECT COUNT(*) - COUNT({_q(col)}), COUNT(DISTINCT {_q(col)}), "
        f"MIN({_q(col)})::VARCHAR, MAX({_q(col)})::VARCHAR FROM {_q(table)}"
    ).fetchone()
    top: list[tuple[str, int]] = []
    if sql_type == "VARCHAR" and distinct <= LOW_CARDINALITY_MAX:
        top = [
            (v, int(c))
            for v, c in con.execute(
                f"SELECT {_q(col)}, COUNT(*) AS c FROM {_q(table)} WHERE {_q(col)} IS NOT NULL "
                f"GROUP BY 1 ORDER BY c DESC, 1 ASC"
            ).fetchall()
        ]
    return ColumnInfo(name=col, original_name=original, sql_type=sql_type, null_count=int(nulls),
                      distinct_count=int(distinct), min=lo, max=hi, top_values=top)


def render_schema_card(tables: list[TableInfo], data_range: DateRange | None,
                       warnings: list[str]) -> str:
    """Deterministic plain-text description of the catalog for prompts (SPEC §7.2.9).

    The format is a consumer-visible contract for prompts (M3): tell M3 before
    changing it.
    """
    lines: list[str] = []
    for t in tables:
        lines.append(f"TABLE {t.name}  ({t.row_count} rows; source {t.source_file})")
        for c in t.columns:
            desc = f"  {c.name}  {c.sql_type}  nulls {c.null_count}"
            if c.top_values:
                vals = ", ".join(f'"{v}"({n})' for v, n in c.top_values)
                desc += f"  values: {vals}"
            elif c.min is not None:
                desc += f"  range {c.min}..{c.max}"
            desc += f'  ["{c.original_name}"]'
            lines.append(desc)
    if data_range is not None:
        lines.append(f"DATES {data_range.start.isoformat()}..{data_range.end.isoformat()}")
    for w in warnings:
        lines.append(f"WARN {w}")
    return "\n".join(lines) + "\n"


def setup_business(business_dir: Path, business_id: str, work_dir: Path) -> BusinessCatalog:
    """Materialize one business into ``<work_dir>/biz/<bkey>/catalog.duckdb``.

    Never writes inside ``business_dir`` (``/data`` is read-only).
    """
    bkey = business_key(business_id)
    db_dir = work_dir / "biz" / bkey
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "catalog.duckdb"
    for stale in (db_path, db_dir / "catalog.duckdb.wal"):
        stale.unlink(missing_ok=True)

    warnings: list[str] = []
    readme_text: str | None = None
    files = sorted(p for p in business_dir.iterdir() if p.is_file())
    for p in files:
        if p.name.lower() == "readme.md":
            readme_text = nfc(p.read_text(encoding="utf-8-sig"))

    tables: list[TableInfo] = []
    date_bounds: list[tuple[date, date]] = []
    con = duckdb.connect(str(db_path), config=DUCKDB_SAFE_CONFIG)
    try:
        used_table_names: list[str] = []
        for path in files:
            suffix = path.suffix.lower()
            if suffix in _UNSUPPORTED:
                warnings.append(f"{codes.W_UNSUPPORTED_FILE} {path.name}")
                continue
            if suffix != ".csv":
                continue
            header, rows = read_csv(path)
            if not header:
                warnings.append(f"{codes.W_EMPTY_FILE} {path.name}")
                continue
            table = _unique(used_table_names + [to_identifier(path.stem)])[-1]
            used_table_names.append(table)
            cols = _unique([to_identifier(h) for h in header])
            types = [infer_column_type([r[i] for r in rows]) for i in range(len(header))]
            ddl = ", ".join(f"{_q(c)} {t}" for c, t in zip(cols, types, strict=True))
            con.execute(f"CREATE TABLE {_q(table)} ({ddl})")
            if rows:
                placeholders = ", ".join("?" for _ in cols)
                con.executemany(
                    f"INSERT INTO {_q(table)} VALUES ({placeholders})",
                    [[convert(v, t) for v, t in zip(r, types, strict=True)] for r in rows],
                )
            infos = [
                _profile_column(con, table, c, nfc(h), t)
                for c, h, t in zip(cols, header, types, strict=True)
            ]
            for info in infos:
                if info.sql_type == "DATE" and info.min is not None:
                    date_bounds.append((date.fromisoformat(info.min), date.fromisoformat(info.max)))
            tables.append(TableInfo(name=table, source_file=path.name, row_count=len(rows),
                                    columns=infos))
        con.execute("CHECKPOINT")
    finally:
        con.close()

    data_range = (
        DateRange(start=min(b[0] for b in date_bounds), end=max(b[1] for b in date_bounds))
        if date_bounds else None
    )
    card = render_schema_card(tables, data_range, warnings)
    return BusinessCatalog(
        business_id=business_id,
        bkey=bkey,
        db_path=str(db_path),
        tables=tables,
        data_range=data_range,
        readme_text=readme_text,
        schema_card=card,
        schema_card_sha256=hashlib.sha256(card.encode("utf-8")).hexdigest(),
        warnings=warnings,
        status="ready" if tables else "failed",
    )
