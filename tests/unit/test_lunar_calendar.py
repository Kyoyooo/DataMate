"""Calendar tests use supplied fixture data and explicitly synthetic mappings."""

from datetime import date, timedelta

import pytest

from datamate.contracts import TimeRef
from datamate.rules import load_split
from datamate.temporal import (
    CalendarValidationError,
    LunarCalendar,
    LunarLookupError,
    resolve_windows,
)

from conftest import SPLIT

HEADER = "date,lunar_year,lunar_month,lunar_day,lunar_leap\n"


def test_calendar_fixture_round_trip():
    calendar = LunarCalendar.from_csv(SPLIT / "calendar.csv")
    expected = {
        date(2026, 2, 16): (2025, 12, 29, False),
        date(2026, 2, 17): (2026, 1, 1, False),
        date(2026, 2, 18): (2026, 1, 2, False),
    }
    for solar, lunar in expected.items():
        assert calendar.covers(solar)
        assert calendar.to_lunar(solar) == lunar
        assert calendar.to_solar(*lunar) == solar
    assert not calendar.covers(date(2026, 2, 15))
    with pytest.raises(LunarLookupError, match="outside"):
        calendar.to_lunar(date(2026, 2, 19))
    with pytest.raises(LunarLookupError, match="outside"):
        calendar.to_solar(2026, 1, 1, True)


def test_synthetic_leap_month_is_distinct_and_ambiguous_without_flag(tmp_path):
    start = date(2025, 1, 1)
    # A synthetic 29-day regular month followed by two days of a leap month.
    rows = [f"{start + timedelta(days=i)},2025,5,{i + 1},false\n" for i in range(29)]
    rows += [f"{start + timedelta(days=29 + i)},2025,5,{i + 1},true\n" for i in range(2)]
    path = tmp_path / "calendar.csv"
    path.write_text(HEADER + "".join(rows), encoding="utf-8-sig")
    calendar = LunarCalendar.from_csv(path)
    assert calendar.to_solar(2025, 5, 1) == start
    assert calendar.to_solar(2025, 5, 1, True) == date(2025, 1, 30)
    assert calendar.to_solar(2025, 5, 3, None) == date(2025, 1, 3)
    with pytest.raises(LunarLookupError, match="ambiguous"):
        calendar.to_solar(2025, 5, 1, None)
    for offset in range(len(rows)):
        solar = start + timedelta(days=offset)
        assert calendar.to_solar(*calendar.to_lunar(solar)) == solar


@pytest.mark.parametrize("content, code, row", [
    ("date,lunar_year,lunar_month,lunar_day\n", "missing_columns", 1),
    (HEADER, "empty_calendar", None),
    (HEADER + "2025-02-29,2025,1,1,false\n", "invalid_date", 2),
    (HEADER + "20250101,2025,1,1,false\n", "invalid_date", 2),
    (HEADER + "2025-01-01,2025,13,1,false\n", "invalid_field", 2),
    (HEADER + "2025-01-01,2025,1,31,false\n", "invalid_field", 2),
    (HEADER + "2025-01-01,2025,1,1,maybe\n", "invalid_field", 2),
    (HEADER + "2025-01-01,2025,1,1\n", "invalid_row", 2),
    (HEADER + "2025-01-01,2025,1,1,false\n2025-01-01,2025,1,2,false\n", "duplicate_date", 3),
    (HEADER + "2025-01-01,2025,1,1,false\n2025-01-03,2025,1,3,false\n", "date_gap", 3),
    (HEADER + "2025-01-02,2025,1,1,false\n2025-01-01,2025,1,2,false\n", "date_order", 3),
    (HEADER + "2025-01-01,2025,1,1,false\n2025-01-02,2025,1,1,false\n", "duplicate_lunar_date", 3),
    (HEADER + "2025-01-01,2025,1,28,false\n2025-01-02,2025,2,1,false\n", "lunar_day_order", 3),
])
def test_malformed_calendars_report_structured_diagnostics(tmp_path, content, code, row):
    (tmp_path / "calendar.csv").write_text(content, encoding="utf-8")
    split = load_split(tmp_path)
    assert not split.calendar_ok
    assert "W_CALENDAR_INVALID" in split.warnings
    assert split.calendar_diagnostic is not None
    assert (split.calendar_diagnostic.code, split.calendar_diagnostic.row) == (code, row)


def test_missing_or_unreadable_calendar_preserves_gregorian_queries(tmp_path):
    assert "W_CALENDAR_MISSING" in load_split(tmp_path).warnings
    path = tmp_path / "calendar.csv"
    path.write_bytes(b"\xff")
    with pytest.raises(CalendarValidationError, match="codec"):
        LunarCalendar.from_csv(path)
    split = load_split(tmp_path)
    assert not split.calendar_ok and split.calendar_diagnostic.code == "unreadable_csv"
    refs = [TimeRef(span="hôm nay", expr={"kind": "relative_period", "unit": "day", "offset": 0})]
    windows, error = resolve_windows(refs, date(2026, 3, 4), split.temporal, None)
    assert error is None and windows[0].start == windows[0].end == date(2026, 3, 4)
