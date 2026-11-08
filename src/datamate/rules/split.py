"""Split bootstrap (SPEC §7.1, P1 subset). Owner: M2.

Reads the active split's rulebook, validates its lunar calendar, and optionally
verifies one model-produced temporal profile. The caller must opt into model
extraction while the H7 stage and real HTTP integration are under review.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from datamate.contracts import CalendarDiagnostic, ModelCall, SplitContext, TemporalParams, codes
from datamate.lexicon import nfc
from datamate.llm import ModelClient
from datamate.prompts import RULES_TEMPORAL_ID, render_temporal_profile
from datamate.rules.temporal_params import temporal_candidate_schema, validate_temporal_params
from datamate.temporal import CalendarValidationError, LunarCalendar


def load_split(data_dir: Path, *, client: ModelClient | None = None,
               max_tokens: int | None = None) -> SplitContext:
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

    temporal = TemporalParams()
    calls: list[ModelCall] = []
    temporal_diagnostics: dict[str, str] = {}
    if not rulebook.strip():
        temporal_diagnostics["profile"] = "empty_rulebook"
    elif client is not None:
        call = client.complete(
            stage="rule_profile", template_id=RULES_TEMPORAL_ID, messages=render_temporal_profile(rulebook),
            json_schema=temporal_candidate_schema(), max_tokens=2048 if max_tokens is None else max_tokens,
            call_id="split:rule_profile:1",
        )
        calls.append(call)
        if call.error:
            temporal_diagnostics["profile"] = "model_error"
        elif call.stage != "rule_profile" or call.template_id != RULES_TEMPORAL_ID:
            temporal_diagnostics["profile"] = "unexpected_call"
        else:
            temporal, temporal_diagnostics = validate_temporal_params(rulebook, call.content)
    return SplitContext(
        rulebook_text=rulebook,
        rulebook_sha256=hashlib.sha256(rulebook.encode("utf-8")).hexdigest(),
        temporal=temporal,
        calendar_path=calendar_path,
        calendar_ok=diagnostic is None,
        calendar_diagnostic=diagnostic,
        rule_profile_calls=calls,
        temporal_diagnostics=temporal_diagnostics,
        warnings=warnings,
    )
