"""Prompt blob store: keeps log size bounded (SPEC §8.3, TASKS M4-07). Owner: M4.

``ModelCall.transport.request_body`` repeats the whole system prompt (rulebook, README,
SchemaCard; hundreds of thousands of characters on real businesses) and the JSON schema
for every call. In ``questions.jsonl`` any message longer than ``LARGE`` characters and
the response schema are replaced by ``{"content_sha256", "content_chars"}`` /
``{"schema_sha256"}`` references; the text is written once to ``logs/prompt_blobs.jsonl``
as ``{"sha256", "text"}``. ``request_sha256`` still hashes the full original body, so
the exact request can be rebuilt (messages from blobs) and checked.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any

from datamate.contracts import ModelCall

LARGE = 512


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class PromptBlobStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(path, "w", encoding="utf-8", newline="\n")  # noqa: SIM115
        self._seen: set[str] = set()
        self._lock = threading.Lock()

    def put(self, text: str) -> str:
        sha = _sha(text)
        with self._lock:
            if sha not in self._seen:
                self._seen.add(sha)
                self._fh.write(json.dumps({"sha256": sha, "text": text}, ensure_ascii=False) + "\n")
                self._fh.flush()
        return sha

    def finalize(self) -> None:
        """Close and rewrite sorted by hash, so the file does not depend on thread timing."""
        with self._lock:
            self._fh.close()
        rows = sorted(self.path.read_text(encoding="utf-8").splitlines())
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text("".join(r + "\n" for r in rows), encoding="utf-8")
        os.replace(tmp, self.path)

    def compact(self, call: ModelCall) -> ModelCall:
        transport = call.transport
        if not transport or not isinstance(transport.get("request_body"), dict):
            return call
        body: dict[str, Any] = dict(transport["request_body"])
        messages = []
        for m in body.get("messages", []):
            content = m.get("content", "")
            if isinstance(content, str) and len(content) > LARGE:
                messages.append({"role": m.get("role"), "content_sha256": self.put(content),
                                 "content_chars": len(content)})
            else:
                messages.append(m)
        body["messages"] = messages
        rf = body.get("response_format")
        if isinstance(rf, dict) and isinstance(rf.get("json_schema"), dict) \
                and "schema" in rf["json_schema"]:
            schema_text = json.dumps(rf["json_schema"]["schema"], sort_keys=True,
                                     ensure_ascii=False, separators=(",", ":"))
            js = {k: v for k, v in rf["json_schema"].items() if k != "schema"}
            js["schema_sha256"] = self.put(schema_text)
            body["response_format"] = {**rf, "json_schema": js}
        return call.model_copy(update={"transport": {**transport, "request_body": body,
                                                     "request_compacted": True}})
