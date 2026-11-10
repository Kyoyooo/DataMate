"""Model access. ``make_client`` is the only place a backend is chosen."""

from __future__ import annotations

from datamate.config import ModelConfig
from datamate.llm.client import ModelClient, request_sha256
from datamate.llm.scripted import ScriptedModelClient


class ProductionGuardError(RuntimeError):
    """A development-only component was requested outside development mode."""


def make_client(cfg: ModelConfig, *, dev: bool) -> ModelClient:
    if cfg.backend == "scripted":
        if not dev:
            raise ProductionGuardError(
                "model.backend='scripted' is development-only and is rejected without --dev"
            )
        if not cfg.script_path:
            raise ValueError("model.script_path is required for the scripted backend")
        return ScriptedModelClient.from_file(cfg.script_path)
    if cfg.backend == "http":
        raise NotImplementedError(
            "HttpModelClient (vLLM OpenAI-compatible client) is not implemented yet: TASKS M3-02. "
            "Refusing to run rather than produce placeholder answers."
        )
    raise ValueError(f"unknown model backend {cfg.backend!r}")  # pragma: no cover


__all__ = ["ModelClient", "ProductionGuardError", "ScriptedModelClient", "make_client",
           "request_sha256"]
