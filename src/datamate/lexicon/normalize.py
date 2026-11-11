"""Whole-token alias expansion for question context; original wording stays authoritative."""

from __future__ import annotations

import csv
import re
from functools import lru_cache
from importlib.resources import files

from datamate.lexicon.fold import fold, nfc


@lru_cache(maxsize=1)
def load_abbreviations() -> dict[str, str]:
    path = files("datamate.lexicon").joinpath("abbrev_vi.tsv")
    rows = csv.reader(
        (
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ),
        delimiter="\t",
    )
    aliases = {}
    for alias, expansion, _ in rows:
        key = fold(alias)
        if key in aliases:
            raise ValueError(f"Duplicate lexicon alias: {alias}")
        aliases[key] = nfc(expansion)
    return aliases


def normalize_question(text: str, aliases: dict[str, str] | None = None) -> str:
    mappings = load_abbreviations() if aliases is None else aliases
    normalized = re.sub(
        r"(?<!\w)[^\W\d_]+(?!\w)",
        lambda match: mappings.get(fold(match.group()), match.group()),
        nfc(text),
    )
    return " ".join(normalized.split())


def abbreviation_hints(text: str) -> list[dict]:
    tokens = {fold(m.group()) for m in re.finditer(r"(?<!\w)[^\W\d_]+(?!\w)", nfc(text))}
    result = []
    path = files("datamate.lexicon").joinpath("context_vi.tsv")
    for row in csv.reader(
        (
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#")
        ),
        delimiter="\t",
    ):
        token, interpretations, reason = row
        if token in tokens:
            result.append(
                {
                    "token": token,
                    "candidates": interpretations.split("|"),
                    "reason": reason,
                    "automatic_substitution": False,
                }
            )
    return result
