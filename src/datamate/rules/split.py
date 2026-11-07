"""Split bootstrap (SPEC §7.1, P1 subset). Owner: M2.

Reads the active split's ``rulebook.md`` verbatim and notes whether
``calendar.csv`` exists. Temporal parameters are the generic defaults of
``TemporalParams`` and are marked ``source="generic"``.

Deferred: extracting TemporalParams from the rulebook with a model call and
span validation (TASKS M2-05); calendar parsing and validation (M2-02);
RuleProfile (M2-08). Nothing here may encode a training-rulebook value.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from datamate.contracts import SplitContext, TemporalParams
from datamate.lexicon import nfc


def load_split(data_dir: Path) -> SplitContext:
    warnings: list[str] = []
    rulebook_path = data_dir / "rulebook.md"
    try:
        rulebook = nfc(rulebook_path.read_bytes().decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError):
        rulebook = ""
        warnings.append("W_RULEBOOK_MISSING")
    calendar = data_dir / "calendar.csv"
    if not calendar.is_file():
        warnings.append("W_CALENDAR_MISSING")
    return SplitContext(
        rulebook_text=rulebook,
        rulebook_sha256=hashlib.sha256(rulebook.encode("utf-8")).hexdigest(),
        temporal=TemporalParams(),
        calendar_path=str(calendar) if calendar.is_file() else None,
        warnings=warnings,
    )
