"""M2-07 rule-level regressions using synthetic catalog evidence."""

from datetime import date
from decimal import Decimal

import pytest

from datamate.config import DecisionConfig, RunConfig
from datamate.contracts import (
    Answerability,
    BusinessCatalog,
    ColumnInfo,
    ExecutionResult,
    ListValue,
    ModelCall,
    QuestionFrame,
    ScalarValue,
    SolverAttempt,
    TableInfo,
    TimeRef,
    TimeWindow,
    codes,
)
from datamate.decision import decide, field_in_catalog, pre_solve_decision

CONFIG = RunConfig()
DAY = date(2026, 3, 4)
CALL = ModelCall(call_id="synthetic:solve", stage="solve", template_id="solve.sql.v1", backend="scripted",
                 request_sha256="", params={}, content="", reasoning=None, finish_reason="stop", latency_ms=0)


def _column(name, original):
    return ColumnInfo(name=name, original_name=original, sql_type="DECIMAL(38,6)", null_count=0,
                      distinct_count=1)


@pytest.fixture
def evidence_catalog():
    tables = [
        TableInfo(name="sales", source_file="sales.csv", row_count=1,
                  columns=[_column("price", "Đơn giá"), _column("revenue", "Doanh thu")]),
        TableInfo(name="stock", source_file="stock.csv", row_count=1,
                  columns=[_column("quantity", "Số lượng"), _column("stock_code", "Mã hàng")]),
    ]
    return BusinessCatalog(business_id="synthetic", bkey="test", db_path="", tables=tables,
                           data_range=None, readme_text=None, schema_card="", schema_card_sha256="")


def _frame(status="answerable", field=None, **changes):
    return QuestionFrame(**{"expected_type": "number", "numeric_kind": "measure", **changes},
                         answerability=Answerability(status=status, missing_fields=[field] if field else []))


def _number(value):
    return ScalarValue(type="number", value=Decimal(value))


def _attempt(value=None, *, error=None, execution=None):
    return SolverAttempt(attempt_no=1, stage="solve", model_call=CALL, solver_output=None,
                         execution=execution, ok=error is None, error_code=error, value=value)


def _window(ratio, role="primary", ref_index=0):
    return TimeWindow(ref_index=ref_index, role=role, start=DAY, end=DAY,
                      granularity="day", coverage_ratio=ratio)


@pytest.mark.parametrize("frame, windows, attempts, error, expected", [
    pytest.param(_frame(), [], [], codes.E_PARSE_INVALID, ("abstain", codes.E_PARSE_INVALID), id="1-parse"),
    pytest.param(_frame("unclear"), [_window(0)], [], None, ("abstain", codes.D_UNCLEAR), id="2-unclear"),
    pytest.param(_frame("missing_field", "giá vốn"), [], [], None,
                 ("unanswerable", codes.D_UNANSWERABLE_CONFIRMED), id="3-missing"),
    pytest.param(_frame(), [_window(0)], [], None,
                 ("unanswerable", codes.D_UNANSWERABLE_OUT_OF_RANGE), id="4-coverage"),
    pytest.param(_frame(), [], [], None, ("abstain", codes.E_NO_SUCCESS), id="5-no-attempt"),
    pytest.param(_frame(), [], [_attempt(error=codes.E_SQL_EXEC)], None,
                 ("abstain", codes.E_SQL_EXEC), id="5-sql-error"),
    pytest.param(_frame(), [], [_attempt(ScalarValue(type="boolean", value=True))], None,
                 ("abstain", codes.E_TYPE_CONTRACT), id="6-type"),
    pytest.param(_frame(expected_type="percent"), [],
                 [_attempt(ScalarValue(type="percent", value=Decimal("100001")))], None,
                 ("abstain", codes.D_IMPLAUSIBLE), id="7-implausible"),
    pytest.param(_frame(), [_window(1)], [_attempt(_number(0))], None,
                 ("answer", codes.D_ANSWER), id="8-computed-zero"),
    pytest.param(_frame(), [_window(0.5)], [_attempt(_number(3))], None,
                 ("answer", codes.D_ANSWER), id="8-partial-coverage"),
])
def test_eight_gate_rules(evidence_catalog, frame, windows, attempts, error, expected):
    decision = decide(frame, windows, attempts, evidence_catalog, CONFIG, error)
    assert (decision.kind, decision.reason_code) == expected


@pytest.mark.parametrize("field, readme, status, source, expected_kind", [
    ("sales.price", None, "present", "catalog_exact", "answer"),
    ("Đơn giá", None, "present", "catalog_exact", "answer"),
    ("Tồn kho", "- Tồn kho: stock.quantity", "present", "readme_mapping", "answer"),
    ("Giá bán", "- sales.price: Giá bán", "present", "readme_mapping", "answer"),
    ("Số lượng", "- Không có cột: Số lượng", "conflict", "catalog_vs_readme", "answer"),
    ("Đơn giá", "- Đơn giá: stock.quantity", "conflict", "catalog_vs_readme", "answer"),
    ("Tên khách", "Báo cáo tham khảo Tên khách từ nguồn khác.", "uncertain", "readme_mention", "answer"),
    ("Tồn kho", "- Tồn kho: warehouse.inventory", "uncertain", "readme_mention", "answer"),
    ("quantitty", None, "uncertain", "catalog_fuzzy", "answer"),
    ("giá vốn", None, "absent", "catalog_no_match", "unanswerable"),
    ("thu", None, "absent", "catalog_no_match", "unanswerable"),
    ("giá vốn", "- Không ghi giá vốn", "absent", "readme_absence", "unanswerable"),
])
def test_catalog_evidence(evidence_catalog, field, readme, status, source, expected_kind):
    catalog = evidence_catalog.model_copy(update={"readme_text": readme})
    decision = decide(_frame("missing_field", field), [], [_attempt(_number(7))], catalog, CONFIG, None)
    assert decision.kind == expected_kind
    assert decision.reason_code == (codes.D_ANSWER if expected_kind == "answer" else codes.D_UNANSWERABLE_CONFIRMED)
    evidence, = decision.features["missing_field_evidence"]
    assert (evidence["field"], evidence["status"], evidence["source"]) == (field, status, source)


def test_ambiguous_fuzzy_candidates_are_not_catalog_proof(evidence_catalog):
    columns = [_column("quantita", "Quantita"), _column("quantity", "Quantity")]
    table = evidence_catalog.tables[1].model_copy(update={"columns": columns})
    catalog = evidence_catalog.model_copy(update={"tables": [table]})
    frame = _frame("missing_field", "quantitx")
    assert not field_in_catalog("quantitx", catalog)
    assert pre_solve_decision(frame, [], catalog, CONFIG) is None
    decision = decide(frame, [], [], catalog, CONFIG, None)
    evidence, = decision.features["missing_field_evidence"]
    assert evidence == {"field": "quantitx", "status": "uncertain", "source": "catalog_fuzzy",
                        "columns": ["stock.quantita", "stock.quantity"]}
    assert decision.reason_code == codes.E_NO_SUCCESS


def test_multi_table_matches_can_be_disambiguated_by_qualifier(evidence_catalog):
    stock = evidence_catalog.tables[1].model_copy(update={"columns": [_column("price", "Đơn giá")]})
    catalog = evidence_catalog.model_copy(update={"tables": [evidence_catalog.tables[0], stock]})
    decision = decide(_frame("missing_field", "Đơn giá"), [], [], catalog, CONFIG, None)
    evidence, = decision.features["missing_field_evidence"]
    assert evidence["source"] == "catalog_ambiguous"
    assert evidence["columns"] == ["sales.price", "stock.price"]
    assert field_in_catalog("stock.price", catalog)


def test_partial_catalog_cannot_confirm_missing_field(evidence_catalog):
    catalog = evidence_catalog.model_copy(update={"warnings": [codes.W_UNSUPPORTED_FILE + " skipped.xlsx"]})
    frame = _frame("missing_field", "giá vốn")
    assert pre_solve_decision(frame, [], catalog, CONFIG) is None
    decision = decide(frame, [], [_attempt(error=codes.E_SQL_EXEC)], catalog, CONFIG, None)
    assert decision.reason_code == codes.E_SQL_EXEC
    assert decision.features["missing_field_evidence"][0]["source"] == "catalog_incomplete"


@pytest.mark.parametrize("ratio, policy, expected, state", [
    (0, "unanswerable", ("unanswerable", codes.D_UNANSWERABLE_OUT_OF_RANGE), "zero"),
    (0, "abstain", ("abstain", codes.D_UNANSWERABLE_OUT_OF_RANGE), "zero"),
    (0.5, "unanswerable", ("answer", codes.D_ANSWER), "partial"),
    (1, "unanswerable", ("answer", codes.D_ANSWER), "full"),
    (None, "unanswerable", ("answer", codes.D_ANSWER), "unknown"),
])
def test_comparison_coverage(evidence_catalog, ratio, policy, expected, state):
    cfg = RunConfig(decision=DecisionConfig(zero_coverage=policy))
    windows = [_window(1), _window(ratio, "comparison", 1)]
    decision = decide(_frame(), windows, [_attempt(_number(0))], evidence_catalog, cfg, None)
    assert (decision.kind, decision.reason_code) == expected
    assert decision.features["coverage"][1] == {"ref_index": 1, "role": "comparison", "ratio": ratio, "state": state}


def test_missing_explicit_comparison_window_abstains(evidence_catalog):
    refs = [TimeRef(span="kỳ trước", role="baseline", expr={"kind": "all_time"})]
    decision = decide(_frame(time=refs), [], [_attempt(_number(0))], evidence_catalog, CONFIG, None)
    assert (decision.kind, decision.reason_code) == ("abstain", codes.E_TIME_UNSUPPORTED)
    assert decision.features["missing_comparison_refs"] == [0]


@pytest.mark.parametrize("rows, row_count, error, expected_state", [
    ([[None]], 1, codes.E_EMPTY_RESULT, "null_scalar"),
    ([], 0, codes.E_EMPTY_RESULT, "empty"),
    ([], 0, codes.E_SQL_EXEC, "error"),
    ([[0]], 1, None, "rows"),
])
def test_execution_state_is_not_an_answerability_guess(evidence_catalog, rows, row_count, error, expected_state):
    execution = ExecutionResult(code="SELECT ...", ok=error != codes.E_SQL_EXEC,
                                columns=["value"], rows=rows, row_count=row_count,
                                error_code=error if error == codes.E_SQL_EXEC else None)
    attempt = _attempt(_number(0) if error is None else None, error=error, execution=execution)
    decision = decide(_frame(), [], [attempt], evidence_catalog, CONFIG, None)
    assert decision.reason_code == (error or codes.D_ANSWER)
    assert decision.features["execution_state"] == expected_state
    assert decision.features["row_count"] == (None if error == codes.E_SQL_EXEC else row_count)
    assert decision.features["has_null"] is (rows == [[None]])


def test_valid_empty_list_stays_an_answer(evidence_catalog):
    value = ListValue(order="question_order", items=[])
    execution = ExecutionResult(code="SELECT ...", ok=True, columns=["ord", "item"])
    frame = _frame(expected_type="list", list_order="question_order")
    decision = decide(frame, [_window(1)], [_attempt(value, execution=execution)], evidence_catalog, CONFIG, None)
    assert (decision.kind, decision.reason_code, decision.value) == ("answer", codes.D_ANSWER, value)
    assert decision.features["execution_state"] == "empty"
