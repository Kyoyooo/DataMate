"""Run configuration (SPEC §6, P1 subset). Owner: M4.

JSON profiles may extend a shared JSON file. Unknown keys are errors;
missing keys take the defaults below. ``config_sha256`` hashes the effective
configuration (defaults filled) so run records can be compared.

Adding a key: give it a default here, document it in README "Configuration",
and merge it together with the code that reads it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _Section(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ModelConfig(_Section):
    # "scripted" is development-only and is rejected outside --dev (run.py).
    # Serving is external to the client; M4 owns server launch and health checks.
    backend: Literal["scripted", "http"] = "http"
    script_path: str | None = None  # scripted backend only
    path: str | None = None  # local model directory (production)
    base_url: str | None = None  # e.g. http://127.0.0.1:8000/v1; required for http
    served_model_name: str = Field(default="datamate", min_length=1)
    model_call_timeout_s: float = Field(default=120.0, gt=0, allow_inf_nan=False)
    schema_adapter: Literal["timeref.v1", "none"] = "timeref.v1"
    temperature: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    top_p: float = Field(default=1.0, gt=0, le=1)
    top_k: int = Field(default=-1, ge=-1)
    min_p: float = Field(default=0.0, ge=0, le=1)
    presence_penalty: float = Field(default=0.0, ge=-2, le=2)
    frequency_penalty: float = Field(default=0.0, ge=-2, le=2)
    repetition_penalty: float = Field(default=1.0, gt=0, allow_inf_nan=False)
    enable_thinking: dict[str, bool] = {"parse": False, "solve": False, "repair": False}
    seed: int = 20261116
    max_tokens: dict[str, int] = {"parse": 1024, "solve": 2048, "repair": 2048}

    @field_validator("base_url")
    @classmethod
    def _local_endpoint(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or parsed.path.rstrip("/") not in {"", "/v1"}):
            raise ValueError("model.base_url must be loopback HTTP, optionally ending in /v1")
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError("model.base_url has an invalid port")
        return value.rstrip("/")


class SolverConfig(_Section):
    max_repairs: int = Field(default=1, ge=0)


class ServingConfig(_Section):
    """Shared limits: consumed by prompt budgeting and M4's server launch adapter."""

    max_model_len: int = Field(default=8192, gt=0)
    max_num_seqs: int = Field(default=4, gt=0)
    max_num_batched_tokens: int = Field(default=8192, gt=0)
    gpu_memory_utilization: float = Field(default=0.90, gt=0, le=1)
    target_executor_gib: float = Field(default=28.8, gt=0, allow_inf_nan=False)
    dtype: str = "bfloat16"
    prefix_caching: bool = True
    chunked_prefill: bool = True
    reasoning_parser: str = "qwen3"


class PromptBudgetConfig(_Section):
    safety_margin_tokens: int = Field(default=64, ge=0)
    context_budget_tokens: int | None = Field(default=None, gt=0)  # optional input-only cap
    readme_budget_tokens: int = Field(default=512, ge=0)
    schema_card_budget_tokens: int = Field(default=3000, gt=0)
    relevant_tables: int = Field(default=4, gt=0)


class ExecLimits(_Section):
    sql_timeout_s: float = 20.0
    max_result_rows: int = 1000
    memory_limit_mb: int = 4096


class DecisionConfig(_Section):
    # Rulebook (train and public_test) §7: a period entirely outside the data's
    # date range is "unanswerable", not zero. "abstain" is the conservative switch.
    zero_coverage: Literal["unanswerable", "abstain"] = "unanswerable"


class FormattingConfig(_Section):
    rounding: Literal["ROUND_HALF_UP", "ROUND_HALF_EVEN"] = "ROUND_HALF_UP"
    money_decimals: int = 0  # money rounds to whole VND (DC-1)
    default_decimals: int = 2  # percents, averages, other measures


class LoggingConfig(_Section):
    max_output_rows_logged: int = 50


class RunConfig(_Section):
    work_dir: str = "/tmp/datamate"
    model: ModelConfig = ModelConfig()
    solver: SolverConfig = SolverConfig()
    serving: ServingConfig = ServingConfig()
    prompt_budget: PromptBudgetConfig = PromptBudgetConfig()
    exec_limits: ExecLimits = ExecLimits()
    decision: DecisionConfig = DecisionConfig()
    formatting: FormattingConfig = FormattingConfig()
    logging: LoggingConfig = LoggingConfig()

    @model_validator(mode="after")
    def _context_limits(self) -> RunConfig:
        if not {"parse", "solve", "repair"} <= self.model.max_tokens.keys():
            raise ValueError("model.max_tokens must define parse, solve and repair")
        if any(n <= 0 or n + self.prompt_budget.safety_margin_tokens >= self.serving.max_model_len
               for n in self.model.max_tokens.values()):
            raise ValueError("each output budget must leave room for prompt + safety margin")
        return self

    def input_budget(self, stage: str) -> int:
        limit = (self.serving.max_model_len - self.model.max_tokens[stage]
                 - self.prompt_budget.safety_margin_tokens)
        cap = self.prompt_budget.context_budget_tokens
        return min(limit, cap) if cap is not None else limit

    def sha256(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _apply_override(tree: dict[str, Any], dotted: str, raw: str) -> None:
    try:
        value: Any = json.loads(raw)
    except json.JSONDecodeError:
        value = raw
    keys = dotted.split(".")
    node = tree
    for k in keys[:-1]:
        node = node.setdefault(k, {})
        if not isinstance(node, dict):
            raise ValueError(f"cannot override {dotted!r}: {k!r} is not a section")
    node[keys[-1]] = value


def load_config(path: str | Path | None, overrides: list[str] | None = None) -> RunConfig:
    """Load a config file (or defaults if ``path`` is None) and apply ``key=value`` overrides."""
    tree: dict[str, Any] = {}
    if path is not None:
        tree = _read_config(Path(path), set())
    for item in overrides or []:
        if "=" not in item:
            raise ValueError(f"override must be key=value, got {item!r}")
        key, raw = item.split("=", 1)
        _apply_override(tree, key.strip(), raw)
    return RunConfig.model_validate(tree)


def _read_config(path: Path, ancestors: set[Path]) -> dict[str, Any]:
    path = path.resolve()
    if path in ancestors or len(ancestors) >= 16:
        raise ValueError("cyclic or excessively deep config extends")
    tree = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(tree, dict):
        raise ValueError("config must be a JSON object")
    parent = tree.pop("extends", None)
    if parent is None:
        return tree
    if not isinstance(parent, str) or not parent:
        raise ValueError("extends must name a config file relative to this file")
    base = _read_config(path.parent / parent, ancestors | {path})
    return _merge_config(base, tree)


def _merge_config(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge_config(result[key], value)
        else:
            result[key] = value
    return result
