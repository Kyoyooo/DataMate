"""Minimal CSV reader for the development fixture. Owner: M1.

SCOPE (bootstrap): UTF-8 (BOM tolerated), delimiter sniffed among , ; TAB |,
header in the first row, every cell returned as a string. Typing is limited to
plain integers, plain decimals with '.', and ISO dates (``infer_column_type``).

NOT YET IMPLEMENTED (TASKS M1-03, M1-06, M1-07): encoding detection, VN/EN
thousands separators ("1.250.000", "560,000"), magnitude suffixes ("150k",
"1tr2"), non-ISO dates ("1 thg 6 2025", "dd/mm/yyyy"), raw-column preservation.
Real training files use those formats, so this reader is not production-ready.
"""

from __future__ import annotations

import csv
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from datamate.lexicon import nfc

NULL_TOKENS = {"", "na", "n/a", "null", "none", "nan"}
_INT = re.compile(r"^[+-]?\d+$")
_DEC = re.compile(r"^[+-]?\d+\.\d+$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def read_csv(path: Path) -> tuple[list[str], list[list[str]]]:
    """Return (header, rows). All values are NFC strings; short rows are padded."""
    text = path.read_bytes().decode("utf-8-sig")
    sample = text[:65536]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","
    reader = csv.reader(text.splitlines(), delimiter=delimiter, quotechar='"')
    rows = [[nfc(c) for c in r] for r in reader if any(c.strip() for c in r)]
    if not rows:
        return [], []
    header, body = rows[0], rows[1:]
    width = len(header)
    body = [(r + [""] * width)[:width] for r in body]
    return header, body


def is_null(value: str) -> bool:
    return value.strip().lower() in NULL_TOKENS


def infer_column_type(values: list[str]) -> str:
    """BIGINT if all non-null values are integers, DECIMAL(38,6) if plain decimals,
    DATE if ISO dates, else VARCHAR. An all-null column is VARCHAR."""
    present = [v.strip() for v in values if not is_null(v)]
    if not present:
        return "VARCHAR"
    if all(_INT.match(v) for v in present):
        if all(-(2**63) <= int(v) < 2**63 for v in present):
            return "BIGINT"
        return "DECIMAL(38,6)"
    if all(_INT.match(v) or _DEC.match(v) for v in present):
        if all(len(v.split(".")[1]) <= 6 for v in present if "." in v):
            return "DECIMAL(38,6)"
        return "VARCHAR"
    if all(_ISO_DATE.match(v) for v in present):
        try:
            for v in present:
                date.fromisoformat(v)
            return "DATE"
        except ValueError:
            return "VARCHAR"
    return "VARCHAR"


def convert(value: str, sql_type: str) -> object:
    """Convert one cell to a Python value for ``sql_type``; nulls become None."""
    if is_null(value):
        return None
    v = value.strip()
    if sql_type == "BIGINT":
        return int(v)
    if sql_type.startswith("DECIMAL"):
        try:
            return Decimal(v)
        except InvalidOperation as exc:  # pragma: no cover - guarded by infer_column_type
            raise ValueError(f"not a decimal: {value!r}") from exc
    if sql_type == "DATE":
        return date.fromisoformat(v)
    return value  # VARCHAR: keep exactly as found (NFC), including surrounding spaces
