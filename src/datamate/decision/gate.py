"""Rule gate: answer, unanswerable, or abstain (SPEC §7.9, C9, P1). Owner: M2.

Scoring is +1 correct, 0 abstain, -1 wrong, and a wrong "unanswerable" costs
-1 like any wrong answer. So "unanswerable" is emitted only on positive
evidence that the data cannot support the question:

  * a resolved time window has zero overlap with the business's data range
    (rulebook §7, train and public_test: "no data" is not zero), or
  * the parser reports a missing field AND the catalog check cannot find it.

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

from datamate.config import RunConfig
from datamate.contracts import (
    BusinessCatalog,
    Decision,
    QuestionFrame,
    ScalarValue,
    SolverAttempt,
    TimeWindow,
    codes,
)
from datamate.lexicon import fold

PERCENT_PLAUSIBLE_MAX = Decimal(100_000)


def field_in_catalog(field: str, cat: BusinessCatalog) -> bool:
    """Lexical check that a field named by the parser exists somewhere in the data.

    True if every folded token of ``field`` occurs in one column's identifier or
    original header, or the folded field occurs in the folded README. This is a
    deliberately permissive check: if in doubt, the field counts as present and
    the question is NOT declared unanswerable. (Fuzzy matching: TASKS M2-07.)
    """
    tokens = fold(field).split()
    if not tokens:
        return True
    for t in cat.tables:
        for c in t.columns:
            haystack = set(fold(c.name.replace("_", " ")).split()) | set(fold(c.original_name).split())
            if all(tok in haystack for tok in tokens):
                return True
    return bool(cat.readme_text) and fold(field) in fold(cat.readme_text or "")


def pre_solve_decision(frame: QuestionFrame, windows: list[TimeWindow], cat: BusinessCatalog,
                       cfg: RunConfig) -> Decision | None:
    """Rules 2–4. A non-None result means solving is unnecessary."""
    a = frame.answerability
    if a.status == "unclear":
        return Decision(kind="abstain", reason_code=codes.D_UNCLEAR)
    if a.status == "missing_field" and a.missing_fields:
        if not any(field_in_catalog(f, cat) for f in a.missing_fields):
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


def decide(frame: QuestionFrame | None, windows: list[TimeWindow], attempts: list[SolverAttempt],
           cat: BusinessCatalog | None, cfg: RunConfig, pipeline_error: str | None) -> Decision:
    features = {
        "n_attempts": len(attempts),
        "n_repairs": sum(1 for a in attempts if a.stage == "repair"),
        "min_coverage": min((w.coverage_ratio for w in windows if w.coverage_ratio is not None),
                            default=None),
        "temporal_generic": any("F_TEMPORAL_GENERIC" in w.flags for w in windows),
    }

    def done(**kw: object) -> Decision:
        return Decision(features=features, **kw)

    if pipeline_error is not None or frame is None or cat is None:
        return done(kind="abstain", reason_code=pipeline_error or codes.E_INTERNAL)
    pre = pre_solve_decision(frame, windows, cat, cfg)
    if pre is not None:
        return done(kind=pre.kind, reason_code=pre.reason_code,
                    unanswerable_reason=pre.unanswerable_reason)
    final = next((a for a in reversed(attempts) if a.ok), None)
    if final is None or final.value is None:
        last = attempts[-1].error_code if attempts else None
        return done(kind="abstain", reason_code=last or codes.E_NO_SUCCESS)
    value = final.value
    features["row_count"] = final.execution.row_count if final.execution else None
    if value.type != frame.expected_type:
        return done(kind="abstain", reason_code=codes.E_TYPE_CONTRACT)
    if isinstance(value, ScalarValue) and value.type == "percent" \
            and abs(value.value) > PERCENT_PLAUSIBLE_MAX:
        return done(kind="abstain", reason_code=codes.D_IMPLAUSIBLE)
    return done(kind="answer", value=value, reason_code=codes.D_ANSWER)
