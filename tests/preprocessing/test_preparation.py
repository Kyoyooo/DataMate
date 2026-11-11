"""Independent expectations for preprocessing edge cases required by SPEC §7.1–7.2."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest
from openpyxl import Workbook

from datamate.ingest.common import implementation_digest, json_text, sha256_file
from datamate.ingest.engine import (
    DataConfig,
    infer_data_column,
    numeric_convention,
    parse_numeric,
    prepare_data,
    row_kinds,
    source_fragments,
    split_blocks,
)
from datamate.preprocessing.calendar import LunarCalendar, parse_calendar, prepare_calendar
from datamate.preprocessing.qa import load_questions, prepare_qa
from datamate.preprocessing.rulebook import (
    build_rule_graph,
    parse_rules,
    prepare_rulebook,
    retrieve_evidence,
    validate_temporal_fields,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/split_mini"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1.250.000", "1250000"),
        ("1,5", "1.5"),
        ("150k", "150000"),
        ("1tr2", "1200000"),
        ("2k5", "2500"),
        ("12,5%", "12.5"),
        ("(12.500 đồng)", "-12500"),
        ("1\u00a0250 vnđ", "1250"),
    ],
)
def test_numeric_examples(raw, expected):
    assert parse_numeric(raw)[0] == Decimal(expected)


@pytest.mark.parametrize("token", ["", "N/A", "NA", "none", "null", "nan", "-", "--", "—"])
def test_null_tokens(token):
    assert parse_numeric(token) == (None, "missing")


def test_numeric_ambiguity_and_identifier_protection():
    assert numeric_convention(["1,234", "2,345"])[0] is None
    ambiguous = infer_data_column("Thành tiền", ["1,234", "2,345"], DataConfig())
    assert ambiguous["sql_type"] == "VARCHAR"
    assert "W_NUMERIC_AMBIGUOUS" in ambiguous["warnings"]
    assert infer_data_column("Mã hàng", ["001", "002"], DataConfig())["values"] == ["001", "002"]
    assert infer_data_column("Địa chỉ", ["12", "34"], DataConfig())["sql_type"] == "VARCHAR"


def test_column_date_evidence_and_conflict():
    result = infer_data_column("Ngày", ["01/13/2025", "02/03/2025"], DataConfig())
    assert result["values"] == [date(2025, 1, 13), date(2025, 2, 3)]
    conflict = infer_data_column("Ngày", ["13/01/2025", "01/13/2025"], DataConfig())
    assert conflict["sql_type"] == "VARCHAR"
    assert "W_DATE_AMBIGUOUS" in conflict["warnings"]
    assumed = infer_data_column("Ngày", ["01/02/2025"], DataConfig())
    assert assumed["values"] == [date(2025, 2, 1)]
    assert "W_DATE_ASSUMED_DMY" in assumed["warnings"]


def test_months_serial_and_datetime():
    months = infer_data_column("Tháng", ["2025-09", "10/2025"], DataConfig())
    assert months["values"] == [date(2025, 9, 1), date(2025, 10, 1)]
    assert months["format_note"] == "month"
    assert infer_data_column("Period", ["09/2025"], DataConfig())["format_note"] == "month"
    serial = infer_data_column("Ngày", [45292], DataConfig())
    assert serial["values"] == [date(2024, 1, 1)]
    old_epoch = infer_data_column("Ngày", [43830], DataConfig(), "1904-01-01T00:00:00")
    assert old_epoch["values"] == [date(2024, 1, 1)]
    timestamp = infer_data_column("Ngày", ["2025-09-01 13:14:15"], DataConfig())
    assert timestamp["sql_type"] == "TIMESTAMP"
    assert timestamp["values"] == [datetime(2025, 9, 1, 13, 14, 15)]


def test_quantities_keep_units_without_conversion():
    result = infer_data_column("Số lượng", ["2 thùng", "3 bao 25kg"], DataConfig())
    assert result["values"] == [Decimal(2), Decimal(3)]
    assert result["units"] == ["thùng", "bao 25kg"]
    ambiguous = infer_data_column("SL", ["1,234 chai"], DataConfig())
    assert ambiguous["sql_type"] == "VARCHAR"
    assert "W_NUMERIC_AMBIGUOUS" in ambiguous["warnings"]
    assert infer_data_column("Số điện thoại", ["0901234567"], DataConfig())["values"] == [
        "0901234567"
    ]


def test_two_blocks_and_total_rows():
    blocks = split_blocks(
        [
            ["Ngày", "Mã", "Tiền"],
            ["01/01/2025", "SP01", 100],
            [None] * 3,
            [None] * 3,
            ["Ngày", "Mã", "SL"],
            ["02/01/2025", "SP02", 2],
        ],
        DataConfig(),
    )
    assert len(blocks) == 2
    assert blocks[0]["headers"] == ["Ngày", "Mã", "Tiền"]
    assert blocks[1]["headers"] == ["Ngày", "Mã", "SL"]
    assert blocks[0]["source_rows"] == [2]
    assert blocks[1]["source_rows"] == [6]
    assert row_kinds(
        ["Mã", "SL", "Tiền"], [["SP01", 2, 100], ["SP02", 3, 200], ["Tổng cộng", 5, 300]]
    ) == ["data", "data", "summary"]


def test_sparse_title_is_not_chosen_as_header():
    blocks = split_blocks(
        [
            ["Sales report for 2025", None, None],
            ["Ngày", "Mã", "Tiền"],
            ["2025-01-01", "001", 10],
        ],
        DataConfig(),
    )
    assert len(blocks) == 1
    assert blocks[0]["header_row"] == 2
    assert blocks[0]["prefix_rows"][0]["source_row"] == 1


def test_merged_header_new_header_and_notes():
    blocks = split_blocks(
        [
            ["Sales", None, "Stock"],
            ["Ngày", "SL", None],
            ["01/01/2025", 2, 3],
            ["Note: exported", None, None],
        ],
        DataConfig(),
    )
    assert len(blocks) == 1
    assert blocks[0]["headers"] == ["Sales Ngày", "Sales SL", "Stock"]
    assert blocks[0]["row_kinds"] == ["data", "note"]
    repeated = split_blocks([["Mã", "Tiền"], ["A", 1], ["Mã", "Tiền"], ["B", 2]], DataConfig())
    assert len(repeated) == 2


def test_sqlite_tables_and_views_without_source_writes(tmp_path):
    path = tmp_path / "source.sqlite"
    connection = sqlite3.connect(path)
    connection.executescript(
        "CREATE TABLE orders(id TEXT, amount INTEGER); INSERT INTO orders VALUES('001',100); CREATE VIEW totals AS SELECT SUM(amount) AS amount FROM orders;"
    )
    connection.close()
    before = sha256_file(path)
    fragments = list(source_fragments(path, DataConfig()))
    assert {part for part, _, _, _ in fragments} == {"orders", "totals"}
    assert sha256_file(path) == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["source.sqlite"]


def test_sqlite_live_wal_is_read_from_scratch_without_losing_commits(tmp_path):
    path = tmp_path / "live.sqlite"
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE orders(id INTEGER)")
        connection.execute("INSERT INTO orders VALUES (7)")
        connection.commit()
        before = {p.name: sha256_file(p) for p in tmp_path.iterdir()}
        fragments = list(source_fragments(path, DataConfig()))
        assert fragments[0][2]["rows"] == [[7]]
        assert {p.name: sha256_file(p) for p in tmp_path.iterdir()} == before
    finally:
        connection.close()


def test_uncached_excel_formulas_are_reported(tmp_path):
    workbook = Workbook()
    workbook.active.append(["Mã", "Tiền"])
    workbook.active.append(["A", "=1+2"])
    path = tmp_path / "formulas.xlsx"
    workbook.save(path)
    fragments = list(source_fragments(path, DataConfig()))
    assert "W_UNCACHED_FORMULAS B2" in fragments[0][3]["warnings"]


def test_calamine_records_1904_epoch_for_unformatted_serials(tmp_path):
    from openpyxl.utils.datetime import CALENDAR_MAC_1904

    workbook = Workbook()
    workbook.epoch = CALENDAR_MAC_1904
    workbook.active.append(["Ngày", "Tiền"])
    workbook.active.append([43830, 1])
    path = tmp_path / "mac.xlsx"
    workbook.save(path)
    _, _, block, details = next(source_fragments(path, DataConfig()))
    result = infer_data_column("Ngày", [block["rows"][0][0]], DataConfig(), details["excel_epoch"])
    assert result["values"] == [date(2024, 1, 1)]


def test_calendar_round_trip_and_leap_month_distinction(tmp_path):
    path = tmp_path / "calendar.csv"
    path.write_text(
        "date,lunar_year,lunar_month,lunar_day,lunar_leap\n2025-07-25,2025,6,1,false\n2025-07-26,2025,6,1,true\n",
        encoding="utf-8",
    )
    records, report = parse_calendar(path)
    assert report["calendar_ok"]
    calendar = LunarCalendar(records)
    assert calendar.to_solar(2025, 6, 1, True) == date(2025, 7, 26)
    assert calendar.to_solar(2025, 6, 1, False) == date(2025, 7, 25)
    for solar in calendar.solar:
        assert calendar.to_solar(*calendar.to_lunar(solar)) == solar
    assert not calendar.covers(date(2025, 7, 25), date(2025, 7, 27))
    with pytest.raises(KeyError):
        calendar.to_solar(2024, 1, 1)


@pytest.mark.parametrize(
    "second",
    ["2025-01-01,2025,1,2,false", "2025-01-03,2025,1,3,false", "2025-01-02,2025,13,2,false"],
)
def test_invalid_calendar_disables_lunar(tmp_path, second):
    split = tmp_path / "input"
    split.mkdir()
    (split / "calendar.csv").write_text(
        "date,lunar_year,lunar_month,lunar_day,lunar_leap\n2025-01-01,2025,1,1,false\n"
        + second
        + "\n",
        encoding="utf-8",
    )
    assert not prepare_calendar(split, tmp_path / "output")["validation"]["calendar_ok"]


def test_qa_never_reads_test_answers_and_preserves_training_decimal(tmp_path):
    split = tmp_path / "split"
    (split / "data/shop").mkdir(parents=True)
    (split / "questions.jsonl").write_text(
        '{"id":"q1","business_id":"shop","question":"Bao nhiêu?","as_of_date":"2025-01-01"}\n',
        encoding="utf-8",
    )
    answers = split / "answers.jsonl"
    answers.write_text("deliberately invalid JSON", encoding="utf-8")
    result = prepare_qa(split, tmp_path / "output")
    assert result["validation"]["valid"]
    assert not result["validation"]["answers_read"]
    assert not (result["folder"] / "evaluation").exists()
    answers.write_text(
        '{"id":"q1","type":"number","answer":9007199254740993.01,"alias":[]}\n', encoding="utf-8"
    )
    train = prepare_qa(split, tmp_path / "output", split_role="train")
    assert train["validation"]["valid"]
    stored = (train["folder"] / "evaluation/answers.jsonl").read_text()
    assert "9007199254740993.01" in stored
    assert "answers.jsonl" not in (train["folder"] / "inference/questions.jsonl").read_text()


def test_qa_bad_json_does_not_reuse_previous_id(tmp_path):
    (tmp_path / "data/shop").mkdir(parents=True)
    question = {"id": "valid", "business_id": "shop", "question": "x", "as_of_date": "2025-01-01"}
    (tmp_path / "questions.jsonl").write_text(
        json.dumps(question) + "\nbroken\n" + json.dumps(question), encoding="utf-8"
    )
    questions, errors, counts = load_questions(tmp_path)
    assert len(questions) == 1
    assert errors[0]["id"] is None
    assert counts["ignored_duplicate_id"] == 1


def test_qa_path_traversal_rejected(tmp_path):
    row = {"id": "q", "business_id": "../outside", "question": "x", "as_of_date": "2025-01-01"}
    (tmp_path / "questions.jsonl").write_text(json.dumps(row), encoding="utf-8")
    assert load_questions(tmp_path)[1]


def test_rulebook_arbitrary_headings_tables_and_missing_input(tmp_path):
    text = "# Rules\n\n## 14. Sales\n| Term | Meaning |\n| --- | --- |\n| `a|b` | Revenue after discount; see §22. |\n\n## 22. Exceptions\n- Do not count cancelled orders.\n"
    rules, report = parse_rules(text)
    assert report["valid"]
    assert len(rules) == 2
    assert rules[0]["table_cells"][0] == "`a|b`"
    graph = build_rule_graph(rules)
    assert graph["edges"][0]["target"] == rules[1]["rule_id"]
    evidence = retrieve_evidence("Revenue", rules, graph, top_k=1)
    assert len(evidence["rules"]) == 2
    result = prepare_rulebook(tmp_path, tmp_path.parent / (tmp_path.name + "_out"))
    assert result["validation"]["valid"]
    assert "W_RULEBOOK_MISSING" in result["validation"]["warnings"]


def test_temporal_provenance_accepts_exact_span_and_rejects_paraphrase():
    text = "Tuần bắt đầu Chủ nhật. Tháng này tính đến hết hôm nay."
    fields = {
        "week_start": {"value": "sun", "span": "Tuần bắt đầu Chủ nhật."},
        "to_date_end": {"value": "day_before_as_of", "span": "Exclude today"},
        "rolling_includes_as_of": {"value": 1, "span": "hôm nay"},
    }
    result = validate_temporal_fields(text, fields)
    assert result["week_start"] == "sun"
    assert result["provenance"]["week_start"]["source"] == "rulebook"
    assert result["to_date_end"] == "as_of"
    assert result["provenance"]["to_date_end"]["source"] == "generic"
    assert result["provenance"]["rolling_includes_as_of"]["source"] == "generic"


def test_rulebook_uses_one_extractor_call_and_records_actual_response(tmp_path):
    split = tmp_path / "split"
    split.mkdir()
    text = "Tuần bắt đầu Chủ nhật."
    (split / "rulebook.md").write_text(text, encoding="utf-8")
    calls = []

    def extractor(rulebook):
        calls.append(rulebook)
        return {"week_start": {"value": "sun", "span": text}}, {
            "raw_response": "actual synthetic response",
            "thinking": None,
        }

    result = prepare_rulebook(split, tmp_path / "output", temporal_extractor=extractor)
    assert calls == [text]
    assert result["temporal"]["week_start"] == "sun"
    assert result["validation"]["temporal_model_call_performed"]
    assert (
        json.loads((result["folder"] / "model_call.json").read_text())["raw_response"]
        == "actual synthetic response"
    )


def test_live_code_fingerprint_changes_and_decimal_wire():
    namespace = {"__name__": "review"}
    exec("def parse(value): return value + 1", namespace)
    before = implementation_digest(namespace)
    exec("def parse(value): return value + 2", namespace)
    assert before != implementation_digest(namespace)
    assert json_text({"value": Decimal("9007199254740993.01")}) == '{"value":9007199254740993.01}'


def test_fixture_four_components_and_idempotent_catalog(tmp_path):
    data = prepare_data(FIXTURE, tmp_path)
    assert data["validation"]["valid"], data["validation"]
    catalog = data["catalogs"][0]
    business_folder = data["folder"] / "businesses" / catalog["bkey"]
    card = (business_folder / "schema_card.txt").read_bytes()
    database = business_folder / "catalog.duckdb"
    with duckdb.connect(str(database), read_only=True) as connection:
        table = catalog["tables"][0]["name"]
        assert connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] > 0
    again = prepare_data(FIXTURE, tmp_path)
    assert data["folder"] == again["folder"]
    assert (business_folder / "schema_card.txt").read_bytes() == card
    assert prepare_calendar(FIXTURE, tmp_path)["validation"]["valid"]
    assert prepare_qa(FIXTURE, tmp_path, split_role="train")["validation"]["answers"] == 13
    assert prepare_rulebook(FIXTURE, tmp_path)["validation"]["valid"]


def test_excel_all_sheets_and_exact_decimal_storage(tmp_path):
    split = tmp_path / "input"
    business = split / "data/new_shop"
    business.mkdir(parents=True)
    (split / "questions.jsonl").write_text(
        '{"id":"q1","business_id":"new_shop","question":"x","as_of_date":"2025-01-02"}',
        encoding="utf-8",
    )
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sales"
    sheet.append(["Mã", "Thành tiền"])
    sheet.append(["001", "9007199254740993,25"])
    workbook.create_sheet("Stock").append(["Mã", "SL"])
    workbook.save(business / "source.xlsx")
    result = prepare_data(split, tmp_path / "output")
    assert result["validation"]["valid"], result["validation"]
    catalog = result["catalogs"][0]
    assert len(catalog["tables"]) == 2
    sales = next(t for t in catalog["tables"] if t["source_part"] == "Sales")
    database = result["folder"] / "businesses" / catalog["bkey"] / "catalog.duckdb"
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute(f'SELECT thanh_tien FROM "{sales["name"]}"').fetchone()[
            0
        ] == Decimal("9007199254740993.25")
