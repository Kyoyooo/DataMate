"""Check M2-07 against catalogs built by the M1 ingestion path."""

from datetime import date

import pytest

from datamate.catalog import setup_business
from datamate.contracts import DateRange, codes

from conftest import run_one


@pytest.fixture(scope="module")
def activity_catalog(tmp_path_factory):
    root = tmp_path_factory.mktemp("m1-decision")
    source = root / "source"
    source.mkdir()
    (source / "sales.csv").write_text(
        "Code,Date,Expiry,Doanh thu,Fee\n"
        "001,2026-03-01,2028-01-01,100,10\n"
        "002,2026-03-04,2028-02-01,200,20\n",
        encoding="utf-8",
    )
    (source / "README.md").write_text(
        "Tiền thực thu: sales.doanh_thu\n"
        "Khoản đối chiếu: sales.doanh_thu\n"
        "Khoản đối chiếu: sales.fee\n",
        encoding="utf-8",
    )
    catalog = setup_business(source, "biz_fx01", root / "work")
    assert catalog.status == "ready", catalog.warnings
    return catalog


@pytest.mark.parametrize(
    "claim, status, source, columns",
    [
        ("Doanh thu", "present", "catalog_exact", ["sales.doanh_thu"]),
        ("Tiền thực thu", "present", "readme_mapping", ["sales.doanh_thu"]),
        ("Khoản đối chiếu", "uncertain", "readme_ambiguous", ["sales.doanh_thu", "sales.fee"]),
        ("Giá vốn nhập hàng", "absent", "catalog_no_match", []),
    ],
)
def test_catalog_field_claims_control_whether_sql_runs(
    cfg, split, activity_catalog, claim, status, source, columns,
):
    frame = {
        "expected_type": "number",
        "numeric_kind": "money",
        "answerability": {"status": "missing_field", "missing_fields": [claim]},
    }
    solves = [] if status == "absent" else [{"sql": "SELECT SUM(doanh_thu) AS value FROM sales"}]
    record, log = run_one(
        f"{claim} là bao nhiêu?", frame, *solves, cfg=cfg, split=split, catalog=activity_catalog,
    )

    assert log.decision["features"]["missing_field_evidence"] == [
        {"field": claim, "status": status, "source": source, "columns": columns},
    ]
    if status == "absent":
        assert record["type"] == "unanswerable"
        assert log.decision["reason_code"] == codes.D_UNANSWERABLE_CONFIRMED
        assert log.code is None and [c.stage for c in log.calls] == ["parse"]
    else:
        assert record == {"id": "t_q1", "type": "number", "answer": 300}
        assert log.decision["reason_code"] == codes.D_ANSWER
        assert [c.stage for c in log.calls] == ["parse", "solve"]


@pytest.mark.parametrize(
    "comparison_end, ratio, state",
    [("2026-02-28", 0.0, "zero"), ("2026-03-01", 0.5, "partial")],
)
def test_catalog_activity_bounds_reach_the_gate(
    cfg, split, activity_catalog, comparison_end, ratio, state,
):
    assert activity_catalog.data_range == DateRange(start=date(2026, 3, 1), end=date(2026, 3, 4))
    span = f"2026-02-28 đến {comparison_end}"
    frame = {"expected_type": "boolean", "time": [
        {"span": "Tháng này", "expr": {"kind": "relative_period", "unit": "month", "offset": 0}},
        {"span": span, "role": "comparison",
         "expr": {"kind": "date_range", "start": "2026-02-28", "end": comparison_end}},
    ]}
    sql = (
        "SELECT COUNT(*) FILTER (WHERE date BETWEEN DATE '2026-03-01' AND DATE '2026-03-04')"
        f" > COUNT(*) FILTER (WHERE date BETWEEN DATE '2026-02-28' AND DATE '{comparison_end}')"
        " AS value FROM sales"
    )
    solves = [] if state == "zero" else [{"sql": sql}]
    record, log = run_one(
        f"Tháng này có nhiều đơn hơn kỳ {span} không?", frame, *solves,
        cfg=cfg, split=split, catalog=activity_catalog,
    )

    assert log.decision["features"]["coverage"] == [
        {"ref_index": 0, "role": "primary", "ratio": 1.0, "state": "full"},
        {"ref_index": 1, "role": "comparison", "ratio": ratio, "state": state},
    ]
    if state == "zero":
        assert record["type"] == "unanswerable"
        assert log.decision["reason_code"] == codes.D_UNANSWERABLE_OUT_OF_RANGE
        assert log.code is None and [c.stage for c in log.calls] == ["parse"]
    else:
        assert record == {"id": "t_q1", "type": "boolean", "answer": True}
        assert log.decision["reason_code"] == codes.D_ANSWER
        assert [c.stage for c in log.calls] == ["parse", "solve"]
