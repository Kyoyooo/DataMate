"""M3-11: python fallback executor and solver switch (default off)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from datamate.config import ExecLimits, RunConfig, load_config
from datamate.contracts import QuestionFrame, codes
from datamate.sandbox import SandboxPool, run_python
from datamate.solver import solve

from conftest import question, scripted

LIMITS = ExecLimits(sql_timeout_s=2.0, kill_grace_s=1.0, memory_limit_mb=256, workers=1)


def run(db, code):
    return run_python(db, code, LIMITS)


def test_scalar_and_exact_decimals(catalog):
    r = run(catalog.db_path, "def solve(con):\n    return con.execute('SELECT COUNT(*) FROM ban_hang').fetchone()[0]")
    assert r.ok and r.language == "python" and r.columns == ["value"] and isinstance(r.rows[0][0], int)
    r = run(catalog.db_path, "from decimal import Decimal\ndef solve(con):\n    return Decimal('1.10') + Decimal('2.20')")
    assert r.rows == [[Decimal("3.30")]]
    r = run(catalog.db_path, "def solve(con):\n    return 0.1 + 0.2")
    assert r.rows == [[Decimal("0.30000000000000004")]]  # float -> Decimal(repr), never rounded
    r = run(catalog.db_path, "import datetime\ndef solve(con):\n    return datetime.date(2026, 3, 1)")
    assert r.rows == [[date(2026, 3, 1)]]


def test_list_of_dicts_and_table_shapes(catalog):
    r = run(catalog.db_path, "def solve(con):\n    return [{'item': 'a', 'sort_key': 2, 'tie_code': 'x'},"
                             " {'item': 'b', 'sort_key': 1, 'tie_code': None}]")
    assert r.columns == ["item", "sort_key", "tie_code"] and r.rows == [["a", 2, "x"], ["b", 1, None]]
    assert run(catalog.db_path, "def solve(con):\n    return ['x', 'y']").rows == [["x"], ["y"]]


def test_pandas_dataframe_if_available(catalog):
    pytest.importorskip("pandas")
    r = run(catalog.db_path, "import pandas as pd\ndef solve(con):\n"
                             "    return pd.DataFrame({'ten': ['a'], 'sl': [3]})")
    assert r.ok and r.columns == ["ten", "sl"] and r.rows == [["a", 3]]


@pytest.mark.parametrize("code", [
    "import os\ndef solve(con):\n    return 1",
    "import subprocess\ndef solve(con):\n    return 1",
    "def solve(con):\n    return open('/etc/passwd').read()",
    "def solve(con):\n    return eval('1+1')",
    "def solve(con):\n    exec('x=1')\n    return 1",
    "def solve(con):\n    return __import__('os').getcwd()",
    "def solve(con):\n    return compile('1', 'f', 'eval')",
    "x = 1",  # no solve()
    "def solve(con):\n    raise ValueError('boom')",
    "def solve(con):\n    return con.execute('SELECT * FROM read_csv(\\'/etc/passwd\\')').fetchall()",
])
def test_forbidden_or_broken_code_is_a_failed_execution_not_an_exception(catalog, code):
    r = run(catalog.db_path, code)
    assert not r.ok and r.error_code == codes.E_SQL_EXEC and r.language == "python"


def test_python_runs_inside_the_killable_pool_and_runaway_code_is_killed(catalog):
    with SandboxPool(1, LIMITS) as pool:
        ok = pool.run_python(catalog.db_path, "def solve(con):\n    return 42")
        assert ok.ok and ok.rows == [[42]]
        hang = pool.run_python(catalog.db_path, "def solve(con):\n    while True:\n        pass")
        assert hang.error_code == codes.E_SQL_TIMEOUT and hang.language == "python" and pool.killed == 1
        assert pool.run_python(catalog.db_path, "def solve(con):\n    return 7").rows == [[7]]


FRAME = {"expected_type": "number", "numeric_kind": "count"}
BAD_SQL = {"sql": "SELECT nope FROM missing"}
TEXT = "Có bao nhiêu dòng bán hàng?"


def solver_run(cfg, catalog, split, *outputs):
    client = scripted(TEXT, FRAME, *outputs)
    return solve(question(TEXT), QuestionFrame.model_validate(FRAME), [], catalog, split, client, cfg)


def test_fallback_is_off_by_default(catalog, split):
    assert RunConfig().solver.python_fallback is False
    cfg = load_config(None, ["model.backend=scripted", "solver.max_repairs=0"])
    attempts = solver_run(cfg, catalog, split, BAD_SQL)
    assert [a.stage for a in attempts] == ["solve"] and not attempts[0].ok


def fallback_entry(code):
    import json
    return {"stage": "fallback", "question": TEXT, "content": json.dumps({"python": code})}


def test_failed_sql_then_python_fallback_succeeds_when_switched_on(catalog, split):
    cfg = load_config(None, ["model.backend=scripted", "solver.max_repairs=0", "solver.python_fallback=true"])
    client = scripted(TEXT, FRAME, BAD_SQL)
    client._responses[("fallback", TEXT)].append(
        fallback_entry("def solve(con):\n    return con.execute('SELECT COUNT(*) FROM ban_hang').fetchone()[0]"))
    attempts = solve(question(TEXT), QuestionFrame.model_validate(FRAME), [], catalog, split, client, cfg)
    assert [a.stage for a in attempts] == ["solve", "fallback"]
    fb = attempts[-1]
    assert fb.ok and fb.execution.language == "python" and fb.model_call.template_id == "solve.python.v1"
    assert fb.value.value > 0 and fb.python_output.python.startswith("def solve")


def test_empty_result_and_model_errors_never_reach_the_fallback(catalog, split):
    cfg = load_config(None, ["model.backend=scripted", "solver.max_repairs=0", "solver.python_fallback=true"])
    attempts = solver_run(cfg, catalog, split, {"sql": "SELECT NULL AS value"})  # E_EMPTY_RESULT
    assert [a.stage for a in attempts] == ["solve"] and attempts[0].error_code == codes.E_EMPTY_RESULT
    attempts = solver_run(cfg, catalog, split)  # no scripted solve -> E_SCRIPT_MISS (model error)
    assert [a.stage for a in attempts] == ["solve"]


def test_invalid_fallback_output_is_recorded_not_raised(catalog, split):
    cfg = load_config(None, ["model.backend=scripted", "solver.max_repairs=0", "solver.python_fallback=true"])
    client = scripted(TEXT, FRAME, BAD_SQL)
    client._responses[("fallback", TEXT)].append({"stage": "fallback", "question": TEXT, "content": "not json"})
    attempts = solve(question(TEXT), QuestionFrame.model_validate(FRAME), [], catalog, split, client, cfg)
    assert attempts[-1].stage == "fallback" and attempts[-1].error_code == codes.E_SOLVER_OUTPUT_INVALID
