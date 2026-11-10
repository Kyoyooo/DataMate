"""Tokenizer access for prompt budgeting (SPEC §7.13.4, TASKS M3-03). Owner: M3.

``load_tokenizer`` loads the shipped model's tokenizer from disk only
(``local_files_only=True``; no network). It returns an object with the HF-style
``encode(text, add_special_tokens=False) -> list[int]``, the interface M1's
``select_schema_context`` also expects. When ``transformers`` or the tokenizer files
are absent it returns ``None``; callers decide whether that is fatal (production) or
whether the conservative ``CharEstimateTokenizer`` is acceptable (CPU development).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Protocol


class Tokenizer(Protocol):
    name: str

    def encode(self, text: str, add_special_tokens: bool = False) -> list[int]: ...


class CharEstimateTokenizer:
    """Development estimate: ``ceil(len / chars_per_token)`` tokens. NOT a real tokenizer.

    2.5 characters per token is deliberately pessimistic for Vietnamese so that budgets
    estimated with it err on the safe side. Never used silently in production.
    """

    name = "chars-estimate"

    def __init__(self, chars_per_token: float = 2.5):
        self.chars_per_token = chars_per_token

    def encode(self, text: str, add_special_tokens: bool = False) -> list[int]:
        return [0] * math.ceil(len(text) / self.chars_per_token)


class _HFTokenizer:
    def __init__(self, tok: Any, path: str):
        self._tok, self.name = tok, f"hf:{path}"

    def encode(self, text: str, add_special_tokens: bool = False) -> list[int]:
        return list(self._tok.encode(text, add_special_tokens=add_special_tokens))


def load_tokenizer(model_path: str | None) -> Tokenizer | None:
    if not model_path or not Path(model_path).is_dir():
        return None
    try:
        from transformers import AutoTokenizer  # type: ignore[import-not-found]

        return _HFTokenizer(AutoTokenizer.from_pretrained(model_path, local_files_only=True),
                            model_path)
    except Exception:  # missing library or files: the caller decides
        return None


def count_tokens(tok: Tokenizer, text: str) -> int:
    return len(tok.encode(text, add_special_tokens=False))
