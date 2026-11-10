# DataMate 2026 — Technical Specification

| Field | Value |
|---|---|
| **Document** | `SPEC.md` |
| **Version** | 1.1 — ownership for one lead and four members; compatibility, conformance, and determinism rules for parallel development |
| **Status** | Implementation baseline. Contracts in §5 are **frozen at I0 (2026-11-07 12:00 GMT+7)**; later changes follow §15. |
| **Date** | 2026-11-06 (GMT+7) |
| **Design authority** | `ARCHITECTURE_PROPOSAL.md` v2.1 (cited as **AP §x**) |
| **Structural companion** | `ARCHITECTURE.md` v1.1 (cited as **ARCH §x**) — module layout, runtime views, seams |
| **Compliance authority** | `COMPETITION_BRIEF.md` (**Brief §x**) and `zac2026_DataMate_docker_guideline_final.md` (**DG §x**) |
| **Audience** | The lead and the four members M1–M4 (roles in `IMPLEMENTATION_PLAN.md` §2) |

---

## 0. How to read this document

### 0.1 Normative language
**MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** are used as in RFC 2119. Everything not marked as an example, rationale, or note is normative.

### 0.2 Tags
| Tag | Meaning |
|---|---|
| **[REQ]** | Competition or Docker-guide requirement (Brief / DG) |
| **[AP]** | Fixed by the approved architecture |
| **[SPEC]** | Specification-level choice made here within the architecture |
| **[DEFAULT DEC-n]** | Default chosen here for a decision still open in AP §13; changeable only through the configuration key named, with no code change |
| **[VERIFY]** | Must be confirmed against the Brief, training data, or a test before M1; the current value is the working assumption |

### 0.3 Source availability
- Available while writing: `ARCHITECTURE_PROPOSAL.md` v2.1, `ARCHITECTURE.md` v1.1, `IMPLEMENTATION_PLAN.md` v1.1, `TASKS.md` v1.1, and the Docker guide.
- **Not available:** `CLAUDE.md` and `COMPETITION_BRIEF.md`. Brief citations follow AP v2.1. Every item that depends on exact Brief wording (notably the JSON wire shapes of `list` and `table`, rounding mode, and `boolean` encoding) is tagged **[VERIFY]** and listed in §17. The lead owns checking these against the Brief by **I0** (TASKS L-11).
- `ARCHITECTURE.md` adds module-level detail. It MUST NOT contradict this specification; conflicts are resolved by the change process in §15.

### 0.4 Clarifications of the architecture
This specification introduces **no major architectural change**. It makes seven clarifications, listed in §16 (SC-1 … SC-7), that resolve under-specified points in AP. One of them (SC-3) fixes a **critical offline-compatibility gap**: DuckDB downloads extensions at run time by default, which would fail under `--network none`.

### 0.5 Owners
Owners are the roles of `IMPLEMENTATION_PLAN.md` §2: **Lead** (contracts, evaluation, integration), **M1** Data & Semantics, **M2** Rules, Time & Answers, **M3** Reasoning Engine, **M4** Platform & Compliance. Each component heading in §7 names its owner.

---

## 1. Scope

### 1.1 In scope
The inference system packaged in the Docker image: entry point, process model, shared data contracts, configuration, every component C1–C14 of AP §6, prompts (by contract, not wording), determinism, performance budgets, logging, testing, compatibility rules for parallel development, compliance artifacts, and integration procedure.

### 1.2 Out of scope
Schedule and task assignment (`IMPLEMENTATION_PLAN.md`, `TASKS.md`), prompt wording (owned by M3, versioned in `prompts/`), and fine-tuning (AP §8.3, Phase 3 only).

### 1.3 Phase markers
Each requirement belongs to **P1** (baseline, required for M1), **P2** (accuracy), or **P3** (optional, gated) per AP §10. Unmarked requirements are P1. A P2/P3 feature MUST be behind a configuration switch (§6) whose production default is `false` until its gate passes.

---

## 2. System runtime contract

### 2.1 Entry point [REQ DG §5]
- `bash /code/predict.sh`, no arguments, no interactive input.
- `predict.sh` MUST:
  1. `set -euo pipefail`.
  2. Export the fixed environment of §2.4.
  3. `mkdir -p /result/logs`.
  4. `exec python3 -m datamate.run --config /code/config/run_config.json --data-dir /data --result-dir /result`.
- `predict.sh` MUST NOT read any environment variable that changes behavior. The Python entry point MUST ignore all `DATAMATE_*` overrides unless `--dev` is passed, and `predict.sh` never passes `--dev`.
- Development-only flags (accepted only with `--dev`): `--set key=value` (configuration override, §6.1) and `--stub <stage>` (replace a pipeline stage with its stand-in from `contracts/testing.py`, for integration; stages: `split`, `setup`, `parse`, `temporal`, `solve`, `execute`, `decide`, `format`).
- Exit code: **0** when `submission.jsonl` contains exactly one line per distinct input question id (answers or abstains) and `run.json` is written; **1** otherwise. A fatal error MUST still trigger the finalization step of §2.3 before exiting.

### 2.2 Filesystem
| Path | Access | Content |
|---|---|---|
| `/data` | read-only [REQ] | Inputs (DG §3.1). Nothing may be written, including SQLite journals (§7.2.4) |
| `/code` | read-only by convention | Code, config, models, training artifacts (DG §4) |
| `/tmp/datamate/` | read-write | Scratch root; created at startup; never read across runs |
| `/tmp/datamate/biz/<bkey>/catalog.duckdb` | rw during setup, ro afterwards | Per-business database |
| `/tmp/datamate/sandbox/<pid>/` | rw | Executor scratch |
| `/result/submission.jsonl` | write | §8.2 |
| `/result/logs/questions.jsonl` | write | §8.3 |
| `/result/logs/businesses.jsonl` | write | §8.4 |
| `/result/logs/run.json` | write | §8.5 |
| `/result/logs/progress.log` | write | Human-readable progress, non-normative content |

`<bkey>` is the business directory name sanitized to `[A-Za-z0-9_-]`, used only as a path key.

### 2.3 Run lifecycle
```
T0  process start (monotonic clock starts; wall-clock budget counts from here)
 1  load + validate RunConfig; compute config_sha256
 2  validate /data layout; read questions.jsonl (§7.0)
 3  in parallel:
      a. start model replicas (C13) and wait for health + warm-up
      b. split bootstrap (C1): rulebook, calendar, TemporalParams (needs a replica)
      c. business setup (C2, then C3 in P2) in a process pool, ordered per §7.12
 4  as each business becomes READY and the split context is READY, enqueue its questions
 5  question workers run the per-question pipeline (§7.4–§7.11)
 6  global stop at min(all done, T0 + global_hard_stop_s)
 7  finalize: write `abstain` for every unwritten id; write run.json; stop replicas; exit
```

### 2.4 Fixed environment (set in Dockerfile and re-exported by `predict.sh`)
| Variable | Value | Reason |
|---|---|---|
| `HF_HUB_OFFLINE` | `1` | [REQ DG §9] |
| `TRANSFORMERS_OFFLINE` | `1` | [REQ DG §9] |
| `PYTHONHASHSEED` | `0` | Determinism |
| `PYTHONUNBUFFERED` | `1` | Logging |
| `TOKENIZERS_PARALLELISM` | `false` | Determinism, fork safety |
| `OMP_NUM_THREADS`, `MKL_NUM_THREADS`, `OPENBLAS_NUM_THREADS` | `1` | Determinism of numeric libraries in sandbox workers |
| `NCCL_P2P_DISABLE` | `1` | [DG §9] harmless in DP topology; required only for the TP contingency |
| `VLLM_BATCH_INVARIANT` | `0` **[DEFAULT DEC-3]**; `1` only if it validates (AP §7.7) | Determinism |
| `VLLM_NO_USAGE_STATS`, `DO_NOT_TRACK` | `1` | No outbound calls |

### 2.5 Prohibited behavior [REQ]
- No network access of any kind except the loopback interface used by C13.
- No answer, prompt branch, threshold, or code path selected by a question `id` or `business_id`. These values MAY be used only as opaque keys for grouping, ordering, file naming, and logging. A static check in CI MUST fail on any string literal matching an id pattern from the training split appearing in `src/`.
- No writes under `/data`.

---

## 3. Process model

```
main process (asyncio event loop)
├── Orchestrator (C12), Writer task (C11), ModelClient (C13 client)
├── replica-0: vLLM OpenAI server subprocess, CUDA_VISIBLE_DEVICES=0, 127.0.0.1:8100
├── replica-1: vLLM OpenAI server subprocess, CUDA_VISIBLE_DEVICES=1, 127.0.0.1:8101
├── setup pool: ProcessPoolExecutor (spawn), size = setup_workers   → C2, C3 DB work
└── sandbox pool: custom killable worker pool (spawn), size = sandbox_workers → C8 (§7.8)
```
- Start method MUST be `spawn` for all pools (no inherited CUDA or event-loop state). The sandbox pool is not a `ProcessPoolExecutor`, because a timed-out worker must be killed and replaced individually.
- Only C11 writes to `/result`. Only C13 talks to model servers. Only C2/C3 write DuckDB files. Only C8 executes generated code.
- Fallback **[AP §6.3]**: if loopback serving is unavailable under `--network none` (checked at G6), replicas run as in-process `AsyncLLM` engines behind the same `ModelClient` protocol (§7.13.3). No other component may observe the difference.

---

## 4. Repository and module layout

### 4.1 Image layout [REQ DG §4]
```
/code/
├── predict.sh
├── README.md                     # §13.1
├── requirements.txt              # pinned, generated from the lock (§4.4)
├── config/run_config.json        # frozen production config (§6)
├── src/datamate/                 # inference package (installed with pip -e or on PYTHONPATH)
├── models/<model_dir>/           # only the selected model (AP §7.9)
└── training_code/                # §13.2
```

### 4.2 Package layout, ownership, and review
| Module | Component | Owner | Suggested reviewer | Depends on |
|---|---|---|---|---|
| `datamate/contracts/` | All shared types (§5), protocols, test doubles | **Lead** | Members whose components produce or consume the changed type | stdlib, pydantic |
| `datamate/config.py` | RunConfig loader (§6) | M4 | Lead | contracts |
| `datamate/run.py` | Entry point, lifecycle, stub mode (§2) | M4 | Lead | all |
| `datamate/rules/` | C1 Split Bootstrap | M2 | M3 | contracts, llm, prompts |
| `datamate/temporal/` | C5 Temporal Resolver, LunarCalendar | M2 | M3 | contracts |
| `datamate/semantics/` | C3 Semantic Compiler (P2) | M1 | M2 | contracts, llm, prompts, catalog |
| `datamate/lexicon/` | Abbreviation lexicon, text folding | M1 | M2 | — |
| `datamate/ingest/` | C2 readers, parsers | M1 | M3 | contracts, lexicon |
| `datamate/catalog/` | C2 DuckDB materialization, profiling, SchemaCard | M1 | M3 | contracts, ingest, llm (tokenizer) |
| `datamate/entities/` | C6 Entity Linker (P2) | M1 | M3 | contracts, lexicon |
| `datamate/llm/client.py`, `tokenizer.py` | C13 client | M3 | M4 | contracts |
| `datamate/llm/replicas.py`, `inprocess.py` | C13 replicas | M4 | M3 | contracts |
| `datamate/prompts/` | Prompt templates + IDs (§7.13.5) | M3 | Lead | — |
| `datamate/parse/` | C4 Question Parser | M3 | M2 | contracts, llm, prompts, lexicon |
| `datamate/solver/` | C7 Solver, context pack | M3 | M2 | contracts, llm, prompts, lexicon |
| `datamate/sandbox/` | C8 Executor | M3 | M4 | contracts |
| `datamate/decision/` | C9 Verifier & Decision | M2 | Lead | contracts, lexicon |
| `datamate/formatting/` | C10 Formatter | M2 | Lead | contracts |
| `datamate/runtime/` | C12 Orchestrator, C11 Writer, records | M4 | M3 (orchestration), Lead (records) | contracts, all pipeline modules |
| `datamate/eval/` | C14 scorer, harness (not imported by `run.py`) | **Lead** | M2 (scoring), M4 (harness) | contracts, all |
| `tests/contract/`, `tests/integration/`, `tests/determinism/`, `tests/golden/` | Shared tests (§14) | **Lead** | M2 for goldens | — |

Review is optional; only pull-request-only merging to `main` is enforced (§18.2, `CONTRIBUTING.md`).

### 4.3 Dependency and public-API rules
- `contracts` imports nothing from `datamate`.
- **Public API.** Each package declares its public names in `__init__.py` `__all__`. Another package MAY import only those names (or contract types). Private modules and `_`-prefixed names are never imported across packages. CI checks this.
- Pipeline modules communicate **only** through contract types and the protocols in §5.10.
- Layering follows ARCH §4.2: a module imports only from its own layer or lower layers.
- `eval` MAY import anything; nothing on the inference path imports `eval`.
- Cyclic imports are forbidden; CI runs an import-graph check.

### 4.4 Dependencies
- Base image per DEC-3 (AP §7.9). Python version = the base image's Python.
- `requirements.lock` MUST be generated by `pip freeze` **inside the chosen base image** after installing project requirements; every development environment installs from the same lock (AP §4.2). Adding a dependency is a change to the lock, approved by the lead and M4.
- Project-level dependencies (exact pins fixed at M0 in the lock): `duckdb`, `python-calamine`, `openpyxl` (fallback reader), `pandas`, `pyarrow`, `rapidfuzz`, `charset-normalizer`, `httpx`; `pydantic` v2, `transformers` (tokenizer only), and `openai` are taken from the base image.
- No dependency may perform network access at import or run time. Verified by G6 (`--network none`).

---

## 5. Shared contracts

### 5.1 General rules
- Implemented as **pydantic v2** models in `datamate/contracts/`, with `model_config = ConfigDict(frozen=True, extra="forbid", strict=True)`.
- `CONTRACTS_VERSION = "1.0.0"` (semver, §15). Every log record carries it.
- **Implemented surface:** `datamate/contracts/` v1.0.0 implements the P1 subset of this section. §18.3 lists every difference; where they differ for P1, the code and §18.3 are authoritative.
- JSON Schemas are exported to `contracts/schemas/<Name>.json` by a script and committed. CI fails if exported schemas differ from committed ones without a version bump.
- Dates are `datetime.date` in memory and ISO-8601 strings on the wire. Decimal values are `decimal.Decimal` in memory and **never** pass through binary floating point between the executor and the formatter.
- Text is NFC-normalized at the boundary where it enters the system (input files, model output). Contracts never hold accent-folded text except fields explicitly named `*_folded`.

### 5.2 Enumerations
```text
AnswerType     = number | percent | string | date | boolean | list | table
DecisionKind   = answer | unanswerable | abstain
DateGranularity= day | month
Granularity    = day | week | month | quarter | year | range
Stage          = rule_profile | compile | parse | solve | repair | fallback | fallback_repair
ExprKind       = date | date_range | calendar_period | relative_period | rolling
               | same_period_prior_year | lunar_holiday | lunar_date_range | all_time | unsupported
MentionKind    = product | category | customer | supplier | employee | store | channel | other
ResultShape    = scalar | list | table
ReasonCode     = see §10.2
```

### 5.3 Inputs
**`Question`**
| Field | Type | Constraint |
|---|---|---|
| `id` | str | non-empty |
| `business_id` | str | non-empty; must match a directory under `/data/data/` or the question is abstained with `E_INPUT_BUSINESS_MISSING` |
| `question` | str | NFC |
| `as_of_date` | date | ISO `yyyy-mm-dd`; unparsable → abstain with `E_INPUT_AS_OF` |
| `line_no` | int | 1-based line in `questions.jsonl` (ordering only) |

### 5.4 Configuration
**`RunConfig`** — see §6 for every key. Loaded once; immutable; `config_sha256` = SHA-256 of the canonical JSON (sorted keys, no whitespace).

### 5.5 Split-level contracts
**`TemporalParams`** (SC-1; P1)
| Field | Type | Meaning | Generic fallback when the rulebook is silent |
|---|---|---|---|
| `week_start` | `mon`/`sun` | First day of a week | `mon` (ISO 8601) |
| `to_date_end` | `as_of` / `day_before_as_of` | End of "this week/month/year" and "to date" windows | `as_of` |
| `rolling_includes_as_of` | bool | Whether "last N days" includes `as_of_date` | `true` |
| `prior_period_full` | bool | "Last week/month" means the full previous calendar period | `true` |
| `year_omitted_policy` | `most_recent_not_after_as_of` | Year inference for "tháng 3", "Q2" | fixed |
| `same_period_alignment` | `calendar_dates` / `elapsed_days` | How "cùng kỳ năm ngoái" maps a window | `calendar_dates` |
| `provenance` | map field → `{source: "rulebook"|"generic", span: str|null}` | Audit trail | — |

Fallback values are **generic conventions, not values learned from the training rulebook**; every fallback use is logged with `provenance.source="generic"` and raises `F_TEMPORAL_GENERIC` as a verifier feature (§7.9).

**`HolidayWindow`** (P2): `name_key` (str, from rulebook vocabulary), `anchor` (`{lunar_month, lunar_day}`), `start_offset_days` (int), `end_offset_days` (int), `span` (rulebook quote).

**`RuleProfile`** (P2): `temporal: TemporalParams`, `holidays: list[HolidayWindow]`, `default_rank_criterion: {metric_text: str, span: str} | null`, `definitions: list[{term: str, text: str, span: str}]`, `unresolved: list[str]`.

**`SplitContext`**: `rulebook_text: str` (verbatim, NFC), `rulebook_sha256: str`, `temporal: TemporalParams`, `rule_profile: RuleProfile | null`, `calendar: LunarCalendar` (protocol §5.10), `calendar_ok: bool`.

### 5.6 Business-level contracts
**`ColumnInfo`**
| Field | Type | Notes |
|---|---|---|
| `name` | str | SQL identifier (SC-2) |
| `original_name` | str | Header as found, NFC |
| `sql_type` | str | `BIGINT`, `DECIMAL(38,6)`, `DOUBLE`, `VARCHAR`, `DATE`, `TIMESTAMP`, `BOOLEAN` |
| `semantic_hint` | str \| null | `money`, `quantity`, `percent`, `code`, `name`, `status`, `date`, or null |
| `null_rate` | float | 0–1 |
| `distinct_count` | int | Exact |
| `min`, `max` | str \| null | String form |
| `top_values` | list[{value: str, count: int}] | §7.2.8 |
| `raw_column` | str \| null | Name of the preserved raw VARCHAR column when parsing changed the value |
| `parse_rate` | float | Share of non-null raw values that parsed |
| `format_note` | str \| null | e.g. `dot_thousands`, `dd/mm/yyyy`, `excel_serial` |

**`TableInfo`**: `name`, `source_file` (relative to business dir), `source_part` (sheet / SQLite table / null), `row_count`, `columns: list[ColumnInfo]`, `candidate_keys: list[list[str]]`, `dropped_rows: {total_rows: int, note_rows: int, blank_rows: int}`.

**`JoinEdge`**: `left: "table.col"`, `right: "table.col"`, `cardinality: "n:1"|"1:1"|"n:n"`, `match_rate: float`.

**`BusinessCatalog`**
| Field | Type |
|---|---|
| `business_id` | str |
| `bkey` | str |
| `db_path` | str |
| `tables` | list[TableInfo] |
| `joins` | list[JoinEdge] |
| `date_columns` | list[{column: "table.col", min: date, max: date}] |
| `data_range` | `DateRange \| null` where `DateRange = {start: date, end: date}`; union over date columns of non-dimension tables |
| `readme_text` | str \| null (verbatim, truncated only for the context pack, never in storage) |
| `schema_card` | str (§7.2.9) |
| `schema_card_sha256` | str |
| `warnings` | list[{code: str, detail: str}] |
| `setup_ms` | int |
| `status` | `ready` / `failed` |

**`ViewSpec`** (P2): `name` (`v_` prefix), `purpose`, `ddl`, `depends_on: list[str]`, `validation: {executed: bool, row_count: int, checks: list[{name, passed, detail}]}`, `enabled: bool`, `category: str`.

**`SemanticAnnotations`** (P2): `table_roles: map table → {role: fact|dimension|lookup|log|other, grain: str}`, `value_semantics: list[{column, value, meaning}]`, `join_paths: list[JoinEdge]`, `views: list[ViewSpec]`, `compile_calls: list[ModelCall]`.

### 5.7 Question-level contracts
**`TimeExpr`** — discriminated union on `kind` (SC-6):
| `kind` | Fields | Example |
|---|---|---|
| `date` | `date` | "ngày 5/3/2025" |
| `date_range` | `start`, `end` | "từ 1/3 đến 15/3" (year resolved by policy if missing; model emits `null` year) |
| `calendar_period` | `unit` (month/quarter/year/week), `year: int\|null`, `index: int\|null` | "tháng 3/2025", "quý 2", "năm 2024" |
| `relative_period` | `unit` (day/week/month/quarter/year), `offset: int`, `to_date: bool` | "tuần rồi" → week, −1, false; "tháng này" → month, 0, true |
| `rolling` | `unit` (day/week/month), `count: int ≥ 1` | "7 ngày qua" |
| `same_period_prior_year` | `ref: int` (index into `QuestionFrame.time`) | "cùng kỳ năm ngoái" |
| `lunar_holiday` (P2) | `name_key: str`, `year_offset: int` | "Tết năm nay" |
| `lunar_date_range` (P2) | `lunar_month`, `lunar_day_start\|null`, `lunar_day_end\|null`, `year_offset` | "rằm tháng 8" |
| `all_time` | — | no time constraint stated |
| `unsupported` | `reason: str` | anything else |

**`TimeRef`**: `span: str` (verbatim substring of the question), `role: primary|comparison|baseline`, `expr: TimeExpr`.

**`Mention`**: `text: str` (verbatim substring), `kind: MentionKind`.

**`RankingSpec`**: `k: int|null`, `direction: top|bottom`, `criterion_text: str|null` (null → rulebook default criterion).

**`Answerability`**: `status: answerable|missing_field|unclear`, `missing_fields: list[str]`.

**`QuestionFrame`** (model output, schema-constrained, §7.4)
| Field | Type |
|---|---|
| `expected_type` | AnswerType |
| `date_granularity` | DateGranularity \| null (required iff `expected_type == date`) |
| `metric_text` | str (≤ 200 chars) |
| `mentions` | list[Mention] (≤ 10) |
| `time` | list[TimeRef] (≤ 4) |
| `ranking` | RankingSpec \| null (required iff `expected_type == list`) |
| `group_by_text` | list[str] |
| `comparison` | `{kind: change_pct|change_abs|ratio|difference, baseline_ref: int}` \| null |
| `needs_procedural` | bool |
| `answerability` | Answerability |

**`TimeWindow`**: `ref_index: int`, `role`, `start: date`, `end: date` (inclusive, start ≤ end), `granularity: Granularity`, `provenance: list[str]` (param names and sources used), `coverage_ratio: float` (overlap days with `data_range` / window days; `null` if no data range), `flags: list[str]`.

**`EntityCandidate`** (P2): `mention_index: int`, `table`, `column`, `value: str` (as stored), `code: str|null`, `score: float` (0–100), `strength: strong|weak`.

**`ModelCall`**
| Field | Type | Notes |
|---|---|---|
| `call_id` | str | `<question_id or bkey>:<stage>:<n>` |
| `stage` | Stage | |
| `replica` | int | |
| `template_id` | str | §7.13.5 |
| `request_sha256` | str | SHA-256 of the canonical request JSON (messages + params) |
| `params` | object | Every decoding parameter actually sent |
| `content` | str | Exact `message.content` returned |
| `reasoning` | str \| null | Exact `reasoning_content` returned, or null |
| `finish_reason` | str | |
| `prompt_tokens`, `completion_tokens` | int | |
| `latency_ms` | int | |
| `error` | str \| null | Transport/timeout error code |

**`ExecutionResult`**: `language: sql|python`, `code: str` (exact executed text), `ok: bool`, `error_code: ReasonCode|null`, `error_text: str|null` (≤ 2,000 chars, truncated with marker — error text is diagnostic, not a compliance field), `columns: list[str]`, `column_types: list[str]`, `rows: list[list[JSONValue]]` (≤ `max_result_rows`), `row_count: int` (rows fetched, capped at `max_result_rows + 1`), `truncated: bool` (true iff more than `max_result_rows` rows exist), `duration_ms: int`, `helper_call: {function: str, inputs: object} | null`.

Row values crossing the process boundary are encoded as tagged JSON (`{"t":"dec","v":"123.450000"}`, `{"t":"date","v":"2025-03-01"}`, plain strings, ints, bools, null) so that no value passes through float.

**`SolverAttempt`**: `attempt_no: int`, `stage: Stage`, `model_call: ModelCall`, `solver_output: SolverOutput | null` (null if model output invalid), `execution: ExecutionResult | null`, `contract_check: {ok: bool, reason: ReasonCode|null}`.

**`SolverOutput`** (model output, schema-constrained, §7.7.3): `sql: str` (or `python: str` for fallback), `result_shape: ResultShape`, `answer_column: str|null`, `notes: str` (≤ 300 chars).

**`TypedValue`** — discriminated union:
| `type` | In-memory value |
|---|---|
| `number`, `percent` | `Decimal` |
| `string` | `str` |
| `date` | `{value: date, granularity: DateGranularity}` |
| `boolean` | `bool` |
| `list` | `list[{item: JSONScalar, sort_key: Decimal|str|null, tie_code: str|null}]` |
| `table` | `{columns: list[str], rows: list[list[JSONScalar]]}` |

**`Decision`**: `kind: DecisionKind`, `value: TypedValue|null` (iff answer), `reason_code: ReasonCode`, `unanswerable_reason: str|null`, `features: map[str, float|int|bool|str]`, `p_correct: float|null` (P3).

### 5.8 Output contracts
**`SubmissionRecord`** [REQ DG §3.2] — exactly one of:
```json
{"id": "q_01234", "type": "number", "answer": 48250000}
{"id": "q_01235", "type": "unanswerable", "reason": "missing_field:cost"}
{"id": "q_01236", "type": "abstain"}
```
**`LogRecord`** — §8.3. **`BusinessLogRecord`** — §8.4. **`RunRecord`** — §8.5.

### 5.9 Contract invariants (enforced by validators and tested)
1. `TimeWindow.start ≤ TimeWindow.end`.
2. `QuestionFrame.ranking` present iff `expected_type == list`; `date_granularity` present iff `expected_type == date`.
3. `Decision.value.type == SubmissionRecord.type` for answers.
4. Every `Mention.text` and `TimeRef.span` is a substring of the original **or** normalized question; otherwise the item is dropped and `F_SPAN_MISMATCH` is set.
5. `ModelCall.content` and `.reasoning` are stored byte-for-byte as returned.

### 5.10 Protocols and stand-ins (`contracts/protocols.py`, `contracts/testing.py`)
```python
class ModelClient(Protocol):
    async def call(self, *, stage: Stage, template_id: str, messages: list[dict],
                   json_schema: dict | None, max_tokens: int, enable_thinking: bool,
                   replica: int, call_id: str, timeout_s: float) -> ModelCall: ...

class LunarCalendar(Protocol):
    def to_lunar(self, d: date) -> tuple[int, int, int, bool]: ...   # (year, month, day, is_leap)
    def to_solar(self, lunar_year: int, month: int, day: int, is_leap: bool = False) -> date: ...
    def covers(self, d: date) -> bool: ...

class Executor(Protocol):
    async def run_sql(self, db_path: str, sql: str, limits: ExecLimits) -> ExecutionResult: ...
    async def run_python(self, db_path: str, code: str, limits: ExecLimits) -> ExecutionResult: ...  # P2

class Deadline(Protocol):
    @property
    def soft_expired(self) -> bool: ...
    @property
    def hard_expired(self) -> bool: ...
    def remaining_s(self) -> float: ...

# ExecLimits is the RunConfig.exec_limits section (a contract type).

class SubmissionSink(Protocol):
    async def write(self, record: SubmissionRecord, log: LogRecord) -> None: ...
    def written_ids(self) -> frozenset[str]: ...
```

Stand-ins in `contracts/testing.py` MUST exist at I0 (11-07 12:00) and MUST pass the conformance suites of §14.3:

| Stand-in | Implements | Behavior |
|---|---|---|
| `ScriptedModelClient` | `ModelClient` | Returns fixed `content`/`reasoning` per `(stage, template_id)` or per call order |
| `ReplayModelClient` | `ModelClient` | Returns recorded `ModelCall`s keyed by `request_sha256`; unknown request → `ModelCall.error = "E_REPLAY_MISS"` |
| `FakeExecutor` | `Executor` | Runs SQL in-process on a read-only DuckDB connection with the same encoding and error codes as C8 |
| `FixtureLunarCalendar` | `LunarCalendar` | Built from a small calendar fixture covering two lunar years |
| `FakeDeadline` | `Deadline` | Manually advanced clock |
| `InMemorySink` | `SubmissionSink` | Records writes in order; rejects duplicate ids |
| `fixture_split_context()` | — | A `SplitContext` with generic `TemporalParams` and the fixture calendar |

Fake catalogs (`make_fake_catalog()` and prebuilt catalogs under `tests/fixtures/catalogs/`) are provided by M1 by 11-07 EOD (TASKS M1-11).

---

## 6. Configuration

### 6.1 Rules
- Production configuration is `/code/config/run_config.json`, frozen in the image [REQ DG §5.3]. It is the **only** source of tunable values; no module may hard-code a value listed here.
- Unknown keys are an error. Missing keys take the defaults below; the effective configuration (with defaults filled) is what `config_sha256` hashes and what `run.json` records.
- The dev harness MAY override keys via `--dev --set key=value`; overrides are recorded in the run record. `predict.sh` cannot pass overrides. No member edits `run_config.json` locally for experiments.
- Adding a key requires a default and a row in this section, merged with the code that reads it (§15).

### 6.2 Keys and defaults
```json
{
  "contracts_version": "1.0.0",
  "model": {
    "path": "/code/models/<selected>",
    "serving": "http",
    "served_name": "datamate",
    "revision": "<hf-commit-sha>",
    "dtype": "bfloat16",
    "quantization": null,
    "max_model_len": 32768,
    "gpu_memory_utilization": 0.90,
    "max_num_seqs": 64,
    "enable_prefix_caching": true,
    "reasoning_parser": null,
    "replicas": 2,
    "tensor_parallel_size": 1,
    "base_port": 8100,
    "startup_timeout_s": 900,
    "extra_server_args": []
  },
  "decoding": {
    "temperature": 0.0,
    "top_p": 1.0,
    "seed": 20261116,
    "stages": {
      "rule_profile": {"max_tokens": 2048, "enable_thinking": false},
      "compile":      {"max_tokens": 4096, "enable_thinking": false},
      "parse":        {"max_tokens": 1024, "enable_thinking": false},
      "solve":        {"max_tokens": 2048, "enable_thinking": false},
      "repair":       {"max_tokens": 2048, "enable_thinking": false},
      "fallback":     {"max_tokens": 3072, "enable_thinking": false}
    }
  },
  "concurrency": {"questions_per_replica": 24, "setup_workers": 8, "setup_threads_per_business": 4, "sandbox_workers": 16},
  "deadlines": {
    "model_call_timeout_s": 120,
    "question_soft_s": 120,
    "question_hard_s": 300,
    "target_finish_s": 9000,
    "degrade_if_projected_finish_s": 14400,
    "global_hard_stop_s": 19800
  },
  "exec_limits": {
    "sql_timeout_s": 20, "python_timeout_s": 30,
    "memory_limit_mb": 8192, "max_result_rows": 1000, "duckdb_threads": 1
  },
  "solver": {
    "max_repairs": 2, "fewshot_k": 3,
    "context_budget_tokens": 24000, "schema_card_budget_tokens": 8000,
    "readme_budget_tokens": 2000, "python_fallback": false
  },
  "features": {
    "rule_profile": false, "lunar": false, "entity_linker": false,
    "compiled_views": false, "compiled_views_categories": null, "verifier_features": false,
    "calibrator": false, "multi_strategy": false
  },
  "decision": {"policy": "rule_gate", "calibrator_path": null, "threshold": 0.5,
               "abstain_on_zero_coverage": true},
  "formatting": {"rounding": "ROUND_HALF_UP", "integer_literal_when_integral": true,
                 "tie_code_order": "numeric_if_all_numeric_else_lexicographic"},
  "ingest": {
    "numeric_accept_rate": 0.98, "date_accept_rate": 0.98,
    "max_header_scan_rows": 20, "low_cardinality_max": 50, "top_values_max": 30,
    "max_file_mb": 2048
  },
  "entities": {"top_k": 5, "strong_threshold": 85, "weak_threshold": 70},
  "logging": {"progress_interval_s": 60, "max_output_rows_logged": 50}
}
```
Notes:
- `enable_thinking: false` everywhere is **[DEFAULT DEC-10]**.
- `reasoning_parser` is set by DEC-3 (e.g. `qwen3` for Qwen models). It MUST be set whenever any stage enables thinking, so reasoning arrives in `reasoning_content` rather than inside `content`.
- `decision.policy = "rule_gate"` is **[DEFAULT DEC-8]**.
- `features.compiled_views = false` is **[DEFAULT DEC-4]**.
- `max_num_seqs` and `questions_per_replica` are fixed; they MUST NOT be tuned at run time (AP §6.11).
- `global_hard_stop_s` = 5 h 30 min leaves 30 minutes of the 6-hour limit for finalization and safety.

---

## 7. Component specifications

Each component lists: owner, interface, behavior, failure handling, budget, and required tests. Function signatures are normative names and types; internal structure is free.

### 7.0 Input loading (owner M4, in `run.py`)
- Read `/data/questions.jsonl` as UTF-8 (BOM tolerated). Each non-blank line is parsed independently.
- A line that is not valid JSON, or lacks `id`, is skipped and counted in `run.json.errors` (it cannot be answered without an id).
- A line with an `id` but other invalid fields becomes a `Question` that is abstained with the matching input reason code.
- Duplicate `id`: the first occurrence is processed; later occurrences are ignored and counted. Exactly one submission line per distinct id.
- `/data/data/<business_id>/` directories are discovered by listing; businesses with no questions are not set up.

### 7.1 C1 Split Bootstrap (owner M2)
```python
async def bootstrap_split(data_dir: Path, cfg: RunConfig, client: ModelClient) -> SplitContext
```
1. **Rulebook.** Read `rulebook.md` bytes; decode as UTF-8 (strip BOM); NFC-normalize; store verbatim. Missing or unreadable → `rulebook_text = ""`, warning `W_RULEBOOK_MISSING`; the run continues with generic parameters.
2. **Calendar.** Read `calendar.csv`. Column mapping uses an alias table (solar date; lunar year, month, day; leap flag) **[VERIFY against the actual file at M0]**. Validation: solar dates strictly increasing by one day without gaps; lunar fields within range. Failure → `calendar_ok = false`; lunar features unavailable; warning `W_CALENDAR_INVALID`.
3. **TemporalParams (P1, SC-1).** One model call, stage `rule_profile`, template `rules.temporal.v1`, JSON-schema-constrained output: for each field of §5.5, `{value, span}` where `span` is a verbatim rulebook quote or null.
   - Validation per field: `span` MUST be a substring of the rulebook after whitespace collapsing; `value` MUST be in the allowed set. A field failing either check takes the generic fallback with `provenance.source = "generic"`.
   - If the rulebook is empty, the call is skipped and all fields are generic.
   - The call runs on replica 0 before any question is dispatched; its `ModelCall` is stored in `run.json.split.calls`.
4. **RuleProfile (P2, `features.rule_profile`).** Same pattern with template `rules.profile.v1`; adds `holidays`, `default_rank_criterion`, `definitions`. Each holiday is validated by resolving it for every lunar year covered by the calendar; a holiday that fails resolution is dropped and named in `unresolved`.

Tests: rulebook verbatim round-trip (byte equality after NFC); span validation rejects paraphrases; generic fallback on empty rulebook; calendar validator on fixtures with a gap, a duplicate, and a leap month.

### 7.2 C2 Ingestion & Catalog (owner M1)
```python
def setup_business(business_dir: Path, bkey: str, cfg: RunConfig) -> BusinessCatalog   # runs in setup pool
```

#### 7.2.1 Discovery
- Files directly under the business directory (recursive one level for subfolders) with extensions `.csv`, `.tsv`, `.txt` (only if delimiter sniffing succeeds), `.xlsx`, `.xlsm`, `.xls` (via calamine), `.sqlite`, `.sqlite3`, `.db`. Sorted by relative path (byte order) for deterministic table order.
- `README.md` (case-insensitive) is read verbatim into `readme_text`.
- Files larger than `ingest.max_file_mb` are skipped with `W_FILE_TOO_LARGE`.

#### 7.2.2 CSV
- Encoding detection order: UTF-8-SIG → UTF-8 → `charset-normalizer` best guess restricted to {cp1258, utf-16, windows-1252} → latin-1 (with `W_ENCODING_FALLBACK`).
- Dialect: sniff delimiter among `, ; \t |` on the first 64 KB; quote char `"`.
- All cells read as strings first; typing happens in §7.2.5.

#### 7.2.3 Excel
- Read every sheet with `python-calamine`; `openpyxl` only if calamine fails on a file (`W_READER_FALLBACK`).
- Cells keep their native type from the reader (number, datetime, string, bool). Date-typed cells are dates; numeric cells in date-hinted columns are tested as Excel serials (§7.2.6).
- **Table block detection:** a block is a maximal run of rows separated from others by ≥ 2 fully blank rows **or** by a new header row. Each block becomes one table.
- **Header detection:** within the first `max_header_scan_rows` rows of a block, choose the row maximizing `score = 0.5·text_ratio + 0.3·uniqueness + 0.2·type_consistency_below`, where `text_ratio` is the share of non-empty string cells, `uniqueness` the share of distinct non-empty values, and `type_consistency_below` the share of columns whose next 20 rows are type-consistent. Rows above the header are title rows (recorded in `TableInfo.dropped_rows` as notes). If the row directly above the header is partially filled and the header has blanks, the two rows are merged (`"<upper> <lower>"`). Ties choose the earliest row.
- **Total rows:** a row is a total row if its first non-empty text cell, folded, matches `^(tong( cong)?|cong|total|grand total|sum|tong so)\b` **and** at least one numeric cell equals the sum of that column over the preceding rows of the block within 0.5% (or the row is the last data row of the block). Total rows are dropped (`W_TOTAL_ROW_DROPPED`, with row index).
- **Note rows:** trailing rows with exactly one non-empty text cell are dropped as notes.

#### 7.2.4 SQLite (SC-3)
- Opened with the Python standard library: `sqlite3.connect("file:<path>?mode=ro&immutable=1", uri=True)` so nothing is written to `/data` (no journal or WAL files).
- Each user table and view (excluding `sqlite_%`) is read with `SELECT *` and loaded into DuckDB through Arrow. Declared SQLite types are kept in `format_note`; values pass through the same typing step as CSV columns when stored as text.
- The DuckDB `sqlite` extension MUST NOT be used (it would be downloaded at run time).

#### 7.2.5 Numeric parsing
Applied per column to string values. Null tokens (after trim, case-folded): `""`, `na`, `n/a`, `null`, `none`, `nan`, `-`, `--`, `—`.
- Strip whitespace and NBSP; strip currency tokens (`đ`, `₫`, `vnd`, `vnđ`, `dong`, `đồng`) and a trailing `%` (sets `semantic_hint = percent`).
- Magnitude suffixes (case-insensitive, accent-folded): `k`, `nghin`, `ngan` = 10³; `tr`, `trieu` = 10⁶; `ty`, `ti` = 10⁹. Compound form `<int><suffix><digits>` means `<int>.<digits> × suffix` (e.g. `1tr2` = 1,200,000; `2k5` = 2,500).
- **Separator convention is chosen per column** by evaluating three conventions on all values — `VN` (`.` thousands, `,` decimal), `EN` (`,` thousands, `.` decimal), `PLAIN` (no thousands separator, `.` decimal) — and selecting the one with the highest parse rate; ties are broken by evidence count (values that parse under only one convention), then in the order `VN`, `EN`, `PLAIN`. Columns where conventions remain tied with conflicting results get `W_NUMERIC_AMBIGUOUS` and stay `VARCHAR`.
- A column becomes numeric if its parse rate ≥ `numeric_accept_rate`. Unparsable values become NULL **and** the original column is kept as `<name>__raw VARCHAR`.
- Target SQL type: `BIGINT` if every parsed value is integral and fits in int64; otherwise `DECIMAL(38,6)` if every value has ≤ 6 fractional digits; otherwise `DOUBLE`. (SC-4: exact types keep large VND sums exact.)

#### 7.2.6 Date parsing
- Candidate formats: `yyyy-mm-dd`, `dd/mm/yyyy`, `mm/dd/yyyy`, `dd-mm-yyyy`, `dd.mm.yyyy`, `yyyy/mm/dd`, `dd/mm/yy`, `yyyy-mm`, `mm/yyyy`, and each with an optional time part; Excel serials 20000–80000 in columns whose header (folded) contains `ngay`, `date`, `thoi gian`, `time`, `thang`, or `month`.
- Day/month order is decided per column: any value with first field > 12 forces day-first; any with second field > 12 forces month-first; conflicting evidence → `W_DATE_AMBIGUOUS`, keep `VARCHAR`; no evidence → day-first (Vietnamese locale convention) with `W_DATE_ASSUMED_DMY`.
- A column becomes `DATE` (or `TIMESTAMP` if any non-midnight time appears) when its parse rate ≥ `date_accept_rate`; raw column kept as for numbers. Month-only columns become `DATE` on the first of the month with `format_note = "month"`.

#### 7.2.7 Identifiers (SC-2)
- Table names: `<file_stem>` (CSV), `<file_stem>__<sheet>[_<block>]` (XLSX), `<file_stem>__<table>` (SQLite).
- Column and table identifiers are derived by accent-folding (§7.6.1), lowercasing, replacing non-alphanumerics by `_`, collapsing repeats, trimming `_`, prefixing `c_` if starting with a digit, and suffixing `_2`, `_3`… on collision, in source order.
- The original header is always kept in `original_name` and shown in the SchemaCard. **Data values are never folded or altered.**

#### 7.2.8 Profiling
For each column: null rate, exact distinct count, min/max, and `top_values`: all values with counts if distinct count ≤ `low_cardinality_max`, else the `top_values_max` most frequent (ties by value ascending). `semantic_hint` from header keywords (folded): `ma`, `code`, `id` → code; `ten`, `name` → name; `trang thai`, `status` → status; `gia`, `tien`, `doanh thu`, `amount`, `price`, `cost` → money; `so luong`, `sl`, `qty`, `quantity` → quantity.
- **Candidate keys:** single columns with distinct count = row count and no nulls; two-column keys only for tables ≤ 50 columns.
- **Joins:** for column pairs across tables with compatible types where the folded names match (exact, or one equals the other plus/minus a table-name token) **or** value containment ≥ 0.95 into a candidate key: record `JoinEdge` with `match_rate` = share of non-null left values found on the right. Only edges with `match_rate ≥ 0.90` are kept.
- **Date coverage:** `date_columns` for every DATE/TIMESTAMP column; `data_range` = union of ranges over tables that are not low-cardinality dimension tables (row count > 200 or with a money/quantity column).

#### 7.2.9 SchemaCard
Deterministic plain text, in table order, then joins, then date coverage, then warnings. Format:
```
TABLE orders  (12,345 rows; source orders.xlsx › "Đơn hàng")
  order_id     BIGINT        key  nulls 0%     1..12345              ["Mã đơn"]
  status       VARCHAR             nulls 0%     values: "Hoàn thành"(9800), "Đã hủy"(1200), "Trả hàng"(345)
  amount       BIGINT              nulls 0.2%   0..48500000   money   ["Thành tiền"]
JOIN orders.customer_id → customers.customer_id  (n:1, 99.8%)
DATES orders.order_date 2024-01-01..2025-06-30
WARN W_TOTAL_ROW_DROPPED orders row 12346
```
- Budgeted with the model tokenizer to `schema_card_budget_tokens`. Reduction order when over budget: (1) top values of high-cardinality columns trimmed to 10; (2) then to 5; (3) `relevant-subset` mode at question time (§7.7.1). The full card is always stored in the business log.
- The SchemaCard format is a **consumer-visible contract** for M3 (prompts) and M2 (catalog check). A format change requires consumer tests to pass (§14.4) and a note in the merge request.

#### 7.2.10 Materialization
- Create `/tmp/datamate/biz/<bkey>/catalog.duckdb` with `duckdb.connect(path, config={"threads": concurrency.setup_threads_per_business, "autoinstall_known_extensions": false, "autoload_known_extensions": false})`, load tables via Arrow, create views (P2), `CHECKPOINT`, close. The file is then opened read-only by C8 only.
- Business setup failure (any uncaught exception) → `status = failed`, all its questions abstain with `E_BUSINESS_SETUP`.

Tests: fixture files for every rule above (title rows, merged headers, two blocks per sheet, totals, note rows, `1.250.000`, `1,5`, `150k`, `1tr2`, `12,5%`, ambiguous `01/02/2025`, Excel serials, cp1258 CSV, SQLite with WAL mode on read-only filesystem); idempotence (two setups produce byte-identical SchemaCards); budget: 300k-row XLSX ≤ 60 s on the reference CPU class.

### 7.3 C3 Semantic Compiler (P2, `features.compiled_views`, owner M1)
```python
async def compile_semantics(cat: BusinessCatalog, split: SplitContext, client: ModelClient, replica: int) -> SemanticAnnotations
```
- One model call (template `semantics.compile.v1`) with rulebook, README, SchemaCard; output schema: table roles, value semantics, and up to 8 `ViewSpec` proposals for core rulebook definitions.
- Each view: DDL must be `CREATE VIEW v_<name> AS SELECT …` only; created in the setup connection; validation checks — executes without error; non-empty; no duplicate values in declared key columns; for money views, `SUM(view) ≤ SUM(source)` where the rule implies exclusion. Failing views are dropped (`enabled = false`, kept in the log).
- Views are exposed to the solver with their DDL and purpose. Per-category kill switch: `features.compiled_views_categories` (list) MAY restrict use.
- All compile calls go to the business log; per-question logs reference views via `views_used` with DDL hash.

### 7.4 C4 Question Parser (owner M3)
```python
async def parse_question(q: Question, split: SplitContext, cat: BusinessCatalog, client: ModelClient, replica: int) -> tuple[QuestionFrame | None, ModelCall]
```
- **Normalization:** `normalized_question` = original with abbreviation expansion from `lexicon/abbrev_vi.tsv` (token-wise, matched on folded lowercase tokens, whole tokens only). Both original and normalized text are sent; the original is authoritative.
- **Call:** template `parse.frame.v1`, JSON schema = `QuestionFrame` schema (exported), `max_tokens` from `decoding.stages.parse`. Context: rulebook, SchemaCard (subset allowed), `as_of_date`, question.
- **Validation:** pydantic validation and §5.9 invariants. Invalid output → **no retry** in P1; question abstains with `E_PARSE_INVALID`.

### 7.5 C5 Temporal Resolver (owner M2)
```python
def resolve_windows(frame: QuestionFrame, as_of: date, params: TemporalParams,
                    calendar: LunarCalendar | None, data_range: DateRange | None) -> list[TimeWindow]
```
Pure function; no I/O; no model calls. Resolution rules (`a` = `as_of_date`):

| `kind` | Rule |
|---|---|
| `date` | `[d, d]`, granularity `day` |
| `date_range` | `[start, end]`; missing year → `year_omitted_policy` applied to `start`, `end` gets the same year (next year if end < start) |
| `calendar_period` | Period identified by unit/index/year; `year = null` → the latest year whose period start ≤ `a`; `unit = week` uses `week_start` and ISO week numbering |
| `relative_period` | Let P₀ be the period of `unit` containing `a` (weeks per `week_start`). Pₖ = P₀ shifted by `offset`. If `offset = 0` and `to_date`: end = `a` (or `a − 1` if `to_date_end = day_before_as_of`). If `offset = 0` and not `to_date`: full P₀, flag `F_WINDOW_EXTENDS_PAST_AS_OF` if end > `a`. If `offset < 0`: full Pₖ |
| `rolling` | end = `a` if `rolling_includes_as_of` else `a − 1`; `day`: start = end − (count − 1); `week`: start = end − (7·count − 1); `month`: start = (end − count months) + 1 day, day-of-month clamped |
| `same_period_prior_year` | The referenced window shifted by −1 year; `calendar_dates`: same month/day, 29 Feb → 28 Feb; `elapsed_days`: same length ending at shifted end |
| `all_time` | `data_range` if known (granularity `range`); else no window and flag `F_NO_DATA_RANGE` |
| `lunar_holiday` (P2) | lunar year = lunar year of `a` + `year_offset`; anchor = `to_solar(anchor)`; window = `[anchor + start_offset, anchor + end_offset]` from the matching `HolidayWindow`. No match or `calendar_ok = false` → `E_TIME_UNSUPPORTED` |
| `lunar_date_range` (P2) | Convert lunar start/end with `to_solar`; leap month only if the rulebook says so |
| `unsupported` | `E_TIME_UNSUPPORTED` |

- `coverage_ratio` = |window ∩ data_range| / |window| in days.
- In P1 any `E_TIME_UNSUPPORTED` makes the question abstain (AP §7.1).
- Provenance lists every `TemporalParams` field consulted and its source.

Tests: table-driven cases for every row, crossing year boundaries, leap years, week starts Monday and Sunday, `to_date_end` both values, Tết spanning two solar years (P2), plus a property test: `start ≤ end` and window length matches the rule for 10,000 random `(a, expr)` pairs.

### 7.6 C6 Entity Linker (P2, `features.entity_linker`, owner M1)
#### 7.6.1 Folding function (shared, in `lexicon/fold.py`)
`fold(s)` = NFD → remove combining marks (U+0300–U+036F) → map `đ/Đ` → `d` → lowercase → replace non-alphanumerics by space → collapse spaces. Used **only** for retrieval keys, SQL identifiers (SC-2), and keyword matching. Never applied to output values or scorer input (DEC-11). `fold()` is part of `lexicon`'s public API and is used by M1, M2, and M3; its behavior is frozen at I0 and changes follow §15 like a contract.

#### 7.6.2 Index and query
- Index: for every `VARCHAR` column with `semantic_hint` in {name, code, status} or distinct count ≤ 100,000: map `fold(value)` → (table, column, value, code), where `code` is the value of a code column in the same row if a 1:1 code column exists.
- Query per mention: candidates by exact folded match, then `rapidfuzz.fuzz.token_set_ratio` and `partial_ratio` (score = max) against folded values; keep scores ≥ `weak_threshold`, top `top_k`, ties by (table, column, value) ascending.
- `strength = strong` if score ≥ `strong_threshold`.

### 7.7 C7 Solver (owner M3)
```python
async def solve(q: Question, frame: QuestionFrame, windows: list[TimeWindow],
                cands: list[EntityCandidate], cat: BusinessCatalog, sem: SemanticAnnotations | None,
                split: SplitContext, client: ModelClient, executor: Executor,
                replica: int, deadline: Deadline) -> list[SolverAttempt]
```

#### 7.7.1 Context pack (fixed order, for prefix-cache reuse)
| # | Section | Shared across | Budget rule |
|---|---|---|---|
| 1 | System instructions (template) | run | fixed |
| 2 | Rulebook (verbatim) | run | never truncated |
| 3 | README | business | ≤ `readme_budget_tokens`, head-truncated with marker |
| 4 | SchemaCard | business | ≤ `schema_card_budget_tokens` |
| 5 | Validated views (P2) | business | full DDL |
| 6 | Few-shot examples | question | `fewshot_k`, dropped last-first when over budget |
| 7 | Question block: original + normalized question, `as_of_date`, QuestionFrame JSON, resolved windows as literal dates, entity candidates, type contract and SQL rules for the expected type | question | — |

- Sections 1–5 are rendered identically for every question of a business (byte-identical) so the server's prefix cache applies.
- Total MUST be ≤ `context_budget_tokens`. Reduction order: few-shot examples → README → SchemaCard relevant-subset mode (tables ranked by folded-token overlap with question, metric, and mentions; full column lists for the top 4 tables, names only for the rest). If still over budget → `E_CONTEXT_OVERFLOW` (abstain).
- Token counts use the model tokenizer loaded from `model.path` with `local_files_only=True`.

#### 7.7.2 Few-shot bank
- File: `/code/src/datamate/assets/fewshot.jsonl`, built by `training_code/data_generation/build_fewshot.py` from the **training split only** (§13.2). Entry: `{entry_id, source_business_id, question, frame, sql, expected_type, schema_excerpt}`.
- Selection: score = `token_set_ratio(fold(question + metric_text), fold(entry.question + entry.metric))`, bonus +10 for same `expected_type`; top `fewshot_k`, ties by `entry_id`.
- In cross-validation, entries whose `source_business_id` belongs to the evaluated fold MUST be excluded (leakage guard, tested).

#### 7.7.3 Model output and SQL rules
Template `solve.sql.v1`; JSON schema `SolverOutput`. Rules stated in the prompt **and** enforced by `check_sql` before execution:

| Rule | Enforcement | Violation |
|---|---|---|
| Exactly one statement, type SELECT (incl. `WITH`) | `duckdb` `extract_statements` → one statement with type SELECT | `E_SQL_NOT_SELECT` |
| Only catalog tables and validated views | executed against a read-only DB with external access disabled (§7.8) | `E_SQL_EXEC` |
| Scalar shape: 1 row × 1 column (`value` or `answer_column`) | contract check | `E_TYPE_CONTRACT` |
| List shape: columns `item`, `sort_key`, `tie_code` | contract check | `E_TYPE_CONTRACT` |
| Table shape: ≥ 1 column; column names per conventions (§7.10) | contract check | `E_TYPE_CONTRACT` |
| `LIMIT` requires `ORDER BY` | token check outside string literals | `E_SQL_NONDETERMINISTIC` |
| Percent values in percent units | prompt + verifier plausibility | flag `F_PERCENT_SCALE` if all \|v\| ≤ 1.5 |
| Month dates as `DATE` (first of month) or `'yyyy-mm'` text | contract check | `E_TYPE_CONTRACT` |

#### 7.7.4 Attempt loop
```
attempt 1: solve (stage=solve)
while not ok and repairs < max_repairs and not deadline.soft_expired and not degrade:
    repair (stage=repair): conversation = [context, question, previous assistant output,
                                            user message with the error code and error_text or contract violation]
P2: if still not ok, or frame.needs_procedural and python_fallback:
    fallback (stage=fallback, template solve.python.v1) + at most 1 fallback_repair
```
- `ok` = model output valid **and** execution succeeded **and** contract check passed **and** result non-empty.
- The repair conversation reuses sections 1–7 verbatim, appending turns, so the prefix stays cached.
- Each attempt is a `SolverAttempt`; all are passed to C9 and logged in order.

#### 7.7.5 Result → TypedValue (`to_typed_value`)
| Expected type | Rule |
|---|---|
| `number` | Single cell → `Decimal`; NULL → empty result |
| `percent` | Single cell → `Decimal` (already percent units) |
| `string` | Single cell → `str` exactly as stored |
| `date` | `DATE` → value; `'yyyy-mm'` text → first of month with granularity `month`; granularity from `frame.date_granularity` |
| `boolean` | Single cell BOOLEAN, or integer 0/1 → bool |
| `list` | Rows → `{item, sort_key, tie_code}` |
| `table` | Columns and rows as returned |

### 7.8 C8 Sandbox Executor (owner M3)
- Custom worker pool of `sandbox_workers` processes (`multiprocessing`, spawn). Each worker sets `RLIMIT_AS = memory_limit_mb + 2048 MB`, works in `/tmp/datamate/sandbox/<pid>/`, and caches one read-only connection per `db_path`:
  ```python
  duckdb.connect(db_path, read_only=True, config={
      "threads": 1, "memory_limit": f"{memory_limit_mb}MB",
      "enable_external_access": False,
      "autoinstall_known_extensions": False, "autoload_known_extensions": False})
  # then: SET lock_configuration = true
  ```
- Fetch with `fetchmany(max_result_rows + 1)`.
- Value encoding to the parent: tagged JSON (§5.7). `DOUBLE` values are converted with `Decimal(repr(x))`; `DECIMAL` values stay `Decimal`; dates as ISO strings. The encoder lives in `sandbox/encode.py` and is shared with `FakeExecutor`, so both produce identical results.
- **Timeout:** the parent waits `sql_timeout_s`; on expiry it `SIGKILL`s the worker, spawns a replacement, and returns `E_SQL_TIMEOUT`. A crashed worker returns `E_EXEC_CRASH` and is replaced.
- **Python fallback (P2):** code MUST define `def solve(con):`; executed with `exec` in a fresh namespace whose `__import__` allows only `math, statistics, datetime, decimal, fractions, collections, itertools, functools, operator, re, json, pandas, numpy`. `open`, `eval`, `exec`, `compile`, `input`, and `__import__` of other modules raise. Return value: scalar, list, `pandas.DataFrame`, or `pandas.Series`, converted to `ExecutionResult` rows. This is a fault boundary, not a security boundary.
- `ExecutionResult.code` is the exact text executed; `helper_call` is set when the code is a call to a packaged helper (DG §3.3).

Tests: infinite recursive CTE terminated at timeout; 100 GB cross join rejected by memory limit; `COPY … TO` and `read_csv('/etc/passwd')` rejected; `ATTACH` rejected; concurrent read-only access from 16 workers to one DB file; Decimal round-trip exactness for 10¹⁴-scale sums.

### 7.9 C9 Verifier & Decision (owner M2)
```python
def decide(q: Question, frame: QuestionFrame | None, windows: list[TimeWindow],
           attempts: list[SolverAttempt], cat: BusinessCatalog, cfg: RunConfig,
           pipeline_error: ReasonCode | None) -> Decision
```
**Rule gate (P1, `decision.policy = rule_gate`)** — evaluated in order; the first matching rule decides:

| # | Condition | Decision | Reason code |
|---|---|---|---|
| 1 | `pipeline_error` set (input, setup, parse, time, context, deadline, internal) | abstain | that code |
| 2 | `frame.answerability.status = missing_field` **and** every named field fails the catalog check below | `unanswerable` (`reason = "missing_field:<f1>[,<f2>]"`) | `D_UNANSWERABLE_CONFIRMED` |
| 3 | No attempt with `ok = true` | abstain | last attempt's error code, else `E_NO_SUCCESS` |
| 4 | Final attempt result converts to a `TypedValue` whose type ≠ `frame.expected_type` | abstain | `E_TYPE_CONTRACT` |
| 5 | Any primary window with `coverage_ratio = 0` and `decision.abstain_on_zero_coverage` | abstain | `D_OUT_OF_RANGE` |
| 6 | Value is NaN/Infinity, or a percent with \|v\| > 100,000 | abstain | `D_IMPLAUSIBLE` |
| 7 | Otherwise | answer | `D_ANSWER` |

- **Catalog check for missing fields:** a field is *absent* if `max(token_set_ratio(fold(field), fold(name)))` over all column `name`, `original_name`, and `semantic_hint` values is < 60, and no README line contains the folded field as a substring. A field found by this check means the model's hint is not trusted (rule 2 does not fire).
- `features` always records: `n_attempts`, `n_repairs`, `used_fallback`, `row_count`, `min_coverage`, `temporal_generic_params`, `span_mismatch`, `percent_scale_flag`, `degrade`.
- **P2 verifier features** (`features.verifier_features`) add magnitude z-score against column range, entity strength, and window flags; in P2 they are only recorded.
- **P3 calibrator** (`decision.policy = calibrator`): `p_correct = model(features)`; answer iff `p_correct ≥ threshold`; rules 1–6 still apply first.

### 7.10 C10 Formatter (owner M2)
```python
def to_submission(q_id: str, d: Decision, cfg: RunConfig) -> SubmissionRecord
```
| Type | Wire value |
|---|---|
| `number` | `Decimal.quantize(Decimal("0.01"), rounding=cfg.formatting.rounding)`; `-0` → `0`; if integral and `integer_literal_when_integral` → JSON integer, else JSON number with trailing zeros removed (`12.50` → `12.5`). **[VERIFY rounding mode and int/float handling, Q5]** |
| `percent` | Same as number; value already in percent units |
| `string` | Stored value, leading/trailing whitespace trimmed, otherwise unchanged (NFC) |
| `date` | `yyyy-mm-dd` (granularity `day`) or `yyyy-mm` (granularity `month`) |
| `boolean` | JSON `true` / `false` **[VERIFY]** |
| `list` | Sort by `sort_key` (descending for `top`, ascending for `bottom`), then `tie_code` ascending per `tie_code_order`, then `item`; truncate to `k` (all if fewer); emit JSON array of `item` values. **[VERIFY wire shape against Brief §2.2]** |
| `table` | `{"columns": [...], "rows": [[...], ...]}` with numeric cells formatted as `number`. Column naming follows training-reference conventions documented by M2 in `formatting/table_conventions.md`. **[VERIFY wire shape against Brief §2.2]** |
| `unanswerable` | `{"id", "type": "unanswerable", "reason"}` |
| `abstain` | `{"id", "type": "abstain"}` |

- Serialization uses a custom encoder that writes `Decimal` as a JSON number literal (never a string, never via float), `ensure_ascii=False`, separators `(",", ":")`, key order `id, type, answer|reason`.
- **Independent oracle.** The formatter (M2) and the scorer (Lead, §7.14) are written by different people and MUST both pass the shared goldens in `tests/golden/`. A change to a golden requires approval from both owners.

### 7.11 C11 Persistence & Compliance Logging (owner M4)
- A single writer task consumes `(SubmissionRecord, LogRecord)` pairs from an asyncio queue.
- For each pair: append the log line to `questions.jsonl`, `flush`, `os.fsync`; then append the submission line to `submission.jsonl`, `flush`, `os.fsync`. (Order guarantees no answer exists without its log record.)
- Rejects a second record for an id already written (`E_DUPLICATE_WRITE`, logged in `run.json`).
- Files are opened in append mode at start. In production the result directory is expected empty; if `submission.jsonl` already exists, it is renamed to `submission.jsonl.prev-<n>` before starting (never deleted). Resume mode exists only in the dev harness.
- Formats: §8.

### 7.12 C12 Orchestrator (owner M4)
1. **Grouping and order.** Group questions by `business_id`; order businesses by (question count descending, `business_id` ascending); questions within a business by `line_no`.
2. **Replica assignment.** In that order, assign each business to the replica with the smaller assigned question total (tie → lower index). Assignment is computed before any work starts and logged.
3. **Setup.** Business setups are submitted to the setup pool in the same order. A business's questions are enqueued on its replica queue when its catalog is `ready` and the split context is ready.
4. **Workers.** Each replica has `questions_per_replica` worker coroutines pulling from its queue. A question's `elapsed_ms` starts when a worker takes it (it enters its batch) and ends when its records are handed to the writer.
5. **Per-question pipeline:** normalize → C4 → C5 → (P2) C6 → C7/C8 → C9 → C10 → C11. Any exception is caught at the question boundary → abstain with `E_INTERNAL`, traceback in `run.json.errors` (first 100).
6. **Deadlines.** Soft (`question_soft_s`): no new repair or fallback starts. Hard (`question_hard_s`): the question task is cancelled → abstain `E_DEADLINE`.
7. **Degrade mode.** Every `progress_interval_s`, projected finish = elapsed + remaining questions × recent mean per-question throughput time. If projected finish > `degrade_if_projected_finish_s`, set degrade (no repairs, no fallback, no P3) for the rest of the run; record activation time. Degrade mode is a safety net and is expected never to activate on the reference hardware.
8. **Global stop.** At `T0 + global_hard_stop_s`, cancel all work, write `abstain` (`E_GLOBAL_STOP`) for every unwritten id, finalize.
9. **SIGTERM:** same as global stop, immediately.
10. **Replica failure:** one restart attempt; while down, its queue is drained to the other replica. Events logged.
11. **Stub mode (dev only).** With `--dev --stub <stage>`, the pipeline uses the stand-in for that stage (§5.10), so the lead can integrate stages one at a time (TASKS L-05).

### 7.13 C13 Model Serving (owners M4: replicas; M3: client)
#### 7.13.1 Replica launch
For replica `i` (`0 ≤ i < model.replicas`):
```
CUDA_VISIBLE_DEVICES=i  python3 -m vllm.entrypoints.openai.api_server \
  --model <model.path> --served-model-name <served_name> --dtype <dtype> \
  --max-model-len <max_model_len> --gpu-memory-utilization <gpu_memory_utilization> \
  --max-num-seqs <max_num_seqs> --seed <decoding.seed> \
  --host 127.0.0.1 --port <base_port + i> \
  [--enable-prefix-caching] [--reasoning-parser <reasoning_parser>] [--quantization <q>] \
  --generation-config vllm  <extra_server_args...>
```
- `--generation-config vllm` prevents the checkpoint's `generation_config.json` from changing sampling defaults. Flag names MUST be re-checked against the vLLM version fixed by DEC-3 **[VERIFY]**; multimodal checkpoints add the flag that disables image/video inputs for that version.
- Server stdout/stderr go to `/result/logs/replica-<i>.log`.
- Readiness: poll `GET /health` until 200 or `startup_timeout_s`; then one warm-up request (fixed prompt, `max_tokens = 8`). Load time per replica is recorded in `run.json`.
- TP contingency (DEC-13): `replicas = 1`, `tensor_parallel_size = 2`, `CUDA_VISIBLE_DEVICES=0,1`, with the DG §9 NCCL settings.

#### 7.13.2 Client request
`POST /v1/chat/completions` with: `model`, `messages`, `temperature`, `top_p`, `max_tokens`, `seed`, `n = 1`, `response_format = {"type": "json_schema", "json_schema": {"name": <template_id>, "schema": <schema>, "strict": true}}` when a schema is given, and `chat_template_kwargs = {"enable_thinking": <bool>}`. Every parameter is sent explicitly on every call.
- Transport error: one retry of the identical request. Timeout (`model_call_timeout_s`): no retry; `ModelCall.error = "E_MODEL_TIMEOUT"`.
- `request_sha256` = SHA-256 of the canonical JSON of the request body.
- The client returns `content` and `reasoning_content` exactly as received.

#### 7.13.3 In-process fallback
If loopback serving is unavailable, `AsyncLLM` engines with identical engine arguments implement the same `ModelClient` protocol. Selected by `model.serving = "inprocess"` (default `"http"`). It MUST pass the `ModelClient` conformance suite.

#### 7.13.4 Tokenizer
Loaded once per process from `model.path` (`local_files_only=True`) for budget counting with the model's chat template.

#### 7.13.5 Prompt templates
- Stored as `datamate/prompts/<template_id>.j2` (Jinja2), rendered with `StrictUndefined`.
- IDs (P1): `rules.temporal.v1`, `parse.frame.v1`, `solve.sql.v1`, `repair.sql.v1`. (P2): `rules.profile.v1`, `semantics.compile.v1`, `solve.python.v1`, `repair.python.v1`.
- Any wording change creates a new version suffix; the SHA-256 of every template is recorded in `run.json`. Templates MUST NOT contain business- or question-specific content.
- Templates used by other members' components (`rules.*` for M2, `semantics.*` for M1) are owned by M3 for rendering and versioning; their content is co-authored with the consuming member, who must approve wording changes.
- A template version change MUST refresh the recorded `ModelCall` fixtures that depend on it in the same merge (TASKS M3-13); otherwise `ReplayModelClient` returns `E_REPLAY_MISS` and CI fails.

### 7.14 C14 Evaluation Harness (owner Lead)
- `score_one(pred: SubmissionRecord | None, ref: ReferenceRecord) -> Literal[1, 0, -1]` implementing Brief §2.1–2.2 exactly; `PA = Σ score / N`.
- Entry point: `python -m datamate.eval.harness --config <file> --data-dir <split> --answers <answers.jsonl> --out <dir> [--fold k] [--resume] [--dev --set key=value ...]`. It calls the same `datamate.run.main` as production.
- Folds: businesses sorted by `sha256(business_id)`, fold = rank mod 5 (dev only). Leave-type-out uses `eval/business_types.json` (manual labels, Lead, M0).
- Reports: PA, accuracy on answered, coverage, `unanswerable` precision/recall, per type, per reason code, per component that raised the reason code, per category if the training data provides categories **[VERIFY]**, latency p50/p95, projected runtime at 500 and 1,000 questions.
- **Run record** (`<out>/run_record.json`): config and overrides, git commit, contracts version, template hashes, environment fingerprint (GPU name, driver, CUDA, torch, vLLM, DuckDB, Python, lock hash), data snapshot hash, model revision, per-question outcome, timing.
- **Comparability.** `compare_runs(a, b)` reports identical lines, changed lines, and ΔPA. It refuses to compare runs whose environment fingerprint, data snapshot hash, or model revision differ unless `--allow-env-diff` is given, and prints which differ.

---

## 8. Output file formats

### 8.1 General
UTF-8, one JSON object per line, `\n` terminated, `ensure_ascii=False`, compact separators. Field order as listed.

### 8.2 `submission.jsonl` [REQ DG §3.2]
See §5.8 and §7.10.

### 8.3 `logs/questions.jsonl` [REQ DG §3.3]
| Field | Required by | Content |
|---|---|---|
| `id` | DG | Question id |
| `answer` | DG | The submission object without `id`: `{"type", "answer"}`, `{"type": "unanswerable", "reason"}`, or `{"type": "abstain"}` |
| `elapsed_ms` | DG | Non-negative int (§7.12 step 4) |
| `thinking` | DG | `null` if no call returned reasoning; otherwise a list with one entry per model call **in call order**, each the exact `reasoning_content` or `""` for calls that returned none (SC-7) |
| `code` | DG (when executed) | `null` if nothing executed; a string if one execution; otherwise a list of exact executed texts in order |
| `output` | DG (when executed) | Execution output of the attempt that produced the answer (else the last attempt): `{"columns", "rows" (≤ max_output_rows_logged), "row_count", "truncated"}` or the error text |
| `inputs` | DG (helpers) | Actual helper arguments, when `helper_call` is set |
| `contracts_version` | SPEC | |
| `business_id` | SPEC | Audit only |
| `calls` | SPEC | List of `ModelCall` (all fields, including `content`) in call order |
| `attempts` | SPEC | `[{attempt_no, stage, language, ok, error_code, duration_ms}]` |
| `windows` | SPEC | `TimeWindow` list |
| `decision` | SPEC | `{kind, reason_code, features, p_correct}` |
| `views_used` | SPEC (P2) | `[{name, ddl_sha256}]` |
| `degrade` | SPEC | bool |

### 8.4 `logs/businesses.jsonl`
`{business_id, bkey, status, setup_ms, warnings, tables (TableInfo list), joins, data_range, schema_card, schema_card_sha256, views (P2), compile_calls (P2, full ModelCall list)}`.

### 8.5 `logs/run.json`
`{contracts_version, config (effective), config_sha256, template_sha256: {id: sha}, model: {path, revision, weights_sha256_index}, environment, replica_assignment, timings: {replica_load_ms[], first_answer_ms, total_ms}, split: {rulebook_sha256, temporal_params, rule_profile, calls}, counts: {questions, distinct_ids, answered, unanswerable, abstained, by_reason}, degrade_activated_ms, errors: [...]}`. Written at finalization; an interim copy is rewritten atomically (temp file + rename) every `progress_interval_s`.

---

## 9. Determinism requirements

| ID | Requirement | Verified by |
|---|---|---|
| D1 | Greedy decoding: `temperature = 0`, `top_p = 1`, fixed `seed`, fixed `max_tokens`, explicit `enable_thinking` on every call | Client unit test asserts every request body |
| D2 | Fixed concurrency (`questions_per_replica`, `max_num_seqs`) and fixed replica assignment (§7.12) | Config review; assignment logged and compared across runs |
| D3 | Context sections 1–5 byte-identical within a business | Test renders twice, compares bytes |
| D4 | All iteration over sets/dicts that affects output is over sorted keys | Code review checklist; `PYTHONHASHSEED=0` |
| D5 | Ingestion and SchemaCard are pure functions of the input files | Idempotence test (§7.2) |
| D6 | DuckDB query execution with `threads = 1`; exact numeric types (BIGINT/DECIMAL) | C8 tests |
| D7 | `LIMIT` only with `ORDER BY`; lists re-sorted deterministically by the formatter | §7.7.3, §7.10 tests |
| D8 | No wall-clock-dependent logic except deadlines, degrade mode, and global stop; their activations are logged | Code review; run.json |
| D9 | Library versions pinned by the lock; model revision pinned; data snapshot hashed | Run-record environment fingerprint |
| D10 | `VLLM_BATCH_INVARIANT` per DEC-3 outcome | G4 |
| D11 | Few-shot selection and entity ranking have total orders (explicit tie-breaks) | Unit tests |
| D12 | Acceptance: two runs on the same host give identical `submission.jsonl` (target) or \|ΔPA\| ≤ 0.005 (gate G4/G7) | `compare_runs` |
| D13 | CPU determinism CI: two runs on fixtures with `ReplayModelClient` produce byte-identical `submission.jsonl` and identical `questions.jsonl` after removing timing fields | §14.5, on every merge |

---

## 10. Error handling

### 10.1 Policy
Errors never propagate past a question boundary or a business boundary. Every failure maps to a reason code, and the question receives `abstain` unless rule 2 of §7.9 applies. Warnings never change a decision directly; they are recorded and MAY be verifier features.

### 10.2 Reason codes
| Code | Raised by | Meaning |
|---|---|---|
| `D_ANSWER` | C9 | Answer emitted |
| `D_UNANSWERABLE_CONFIRMED` | C9 | Confirmed missing field |
| `D_OUT_OF_RANGE` | C9 | Window outside data coverage |
| `D_IMPLAUSIBLE` | C9 | Non-finite or implausible value |
| `E_INPUT_AS_OF`, `E_INPUT_BUSINESS_MISSING` | 7.0 | Invalid input fields |
| `E_BUSINESS_SETUP` | C2/C3 | Business setup failed |
| `E_PARSE_INVALID` | C4 | QuestionFrame invalid |
| `E_TIME_UNSUPPORTED` | C5 | Expression not resolvable |
| `E_CONTEXT_OVERFLOW` | C7 | Context pack exceeds budget |
| `E_MODEL_TIMEOUT`, `E_MODEL_TRANSPORT` | C13 | Model call failed |
| `E_REPLAY_MISS` | `ReplayModelClient` (tests only) | No recorded call for this request |
| `E_SOLVER_OUTPUT_INVALID` | C7 | SolverOutput invalid |
| `E_SQL_NOT_SELECT`, `E_SQL_NONDETERMINISTIC` | C7 | SQL rule violated |
| `E_SQL_EXEC`, `E_SQL_TIMEOUT`, `E_EXEC_CRASH`, `E_EXEC_MEMORY` | C8 | Execution failed |
| `E_PY_EXEC`, `E_PY_TIMEOUT`, `E_PY_IMPORT` | C8 (P2) | Python fallback failed |
| `E_EMPTY_RESULT` | C7/C9 | No rows or NULL |
| `E_TYPE_CONTRACT` | C7/C9 | Result does not match expected type |
| `E_NO_SUCCESS` | C9 | No successful attempt |
| `E_DEADLINE`, `E_GLOBAL_STOP` | C12 | Time limits |
| `E_INTERNAL` | C12 | Uncaught exception |
| `E_DUPLICATE_WRITE` | C11 | Second write for an id (not a question outcome) |

Warning codes (`W_*`) are defined where raised (§7.1, §7.2) and listed in `contracts/codes.py`. Each code's owning component is listed there too, so error analysis can route errors to their owner (TASKS L-14).

---

## 11. Performance budgets

Budgets are measured on Colab G4 with the target memory cap (AP §4.2) and confirmed on E5.

| Item | Budget | Owner | Measured at |
|---|---|---|---|
| Replica load + warm-up (both, in parallel) | ≤ 300 s | M4 | M1 |
| TemporalParams call | ≤ 30 s | M2 | M1 |
| Business setup (300k rows, XLSX) | ≤ 60 s per business, overlapped | M1 | M1 |
| Parse call | p95 ≤ 15 s at production concurrency | M3 | M1 |
| Solve/repair call | p95 ≤ 30 s at production concurrency | M3 | M1 |
| SQL execution | p95 ≤ 2 s; hard limit 20 s | M3 | M1 |
| Per-question throughput time per replica | ≤ 17 s mean (AP §7.8) | M4 | M1, M3 |
| Full run, 1,000 questions | ≤ 9,000 s (gate G3) | M4 | M1 (projected), M3 (measured) |
| Peak host RAM | ≤ 128 GB | M4 | M3 |
| `/tmp` usage | ≤ 50 GB | M1 | M3 |
| GPU memory per replica | within `gpu_memory_utilization × 32 GB` | M4 | M1 |

---

## 12. Security and isolation (fault containment)
- The container runs without network; the only sockets are loopback ports `base_port … base_port + replicas − 1`.
- Generated SQL runs read-only with external access disabled and configuration locked; generated Python runs in killable worker processes with resource limits and an import allow-list.
- No generated code runs in the main process. No generated code can write outside `/tmp/datamate/sandbox/<pid>/`.

---

## 13. Compliance artifacts (owner M4, sign-off Lead)

### 13.1 `/code/README.md` [REQ DG §8]
MUST contain: approach (data reading, code generation and execution, answer choice); for **each** model (LLM, and P3 calibrator if adopted): name, public source URL, fixed revision, original release date, license, parameter count computed by `tools/count_params.py` (sum of tensor element counts over all safetensors in the shipped directory, vision towers included); data sources and versions, preprocessing, train/validation counts; run instructions; folder locations (DG §4); statement of whether training or data generation was performed.

### 13.2 `/code/training_code/` [REQ DG §4, §8]
- Even without fine-tuning, the **few-shot bank** and any **calibrator** are derived from the training split, so their generation is packaged:
  - `data_generation/build_fewshot.py`, `data_generation/build_calibrator_data.py` (P3), `configs/`, `logs/`, `data/` (the derived files), `requirements.txt` (pinned), `README.md` with exact commands and the statement "no model fine-tuning was performed" unless DEC-9 adopts LoRA.
- `data_manifest.json`: `[{path, sha256, size_bytes, source, version, split, record_count}]` for every packaged data file; for any omitted training-only base checkpoint: public URL, revision, license, required files, SHA-256.
- `.dockerignore` MUST NOT exclude `training_code/`.

### 13.3 Pre-submission checklist (maps to DG §10)
Automated by `tools/precheck.sh` on E5: run the exact scoring command; verify one submission line per question; validate every log line against the `LogRecord` schema; verify `thinking`/`code`/`output` presence rules; compare two runs; report runtime projection; check image platform and uncompressed size; verify `md5sum -c` on a second machine.

---

## 14. Testing, compatibility, and integration

### 14.1 Test layout and ownership
```
tests/
├── contract/
│   ├── test_schemas.py           # round-trip, invariants (§5.9), schema diff — Lead
│   ├── conformance/              # one suite per protocol (§14.3) — Lead
│   └── consumers/                # consumer tests (§14.4) — written by consumers
├── unit/<package>/               # owner of the package
├── integration/                  # ReplayModelClient on fixture businesses — Lead
├── determinism/                  # two runs, byte comparison (§14.5) — Lead
├── golden/                       # Brief examples shared by scorer and formatter — Lead + M2
└── fixtures/
    ├── businesses/               # M1
    ├── catalogs/                 # M1 (fake catalogs)
    ├── rulebooks/                # M2
    └── model_calls/              # M3 (recorded ModelCalls with template versions)
```

### 14.2 Requirements
- **Traceability.** Every MUST in a component section has at least one test whose name starts with `test_spec_<section>_` (for example `test_spec_7_5_rolling_excludes_as_of`). CI reports MUSTs of the owner's sections that have no test.
- Coverage target ≥ 80% lines for `ingest`, `catalog`, `temporal`, `formatting`, `decision`, `sandbox`, `eval`.
- `pytest -q` passes on CPU for all tests except those marked `gpu`. Tests marked `gpu` run on Colab.
- Static checks: import graph and layering (§4.3), public-API rule (§4.3), id-literal scan (§2.5), schema diff (§5.1), `ruff`, `mypy --strict` for `contracts/`, `temporal/`, `formatting/`.

### 14.3 Conformance suites
Each protocol of §5.10 has one suite in `tests/contract/conformance/`, parameterized over every implementation (stand-in and real). An implementation is not mergeable until it passes.

| Suite | Implementations | Checks |
|---|---|---|
| `test_model_client.py` | `ScriptedModelClient`, `ReplayModelClient`, `HttpModelClient` (marked `gpu`), in-process client (marked `gpu`) | Every `ModelCall` field present; `request_sha256` identical for identical requests and different otherwise; `content`/`reasoning` byte-exact (Vietnamese text, whitespace, empty string); errors returned as `ModelCall.error`, never raised; `params` echo every sent parameter |
| `test_executor.py` | `FakeExecutor`, sandbox pool | Tagged encoding round-trip for every SQL type; Decimal exactness; `truncated` and `row_count` semantics; error codes for syntax error, timeout, memory, write attempt; identical results from both implementations on the fixture catalogs |
| `test_lunar_calendar.py` | `FixtureLunarCalendar`, C5 implementation | `to_solar(to_lunar(d)) == d` over the covered range; `covers()` consistent with conversions; leap-month handling; defined error outside range |
| `test_submission_sink.py` | `InMemorySink`, C11 writer | One write per id; duplicate rejected; `written_ids()` exact; log record persisted before its submission line (file inspection for C11) |

### 14.4 Fakes and consumer tests
- **Fakes.** Before a real component exists, its consumers code against the stand-ins of §5.10 and the fake catalogs (M1-11). Stand-ins pass the same conformance suites as real components.
- **Consumer tests.** When a consumer depends on a behavior of another member's output that the contract types do not express (for example, "the SchemaCard lists all values of low-cardinality status columns", "list results always carry `tie_code`"), the consumer writes a test in `tests/contract/consumers/` named `<consumer>__<producer>__<assumption>.py`. The test runs against the producer's real implementation on fixtures.
- A producer MUST NOT merge a change that breaks a consumer test. If the assumption should change, the producer and consumer agree first and change the test in the same merge, approved by both.

### 14.5 Determinism CI
- On every merge request, `tests/determinism/` runs `run.main` twice on the fixture businesses with `ReplayModelClient` and `--dev --set model.replicas=1`, in two fresh processes.
- `submission.jsonl` MUST be byte-identical. `questions.jsonl`, `businesses.jsonl`, and `run.json` MUST be identical after removing timing fields (`elapsed_ms`, `latency_ms`, `duration_ms`, `setup_ms`, `timings`, timestamps).
- A failure blocks the merge (D13).

### 14.6 Integration stages
| Stage | Date | Content | Exit |
|---|---|---|---|
| **I0** | 11-07 12:00 | `contracts/` v1.0.0, protocols, stand-ins, schemas, conformance suites merged by the lead | Contract and conformance tests green |
| **I1** | 11-08 | Walking skeleton: every stage real or stubbed (`--stub`); `run.main` end-to-end with `ReplayModelClient`; valid outputs on fixtures | Integration and determinism tests green |
| **I2** | 11-09 | Real components on Colab G4 against the training split | Gates G1–G3 (AP §9.2) |
| **I3** | 11-11 | P2 features behind switches | G4–G5 |
| **I4** | 11-13 | Container on E5 | G6 |

### 14.7 Parallel development rules
- Each member develops against contracts, stand-ins, and fakes, not against another member's unfinished code.
- Recorded `ModelCall` fixtures are produced on Colab by M3 (TASKS M3-13) and refreshed with every template version change, so CPU-only work can run integration tests without a GPU.
- Merges to `main` happen in the daily merge window (`IMPLEMENTATION_PLAN.md` §4.3), in dependency order, each with green unit, contract, conformance, consumer, integration, and determinism tests, and approval from the required reviewer in §4.2.

---

## 15. Change control and compatibility

### 15.1 Contracts
- `contracts/` is owned by the lead. A change requires: a written proposal (one paragraph), the list of affected producers and consumers, a version bump, regenerated schemas, updated stand-ins, and updated conformance tests — all in the same merge.
- **Version rules.**
  | Change | Version | Allowed after I0 |
  |---|---|---|
  | Documentation, stricter validator that accepts all data produced today | patch | Yes |
  | New optional field with a default; new enum member that consumers may ignore; new reason or warning code | minor | Yes, with notice to consumers |
  | Removing or renaming a field, changing a type, making an optional field required, changing the meaning of a value | major | Only with lead approval and same-day notice to all members; never after the 11-13 freeze |
- **Two-step changes.** A major change is done as: (1) add the new field (minor), (2) migrate producers and consumers, (3) remove the old field (major), so `main` stays green at every step.

### 15.2 Other shared surfaces
These are treated like contracts (same version rules, reviewer = all consumers):
- `lexicon.fold()` behavior (§7.6.1).
- SchemaCard text format (§7.2.9).
- Prompt template IDs and versions (§7.13.5).
- Configuration keys (§6): adding a key needs a default; removing or renaming a key is a major change.
- Reason and warning codes (§10.2): codes are never reused with a different meaning.
- Goldens in `tests/golden/` (§7.10): changes need approval from the lead and M2.

### 15.3 Freeze
After the 11-13 freeze, changes are bug fixes only, each re-validated on E5 (G6). Configuration defaults may change until the freeze through a reviewed change to `run_config.json` with the harness result that justifies it attached.

This specification is updated in the same merge as any change it governs.

---

## 16. Clarifications of the architecture

None of these changes a component boundary or an approved decision.

| ID | Clarification | AP reference | Reason |
|---|---|---|---|
| **SC-1** | P1 temporal parameters are extracted **once per split** by C1 (`TemporalParams`), not per question by the parser | AP §7.1 ("parameters filled by the parser") | Same parameters for every question (determinism, fewer tokens); still read from the mounted rulebook, with explicit generic fallbacks |
| **SC-2** | SQL identifiers are accent-folded ASCII; original headers kept in metadata and SchemaCard; data values never altered | AP §6.2, DEC-11 | Reliable SQL generation. **Extends the scope of DEC-11 to identifiers; needs lead confirmation with DEC-11** |
| **SC-3** | **Critical:** SQLite is read with the Python standard library (`mode=ro&immutable=1`); DuckDB extension auto-install/auto-load disabled everywhere | AP §6.2 ("SQLite attached read-only") | DuckDB's `sqlite` extension is downloaded at run time and would fail under `--network none`; a normal SQLite open can also try to write journal files on read-only `/data` |
| **SC-4** | DuckDB queries run single-threaded; integral columns `BIGINT`, fixed-point `DECIMAL(38,6)` | AP §7.7 | Parallel floating-point aggregation can change results between runs; large VND sums can exceed double precision at 2-decimal resolution |
| **SC-5** | List queries return `item, sort_key, tie_code`; the formatter applies ordering, tie-break, and truncation | AP §5.3 ("deterministic ranking") | Makes the deterministic ranking helper concrete |
| **SC-6** | Time expressions are emitted in a closed structured vocabulary (`TimeExpr`) plus the verbatim span | AP §7.1 ("LLM extracts expressions verbatim") | Code can resolve structured expressions exactly; free Vietnamese text cannot be resolved deterministically |
| **SC-7** | `thinking` is a per-call list with `""` for calls without reasoning when at least one call produced reasoning; `null` when none did | AP §7.6, DG §3.3 | Keeps call-order alignment with `calls[]` without inventing reasoning |

---

## 17. Open items and verification list

| ID | Item | Owner | Due | Default until resolved |
|---|---|---|---|---|
| V1 | JSON wire shape of `list` answers (items only? codes or names?) per Brief §2.2 | Lead (L-11) | **Closed 11-08** | JSON array of values. Train: 193 lists, 106 all names and 87 all integers, never mixed, never empty, length 2–11. Names are the wire value; codes are accepted forms in `alias`, one alias list per position |
| V2 | JSON wire shape of `table` answers per Brief §2.2 | Lead (L-11) | **Closed 11-08** | `{"columns", "rows"}`. Train: 19 tables, 71 rows, every cell pair `[name, integer]`; `alias` has one list per row for the name cell. Only the columns `khach_hang, so_tien_no` occur in train, so other tables' column names remain unobserved (M2-11) |
| V3 | Rounding mode for 2-decimal rounding; int vs float literal (AP Q5) | Lead (L-11) | **Partly closed 11-08; one question open** | Literals: all 1,884 `number` refs are JSON integers; all 578 `percent` refs have ≤ 2 decimals; a numeric comparison makes `50` and `50.0` equal. Money: half-up to whole VND (rulebook §3, §9). **Open question for the organizers:** the rounding mode for percents and non-money averages at an exact tie; rulebook §9 gives only "2 chữ số thập phân", and the references cannot show it. Default `ROUND_HALF_UP` |
| V4 | `boolean` encoding | Lead (L-11) | **Closed 11-08** | JSON `true`/`false`: all 23 train refs; rulebook §9 marks `1` and `"có"` wrong |
| V5 | `tie_code` ordering (numeric vs lexicographic codes) | Lead (L-11), M2 | **Closed for train 11-08** | Train alias codes are fixed-width (`SP` + 4 digits, `KH` + 4, `NCC` + 3), so both orders agree; no all-digit codes occur. Keep numeric-if-all-numeric. M1-01 reports any business whose codes vary in width |
| V6 | `calendar.csv` column names and leap-month encoding | M2 (M2-01) | M0 | Alias table |
| V7 | Reference behavior for out-of-range windows (AP Q7) | Lead | I2 | Abstain on zero coverage |
| V8 | Per-business setup time attribution in `elapsed_ms` (AP Q8) | Lead | I1 | Excluded; logged in businesses.jsonl |
| V9 | vLLM CLI flag names and `chat_template_kwargs` / `response_format` support for the DEC-3 version | M4, M3 | I2 | As in §7.13 |
| V10 | Loopback availability under `--network none` | M4 (M4-10) | G6 | HTTP serving; in-process fallback ready |
| V11 | Question categories present in the training data (for reporting) | Lead | M0 | Report by type and reason only |
| V12 | DEC-11 including SC-2 identifier folding | Lead | I0 | Folding for retrieval keys and identifiers only |
| V13 | Exact Brief wording for every [REQ] carried from AP (source not available while writing) | Lead | I0 | AP statements |

---

## Appendix A. Worked example (illustrative)

Question: `{"id": "q_00042", "business_id": "biz_007", "question": "doanh thu thang truoc la bao nhieu", "as_of_date": "2025-06-18"}`

1. C4 `QuestionFrame`: `expected_type = number`, `metric_text = "doanh thu"`, `time = [{span: "thang truoc", role: primary, expr: {kind: relative_period, unit: month, offset: -1, to_date: false}}]`, `answerability = answerable`.
2. C5 with `prior_period_full = true`: window `[2025-05-01, 2025-05-31]`, granularity `month`, coverage 1.0.
3. C7 SQL (`solve.sql.v1`): `SELECT SUM(amount) AS value FROM orders WHERE order_date BETWEEN DATE '2025-05-01' AND DATE '2025-05-31' AND status NOT IN (…)`.
4. C8 result: one row, `{"t": "dec", "v": "48250000"}` (BIGINT sum).
5. C9: rule 7 → `D_ANSWER`. C10: integral → `48250000`.
6. Submission line: `{"id":"q_00042","type":"number","answer":48250000}`.
7. Log line: `{"id":"q_00042","answer":{"type":"number","answer":48250000},"elapsed_ms":7312,"thinking":null,"code":"SELECT SUM(amount) AS value …","output":{"columns":["value"],"rows":[[48250000]],"row_count":1,"truncated":false},"contracts_version":"1.0.0","business_id":"biz_007","calls":[…2 calls…],"attempts":[{"attempt_no":1,"stage":"solve","language":"sql","ok":true,"error_code":null,"duration_ms":41}],"windows":[…],"decision":{"kind":"answer","reason_code":"D_ANSWER","features":{…},"p_correct":null},"degrade":false}`

## Appendix B. Interface summary by owner

| Owner | Provides | Consumes | Stand-in others use until ready | First deliverable |
|---|---|---|---|---|
| Lead | Contract types, protocols, stand-ins, conformance suites, scorer, harness, run comparison | All outputs | — | `contracts/` v1.0.0 (11-07 12:00) |
| M1 | `BusinessCatalog`, DuckDB file, SchemaCard, `fold()`, lexicon, `EntityCandidate` (P2), `SemanticAnnotations` (P2) | `RunConfig`, `ModelClient` (P2) | Fake catalogs (M1-11) | Fake catalogs (11-07); `setup_business` on fixtures (11-08) |
| M2 | `SplitContext`, `TemporalParams`, `TimeWindow`, `LunarCalendar`, `Decision`, `SubmissionRecord` formatting | `QuestionFrame`, `SolverAttempt`, `BusinessCatalog`, `ModelClient` | `fixture_split_context()`, literal windows | `resolve_windows` P1 (11-08 12:00) |
| M3 | `QuestionFrame`, `SolverOutput`, `SolverAttempt`, `ExecutionResult`, `ModelClient` implementation, prompts, recorded `ModelCall`s | `SplitContext`, `BusinessCatalog`, `TimeWindow`, `fold()` | `ScriptedModelClient`, `ReplayModelClient`, `FakeExecutor` | Client (11-07); recorded fixtures (11-08 12:00) |
| M4 | `run.main`, stub mode, Orchestrator, Writer, `LogRecord`, replicas, Docker image, compliance artifacts | Everything | `InMemorySink`, direct pipeline calls | Colab env + replicas (11-07); `run.main` stub mode (11-08) |

---

## 18. Bootstrap corrections and deferrals (accepted 2026-11-08, PR #4)

The bootstrap codebase (`src/datamate`, contracts `1.0.0`) implements a **P1 subset** of this specification. It does **not** claim full compliance. This section records (a) corrections to this specification found while inspecting the actual train/public_test data and rulebooks, and (b) requirements the bootstrap deliberately defers. The lead accepted these corrections by merging the L-04 pull request (PR #4); where they differ from earlier sections, this section prevails.

### 18.1 Design corrections

| ID | Correction | Evidence | Affects |
|---|---|---|---|
| **DC-1** | **Money rounds to whole VND; percents and other measures to 2 decimals.** `QuestionFrame.numeric_kind ∈ {money, count, measure}` (required for `number`) travels with the typed value; the formatter rounds money to `formatting.money_decimals` (0) and everything else, including every percent, to `formatting.default_decimals` (2), mode `ROUND_HALF_UP`. Replaces §7.10 "quantize everything to 0.01". | Rulebook §9 (train and public_test): money is whole VND and an average of money is money; §3: "nửa đồng làm tròn lên". All 1,884 training `number` references are integers. | §5.7, §7.10, V3 |
| **DC-2** | **Two kinds of list.** `QuestionFrame.list_order ∈ {ranked, question_order}` (required for `list`); `ranking` is required only for `ranked`. Ranked lists are re-sorted by the formatter (§7.10); `question_order` lists (SQL columns `ord`, `item`) keep the question's order and are never re-sorted. Replaces invariant §5.9-2 "ranking present iff list". | Training references include `[Jan, Feb, Mar revenue]` "theo thứ tự thời gian" and `[whole boxes, loose units]`; sorting these by value would be wrong. Rulebook §9: "Câu hỏi nhiều số thì ghi list theo đúng thứ tự câu hỏi nêu". | §5.7, §5.9, §7.7.3, §7.10, V1 |
| **DC-3** | **Zero data coverage → `unanswerable`, not `abstain`.** Any resolved window (primary, comparison, or baseline) with `coverage_ratio = 0` yields `unanswerable` (`D_UNANSWERABLE_OUT_OF_RANGE`), configurable to `abstain` via `decision.zero_coverage`. Windows and coverage are capped at `as_of_date` (records after "today" have not happened). Replaces §7.9 rule 5. | Rulebook §7 (both splits): a period entirely outside the data range is unanswerable, "không phải 0". Training example: "tháng 2/2025 thay đổi bao nhiêu % so với tháng liền trước" → `unanswerable`. | §7.5, §7.9, V7 |
| **DC-4** | **Missing information is never zero.** NULL or no rows where a value is required → `E_EMPTY_RESULT` → `abstain`, and is not sent to repair. A computed `0` (e.g. `COALESCE(SUM(qty), 0)` over a covered period) is an answer. Non-finite results (DuckDB returns `inf` for `1/0`) → `D_IMPLAUSIBLE` → abstain. | Rulebook §7; DuckDB behavior verified locally. | §7.7.4, §7.7.5, §7.9 |
| **DC-5** | **Synchronous `ModelClient`.** `complete(*, stage, template_id, messages, json_schema, max_tokens, call_id) -> ModelCall`, called from worker threads; no asyncio. | Simpler for five parallel developers; HTTP calls to vLLM release the GIL, so a thread pool gives the same concurrency. | §3, §5.10, §7.12, §7.13 |
| **DC-6** | **Invented time spans are invalid output.** A `TimeRef.span` not found in the question (compared after `fold`) makes the frame invalid (`E_PARSE_INVALID`, abstain) instead of being dropped. | Dropping a time constraint silently changes the question into an all-time question, which risks −1. | §5.9-4, §7.4 |
| **DC-7** | **Logs are one JSONL file.** Per-question records go to `/result/logs/questions.jsonl`. | DG §3.3: "Any format is accepted", one record per question. | §8.3 (confirms) |

### 18.2 Deferred in the bootstrap (tracked in `TASKS.md`)

| Requirement | Bootstrap state | Task |
|---|---|---|
| §5.1 strict pydantic mode, exported JSON Schemas, schema-diff CI | Frozen, `extra="forbid"` models; no strict mode; no exported schemas | Not scheduled: add when a consumer needs it |
| §5.10 `ReplayModelClient`, `FakeExecutor`, conformance suites | Only `ScriptedModelClient` (dev-only) | M3-13; suites when a second implementation exists |
| §7.1 TemporalParams from the rulebook (model call, span validation); calendar validation | Generic defaults, empty `provenance`, logged with `F_TEMPORAL_GENERIC` | M2-05, M2-02 |
| §7.2 ingestion: encodings, VN/EN separators, suffixes, non-ISO dates, Excel, SQLite, header/total detection, joins, budgeted SchemaCard | Fixture CSV reader only (UTF-8, ISO dates, plain numbers); Excel/SQLite skipped with a warning; business `failed` if nothing readable. **Too slow for real data**: row-by-row insert did not finish the 30 training businesses within 10 minutes | M1-03…M1-10 |
| §7.4 abbreviation normalization; JSON-schema-constrained decoding | Not implemented | M1-02, M3-02, M3-04 |
| §7.5 year-omitted date ranges, rolling weeks/months, same period last year, "same days of previous month", lunar windows, shifts | `unsupported` → abstain | M2-04, M2-09 |
| §7.7 context budgeting, few-shot bank, Python fallback, soft deadline | Not implemented | M3-05, M3-10, M3-11 |
| §7.8 process isolation (killable pool, RLIMIT_AS) | In-process read-only DuckDB with external access disabled, locked config, timer interrupt. **Not process isolation.** | M3-07 |
| §7.9 fuzzy catalog check | Token-containment check, permissive (in doubt → not unanswerable) | M2-07 |
| §7.12 replicas, concurrency, deadlines, degrade mode, global stop, SIGTERM | Sequential, single process | M4-05 |
| §7.13 `HttpModelClient`, replica manager | M3-02 HTTP client implemented (§18.5); replica manager pending. Production config requires an explicit loopback endpoint | M3-02 (real-call acceptance pending), M4-03 |
| §7.14 harness, folds, run records, `compare_runs` | Scorer only (`datamate.eval.score`) | L-10, L-12 |
| §2.1 `predict.sh`, Docker image | Not implemented | M4-09 |
| §4.2, §14.7, §15 reviewer approvals, CODEOWNERS, daily merge window as a gate | **Dropped** for this team: the only enforced rule is pull-request-only merging to `main`; affected members are told about shared-interface changes | L-19 |

### 18.3 Contract v1.0.0 (TASKS L-04)

**Freeze rule.** v1.0.0 settles everything that would be a *major* change later (§15.1). Fields that can arrive later as optional additions stay out until a consumer needs them, as minor versions.

**Changes made for the freeze (0.1.0 → 1.0.0)**

| Change | Why now | Affects |
|---|---|---|
| `TemporalParams.source` replaced by per-field `provenance: {field: {source, span}}` and `uses_generic()` | M2-05 validates field by field (§7.1); changing the type after the freeze would be major | M2, M3 |
| `SubmissionRecord` validates the wire shape of each type; `reason` only on `unanswerable`; `abstain` carries nothing | A wrong format scores as wrong (Brief §4); all 3,000 training references pass | M2, M4 |
| `D_UNCLEAR`, `E_INPUT_INVALID`, and all `W_*` codes registered in `contracts/codes.py`; a test fails on any unregistered code in `src/` | §10.2 requires one registry | M1, M2, M4 |
| Enums `NumericKind`, `ListOrder`, `Granularity`, `DateGranularity`, `DecisionKind`, and `ParamProvenance` exported publicly | Public-API rule, §4.3 | all |

**Differences from §5, accepted with PR #4**

| Contract | v1.0.0 | Reason | Affects |
|---|---|---|---|
| `QuestionFrame` | Adds `numeric_kind`, `list_order` (DC-1, DC-2); `mentions`, `group_by_text`, `comparison`, `needs_procedural` are not present yet | Later additions are optional fields (M1-12, M3-04) | M2, M3 |
| `TimeExpr` | P1 kinds only; `rolling.unit` is `day`; `date` and `date_range` require full dates | Year-omitted ranges, rolling weeks/months, same period last year, and lunar kinds arrive as **new kinds or wider enums** (minor), not by making existing date fields nullable (M2-04, M2-09) | M2, M3 |
| `SolverOutput` | `sql`, `notes` only | Result shape follows from `QuestionFrame`; `python` arrives with M3-11 | M2, M3 |
| `ExecutionResult.rows` | In-memory `Decimal`/`int`/`str`/`bool`/`date`/`None`, never float | The tagged JSON of §5.7 stays private to the sandbox worker boundary (M3-07) | M3 |
| `ModelCall` | Adds `backend`; `replica` and token counts not present yet | Optional additions (M3-02, M4-03) | M3, M4 |
| `Stage` | `parse`, `solve`, `repair` | New stages are new enum members (M2-05, M1-13, M3-11) | M1, M2, M3 |
| `BusinessCatalog`, `ColumnInfo`, `TableInfo` | `warnings: list[str]` as `"<CODE> <detail>"`; `null_count` instead of `null_rate`; joins, keys, and date-column lists not present yet | Strings stay greppable and routable; the rest are additions (M1-10) | M1, M2, M3 |
| `TypedValue` | Numeric values carry `numeric_kind`; one kind per table | Per-column kinds are an addition (M2-11) | M2, M3 |
| `LogRecord` | P1 fields; `inputs`, `views_used`, `degrade` not present yet | Optional additions when those features exist | M4 |
| Protocols | `ModelClient` is synchronous and lives in `llm/` (DC-5); other §5.10 protocols are not defined | Added with their second implementation | M3, M4 |

### 18.4 M2-04 resolver and H6 handoff

The bootstrap handled explicit dates and ranges, solar calendar and relative periods, rolling days, and all-time windows. M2-04 extends the existing `TimeExpr` vocabulary and preserves the resolver signature and `TimeWindow` output. Lunar windows, sub-day shifts, and `calendar_period` with ISO week indices are outside this change.

**Contract extension.** Version `1.1.0` keeps the frozen `date` and `date_range` kinds unchanged. The new `yearless_date` and `yearless_date_range` kinds carry missing-year values such as `{ "month": 3, "day": 5, "year": null }`. `rolling.unit` adds `week` and `month`. `same_period_prior_year` and `same_days_previous_month` each take `ref`, a zero-based index into `QuestionFrame.time`. `TemporalParams.same_period_alignment` defaults to `calendar_dates` as in §5.5 and uses the frozen per-field `provenance` contract. The parser passes the generated schema to the client and uses `parse.frame.v3` to describe the added forms. Lead, M3 and M4 should account for the minor version, the new parameter and the new template ID in integration and run records.

Comparison references can point forward or back. The resolver preserves input order and `ref_index` in the output, and comparisons use the source window after `as_of_date` clipping. A missing source, invalid index, cycle, or inapplicable comparison returns `E_TIME_UNSUPPORTED` for the question. Coverage is computed separately for each resolved window. The existing gate and output contract continue to handle zero or unknown coverage.

**Temporal rule inventory and test evidence.** `split_mini` and `rulebooks/temporal_alt` are synthetic. The alternate calendar uses illustrative values to exercise the CSV structure, including a leap flag. The actual train and public-test `rulebook.md` and `calendar.csv` files were unavailable for this inspection. Rule extraction, calendar validation, and the real split comparison remain with M2-05, M2-02, and M2-01 respectively.

| Rule | Source excerpt | Resolver or bootstrap behavior | Runtime parameter | Fallback | Test evidence |
|---|---|---|---|---|---|
| Week start and full prior week | Fixture §Thời gian, “Tuần bắt đầu thứ Hai” and “cả tuần liền trước” | Uses the selected weekday and a full prior calendar week | `week_start`, `prior_period_full` | Monday, full prior week. Alternative `prior_period_full` behavior is outside M2-04 | `test_resolution_table`, `test_parameters_change_resolution` |
| To date and future records | Fixture intro and §Thời gian, “đến hết hôm nay” | To-date ends at the configured boundary. DC-3 clips overlapping windows at `as_of_date` and gives wholly future windows zero coverage. §7.5's older full-current-period description differs from DC-3 | `to_date_end`, `as_of_date` | Include `as_of_date` | `test_current_month_is_clipped_to_as_of`, `test_coverage_ignores_records_after_as_of` |
| Rolling windows | Fixture, “ngày cuối là hôm nay”; §7.5, “day-of-month clamped” | Days and weeks use inclusive day counts. Months clamp the shifted end and start the next day | `rolling_includes_as_of` | `true` | `test_spec_7_5_rolling_windows`, seeded rolling cases |
| Omitted year | §5.5, `most_recent_not_after_as_of`; §7.5, “next year if end < start” | A single day or range start uses the latest valid occurrence through `as_of_date`, including the latest leap-year occurrence of 29 February. A yearless end inherits the start year or rolls once. Invalid dates in the selected year and reversed explicit endpoints fail | `as_of_date`, fixed year-omitted policy | An unresolved date yields `E_TIME_UNSUPPORTED` | Yearless table and seeded day cases |
| Same period last year | §7.5, “29 Feb → 28 Feb” and “same length ending at shifted end” | `calendar_dates` shifts both endpoints and clamps leap day. `elapsed_days` preserves inclusive length ending at the shifted end | `same_period_alignment` | `calendar_dates` | `test_spec_7_5_prior_year_alignment`, seeded prior-year cases |
| Same days of previous month | `TASKS.md` requires the comparison. Historical `period.py` says “if that month is shorter, up to its end” | Proposed rule for a source from day 1 through a day of the same month. Start on day 1 of the previous month and clamp its end. Other source shapes return `E_TIME_UNSUPPORTED` | `ref` | Requires a resolved source | Previous-month table and seeded cases |
| Coverage | Fixture, “hoàn toàn ngoài khoảng ngày có dữ liệu” and DC-3 | Keep the requested bounds except for the `as_of_date` cap. A zero-coverage comparison reaches the existing decision gate. An unresolved comparison aborts before SQL | `data_range`, `decision.zero_coverage` | Coverage unknown without a range unless the window is wholly future. Known zero defaults to `unanswerable` | Coverage table, `test_comparison_without_data_or_source_skips_sql` |
| Solar/lunar calendar | `split_mini/calendar.csv` header and §7.1 | Split loader records the calendar path. V6 still requires real-file verification | `calendar_path` | Absent file yields `W_CALENDAR_MISSING` | `split_mini` and `temporal_alt` fixtures, `test_parameters_change_resolution` |

The historical baseline self-test checks inclusive day arithmetic, month/quarter year selection, and shorter-month comparisons. Its previous-month clamp informed the proposal where §7.5 gives no formula. Its text heuristics and split-specific behavior were excluded. H6 CPU evidence includes the scripted parser-to-SQL comparison test and 11,000 generated temporal cases with seed `0x20261108`. Local Windows Python 3.14.0 verification passed 139 tests and Ruff. The fixture scored 13/13 (PA 1.0000) and its submission matched the bootstrap byte for byte. Model output on the expanded schema still needs M3 validation on the real client.

### 18.5 M3-02 HTTP client and additive contract proposal (2026-11-09)

**Change proposal / consumer notice.** Add optional `ModelCall.transport: dict[str, Any] | None = None` and register `E_MODEL_TIMEOUT` / `E_MODEL_TRANSPORT`; bump contracts to `1.4.0` (additive minor on top of `main`'s `1.3.0`; the original proposal said `1.2.0` because it was written before M2-05's `1.3.0`). `MODEL_COMPARISION_L4.ipynb` was removed from this change: it targeted contracts `1.3.0` and template `parse.frame.v3` as they existed on another branch, ran on an L4 (sm_89) and did not verify licenses or release dates, so it is not reproducible evidence; M3-01/M3-08 replaces it. The existing required fields and scripted request-hash convention remain unchanged. Producers affected: HTTP client; consumers affected: runtime logs, evaluation, future replay (M3-13), M4 serving/orchestration, and M1/M2 model callers. The source config gains defaulted HTTP/decoding keys documented in README. This implementation is prepared for review; it does not assert Lead/M4 approval or a real GPU acceptance run.

`HttpModelClient` implements DC-5 synchronously using the standard library. It accepts only explicit loopback HTTP endpoints, bypasses proxies and does not follow redirects. Server startup/health/restarts remain M4's responsibility. Configuration without `model.base_url` fails before outputs are opened. A transport failure gets one identical retry within the remaining call budget; timeout, HTTP errors, and malformed response envelopes do not retry. All model/transport failures return a `ModelCall.error`. Model-generated invalid JSON/SQL and `finish_reason=length` remain unmodified for caller-side validation.

The client hashes canonical JSON of the actual HTTP body after schema adaptation. `transport` captures that body, original schema SHA-256, adapter policy, raw response text, status, preparation flag and attempt history. A pre-send preparation failure records `request_prepared=false`, no `request_body`, and the SHA-256 of `{}`; it is not a record of a transmitted request and must not be replayed as one. `params` echoes sent model/decoding fields (messages and response schema are in the recorded request body). HTTP errors and protocol failures use `E_MODEL_ERROR`; diagnostic details are in `transport`.

The versioned `timeref.v1` adapter copies the source schema, makes each time-expression branch's unique string `kind.const` required, and converts only `TimeRef.expr.oneOf` to `anyOf`. It rejects overlapping tags and other unsupported `oneOf` unions. Original Pydantic validation remains in parse/solver. `model.schema_adapter=none` is an explicit opt-out for a backend supporting the source schema, not an automatic unconstrained-generation fallback.

CPU acceptance lives in `tests/unit/test_model_client.py`, using a real loopback fake server. It covers explicit fields, exact generated text/reasoning, canonical hashes, schema adaptation, retry/timeout, error envelopes, redirects/proxy isolation, concurrent callers and the fixture pipeline. `notebooks/M3_02_HTTP_CLIENT_CHECK.ipynb` reruns those checks by criterion and records an optional real vLLM call. Real GPU acceptance and M3-13 replay remain pending until observed evidence exists.

**Observed local verification (2026-11-09).** With `PYTHONPATH=src`, `.venv/Scripts/python -m pytest -ra -p no:cacheprovider` completed with **214 passed, 2 skipped** (training-reference checks skipped because `train/answers.jsonl` is absent). `.venv/Scripts/python -m ruff check src tests --no-cache` reported **All checks passed**. The notebook's CPU test/report cells were executed locally after substituting the existing checkout/environment for Colab clone/install: all **37 focused M3-02 acceptance cases** passed, regression/lint checks ran, CSV/JSON/conclusion exports were verified, and the disabled live-model branch remained **NOT VERIFIED**. The notebook JSON and all code-cell syntax were validated. No vLLM/GPU call was executed in this verification.

### 18.6 M4-05 orchestrator and contracts 1.5.0 (2026-11-11)

**Contract change (additive, minor).** `contracts/codes.py` registers `E_DEADLINE`, `E_GLOBAL_STOP` (both already named in §10.2) and `E_REPLICA_DOWN` (no model replica available; the all-abstain submission written when servers cannot start or all replicas die). `CONTRACTS_VERSION = "1.5.0"`.

**Non-contract interface changes.** `ModelClient.complete` gains an optional `timeout_s` (caps one call below `model.model_call_timeout_s`; used to enforce question deadlines). `llm.Deadline` / `DeadlineExceeded` / `NO_DEADLINE` are new public names; `parse_question`, `solve` and `answer_question` take an optional `deadline`. New config sections `serving`, `concurrency`, `deadlines` (README table). Deviations from §6.2/§7.12, all deliberate:
- Serving keys live in a `serving` section, not under `model`.
- Business setup runs in a **thread** pool (`concurrency.setup_workers`), not a spawn process pool; M1 may switch the executor if ingestion proves GIL-bound.
- Hard deadlines are enforced cooperatively (each call is capped to the remaining question time; no thread is killed), so a worker is occupied at most until its capped call returns.
- Records are appended in completion order while the run is live and re-ordered at finalization (`ResultWriter.finalize_canonical`: rows rejected at input first, then questions by input line), so `submission.jsonl` bytes do not depend on worker count or scheduling (D2, D13). `questions.jsonl` is re-ordered the same way.
- `sandbox.execute.open_readonly` tolerates DuckDB's per-process shared instance already being config-locked (needed once questions run concurrently). Real isolation is M3-07.

### 18.7 M3-13 replay (contracts 1.6.0)

Registers `E_REPLAY_MISS` (additive; `CONTRACTS_VERSION = "1.6.0"`). `ReplayModelClient` is keyed by the SHA-256 of the canonical HTTP request body that `HttpModelClient` would send for the active `model.*` config (so prompt, schema, sampling, `max_tokens` and thinking switch are all part of the key), which refines §5.10's "request_sha256". Replayed `ModelCall`s carry `backend="replay"`; the recorded backend is in `transport.recorded_backend`. New config keys `model.replay_path`, `model.record_path` and backend `replay` are development-only. Format: `datamate.model_calls.v1` (see `llm/replay.py`).

### 18.8 M4-07 records (contracts 1.7.0)

`LogRecord.degrade: bool = False` is added (additive, `CONTRACTS_VERSION = "1.7.0"`); `inputs` and `views_used` stay absent until helper calls / P2 views exist. `model.revision` is a new config key (recorded in run.json).

**Bounded logs.** `ModelCall.transport.request_body` in `logs/questions.jsonl` is *compacted*: any message longer than 512 characters becomes `{"role", "content_sha256", "content_chars"}` and the response schema becomes `schema_sha256` (marker `transport.request_compacted = true`); the texts are written once to `logs/prompt_blobs.jsonl` (`{"sha256", "text"}`, sorted by hash). `request_sha256` still hashes the original body, so the request can be rebuilt from the blobs (tested). `content`, `reasoning`, `code`, `output` are never compacted. Without this a real business whose SchemaCard is ~370,000 characters would add that text to every call line.

**run.json** now also carries `model` (path, served name, backend, revision, file sizes, hash of `SHA256SUMS` if shipped), `environment` (Python, platform, package versions read from metadata, GPUs from `nvidia-smi` or null, selected env vars, hash of `requirements.lock` and `BUILD_INFO.json` when present under `/code`), `timings` (`replica_load_ms`, `first_answer_ms`, `total_ms`), `degrade_activated_ms`, `replicas` (ports, GPUs, commands, restarts, events); `businesses.jsonl` rows carry `setup_ms`.

### 18.9 M3-03 context budget (contracts 1.8.0)

Registers `E_CONTEXT_OVERFLOW` (named in §10.2; `CONTRACTS_VERSION = "1.8.0"`). New `solver.*` keys: `tokenizer` (`model` | `estimate`; `estimate` is development-only and production exits 2 if the model's tokenizer cannot be loaded from `model.path` with `local_files_only`), `context_budget_tokens`, `schema_card_budget_tokens`, `readme_budget_tokens`, `fewshot_k`, `question_block_reserve_tokens`. `prompts/budget.py` implements the §7.7.1 reduction order; the SchemaCard relevant-subset step is an injected callable so that M1's `select_schema_context` (HF-style `encode(text, add_special_tokens=False)` tokenizer interface, matched by `llm/tokenizer.py`) can be connected without duplicating it. The per-question record `decision.context` carries `{tokens, reductions, tokenizer}` (or `{overflow}`); run.json carries `context_budget`.

### 18.10 M3-07 sandbox pool (contracts 1.9.0)

Registers `E_EXEC_CRASH` (`CONTRACTS_VERSION = "1.9.0"`). `exec_limits` gains `isolation` (`process` | `inprocess`; `process` is the default and what `run.main` uses), `workers` (§7.8 `sandbox_workers`, default 16) and `kill_grace_s`. Deviation from §7.8: results cross the pipe as pickled `ExecutionResult` objects (exact for Decimal/int/str/bool/date), not as tagged JSON; DOUBLE is still converted with `Decimal(repr(x))` inside the worker. The worker's own interrupt answers `E_SQL_TIMEOUT` at `sql_timeout_s`; the parent SIGKILLs a worker that has not answered `kill_grace_s` later. `run()` called directly (tests) executes in process unless an `executor` is passed. Python fallback (§7.8, M3-11) is not part of this pool yet.

### 18.11 M3-04/05/10 prompts v2 and few-shot bank (no contract change)

New template ids `solve.sql.v2`, `repair.sql.v2` (v1 unchanged; its SHA-256 is pinned by a test). `solver.template_version` (`v1` default | `v2`) selects them; `solver.fewshot_bank_path` and `solver.fewshot_exclude_businesses` (leakage guard, dev folds only) control few-shot examples, which are rendered into the **question block** of v2 so the business-level prefix stays cacheable and byte-identical. The bank selector uses a dependency-free token-set Jaccard instead of rapidfuzz (§7.7.2) with the same tie-break rule. The bank file is generated, never hand-written.

### 18.12 M3-11 python fallback (contracts 1.10.0)

Additive contract changes (`CONTRACTS_VERSION = "1.10.0"`): `Stage` gains `fallback`; new `PythonSolverOutput {python, notes}`; `ExecutionResult.language` (`sql` default | `python`); `SolverAttempt.python_output` and `solver_output` now optional. `solver.python_fallback` (default **false**) enables one fallback attempt after the SQL attempts failed with an error that is about the code (never after `E_EMPTY_RESULT`, `D_IMPLAUSIBLE`, `E_SQL_TIMEOUT`, `E_EXEC_CRASH`, a model error, a soft deadline or degrade mode). Config adds `model.max_tokens.fallback` (3072) and `model.enable_thinking.fallback`. Execution follows §7.8 (allow-listed imports, fault boundary only) inside the killable pool. A list/table return value uses dict keys as columns (`item, sort_key, tie_code` / `ord, item` / entity + measures).

