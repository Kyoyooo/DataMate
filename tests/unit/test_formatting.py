"""Formatter wire values (M2). Expected values follow Brief §2.1–2.2 and rulebook §9."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from datamate.config import FormattingConfig
from datamate.contracts import (
    DateValue,
    Decision,
    ListItem,
    ListValue,
    RankingSpec,
    ScalarValue,
    TableValue,
    dumps,
)
from datamate.formatting import to_submission

CFG = FormattingConfig()


def wire(value, ranking=None, cfg=CFG):
    d = Decision(kind="answer", value=value, reason_code="D_ANSWER")
    return to_submission("q", d, ranking, cfg).to_wire()["answer"]


def num(v: str, kind: str | None, t: str = "number"):
    return ScalarValue(type=t, value=Decimal(v), numeric_kind=kind)


@pytest.mark.parametrize("raw, kind, expected", [
    ("65000.5", "money", 65001),          # half đồng rounds up (rulebook §3, §9)
    ("71269.4999", "money", 71269),
    ("48250000", "money", 48250000),
    ("-12000.5", "money", -12001),       # half-up is away from zero for negatives
    ("18.6", "measure", Decimal("18.6")),
    ("2.675", "measure", Decimal("2.68")),  # binary float would give 2.67
    ("7.000", "count", 7),
    ("-0.001", "measure", 0),            # no negative zero on the wire
])
def test_number_rounding_money_vs_ordinary(raw, kind, expected):
    out = wire(num(raw, kind))
    assert out == expected and type(out) is type(expected)


def test_money_is_exact_at_large_scale():
    out = wire(num("123456789012345.5", "money"))
    assert out == 123456789012346
    assert dumps(out) == "123456789012346"


@pytest.mark.parametrize("raw, expected", [
    ("16.6666666666667", "16.67"), ("-12.445", "-12.45"), ("12.4", "12.4"), ("50", "50"),
])
def test_percent_two_decimals_even_if_marked_money(raw, expected):
    out = wire(num(raw, "money", "percent"))
    assert dumps(out) == expected


def test_half_even_config_changes_only_ties():
    even = FormattingConfig(rounding="ROUND_HALF_EVEN")
    assert wire(num("65000.5", "money"), cfg=even) == 65000
    assert wire(num("65001.5", "money"), cfg=even) == 65002


def test_ranked_list_orders_by_criterion_then_code_and_truncates():
    items = [
        ListItem(item="Bạc xỉu (M)", sort_key=Decimal(2), tie_code="SP03"),
        ListItem(item="Bánh mì que", sort_key=Decimal(3), tie_code="SP04"),
        ListItem(item="Trà đào (M)", sort_key=Decimal(1), tie_code="SP02"),
        ListItem(item="Cà phê sữa (M)", sort_key=Decimal(3), tie_code="SP01"),
    ]
    v = ListValue(order="ranked", items=items)
    assert wire(v, RankingSpec(k=3)) == ["Cà phê sữa (M)", "Bánh mì que", "Bạc xỉu (M)"]
    # bottom-k: ascending criterion, ties still by code ascending
    assert wire(v, RankingSpec(k=2, direction="bottom")) == ["Trà đào (M)", "Bạc xỉu (M)"]
    # fewer candidates than k: all of them
    assert len(wire(v, RankingSpec(k=10))) == 4


def test_ranked_list_numeric_codes_compare_numerically():
    items = [ListItem(item="B", sort_key=Decimal(5), tie_code="10"),
             ListItem(item="A", sort_key=Decimal(5), tie_code="9")]
    assert wire(ListValue(order="ranked", items=items), RankingSpec(k=None)) == ["A", "B"]


def test_question_order_list_is_never_resorted():
    # The question asks for January then February; January is the smaller value.
    items = [ListItem(item=Decimal(341001), position=2), ListItem(item=Decimal(93000), position=1)]
    v = ListValue(order="question_order", items=items, numeric_kind="money")
    assert wire(v) == [93000, 341001]
    # [whole boxes, loose units] keeps its order even when the second is larger
    v2 = ListValue(order="question_order",
                   items=[ListItem(item=Decimal(2), position=1), ListItem(item=Decimal(22), position=2)])
    assert wire(v2) == [2, 22]


def test_question_order_list_requires_unique_positions():
    v = ListValue(order="question_order",
                  items=[ListItem(item="a", position=1), ListItem(item="b", position=1)])
    with pytest.raises(ValueError):
        wire(v)


def test_date_day_and_month_granularity():
    assert wire(DateValue(value=date(2025, 9, 1), granularity="month")) == "2025-09"
    assert wire(DateValue(value=date(2026, 8, 15), granularity="day")) == "2026-08-15"


def test_string_keeps_diacritics_and_trims():
    assert wire(ScalarValue(type="string", value="  Sting dâu 330ml ")) == "Sting dâu 330ml"


def test_table_numeric_cells_are_numbers():
    v = TableValue(columns=["khach_hang", "so_tien_no"],
                   rows=[["Chị Lan", Decimal("3200000")], ["Anh Tú", Decimal("1500000.4")]],
                   numeric_kind="money")
    assert dumps(wire(v)) == '{"columns":["khach_hang","so_tien_no"],"rows":[["Chị Lan",3200000],["Anh Tú",1500000]]}'


def test_unanswerable_and_abstain_wire_shape():
    u = to_submission("q1", Decision(kind="unanswerable", reason_code="x",
                                     unanswerable_reason="missing_field:giá vốn"), None, CFG)
    a = to_submission("q2", Decision(kind="abstain", reason_code="x"), None, CFG)
    assert dumps(u.to_wire()) == '{"id":"q1","type":"unanswerable","reason":"missing_field:giá vốn"}'
    assert dumps(a.to_wire()) == '{"id":"q2","type":"abstain"}'


def test_non_finite_number_is_rejected():
    with pytest.raises(ValueError):
        wire(num("Infinity", "money"))
