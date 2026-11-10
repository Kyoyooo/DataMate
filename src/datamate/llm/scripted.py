"""ScriptedModelClient — DEVELOPMENT AND TESTS ONLY. Owner: M3.

Returns pre-written responses so the whole pipeline runs on CPU without a
model. It is rejected outside ``--dev`` (see ``make_client``). Responses are
matched on (stage, question text found in the user messages), never on a
question or business id. Repeated calls for the same key return the scripted
responses in order; when they run out, the call fails with E_SCRIPT_MISS.

Script file: JSONL, one object per response:
  {"stage": "parse"|"solve"|"repair", "question": "<exact question text>",
   "content": "<exact model output>", "reasoning": null}
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from datamate.contracts import ModelCall, Stage, codes
from datamate.llm.client import request_sha256


class ScriptedModelClient:
    backend = "scripted"
    dev_only = True

    def __init__(self, entries: list[dict[str, Any]]):
        self._responses: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for e in entries:
            self._responses[(e["stage"], e["question"])].append(e)
        self._cursor: dict[tuple[str, str], int] = defaultdict(int)

    @classmethod
    def from_file(cls, path: str | Path) -> ScriptedModelClient:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        return cls([json.loads(line) for line in lines if line.strip()])

    def _match(self, stage: str, user_text: str) -> tuple[str, str] | None:
        keys = [k for k in self._responses if k[0] == stage and k[1] in user_text]
        return max(keys, key=lambda k: len(k[1])) if keys else None

    def complete(self, *, stage: Stage, template_id: str, messages: list[dict[str, str]],
                 json_schema: dict[str, Any] | None, max_tokens: int,
                 call_id: str) -> ModelCall:
        params = {"max_tokens": max_tokens, "temperature": 0.0}
        user_text = "\n".join(m["content"] for m in messages if m["role"] == "user")
        key = self._match(stage, user_text)
        entry = None
        if key is not None and self._cursor[key] < len(self._responses[key]):
            entry = self._responses[key][self._cursor[key]]
            self._cursor[key] += 1
        return ModelCall(
            call_id=call_id,
            stage=stage,
            template_id=template_id,
            backend=self.backend,
            request_sha256=request_sha256(messages, params, json_schema),
            params=params,
            content=entry["content"] if entry else "",
            reasoning=entry.get("reasoning") if entry else None,
            finish_reason="stop" if entry else "error",
            latency_ms=0,
            error=None if entry else codes.E_SCRIPT_MISS,
        )
