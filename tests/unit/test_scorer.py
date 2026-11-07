"""Local scorer (Lead) against Brief §2.1 examples. Independent of the formatter."""

from __future__ import annotations

from decimal import Decimal

from datamate.eval.score import normalize_string, score_one


def ref(t, answer=None, alias=None):
    return {"id": "q", "type": t, "answer": answer, "alias": alias or []}


def pred(t, answer=None):
    return {"id": "q", "type": t, "answer": answer}


def test_string_normalization_keeps_diacritics():
    assert normalize_string("  Sting  DÂU-330ml! ") == "sting dâu 330ml"
    assert score_one(pred("string", "sting dâu 330ml"), ref("string", "Sting dâu 330ml")) == 1
    assert score_one(pred("string", "Sting dầu 330ml"), ref("string", "Sting dâu 330ml")) == -1
    assert score_one(pred("string", "Sting dau 330ml"), ref("string", "Sting dâu 330ml")) == -1
    assert score_one(pred("string", "sp0042"), ref("string", "Sting dâu 330ml", ["SP0042"])) == 1


def test_numbers_and_percents():
    assert score_one(pred("number", 48250000), ref("number", 48250000)) == 1
    assert score_one(pred("number", 48250001), ref("number", 48250000)) == -1
    assert score_one(pred("number", "48250000"), ref("number", 48250000)) == -1
    assert score_one(pred("percent", Decimal("-12.45")), ref("percent", -12.45)) == 1
    assert score_one(pred("percent", 12.45), ref("percent", -12.45)) == -1


def test_type_must_match_and_abstain_scores_zero():
    assert score_one(pred("percent", 5), ref("number", 5)) == -1
    assert score_one({"id": "q", "type": "abstain"}, ref("number", 5)) == 0
    assert score_one(None, ref("number", 5)) == 0
    assert score_one(pred("unanswerable"), ref("unanswerable")) == 1
    assert score_one(pred("unanswerable"), ref("number", 0)) == -1
    assert score_one(pred("number", 0), ref("unanswerable")) == -1


def test_boolean_and_date_exact():
    assert score_one(pred("boolean", True), ref("boolean", True)) == 1
    assert score_one(pred("boolean", 1), ref("boolean", True)) == -1
    assert score_one(pred("date", "2025-09"), ref("date", "2025-09")) == 1
    assert score_one(pred("date", "2025-09-01"), ref("date", "2025-09")) == -1


def test_list_is_ordered_with_positional_aliases():
    r = ref("list", ["Cà phê sữa", "Bạc xỉu"], [["SP01"], ["SP02"]])
    assert score_one(pred("list", ["cà phê sữa", "sp02"]), r) == 1
    assert score_one(pred("list", ["Bạc xỉu", "Cà phê sữa"]), r) == -1
    assert score_one(pred("list", ["Cà phê sữa"]), r) == -1


def test_table_columns_by_name_rows_as_set():
    r = ref("table", {"columns": ["khach_hang", "so_tien_no"],
                      "rows": [["Chị Lan", 3200000], ["Anh Tú", 1500000]]})
    swapped = {"columns": ["so_tien_no", "khach_hang"], "rows": [[1500000, "Anh Tú"], [3200000, "Chị Lan"]]}
    assert score_one(pred("table", swapped), r) == 1
    renamed = {"columns": ["ten", "no"], "rows": [["Anh Tú", 1500000], ["Chị Lan", 3200000]]}
    assert score_one(pred("table", renamed), r) == 1  # by position when names differ
    wrong = {"columns": ["khach_hang", "so_tien_no"], "rows": [["Chị Lan", 3200000]]}
    assert score_one(pred("table", wrong), r) == -1
