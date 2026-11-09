"""Technical ingestion and deterministic cataloging; no business-ID-specific rules."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
import shutil
import sqlite3
import tempfile
import zipfile
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from xml.etree import ElementTree

from .common import (
    component_run,
    finish_component,
    fold_key,
    identifier,
    implementation_digest,
    inventory_files,
    missing_value,
    nfc_text,
    read_delimited,
    safe_business_dir,
    source_text,
    sql_quote,
    unique_names,
    verify_inventory,
    write_json,
)
from .qa import load_questions


@dataclass(frozen=True)
class DataConfig:
    numeric_accept_rate: float = 0.98
    date_accept_rate: float = 0.98
    max_header_scan_rows: int = 20
    low_cardinality_max: int = 50
    top_values_max: int = 30
    max_file_mb: int = 2048
    schema_card_budget_tokens: int = 8000
    max_columns_for_pair_keys: int = 50

    def __post_init__(self):
        if not 0 < self.numeric_accept_rate <= 1 or not 0 < self.date_accept_rate <= 1:
            raise ValueError("Acceptance rates must be in (0, 1]")
        if (
            min(
                self.max_header_scan_rows,
                self.max_file_mb,
                self.top_values_max,
                self.low_cardinality_max,
                self.schema_card_budget_tokens,
            )
            < 1
        ):
            raise ValueError("Data limits must be positive")


def parse_numeric(value, convention: str = "VN") -> tuple[Decimal | None, str]:
    if missing_value(value):
        return None, "missing"
    if isinstance(value, bool):
        return None, "invalid_boolean_as_number"
    try:
        if isinstance(value, (int, float, Decimal)):
            result = Decimal(str(value))
        else:
            text = re.sub(r"\s+", "", fold_key(value))
            if text.startswith("(") and text.endswith(")"):
                text = "-" + text[1:-1]
            text = re.sub(r"(?:vnd|dong|d|₫|%)$", "", text)
            scales = {
                "k": 1000,
                "nghin": 1000,
                "ngan": 1000,
                "tr": 10**6,
                "trieu": 10**6,
                "ty": 10**9,
                "ti": 10**9,
            }
            compound = re.fullmatch(r"([+-]?\d+)(trieu|nghin|ngan|tr|ty|ti|k)(\d+)", text)
            if compound:
                text, multiplier = compound[1] + "." + compound[3], scales[compound[2]]
                with localcontext() as context:
                    context.prec = max(80, len(text) + 20)
                    result = Decimal(text) * multiplier
            else:
                suffix = re.fullmatch(r"(.+?)(trieu|nghin|ngan|tr|ty|ti|k)", text)
                multiplier = scales[suffix[2]] if suffix else 1
                text = suffix[1] if suffix else text
                group, point = (".", ",") if convention == "VN" else (",", ".")
                if convention == "PLAIN":
                    pattern = r"[+-]?\d+(?:\.\d+)?"
                else:
                    pattern = (
                        r"[+-]?(?:\d+|\d{1,3}(?:"
                        + re.escape(group)
                        + r"\d{3})+)(?:"
                        + re.escape(point)
                        + r"\d+)?"
                    )
                if not re.fullmatch(pattern, text):
                    return None, "unparsed_number"
                text = (
                    text if convention == "PLAIN" else text.replace(group, "").replace(point, ".")
                )
                with localcontext() as context:
                    context.prec = max(80, len(text) + 20)
                    result = Decimal(text) * multiplier
        return (result, "parsed") if result.is_finite() else (None, "nonfinite")
    except (InvalidOperation, ValueError, OverflowError):
        return None, "unparsed_number"


def numeric_convention(values: list) -> tuple[str | None, list[str]]:
    """Select by parse rate, then unique evidence; retain conflicting ties as text."""
    if not any(isinstance(v, str) and not missing_value(v) for v in values):
        return "VN", []
    unique = list(
        {(type(v).__name__, source_text(v)): v for v in values if not missing_value(v)}.values()
    )
    if not unique:
        return "VN", []
    counts = Counter((type(v).__name__, source_text(v)) for v in values if not missing_value(v))
    candidates = {
        policy: [parse_numeric(v, policy)[0] for v in unique] for policy in ("VN", "EN", "PLAIN")
    }
    scores = {}
    for policy, parsed in candidates.items():
        success = sum(
            counts[(type(v).__name__, source_text(v))]
            for v, p in zip(unique, parsed, strict=True)
            if p is not None
        )
        evidence = sum(
            p is not None and sum(candidates[other][i] is not None for other in candidates) == 1
            for i, p in enumerate(parsed)
        )
        scores[policy] = (success, evidence)
    best = max(scores.values())
    tied = [policy for policy in candidates if scores[policy] == best]
    for index in range(len(unique)):
        outcomes = {
            candidates[policy][index] for policy in tied if candidates[policy][index] is not None
        }
        if len(outcomes) > 1:
            return None, ["W_NUMERIC_AMBIGUOUS"]
    return tied[0], []


def date_convention(values: list) -> tuple[str | None, list[str]]:
    evidence = set()
    for value in values:
        if isinstance(value, str):
            match = re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-]\d{2,4}(?:\s|$)", value.strip())
            if match:
                if int(match[1]) > 12:
                    evidence.add("DMY")
                if int(match[2]) > 12:
                    evidence.add("MDY")
    if len(evidence) > 1:
        return None, ["W_DATE_AMBIGUOUS"]
    return (next(iter(evidence)), []) if evidence else ("DMY", ["W_DATE_ASSUMED_DMY"])


def parse_date_value(
    value,
    order: str = "DMY",
    *,
    serial_allowed: bool = False,
    excel_epoch: str = "1899-12-30T00:00:00",
    source_year: int | None = None,
) -> tuple[date | datetime | None, str]:
    if missing_value(value):
        return None, "missing"
    if isinstance(value, bool):
        return None, "unparsed_date"
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return None, "timezone_requires_policy"
        return (value.date() if value.time() == time() else value), "parsed"
    if isinstance(value, date):
        return value, "parsed"
    text = str(value).strip()
    vietnamese_date = re.fullmatch(r"(\d{1,2})\s+(?:thg|tháng)\s+(\d{1,2})\s+(\d{4})", text, re.I)
    if vietnamese_date:
        text = f"{vietnamese_date[1]}/{vietnamese_date[2]}/{vietnamese_date[3]}"
    if re.fullmatch(r"\d{1,2}[/.-]\d{1,2}", text):
        if source_year is None:
            return None, "missing_year_context"
        first, second = map(int, re.split(r"[/.-]", text))
        try:
            return date(
                source_year,
                first if order == "MDY" else second,
                second if order == "MDY" else first,
            ), "parsed"
        except ValueError:
            return None, "unparsed_date"
    month_time = re.fullmatch(
        r"(\d{4}-\d{2}|\d{1,2}/\d{4})[ T](\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)", text
    )
    if month_time:
        month, status = parse_date_value(month_time[1], order)
        try:
            return datetime.combine(month, time.fromisoformat(month_time[2])), status
        except (ValueError, TypeError):
            return None, "unparsed_date"
    if serial_allowed and re.fullmatch(r"\d{5}(?:\.\d+)?", text) and 20000 <= float(text) <= 80000:
        from openpyxl.utils.datetime import from_excel

        parsed = from_excel(float(text), epoch=datetime.fromisoformat(excel_epoch))
        return (parsed.date() if parsed.time() == time() else parsed), "parsed"
    if re.fullmatch(r"\d{4}-\d{2}", text):
        try:
            return date.fromisoformat(text + "-01"), "month"
        except ValueError:
            return None, "unparsed_date"
    if re.fullmatch(r"\d{1,2}/\d{4}", text):
        try:
            month, year = map(int, text.split("/"))
            return date(year, month, 1), "month"
        except ValueError:
            return None, "unparsed_date"
    try:
        parsed = datetime.fromisoformat(text)
        return parse_date_value(parsed)
    except ValueError:
        pass
    base = ["%Y/%m/%d", "%d-%m-%Y", "%d.%m.%Y"]
    base += ["%m/%d/%Y", "%m/%d/%y"] if order == "MDY" else ["%d/%m/%Y", "%d/%m/%y"]
    for fmt in base:
        for clock in ("", " %H:%M:%S", " %H:%M"):
            try:
                return parse_date_value(datetime.strptime(text, fmt + clock))
            except ValueError:
                continue
    return None, "unparsed_date"


def column_hint(header: str) -> str | None:
    name = identifier(re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", header))
    tokens = set(name.split("_"))
    if name.startswith(("so_ngay", "so_thang", "so_tuan", "han_no", "ky_han", "thoi_han")):
        return None  # Durations remain numeric unless the actual values establish dates.
    if tokens & {"ma", "id", "code", "phone", "sdt", "sku", "barcode", "imei", "cccd"}:
        return "code"
    if name in {"so_dien_thoai", "so_dt", "so_phieu", "so_don", "so_hoa_don", "so_hd", "bill"}:
        return "code"
    if name in {"dvt", "don_vi", "don_vi_tinh", "unit"}:
        return "name"
    if tokens & {"ten", "name"} or any(
        p in name
        for p in ("dia_chi", "ghi_chu", "dien_giai", "trang_thai", "tien_do", "tinh_trang")
    ):
        return "status" if "trang_thai" in name else "name"
    if tokens & {"date", "ngay", "timestamp", "datetime", "month", "thang"} or "thoi_gian" in name:
        return "date"
    if tokens & {"sl", "qty", "quantity"} or "so_luong" in name:
        return "quantity"
    if tokens & {"tien", "gia", "price", "cost", "amount", "phi"} or name in {
        "tt",
        "dg",
        "doanh_thu",
        "cong_no",
    }:
        return "money"
    return None


def parse_quantity_value(value, convention: str) -> tuple[Decimal | None, str | None, str]:
    if not isinstance(value, str) or missing_value(value):
        parsed, status = parse_numeric(value, convention)
        return parsed, None, status
    match = re.fullmatch(r"\s*([+-]?\d[\d.,]*)\s*([^\d\W].*)", value, re.UNICODE)
    if not match:
        parsed, status = parse_numeric(value, convention)
        return parsed, None, status
    parsed, status = parse_numeric(match[1], convention)
    return parsed, nfc_text(match[2].strip()), status


def cached_parse(values: list, parser) -> list:
    cache, result = {}, []
    for value in values:
        key = (type(value).__name__, source_text(value))
        if key not in cache:
            cache[key] = parser(value)
        result.append(cache[key])
    return result


def infer_data_column(
    header: str,
    values: list,
    config: DataConfig,
    epoch: str | None = None,
    source_year: int | None = None,
) -> dict:
    hint, warnings = column_hint(header), []
    present = [v for v in values if not missing_value(v)]
    result = {
        "sql_type": "VARCHAR",
        "semantic_hint": hint,
        "warnings": warnings,
        "format_note": None,
        "units": [None] * len(values),
    }
    if not present or hint in {"code", "name", "status"}:
        result.update(
            values=[None if missing_value(v) else source_text(v) for v in values],
            statuses=["missing" if missing_value(v) else "retained_string" for v in values],
        )
        return result
    date_like = hint == "date" or all(isinstance(v, (date, datetime)) for v in present)
    date_like |= all(
        isinstance(v, str)
        and bool(
            re.match(
                r"^(?:\d{4}[-/]\d{2}|\d{1,2}/\d{4}$|\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})", v.strip()
            )
        )
        for v in present
    )
    if date_like:
        order, date_warnings = date_convention(values)
        warnings.extend(date_warnings)
        pairs = cached_parse(
            values,
            lambda v: parse_date_value(
                v,
                order or "DMY",
                serial_allowed=hint == "date",
                excel_epoch=epoch or "1899-12-30T00:00:00",
                source_year=source_year,
            ),
        )
        success = sum(p is not None for p, _ in pairs) / len(present)
        if order and success >= config.date_accept_rate:
            has_time = any(isinstance(v, datetime) for v, _ in pairs)
            result.update(
                sql_type="TIMESTAMP" if has_time else "DATE",
                values=[v for v, _ in pairs],
                statuses=["parsed" if status == "month" else status for _, status in pairs],
                format_note="month"
                if all(status in {"month", "missing"} for _, status in pairs)
                else None,
            )
            return result
        warnings.append("W_DATE_RETAINED_TEXT")
    elif all(isinstance(v, bool) for v in present):
        result.update(
            sql_type="BOOLEAN",
            values=[None if missing_value(v) else v for v in values],
            statuses=["missing" if missing_value(v) else "parsed" for v in values],
        )
        return result
    else:
        numeric_inputs = values
        if hint == "quantity":
            numeric_inputs = []
            for value in values:
                match = (
                    re.fullmatch(r"\s*([+-]?\d[\d.,]*)\s*([^\d\W].*)", value, re.UNICODE)
                    if isinstance(value, str)
                    else None
                )
                numeric_inputs.append(match[1] if match else value)
        policy, number_warnings = numeric_convention(numeric_inputs)
        warnings.extend(number_warnings)
        triples = cached_parse(
            values,
            lambda v: (
                parse_quantity_value(v, policy or "VN")
                if hint == "quantity"
                else parse_numeric(v, policy or "VN")
            ),
        )
        pairs = [(v[0], v[-1]) for v in triples]
        parsed = [v for v, _ in pairs]
        if (
            policy
            and sum(v is not None for v in parsed) / len(present) >= config.numeric_accept_rate
        ):
            nonnull = [v for v in parsed if v is not None]
            integral = all(v == v.to_integral_value() and -(2**63) <= v < 2**63 for v in nonnull)
            fixed = all(
                v.as_tuple().exponent >= -6 and (v == 0 or v.adjusted() < 32) for v in nonnull
            )
            dtype = "BIGINT" if integral else "DECIMAL(38,6)" if fixed else "DOUBLE"
            if dtype == "DOUBLE":
                warnings.append("W_FLOATING_POINT_COLUMN")
            result.update(
                sql_type=dtype,
                values=parsed,
                statuses=[s for _, s in pairs],
                number_convention=policy,
                units=[v[1] for v in triples] if hint == "quantity" else [None] * len(values),
            )
            if any(isinstance(v, str) and v.strip().endswith("%") for v in present):
                result["semantic_hint"] = "percent"
            return result
        if hint in {"money", "quantity"} or any(v is not None for v in parsed):
            warnings.append("W_NUMERIC_RETAINED_TEXT")
    result.update(
        values=[None if missing_value(v) else source_text(v) for v in values],
        statuses=["missing" if missing_value(v) else "retained_string" for v in values],
    )
    return result


def header_score(rows: list[list], index: int) -> float:
    row = rows[index]
    present = [v for v in row if v is not None and str(v).strip()]
    if not present:
        return -1.0
    width = max(len(r) for r in rows[index : index + 21])
    text_ratio = sum(isinstance(v, str) for v in present) / max(width, 1)
    uniqueness = len({source_text(v) for v in present}) / len(present)
    consistent = []
    for column in range(len(row)):
        kinds = [
            type(r[column]).__name__
            for r in rows[index + 1 : index + 21]
            if column < len(r) and not missing_value(r[column]) and not recognizable_header(r)
        ]
        if kinds:
            consistent.append(max(Counter(kinds).values()) / len(kinds))
    return (
        0.5 * text_ratio
        + 0.3 * uniqueness
        + 0.2 * (sum(consistent) / len(consistent) if consistent else 0)
    )


def recognizable_header(row: list) -> bool:
    labels = {
        "date",
        "ngay",
        "ngay_ban",
        "ngay_thang",
        "ngay_dat_hang",
        "id",
        "ma",
        "sku",
        "code",
        "product",
        "customer",
        "ten",
        "name",
        "amount",
        "tien",
        "thanh_tien",
        "tong_tien",
        "gia",
        "sl",
        "qty",
        "quantity",
        "so_luong",
        "status",
        "trang_thai",
        "ghi_chu",
        "note",
        "don_vi",
        "dvt",
        "ma_don_hang",
        "ten_san_pham",
        "ten_khach_hang",
        "gia_san_pham",
        "so_luong_san_pham",
        "don_vi_tinh",
    }
    present = [v for v in row if not missing_value(v)]
    if len(present) < 2 or not all(isinstance(v, str) for v in present):
        return False
    required, matches = max(2, math.ceil(len(present) * 0.7)), 0
    for index, value in enumerate(present):
        matches += identifier(value) in labels
        if matches + len(present) - index - 1 < required:
            return False
    return matches >= required


def row_kinds(headers: list[str], rows: list[list]) -> list[str]:
    kinds, running, counts = (
        ["data"] * len(rows),
        [Decimal(0) for _ in headers],
        [0 for _ in headers],
    )
    number_cache = {}
    sum_columns = {
        i
        for i, header in enumerate(headers)
        if column_hint(header) not in {"code", "name", "status", "date"}
    }
    for index, row in enumerate(rows):
        present = [(i, v) for i, v in enumerate(row) if not missing_value(v)]
        if not present:
            kinds[index] = "blank"
            continue
        first_text = next((str(v) for _, v in present if isinstance(v, str)), "")
        total = bool(
            re.match(
                r"^(tong( cong)?|cong|total|grand total|sum|tong so)\b",
                fold_key(first_text).strip(),
            )
        )
        matches = False
        if total:
            for column, value in present:
                number = parse_numeric(value)[0]
                if number is not None and counts[column]:
                    expected = running[column]
                    matches |= abs(number - expected) <= abs(expected) * Decimal("0.005")
        if total and (matches or index == len(rows) - 1):
            kinds[index] = "summary"
        elif (
            len(present) == 1
            and isinstance(present[0][1], str)
            and (
                fold_key(first_text).startswith(("ghi chu", "note:"))
                or index == len(rows) - 1
                and len(headers) > 1
            )
        ):
            kinds[index] = "note"
        else:
            for column, value in present:
                if column not in sum_columns:
                    continue
                cache_key = (type(value).__name__, source_text(value))
                if cache_key not in number_cache:
                    number_cache[cache_key] = parse_numeric(value)[0]
                number = number_cache[cache_key]
                if number is not None:
                    with localcontext() as context:
                        context.prec = 80
                        running[column] += number
                    counts[column] += 1
    for index in range(len(rows) - 1, -1, -1):
        present = [v for v in rows[index] if not missing_value(v)]
        if len(headers) > 1 and len(present) == 1 and isinstance(present[0], str):
            kinds[index] = "note"
        elif present:
            break
    return kinds


def split_blocks(source_rows: list[list], config: DataConfig) -> list[dict]:
    """Split blank-separated regions and new headers; preserve physical source ordinals."""
    regions, current, blanks = [], [], []
    for ordinal, row in enumerate(source_rows, 1):
        if not any(v is not None and str(v).strip() for v in row):
            blanks.append((ordinal, row))
            continue
        if len(blanks) >= 2 and current:
            regions.append(current)
            current = []
        elif current:
            current.extend(blanks)
        blanks = []
        current.append((ordinal, row))
    if current:
        regions.append(current)
    blocks = []
    for region in regions:
        rows = [r for _, r in region]
        scan = list(range(min(config.max_header_scan_rows, len(rows))))
        confirmed = [i for i in scan if recognizable_header(rows[i])]
        scan = confirmed or scan
        header_index = max(scan, key=lambda i: (header_score(rows, i), -i))
        # A sparse group header followed by column labels belongs to one merged header.
        if (
            header_index + 1 < len(rows)
            and not recognizable_header(rows[header_index])
            and recognizable_header(rows[header_index + 1])
            and any(missing_value(v) for v in rows[header_index])
        ):
            header_index += 1
        # A header-only region is exported as an empty table rather than discarded.
        boundaries = [header_index] + [
            i for i in range(header_index + 1, len(rows)) if recognizable_header(rows[i])
        ]
        for block_index, start in enumerate(boundaries):
            end = boundaries[block_index + 1] if block_index + 1 < len(boundaries) else len(rows)
            header = list(rows[start])
            width = max([len(header)] + [len(r) for r in rows[start + 1 : end]])
            header += [None] * (width - len(header))
            if start > 0:
                upper = rows[start - 1]
                if 0 < sum(not missing_value(v) for v in upper) < width and any(
                    missing_value(v) for v in header
                ):
                    carry = ""
                    for i in range(width):
                        if i < len(upper) and not missing_value(upper[i]):
                            carry = str(upper[i])
                        header[i] = (carry + " " + str(header[i] or "")).strip()
            headers = [
                source_text(v) if v is not None and str(v).strip() else f"column_{i + 1}"
                for i, v in enumerate(header)
            ]
            body = [(r + [None] * width)[:width] for r in rows[start + 1 : end]]
            ordinals = [region[i][0] for i in range(start + 1, end)]
            kinds = row_kinds(headers, body)
            blocks.append(
                {
                    "headers": headers,
                    "rows": body,
                    "source_rows": ordinals,
                    "row_kinds": kinds,
                    "header_row": region[start][0],
                    "prefix_rows": [
                        {"source_row": n, "values": [source_text(v) for v in r]}
                        for n, r in region[:start]
                    ]
                    if block_index == 0
                    else [],
                    "blank_rows_dropped": len(blanks) if end == len(rows) else 0,
                }
            )
    return blocks


def excel_sources(path: Path) -> list[tuple[str, list[list], dict]]:
    warnings = []
    try:
        from python_calamine import CalamineWorkbook

        with CalamineWorkbook.from_path(str(path)) as workbook:
            sources = [
                (
                    name,
                    workbook.get_sheet_by_name(name).to_python(skip_empty_area=False),
                    {"reader": "calamine", "warnings": []},
                )
                for name in workbook.sheet_names
            ]
        if path.suffix.lower() in {".xlsx", ".xlsm"}:
            formula_warnings, epoch = audit_excel_formulas(path, sources)
            for name, _, details in sources:
                details["warnings"].extend(formula_warnings.get(name, []))
                details["excel_epoch"] = epoch
        return sources
    except Exception as error:
        if path.suffix.lower() == ".xls":
            raise RuntimeError(f"calamine cannot read legacy Excel: {error}") from error
        warnings.append(f"W_READER_FALLBACK: {type(error).__name__}: {error}")
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sources = [
            (
                sheet.title,
                [list(row) for row in sheet.iter_rows(values_only=True)],
                {
                    "reader": "openpyxl",
                    "excel_epoch": workbook.epoch.isoformat(),
                    "formula_policy": "cached values; source workbook retained by checksum",
                    "warnings": warnings,
                },
            )
            for sheet in workbook
        ]
        formula_warnings, epoch = audit_excel_formulas(path, sources)
        for name, _, details in sources:
            details["warnings"].extend(formula_warnings.get(name, []))
            details["excel_epoch"] = epoch
        return sources
    finally:
        workbook.close()


def audit_excel_formulas(
    path: Path, sources: list[tuple[str, list[list], dict]]
) -> tuple[dict, str]:
    """Report uncached formulas rather than treating their missing values as evidence."""
    from openpyxl import load_workbook

    # Most exports contain cached values only. Scan compressed XML before
    # constructing millions of openpyxl cells solely to discover no formulas.
    with zipfile.ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        properties = root.find("{*}workbookPr")
        mac_epoch = properties is not None and properties.get("date1904") in {"1", "true"}
        epoch = "1904-01-01T00:00:00" if mac_epoch else "1899-12-30T00:00:00"
        has_formulas = False
        for name in archive.namelist():
            if name.startswith("xl/worksheets/") and name.endswith(".xml"):
                with archive.open(name) as stream:
                    tail = b""
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        text = tail + chunk
                        if b"<f" in text or b":f" in text:
                            has_formulas = True
                            break
                        tail = chunk[-3:]
            if has_formulas:
                break
        if not has_formulas:
            return {}, epoch

    cached = {name: rows for name, rows, _ in sources}
    workbook = load_workbook(path, read_only=True, data_only=False)
    issues = {}
    try:
        for sheet in workbook:
            rows = cached[sheet.title]
            missing = []
            for row in sheet.iter_rows():
                for cell in row:
                    if cell.data_type == "f":
                        value = (
                            rows[cell.row - 1][cell.column - 1]
                            if cell.row <= len(rows) and cell.column <= len(rows[cell.row - 1])
                            else None
                        )
                        if value is None or value == "":
                            missing.append(cell.coordinate)
            if missing:
                issues[sheet.title] = ["W_UNCACHED_FORMULAS " + ",".join(missing)]
        return issues, workbook.epoch.isoformat()
    finally:
        workbook.close()


@contextmanager
def sqlite_readonly_snapshot(path: Path):
    """Copy a live WAL snapshot to scratch before immutable reads; never checkpoint input."""
    wal = Path(str(path) + "-wal")
    with tempfile.TemporaryDirectory(prefix="datamate_sqlite_") as temporary:
        snapshot = path.resolve()
        if wal.is_file() and wal.stat().st_size > 32:
            copied = Path(temporary) / "source.sqlite"
            shutil.copyfile(path, copied)
            shutil.copyfile(wal, Path(str(copied) + "-wal"))
            scratch = sqlite3.connect(str(copied))
            target = sqlite3.connect(str(Path(temporary) / "snapshot.sqlite"))
            try:
                scratch.backup(target)
            finally:
                target.close()
                scratch.close()
            snapshot = Path(temporary) / "snapshot.sqlite"
        connection = sqlite3.connect(snapshot.as_uri() + "?mode=ro&immutable=1", uri=True)
        try:
            yield connection
        finally:
            connection.close()


def source_fragments(path: Path, config: DataConfig):
    suffix = path.suffix.lower()
    if suffix in {".csv", ".tsv", ".txt"}:
        rows, details = read_delimited(path, require_dialect=suffix == ".txt")
        for index, block in enumerate(split_blocks(rows, config), 1):
            yield None, index, block, details
    elif suffix in {".xlsx", ".xlsm", ".xls"}:
        for sheet, rows, details in excel_sources(path):
            for label in (sheet, path.stem):
                years = set(re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", label))
                if len(years) == 1:
                    details["source_year"] = int(next(iter(years)))
                    details["year_evidence"] = label
                    break
            for index, block in enumerate(split_blocks(rows, config), 1):
                yield sheet, index, block, details
    elif suffix in {".sqlite", ".sqlite3", ".db"}:
        with sqlite_readonly_snapshot(path) as connection:
            objects = connection.execute(
                "SELECT name,type FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY name COLLATE BINARY"
            ).fetchall()
            for name, object_type in objects:
                cursor = connection.execute(f"SELECT * FROM {sql_quote(name)}")
                headers = [d[0] for d in cursor.description]
                rows = [list(row) for row in cursor.fetchall()]
                block = {
                    "headers": headers,
                    "rows": rows,
                    "source_rows": list(range(1, len(rows) + 1)),
                    "row_kinds": ["data"] * len(rows),
                    "header_row": None,
                    "prefix_rows": [],
                    "blank_rows_dropped": 0,
                }
                details = {
                    "reader": "sqlite3 immutable read-only",
                    "object_type": object_type,
                    "declared_columns": connection.execute(
                        f"PRAGMA table_info({sql_quote(name)})"
                    ).fetchall(),
                    "declared_foreign_keys": connection.execute(
                        f"PRAGMA foreign_key_list({sql_quote(name)})"
                    ).fetchall(),
                    "source_row_policy": "read ordinal; not a primary key",
                    "warnings": [],
                }
                yield name, 1, block, details


def materialize_fragment(
    connection,
    table: str,
    relative: str,
    part: str | None,
    block: dict,
    details: dict,
    config: DataConfig,
) -> dict:
    import pyarrow as pa

    headers, rows = block["headers"], block["rows"]
    names = unique_names(headers)
    raw, typed, dtypes, columns = {}, {}, {}, []
    reserved = set(names)
    for index, (name, original) in enumerate(zip(names, headers, strict=True)):
        values = [row[index] for row in rows]
        active = [
            v if kind == "data" else None
            for v, kind in zip(values, block["row_kinds"], strict=True)
        ]
        parsed = infer_data_column(
            original, active, config, details.get("excel_epoch"), details.get("source_year")
        )
        raw[name] = [source_text(v) for v in values]
        typed[name] = [source_text(v) for v in parsed["values"]]
        dtypes[name] = parsed["sql_type"]
        raw_column = None
        if parsed["sql_type"] != "VARCHAR":
            raw_column = name + "__raw"
            while raw_column in reserved:
                raw_column += "_"
            reserved.add(raw_column)
            typed[raw_column], dtypes[raw_column] = raw[name], "VARCHAR"
        status = f"__dm_status_{index}"
        while status in reserved:
            status += "_"
        reserved.add(status)
        typed[status] = [
            s if kind == "data" else "non_data_row"
            for s, kind in zip(parsed["statuses"], block["row_kinds"], strict=True)
        ]
        dtypes[status] = "VARCHAR"
        unit_column = None
        if any(parsed["units"]):
            unit_column = f"__dm_unit_{index}"
            while unit_column in reserved:
                unit_column += "_"
            reserved.add(unit_column)
            typed[unit_column], dtypes[unit_column] = parsed["units"], "VARCHAR"
        failures = sum(
            s not in {"missing", "parsed", "retained_string"} for s in parsed["statuses"]
        )
        if failures:
            parsed["warnings"].append(f"W_PARSE_FAILURE count={failures}")
        columns.append(
            {
                "name": name,
                "original_name": original,
                "sql_type": parsed["sql_type"],
                "semantic_hint": parsed["semantic_hint"],
                "format_note": parsed["format_note"],
                "raw_column": raw_column,
                "status_column": status,
                "unit_column": unit_column,
                "warnings": parsed["warnings"],
                "parse_failures": failures,
                "observed_units": sorted({u for u in parsed["units"] if u}),
                "status_counts": dict(Counter(typed[status])),
                "number_convention": parsed.get("number_convention"),
                "parse_rate": (
                    sum(s in {"parsed", "retained_string"} for s in parsed["statuses"])
                    / max(1, sum(s != "missing" for s in parsed["statuses"]))
                )
                if any(s != "missing" for s in parsed["statuses"])
                else 1.0,
            }
        )
    provenance_names = {}
    for base, values in {
        "source_row": block["source_rows"],
        "row_kind": block["row_kinds"],
    }.items():
        name = f"__dm_{base}"
        while name in reserved:
            name += "_"
        reserved.add(name)
        provenance_names[base] = name
        raw[name] = typed[name] = [str(v) for v in values]
        dtypes[name] = "BIGINT" if base == "source_row" else "VARCHAR"
    for schema, data in (("raw", raw), ("typed", typed)):
        arrow = pa.table(
            {name: pa.array(values, type=pa.string()) for name, values in data.items()}
        )
        connection.register("incoming", arrow)
        projection = ",".join(
            f"CAST({sql_quote(n)} AS {dtypes[n] if schema == 'typed' else 'VARCHAR'}) AS {sql_quote(n)}"
            for n in data
        )
        try:
            connection.execute(
                f"CREATE TABLE {schema}.{sql_quote(table)} AS SELECT {projection} FROM incoming"
            )
        finally:
            connection.unregister("incoming")
    row_kind = sql_quote(provenance_names["row_kind"])
    connection.execute(
        f"CREATE VIEW {sql_quote(table)} AS SELECT * FROM typed.{sql_quote(table)} WHERE {row_kind}='data'"
    )
    dropped_indices = {
        kind: [
            ordinal
            for ordinal, category in zip(block["source_rows"], block["row_kinds"], strict=True)
            if category == kind
        ]
        for kind in {"summary", "note", "blank"}
    }
    dropped_indices["note"].extend(row["source_row"] for row in block["prefix_rows"])
    return {
        "name": table,
        "source_file": relative,
        "source_part": part,
        "row_count": block["row_kinds"].count("data"),
        "raw_row_count": len(rows),
        "columns": columns,
        "source_details": details,
        "header_row": block["header_row"],
        "prefix_rows": block["prefix_rows"],
        "provenance_columns": provenance_names,
        "dropped_rows": dict(Counter(kind for kind in block["row_kinds"] if kind != "data")),
        "dropped_source_indices": dropped_indices,
        "candidate_keys": [],
    }


def profile_table(connection, table: dict, config: DataConfig) -> None:
    name = sql_quote(table["name"])
    for column in table["columns"]:
        field = sql_quote(column["name"])
        nulls, distinct, lower, upper = connection.execute(
            f"SELECT COUNT(*)-COUNT({field}),COUNT(DISTINCT {field}),MIN({field})::VARCHAR,MAX({field})::VARCHAR FROM {name}"
        ).fetchone()
        limit = (
            config.low_cardinality_max
            if distinct <= config.low_cardinality_max
            else config.top_values_max
        )
        top = connection.execute(
            f"SELECT {field}::VARCHAR,COUNT(*) AS n FROM {name} WHERE {field} IS NOT NULL GROUP BY {field} ORDER BY n DESC,{field} ASC LIMIT {int(limit)}"
        ).fetchall()
        column.update(
            null_count=nulls,
            distinct_count=distinct,
            min=lower,
            max=upper,
            top_values=[list(v) for v in top],
            null_rate=nulls / table["row_count"] if table["row_count"] else 0,
        )
        if table["row_count"] and nulls == 0 and distinct == table["row_count"]:
            table["candidate_keys"].append([column["name"]])
    if 0 < len(table["columns"]) <= config.max_columns_for_pair_keys and table["row_count"]:
        singles = {key[0] for key in table["candidate_keys"]}
        for left, right in itertools.combinations(table["columns"], 2):
            if (
                left["name"] in singles
                or right["name"] in singles
                or left["null_count"]
                or right["null_count"]
            ):
                continue
            fields = f"{sql_quote(left['name'])},{sql_quote(right['name'])}"
            distinct = connection.execute(
                f"SELECT COUNT(*) FROM (SELECT DISTINCT {fields} FROM {name})"
            ).fetchone()[0]
            if distinct == table["row_count"]:
                table["candidate_keys"].append([left["name"], right["name"]])


def catalog_joins(connection, tables: list[dict]) -> list[dict]:
    joins = []
    for left, right in itertools.permutations(tables, 2):
        right_keys = {key[0] for key in right["candidate_keys"] if len(key) == 1}
        left_keys = {key[0] for key in left["candidate_keys"] if len(key) == 1}
        for lc, rc in itertools.product(left["columns"], right["columns"]):
            numeric = {"BIGINT", "DOUBLE", "DECIMAL(38,6)"}
            compatible = (
                lc["sql_type"] == rc["sql_type"] or {lc["sql_type"], rc["sql_type"]} <= numeric
            )

            def trim_table(column, table):
                tokens = identifier(column).split("_")
                prefix = identifier(table).split("_")
                return tokens[len(prefix) :] if tokens[: len(prefix)] == prefix else tokens

            name_match = lc["name"] == rc["name"] or trim_table(
                lc["name"], left["name"]
            ) == trim_table(rc["name"], right["name"])
            if (
                not compatible
                or lc["max"] is None
                or (not name_match and rc["name"] not in right_keys)
            ):
                continue
            if not name_match and lc.get("distinct_count", 0) > rc.get("distinct_count", 0) / 0.95:
                continue
            # Value containment is observational evidence, never an asserted foreign key.
            ln, rn = sql_quote(lc["name"]), sql_quote(rc["name"])
            total, matched = connection.execute(
                f"SELECT COUNT(*),COUNT(*) FILTER(WHERE EXISTS(SELECT 1 FROM {sql_quote(right['name'])} r WHERE r.{rn}=l.{ln})) FROM {sql_quote(left['name'])} l WHERE l.{ln} IS NOT NULL"
            ).fetchone()
            rate = matched / total if total else 0
            if rate >= 0.90 and (name_match or rate >= 0.95):
                joins.append(
                    {
                        "left_table": left["name"],
                        "left_column": lc["name"],
                        "right_table": right["name"],
                        "right_column": rc["name"],
                        "match_rate": rate,
                        "relationship": "candidate_n_to_1",
                        "cardinality": ("1:1" if lc["name"] in left_keys else "n:1")
                        if rc["name"] in right_keys
                        else "n:n",
                    }
                )
    return joins


def catalog_date_range(tables: list[dict]) -> tuple[list[dict], dict | None]:
    dates = []
    for table in tables:
        dimension = table["row_count"] <= 200 and not any(
            c["semantic_hint"] in {"money", "quantity"} for c in table["columns"]
        )
        for column in table["columns"]:
            if column["sql_type"] in {"DATE", "TIMESTAMP"} and column["min"] is not None:
                label = identifier(re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", column["original_name"]))
                non_activity = label in {"hsd", "dob", "expiry", "expiration"} or any(
                    term in label
                    for term in (
                        "han_su_dung",
                        "het_han",
                        "han_thanh_toan",
                        "ngay_den_han",
                        "ngay_sinh",
                        "ngay_thoi_viec",
                        "expiry",
                        "expiration",
                        "due_date",
                        "birth_date",
                    )
                )
                dates.append(
                    {
                        "table": table["name"],
                        "column": column["name"],
                        "start": column["min"][:10],
                        "end": column["max"][:10],
                        "included_in_data_range": not dimension and not non_activity,
                        "exclusion_reason": "non_activity_date"
                        if non_activity
                        else "dimension_table"
                        if dimension
                        else None,
                    }
                )
    included = [row for row in dates if row["included_in_data_range"]]
    bounds = (
        {"start": min(row["start"] for row in included), "end": max(row["end"] for row in included)}
        if included
        else None
    )
    return dates, bounds


def render_catalog(catalog: dict, *, top_limit: int | None = None) -> str:
    lines = []
    for table in catalog["tables"]:
        part = f" > {table['source_part']}" if table["source_part"] is not None else ""
        lines.append(
            f"TABLE {table['name']}  ({table['row_count']:,} rows; source {table['source_file']}{part})"
        )
        keys = {name for key in table["candidate_keys"] for name in key}
        for column in table["columns"]:
            line = f"  {column['name']} {column['sql_type']} {'candidate_key' if column['name'] in keys else ''} nulls {column['null_rate']:.2%}"
            high_cardinality = column["distinct_count"] > catalog.get("low_cardinality_max", 50)
            top = (
                column["top_values"][:top_limit]
                if top_limit and high_cardinality
                else column["top_values"]
            )
            if column["sql_type"] == "VARCHAR":
                line += " values: " + ", ".join(
                    f"{json.dumps(v, ensure_ascii=False)}({n})" for v, n in top
                )
            elif column["min"] is not None:
                line += f" {column['min']}..{column['max']}"
            line += f" {column['semantic_hint'] or ''} [{json.dumps(column['original_name'], ensure_ascii=False)}]"
            if column.get("unit_column"):
                line += f" unit_column={column['unit_column']} units={json.dumps(column['observed_units'], ensure_ascii=False)} (no conversion)"
            lines.append(line)
    for edge in catalog["joins"]:
        lines.append(
            f"JOIN {edge['left_table']}.{edge['left_column']} -> {edge['right_table']}.{edge['right_column']} (candidate n:1, {edge['match_rate']:.1%})"
        )
    lines.extend(
        f"DATES {row['table']}.{row['column']} {row['start']}..{row['end']}"
        + (
            f" (excluded from activity coverage: {row.get('exclusion_reason')})"
            if not row.get("included_in_data_range", True)
            else ""
        )
        for row in catalog["date_columns"]
    )
    lines.extend("WARN " + warning for warning in catalog["warnings"])
    lines.extend(
        f"VIEW {view['name']} {view['purpose']}\n{view['ddl']}" for view in catalog.get("views", [])
    )
    return "\n".join(lines) + "\n"


def budget_schema_card(catalog: dict, config: DataConfig, tokenizer=None) -> dict:
    """Only a supplied inference tokenizer can certify the production token budget."""
    full = render_catalog(catalog)
    if tokenizer is None:
        return {
            "text": full,
            "full_text": full,
            "budget_verified": False,
            "needs_relevant_subset": None,
            "warning": "W_TOKENIZER_REQUIRED_FOR_BUDGET",
        }
    for limit in (None, 10, 5):
        text = render_catalog(catalog, top_limit=limit)
        count = len(tokenizer.encode(text, add_special_tokens=False))
        if count <= config.schema_card_budget_tokens:
            return {
                "text": text,
                "full_text": full,
                "tokens": count,
                "budget_verified": True,
                "needs_relevant_subset": False,
            }
    return {
        "text": text,
        "full_text": full,
        "tokens": count,
        "budget_verified": True,
        "needs_relevant_subset": True,
        "warning": "W_CONTEXT_RELEVANT_SUBSET_REQUIRED",
    }


def validate_catalog_database(database: Path, tables: list[dict]) -> dict:
    import duckdb

    failures = []
    with duckdb.connect(
        str(database),
        read_only=True,
        config={
            "threads": 1,
            "autoinstall_known_extensions": False,
            "autoload_known_extensions": False,
        },
    ) as connection:
        for table in tables:
            name = sql_quote(table["name"])
            raw_count = connection.execute(f"SELECT COUNT(*) FROM raw.{name}").fetchone()[0]
            typed_count = connection.execute(f"SELECT COUNT(*) FROM typed.{name}").fetchone()[0]
            data_count = connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            if (
                raw_count != table["raw_row_count"]
                or typed_count != raw_count
                or data_count != table["row_count"]
            ):
                failures.append("ROW_ACCOUNTING " + table["name"])
            for column in table["columns"]:
                status = sql_quote(column["status_column"])
                actual = dict(
                    connection.execute(
                        f"SELECT {status},COUNT(*) FROM typed.{name} GROUP BY {status}"
                    ).fetchall()
                )
                if actual != column["status_counts"]:
                    failures.append(f"STATUS_ACCOUNTING {table['name']}.{column['name']}")
    return {"valid": not failures, "failures": failures, "tables_checked": len(tables)}


def build_business_database(
    business: Path, business_id: str, destination: Path, config: DataConfig, tokenizer=None
) -> dict:
    import duckdb

    business = business.resolve()
    if destination.resolve().is_relative_to(business):
        raise ValueError("Work directory must be outside business input")
    key = hashlib.sha256(business_id.encode()).hexdigest()[:20]
    destination.mkdir(parents=True, exist_ok=True)
    database = destination / "catalog.duckdb"
    temporary = destination / "catalog.build.duckdb"
    for stale in (temporary, Path(str(temporary) + ".wal")):
        stale.unlink(missing_ok=True)
    # Rebuild without reusing an unverified database from an interrupted run.
    connection = duckdb.connect(
        str(temporary),
        config={
            "threads": 1,
            "autoinstall_known_extensions": False,
            "autoload_known_extensions": False,
        },
    )
    tables, warnings, used = [], [], []
    readme = next(
        (p for p in sorted(business.iterdir()) if p.is_file() and p.name.casefold() == "readme.md"),
        None,
    )
    readme_text = nfc_text(readme.read_text(encoding="utf-8-sig")) if readme else None
    try:
        connection.execute("CREATE SCHEMA raw")
        connection.execute("CREATE SCHEMA typed")
        paths = sorted(
            (
                p
                for p in business.rglob("*")
                if p.is_file() and len(p.relative_to(business).parts) <= 2
            ),
            key=lambda p: p.relative_to(business).as_posix().encode("utf-8"),
        )
        for path in paths:
            if path.suffix.lower() not in {
                ".csv",
                ".tsv",
                ".txt",
                ".xlsx",
                ".xlsm",
                ".xls",
                ".sqlite",
                ".sqlite3",
                ".db",
            }:
                continue
            relative = path.relative_to(business).as_posix()
            if path.stat().st_size > config.max_file_mb * 1024**2:
                warnings.append(f"W_FILE_TOO_LARGE {relative}")
                continue
            if path.suffix.lower() == ".txt":
                try:
                    read_delimited(path, require_dialect=True)
                except ValueError:
                    warnings.append(f"W_DELIMITER_UNRECOGNIZED {relative}")
                    continue
            for part, index, block, details in source_fragments(path, config):
                base = (
                    identifier(path.stem)
                    + (f"__{identifier(part)}" if part is not None else "")
                    + (f"_{index}" if index > 1 else "")
                )
                name, suffix = base, 1
                while name in used:
                    suffix += 1
                    name = f"{base}_{suffix}"
                used.append(name)
                table = materialize_fragment(
                    connection, name, relative, part, block, details, config
                )
                profile_table(connection, table, config)
                tables.append(table)
                warnings.extend(f"{warning} {relative}" for warning in details.get("warnings", []))
                warnings.extend(
                    f"{warning} {name}.{column['name']}"
                    for column in table["columns"]
                    for warning in column["warnings"]
                )
                warnings.extend(
                    f"W_{'TOTAL' if kind == 'summary' else kind.upper()}_ROW_DROPPED {name} row={ordinal}"
                    for kind, indices in table["dropped_source_indices"].items()
                    for ordinal in indices
                )
        joins = catalog_joins(connection, tables)
        connection.execute("CHECKPOINT")
    finally:
        connection.close()
    temporary.replace(database)
    date_columns, data_range = catalog_date_range(tables)
    database_validation = validate_catalog_database(database, tables)
    formula_complete = not any("W_UNCACHED_FORMULAS" in warning for warning in warnings)
    catalog = {
        "business_id": business_id,
        "bkey": key,
        "database": "catalog.duckdb",
        "tables": tables,
        "joins": joins,
        "date_columns": date_columns,
        "data_range": data_range,
        "readme_text": readme_text,
        "warnings": sorted(set(warnings)),
        "status": "ready"
        if tables and database_validation["valid"] and formula_complete
        else "failed",
        "database_validation": database_validation,
        "cached_formula_values_complete": formula_complete,
        "business_semantics_validated": False,
        "low_cardinality_max": config.low_cardinality_max,
    }
    card = budget_schema_card(catalog, config, tokenizer)
    catalog["schema_card_budget"] = {
        k: v for k, v in card.items() if k not in {"text", "full_text"}
    }
    catalog["schema_card_sha256"] = hashlib.sha256(card["full_text"].encode()).hexdigest()
    (destination / "schema_card.txt").write_text(card["full_text"], encoding="utf-8")
    (destination / "schema_card_prompt.txt").write_text(card["text"], encoding="utf-8")
    if readme_text is not None:
        (destination / "README.md").write_text(readme_text, encoding="utf-8")
    write_json(destination / "catalog.json", catalog)
    return catalog


def prepare_business(
    split_dir: Path, business_id: str, folder: Path, config: DataConfig, tokenizer=None
) -> dict:
    key = hashlib.sha256(business_id.encode()).hexdigest()[:20]
    return build_business_database(
        safe_business_dir(split_dir, business_id),
        business_id,
        folder / "businesses" / key,
        config,
        tokenizer,
    )


def prepare_data(
    split_dir: Path,
    output_dir: Path,
    config: DataConfig | None = None,
    *,
    tokenizer=None,
    code_sha256: str | None = None,
) -> dict:
    config = config or DataConfig()
    questions, rejected, _ = load_questions(split_dir)
    businesses = sorted({q["business_id"] for q in questions})
    paths = [split_dir / "questions.jsonl"]
    for business_id in businesses:
        business = safe_business_dir(split_dir, business_id)
        paths.extend(
            p
            for p in business.rglob("*")
            if p.is_file() and len(p.relative_to(business).parts) <= 2
        )
    inventory = inventory_files(split_dir, paths)
    folder = component_run(
        split_dir,
        output_dir,
        "data",
        inventory,
        asdict(config),
        code_sha256 or implementation_digest(globals()),
    )
    catalogs, errors = [], []
    for business_id in businesses:
        try:
            catalogs.append(prepare_business(split_dir, business_id, folder, config, tokenizer))
        except Exception as error:
            errors.append(
                {"business_id": business_id, "reason": f"{type(error).__name__}: {error}"}
            )
    write_json(folder / "catalogs.json", catalogs)
    write_json(folder / "business_errors.json", errors)
    unchanged = verify_inventory(split_dir, inventory)
    validation = {
        "valid": bool(catalogs)
        and not errors
        and not rejected
        and all(c["status"] == "ready" for c in catalogs)
        and unchanged["valid"],
        "businesses": len(businesses),
        "completed_businesses": len(catalogs),
        "errors": errors,
        "rejected_questions": len(rejected),
        "input_unchanged": unchanged,
        "business_semantics_validated": False,
        "schema_token_budget_verified": all(
            c["schema_card_budget"]["budget_verified"] for c in catalogs
        ),
    }
    finish_component(folder, validation)
    return {"folder": folder, "catalogs": catalogs, "validation": validation}
