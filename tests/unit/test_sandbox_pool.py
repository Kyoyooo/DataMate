"""M3-07 (SPEC §7.8 tests): killable pool, memory bomb, concurrency, exact decimals (CPU)."""

from __future__ import annotations

import os
import signal
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import duckdb
import pytest

from datamate.config import ExecLimits
from datamate.contracts import codes
from datamate.sandbox import SandboxPool

LIMITS = ExecLimits(sql_timeout_s=1.0, kill_grace_s=1.0, memory_limit_mb=256, workers=2)


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "t.duckdb")
    con = duckdb.connect(path)
    con.execute("CREATE TABLE t(x BIGINT, d DECIMAL(38,6), s VARCHAR)")
    con.execute("INSERT INTO t VALUES (1, 100000000000000.123456, 'a'), "
                "(2, 99999999999999.000001, 'b')")
    con.execute("CREATE TABLE big AS SELECT i AS x FROM range(100000) t(i)")
    con.close()
    return path


@pytest.fixture
def pool():
    with SandboxPool(2, LIMITS) as p:
        yield p


def test_basic_query_and_cached_connection_reuse(pool, db):
    r = pool.run_sql(db, "SELECT COUNT(*) AS n FROM t")
    assert r.ok and r.rows == [[2]] and r.columns == ["n"]
    assert pool.run_sql(db, "SELECT MAX(x) AS m FROM t").rows == [[2]]


def test_decimal_round_trip_is_exact_at_1e14_scale(pool, db):
    r = pool.run_sql(db, "SELECT SUM(d) AS s FROM t")
    assert r.rows == [[Decimal("199999999999999.123457")]]  # hand-added: 1e14+.123456 + 99999999999999.000001
    assert isinstance(r.rows[0][0], Decimal)
    r = pool.run_sql(db, "SELECT CAST(0.1 AS DOUBLE) + CAST(0.2 AS DOUBLE) AS v")
    assert r.rows == [[Decimal("0.30000000000000004")]]  # DOUBLE -> Decimal(repr(x)), never float


def test_runaway_recursive_cte_is_terminated_at_the_timeout(pool, db):
    started = time.monotonic()
    r = pool.run_sql(db, "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) "
                         "SELECT COUNT(*) FROM r")
    assert not r.ok and r.error_code == codes.E_SQL_TIMEOUT
    assert time.monotonic() - started < LIMITS.sql_timeout_s + LIMITS.kill_grace_s + 3
    assert pool.run_sql(db, "SELECT 1 AS v").ok  # the pool still works afterwards


def test_external_access_is_rejected(pool, db):
    for sql in ("SELECT * FROM read_csv('/etc/passwd')", "COPY t TO '/tmp/x_datamate_leak.csv'",
                "ATTACH '/tmp/other_datamate.duckdb' AS o", "INSTALL httpfs"):
        r = pool.run_sql(db, sql)
        assert not r.ok and r.error_code == codes.E_SQL_EXEC, sql
    assert not os.path.exists("/tmp/x_datamate_leak.csv")


def test_memory_bomb_is_contained_and_the_worker_is_replaced(db):
    limits = ExecLimits(sql_timeout_s=5.0, kill_grace_s=2.0, memory_limit_mb=128, workers=1)
    with SandboxPool(1, limits) as p:
        r = p.run_sql(db, "SELECT list(i) FROM range(1000000000) t(i)")
        assert not r.ok and r.error_code in (codes.E_SQL_EXEC, codes.E_EXEC_CRASH)
        assert p.run_sql(db, "SELECT 1 AS v").ok  # whichever way it failed, the pool recovered


def hang_worker(conn, limits, scratch):  # a worker that never answers (stuck in native code)
    while True:
        conn.recv()
        time.sleep(3600)


def test_hung_worker_is_killed_and_replaced_not_waited_for(db):
    with SandboxPool(1, LIMITS, worker_target=hang_worker) as p:
        pid = p._idle.queue[0].process.pid
        started = time.monotonic()
        r = p.run_sql(db, "SELECT 1")
        assert r.error_code == codes.E_SQL_TIMEOUT and "killed" in r.error_text
        assert time.monotonic() - started < LIMITS.sql_timeout_s + LIMITS.kill_grace_s + 3
        assert p.killed == 1 and p.replaced == 1
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)  # the old worker is gone


def test_crashed_worker_returns_exec_crash_and_is_replaced(pool, db):
    worker = pool._idle.queue[0]
    os.kill(worker.process.pid, signal.SIGKILL)
    worker.process.join()
    codes_seen = {pool.run_sql(db, "SELECT 1 AS v").error_code for _ in range(2)}
    assert codes.E_EXEC_CRASH in codes_seen
    assert pool.run_sql(db, "SELECT 1 AS v").ok and pool.run_sql(db, "SELECT 2 AS v").ok


def test_sixteen_concurrent_readers_on_one_database_file(db):
    limits = ExecLimits(sql_timeout_s=10.0, memory_limit_mb=256, workers=16)
    with SandboxPool(16, limits) as p, ThreadPoolExecutor(16) as ex:
        results = list(ex.map(lambda i: p.run_sql(db, f"SELECT SUM(x) + {i} AS v FROM big"),
                              range(32)))
    total = sum(range(100000))
    assert all(r.ok for r in results)
    assert [r.rows[0][0] for r in results] == [total + i for i in range(32)]


def test_orchestrated_run_uses_the_pool_and_matches_in_process_answers(tmp_path):
    from datamate.eval.score import score_files
    from datamate.run import main

    from conftest import REPO, SCRIPT, SPLIT
    out = tmp_path / "out"
    assert main(["--dev", "--config", str(REPO / "config" / "dev.json"), "--data-dir", str(SPLIT),
                 "--result-dir", str(out), "--set", f"work_dir={tmp_path / 'w'}",
                 "--set", f"model.script_path={SCRIPT}", "--set", "exec_limits.isolation=\"process\""
                 ]) == 0
    assert set(score_files(out / "submission.jsonl", SPLIT / "answers.jsonl")["per_id"].values()) == {1}
