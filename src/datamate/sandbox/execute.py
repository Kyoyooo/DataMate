"""SQL execution (SPEC §7.8, C8, P1 subset). Owner: M3.

Runs one SELECT on a **read-only** DuckDB connection with external access
disabled, extension auto-install/auto-load disabled, one thread, a memory
limit, and the configuration locked. A watchdog timer interrupts queries that
exceed ``sql_timeout_s``.

THIS IS NOT PROCESS ISOLATION. Generated SQL runs in the calling process. The
killable worker pool, RLIMIT_AS, and the Python fallback are TASKS M3-07/M3-11.

Value encoding: DOUBLE values become ``Decimal(repr(x))`` here, so no float
reaches the formatter. HUGEINT/BIGINT stay int; DECIMAL stays Decimal.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from decimal import Decimal
from typing import Any

import duckdb

from datamate.config import ExecLimits
from datamate.contracts import ExecutionResult, codes

_MAX_ERROR_CHARS = 2000


def _encode(value: Any) -> Any:
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, datetime) and value.hour == value.minute == value.second == 0 \
            and value.microsecond == 0:
        return value.date()
    return value


def open_readonly(db_path: str, limits: ExecLimits,
                  temp_directory: str | None = None) -> duckdb.DuckDBPyConnection:
    config: dict[str, Any] = {
        "threads": 1,
        "memory_limit": f"{limits.memory_limit_mb}MB",
        "enable_external_access": False,
        "autoinstall_known_extensions": False,
        "autoload_known_extensions": False,
    }
    if temp_directory:  # spill files of a sandbox worker stay in its own scratch directory
        config["temp_directory"] = temp_directory
        config["max_temp_directory_size"] = "4GB"
    con = duckdb.connect(db_path, read_only=True, config=config)
    try:
        con.execute("SET lock_configuration = true")
    except duckdb.InvalidInputException as exc:
        # DuckDB shares one database instance per file within a process; a concurrent
        # caller (orchestrator worker threads) finds it already locked with the same config.
        if "locked" not in str(exc):
            raise
    return con


def run_sql(db_path: str, sql: str, limits: ExecLimits, *,
            connection: duckdb.DuckDBPyConnection | None = None,
            temp_directory: str | None = None) -> ExecutionResult:
    """Execute ``sql`` exactly as given. Errors are returned, never raised.

    ``connection`` (sandbox workers) reuses a cached read-only connection and is not closed.
    """
    started = time.monotonic()
    timed_out = threading.Event()
    con = None
    try:
        con = connection or open_readonly(db_path, limits, temp_directory)

        def _interrupt() -> None:
            timed_out.set()
            con.interrupt()

        timer = threading.Timer(limits.sql_timeout_s, _interrupt)
        timer.start()
        try:
            cur = con.execute(sql)
            columns = [d[0] for d in cur.description] if cur.description else []
            types = [str(d[1]) for d in cur.description] if cur.description else []
            fetched = cur.fetchmany(limits.max_result_rows + 1)
        finally:
            timer.cancel()
        truncated = len(fetched) > limits.max_result_rows
        rows = [[_encode(v) for v in r] for r in fetched[: limits.max_result_rows]]
        return ExecutionResult(
            code=sql, ok=True, columns=columns, column_types=types, rows=rows,
            row_count=len(fetched), truncated=truncated,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    except duckdb.Error as exc:
        code = codes.E_SQL_TIMEOUT if timed_out.is_set() else codes.E_SQL_EXEC
        return ExecutionResult(
            code=sql, ok=False, error_code=code,
            error_text=f"{type(exc).__name__}: {exc}"[:_MAX_ERROR_CHARS],
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    finally:
        if con is not None and connection is None:
            con.close()
