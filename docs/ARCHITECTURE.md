# DataMate 2026 — System Architecture

| Field | Value |
|---|---|
| **Document** | `ARCHITECTURE.md` |
| **Version** | 1.1 — ownership for one lead and four members; seams for parallel development (§10) |
| **Status** | Implementation baseline |
| **Date** | 2026-11-06 (GMT+7) |
| **Derived from** | `ARCHITECTURE_PROPOSAL.md` v2.1 (**AP**) — approved design and rationale |
| **Normative companion** | `SPEC.md` v1.1 (**SPEC**) — contracts, configuration, algorithms, acceptance tests |
| **Compliance authority** | `COMPETITION_BRIEF.md` (**Brief**) and the Docker Submission Guide (**DG**) |

### How the four engineering documents relate
| Document | Answers | Changes when |
|---|---|---|
| `ARCHITECTURE_PROPOSAL.md` | *Why* this design; alternatives; risks; decisions | A decision is revisited |
| `ARCHITECTURE.md` (this) | *How the system is structured*: views, modules, runtime behavior, deployment | A module boundary or flow changes |
| `SPEC.md` | *Exactly what* each interface, field, algorithm, and test must be | A contract, config key, or rule changes |
| `IMPLEMENTATION_PLAN.md` / `TASKS.md` | *Who builds what, when*; collaboration and reproducibility rules | Schedule or ownership changes |

If this document and `SPEC.md` disagree on a contract, field, or value, **SPEC prevails** and this document is corrected. Owners below are the roles of `IMPLEMENTATION_PLAN.md` §2: **Lead**, **M1** Data & Semantics, **M2** Rules, Time & Answers, **M3** Reasoning Engine, **M4** Platform & Compliance.

---

## 1. Architectural drivers

| Driver | Source | Architectural response |
|---|---|---|
| Exact-match scoring with −1 for wrong answers | Brief §2 | Deterministic typing/formatting (C10); conservative answer/abstain gate (C9) |
| Private rulebook may differ; unseen business types | Brief §3 | Rulebook treated as data (C1); schema-driven ingestion and prompting (C2, C7) |
| 2 × RTX 5090, 6 h, ≤ 15B params, offline | DG §2 | Two single-GPU replicas of one model (C13); runtime scheduler (C12) |
| \|ΔPA\| ≤ 0.03 on re-run | DG §6 | Greedy decoding, fixed concurrency, deterministic data path (§8.1) |
| Per-question logs of actual thinking/code/output | DG §3.3 | Capture at the model-client and executor boundaries (C11, C13, C8) |
| Development on Google Colab (one GPU, no Docker) | AP §4 | Single-GPU-testable serving; same package and lock in Colab and image |
| Ten days, five engineers | AP §0 | Phased delivery; frozen contracts; test doubles for parallel work |

---

## 2. Context view

```
                ┌──────────────────────────── Docker container (--network none) ──────────────────────────┐
 /data (ro) ───►│                                                                                          │
  data/<biz>/   │   DataMate inference system  (bash /code/predict.sh)                                     │──► /result
  rulebook.md   │                                                                                          │    submission.jsonl
  calendar.csv  │   uses: /code/models/<model> (weights), /code/config/run_config.json, /tmp (scratch)    │    logs/*
  questions.jsonl                                                                                          │
                └────────────────────────────── GPU0, GPU1 (RTX 5090, 32 GB each) ─────────────────────────┘
```
External actors: the organizer's runner (starts the container, mounts `/data` and `/result`), and in development the evaluation harness (C14), which calls the same entry function with a training split and its answers.

---

## 3. Process (container) view

```
python3 -m datamate.run   ── main process, single asyncio event loop
│
├── runtime.Orchestrator (C12)  — schedules everything; owns deadlines and global stop
├── runtime.Writer (C11)        — sole writer of /result
├── llm.ModelClient (C13)       — sole HTTP client to the replicas
│
├── replica 0  ─ subprocess: vLLM OpenAI server, CUDA_VISIBLE_DEVICES=0, 127.0.0.1:8100
├── replica 1  ─ subprocess: vLLM OpenAI server, CUDA_VISIBLE_DEVICES=1, 127.0.0.1:8101
│
├── setup pool    ─ ProcessPoolExecutor(spawn), setup_workers   → ingest + catalog (C2), view DDL (C3)
└── sandbox pool  ─ killable worker processes(spawn), sandbox_workers → SQL / Python execution (C8)
```

**Why this split.** Model inference is GPU-bound and lives in separate server processes; ingestion and query execution are CPU-bound and isolated in worker processes so a runaway query or a parser crash cannot take down the event loop. The event loop only orchestrates, renders prompts, and validates small JSON objects.

**Communication.**
| From → To | Mechanism | Payload |
|---|---|---|
| Orchestrator → setup pool | `run_in_executor` | business dir, config → `BusinessCatalog` (pickled pydantic) |
| Solver → sandbox pool | pipe per worker | `(db_path, code, limits)` → `ExecutionResult` (tagged JSON) |
| Any stage → replicas | `ModelClient` over loopback HTTP | chat request → `ModelCall` |
| Pipeline → Writer | `asyncio.Queue` | `(SubmissionRecord, LogRecord)` |

---

## 4. Module (package) view

### 4.1 Source tree
```
src/datamate/
├── __init__.py
├── run.py                    # M4 — entry point; lifecycle (SPEC §2.3); stub mode
├── config.py                 # M4 — RunConfig load/validate/hash; dev overrides
├── contracts/                # Lead — no imports from datamate
│   ├── __init__.py           # CONTRACTS_VERSION
│   ├── enums.py              # AnswerType, Stage, ExprKind, …
│   ├── codes.py              # ReasonCode, warning codes
│   ├── inputs.py             # Question
│   ├── split.py              # TemporalParams, HolidayWindow, RuleProfile, SplitContext
│   ├── business.py           # ColumnInfo, TableInfo, JoinEdge, BusinessCatalog, ViewSpec, SemanticAnnotations
│   ├── question.py           # TimeExpr, TimeRef, Mention, QuestionFrame, TimeWindow, EntityCandidate
│   ├── execution.py          # ModelCall, ExecutionResult, SolverOutput, SolverAttempt, ExecLimits
│   ├── decision.py           # TypedValue, Decision
│   ├── output.py             # SubmissionRecord, LogRecord, BusinessLogRecord, RunRecord
│   ├── protocols.py          # ModelClient, LunarCalendar, Executor, Deadline, SubmissionSink
│   ├── testing.py            # ReplayModelClient, ScriptedModelClient, InMemorySink, FakeDeadline
│   └── schemas/              # exported JSON Schemas (committed)
├── lexicon/                  # M1
│   ├── fold.py               # fold() — retrieval/identifier keys only
│   ├── normalize.py          # NFC, whitespace, abbreviation expansion
│   └── abbrev_vi.tsv
├── rules/                    # M2 — C1
│   ├── bootstrap.py          # bootstrap_split()
│   ├── rulebook.py           # load verbatim, span validation
│   └── temporal_params.py    # extraction call + validation + generic fallback
├── temporal/                 # M2 — C5
│   ├── calendar.py           # LunarCalendar implementation over calendar.csv
│   ├── periods.py            # period arithmetic (weeks, months, quarters, shifts, clamping)
│   └── resolver.py           # resolve_windows()
├── semantics/                # M1 — C3 (P2)
│   ├── compiler.py           # compile_semantics()
│   └── validate_views.py
├── ingest/                   # M1 — C2 readers and value parsing
│   ├── discover.py
│   ├── csv_reader.py
│   ├── excel_reader.py       # calamine; block/header/total-row detection
│   ├── sqlite_reader.py      # stdlib sqlite3, immutable read-only
│   ├── numbers.py            # VN/EN/PLAIN conventions, suffixes, voting
│   ├── dates.py              # format inference, DMY/MDY evidence, Excel serials
│   └── identifiers.py        # SQL identifier derivation (SC-2)
├── catalog/                  # M1 — C2 materialization and profiling
│   ├── materialize.py        # DuckDB file creation
│   ├── profile.py            # column stats, keys, joins, date coverage
│   ├── schema_card.py        # deterministic SchemaCard rendering + budgeting
│   └── setup.py              # setup_business()
├── entities/                 # M1 — C6 (P2)
│   ├── index.py
│   └── link.py
├── llm/                      # M3 client.py, tokenizer.py; M4 replicas.py, inprocess.py — C13
│   ├── client.py             # HttpModelClient
│   ├── inprocess.py          # AsyncLLM fallback client
│   ├── replicas.py           # launch, health, warm-up, restart
│   └── tokenizer.py          # token counting with chat template
├── prompts/                  # M3
│   ├── render.py             # Jinja2 StrictUndefined; template hashing
│   └── *.j2                  # rules.temporal.v1, parse.frame.v1, solve.sql.v1, repair.sql.v1, …
├── parse/                    # M3 — C4
│   └── parser.py             # parse_question()
├── solver/                   # M3 — C7
│   ├── context_pack.py       # sections 1–7, budgeting, relevant-subset mode
│   ├── fewshot.py            # bank loading + deterministic selection
│   ├── sql_rules.py          # check_sql()
│   ├── contract_check.py     # result shape vs expected type
│   ├── typed_value.py        # to_typed_value()
│   └── solver.py             # solve(): attempt loop
├── sandbox/                  # M3 — C8
│   ├── pool.py               # killable worker pool
│   ├── worker.py             # worker main: duckdb read-only connections, exec
│   ├── encode.py             # tagged JSON value encoding
│   └── py_guard.py           # import allow-list (P2)
├── decision/                 # M2 — C9
│   ├── features.py
│   ├── gate.py               # rule gate
│   ├── catalog_check.py      # missing-field confirmation
│   └── calibrator.py         # P3
├── formatting/               # M2 — C10
│   ├── numbers.py            # Decimal quantize, integer literal rule
│   ├── lists.py              # ranking, tie-break, truncation
│   ├── tables.py
│   ├── serialize.py          # Decimal-preserving JSON encoder
│   └── table_conventions.md
├── runtime/                  # M4 — C11, C12
│   ├── orchestrator.py       # grouping, assignment, workers, deadlines, degrade, stop
│   ├── pipeline.py           # per-question pipeline composition
│   ├── deadline.py
│   ├── writer.py             # fsync writer
│   └── records.py            # LogRecord / BusinessLogRecord / RunRecord assembly
├── eval/                     # Lead — C14 (never imported by run.py)
│   ├── scorer.py
│   ├── harness.py
│   ├── folds.py
│   ├── report.py
│   └── compare_runs.py
└── assets/
    └── fewshot.jsonl         # M3 — generated from training split (training_code/data_generation)
```

### 4.2 Layering
```
 L5  run.py, eval/                      entry points
 L4  runtime/                           orchestration, persistence
 L3  parse/, solver/, decision/, semantics/   reasoning stages
 L2  catalog/, temporal/, rules/, entities/, sandbox/, formatting/, llm/, prompts/   services
 L1  ingest/, lexicon/                  primitives
 L0  contracts/, config.py              shared types
```
A module may import only from its own layer or lower layers. `llm/` and `prompts/` are services used by L3 and by `rules/`/`semantics/`. The import-graph check in CI enforces this table (SPEC §4.3).

### 4.3 Component responsibilities (summary)
Full behavior is in SPEC §7; this table fixes ownership and the boundaries each component must not cross.

| Component | Package | Owner | Owns | Must not |
|---|---|---|---|---|
| C1 Split Bootstrap | `rules/` | M2 | Rulebook text, `TemporalParams`, `RuleProfile` (P2) | Hold any training-rulebook constant |
| C2 Ingestion & Catalog | `ingest/`, `catalog/` | M1 | DuckDB file, SchemaCard, profiling | Alter data values; call the model |
| C3 Semantic Compiler (P2) | `semantics/` | M1 | Validated views | Expose unvalidated views |
| C4 Question Parser | `parse/` | M3 | `QuestionFrame` | Compute dates or answers |
| C5 Temporal Resolver | `temporal/` | M2 | `TimeWindow` | Do I/O or model calls |
| C6 Entity Linker (P2) | `entities/` | M1 | `EntityCandidate` | Return folded values |
| C7 Solver | `solver/` | M3 | Context pack, attempt loop, `SolverAttempt` | Execute code itself |
| C8 Sandbox Executor | `sandbox/` | M3 | Execution, limits, value encoding | Write outside its scratch dir |
| C9 Verifier & Decision | `decision/` | M2 | `Decision` | Call the model (P1/P2) |
| C10 Formatter | `formatting/` | M2 | Wire values | Read model output strings directly |
| C11 Persistence | `runtime/writer.py` | M4 | `/result` files | Be bypassed by any other writer |
| C12 Orchestrator | `runtime/` | M4 | Scheduling, deadlines, assignment | Change concurrency at run time |
| C13 Model Serving | `llm/` | M3 (client), M4 (replicas) | Replicas, requests, `ModelCall` | Use server or template defaults |
| C14 Evaluation | `eval/` | Lead | Scoring, CV, run records | Be imported by the inference path |

---

## 5. Runtime views

### 5.1 Startup
```
run.main
 ├─ config.load(run_config.json) ─► RunConfig, config_sha256
 ├─ read questions.jsonl ─► Question[] (invalid → pre-abstained)
 ├─ orchestrator.plan(): group by business, order, assign replicas   (deterministic)
 ├─ in parallel ─────────────────────────────────────────────────────────────────
 │   ├─ replicas.start(0), replicas.start(1) → /health → warm-up
 │   ├─ setup pool: setup_business(b) for b in planned order
 │   └─ after replica 0 ready: rules.bootstrap_split() → SplitContext
 └─ when SplitContext ready and business b ready → enqueue b's questions on its replica queue
```

### 5.2 Per-question flow (P1)
```
worker(replica r) takes q            ← elapsed_ms starts
 │
 ├─ lexicon.normalize(q.question) → normalized
 ├─ parse.parse_question()   ──ModelCall#1──► replica r ──► QuestionFrame | E_PARSE_INVALID
 ├─ temporal.resolve_windows()                         ──► TimeWindow[] | E_TIME_UNSUPPORTED
 ├─ solver.solve()
 │    ├─ context_pack.build()  (sections 1–5 byte-identical per business)
 │    ├─ attempt 1: ModelCall#2 ─► SolverOutput ─► check_sql ─► sandbox.run_sql ─► contract_check
 │    └─ ≤ 2 repairs (append turns; same prefix) while not ok and before soft deadline
 ├─ decision.decide()  → Decision (rule gate)
 ├─ formatting.to_submission() → SubmissionRecord
 └─ writer.put(SubmissionRecord, LogRecord)            ← elapsed_ms ends
```
P2 inserts `entities.link()` after temporal resolution and the Python fallback after failed SQL attempts; C3 views appear as context section 5.

### 5.3 Failure paths
| Event | Handling | Outcome |
|---|---|---|
| Business setup exception | Caught in setup pool; `status = failed` | All its questions abstain `E_BUSINESS_SETUP` |
| Model call timeout | `ModelCall.error`; stage treats as failed attempt | Repair if allowed, else abstain |
| SQL timeout / OOM | Worker killed and replaced | Attempt fails with `E_SQL_TIMEOUT` / `E_EXEC_MEMORY` |
| Any uncaught exception in a question | Caught at question boundary | Abstain `E_INTERNAL`; traceback in run.json |
| Question exceeds hard deadline | Task cancelled | Abstain `E_DEADLINE` |
| Replica crash | One restart; queue drained to the other replica | Questions continue on remaining replica |
| Run behind schedule | Degrade mode (no repairs/fallback/P3) | Logged activation time |
| `T0 + global_hard_stop_s` or SIGTERM | Cancel all; finalize | Unwritten ids abstain `E_GLOBAL_STOP` |

### 5.4 Shutdown
Writer drains its queue → abstain lines for unwritten ids → `run.json` written atomically → replicas receive SIGTERM (then SIGKILL after 30 s) → pools shut down → exit code per SPEC §2.1.

---

## 6. Data view

### 6.1 Data lifecycle
| Artifact | Created by | Location | Lifetime | Consumers |
|---|---|---|---|---|
| `RunConfig` | image build | `/code/config/run_config.json` | frozen | all |
| Few-shot bank | `training_code/data_generation/build_fewshot.py` | `/code/src/datamate/assets/fewshot.jsonl` | frozen | C7 |
| `SplitContext` | C1 | memory | run | C4, C5, C7 |
| Business DuckDB | C2 (+C3 views) | `/tmp/datamate/biz/<bkey>/catalog.duckdb` | run | C8 (read-only) |
| `BusinessCatalog` | C2 | memory + `businesses.jsonl` | run | C4, C6, C7, C9 |
| Per-question objects | C4–C10 | memory | question | C11 |
| Outputs | C11 | `/result/...` | persistent | organizers |

### 6.2 Business database layout
- One DuckDB file per business, one table per source table/sheet block (SPEC §7.2.7 naming).
- Parsed columns carry their typed values; `<col>__raw` VARCHAR columns are present only where parsing changed or nulled values.
- P2 views are named `v_<name>` and stored in the same file; their DDL is also in the business log.
- No indexes; DuckDB scans are fast enough at ≤ 300k rows and keep setup simple.

### 6.3 Text handling
| Text | Normal form | Folded? |
|---|---|---|
| Data values in DuckDB | as read, NFC | Never |
| Original headers | NFC | Never (kept in `original_name`) |
| SQL identifiers | ASCII from `fold()` | Yes (SC-2) |
| Question text sent to the model | original NFC + normalized copy | No |
| Entity index keys | `fold()` | Yes (retrieval only) |
| Output strings | stored value | Never |

---

## 7. Deployment view

### 7.1 Image
```
FROM <base image chosen by DEC-3>        # vLLM + PyTorch with sm_120 support
ENTRYPOINT []
ENV  (SPEC §2.4)
COPY requirements.txt → pip install (lock)            layer: dependencies
COPY models/<selected>/ → /code/models/<selected>/    layer: weights (cached across code changes)
COPY training_code/ → /code/training_code/            layer: compliance artifacts
COPY config/ predict.sh README.md → /code/
COPY src/ → /code/src/                                layer: code (changes most often)
CMD ["bash", "/code/predict.sh"]
```
Built for `linux/amd64` on the build host (E4); tagged `zaic2026_datamate_<team_name>:final` (DG §9).

### 7.2 Environments
| Env | What runs | How it differs from the target |
|---|---|---|
| E1 Colab G4 (sm_120) | Package installed from the lock in a venv; replicas as subprocesses; harness | One GPU → `replicas = 1` with `--dev`; memory capped to the 32 GB equivalent; no Docker |
| E2 Colab A100/H100 | Accuracy experiments | Different GPU architecture; runtime and determinism numbers not valid |
| E3 CPU (Colab or laptops) | Unit, contract, integration tests with test doubles | No model |
| E4 Build host | `docker build`, `save`, checksum, upload | No GPU needed |
| E5 Rehearsal host (sm_120, Docker) | Exact scoring command; private-test run of the frozen image | Must match the target as closely as possible (AP RISK-1, RISK-2) |

### 7.3 Configuration by environment
Production uses `run_config.json` as frozen. Development uses the same file plus recorded `--dev --set` overrides, for example `model.replicas=1`, `model.gpu_memory_utilization=0.30` on G4, `model.path=/content/models/<m>`. No override is permitted in the image.

---

## 8. Cross-cutting concerns

### 8.1 Determinism
Sources of nondeterminism and their controls:

| Source | Control | Where |
|---|---|---|
| Sampling | Greedy, fixed seed, explicit params | C13 client |
| Batch composition on GPU | Fixed concurrency, fixed assignment; batch-invariant mode if validated | C12, C13 |
| Prompt bytes | Deterministic rendering; byte-identical shared prefix | C7, prompts |
| Python iteration order | `PYTHONHASHSEED=0`; sorted iteration where output depends on it | all |
| Parallel float aggregation | DuckDB `threads = 1` in sandbox; exact numeric types | C2, C8 |
| Unordered SQL results | `LIMIT` requires `ORDER BY`; formatter re-sorts lists | C7, C10 |
| Library drift | Lock generated inside the base image | build |
| Timing-dependent behavior | Limited to deadlines, degrade mode, global stop; all logged | C12 |

### 8.2 Observability
- **Compliance logs** (`questions.jsonl`): DG-required fields plus calls, attempts, windows, decision (SPEC §8.3).
- **Business log** (`businesses.jsonl`): ingestion warnings, SchemaCard, view DDL and compile calls.
- **Run record** (`run.json`): configuration hash, template hashes, environment fingerprint, assignment, timings, counts by reason code.
- **Progress log**: one line per `progress_interval_s` with answered/abstained counts and projected finish.
- **Harness reports**: PA by type, category, and reason code; latency percentiles; run comparison.

### 8.3 Error handling
Errors are values: each failure becomes a `ReasonCode` on the attempt or decision. Exceptions are caught only at three boundaries — the question task, the business setup task, and the run — and every caught exception is logged with its traceback in `run.json` (first 100).

### 8.4 Configuration
One immutable `RunConfig`, passed explicitly (no globals). Features not yet past their gate are off by configuration (SPEC §1.3), so P2/P3 code can be merged early without changing production behavior.

### 8.5 Time
- All business dates are `datetime.date`; there is no time-zone logic because inputs carry dates, not instants.
- `as_of_date` is the only notion of "today"; the system clock is never consulted for answers.
- Monotonic clock for `elapsed_ms`, deadlines, and the global stop.

### 8.6 Security posture
No network; generated code runs in separate killable processes with read-only data, external access disabled in DuckDB, and an import allow-list for Python. This is fault containment for model mistakes, not a defense against a hostile adversary (SPEC §12).

---

## 9. Architecture decision records

| ADR | Decision | Status | Source |
|---|---|---|---|
| ADR-001 | Hybrid pipeline (deterministic data/time/format + LLM SQL) | Accepted | AP DEC-1 |
| ADR-002 | DuckDB SQL primary, bounded Python fallback (P2) | Accepted | AP DEC-2 |
| ADR-003 | Model and base image selected by bake-off on Colab G4 | Accepted (outcome 11-09) | AP DEC-3 |
| ADR-004 | Compiled per-business views behind a switch | Proposed (P2, 11-11) | AP DEC-4 |
| ADR-005 | Deterministic temporal resolution with structured `TimeExpr` | Accepted | AP DEC-5, SPEC SC-6 |
| ADR-006 | Rulebook as data; split-level `TemporalParams` | Accepted | AP DEC-6, SPEC SC-1 |
| ADR-007 | No ensembles or learned calibration in P1 | Accepted | AP DEC-7 |
| ADR-008 | Rule gate as P1 decision policy | Proposed (default) | AP DEC-8 |
| ADR-009 | No fine-tuning on the critical path | Accepted | AP DEC-9 |
| ADR-010 | Thinking off by default; per-stage switch | Proposed (default) | AP DEC-10 |
| ADR-011 | Accent folding for retrieval keys and SQL identifiers only | Proposed (lead to confirm) | AP DEC-11, SPEC SC-2 |
| ADR-012 | Two independent single-GPU replicas; no TP in baseline | Proposed (default) | AP DEC-13 |
| ADR-013 | SQLite via stdlib, DuckDB extensions disabled | Accepted (critical) | SPEC SC-3 |
| ADR-014 | Single-threaded query execution, exact numeric types | Accepted | SPEC SC-4 |
| ADR-015 | Ranking applied by formatter from `item/sort_key/tie_code` | Accepted | SPEC SC-5 |
| ADR-016 | HTTP serving on loopback, in-process engine as fallback | Accepted, verify at G6 | AP §6.3 |
| ADR-017 | Log record written and fsynced before its submission line | Accepted | SPEC §7.11 |
| ADR-018 | Scorer (Lead) and formatter (M2) written by different people against shared goldens | Accepted | IMPLEMENTATION_PLAN §2.1 |
| ADR-019 | Cross-package imports only through each package's `__all__`; protocol implementations must pass shared conformance suites | Accepted | SPEC §4.3, §14.3 |

New decisions are added here with a one-paragraph rationale and a link to the change that implemented them.

---

## 10. Seams for parallel development

The system is cut so that each member's work meets the others' only at a small number of typed seams. Every seam has a contract (SPEC §5), a stand-in the consumer can use before the real component exists, and a test that fails if producer and consumer drift apart.

### 10.1 Seam inventory
| Seam | Producer → Consumer(s) | Contract | Stand-in until real | Compatibility check |
|---|---|---|---|---|
| Catalog | M1 → M2 (gate catalog check), M3 (context pack, executor) | `BusinessCatalog` + DuckDB file | Fake catalogs (TASKS M1-11) | Consumer tests on SchemaCard and catalog fields |
| Split context | M2 → M3 | `SplitContext`, `TemporalParams` | Fixture `SplitContext` in `contracts/testing.py` | Consumer tests; perturbation suite (P2) |
| Time windows | M2 → M3, M2 (gate) | `TimeWindow` | Literal windows in tests | Resolver property tests; consumer tests |
| Model | M3 + M4 → M2 (C1), M1 (C3), M3 (C4, C7) | `ModelClient` → `ModelCall` | `ScriptedModelClient`, `ReplayModelClient` | `ModelClient` conformance suite |
| Execution | M3 (C8) → M3 (C7) | `Executor` → `ExecutionResult` | In-process fake executor in `contracts/testing.py` | `Executor` conformance suite |
| Attempts | M3 → M2 | `SolverAttempt`, `TypedValue` | Scripted attempts | Consumer tests in `decision/` |
| Answer | M2 → M4 | `Decision`, `SubmissionRecord` | Stub decision in `run.py` stub mode | Formatter goldens shared with the scorer |
| Records | M4 → Lead (harness), organizers | `LogRecord`, `BusinessLogRecord`, `RunRecord` | — | JSON-schema validation of every line |
| Sink | M4 → all pipeline stages | `SubmissionSink` | `InMemorySink` | `SubmissionSink` conformance suite |
| Calendar | M2 → M2 | `LunarCalendar` | Small fixture calendar | `LunarCalendar` conformance suite |

### 10.2 Rules that keep the seams stable
1. **Contracts are the only shared types.** Nothing else is imported across packages except names in each package's `__all__` (ADR-019; SPEC §4.3).
2. **Stand-ins pass the same tests as real components.** Test doubles and fakes run against the conformance suites, so passing against a stand-in means passing against the real thing (SPEC §14.3).
3. **Consumers write down their assumptions.** Any assumption about another member's output becomes a consumer test that the producer must keep green (SPEC §14.4).
4. **Stub mode for integration.** `run.py` can replace any stage with its stand-in by configuration (`--dev --stub <stage>`), so the lead integrates components one at a time (TASKS L-05).
5. **Replay fixtures pin model behavior on CPU.** Recorded `ModelCall`s are keyed by request hash and carry their template versions; a prompt change refreshes them in the same merge (SPEC §7.13.5).
6. **Switches isolate unfinished work.** P2/P3 code is merged with its switch off (SPEC §1.3).

### 10.3 Test tree by seam
```
tests/
├── contract/
│   ├── test_schemas.py           # round-trip, invariants, schema diff (Lead)
│   ├── conformance/              # one suite per protocol (Lead); run against doubles and real implementations
│   │   ├── test_model_client.py
│   │   ├── test_executor.py
│   │   ├── test_lunar_calendar.py
│   │   └── test_submission_sink.py
│   └── consumers/                # written by consumers; named <consumer>__<producer>__<assumption>.py
├── unit/<package>/               # owner of the package
├── integration/                  # Lead; ReplayModelClient on fixture businesses
├── determinism/                  # Lead; two runs, byte comparison
├── golden/                       # Brief examples shared by scorer (Lead) and formatter (M2)
└── fixtures/
    ├── businesses/               # M1
    ├── catalogs/                 # M1 (fake catalogs)
    ├── rulebooks/                # M2
    └── model_calls/              # M3
```

---

## 11. Quality attributes

| Attribute | Target | Mechanism | Verified by |
|---|---|---|---|
| Correctness of format | 100% valid lines | Formatter goldens; schema validation | SPEC §9, G2 |
| Reproducibility | identical submissions on re-run | §8.1 | G4, G7 |
| Runtime | ≤ 2.5 h for 1,000 questions | Two replicas, prefix caching, deadlines, degrade mode | G3, G6 |
| Robustness | no crash ends the run | Boundary exception handling, process isolation | Fault-injection tests (TASKS M4-11) |
| Compliance | all DG §10 checks pass | Writer, records, precheck script | G6, G8 |
| Generalization | held-out-business PA tracked | Schema-driven design; grouped CV | C14 reports |
| Parallel development | four members build at once without breaking each other | Seams of §10: contracts, fakes, conformance and consumer tests, public-API rule | I1 walking skeleton; CI on every merge |

---

## 12. Residual architectural risks
The full register is AP §12. Risks that this architecture specifically depends on:

| Risk | Architectural dependency | Fallback built in |
|---|---|---|
| RISK-1 No Docker sm_120 host | G6/G7 rehearsal and the private-test run | None in software; must be resolved by DEC-14 |
| RISK-3 Newer vLLM fails on sm_120 | C13 on the chosen base image | Model choice on the reference image (ADR-003) |
| RISK-4 Batch-invariant mode unavailable | Determinism under concurrency | Short structured generations; lower concurrency by config |
| V10 Loopback unavailable under `--network none` | HTTP serving | In-process `AsyncLLM` client (ADR-016) |
| Model does not fit 32 GB with KV cache | DP topology | TP=2 contingency config (SPEC §7.13.1) |
