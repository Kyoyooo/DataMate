"""Decision → submission wire value (SPEC §7.10, C10). Owner: M2.

Rounding (DC-1; Brief §2.1; rulebook §9 of train and public_test):
  * money (numeric_kind "money")  → ``formatting.money_decimals`` (0: whole VND)
  * percent and everything else   → ``formatting.default_decimals`` (2)
  * mode ``formatting.rounding`` (ROUND_HALF_UP: "nửa đồng làm tròn lên")
Integral results are written as JSON integers; others as exact decimal literals.

Lists (DC-2):
  * ranked          → sort by sort_key (desc for top, asc for bottom), ties by
                      tie_code ascending (numeric if all codes are digits), then
                      item; truncate to k (all if fewer than k).
  * question_order  → keep the question's order (by ``position``); never re-sorted.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal
from typing import Any

from datamate.config import FormattingConfig
from datamate.contracts import (
    DateValue,
    Decision,
    ListItem,
    ListValue,
    RankingSpec,
    ScalarValue,
    SubmissionRecord,
    TableValue,
)

_MODES = {"ROUND_HALF_UP": ROUND_HALF_UP, "ROUND_HALF_EVEN": ROUND_HALF_EVEN}


def round_number(value: Decimal, numeric_kind: str | None, cfg: FormattingConfig,
                 *, is_percent: bool = False) -> int | Decimal:
    if not value.is_finite():
        raise ValueError(f"cannot format non-finite number {value}")
    places = cfg.money_decimals if (numeric_kind == "money" and not is_percent) \
        else cfg.default_decimals
    q = value.quantize(Decimal(1).scaleb(-places), rounding=_MODES[cfg.rounding])
    if q == q.to_integral_value():
        return int(q)  # also turns -0 into 0
    return q.normalize()


def _wire_scalar(v: Decimal | str, numeric_kind: str | None, cfg: FormattingConfig) -> Any:
    if isinstance(v, Decimal):
        return round_number(v, numeric_kind, cfg)
    return v.strip()


def _tie_key(items: list[ListItem]) -> Any:
    codes_ = [i.tie_code for i in items if i.tie_code is not None]
    numeric = bool(codes_) and all(c.isdigit() for c in codes_)

    def key(i: ListItem) -> tuple:
        if i.tie_code is None:
            return (1, 0, "")
        return (0, int(i.tie_code), "") if numeric else (0, 0, i.tie_code)

    return key


def order_ranked(items: list[ListItem], ranking: RankingSpec) -> list[ListItem]:
    """Deterministic ranking order (Brief §2.2): criterion, then code ascending, then item."""
    keys = [i.sort_key for i in items if i.sort_key is not None]
    if keys and len({type(k) for k in keys}) > 1:
        raise ValueError("mixed sort_key types in ranked list")
    tie = _tie_key(items)
    # Stable two-pass sort: secondary order first, then the criterion. Python's
    # sort is stable even with reverse=True, so ties keep code-ascending order.
    by_tie = sorted(items, key=lambda i: (tie(i), str(i.item)))
    keyed = sorted((i for i in by_tie if i.sort_key is not None), key=lambda i: i.sort_key,
                   reverse=ranking.direction == "top")
    ordered = keyed + [i for i in by_tie if i.sort_key is None]
    return ordered if ranking.k is None else ordered[: ranking.k]


def to_submission(question_id: str, d: Decision, ranking: RankingSpec | None,
                  cfg: FormattingConfig) -> SubmissionRecord:
    if d.kind == "abstain":
        return SubmissionRecord(id=question_id, type="abstain")
    if d.kind == "unanswerable":
        return SubmissionRecord(id=question_id, type="unanswerable", reason=d.unanswerable_reason)
    v = d.value
    if isinstance(v, ScalarValue):
        if v.type in ("number", "percent"):
            ans: Any = round_number(v.value, v.numeric_kind, cfg, is_percent=v.type == "percent")
        elif v.type == "string":
            ans = v.value.strip()
        else:
            ans = v.value
        return SubmissionRecord(id=question_id, type=v.type, answer=ans)
    if isinstance(v, DateValue):
        text = v.value.isoformat()
        return SubmissionRecord(id=question_id, type="date",
                                answer=text[:7] if v.granularity == "month" else text)
    if isinstance(v, ListValue):
        if v.order == "ranked":
            if ranking is None:
                raise ValueError("ranked list without a RankingSpec")
            items = order_ranked(v.items, ranking)
        else:
            positions = [i.position for i in v.items]
            if None in positions or len(set(positions)) != len(positions):
                raise ValueError("question_order list needs unique positions")
            items = sorted(v.items, key=lambda i: i.position)
        return SubmissionRecord(id=question_id, type="list",
                                answer=[_wire_scalar(i.item, v.numeric_kind, cfg) for i in items])
    if isinstance(v, TableValue):
        rows = [[None if c is None else _wire_scalar(c, v.numeric_kind, cfg) for c in r]
                for r in v.rows]
        return SubmissionRecord(id=question_id, type="table",
                                answer={"columns": list(v.columns), "rows": rows})
    raise ValueError(f"cannot format value {v!r}")  # pragma: no cover
