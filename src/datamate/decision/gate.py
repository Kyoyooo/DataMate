"""Rule gate: answer, unanswerable, or abstain (SPEC §7.9, C9, P1). Owner: M2.

Scoring is +1 correct, 0 abstain, -1 wrong, and a wrong "unanswerable" costs
-1 like any wrong answer. So "unanswerable" is emitted only on positive
evidence that the data cannot support the question:

  * a resolved time window has zero overlap with the business's data range
    (rulebook §7, train and public_test: "no data" is not zero), or
  * the parser reports missing fields and a complete catalog check supports their absence.

Every other failure (bad parse, unsupported time, SQL errors, empty results,
type mismatch, implausible value) is "abstain".

Rules, first match wins:
  1. pipeline error                                → abstain (that code)
  2. answerability "unclear"                       → abstain D_UNCLEAR
  3. missing field confirmed by catalog check      → unanswerable
  4. any window with coverage 0                    → unanswerable (config: abstain)
  5. no successful attempt                         → abstain (last attempt's code)
  6. value type differs from expected type         → abstain E_TYPE_CONTRACT
  7. implausible value (|percent| > 100000)        → abstain D_IMPLAUSIBLE
     (non-finite values never reach here: solver/typed.py rejects them)
  8. otherwise                                     → answer
"""

from __future__ import annotations

from decimal import Decimal
from difflib import SequenceMatcher
from typing import TypedDict

from datamate.config import RunConfig
from datamate.contracts import (
    BusinessCatalog,
    Decision,
    ExecutionResult,
    QuestionFrame,
    ScalarValue,
    SolverAttempt,
    TimeWindow,
    codes,
)
from datamate.lexicon import fold

PERCENT_PLAUSIBLE_MAX = Decimal(100_000)
_INCOMPLETE_SCHEMA = {codes.W_UNSUPPORTED_FILE, codes.W_EMPTY_FILE}
_README_ABSENCE = ("khong co cot ", "khong ghi ", "khong luu ", "no column ")


class _FieldEvidence(TypedDict):
    field: str
    status: str
    source: str
    columns: list[str]


def _catalog_labels(cat: BusinessCatalog) -> dict[str, set[str]]:
    labels: dict[str, set[str]] = {}
    for table in cat.tables:
        table_name = fold(table.name)
        for column in table.columns:
            identifier = f"{table.name}.{column.name}"
            for name in {fold(column.name), fold(column.original_name)} - {""}:
                labels.setdefault(name, set()).add(identifier)
                labels.setdefault(f"{table_name} {name}", set()).add(identifier)
    return labels


def _near_label(tokens: set[str], label: str) -> bool:
    """Conservative subset of §7.9 fuzzy candidates: reordered tokens or a near-complete spelling."""
    other = set(label.split())
    if tokens == other:
        return True
    missing, extra = tokens - other, other - tokens
    if len(missing) != 1 or len(extra) != 1:
        return False
    left, right = next(iter(missing)), next(iter(extra))
    if min(len(left), len(right)) < 4:
        return False
    matched = sum(block.size for block in SequenceMatcher(None, left, right, autojunk=False).get_matching_blocks())
    return matched >= max(len(left), len(right)) - 1


def _field_evidence(field: str, labels: dict[str, set[str]], readme: str,
                    incomplete: bool) -> _FieldEvidence:
    def result(status: str, source: str, columns: set[str] | None = None) -> _FieldEvidence:
        return {"field": field, "status": status, "source": source, "columns": sorted(columns or ())}

    name = fold(field)
    if not name:
        return result("uncertain", "empty_claim")
    physical = labels.get(name, set())
    mapped: set[str] = set()
    mentioned = denied = False
    for line in readme.splitlines():
        normalized = fold(line)
        if any(normalized == prefix + name for prefix in _README_ABSENCE):
            denied = True
            continue
        if f" {name} " not in f" {normalized} ":
            continue
        mentioned = True
        left, sep, right = line.partition(":")
        if sep:
            left_key, right_key = fold(left), fold(right)
            if left_key == name:
                mapped.update(labels.get(right_key, ()))
            if right_key == name:
                mapped.update(labels.get(left_key, ()))

    if physical and (denied or mapped - physical):
        return result("conflict", "catalog_vs_readme", physical | mapped)
    if physical or mapped:
        candidates = physical or mapped
        if len(candidates) > 1 or denied:
            return result("uncertain", "catalog_ambiguous" if physical else "readme_ambiguous", candidates)
        return result("present", "catalog_exact" if physical else "readme_mapping", candidates)
    if mentioned:
        return result("uncertain", "readme_mention")
    tokens = set(name.split())
    nearby = {column for label, columns in labels.items() if _near_label(tokens, label) for column in columns}
    if nearby:
        return result("uncertain", "catalog_fuzzy", nearby)
    if incomplete:
        return result("uncertain", "catalog_incomplete")
    return result("absent", "readme_absence" if denied else "catalog_no_match")


def _check_fields(fields: list[str], cat: BusinessCatalog) -> list[_FieldEvidence]:
    if not fields:
        return []
    labels = _catalog_labels(cat)
    incomplete = cat.status != "ready" or not labels or any(
        warning.split(" ", 1)[0] in _INCOMPLETE_SCHEMA for warning in cat.warnings
    )
    return [_field_evidence(field, labels, cat.readme_text or "", incomplete) for field in fields]


def field_in_catalog(field: str, cat: BusinessCatalog) -> bool:
    """Whether the catalog or a physical README mapping supports the claimed field."""
    return _check_fields([field], cat)[0]["status"] in ("present", "conflict")


def _missing_comparison_refs(frame: QuestionFrame | None, windows: list[TimeWindow]) -> list[int]:
    if frame is None:
        return []
    resolved = {(w.ref_index, w.role) for w in windows}
    return [i for i, ref in enumerate(frame.time)
            if ref.role in ("comparison", "baseline") and (i, ref.role) not in resolved]


def pre_solve_decision(frame: QuestionFrame, windows: list[TimeWindow], cat: BusinessCatalog,
                       cfg: RunConfig, *, field_evidence: list[_FieldEvidence] | None = None) -> Decision | None:
    """Rules 2–4. A non-None result means solving is unnecessary."""
    a = frame.answerability
    if _missing_comparison_refs(frame, windows):
        return Decision(kind="abstain", reason_code=codes.E_TIME_UNSUPPORTED)
    if a.status == "unclear":
        return Decision(kind="abstain", reason_code=codes.D_UNCLEAR)
    if a.status == "missing_field" and a.missing_fields:
        evidence = _check_fields(a.missing_fields, cat) if field_evidence is None else field_evidence
        if evidence and all(item["status"] == "absent" for item in evidence):
            return Decision(kind="unanswerable", reason_code=codes.D_UNANSWERABLE_CONFIRMED,
                            unanswerable_reason="missing_field:" + ",".join(a.missing_fields))
    zero = [w for w in windows if w.coverage_ratio == 0.0]
    if zero:
        kind = "unanswerable" if cfg.decision.zero_coverage == "unanswerable" else "abstain"
        w = zero[0]
        return Decision(kind=kind, reason_code=codes.D_UNANSWERABLE_OUT_OF_RANGE,
                        unanswerable_reason=f"no_data:{w.start.isoformat()}..{w.end.isoformat()}"
                        if kind == "unanswerable" else None)
    return None


def _coverage_state(ratio: float | None) -> str:
    if ratio is None:
        return "unknown"
    if ratio == 0:
        return "zero"
    return "full" if ratio == 1 else "partial"


def _execution_state(execution: ExecutionResult | None, frame: QuestionFrame | None) -> str:
    if execution is None:
        return "not_run"
    if not execution.ok:
        return "error"
    if execution.row_count == 0:
        return "empty"
    if frame and frame.expected_type not in ("list", "table") and execution.row_count == 1 and execution.rows:
        row = execution.rows[0]
        index = (0 if len(execution.columns) == 1 else
                 execution.columns.index("value") if "value" in execution.columns else None)
        if index is not None and index < len(row) and row[index] is None:
            return "null_scalar"
    return "rows"


def decide(frame: QuestionFrame | None, windows: list[TimeWindow], attempts: list[SolverAttempt],
           cat: BusinessCatalog | None, cfg: RunConfig, pipeline_error: str | None) -> Decision:
    final = next((a for a in reversed(attempts) if a.ok), None)
    execution = final.execution if final and final.execution is not None else next(
        (a.execution for a in reversed(attempts) if a.execution is not None), None
    )
    reported = frame.answerability.missing_fields if frame and frame.answerability.status == "missing_field" else []
    evidence = _check_fields(reported, cat) if cat is not None and pipeline_error is None else []
    generic = any("F_TEMPORAL_GENERIC" in w.flags for w in windows)
    features = {
        "n_attempts": len(attempts),
        "n_repairs": sum(1 for a in attempts if a.stage == "repair"),
        "min_coverage": min((w.coverage_ratio for w in windows if w.coverage_ratio is not None),
                            default=None),
        "temporal_generic": generic,
        "temporal_generic_params": generic,
        "used_fallback": False,  # current P1 solver has no fallback stage
        "degrade": False,  # current runtime has no degrade mode
        "span_mismatch": None if pipeline_error == codes.E_PARSE_INVALID else False,
        "percent_scale_flag": None,
        "coverage": [{"ref_index": w.ref_index, "role": w.role, "ratio": w.coverage_ratio,
                      "state": _coverage_state(w.coverage_ratio)} for w in windows],
        "missing_comparison_refs": _missing_comparison_refs(frame, windows),
        "model_answerability": frame.answerability.status if frame else None,
        "model_missing_fields": reported,
        "missing_field_evidence": evidence,
        "execution_state": _execution_state(execution, frame),
        "row_count": execution.row_count if execution and execution.ok else None,
        "has_null": bool(execution and execution.ok and any(cell is None for row in execution.rows for cell in row)),
        "sql_error_code": execution.error_code if execution and not execution.ok else None,
    }

    def done(**kw: object) -> Decision:
        return Decision(features=features, **kw)

    if pipeline_error is not None or frame is None or cat is None:
        return done(kind="abstain", reason_code=pipeline_error or codes.E_INTERNAL)
    pre = pre_solve_decision(frame, windows, cat, cfg, field_evidence=evidence)
    if pre is not None:
        return done(kind=pre.kind, reason_code=pre.reason_code,
                    unanswerable_reason=pre.unanswerable_reason)
    if final is None or final.value is None:
        last = attempts[-1].error_code if attempts else None
        return done(kind="abstain", reason_code=last or codes.E_NO_SUCCESS)
    value = final.value
    if value.type != frame.expected_type:
        return done(kind="abstain", reason_code=codes.E_TYPE_CONTRACT)
    if isinstance(value, ScalarValue) and value.type in ("number", "percent"):
        if not value.value.is_finite():
            return done(kind="abstain", reason_code=codes.D_IMPLAUSIBLE)
        if value.type == "percent":
            magnitude = value.value.copy_abs()
            features["percent_scale_flag"] = magnitude <= Decimal("1.5")  # SPEC §7.7.3, diagnostic only
            if magnitude > PERCENT_PLAUSIBLE_MAX:
                return done(kind="abstain", reason_code=codes.D_IMPLAUSIBLE)
    return done(kind="answer", value=value, reason_code=codes.D_ANSWER)
