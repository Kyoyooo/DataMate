"""Execution result → TypedValue (SPEC §7.7.5). Owner: M3.

Missing information versus zero: no rows, or a NULL where a value is required,
is E_EMPTY_RESULT ("the data did not produce an answer"), never 0. A computed
0 (e.g. ``COALESCE(SUM(qty), 0)`` over a period that has data) is a value.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from datamate.contracts import (
    DateValue,
    ExecutionResult,
    ListItem,
    ListValue,
    QuestionFrame,
    ScalarValue,
    TableValue,
    TypedValue,
    codes,
)

_MONTH = re.compile(r"^\d{4}-\d{2}$")


class ContractViolation(ValueError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code


def _number(v: Any) -> Decimal:
    if v is None:
        raise ContractViolation(codes.E_EMPTY_RESULT, "NULL where a number is required")
    if isinstance(v, bool) or not isinstance(v, (int, Decimal)):
        raise ContractViolation(codes.E_TYPE_CONTRACT, f"expected a number, got {type(v).__name__}")
    d = Decimal(v)
    if not d.is_finite():  # e.g. division by zero in DuckDB yields inf
        raise ContractViolation(codes.D_IMPLAUSIBLE, f"non-finite number {d}")
    return d


def _scalar_cell(ex: ExecutionResult) -> Any:
    if ex.row_count == 0:
        raise ContractViolation(codes.E_EMPTY_RESULT, "query returned no rows")
    if ex.row_count != 1:
        raise ContractViolation(codes.E_TYPE_CONTRACT, f"expected 1 row, got {ex.row_count}")
    if len(ex.columns) == 1:
        return ex.rows[0][0]
    if "value" in ex.columns:
        return ex.rows[0][ex.columns.index("value")]
    raise ContractViolation(codes.E_TYPE_CONTRACT, f"expected one column 'value', got {ex.columns}")


def _col(ex: ExecutionResult, name: str, required: bool = True) -> int | None:
    if name in ex.columns:
        return ex.columns.index(name)
    if required:
        raise ContractViolation(codes.E_TYPE_CONTRACT, f"missing column {name!r} in {ex.columns}")
    return None


def _item(v: Any) -> Decimal | str:
    if v is None:
        raise ContractViolation(codes.E_EMPTY_RESULT, "NULL list item")
    if isinstance(v, str):
        return v
    return _number(v)


def _cell(v: Any) -> Decimal | str | None:
    if v is None or isinstance(v, str):
        return v
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return _number(v)


def _convert(frame: QuestionFrame, ex: ExecutionResult) -> TypedValue:
    t = frame.expected_type
    if t in ("number", "percent"):
        return ScalarValue(type=t, value=_number(_scalar_cell(ex)), numeric_kind=frame.numeric_kind)
    if t == "string":
        v = _scalar_cell(ex)
        if v is None:
            raise ContractViolation(codes.E_EMPTY_RESULT, "NULL string")
        if not isinstance(v, str):
            raise ContractViolation(codes.E_TYPE_CONTRACT, f"expected text, got {type(v).__name__}")
        return ScalarValue(type="string", value=v)
    if t == "boolean":
        v = _scalar_cell(ex)
        if v is None:
            raise ContractViolation(codes.E_EMPTY_RESULT, "NULL boolean")
        if isinstance(v, bool):
            return ScalarValue(type="boolean", value=v)
        if isinstance(v, int) and v in (0, 1):
            return ScalarValue(type="boolean", value=bool(v))
        raise ContractViolation(codes.E_TYPE_CONTRACT, f"expected boolean, got {v!r}")
    if t == "date":
        v = _scalar_cell(ex)
        gran = frame.date_granularity or "day"
        if v is None:
            raise ContractViolation(codes.E_EMPTY_RESULT, "NULL date")
        if isinstance(v, datetime):
            v = v.date()
        if isinstance(v, str) and _MONTH.match(v):
            v = date.fromisoformat(v + "-01")
        elif isinstance(v, str):
            try:
                v = date.fromisoformat(v)
            except ValueError as exc:
                raise ContractViolation(codes.E_TYPE_CONTRACT, f"not a date: {v!r}") from exc
        if not isinstance(v, date):
            raise ContractViolation(codes.E_TYPE_CONTRACT, f"expected date, got {type(v).__name__}")
        return DateValue(value=v, granularity=gran)
    if t == "list":
        if ex.row_count == 0:
            raise ContractViolation(codes.E_EMPTY_RESULT, "list query returned no rows")
        if frame.list_order == "ranked":
            i_item, i_key = _col(ex, "item"), _col(ex, "sort_key")
            i_tie = _col(ex, "tie_code", required=False)
            items = []
            for r in ex.rows:
                key = r[i_key]
                key = key.isoformat() if isinstance(key, (date, datetime)) else key
                key = key if key is None or isinstance(key, str) else _number(key)
                tie = None if i_tie is None or r[i_tie] is None else str(r[i_tie])
                items.append(ListItem(item=_item(r[i_item]), sort_key=key, tie_code=tie))
        else:
            i_ord, i_item = _col(ex, "ord"), _col(ex, "item")
            items = [ListItem(item=_item(r[i_item]), position=int(r[i_ord])) for r in ex.rows]
        if ex.truncated:
            raise ContractViolation(codes.E_TYPE_CONTRACT, "list result truncated")
        return ListValue(order=frame.list_order, items=items, numeric_kind=frame.numeric_kind)
    if t == "table":
        if ex.row_count == 0:
            raise ContractViolation(codes.E_EMPTY_RESULT, "table query returned no rows")
        if ex.truncated:
            raise ContractViolation(codes.E_TYPE_CONTRACT, "table result truncated")
        return TableValue(columns=list(ex.columns), rows=[[_cell(v) for v in r] for r in ex.rows],
                          numeric_kind=frame.numeric_kind)
    raise ContractViolation(codes.E_TYPE_CONTRACT, f"unknown expected type {t}")  # pragma: no cover


def to_typed_value(frame: QuestionFrame, ex: ExecutionResult) -> tuple[TypedValue | None, str | None]:
    """Return (value, error_code); exactly one is None."""
    try:
        return _convert(frame, ex), None
    except ContractViolation as v:
        return None, v.code
