"""Run configuration (SPEC §6, P1 subset). Owner: M4.

One JSON file is the only source of tunable values. Unknown keys are errors;
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

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Section(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ModelConfig(_Section):
    # "scripted" is development-only and is rejected outside --dev (run.py).
    # "http" is the production client (TASKS M3-02); it is not implemented yet.
    backend: Literal["scripted", "http"] = "http"
    script_path: str | None = None  # scripted backend only
    path: str | None = None  # local model directory (production)
    temperature: float = 0.0
    seed: int = 20261116
    max_tokens: dict[str, int] = {"parse": 1024, "solve": 2048, "repair": 2048, "compile": 4096}


class SolverConfig(_Section):
    max_repairs: int = Field(default=1, ge=0)
    schema_card_budget_tokens: int = Field(default=8000, ge=1)


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


class IngestConfig(_Section):
    numeric_accept_rate: float = Field(default=0.98, gt=0, le=1)
    date_accept_rate: float = Field(default=0.98, gt=0, le=1)
    max_header_scan_rows: int = Field(default=20, ge=1)
    low_cardinality_max: int = Field(default=50, ge=1)
    top_values_max: int = Field(default=30, ge=1)
    max_file_mb: int = Field(default=2048, ge=1)


class FeatureConfig(_Section):
    entity_linker: bool = False
    compiled_views: bool = False
    compiled_views_categories: list[str] | None = None


class EntityConfig(_Section):
    top_k: int = Field(default=5, ge=1)
    weak_threshold: float = Field(default=70, ge=0, le=100)
    strong_threshold: float = Field(default=85, ge=0, le=100)
    max_distinct_values: int = Field(default=100000, ge=1)

    @model_validator(mode="after")
    def _thresholds(self):
        if self.strong_threshold < self.weak_threshold:
            raise ValueError("strong_threshold must be at least weak_threshold")
        return self


class RunConfig(_Section):
    work_dir: str = "/tmp/datamate"
    model: ModelConfig = ModelConfig()
    solver: SolverConfig = SolverConfig()
    exec_limits: ExecLimits = ExecLimits()
    decision: DecisionConfig = DecisionConfig()
    formatting: FormattingConfig = FormattingConfig()
    logging: LoggingConfig = LoggingConfig()
    ingest: IngestConfig = IngestConfig()
    features: FeatureConfig = FeatureConfig()
    entities: EntityConfig = EntityConfig()

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
        tree = json.loads(Path(path).read_text(encoding="utf-8"))
    for item in overrides or []:
        if "=" not in item:
            raise ValueError(f"override must be key=value, got {item!r}")
        key, raw = item.split("=", 1)
        _apply_override(tree, key.strip(), raw)
    return RunConfig.model_validate(tree)
