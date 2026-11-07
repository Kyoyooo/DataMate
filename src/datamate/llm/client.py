"""Model client interface (SPEC §5.10, §7.13.2). Owner: M3.

One small protocol. Every implementation must:
- return a ``ModelCall`` for every call, with errors as ``ModelCall.error``
  (never raise for model/transport failures);
- capture ``content`` and ``reasoning`` byte-for-byte as returned;
- send every decoding parameter explicitly and echo it in ``ModelCall.params``.

Calls are synchronous. Concurrency (one thread per in-flight question) is the
orchestrator's job (TASKS M4-05); see SPEC §18 DC-5.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol

from datamate.contracts import ModelCall, Stage


class ModelClient(Protocol):
    backend: str
    dev_only: bool

    def complete(self, *, stage: Stage, template_id: str, messages: list[dict[str, str]],
                 json_schema: dict[str, Any] | None, max_tokens: int,
                 call_id: str) -> ModelCall: ...


def request_sha256(messages: list[dict[str, str]], params: dict[str, Any],
                   json_schema: dict[str, Any] | None) -> str:
    body = {"messages": messages, "params": params, "json_schema": json_schema}
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
