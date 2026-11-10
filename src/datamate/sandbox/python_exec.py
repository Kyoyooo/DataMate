"""Python fallback execution (SPEC §7.8, TASKS M3-11). Owner: M3.

The code must define ``def solve(con):``; it runs with ``exec`` in a fresh namespace whose
``__import__`` allows only a fixed list of pure modules and whose builtins exclude ``open``,
``eval``, ``exec``, ``compile``, ``input`` and ``__import__`` of anything else. ``con`` is the
sandbox's read-only DuckDB connection (external access disabled). This is a FAULT boundary
(wrong code cannot hurt the run), not a security boundary. In production it runs inside a
killable ``SandboxPool`` worker; the in-process path exists for CPU tests.

Return value → ExecutionResult: scalar → column ``value``; list of dicts / DataFrame → its
columns; list of scalars → column ``item``. Floats become ``Decimal(repr(x))``; NaN → None.
"""

from __future__ import annotations

import builtins
import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from datamate.config import ExecLimits
from datamate.contracts import ExecutionResult, codes

ALLOWED_IMPORTS = frozenset({"math", "statistics", "datetime", "decimal", "fractions", "collections",
                             "itertools", "functools", "operator", "re", "json", "pandas", "numpy"})
_SAFE_BUILTINS = (
    "abs all any bool dict divmod enumerate filter float frozenset int isinstance issubclass iter "
    "len list map max min next pow print range repr reversed round set slice sorted str sum tuple "
    "type zip bytes bytearray complex hash id callable getattr hasattr setattr object property "
    "staticmethod classmethod super format ord chr bin hex oct ascii "
    "Exception ValueError TypeError KeyError IndexError ZeroDivisionError ArithmeticError "
    "StopIteration AttributeError RuntimeError NotImplementedError OverflowError LookupError "
    "True False None"
).split()


def _guarded_import(name: str, globals_: Any = None, locals_: Any = None, fromlist: Any = (),
                    level: int = 0) -> Any:
    if level != 0 or name.split(".")[0] not in ALLOWED_IMPORTS:
        raise ImportError(f"import of {name!r} is not allowed")
    return builtins.__import__(name, globals_, locals_, fromlist, level)


def _cell(v: Any) -> Any:
    if v is None or isinstance(v, (bool, int, str, Decimal, date)):
        return v.date() if isinstance(v, datetime) and v == datetime.combine(v.date(), datetime.min.time()) else v
    if isinstance(v, float):
        return None if v != v else Decimal(repr(v))
    if hasattr(v, "item"):  # numpy scalar
        return _cell(v.item())
    if hasattr(v, "to_pydatetime"):
        return _cell(v.to_pydatetime())
    return str(v)


def to_table(value: Any) -> tuple[list[str], list[list[Any]]]:
    if hasattr(value, "to_dict") and hasattr(value, "columns"):  # DataFrame
        cols = [str(c) for c in value.columns]
        return cols, [[_cell(v) for v in row] for row in value.itertuples(index=False, name=None)]
    if hasattr(value, "items") and hasattr(value, "index") and not isinstance(value, dict):  # Series
        return ["item"], [[_cell(v)] for v in value.tolist()]
    if isinstance(value, (list, tuple)):
        if value and all(isinstance(r, dict) for r in value):
            cols = list(value[0])
            return cols, [[_cell(r.get(c)) for c in cols] for r in value]
        if value and all(isinstance(r, (list, tuple)) for r in value):
            return [f"c{i + 1}" for i in range(len(value[0]))], [[_cell(c) for c in r] for r in value]
        return ["item"], [[_cell(v)] for v in value]
    return ["value"], [[_cell(value)]]


def run_python(db_path: str, code: str, limits: ExecLimits, *, connection: Any = None,
               temp_directory: str | None = None) -> ExecutionResult:
    from datamate.sandbox.execute import open_readonly

    started = time.monotonic()
    own = connection is None
    con = None
    try:
        con = connection or open_readonly(db_path, limits, temp_directory)
        namespace: dict[str, Any] = {"__builtins__": {
            **{n: getattr(builtins, n) for n in _SAFE_BUILTINS if hasattr(builtins, n)},
            "__import__": _guarded_import}}
        exec(compile(code, "<fallback>", "exec"), namespace)  # noqa: S102 - sandboxed fault boundary
        if not callable(namespace.get("solve")):
            raise ValueError("the code must define solve(con)")
        columns, rows = to_table(namespace["solve"](con))
        fetched = rows[: limits.max_result_rows + 1]
        return ExecutionResult(
            language="python", code=code, ok=True, columns=columns, column_types=[],
            rows=fetched[: limits.max_result_rows], row_count=len(fetched),
            truncated=len(fetched) > limits.max_result_rows,
            duration_ms=int((time.monotonic() - started) * 1000))
    except Exception as exc:  # generated code may fail in any way
        return ExecutionResult(
            language="python", code=code, ok=False, error_code=codes.E_SQL_EXEC,
            error_text=f"{type(exc).__name__}: {exc}"[:2000],
            duration_ms=int((time.monotonic() - started) * 1000))
    finally:
        if con is not None and own:
            con.close()
