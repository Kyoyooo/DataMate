"""Model access. ``make_client`` is the only place a backend is chosen."""

from __future__ import annotations

from datamate.config import ModelConfig
from datamate.llm.client import ModelClient, request_sha256
from datamate.llm.deadline import NO_DEADLINE, Deadline, DeadlineExceeded
from datamate.llm.http import HttpModelClient, http_request_sha256
from datamate.llm.replay import RecordingModelClient, ReplayModelClient, call_key
from datamate.llm.schema import SCHEMA_ADAPTER_VERSION, schema_for_vllm
from datamate.llm.scripted import ScriptedModelClient


class ProductionGuardError(RuntimeError):
    """A development-only component was requested outside development mode."""


def make_client(cfg: ModelConfig, *, dev: bool) -> ModelClient:
    if (cfg.backend in ("scripted", "replay") or cfg.record_path) and not dev:
        what = "model.record_path" if cfg.backend == "http" else f"model.backend={cfg.backend!r}"
        raise ProductionGuardError(f"{what} is development-only and is rejected without --dev")
    client: ModelClient
    if cfg.backend == "scripted":
        if not cfg.script_path:
            raise ValueError("model.script_path is required for the scripted backend")
        client = ScriptedModelClient.from_file(cfg.script_path)
    elif cfg.backend == "replay":
        if not cfg.replay_path:
            raise ValueError("model.replay_path is required for the replay backend")
        client = ReplayModelClient.from_file(cfg.replay_path, cfg)
    elif cfg.backend == "http":
        client = HttpModelClient(cfg)
    else:
        raise ValueError(f"unknown model backend {cfg.backend!r}")  # pragma: no cover
    if cfg.record_path:
        client = RecordingModelClient(client, cfg.record_path, cfg,
                                     source=f"recorded through backend={cfg.backend!r}")
    return client


__all__ = ["Deadline", "DeadlineExceeded", "HttpModelClient", "ModelClient", "NO_DEADLINE",
           "ProductionGuardError", "RecordingModelClient", "ReplayModelClient",
           "SCHEMA_ADAPTER_VERSION", "ScriptedModelClient", "call_key",
           "http_request_sha256", "make_client", "request_sha256", "schema_for_vllm"]
