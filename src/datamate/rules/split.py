"""Split bootstrap (SPEC §7.1, P1 subset). Owner: M2.

Reads the active split's ``rulebook.md`` verbatim and validates its lunar
calendar. Temporal parameters use generic defaults and empty ``provenance``.

Deferred: extracting TemporalParams from the rulebook with a model call and
span validation (TASKS M2-05);
RuleProfile (M2-08). Nothing here may encode a training-rulebook value.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from datamate.contracts import CalendarDiagnostic, SplitContext, TemporalParams, codes
from datamate.lexicon import nfc
from datamate.temporal import CalendarValidationError, LunarCalendar


def load_split(data_dir: Path) -> SplitContext:
    warnings: list[str] = []
    rulebook_path = data_dir / "rulebook.md"
    try:
        rulebook = nfc(rulebook_path.read_bytes().decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError):
        rulebook = ""
        warnings.append(codes.W_RULEBOOK_MISSING)
    calendar = data_dir / "calendar.csv"
    calendar_path: str | None = str(calendar)
    diagnostic = None
    try:
        LunarCalendar.from_csv(calendar)
    except FileNotFoundError:
        calendar_path = None
        warnings.append(codes.W_CALENDAR_MISSING)
        diagnostic = CalendarDiagnostic(code="missing_file", message="calendar.csv was not found")
    except CalendarValidationError as exc:
        warnings.append(codes.W_CALENDAR_INVALID)
        diagnostic = CalendarDiagnostic(code=exc.code, row=exc.row, message=str(exc))
    return SplitContext(
        rulebook_text=rulebook,
        rulebook_sha256=hashlib.sha256(rulebook.encode("utf-8")).hexdigest(),
        temporal=TemporalParams(),
        calendar_path=calendar_path,
        calendar_ok=diagnostic is None,
        calendar_diagnostic=diagnostic,
        warnings=warnings,
    )
