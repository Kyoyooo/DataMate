"""Conservative verification of split-level temporal claims against the rulebook."""

from __future__ import annotations

import json
import re

from datamate.contracts import ParamProvenance, TemporalParams
from datamate.lexicon import nfc

_TO_DATE_SUBJECT = r"(?:tuần này|tháng này|năm nay)(?:(?:, | và )(?:tuần này|tháng này|năm nay))*"
_TO_DATE_PREFIX = _TO_DATE_SUBJECT + r"(?:\s*:\s*| )(?:tính )?(?:đến|tới) hết (?:ngày )?"
_ROLLING = r"(?:n|\d+) ngày (?:gần nhất|qua)"
_WEEK_START = r"(?:tuần bắt đầu (?:vào |từ )?|the week starts on |week starts on )"
_WEEK_NOT_START = r"(?:tuần không bắt đầu (?:vào |từ )?|(?:the )?week does not start on )"
_WEEKDAY = {"mon": r"(?:thứ hai|thứ 2|monday)", "sun": r"(?:chủ nhật|sunday)"}

# Match complete, affirmative clauses. Values in an example, conditional, or unrecognized
# paraphrase do not authorize a parameter override, even if the model quotes them verbatim.
_RULES: dict[str, dict[str | bool, str]] = {
    "week_start": {option: _WEEK_START + pattern for option, pattern in _WEEKDAY.items()},
    "to_date_end": {
        "as_of": _TO_DATE_PREFIX + r"(?:hôm nay|as_of_date)|to-date periods include (?:today|as_of_date)",
        "day_before_as_of": _TO_DATE_PREFIX + r"hôm qua|to-date periods end (?:yesterday|the day before as_of_date)",
    },
    "rolling_includes_as_of": {
        True: _ROLLING + r"(?:\s*:\s*(?:n|\d+) ngày liền nhau, ngày cuối là hôm nay| (?:tính|bao gồm) (?:cả )?hôm nay)"
        r"|rolling periods include (?:today|as_of_date)",
        False: _ROLLING + r" (?:không tính|không bao gồm) hôm nay|rolling periods exclude (?:today|as_of_date)",
    },
    "prior_period_full": {
        True: r"(?:tuần rồi|tuần trước)\s*:\s*cả tuần liền trước|(?:tuần trước|tháng trước) là cả (?:tuần|tháng) liền trước"
        r"|prior periods use the full preceding calendar period",
        False: r"(?:tuần trước|tháng trước) chỉ tính cùng số ngày|prior periods use only the same number of elapsed days",
    },
    "year_omitted_policy": {
        "most_recent_not_after_as_of": r"(?:khi )?thiếu năm, (?:chọn|dùng) lần xuất hiện gần nhất không sau (?:hôm nay|as_of_date)"
        r"|dates without a year use the latest occurrence on or before as_of_date",
    },
    "same_period_alignment": {
        "calendar_dates": r"cùng kỳ năm ngoái giữ nguyên ngày và tháng|the prior-year period uses the same calendar dates",
        "elapsed_days": r"cùng kỳ năm ngoái (?:giữ nguyên|dùng) (?:cùng )?số ngày|the prior-year period preserves the number of elapsed days",
    },
}

_NON_NORMATIVE = re.compile(r"\b(?:ví dụ|example|for instance|minh họa|giả sử|giả định)\b", re.IGNORECASE)
_LIST_PREFIX = re.compile(r"^(?:[-*+] |\d+[.)] )")


def _collapsed(text: str) -> str:
    return " ".join(nfc(text).split())


def _clauses(text: str) -> set[str]:
    """Recognize prose and Markdown list items, excluding examples and quotations."""
    blocks: list[str] = []
    current: list[str] = []
    fence = ""
    in_examples = False
    for raw in text.splitlines():
        line = raw.strip()
        starts_fence = line.startswith(("```", "~~~"))
        list_item = _LIST_PREFIX.match(line)
        heading = line.startswith("#")
        excluded = line.startswith(">") or bool(_NON_NORMATIVE.search(line))
        if not line or starts_fence or heading or list_item or excluded:
            if current:
                blocks.append(" ".join(current))
                current.clear()
        if starts_fence:
            if not fence:
                fence = line[:3]
            elif line.startswith(fence):
                fence = ""
            continue
        if fence:
            continue
        if heading:
            in_examples = excluded
        if line and not heading and not in_examples and not excluded:
            current.append(line[list_item.end():] if list_item else line)
    if current:
        blocks.append(" ".join(current))
    return {
        _collapsed(clause.translate(str.maketrans("", "", "*`"))).casefold()
        for block in blocks for clause in re.split(r"[.!?;](?=\s|$)", block)
        if clause.strip()
    }


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    # Keep other fields usable, but invalidate duplicated fields and nested keys.
    obj: dict[str, object] = {}
    for key, value in pairs:
        obj[key] = None if key in obj else value
    return obj


def _reject_non_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def temporal_candidate_schema() -> dict:
    properties = {
        field: {
            "type": "object", "additionalProperties": False, "required": ["value", "span"],
            "properties": {"value": {"enum": [*values, None]}, "span": {"type": ["string", "null"]}},
        }
        for field, values in _RULES.items()
    }
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def validate_temporal_params(rulebook: str, content: str) -> tuple[TemporalParams, dict[str, str]]:
    """Resolve a model response using generic defaults and independent per-field evidence."""
    defaults = TemporalParams()
    try:
        candidates = json.loads(content, object_pairs_hook=_unique_object, parse_constant=_reject_non_json_constant)
    except (ValueError, RecursionError):
        return defaults, {"profile": "invalid_json"}
    if not isinstance(candidates, dict):
        return defaults, {"profile": "invalid_shape"}

    normalized_rulebook = _collapsed(rulebook)
    clauses = _clauses(rulebook)
    provenance: dict[str, ParamProvenance] = {}
    verified = {}
    diagnostics = {}
    for name, rules in _RULES.items():
        candidate = candidates.get(name)
        if name not in candidates:
            diagnostics[name] = "missing_field"
            continue
        if not isinstance(candidate, dict) or candidate.keys() != {"value", "span"}:
            diagnostics[name] = "invalid_candidate"
            continue
        value, span = candidate["value"], candidate["span"]
        if value is None:
            diagnostics[name] = "missing_value"
            continue
        if type(value) is not type(getattr(defaults, name)) or value not in rules:
            diagnostics[name] = "invalid_value"
            continue
        if not isinstance(span, str) or not _collapsed(span) or _collapsed(span) not in normalized_rulebook:
            diagnostics[name] = "unverified_span"
            continue

        evidence = {option: {clause for clause in clauses if re.fullmatch(pattern, clause)}
                    for option, pattern in rules.items()}
        supported = {option for option, matches in evidence.items() if matches}
        negated_week = name == "week_start" and any(
            re.fullmatch(_WEEK_NOT_START + _WEEKDAY[value], clause) for clause in clauses
        )
        if negated_week or supported - {value}:
            diagnostics[name] = "contradictory_rulebook"
        elif not evidence[value].intersection(_clauses(span)):
            diagnostics[name] = "insufficient_evidence"
        elif name == "prior_period_full" and value is False:
            diagnostics[name] = "unsupported_runtime_value"
        else:
            verified[name] = value
            provenance[name] = ParamProvenance(source="rulebook", span=span)

    return TemporalParams(**verified, provenance=provenance), diagnostics
