"""Model-output handling, SQL safety, and answer/unanswerable/abstain decisions.

Uses the real fixture catalog (DuckDB) with scripted model responses written here.
"""

from __future__ import annotations

from datamate.config import ExecLimits, load_config
from datamate.sandbox import run_sql
from datamate.solver import check_sql

from conftest import run_one

FEB = "ngay_dat BETWEEN DATE '2026-02-01' AND DATE '2026-02-28'"
VALID = "trang_thai NOT IN ('Huỷ', 'Trả hàng')"
MONTH_FEB = [{"span": "tháng 2/2026", "expr": {"kind": "calendar_period", "unit": "month",
                                               "year": 2026, "index": 2}}]
Q = "Doanh thu tháng 2/2026 là bao nhiêu?"
FRAME = {"expected_type": "number", "numeric_kind": "money", "time": MONTH_FEB}
GOOD_SQL = {"sql": f"SELECT SUM(thanh_tien) AS value FROM ban_hang WHERE {FEB} AND {VALID}"}


def reason(log) -> str:
    return log.decision["reason_code"]


# ---------------------------------------------------------------- invalid model output


def test_invalid_parse_json_abstains(cfg, split, catalog):
    sub, log = run_one(Q, "not json {", cfg=cfg, split=split, catalog=catalog)
    assert sub == {"id": "t_q1", "type": "abstain"} and reason(log) == "E_PARSE_INVALID"


def test_parse_frame_violating_invariants_abstains(cfg, split, catalog):
    bad = {"expected_type": "number", "time": MONTH_FEB}  # numeric_kind missing
    sub, log = run_one(Q, bad, cfg=cfg, split=split, catalog=catalog)
    assert sub["type"] == "abstain" and reason(log) == "E_PARSE_INVALID"


def test_invented_time_span_abstains(cfg, split, catalog):
    frame = {**FRAME, "time": [{**MONTH_FEB[0], "span": "tháng 3/2026"}]}
    sub, log = run_one(Q, frame, cfg=cfg, split=split, catalog=catalog)
    assert sub["type"] == "abstain" and reason(log) == "E_PARSE_INVALID"


def test_invalid_solver_json_is_repaired(cfg, split, catalog):
    sub, log = run_one(Q, FRAME, '{"sql": ', GOOD_SQL, cfg=cfg, split=split, catalog=catalog)
    assert sub == {"id": "t_q1", "type": "number", "answer": 341001}
    assert [a["error_code"] for a in log.attempts] == ["E_SOLVER_OUTPUT_INVALID", None]


def test_repairs_exhausted_abstains(cfg, split, catalog):
    sub, log = run_one(Q, FRAME, {"sql": "SELECT nope FROM ban_hang"},
                       {"sql": "SELECT still_nope FROM ban_hang"},
                       cfg=cfg, split=split, catalog=catalog)
    assert sub["type"] == "abstain" and reason(log) == "E_SQL_EXEC"
    assert log.code == ["SELECT nope FROM ban_hang", "SELECT still_nope FROM ban_hang"]


def test_missing_scripted_response_abstains(cfg, split, catalog):
    sub, log = run_one(Q, FRAME, cfg=cfg, split=split, catalog=catalog)  # no solve response
    assert sub["type"] == "abstain" and reason(log) == "E_SCRIPT_MISS"


def test_wrong_result_shape_abstains(cfg, split, catalog):
    sql = {"sql": f"SELECT ma_don, SUM(thanh_tien) FROM ban_hang WHERE {FEB} GROUP BY ma_don ORDER BY ma_don"}
    sub, log = run_one(Q, FRAME, sql, sql, cfg=cfg, split=split, catalog=catalog)
    assert sub["type"] == "abstain" and reason(log) == "E_TYPE_CONTRACT"


def test_text_where_number_expected_abstains(cfg, split, catalog):
    sql = {"sql": "SELECT 'nhiều lắm' AS value"}
    sub, log = run_one(Q, FRAME, sql, sql, cfg=cfg, split=split, catalog=catalog)
    assert sub["type"] == "abstain" and reason(log) == "E_TYPE_CONTRACT"


def test_division_by_zero_infinity_is_implausible(cfg, split, catalog):
    frame = {"expected_type": "percent", "time": MONTH_FEB}
    sub, log = run_one(Q, frame, {"sql": "SELECT 1.0 / 0 AS value"},
                       cfg=cfg, split=split, catalog=catalog)
    assert sub["type"] == "abstain" and reason(log) == "D_IMPLAUSIBLE"


# ---------------------------------------------------------------- invalid / unsafe SQL


def test_check_sql_rules():
    assert check_sql("SELECT 1")[0] is None
    assert check_sql("WITH a AS (SELECT 1 AS x) SELECT x FROM a")[0] is None
    assert check_sql("SELECT 1; SELECT 2")[0] == "E_SQL_NOT_SELECT"
    assert check_sql("DELETE FROM ban_hang")[0] == "E_SQL_NOT_SELECT"
    assert check_sql("SELECT * FROM ban_hang LIMIT 1")[0] == "E_SQL_NONDETERMINISTIC"
    assert check_sql("SELECT 'LIMIT 1' AS value")[0] is None  # inside a literal
    assert check_sql("SELEC 1")[0] == "E_SQL_EXEC"


def test_executor_is_read_only_without_file_access(catalog):
    limits = ExecLimits()
    for sql in ["SELECT * FROM read_csv('/etc/passwd')",
                "COPY ban_hang TO 'leak.csv'",
                "CREATE TABLE x AS SELECT 1",
                "ATTACH 'other.duckdb'"]:
        res = run_sql(catalog.db_path, sql, limits)
        assert not res.ok and res.error_code == "E_SQL_EXEC", sql


def test_executor_timeout(catalog):
    res = run_sql(catalog.db_path,
                  "WITH RECURSIVE r(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM r) SELECT count(*) FROM r",
                  ExecLimits(sql_timeout_s=0.3))
    assert not res.ok and res.error_code == "E_SQL_TIMEOUT"


def test_executor_keeps_exact_types(catalog):
    res = run_sql(catalog.db_path, f"SELECT SUM(thanh_tien) AS s, AVG(thanh_tien) AS a, "
                  f"MIN(ngay_dat) AS d FROM ban_hang WHERE {FEB}", ExecLimits())
    s, a, d = res.rows[0]
    assert type(s) is int and s == 440001
    assert str(a) == "48889.0" and type(a).__name__ == "Decimal"  # DOUBLE → Decimal(repr)
    assert d.isoformat() == "2026-02-03"


# ---------------------------------------------------------------- missing information vs zero


def test_computed_zero_is_an_answer(cfg, split, catalog):
    q = "Tháng 2/2026 bán được mấy cái Bánh mì que kẹp?"
    frame = {"expected_type": "number", "numeric_kind": "count", "time": MONTH_FEB}
    sql = {"sql": f"SELECT COALESCE(SUM(so_luong), 0) AS value FROM ban_hang "
                  f"WHERE ten_hang = 'Bánh mì que kẹp' AND {FEB} AND {VALID}"}
    sub, log = run_one(q, frame, sql, cfg=cfg, split=split, catalog=catalog)
    assert sub == {"id": "t_q1", "type": "number", "answer": 0}


def test_null_result_abstains_instead_of_zero(cfg, split, catalog):
    sql = {"sql": f"SELECT SUM(thanh_tien) AS value FROM ban_hang WHERE ten_hang = 'Không có' AND {FEB}"}
    sub, log = run_one(Q, FRAME, sql, cfg=cfg, split=split, catalog=catalog)
    assert sub["type"] == "abstain" and reason(log) == "E_EMPTY_RESULT"
    assert len(log.attempts) == 1  # empty results are not "repaired" into a number


def test_no_rows_abstains(cfg, split, catalog):
    q = "Khách nào mua nhiều nhất tháng 2/2026?"
    frame = {"expected_type": "string", "time": MONTH_FEB}
    sql = {"sql": "SELECT khach_hang AS value FROM ban_hang WHERE khach_hang = 'Không ai' "
                  "ORDER BY khach_hang LIMIT 1"}
    sub, log = run_one(q, frame, sql, cfg=cfg, split=split, catalog=catalog)
    assert sub["type"] == "abstain" and reason(log) == "E_EMPTY_RESULT"


def test_period_without_data_is_unanswerable_not_zero(cfg, split, catalog):
    q = "Doanh thu tháng 6/2025 là bao nhiêu?"
    frame = {**FRAME, "time": [{"span": "tháng 6/2025", "expr": {
        "kind": "calendar_period", "unit": "month", "year": 2025, "index": 6}}]}
    sub, log = run_one(q, frame, cfg=cfg, split=split, catalog=catalog)
    assert sub["type"] == "unanswerable" and log.code is None  # no SQL was run


def test_comparison_period_without_data_is_unanswerable(cfg, split, catalog):
    q = "Doanh thu tháng 1/2026 thay đổi bao nhiêu % so với tháng 12/2025?"
    frame = {"expected_type": "percent", "time": [
        {"span": "tháng 1/2026", "expr": {"kind": "calendar_period", "unit": "month", "year": 2026, "index": 1}},
        {"span": "tháng 12/2025", "role": "baseline",
         "expr": {"kind": "calendar_period", "unit": "month", "year": 2025, "index": 12}}]}
    sub, _ = run_one(q, frame, cfg=cfg, split=split, catalog=catalog)
    assert sub["type"] == "unanswerable"


def test_zero_coverage_policy_can_abstain(tmp_path, split, catalog):
    cfg = load_config(None, ["decision.zero_coverage=abstain", f"work_dir={tmp_path}"])
    q = "Doanh thu tháng 6/2025 là bao nhiêu?"
    frame = {**FRAME, "time": [{"span": "tháng 6/2025", "expr": {
        "kind": "calendar_period", "unit": "month", "year": 2025, "index": 6}}]}
    sub, _ = run_one(q, frame, cfg=cfg, split=split, catalog=catalog)
    assert sub["type"] == "abstain"


def test_partially_covered_period_is_computed(cfg, split, catalog):
    q = "Doanh thu tháng 1/2026 là bao nhiêu?"  # data starts 2026-01-20
    frame = {**FRAME, "time": [{"span": "tháng 1/2026", "expr": {
        "kind": "calendar_period", "unit": "month", "year": 2026, "index": 1}}]}
    sql = {"sql": f"SELECT SUM(thanh_tien) AS value FROM ban_hang WHERE ngay_dat "
                  f"BETWEEN DATE '2026-01-01' AND DATE '2026-01-31' AND {VALID}"}
    sub, _ = run_one(q, frame, sql, cfg=cfg, split=split, catalog=catalog)
    assert sub == {"id": "t_q1", "type": "number", "answer": 93000}


def test_missing_field_claim_is_checked_against_catalog(cfg, split, catalog):
    # The model claims "đơn giá" is missing, but the column exists: do not say unanswerable.
    q = "Đơn giá trung bình tháng 2/2026 là bao nhiêu?"
    frame = {**FRAME, "answerability": {"status": "missing_field", "missing_fields": ["đơn giá"]}}
    sql = {"sql": f"SELECT AVG(don_gia) AS value FROM ban_hang WHERE {FEB} AND {VALID}"}
    sub, _ = run_one(q, frame, sql, cfg=cfg, split=split, catalog=catalog)
    assert sub["type"] == "number"


def test_confirmed_missing_field_is_unanswerable(cfg, split, catalog):
    q = "Lãi gộp tháng 2/2026 là bao nhiêu?"
    frame = {**FRAME, "answerability": {"status": "missing_field", "missing_fields": ["giá vốn"]}}
    sub, log = run_one(q, frame, cfg=cfg, split=split, catalog=catalog)
    assert sub == {"id": "t_q1", "type": "unanswerable", "reason": "missing_field:giá vốn"}
    assert reason(log) == "D_UNANSWERABLE_CONFIRMED"
