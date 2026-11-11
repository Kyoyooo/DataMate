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
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _Section(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ModelConfig(_Section):
    # "scripted" is development-only and is rejected outside --dev (run.py).
    # Serving is external to the client; M4 owns server launch and health checks.
    backend: Literal["scripted", "http", "replay"] = "http"
    script_path: str | None = None  # scripted backend only
    replay_path: str | None = None  # replay backend only (dev/CI): recorded calls JSONL
    record_path: str | None = None  # dev only: also record every call to this JSONL file
    path: str | None = None  # local model directory (production)
    revision: str | None = None  # fixed model revision (commit hash); recorded in run.json
    base_url: str | None = None  # e.g. http://127.0.0.1:8000/v1; required for http
    served_model_name: str = Field(default="datamate", min_length=1)
    model_call_timeout_s: float = Field(default=120.0, gt=0, allow_inf_nan=False)
    schema_adapter: Literal["timeref.v1", "none"] = "timeref.v1"
    # False: send no response_format (determinism experiments, M3-08); invalid JSON is then handled
    # by the callers' validation. Production keeps True.
    structured_outputs: bool = True
    temperature: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    top_p: float = Field(default=1.0, gt=0, le=1)
    top_k: int = Field(default=-1, ge=-1)
    min_p: float = Field(default=0.0, ge=0, le=1)
    presence_penalty: float = Field(default=0.0, ge=-2, le=2)
    frequency_penalty: float = Field(default=0.0, ge=-2, le=2)
    repetition_penalty: float = Field(default=1.0, gt=0, allow_inf_nan=False)
    enable_thinking: dict[str, bool] = {"parse": False, "solve": False, "repair": False,
                                       "fallback": False}
    seed: int = 20261116
    max_tokens: dict[str, int] = {"parse": 1024, "solve": 2048, "repair": 2048, "fallback": 3072}

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


class ServingConfig(_Section):
    """vLLM replica launch (SPEC §7.13.1, TASKS M4-03). Owner: M4.

    ``external``: servers are started by someone else (Colab, a developer) and
    ``model.base_url`` is used as is. ``managed``: ``llm.replicas.ReplicaManager``
    starts ``replicas`` loopback servers, one per GPU, from ``model.path``.
    """

    mode: Literal["external", "managed"] = "external"
    replicas: int = Field(default=1, ge=1, le=2)
    tensor_parallel_size: int = Field(default=1, ge=1, le=2)
    gpu_ids: list[int] | None = None  # default: 0 .. replicas * tensor_parallel_size - 1
    base_port: int = Field(default=8100, ge=1024, le=65000)
    vllm_command: list[str] = ["python3", "-m", "vllm.entrypoints.openai.api_server"]
    dtype: str = "bfloat16"
    max_model_len: int = Field(default=32768, ge=256)
    gpu_memory_utilization: float = Field(default=0.90, gt=0, le=1)
    max_num_seqs: int = Field(default=64, ge=1)
    enable_prefix_caching: bool = True
    reasoning_parser: str | None = None
    quantization: str | None = None
    extra_server_args: list[str] = []
    startup_timeout_s: float = Field(default=900.0, gt=0, allow_inf_nan=False)
    health_poll_interval_s: float = Field(default=2.0, gt=0, allow_inf_nan=False)
    warmup_max_tokens: int = Field(default=8, ge=1)
    max_restarts: int = Field(default=1, ge=0)
    shutdown_timeout_s: float = Field(default=30.0, gt=0, allow_inf_nan=False)
    env: dict[str, str] = {}  # extra environment for the server processes

    @model_validator(mode="after")
    def _gpus(self) -> ServingConfig:
        need = self.replicas * self.tensor_parallel_size
        if self.gpu_ids is not None and (len(self.gpu_ids) != need or len(set(self.gpu_ids)) != need
                                         or min(self.gpu_ids) < 0):
            raise ValueError(f"serving.gpu_ids must list {need} distinct non-negative GPU ids")
        return self


class ConcurrencyConfig(_Section):
    """SPEC §6.2. Fixed per run; never tuned at run time (determinism D2)."""

    questions_per_replica: int = Field(default=24, ge=1)  # worker threads per replica
    setup_workers: int = Field(default=8, ge=1)  # business setup (ingestion) threads


class DeadlinesConfig(_Section):
    question_soft_s: float = Field(default=120.0, gt=0, allow_inf_nan=False)  # no new repair after
    question_hard_s: float = Field(default=300.0, gt=0, allow_inf_nan=False)  # abstain E_DEADLINE
    global_hard_stop_s: float = Field(default=19800.0, gt=0, allow_inf_nan=False)  # 5 h 30
    degrade_if_projected_finish_s: float = Field(default=14400.0, gt=0, allow_inf_nan=False)
    progress_interval_s: float = Field(default=60.0, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def _order(self) -> DeadlinesConfig:
        if self.question_soft_s > self.question_hard_s:
            raise ValueError("deadlines.question_soft_s must not exceed question_hard_s")
        return self


class SolverConfig(_Section):
    max_repairs: int = Field(default=1, ge=0)
    # Context budget (SPEC §6.2, §7.7.1); tokens counted with the shipped model's tokenizer.
    tokenizer: Literal["model", "estimate"] = "model"  # "estimate" = dev-only character estimate
    context_budget_tokens: int = Field(default=24000, ge=1000)
    schema_card_budget_tokens: int = Field(default=8000, ge=100)
    readme_budget_tokens: int = Field(default=2000, ge=0)
    fewshot_k: int = Field(default=3, ge=0)
    question_block_reserve_tokens: int = Field(default=1500, ge=0)  # question, frame, windows, answer
    # Prompt version (never edit a released id; see prompts/templates.py). v2 is opt-in until a
    # held-out run shows it is not worse (TASKS M3-09).
    template_version: Literal["v1", "v2"] = "v1"
    # Optional python fallback after failed SQL attempts (SPEC §7.7.4, §7.8). Off until a held-out
    # run shows a gain without regressions (TASKS M3-11 / L-07).
    python_fallback: bool = False
    # Few-shot bank built from the TRAINING split only (training_code/data_generation/build_fewshot.py).
    # null = no examples. Used with template v2. `fewshot_exclude_businesses` is the leakage guard for
    # cross-validation folds (dev harness); it must stay empty in production.
    fewshot_bank_path: str | None = None
    fewshot_exclude_businesses: list[str] = []


class ExecLimits(_Section):
    sql_timeout_s: float = 20.0
    max_result_rows: int = 1000
    memory_limit_mb: int = 4096
    # "process": killable spawn worker pool (SPEC §7.8, M3-07); "inprocess": same-process
    # execution (CPU tests only: a runaway statement cannot be killed).
    isolation: Literal["process", "inprocess"] = "process"
    workers: int = Field(default=16, ge=1)  # sandbox_workers
    kill_grace_s: float = Field(default=2.0, ge=0)  # parent kills a worker this long after the timeout


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
    serving: ServingConfig = ServingConfig()
    concurrency: ConcurrencyConfig = ConcurrencyConfig()
    deadlines: DeadlinesConfig = DeadlinesConfig()
    solver: SolverConfig = SolverConfig()
    exec_limits: ExecLimits = ExecLimits()
    decision: DecisionConfig = DecisionConfig()
    formatting: FormattingConfig = FormattingConfig()
    logging: LoggingConfig = LoggingConfig()
    ingest: IngestConfig = IngestConfig()
    entities: EntityConfig = EntityConfig()
    features: FeatureConfig = FeatureConfig()

    @model_validator(mode="after")
    def _startup_fits_global_stop(self):
        # The global stop counts from process start (model loading counts toward the 6 hours).
        # Worst-case managed startup: every replica times out once and once more per restart.
        s = self.serving
        if s.mode == "managed":
            worst = s.startup_timeout_s * (1 + s.max_restarts)
            if worst >= self.deadlines.global_hard_stop_s:
                raise ValueError(
                    f"serving.startup_timeout_s × (1 + max_restarts) = {worst:g} s leaves no time "
                    f"before deadlines.global_hard_stop_s = {self.deadlines.global_hard_stop_s:g} s")
        return self

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
