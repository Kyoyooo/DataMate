"""Recorded model calls and replay (SPEC §5.10, TASKS M3-13). Owner: M3.

``RecordingModelClient`` wraps any client and appends every call to a JSONL file;
``ReplayModelClient`` answers from that file with no model and no network, so CI can
run the whole pipeline on real recorded outputs.

Both key a call by ``request_sha256`` = SHA-256 of the canonical HTTP request body that
``HttpModelClient`` would send for the active ``model.*`` config (messages, sampling
parameters, schema, max_tokens, thinking switch). So a prompt-template change, a
decoding-parameter change or a schema change gives a different key and the replay
returns ``E_REPLAY_MISS`` instead of a stale answer. Re-record in the same change.

File format ``datamate.model_calls.v1`` (one JSON object per line, UTF-8):
  line 1:  {"format", "contracts_version", "source", "model_config"}
  then:    {"request_sha256", "call": <ModelCall without transport bodies>}
The first record for a hash wins; a later record with the same hash but different
content (non-determinism of the recording backend) is counted in ``conflicts`` and not
stored. Replayed calls carry ``backend="replay"``; the recorded backend is kept in
``transport.recorded_backend``. Replay is development/CI only (rejected without ``--dev``).
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

from datamate.config import ModelConfig
from datamate.contracts import CONTRACTS_VERSION, ModelCall, Stage, codes
from datamate.llm.client import ModelClient
from datamate.llm.http import build_request_body

FORMAT = "datamate.model_calls.v1"
_DROP = {"path", "base_url", "script_path", "record_path", "replay_path"}


def call_key(cfg: ModelConfig, *, stage: Stage, template_id: str, messages: list[dict[str, str]],
             json_schema: dict[str, Any] | None, max_tokens: int) -> str:
    body = build_request_body(cfg, stage=stage, template_id=template_id, messages=messages,
                              json_schema=json_schema, max_tokens=max_tokens)
    data = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _slim(call: ModelCall) -> dict[str, Any]:
    d = call.model_dump(mode="json")
    t = d.get("transport") or {}
    d["transport"] = {k: t[k] for k in ("http_status", "attempts", "error_detail") if k in t} or None
    return d


class RecordingModelClient:
    """Pass-through wrapper; appends each call to ``path``. Thread-safe."""

    dev_only = True

    def __init__(self, inner: ModelClient, path: str | Path, cfg: ModelConfig, source: str = ""):
        self.inner, self.cfg, self.path = inner, cfg, Path(path)
        self.backend = inner.backend
        self.conflicts = 0
        self._seen: dict[str, str] = {}
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        header = {"format": FORMAT, "contracts_version": CONTRACTS_VERSION, "source": source,
                  "model_config": {k: v for k, v in cfg.model_dump(mode="json").items()
                                   if k not in _DROP}}
        self._fh = open(self.path, "w", encoding="utf-8", newline="\n")  # noqa: SIM115
        self._fh.write(json.dumps(header, ensure_ascii=False, sort_keys=True) + "\n")
        self._fh.flush()

    def complete(self, *, stage: Stage, template_id: str, messages: list[dict[str, str]],
                 json_schema: dict[str, Any] | None, max_tokens: int, call_id: str,
                 timeout_s: float | None = None) -> ModelCall:
        call = self.inner.complete(stage=stage, template_id=template_id, messages=messages,
                                   json_schema=json_schema, max_tokens=max_tokens,
                                   call_id=call_id, timeout_s=timeout_s)
        key = call_key(self.cfg, stage=stage, template_id=template_id, messages=messages,
                       json_schema=json_schema, max_tokens=max_tokens)
        with self._lock:
            if key in self._seen:
                if self._seen[key] != call.content:
                    self.conflicts += 1
                return call
            self._seen[key] = call.content
            self._fh.write(json.dumps({"request_sha256": key, "call": _slim(call)},
                                      ensure_ascii=False, sort_keys=True) + "\n")
            self._fh.flush()
        return call

    def close(self) -> None:
        with self._lock:
            self._fh.close()


class ReplayModelClient:
    backend = "replay"
    dev_only = True

    def __init__(self, cfg: ModelConfig, recorded: dict[str, dict[str, Any]], source: str = ""):
        self.cfg, self._recorded, self.source = cfg, recorded, source
        self.misses: list[str] = []

    @classmethod
    def from_file(cls, path: str | Path, cfg: ModelConfig) -> ReplayModelClient:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        header = json.loads(lines[0])
        if header.get("format") != FORMAT:
            raise ValueError(f"{path}: not a {FORMAT} file")
        recorded: dict[str, dict[str, Any]] = {}
        for line in lines[1:]:
            if line.strip():
                row = json.loads(line)
                recorded.setdefault(row["request_sha256"], row["call"])
        return cls(cfg, recorded, header.get("source", ""))

    def complete(self, *, stage: Stage, template_id: str, messages: list[dict[str, str]],
                 json_schema: dict[str, Any] | None, max_tokens: int, call_id: str,
                 timeout_s: float | None = None) -> ModelCall:
        key = call_key(self.cfg, stage=stage, template_id=template_id, messages=messages,
                       json_schema=json_schema, max_tokens=max_tokens)
        rec = self._recorded.get(key)
        if rec is None:
            self.misses.append(key)
            return ModelCall(call_id=call_id, stage=stage, template_id=template_id,
                             backend=self.backend, request_sha256=key, params={}, content="",
                             reasoning=None, finish_reason="error", latency_ms=0,
                             error=codes.E_REPLAY_MISS)
        transport = dict(rec.get("transport") or {})
        transport["recorded_backend"] = rec["backend"]
        transport["recorded_call_id"] = rec["call_id"]
        return ModelCall.model_validate({**rec, "call_id": call_id, "backend": self.backend,
                                         "request_sha256": key, "transport": transport})
