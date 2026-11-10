"""Killable sandbox worker pool (SPEC §7.8, TASKS M3-07). Owner: M3.

``SandboxPool(size)`` keeps ``size`` spawned worker processes. Each worker lowers
``RLIMIT_AS`` to ``memory_limit_mb + 2048 MB``, uses its own scratch directory and caches one
read-only DuckDB connection per database file (external access disabled, configuration locked).
``run_sql`` borrows an idle worker, sends the statement and waits ``sql_timeout_s`` plus
``kill_grace_s`` (the worker's own interrupt normally answers E_SQL_TIMEOUT first). If the
worker does not answer in time the parent SIGKILLs it, starts a replacement and returns
E_SQL_TIMEOUT; a worker that dies (out of memory, crash) yields E_EXEC_CRASH and is replaced.

Result values cross the pipe as pickled ``ExecutionResult`` objects: Decimal, int, str, bool and
date survive exactly and no value passes through float (DOUBLE becomes Decimal(repr(x)) inside
the worker). This is a fault boundary, not a security boundary.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import queue
import tempfile
import threading
import time
from collections.abc import Callable
from multiprocessing.connection import Connection
from typing import Any

from datamate.config import ExecLimits
from datamate.contracts import ExecutionResult, codes

RLIMIT_HEADROOM_MB = 2048


def _worker_main(conn: Connection, limits: ExecLimits, scratch: str) -> None:
    """Worker process loop: receive (db_path, sql), reply with an ExecutionResult."""
    import resource

    from datamate.sandbox.execute import open_readonly, run_sql
    from datamate.sandbox.python_exec import run_python

    cap = (limits.memory_limit_mb + RLIMIT_HEADROOM_MB) * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
    os.makedirs(scratch, exist_ok=True)
    connections: dict[str, Any] = {}
    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            return
        if msg is None:
            return
        kind, db_path, sql = msg
        try:
            if db_path not in connections:
                connections[db_path] = open_readonly(db_path, limits, scratch)
            runner = run_python if kind == "python" else run_sql
            result = runner(db_path, sql, limits, connection=connections[db_path])
        except Exception as exc:  # opening the database failed: a result, not a crash
            result = ExecutionResult(code=sql, ok=False, error_code=codes.E_SQL_EXEC,
                                     error_text=f"{type(exc).__name__}: {exc}"[:2000])
        conn.send(result)


class _Worker:
    def __init__(self, ctx: Any, limits: ExecLimits, scratch_root: str, target: Callable[..., None]):
        self.parent, child = ctx.Pipe()
        self.scratch = os.path.join(scratch_root, f"worker-{id(self):x}")
        self.process = ctx.Process(target=target, args=(child, limits, self.scratch), daemon=True)
        self.process.start()
        child.close()

    def kill(self) -> None:
        try:
            self.process.kill()
        finally:
            self.process.join(timeout=5)
            self.parent.close()

    def stop(self) -> None:
        try:
            self.parent.send(None)
        except (OSError, ValueError):
            pass
        self.process.join(timeout=2)
        if self.process.is_alive():
            self.process.kill()
            self.process.join(timeout=5)
        self.parent.close()


class SandboxPool:
    def __init__(self, size: int, limits: ExecLimits, *, scratch_root: str | None = None,
                 worker_target: Callable[..., None] = _worker_main):
        self.limits, self._target = limits, worker_target
        self._ctx = mp.get_context("spawn")
        self._scratch_root = scratch_root or tempfile.mkdtemp(prefix="datamate-sandbox-")
        self._idle: queue.Queue[_Worker] = queue.Queue()
        self._lock = threading.Lock()
        self._closed = False
        self.size, self.killed, self.replaced = size, 0, 0
        for _ in range(size):
            self._idle.put(_Worker(self._ctx, limits, self._scratch_root, worker_target))

    def run_sql(self, db_path: str, sql: str, limits: ExecLimits | None = None) -> ExecutionResult:
        """``limits`` is accepted for signature compatibility; the pool's limits apply."""
        return self._run("sql", db_path, sql)

    def run_python(self, db_path: str, code: str, limits: ExecLimits | None = None) -> ExecutionResult:
        return self._run("python", db_path, code)

    def _run(self, kind: str, db_path: str, sql: str) -> ExecutionResult:
        started = time.monotonic()
        worker = self._idle.get()
        wait = self.limits.sql_timeout_s + self.limits.kill_grace_s
        try:
            worker.parent.send((kind, db_path, sql))
            if worker.parent.poll(wait):
                result = worker.parent.recv()
                self._idle.put(worker)
                return result
            self._replace(worker)
            return ExecutionResult(
                language="python" if kind == "python" else "sql",
                code=sql, ok=False, error_code=codes.E_SQL_TIMEOUT,
                error_text=f"worker killed after {wait:g} s without an answer",
                duration_ms=int((time.monotonic() - started) * 1000))
        except (EOFError, OSError, BrokenPipeError) as exc:
            self._replace(worker)
            return ExecutionResult(
                language="python" if kind == "python" else "sql",
                code=sql, ok=False, error_code=codes.E_EXEC_CRASH,
                error_text=f"sandbox worker died ({type(exc).__name__}); replaced",
                duration_ms=int((time.monotonic() - started) * 1000))

    def _replace(self, worker: _Worker) -> None:
        worker.kill()
        with self._lock:
            self.killed += 1
            if self._closed:
                return
            self.replaced += 1
        self._idle.put(_Worker(self._ctx, self.limits, self._scratch_root, self._target))

    def close(self) -> None:
        with self._lock:
            self._closed = True
        while True:
            try:
                self._idle.get_nowait().stop()
            except queue.Empty:
                return

    def __enter__(self) -> SandboxPool:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
