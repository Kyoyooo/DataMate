# DataMate — Zalo AI Challenge 2026

An offline agent that answers Vietnamese questions over business CSV/Excel/SQLite data, or reports `unanswerable` / `abstain`. Competition requirements: [`docs/COMPETITION_BRIEF.md`](docs/COMPETITION_BRIEF.md). Technical design: [`docs/SPEC.md`](docs/SPEC.md) (see §18 for what the current code implements and defers). Backlog: [`docs/TASKS.md`](docs/TASKS.md). Workflow: [`CONTRIBUTING.md`](CONTRIBUTING.md).

> **Status (2026-11-11): CPU pipeline complete; no real-model run yet.** Real CSV/Excel/SQLite ingestion ([M1 handoff](docs/M1_IMPLEMENTATION.md)), rulebook/temporal/decision/formatting (M2), loopback HTTP client, prompts, budgeting, process sandbox and replay (M3), replica manager, concurrent orchestrator, run records, `Dockerfile`/`predict.sh` and prechecks (M4) are merged and CPU-tested. Not yet done: model choice (DEC-3), `requirements.lock`, an image built on the reference base, any run on a GPU. All GPU-only checks run in one Colab session on a G4 runtime: [`docs/runbooks/gpu-phase2.md`](docs/runbooks/gpu-phase2.md) (first attempt on a T4 served no model: [evidence](docs/evidence/gpu-check-2026-11-11-t4.md)). Progress: [`docs/M3_M4_PROGRESS.md`](docs/M3_M4_PROGRESS.md). Fixture results are plumbing checks, not competition accuracy.

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

After pulling new commits, re-run the two install commands: `requirements-cpu.lock` gained the M1 ingestion libraries (pyarrow, python-calamine, openpyxl, charset-normalizer, rapidfuzz) on 2026-11-11. GPU/serving dependencies (vLLM, torch, transformers) are **not** installed here; they come from the Docker base image (TASKS M4-01).

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
| `contracts/` | Lead | Shared types, reason codes, exact JSON 1.10.0 (P1 freeze, then additive minors only: SPEC §18.4–§18.14) |
| `eval/` | Lead | Scorer (`python -m datamate.eval.score`, `--logs` per reason code); fold harness (`python -m datamate.eval.harness`) | scorer, harness (CPU-tested) |
| `ingest/`, `catalog/`, `lexicon/` | M1 | Files → DuckDB catalog; `fold()` | CSV/Excel/SQLite ingestion, Vietnamese formats, profiling and bounded prompt schemas; [M1 handoff](docs/M1_IMPLEMENTATION.md) |
| `rules/`, `temporal/`, `decision/`, `formatting/` | M2 | Rulebook, time windows, gate, wire values | calendar validation; generic CLI time params with an opt-in CPU-tested extraction boundary ([M2 handoff](docs/M2_RULEBOOK_CALENDAR.md)) |
| `llm/` (client), `prompts/`, `parse/`, `solver/`, `sandbox/` | M3 | Model calls, prompts, SQL, execution | HTTP, replay and dev scripted clients; budgeting; killable process sandbox pool |
| `runtime/`, `run.py`, `config.py`, `llm/replicas.py` | M4 | Orchestration, writer, config, serving, Docker | concurrent orchestrator, replica manager, Dockerfile/`predict.sh` (CPU-tested; no image on the reference base yet) |

Experimental M1 packages, default off: `entities/` (M1-12, P2), `semantics/` (M1-13, P2).

## Configuration

One JSON file; unknown keys are errors; missing keys take defaults from `src/datamate/config.py`. `--set key=value` overrides work only with `--dev` and are recorded in `run.json`.

| Key | Default | Meaning |
|---|---|---|
| `work_dir` | `/tmp/datamate` | Scratch for per-business DuckDB files (never under the data dir) |
| `ingest.numeric_accept_rate` / `date_accept_rate` | 0.98 / 0.98 | Minimum accepted parse fraction for a typed column |
| `ingest.max_header_scan_rows` / `max_file_mb` | 20 / 2048 | Header search and per-file ingestion limits |
| `ingest.low_cardinality_max` / `top_values_max` | 50 / 30 | Profiling vocabulary and example limits |
| `solver.schema_card_budget_tokens` | 8000 | Enforced with the same tokenizer as the complete prompt; full audit metadata stays on disk |
| `entities.top_k` / `weak_threshold` / `strong_threshold` / `max_distinct_values` | 5 / 70 / 85 / 100000 | Standalone experimental entity-index configuration |
| `features.entity_linker` / `compiled_views` / `compiled_views_categories` | false / false / null | Reserved experimental M1 API settings; not activated by the main runner; real-model gates remain deferred |
| `model.backend` | `http` | `scripted` (dev only) or synchronous loopback `http` |
| `model.base_url` | `null` | Required for HTTP; e.g. `http://127.0.0.1:8000/v1`; loopback only, no credentials/proxies/redirects |
| `model.served_model_name` | `datamate` | Must match vLLM's served model name |
| `model.model_call_timeout_s` | 120 | Shared time budget across attempts; timeouts are not retried |
| `model.schema_adapter` | `timeref.v1` | Transport-only TimeRef oneOf adapter; `none` sends the source schema unchanged |
| `model.temperature`, `model.top_p`, `model.top_k`, `model.min_p` | 0, 1, -1, 0 | Explicit decoding parameters |
| `model.presence_penalty`, `model.frequency_penalty`, `model.repetition_penalty` | 0, 0, 1 | Explicit penalties |
| `model.enable_thinking` | parse/solve/repair false | Per-stage switch; M4 must configure the matching reasoning parser |
| `model.script_path` | `null` | Scripted responses (JSONL) for the dev backend |
| `model.max_tokens` | parse 1024, solve/repair 2048 | Per-stage limits |
| `serving.mode` | `external` | `external`: use `model.base_url` (Colab, manual `vllm serve`); `managed`: `llm.replicas.ReplicaManager` starts the loopback servers from `model.path` |
| `serving.replicas` / `tensor_parallel_size` / `gpu_ids` | 1 / 1 / `null` | One server per GPU (`CUDA_VISIBLE_DEVICES`); `gpu_ids` default `0 … replicas×tp−1` |
| `serving.base_port` | 8100 | Replica `i` listens on `127.0.0.1:base_port+i` |
| `serving.vllm_command` | `python3 -m vllm.entrypoints.openai.api_server` | Launch command (tests substitute a fake server) |
| `serving.dtype` / `max_model_len` / `gpu_memory_utilization` / `max_num_seqs` | bfloat16 / 32768 / 0.90 / 64 | Server flags (SPEC §7.13.1); never tuned at run time |
| `serving.enable_prefix_caching` / `reasoning_parser` / `quantization` / `extra_server_args` | true / null / null / [] | Further server flags |
| `serving.startup_timeout_s` / `health_poll_interval_s` / `warmup_max_tokens` | 900 / 2 / 8 | `GET /health` polling, then one fixed warm-up request |
| `serving.max_restarts` / `shutdown_timeout_s` / `env` | 1 / 30 / {} | Restart budget per replica; SIGTERM→SIGKILL grace; extra server environment |
| `concurrency.questions_per_replica` / `setup_workers` | 24 / 8 | Worker threads per replica; business-setup threads |
| `deadlines.question_soft_s` / `question_hard_s` | 120 / 300 | No new repair after soft; abstain `E_DEADLINE` at hard (model calls are capped to the remaining time) |
| `deadlines.global_hard_stop_s` / `degrade_if_projected_finish_s` / `progress_interval_s` | 19800 / 14400 / 60 | Global stop (unwritten ids → `abstain` `E_GLOBAL_STOP`); degrade mode (no repairs) if the projected finish passes the threshold |
| `solver.max_repairs` | 1 | Repair turns after a failed SQL attempt |
| `exec_limits.sql_timeout_s` / `max_result_rows` / `memory_limit_mb` | 20 / 1000 / 4096 | Executor limits |
| `decision.zero_coverage` | `unanswerable` | What to emit when a period has no data (rulebook §7) |
| `formatting.rounding` / `money_decimals` / `default_decimals` | `ROUND_HALF_UP` / 0 / 2 | Money → whole VND; percents and other measures → 2 decimals |

## Repository layout

```
config/            dev.json (scripted fixture run), run_config.json (set the HTTP endpoint before use)
docs/              competition brief, Docker guide, architecture, SPEC, plan, TASKS
src/datamate/      the package (see map above)
tests/unit/        component tests;  tests/integration/  fixture pipeline end to end
tests/fixtures/    split_mini (synthetic split), scripted/ (dev model responses); see its README
```

Competition data (`train/`, `public_test/`, archives) is git-ignored and never committed. Never train on, tune on, or collect answers from the public or private test (Brief §5.2).

## HTTP client acceptance (M3-02)

Start vLLM separately (M4); set `model.base_url` and `model.served_model_name` in a run config. Client construction does not start or health-check the server. `complete` uses the actual HTTP body for its SHA-256, preserves generated text, and retries transport failures once with identical bytes. HTTP/protocol errors and timeouts are not retried. Errors return as `ModelCall.error`; SQL/content validation stays in parser/solver. A `length` finish reason is preserved, not changed to `stop`.

`ModelCall.transport` records request preparation, adapter version, original schema hash, actual request body, raw response body, status and attempts. Failed schema preparation sends no request (`request_prepared=false`, empty-body hash). The legacy scripted hash is unchanged; replay recordings must pin the HTTP body and adapter policy. Transport records contain runtime prompts/responses and may increase log size.

Run `python -m pytest tests/unit/test_model_client.py` for CPU fake-server checks. The check notebook repeats them by criterion, runs regression/lint checks, and optionally calls a real local vLLM server; without that real call M3-02 is not fully accepted.
