# DataMate — Zalo AI Challenge 2026

An offline agent that answers Vietnamese questions over business CSV/Excel/SQLite data, or reports `unanswerable` / `abstain`. Competition requirements: [`docs/COMPETITION_BRIEF.md`](docs/COMPETITION_BRIEF.md). Technical design: [`docs/SPEC.md`](docs/SPEC.md) (see §18 for what the current code implements and defers). Backlog: [`docs/TASKS.md`](docs/TASKS.md). Workflow: [`CONTRIBUTING.md`](CONTRIBUTING.md).

> **Status (2026-11-09): bootstrap plus M3-02 HTTP client.** The fixture pipeline has a scripted development path and a loopback HTTP client for an externally started vLLM server. Excel/SQLite ingestion, replica management and Docker are still pending. Fixture results are plumbing checks, not competition accuracy. A real Colab call remains an acceptance check in `notebooks/M3_02_HTTP_CLIENT_CHECK.ipynb`.

## Setup (CPU, no GPU, no model weights, no network at run time)

Python 3.10+ (validated with 3.12.3).

```bash
python3 -m venv .venv
```
```bash
.venv/bin/pip install -r requirements-cpu.lock
```
```bash
.venv/bin/pip install -e . --no-deps
```

GPU/serving dependencies (vLLM, torch) are **not** installed here; they come from the Docker base image (TASKS M4-01). HTTP production also needs local tokenizer assets and the optional CPU tokenizer dependencies (`pip install -e '.[tokenizer]'`), unless already provided by that image.

## Run the development pipeline on the fixture

```bash
.venv/bin/python -m datamate.run --dev --config config/dev.json --data-dir tests/fixtures/split_mini --result-dir out/fixture
```
```bash
.venv/bin/python -m datamate.eval.score --pred out/fixture/submission.jsonl --answers tests/fixtures/split_mini/answers.jsonl
```

Expected: exit code 0, 13 lines in `out/fixture/submission.jsonl`, `PA = 1.0000 (n=13 …)`. Logs: `out/fixture/logs/questions.jsonl` (one record per question with `id`, `answer`, `elapsed_ms`, `thinking`, `code`, `output`, model calls, windows, decision), `businesses.jsonl`, `run.json` (records `"dev_mode": true, "model_backend": "scripted"`).

Without `--dev`, the scripted backend is refused. The supplied production config (`config/run_config.json`) still exits with code 2 until `model.base_url` is explicitly configured; no submission file is written in that startup check:

```bash
.venv/bin/python -m datamate.run --config config/run_config.json --data-dir tests/fixtures/split_mini --result-dir out/prod-check
```

## Test and lint

```bash
.venv/bin/python -m pytest
```
```bash
.venv/bin/ruff check src tests
```

## Pipeline and package map

```
data dir ─► rules/ (rulebook, TemporalParams) ─┐
         └► catalog/ + ingest/ (files → DuckDB, SchemaCard) ─┐
questions ─► parse/ (model → QuestionFrame) ─► temporal/ (TimeWindows, coverage)
          ─► decision/ pre-check (unanswerable?) ─► solver/ (model → SQL, repair) ─► sandbox/ (DuckDB read-only)
          ─► decision/ (answer | unanswerable | abstain) ─► formatting/ (wire value) ─► runtime/ writer
```

| Package | Owner | Role | Bootstrap state |
|---|---|---|---|
| `contracts/` | Lead | Shared types, reason codes, exact JSON | 1.3.0 (M3-03 optional budget evidence; SPEC §18.6) |
| `eval/` | Lead | Scorer (`python -m datamate.eval.score`); harness later | scorer |
| `ingest/`, `catalog/`, `lexicon/` | M1 | Files → DuckDB catalog; `fold()` | fixture CSV only (UTF-8, ISO dates, plain numbers) |
| `rules/`, `temporal/`, `decision/`, `formatting/` | M2 | Rulebook, time windows, gate, wire values | generic time params; P1 resolver subset |
| `llm/` (client), `prompts/`, `parse/`, `solver/`, `sandbox/` | M3 | Model calls, prompts, SQL, execution | HTTP + dev scripted clients; in-process executor |
| `runtime/`, `run.py`, `config.py`, `llm/replicas.py` | M4 | Orchestration, writer, config, serving, Docker | sequential; no serving, no image |

Planned packages, created only when their task starts: `entities/` (M1-12, P2), `semantics/` (M1-13, P2), `llm/replay.py` (M3-13), `llm/replicas.py` (M4-03), `eval/harness.py` (L-12), `tools/` (M4-13/M4-14), `training_code/` (M4-13), `Dockerfile` and `predict.sh` (M4-09).

## Configuration

`config/runtime_defaults.json` is the shared M3/M4 profile. Both shipped run configs inherit it through `"extends": "runtime_defaults.json"`. Inheritance paths resolve relative to the child config; dictionaries merge recursively, child values win, cycles are rejected. Unknown keys are errors; unspecified keys take defaults from `src/datamate/config.py`. `--set key=value` overrides work only with `--dev` and are recorded in `run.json`. `load_config(None)` and direct `RunConfig()` use Python defaults; callers wanting the shared profile must explicitly load it or a child config.

| Key | Default | Meaning |
|---|---|---|
| `work_dir` | `/tmp/datamate` | Scratch for per-business DuckDB files (never under the data dir) |
| `model.backend` | `http` | `scripted` (dev only) or synchronous loopback `http` |
| `model.base_url` | `null` | Required for HTTP; e.g. `http://127.0.0.1:8000/v1`; loopback only, no credentials/proxies/redirects |
| `model.path` | `null` | Local immutable model/tokenizer snapshot; required for offline HTTP prompt counting |
| `model.served_model_name` | `datamate` | Must match vLLM's served model name |
| `model.model_call_timeout_s` | 120 | Shared time budget across attempts; timeouts are not retried |
| `model.schema_adapter` | `timeref.v1` | Transport-only TimeRef oneOf adapter; `none` sends the source schema unchanged |
| `model.temperature`, `model.top_p`, `model.top_k`, `model.min_p` | 0, 1, -1, 0 | Explicit decoding parameters |
| `model.presence_penalty`, `model.frequency_penalty`, `model.repetition_penalty` | 0, 0, 1 | Explicit penalties |
| `model.enable_thinking` | parse/solve/repair false | Per-stage switch; M4 must configure the matching reasoning parser |
| `model.script_path` | `null` | Scripted responses (JSONL) for the dev backend |
| `model.max_tokens` | parse 1024, solve/repair 2048 | Per-stage limits |
| `serving.max_model_len` | 8192 | Total per-request context: input + maximum output + safety |
| `serving.max_num_seqs` / `max_num_batched_tokens` | 4 / 8192 | M4 scheduler limits; neither substitutes for the per-request context |
| `serving.gpu_memory_utilization` / `target_executor_gib` | 0.90 / 28.8 | M4 adapter uses the smaller fraction when total VRAM is supplied; allocation target, not a measured process-memory guarantee |
| `serving.dtype` / `reasoning_parser` | `bfloat16` / `qwen3` | Server options for the proposed Qwen3 profile |
| `serving.prefix_caching` / `chunked_prefill` | true / true | M4 launch options |
| `prompt_budget.safety_margin_tokens` | 64 | Reserve beyond input and maximum generation |
| `prompt_budget.context_budget_tokens` | `null` | Optional additional input-only cap; otherwise derived from context/output/safety |
| `prompt_budget.readme_budget_tokens` / `schema_card_budget_tokens` | 512 / 3000 | Per-section limits measured by the local tokenizer |
| `prompt_budget.relevant_tables` | 4 | Maximum tables retaining full columns in relevant-subset fallback |
| `solver.max_repairs` | 1 | Repair turns after a failed SQL attempt |
| `exec_limits.sql_timeout_s` / `max_result_rows` / `memory_limit_mb` | 20 / 1000 / 4096 | Executor limits |
| `decision.zero_coverage` | `unanswerable` | What to emit when a period has no data (rulebook §7) |
| `formatting.rounding` / `money_decimals` / `default_decimals` | `ROUND_HALF_UP` / 0 / 2 | Money → whole VND; percents and other measures → 2 decimals |

## Repository layout

```
config/            runtime_defaults.json (shared limits), dev.json, run_config.json (set model path + endpoint)
docs/              competition brief, Docker guide, architecture, SPEC, plan, TASKS
src/datamate/      the package (see map above)
tests/unit/        component tests;  tests/integration/  fixture pipeline end to end
tests/fixtures/    split_mini (synthetic split), scripted/ (dev model responses); see its README
```

Competition data (`train/`, `public_test/`, archives) is git-ignored and never committed. Never train on, tune on, or collect answers from the public or private test (Brief §5.2).