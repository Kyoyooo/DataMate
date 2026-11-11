"""CSV compatibility API backed by the same policies as full runtime ingestion.

For column-level parsing, prefer infer_data_column(): it returns the inferred
SQL type, original-value status, chosen convention and all parsed values.
"""

from __future__ import annotations

from datetime import datetime, time
from pathlib import Path

from datamate.ingest.common import read_delimited
from datamate.ingest.engine import (
    DataConfig,
    infer_data_column,
    numeric_convention,
    parse_date_value,
    parse_numeric,
)
from datamate.lexicon import nfc

NULL_TOKENS = {"", "na", "n/a", "null", "none", "nan", "-", "--", "\u2014"}


def read_csv(path: Path) -> tuple[list[str], list[list[str]]]:
    """Return raw NFC strings without truncating over-wide source records."""
    rows, _ = read_delimited(path)
    rows = [[nfc(str(v)) for v in row] for row in rows if any(str(v).strip() for v in row)]
    if not rows:
        return [], []
    width = max(map(len, rows))
    header = rows[0] + [f"column_{i + 1}" for i in range(len(rows[0]), width)]
    return header, [row + [""] * (width - len(row)) for row in rows[1:]]


def is_null(value: str) -> bool:
    return value.strip().casefold() in NULL_TOKENS


def infer_column_type(values: list[str], header: str = "") -> str:
    return infer_data_column(header, values, DataConfig())["sql_type"]


def convert(
    value: str, sql_type: str, *, convention: str | None = None, date_order: str = "DMY"
) -> object:
    """Convert with an explicit column convention when a scalar is ambiguous."""
    if is_null(value):
        return None
    if sql_type == "VARCHAR":
        return nfc(value)
    if sql_type in {"BIGINT", "DOUBLE"} or sql_type.startswith("DECIMAL"):
        policy = convention or numeric_convention([value])[0]
        if policy is None:
            raise ValueError("W_NUMERIC_AMBIGUOUS: supply the inferred column convention")
        parsed, status = parse_numeric(value, policy)
        if status != "parsed":
            raise ValueError(status)
        if sql_type == "BIGINT":
            if parsed != parsed.to_integral_value() or not -(2**63) <= parsed < 2**63:
                raise ValueError("Value does not fit BIGINT")
            return int(parsed)
        return float(parsed) if sql_type == "DOUBLE" else parsed
    if sql_type in {"DATE", "TIMESTAMP"}:
        parsed, status = parse_date_value(value, date_order)
        if parsed is None:
            raise ValueError(status)
        if sql_type == "TIMESTAMP" and not isinstance(parsed, datetime):
            return datetime.combine(parsed, time())
        if sql_type == "DATE" and isinstance(parsed, datetime):
            if parsed.time() != time():
                raise ValueError("Non-midnight timestamp cannot be truncated to DATE")
            return parsed.date()
        return parsed
    if sql_type == "BOOLEAN" and value.casefold() in {"true", "false", "0", "1"}:
        return value.casefold() in {"true", "1"}
    raise ValueError(f"Unsupported conversion to {sql_type}")
