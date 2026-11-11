"""Solar/lunar lookup table with explicit alias, leap-month and coverage checks."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from datamate.ingest.common import (
    component_run,
    finish_component,
    identifier,
    implementation_digest,
    inventory_files,
    read_delimited,
    verify_inventory,
    write_json,
    write_jsonl,
)

CALENDAR_ALIASES = {
    "solar_date": [
        "date",
        "solar_date",
        "gregorian_date",
        "ngay_duong",
        "ngay_duong_lich",
        "duong_lich",
    ],
    "lunar_year": ["lunar_year", "am_year", "nam_am", "nam_am_lich"],
    "lunar_month": ["lunar_month", "am_month", "thang_am", "thang_am_lich"],
    "lunar_day": ["lunar_day", "am_day", "ngay_am", "ngay_am_lich"],
    "is_leap_month": [
        "lunar_leap",
        "is_leap",
        "is_leap_month",
        "leap_month",
        "nhuan",
        "thang_nhuan",
    ],
}


def map_calendar_columns(headers: list[str], overrides: dict | None = None) -> dict:
    mapped, overrides = {}, overrides or {}
    for field, aliases in CALENDAR_ALIASES.items():
        candidates = (
            [i for i, name in enumerate(headers) if name == overrides.get(field)]
            if field in overrides
            else [i for i, name in enumerate(headers) if identifier(name) in aliases]
        )
        if len(candidates) != 1:
            raise ValueError(
                f"Calendar column {field} has {len(candidates)} matches; set COLUMN_OVERRIDES"
            )
        mapped[field] = candidates[0]
    if len(set(mapped.values())) != len(mapped):
        raise ValueError("Calendar aliases map different fields to the same column")
    return mapped


def parse_leap_flag(value: str) -> bool:
    token = identifier(value)
    if token in {"true", "c_1", "yes", "co", "nhuan"}:
        return True
    if token in {"false", "c_0", "no", "khong", "thuong"}:
        return False
    raise ValueError(f"Unknown leap flag: {value!r}")


def parse_calendar(path: Path, overrides: dict | None = None) -> tuple[list[dict], dict]:
    source, details = read_delimited(path)
    if not source:
        raise ValueError("Empty calendar.csv")
    mapped = map_calendar_columns(source[0], overrides)
    records, errors, solar_seen, lunar_seen = [], [], set(), set()
    previous = None
    for line_no, row in enumerate(source[1:], 2):
        if not any(str(v).strip() for v in row):
            continue
        try:
            if len(row) != len(source[0]):
                raise ValueError("Calendar row width differs from header")
            values = {field: row[i].strip() for field, i in mapped.items()}
            solar = date.fromisoformat(values["solar_date"])
            year, month, day = (int(values[f"lunar_{part}"]) for part in ("year", "month", "day"))
            leap = parse_leap_flag(values["is_leap_month"])
            if not (1 <= year <= 9999 and 1 <= month <= 12 and 1 <= day <= 30):
                raise ValueError("Lunar fields outside valid domains")
            lunar = (year, month, day, leap)
            if solar in solar_seen or lunar in lunar_seen:
                raise ValueError("Duplicate solar date or lunar tuple")
            if previous is not None and solar != previous + timedelta(days=1):
                raise ValueError("Solar dates must increase one day at a time without gaps")
            solar_seen.add(solar)
            lunar_seen.add(lunar)
            previous = solar
            records.append(
                {
                    "solar_date": solar.isoformat(),
                    "lunar_year": year,
                    "lunar_month": month,
                    "lunar_day": day,
                    "is_leap_month": leap,
                    "source_row": line_no,
                }
            )
        except (ValueError, IndexError) as error:
            errors.append({"source_row": line_no, "reason": str(error)})
    validation = {
        "valid": bool(records) and not errors,
        "calendar_ok": bool(records) and not errors,
        "rows": len(records),
        "errors": errors,
        "column_mapping": mapped,
        "source_headers": source[0],
        "reader": details,
        "solar_start": records[0]["solar_date"] if records else None,
        "solar_end": records[-1]["solar_date"] if records else None,
    }
    return records, validation


class LunarCalendar:
    """A validated lookup; no astronomical guesses outside the supplied calendar."""

    def __init__(self, records: list[dict], calendar_ok: bool = True):
        if not calendar_ok:
            raise ValueError("W_CALENDAR_INVALID: lunar lookup disabled")
        self.solar = {
            date.fromisoformat(r["solar_date"]): (
                r["lunar_year"],
                r["lunar_month"],
                r["lunar_day"],
                r["is_leap_month"],
            )
            for r in records
        }
        self.lunar = {value: key for key, value in self.solar.items()}
        if len(self.solar) != len(records) or len(self.lunar) != len(records):
            raise ValueError("Calendar lookup is not one-to-one")

    def to_lunar(self, solar: date) -> tuple[int, int, int, bool]:
        return self.solar[solar]

    def to_solar(self, year: int, month: int, day: int, is_leap_month: bool = False) -> date:
        return self.lunar[(year, month, day, is_leap_month)]

    def covers(self, start: date, end: date) -> bool:
        if end < start:
            return False
        return all(start + timedelta(days=i) in self.solar for i in range((end - start).days + 1))


def prepare_calendar(
    split_dir: Path,
    output_dir: Path,
    *,
    column_overrides: dict | None = None,
    code_sha256: str | None = None,
) -> dict:
    path = split_dir / "calendar.csv"
    inventory = inventory_files(split_dir, [path])
    folder = component_run(
        split_dir,
        output_dir,
        "calendar",
        inventory,
        {"column_overrides": column_overrides or {}, "aliases": CALENDAR_ALIASES},
        code_sha256 or implementation_digest(globals()),
    )
    try:
        records, validation = parse_calendar(path, column_overrides)
    except (ValueError, OSError, UnicodeError) as error:
        records = []
        validation = {"valid": False, "calendar_ok": False, "errors": [{"reason": str(error)}]}
    write_jsonl(folder / "calendar.jsonl", records)
    write_json(folder / "aliases.json", CALENDAR_ALIASES)
    unchanged = verify_inventory(split_dir, inventory)
    validation["input_unchanged"] = unchanged
    validation["valid"] = validation["valid"] and unchanged["valid"]
    validation["calendar_ok"] = validation["valid"]
    if validation["valid"]:
        lookup = LunarCalendar(records)
        validation["round_trip_valid"] = all(
            lookup.to_solar(*lookup.to_lunar(d)) == d for d in lookup.solar
        )
    finish_component(folder, validation)
    return {"folder": folder, "records": records, "validation": validation}
