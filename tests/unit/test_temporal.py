"""Temporal resolver (M2). Generic parameters; dates checked against a calendar by hand."""

from __future__ import annotations

from datetime import date

import pytest

from datamate.contracts import DateRange, TemporalParams, TimeRef
from datamate.temporal import resolve_windows

GENERIC = TemporalParams()
DATA = DateRange(start=date(2025, 1, 1), end=date(2026, 12, 31))


def ref(**expr) -> TimeRef:
    return TimeRef(span="", expr=expr)


def win(expr: dict, as_of: str, params: TemporalParams = GENERIC, data: DateRange | None = DATA):
    windows, err = resolve_windows([ref(**expr)], date.fromisoformat(as_of), params, data)
    assert err is None
    w = windows[0]
    return w.start.isoformat(), w.end.isoformat()


@pytest.mark.parametrize("expr, as_of, expected", [
    # hôm nay / hôm qua, across a month boundary
    ({"kind": "relative_period", "unit": "day", "offset": 0}, "2026-03-04", ("2026-03-04", "2026-03-04")),
    ({"kind": "relative_period", "unit": "day", "offset": -1}, "2026-03-01", ("2026-02-28", "2026-02-28")),
    # tuần này (Mon → today), tuần rồi (full Mon–Sun), across a year boundary
    ({"kind": "relative_period", "unit": "week", "offset": 0, "to_date": True}, "2026-03-04", ("2026-03-02", "2026-03-04")),
    ({"kind": "relative_period", "unit": "week", "offset": -1, "to_date": False}, "2026-01-02", ("2025-12-22", "2025-12-28")),
    # Sunday as_of belongs to the week that started the previous Monday
    ({"kind": "relative_period", "unit": "week", "offset": 0, "to_date": True}, "2026-03-08", ("2026-03-02", "2026-03-08")),
    # tháng này / tháng trước (leap February) / quý trước / năm ngoái
    ({"kind": "relative_period", "unit": "month", "offset": 0, "to_date": True}, "2026-03-04", ("2026-03-01", "2026-03-04")),
    ({"kind": "relative_period", "unit": "month", "offset": -1, "to_date": False}, "2024-03-15", ("2024-02-01", "2024-02-29")),
    ({"kind": "relative_period", "unit": "quarter", "offset": -1, "to_date": False}, "2026-01-10", ("2025-10-01", "2025-12-31")),
    ({"kind": "relative_period", "unit": "year", "offset": -1, "to_date": False}, "2026-03-04", ("2025-01-01", "2025-12-31")),
    # tháng M/Y, quý Q/Y, năm Y
    ({"kind": "calendar_period", "unit": "month", "year": 2025, "index": 2}, "2026-03-04", ("2025-02-01", "2025-02-28")),
    ({"kind": "calendar_period", "unit": "quarter", "year": 2025, "index": 4}, "2026-03-04", ("2025-10-01", "2025-12-31")),
    ({"kind": "calendar_period", "unit": "year", "year": 2025}, "2026-03-04", ("2025-01-01", "2025-12-31")),
    # year omitted: this year if the period has started, else last year
    ({"kind": "calendar_period", "unit": "month", "index": 2}, "2026-03-04", ("2026-02-01", "2026-02-28")),
    ({"kind": "calendar_period", "unit": "month", "index": 5}, "2026-03-04", ("2025-05-01", "2025-05-31")),
    ({"kind": "calendar_period", "unit": "quarter", "index": 2}, "2026-03-04", ("2025-04-01", "2025-06-30")),
    # N ngày gần nhất includes today
    ({"kind": "rolling", "unit": "day", "count": 7}, "2026-03-04", ("2026-02-26", "2026-03-04")),
    ({"kind": "rolling", "unit": "day", "count": 1}, "2026-03-04", ("2026-03-04", "2026-03-04")),
    # explicit dates
    ({"kind": "date", "date": "2025-07-26"}, "2026-03-04", ("2025-07-26", "2025-07-26")),
    ({"kind": "date_range", "start": "2025-03-01", "end": "2025-03-15"}, "2026-03-04", ("2025-03-01", "2025-03-15")),
])
def test_resolution_table(expr, as_of, expected):
    assert win(expr, as_of) == expected


@pytest.mark.parametrize("unit, count, as_of, include_today, expected", [
    ("day", 1, "2026-01-01", False, ("2025-12-31", "2025-12-31")),
    ("week", 2, "2026-01-02", True, ("2025-12-20", "2026-01-02")),
    ("week", 1, "2026-03-04", False, ("2026-02-25", "2026-03-03")),
    ("month", 1, "2026-01-31", True, ("2026-01-01", "2026-01-31")),
    ("month", 2, "2026-01-31", True, ("2025-12-01", "2026-01-31")),
    ("month", 1, "2024-03-31", True, ("2024-03-01", "2024-03-31")),
    ("month", 1, "2025-03-31", True, ("2025-03-01", "2025-03-31")),
    ("month", 1, "2024-02-29", True, ("2024-01-30", "2024-02-29")),
    ("month", 1, "2025-02-28", True, ("2025-01-29", "2025-02-28")),
    ("month", 1, "2026-03-01", False, ("2026-01-29", "2026-02-28")),
])
def test_spec_7_5_rolling_windows(unit, count, as_of, include_today, expected):
    params = TemporalParams(rolling_includes_as_of=include_today)
    assert win({"kind": "rolling", "unit": unit, "count": count}, as_of, params) == expected


def test_spec_7_5_rolling_before_minimum_date_is_unsupported():
    refs = [ref(kind="rolling", unit="month", count=1)]
    assert resolve_windows(refs, date.min, GENERIC, None) == ([], "E_TIME_UNSUPPORTED")


def test_current_month_is_clipped_to_as_of():
    windows, _ = resolve_windows([ref(kind="calendar_period", unit="month", year=2026, index=3)],
                                 date(2026, 3, 4), GENERIC, DATA)
    assert (windows[0].start, windows[0].end) == (date(2026, 3, 1), date(2026, 3, 4))
    assert "F_CLIPPED_TO_AS_OF" in windows[0].flags


def test_parameters_change_resolution():
    sunday = TemporalParams(week_start="sun", rolling_includes_as_of=False,
                            to_date_end="day_before_as_of")
    assert win({"kind": "relative_period", "unit": "week", "offset": -1, "to_date": False},
               "2026-03-04", sunday) == ("2026-02-22", "2026-02-28")
    assert win({"kind": "rolling", "unit": "day", "count": 7}, "2026-03-04", sunday) == \
        ("2026-02-25", "2026-03-03")
    assert win({"kind": "relative_period", "unit": "month", "offset": 0, "to_date": True},
               "2026-03-04", sunday) == ("2026-03-01", "2026-03-03")


def test_coverage_zero_partial_full():
    data = DateRange(start=date(2026, 1, 20), end=date(2026, 3, 6))
    refs = [ref(kind="calendar_period", unit="month", year=2025, index=12),
            ref(kind="calendar_period", unit="month", year=2026, index=1),
            ref(kind="calendar_period", unit="month", year=2026, index=2)]
    windows, err = resolve_windows(refs, date(2026, 3, 4), GENERIC, data)
    assert err is None
    assert [w.coverage_ratio for w in windows] == [0.0, 12 / 31, 1.0]


def test_coverage_ignores_records_after_as_of():
    data = DateRange(start=date(2026, 1, 1), end=date(2026, 12, 31))
    windows, _ = resolve_windows([ref(kind="calendar_period", unit="month", year=2026, index=6)],
                                 date(2026, 3, 4), GENERIC, data)
    assert windows[0].coverage_ratio == 0.0 and "F_AFTER_AS_OF" in windows[0].flags


def test_all_time_uses_data_range_and_unsupported_is_an_error():
    windows, err = resolve_windows([ref(kind="all_time")], date(2026, 3, 4), GENERIC, DATA)
    assert err is None and windows[0].start == DATA.start and windows[0].end == date(2026, 3, 4)
    _, err = resolve_windows([ref(kind="unsupported", reason="Tết")], date(2026, 3, 4), GENERIC, DATA)
    assert err == "E_TIME_UNSUPPORTED"
