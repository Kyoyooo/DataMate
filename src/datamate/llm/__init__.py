"""Model access. ``make_client`` is the only place a backend is chosen."""

from __future__ import annotations

from datamate.config import ModelConfig
from datamate.llm.client import ModelClient, request_sha256
from datamate.llm.http import HttpModelClient, http_request_sha256
from datamate.llm.schema import SCHEMA_ADAPTER_VERSION, schema_for_vllm
from datamate.llm.scripted import ScriptedModelClient
from datamate.llm.server_config import server_arguments
from datamate.llm.tokenizer import (
    DevelopmentTokenCounter,
    LocalTokenCounter,
    TokenCounter,
    get_token_counter,
)


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
        return HttpModelClient(cfg)
    raise ValueError(f"unknown model backend {cfg.backend!r}")  # pragma: no cover


__all__ = ["HttpModelClient", "ModelClient", "ProductionGuardError", "SCHEMA_ADAPTER_VERSION",
           "ScriptedModelClient", "http_request_sha256", "make_client", "request_sha256",
           "schema_for_vllm", "DevelopmentTokenCounter", "LocalTokenCounter", "TokenCounter",
           "get_token_counter", "server_arguments"]
