"""Temporal resolver (SPEC §7.5, P1 subset). Owner: M2.

Pure functions: structured ``TimeExpr`` + ``as_of_date`` + split parameters →
inclusive date windows. No I/O, no model calls.

Supported now (all documented in tests/unit/test_temporal.py):
  date and date_range (full or yearless dates), calendar_period (month/quarter/year, optional
  year), relative_period (day/week/month/quarter/year, offset ≤ 0, to_date),
  rolling (days/weeks/months), all_time, unsupported → E_TIME_UNSUPPORTED.

Conventions:
- Windows never extend past ``as_of_date``: records dated after "today" are
  treated as not having happened yet. A window that lies entirely after
  ``as_of_date`` keeps its dates, gets coverage 0 and flag F_AFTER_AS_OF.
- ``coverage_ratio`` = days of the window inside the data range (also capped at
  ``as_of_date``) / window days. 0 means "no data for this period", which the
  decision step treats differently from a computed zero.

Deferred (TASKS M2-04, M2-09): "same days of previous month" comparisons, same period last year, lunar
holidays (Tết), sub-day shifts (ca sáng / ca chiều).
"""

from __future__ import annotations

from calendar import isleap, monthrange
from datetime import date, timedelta

from datamate.contracts import (
    AllTimeExpr,
    CalendarPeriodExpr,
    DateExpr,
    DateRange,
    DateRangeExpr,
    MonthDay,
    RelativePeriodExpr,
    RollingExpr,
    TemporalParams,
    TimeRef,
    TimeWindow,
    UnsupportedExpr,
    YearlessDateExpr,
    YearlessDateRangeExpr,
    codes,
)


class TimeResolutionError(ValueError):
    """Raised internally; surfaced to callers as E_TIME_UNSUPPORTED."""


def week_start(d: date, start: str) -> date:
    if start == "mon":
        return d - timedelta(days=d.weekday())
    return d - timedelta(days=(d.weekday() + 1) % 7)


def add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


def _shift_months(d: date, delta: int) -> date:
    year, month = add_months(d.year, d.month, delta)
    return date(year, month, min(d.day, monthrange(year, month)[1]))


def month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def quarter_bounds(year: int, quarter: int) -> tuple[date, date]:
    first = 3 * (quarter - 1) + 1
    return date(year, first, 1), month_bounds(year, first + 2)[1]


def _period(unit: str, as_of: date, offset: int, params: TemporalParams) -> tuple[date, date]:
    """Full calendar period of ``unit`` containing ``as_of``, shifted by ``offset`` periods."""
    if unit == "day":
        d = as_of + timedelta(days=offset)
        return d, d
    if unit == "week":
        s = week_start(as_of, params.week_start) + timedelta(days=7 * offset)
        return s, s + timedelta(days=6)
    if unit == "month":
        y, m = add_months(as_of.year, as_of.month, offset)
        return month_bounds(y, m)
    if unit == "quarter":
        q0 = (as_of.month - 1) // 3
        y, m = add_months(as_of.year, 3 * q0 + 1, 3 * offset)
        return quarter_bounds(y, (m - 1) // 3 + 1)
    if unit == "year":
        y = as_of.year + offset
        return date(y, 1, 1), date(y, 12, 31)
    raise TimeResolutionError(f"unknown unit {unit!r}")


def _calendar_period(e: CalendarPeriodExpr, as_of: date) -> tuple[date, date]:
    if e.unit == "year":
        y = e.year if e.year is not None else as_of.year
        return date(y, 1, 1), date(y, 12, 31)
    if e.index is None:
        raise TimeResolutionError(f"calendar_period {e.unit} needs an index")
    if e.unit == "month":
        if not 1 <= e.index <= 12:
            raise TimeResolutionError(f"month index out of range: {e.index}")
        bounds = lambda y: month_bounds(y, e.index)  # noqa: E731
    else:
        if not 1 <= e.index <= 4:
            raise TimeResolutionError(f"quarter index out of range: {e.index}")
        bounds = lambda y: quarter_bounds(y, e.index)  # noqa: E731
    if e.year is not None:
        return bounds(e.year)
    # Year omitted: the most recent such period whose start is not after as_of.
    start, end = bounds(as_of.year)
    return (start, end) if start <= as_of else bounds(as_of.year - 1)


def _resolve_date(value: date | MonthDay, as_of: date) -> date:
    if isinstance(value, date):
        return value
    year = as_of.year - int((value.month, value.day) > (as_of.month, as_of.day))
    if (value.month, value.day) == (2, 29):
        while year > 0 and not isleap(year):
            year -= 1
    return date(year, value.month, value.day)


def _raw_window(ref: TimeRef, as_of: date, params: TemporalParams,
                data_range: DateRange | None) -> tuple[date, date, str] | None:
    e = ref.expr
    if isinstance(e, (DateExpr, YearlessDateExpr)):
        day = _resolve_date(e.date, as_of)
        return day, day, "day"
    if isinstance(e, (DateRangeExpr, YearlessDateRangeExpr)):
        start = _resolve_date(e.start, as_of)
        end = e.end
        if isinstance(end, MonthDay):
            crosses_year = (end.month, end.day) < (start.month, start.day)
            end = date(start.year + int(crosses_year), end.month, end.day)
        if start > end:
            raise TimeResolutionError("date_range start after end")
        return start, end, "range"
    if isinstance(e, CalendarPeriodExpr):
        s, t = _calendar_period(e, as_of)
        return s, t, e.unit
    if isinstance(e, RelativePeriodExpr):
        s, t = _period(e.unit, as_of, e.offset, params)
        if e.offset == 0 and e.to_date and e.unit != "day":
            t = as_of if params.to_date_end == "as_of" else as_of - timedelta(days=1)
            if t < s:
                raise TimeResolutionError("to-date window is empty")
        return s, t, e.unit
    if isinstance(e, RollingExpr):
        end = as_of if params.rolling_includes_as_of else as_of - timedelta(days=1)
        if e.unit == "month":
            start = _shift_months(end, -e.count) + timedelta(days=1)
        else:
            days = e.count * (7 if e.unit == "week" else 1)
            start = end - timedelta(days=days - 1)
        return start, end, "range"
    if isinstance(e, AllTimeExpr):
        if data_range is None:
            return None
        return data_range.start, data_range.end, "range"
    if isinstance(e, UnsupportedExpr):
        raise TimeResolutionError(e.reason or "unsupported time expression")
    raise TimeResolutionError(f"unhandled expression {type(e).__name__}")  # pragma: no cover


def coverage(start: date, end: date, data_range: DateRange | None, as_of: date) -> float | None:
    if data_range is None:
        return None
    lo = max(start, data_range.start)
    hi = min(end, data_range.end, as_of)
    days = (end - start).days + 1
    return max(0, (hi - lo).days + 1) / days


def resolve_windows(time_refs: list[TimeRef], as_of: date, params: TemporalParams,
                    data_range: DateRange | None) -> tuple[list[TimeWindow], str | None]:
    """Return (windows, error_code). ``error_code`` is E_TIME_UNSUPPORTED or None."""
    windows: list[TimeWindow] = []
    for i, ref in enumerate(time_refs):
        try:
            raw = _raw_window(ref, as_of, params, data_range)
        except (ValueError, OverflowError):  # Invalid or unrepresentable calendar dates.
            return [], codes.E_TIME_UNSUPPORTED
        if raw is None:
            continue
        start, end, gran = raw
        flags: list[str] = []
        if start > as_of:
            flags.append("F_AFTER_AS_OF")
            cov: float | None = 0.0
        else:
            if end > as_of:
                end = as_of
                flags.append("F_CLIPPED_TO_AS_OF")
            cov = coverage(start, end, data_range, as_of)
        if params.uses_generic():
            flags.append("F_TEMPORAL_GENERIC")
        windows.append(TimeWindow(ref_index=i, role=ref.role, start=start, end=end,
                                  granularity=gran, coverage_ratio=cov, flags=flags))
    return windows, None
