"""Local CPU token counting, loaded lazily without model weights or network calls."""

from __future__ import annotations

import hashlib
import json
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from datamate.config import RunConfig


class TokenCounter(Protocol):
    @property
    def fingerprint(self) -> dict[str, Any]: ...

    def count_text(self, text: str) -> int: ...

    def count_messages(self, messages: list[dict[str, str]], *, thinking: bool) -> int: ...


class DevelopmentTokenCounter:
    """CPU fixture stand-in, NOT a model tokenizer; selected only for scripted config."""

    fingerprint = {"mode": "development_utf8_bytes_not_model_tokens"}

    def count_text(self, text: str) -> int:
        return len(text.encode("utf-8"))

    def count_messages(self, messages: list[dict[str, str]], *, thinking: bool) -> int:
        return sum(self.count_text(m["content"]) + len(m["role"]) + 8 for m in messages) + 8


class LocalTokenCounter:
    def __init__(self, path: str):
        root = Path(path).resolve()
        if not root.is_dir():
            raise ValueError("model.path must be a local tokenizer snapshot directory")
        try:
            from transformers import AutoTokenizer
        except ImportError as exc:
            raise ValueError("install the tokenizer extra or use M4's serving environment") from exc
        self._tokenizer = AutoTokenizer.from_pretrained(str(root), local_files_only=True,
                                                       trust_remote_code=False)
        if not self._tokenizer.chat_template:
            raise ValueError("local tokenizer has no chat template")
        files = sorted({p for pattern in ("tokenizer*", "vocab*", "merges*", "special_tokens*",
                                          "*.jinja", "*.jinja2")
                        for p in root.glob(pattern) if p.is_file()})
        digest = hashlib.sha256()
        for file in files:
            digest.update(file.name.encode("utf-8") + b"\0" + file.read_bytes())
        template = json.dumps(self._tokenizer.chat_template, sort_keys=True, ensure_ascii=False)
        self._fingerprint = {"mode": "local_tokenizer", "path": str(root),
                             "files_sha256": digest.hexdigest(),
                             "chat_template_sha256": hashlib.sha256(template.encode()).hexdigest()}
        self._lock = threading.Lock()
        try:
            self.count_messages([{"role": "user", "content": "tokenizer readiness check"}], thinking=False)
        except (ImportError, ValueError) as exc:
            raise ValueError("local chat-template counting failed; install the tokenizer extra") from exc

    @property
    def fingerprint(self) -> dict[str, Any]:
        return dict(self._fingerprint)

    def count_text(self, text: str) -> int:
        with self._lock:
            return len(self._tokenizer.encode(text, add_special_tokens=False))

    def count_messages(self, messages: list[dict[str, str]], *, thinking: bool) -> int:
        with self._lock:
            return len(self._tokenizer.apply_chat_template(
                messages, tokenize=True, add_generation_prompt=True, enable_thinking=thinking))


@lru_cache(maxsize=4)
def _local_counter(path: str) -> LocalTokenCounter:
    return LocalTokenCounter(path)


_COUNTER_LOCK = threading.Lock()


def get_token_counter(cfg: RunConfig) -> TokenCounter:
    if cfg.model.backend == "scripted":
        return DevelopmentTokenCounter()
    if not cfg.model.path:
        raise ValueError("model.path is required for offline prompt token counting (M3-03)")
    with _COUNTER_LOCK:
        return _local_counter(str(Path(cfg.model.path).resolve()))
