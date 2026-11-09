"""Local scorer (Brief §2.1–2.3, C14). Owner: Lead. Not imported by the inference path.

Implements the published matching rules independently of ``formatting/`` so it
can serve as an oracle. Usage:

    python -m datamate.eval.score --pred out/submission.jsonl --answers answers.jsonl

Assumptions where the Brief is not explicit (TASKS L-11 verifies them):
- number: exact, with a 1e-9 tolerance standing in for "ignore floating-point error".
- percent: both sides rounded to 2 decimals (half-up), then compared exactly.
- boolean: JSON true/false only (1/0 or "có" are wrong, per rulebook §9).
- list aliases: ``alias`` is a list (per position) of accepted alternate forms.
- table aliases: ``alias`` is a list (per reference row) of alternate forms of
  the row's name cell (first column).
"""

from __future__ import annotations

import argparse
import re
import unicodedata
from collections import Counter
from decimal import ROUND_HALF_UP, Context, Decimal
from pathlib import Path
from typing import Any

from datamate.contracts import loads_exact

_NON_WORD = re.compile(r"[^\w\s]|_", re.UNICODE)
_TOL = Decimal("1e-9")


def normalize_string(s: str) -> str:
    """Brief §2.1: NFC, lowercase, non-letter/digit/space → space, collapse. Keeps diacritics."""
    s = unicodedata.normalize("NFC", s).lower()
    s = "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in s)
    return " ".join(s.split())


def _num(x: Any) -> Decimal | None:
    if isinstance(x, bool) or not isinstance(x, (int, float, Decimal)):
        return None
    number = Decimal(str(x)) if isinstance(x, float) else Decimal(x)
    return number if number.is_finite() else None


def number_equal(pred: Any, ref: Any) -> bool:
    p, r = _num(pred), _num(ref)
    return p is not None and r is not None and abs(p - r) <= _TOL


def percent_equal(pred: Any, ref: Any) -> bool:
    p, r = _num(pred), _num(ref)
    if p is None or r is None:
        return False
    q = Decimal("0.01")
    context = Context(prec=max(4, p.adjusted() + 4, r.adjusted() + 4), rounding=ROUND_HALF_UP)
    return p.quantize(q, context=context) == r.quantize(q, context=context)


def string_equal(pred: Any, ref: Any, aliases: list[Any] | None = None) -> bool:
    if not isinstance(pred, str):
        return False
    forms = [ref] + [a for a in (aliases or []) if isinstance(a, str)]
    p = normalize_string(pred)
    return any(isinstance(f, str) and p == normalize_string(f) for f in forms)


def element_equal(pred: Any, ref: Any, aliases: list[Any] | None = None) -> bool:
    if isinstance(ref, str):
        return string_equal(pred, ref, aliases)
    return number_equal(pred, ref)


def _match_table_rows(candidates: list[list[int]]) -> bool:
    """Find a one-to-one row match, allowing earlier matches to move when aliases overlap."""
    by_ref: dict[int, int] = {}
    by_pred: dict[int, int] = {}
    for ref_index in range(len(candidates)):
        pending = [ref_index]
        predecessors: dict[int, int] = {}
        free = None
        while pending and free is None:
            row = pending.pop()
            for pred_index in candidates[row]:
                if pred_index in predecessors:
                    continue
                predecessors[pred_index] = row
                if pred_index not in by_pred:
                    free = pred_index
                    break
                pending.append(by_pred[pred_index])
        if free is None:
            return False
        while free is not None:
            row = predecessors[free]
            previous = by_ref.get(row)
            by_ref[row] = free
            by_pred[free] = row
            free = previous
    return True


def _table_equal(pred: Any, ref: dict[str, Any], aliases: list[Any]) -> bool:
    if not isinstance(pred, dict) or pred.keys() != {"columns", "rows"} \
            or not isinstance(pred["columns"], list) or not isinstance(pred["rows"], list):
        return False
    rcols, pcols = ref["columns"], pred["columns"]
    if len(rcols) != len(pcols) or any(not isinstance(c, str) for c in pcols):
        return False
    norm_p = [normalize_string(c) for c in pcols]
    norm_r = [normalize_string(str(c)) for c in rcols]
    if sorted(norm_p) == sorted(norm_r) and len(set(norm_r)) == len(norm_r):
        perm = [norm_p.index(c) for c in norm_r]  # match columns by name
    else:
        perm = list(range(len(rcols)))  # fall back to position
    prows = [r for r in pred["rows"] if isinstance(r, list) and len(r) == len(rcols)]
    if len(prows) != len(pred["rows"]) or len(prows) != len(ref["rows"]):
        return False
    prows = [[r[j] for j in perm] for r in prows]
    candidates = []
    for ri, rrow in enumerate(ref["rows"]):
        row_alias = aliases[ri] if ri < len(aliases) and isinstance(aliases[ri], list) else []
        candidates.append([
            pi for pi, prow in enumerate(prows)
            if all(prow[c] is None if rrow[c] is None
                   else element_equal(prow[c], rrow[c], row_alias if c == 0 else None)
                   for c in range(len(rrow)))
        ])
    return _match_table_rows(candidates)


def score_one(pred: dict[str, Any] | None, ref: dict[str, Any]) -> int:
    """+1 correct, 0 abstain or missing, -1 wrong."""
    if pred is None or pred.get("type") in (None, "abstain"):
        return 0
    rtype, ptype = ref["type"], pred["type"]
    if ptype != rtype:
        return -1
    if rtype == "unanswerable":
        return 1 if pred.get("answer") is None else -1
    p, r = pred.get("answer"), ref.get("answer")
    aliases = ref.get("alias") or []
    if rtype == "number":
        ok = number_equal(p, r)
    elif rtype == "percent":
        ok = percent_equal(p, r)
    elif rtype == "string":
        ok = string_equal(p, r, aliases)
    elif rtype in ("date",):
        ok = isinstance(p, str) and p == r
    elif rtype == "boolean":
        ok = isinstance(p, bool) and p is r
    elif rtype == "list":
        ok = isinstance(p, list) and len(p) == len(r) and all(
            element_equal(pe, re_, aliases[i] if i < len(aliases) else None)
            for i, (pe, re_) in enumerate(zip(p, r, strict=True)))
    elif rtype == "table":
        ok = _table_equal(p, r, aliases)
    else:
        ok = False
    return 1 if ok else -1


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [loads_exact(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def score_files(pred_path: Path, answers_path: Path) -> dict[str, Any]:
    preds: dict[str, dict[str, Any]] = {}
    for rec in _read_jsonl(pred_path):
        preds.setdefault(rec["id"], rec)  # first line per id counts
    refs = _read_jsonl(answers_path)
    per_type: dict[str, Counter[int]] = {}
    total = Counter[int]()
    per_id: dict[str, int] = {}
    for ref in refs:
        s = score_one(preds.get(ref["id"]), ref)
        per_id[ref["id"]] = s
        total[s] += 1
        per_type.setdefault(ref["type"], Counter())[s] += 1
    n = len(refs)
    return {
        "n": n,
        "pa": (total[1] - total[-1]) / n if n else 0.0,
        "correct": total[1], "wrong": total[-1], "abstain": total[0],
        "by_type": {t: {"correct": c[1], "wrong": c[-1], "abstain": c[0]}
                    for t, c in sorted(per_type.items())},
        "per_id": per_id,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m datamate.eval.score")
    ap.add_argument("--pred", type=Path, required=True)
    ap.add_argument("--answers", type=Path, required=True)
    args = ap.parse_args(argv)
    res = score_files(args.pred, args.answers)
    print(f"PA = {res['pa']:.4f}  (n={res['n']}, correct={res['correct']}, "
          f"wrong={res['wrong']}, abstain={res['abstain']})")
    for t, c in res["by_type"].items():
        print(f"  {t:13s} correct={c['correct']:4d} wrong={c['wrong']:4d} abstain={c['abstain']:4d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
