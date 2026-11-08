"""Text normalization helpers (SPEC §7.6.1). Owner: M1.

``fold`` removes diacritics. It is ONLY for retrieval keys, SQL identifiers and
keyword matching. Never apply it to answers, data values, or scorer input.
Its behavior is a shared surface (SPEC §15.2): tell its consumers before changing it.
"""

from __future__ import annotations

import re
import unicodedata

_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def fold(text: str) -> str:
    """NFD → drop combining marks → đ/Đ→d → lowercase → non-alphanumerics to space → collapse."""
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    stripped = stripped.replace("đ", "d").replace("Đ", "D").lower()
    return " ".join(_NON_ALNUM.sub(" ", stripped).split())


def to_identifier(text: str) -> str:
    """SQL identifier from a header: folded, '_'-joined, prefixed if it starts with a digit."""
    ident = fold(text).replace(" ", "_") or "col"
    if ident[0].isdigit():
        ident = "c_" + ident
    return ident
