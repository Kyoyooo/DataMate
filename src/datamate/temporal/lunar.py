"""Bidirectional lunar lookups over the supplied CSV, with no inferred dates."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

LunarDate = tuple[int, int, int, bool]
_REQUIRED = {"date", "lunar_year", "lunar_month", "lunar_day", "lunar_leap"}
_LEAP = {"false": False, "true": True}


class CalendarValidationError(ValueError):
    def __init__(self, code: str, row: int | None, message: str):
        super().__init__(message)
        self.code = code
        self.row = row


class LunarLookupError(ValueError):
    """The requested mapping is ambiguous or absent from the loaded calendar."""


def _integer(row: dict[str, str], name: str, minimum: int, maximum: int, line: int) -> int:
    raw = row[name]
    if raw.isascii() and raw.isdecimal() and len(raw) <= 4:
        value = int(raw)
        if minimum <= value <= maximum:
            return value
    raise CalendarValidationError("invalid_field", line, f"{name} must be an integer in [{minimum}, {maximum}]")


def _parse_row(row: dict[str, str], line: int) -> tuple[date, LunarDate]:
    try:
        solar = date.fromisoformat(row["date"])
        if solar.isoformat() != row["date"]:
            raise ValueError
    except ValueError as exc:
        raise CalendarValidationError("invalid_date", line, "date must be a valid YYYY-MM-DD") from exc
    if "weekday" in row and _integer(row, "weekday", 1, 7, line) != solar.isoweekday():
        raise CalendarValidationError("invalid_field", line, "weekday does not match date (ISO weekday)")
    if row["lunar_leap"] not in _LEAP:
        raise CalendarValidationError("invalid_field", line, "lunar_leap must be true or false")
    lunar = (_integer(row, "lunar_year", 1, 9999, line), _integer(row, "lunar_month", 1, 12, line),
             _integer(row, "lunar_day", 1, 30, line), _LEAP[row["lunar_leap"]])
    return solar, lunar


class LunarCalendar:
    """A contiguous Gregorian range indexed by full lunar date, including leap month."""

    def __init__(self, solar_to_lunar: dict[date, LunarDate]):
        self._solar_to_lunar = dict(solar_to_lunar)
        self._lunar_to_solar = {lunar: solar for solar, lunar in solar_to_lunar.items()}

    @classmethod
    def from_csv(cls, path: Path) -> LunarCalendar:
        by_solar: dict[date, LunarDate] = {}
        seen_lunar: set[LunarDate] = set()
        previous: date | None = None
        line = 1
        try:
            with path.open(encoding="utf-8-sig", newline="") as handle:
                reader = csv.reader(handle, strict=True)
                header = [col.strip() for col in next(reader, [])]
                missing = _REQUIRED.difference(header)
                if missing:
                    raise CalendarValidationError("missing_columns", line, ", ".join(sorted(missing)))
                if len(header) != len(set(header)) or "" in header:
                    raise CalendarValidationError("invalid_header", line, "blank or repeated column name")
                for cells in reader:
                    line = reader.line_num
                    if len(cells) != len(header):
                        raise CalendarValidationError("invalid_row", line, "column count differs from header")
                    row = dict(zip(header, (cell.strip() for cell in cells), strict=True))
                    solar, lunar = _parse_row(row, line)
                    if solar in by_solar:
                        raise CalendarValidationError("duplicate_date", line, solar.isoformat())
                    if previous is not None and (solar - previous).days != 1:
                        code = "date_gap" if solar > previous else "date_order"
                        raise CalendarValidationError(code, line, f"{previous.isoformat()} → {solar.isoformat()}")
                    if lunar in seen_lunar:
                        raise CalendarValidationError("duplicate_lunar_date", line, str(lunar))
                    if previous is not None:
                        prior = by_solar[previous]
                        same_month = (prior[0], prior[1], prior[3]) == (lunar[0], lunar[1], lunar[3])
                        advances = (lunar[2] == prior[2] + 1 if same_month
                                    else prior[2] in (29, 30) and lunar[2] == 1)
                        if not advances:
                            raise CalendarValidationError("lunar_day_order", line, "lunar days do not advance")
                    by_solar[solar] = lunar
                    seen_lunar.add(lunar)
                    previous = solar
        except FileNotFoundError:
            raise
        except (OSError, UnicodeError, csv.Error) as exc:
            raise CalendarValidationError("unreadable_csv", line, str(exc)) from exc
        if not by_solar:
            raise CalendarValidationError("empty_calendar", None, "calendar has no date rows")
        return cls(by_solar)

    def covers(self, d: date) -> bool:
        return d in self._solar_to_lunar

    def to_lunar(self, d: date) -> LunarDate:
        try:
            return self._solar_to_lunar[d]
        except KeyError:
            raise LunarLookupError(f"Gregorian date {d} is outside the loaded calendar") from None

    def to_solar(self, lunar_year: int, month: int, day: int, is_leap: bool | None = False) -> date:
        """Default to the regular month. None requires a unique match across both months."""
        if is_leap is not None and type(is_leap) is not bool:
            raise LunarLookupError("is_leap must be a boolean or None")
        flags = (False, True) if is_leap is None else (is_leap,)
        matches = [self._lunar_to_solar[key] for leap in flags
                   if (key := (lunar_year, month, day, leap)) in self._lunar_to_solar]
        if len(matches) == 1:
            return matches[0]
        if matches:
            raise LunarLookupError("ambiguous lunar date: specify whether the month is a leap month")
        raise LunarLookupError("lunar date is outside the loaded calendar")
