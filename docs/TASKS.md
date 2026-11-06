# DataMate 2026 — Task Breakdown

| Field | Value |
|---|---|
| **Document** | `TASKS.md` |
| **Version** | 1.1 — restructured for one lead and four members |
| **Status** | Baseline backlog; status column maintained by task owners, reviewed daily by the lead |
| **Date** | 2026-11-06 (GMT+7) |
| **Inputs** | `SPEC.md` v1.1 (requirements and acceptance tests), `ARCHITECTURE.md` v1.1 (module layout and seams), `IMPLEMENTATION_PLAN.md` v1.1 (team, schedule, collaboration rules) |

### Conventions
- **Owner prefixes**: `L` lead, `M1`–`M4` members (roles in `IMPLEMENTATION_PLAN.md` §2). The prefix is the owner. IDs are stable from v1.1; new tasks are appended, never renumbered. v1.0 IDs are mapped in §9.
- **Ph**: P1 baseline, P2 accuracy, P3 optional (gated), INT integration/release, COL collaboration infrastructure.
- **Est**: engineer-hours. **Due**: end of day (GMT+7) unless a time is given.
- **Rev**: required reviewer (another owner); see `IMPLEMENTATION_PLAN.md` §4.2.
- **Done when**: acceptance criteria; every task also meets the definition of done in `IMPLEMENTATION_PLAN.md` §6.2.
- **Status**: `Todo` → `Doing` → `Review` → `Done` (or `Dropped`, with reason).
- A P2/P3 task is merged behind its configuration switch with the production default **off** until its gate passes (SPEC §1.3).

---

## 1. Lead — Integration, Contracts & Evaluation (`contracts/`, `eval/`, CI)

| ID | Task | Ph | Est | Due | Depends on | Rev | Done when | Status |
|---|---|---|---|---|---|---|---|---|
| L-01 | Assign members to M1–M4; decide DEC-11 (+ SPEC SC-2) and DEC-13 | P1 | 1 | 11-06 | — | — | Decisions recorded in AP §13 and ARCH §9 | Todo |
| L-02 | Repository, CI (pytest, ruff, mypy for `contracts`/`temporal`/`formatting`, import-graph check, id-literal scan, schema-diff check), branch protection | COL | 4 | 11-07 | — | M4 | CI runs on every merge request; failing checks block merge (SPEC §4.3, §2.5, §14.2, §15) | Todo |
| L-03 | Secure the E5 rehearsal/private-run host (DEC-14) | P1 | 3 | **11-07** | — | — | Host with sm_120 GPU(s), Docker, NVIDIA Container Toolkit; `nvidia-smi` works in a container; booked for 11-10, 11-13–11-15 and the private-test window | Todo |
| L-04 | `contracts/` v1.0.0: all types of SPEC §5, enums, codes, protocols, test doubles, exported schemas | P1 | 6 | **11-07 12:00** | L-02, L-11 | M1–M4 (each reviews the types it produces) | Contract tests pass (round-trip, invariants §5.9); schemas committed; `ReplayModelClient`, `ScriptedModelClient`, `InMemorySink`, `FakeDeadline` available | Todo |
| L-05 | Walking-skeleton integration: replace stubs as components land | INT | 3 | 11-08 | L-04; M1-11, M2-04, M3-05, M2-06, M4-06 | — | `run.main` produces valid submission and log files on fixtures with `ReplayModelClient` (I1) | Todo |
| L-06 | Coordinate first full training-split run on G4 | INT | 2 | 11-09 15:00 | L-05, M4-02, M3-02 | — | Run completes; per-type PA and crash list published | Todo |
| L-07 | Decision reviews: DEC-3/8/10 (11-09), DEC-4 (11-11), P3 go/no-go (11-12), freeze (11-13) | INT | 2 | per plan §7 | L-13, M2-12, M2-13, M3-12, M4-16 | — | Each decision recorded with the evidence used | Todo |
| L-08 | Safety submission sign-off | INT | 1 | 11-14 | M4-17 | — | Link, md5, and size submitted; submission log updated | Todo |
| L-09 | Final submission | INT | 2 | 11-16 18:00 | M4-18 | — | Final image verified from a second machine and submitted | Todo |
| L-10 | Local scorer per Brief §2.1–2.2 (independent oracle; not written by the formatter's author) | P1 | 6 | 11-07 | L-04 | M2 | 100% agreement on every Brief example (G0) | Todo |
| L-11 | Resolve SPEC V1–V5 (list/table wire shapes, rounding, boolean, tie-code order) against the Brief and training answers | P1 | 3 | **11-07 10:00** | — | M2 | Findings posted before contracts freeze; SPEC updated through SPEC §15 if needed | Todo |
| L-12 | Harness: entry point, folds, resume, run records, environment-fingerprint check, reports, `compare_runs` | P1 | 8 | 11-09 | L-10, M4-06 | M4 | SPEC §7.14; resumable on Colab; refuses to compare runs with different fingerprints unless `--allow-env-diff`; projections at 500/1,000 questions | Todo |
| L-13 | Bake-off analysis and DEC-3 recommendation | P1 | 2 | 11-09 | M3-08 | — | Recommendation with evidence to L-07 | Todo |
| L-14 | Error analysis by type, category, reason code, owning component | INT | 4 | 11-10 | L-06 | — | Top error classes with examples, each assigned to an owner | Todo |
| L-15 | Determinism check: two full runs on G4 | INT | 3 | 11-11 | L-12 | M4 | G4: identical submissions or \|ΔPA\| ≤ 0.005 | Todo |
| L-16 | Compare container run (M4-16) with G4 run | INT | 3 | 11-13 | M4-16 | M4 | \|ΔPA\| ≤ 0.01 between environments, or differences explained | Todo |
| L-17 | Second container run comparison for G7 | INT | 3 | 11-15 | M4-17 | M4 | G7: identical submissions or \|ΔPA\| ≤ 0.005 | Todo |
| L-18 | Nightly harness operation, golden-baseline diff, morning report | INT | 3 | daily 11-09–11-15 | L-12 | — | Report posted before stand-up: PA, changed answers vs. previous night with commit range, new reason codes | Todo |
| L-19 | `CODEOWNERS`, merge-request template (SPEC section, tests, run record, contract impact), handoff tracker | COL | 1 | 11-07 | L-02 | — | Every package path has an owner and a required reviewer (plan §4.2) | Todo |
| L-20 | Determinism CI: run `run.main` twice on fixtures with `ReplayModelClient`; byte-compare outputs | COL | 2 | 11-08 | L-05 | M4 | CI fails on any byte difference between the two runs (SPEC §14.5) | Todo |

---

## 2. M1 — Data & Semantics (`ingest/`, `catalog/`, `entities/`, `lexicon/`, `semantics/`)

| ID | Task | Ph | Est | Due | Depends on | Rev | Done when | Status |
|---|---|---|---|---|---|---|---|---|
| M1-01 | Inspect training split; data-inspection report; fixture set v0 | P1 | 4 | 11-07 | — | L | Report lists file types, sizes, sheet structures, number/date formats, README quality; fixtures under `tests/fixtures/businesses/` cover every SPEC §7.2 rule | Todo |
| M1-02 | `fold()`, NFC/whitespace normalization, abbreviation lexicon v0 | P1 | 4 | 11-07 | L-04 | M2 | SPEC §7.6.1, §7.4 normalization; lexicon covers abbreviations seen in training questions | Todo |
| M1-03 | CSV reader: encoding detection, dialect sniffing | P1 | 3 | 11-07 | L-04 | M3 | SPEC §7.2.2; cp1258 and UTF-8-SIG fixtures pass | Todo |
| M1-04 | Excel reader (calamine, all sheets, openpyxl fallback) | P1 | 3 | 11-07 | L-04 | M3 | SPEC §7.2.3 reading; native cell types preserved | Todo |
| M1-05 | SQLite reader (stdlib, `mode=ro&immutable=1`) | P1 | 2 | 11-07 | L-04 | M4 | SPEC §7.2.4; WAL-mode fixture on a read-only directory reads without writes; no DuckDB extension (SC-3) | Todo |
| M1-06 | Numeric parsing: null tokens, currency, suffixes, compound forms, per-column convention voting, exact SQL types | P1 | 5 | 11-07 | L-04 | M2 | SPEC §7.2.5; `1.250.000`, `1,5`, `150k`, `1tr2`, `12,5%` fixtures; ambiguous column stays VARCHAR with warning | Todo |
| M1-07 | Date parsing: formats, DMY/MDY evidence, Excel serials, month columns | P1 | 4 | 11-08 | M1-06 | M2 | SPEC §7.2.6; ambiguous `01/02/2025` fixture behaves as specified | Todo |
| M1-08 | Excel block, header, total-row, note-row detection | P1 | 5 | 11-08 | M1-04 | M3 | SPEC §7.2.3 rules; title-row, merged-header, two-block, totals, notes fixtures pass | Todo |
| M1-09 | Identifiers (SC-2) and DuckDB materialization | P1 | 3 | 11-08 | M1-02–M1-06 | M3 | SPEC §7.2.7, §7.2.10; extension auto-install/load disabled; file reopenable read-only | Todo |
| M1-10 | Profiling, keys, joins, date coverage, SchemaCard rendering and budgeting | P1 | 5 | 11-08 | M1-09, M3-03 | M3 | SPEC §7.2.8–7.2.9; byte-identical SchemaCards across setups; 300k-row XLSX ≤ 60 s | Todo |
| M1-11 | **Catalog fakes for other members**: `make_fake_catalog()` builder and 3 prebuilt fixture catalogs (DuckDB + `BusinessCatalog`) | COL | 2 | **11-07** | L-04 | M3 | Published in `tests/fixtures/catalogs/`; M2/M3/M4 can build and query a catalog without the real ingestion code (SPEC §14.4) | Todo |
| M1-12 | Entity linker: index, fuzzy query, ranking | P2 | 8 | 11-11 | M1-10, M1-02 | M3 | SPEC §7.6; total ordering; values exactly as stored; held-out PA with switch on/off | Todo |
| M1-13 | Semantic compiler and view validation (DEC-4) | P2 | 6 | 11-11 | M1-10, M3-02 | M2 | SPEC §7.3; failing views disabled and logged; held-out PA with/without per category | Todo |
| M1-14 | Ingestion fixes from full runs; fixture gaps | INT | 10 | ongoing to 11-13 | L-06 | M3 | Every ingestion warning class seen in training has a fixture; zero setup failures on training split | Todo |

---

## 3. M2 — Rules, Time & Answers (`rules/`, `temporal/`, `decision/`, `formatting/`)

| ID | Task | Ph | Est | Due | Depends on | Rev | Done when | Status |
|---|---|---|---|---|---|---|---|---|
| M2-01 | Inspect `rulebook.md` and `calendar.csv`; calendar alias table; resolve SPEC V6 | P1 | 2 | 11-07 | — | L | Rule parameters present in the training rulebook documented (for tests only, never as code defaults); alias table committed | Todo |
| M2-02 | `LunarCalendar` over `calendar.csv` with validation | P1 | 3 | 11-07 | M2-01, L-04 | M1 | SPEC §7.1 step 2; gap/duplicate/leap-month fixtures; passes the `LunarCalendar` conformance suite | Todo |
| M2-03 | Period arithmetic: weeks by `week_start`, months, quarters, years, shifts, clamping | P1 | 5 | 11-07 | L-04 | M1 | Unit tests for year boundaries, leap years, both week starts | Todo |
| M2-04 | `resolve_windows()` for all P1 `TimeExpr` kinds; coverage ratio; provenance | P1 | 8 | **11-08 12:00** | M2-03 | M3 | SPEC §7.5 P1 rows; property test over 10,000 random cases; `unsupported` → `E_TIME_UNSUPPORTED` | Todo |
| M2-05 | `TemporalParams` extraction (`rules.temporal.v1`), span validation, generic fallback | P1 | 4 | 11-09 | M3-02, M3-03, M2-04 | M3 | SPEC §7.1 step 3; paraphrased spans rejected; empty rulebook → all generic; result in `run.json.split` | Todo |
| M2-06 | Formatter: all types; Decimal-preserving serializer | P1 | 6 | 11-08 | L-04, L-11 | L | SPEC §7.10 goldens pass; the same goldens are used by L-10's scorer | Todo |
| M2-07 | Rule gate, catalog check for missing fields, base features | P1 | 5 | 11-08 | L-04, M1-11 | L | SPEC §7.9 rules 1–7 each tested against fake catalogs and scripted attempts | Todo |
| M2-08 | `RuleProfile` extraction (`rules.profile.v1`) with validation | P2 | 5 | 11-11 | M2-05 | M3 | SPEC §7.1 step 4; unresolved fields listed | Todo |
| M2-09 | Lunar windows: `lunar_holiday`, `lunar_date_range` | P2 | 4 | 11-11 | M2-02, M2-08 | M1 | SPEC §7.5 P2 rows; Tết across two solar years tested | Todo |
| M2-10 | Rulebook-perturbation suite | P2 | 3 | 11-11 | M2-05 | L | Changing week start / inclusivity / holiday window changes resolved windows as expected | Todo |
| M2-11 | Table column-naming conventions from training references | P2 | 2 | 11-10 | L-11 | L | `formatting/table_conventions.md`; table-type PA reported | Todo |
| M2-12 | Gate value check and P2 verifier features | P2 | 4 | 11-11 | M2-07, L-12 | L | G5: rule-gate PA ≥ answer-everything PA on held-out businesses | Todo |
| M2-13 | Calibrator experiment | P3 | 6 | 11-12 | M2-12 | L | Grouped-CV PA vs. rule gate; adopted only by L-07 | Todo |
| M2-14 | Fixes from full runs (temporal, rule, decision, format errors) | INT | 8 | ongoing to 11-13 | L-06 | L | Each assigned error class reduced or explained | Todo |

---

## 4. M3 — Reasoning Engine (`llm/client.py`, `prompts/`, `parse/`, `solver/`, `sandbox/`)

| ID | Task | Ph | Est | Due | Depends on | Rev | Done when | Status |
|---|---|---|---|---|---|---|---|---|
| M3-01 | Colab G4: install candidate vLLM versions; serve each candidate with the 32 GB-equivalent cap | P1 | 4 | 11-07 | M4-01 | M4 | Per candidate: greedy output on sm_120, memory within cap, CUDA graphs on; results table posted (G1) | Todo |
| M3-02 | `HttpModelClient`: explicit params, JSON-schema responses, `enable_thinking`, request hashing, timeout/retry, exact capture | P1 | 5 | **11-07** | L-04, M4-03 | M4 | SPEC §7.13.2; asserts every request body field (D1); byte-exact capture; passes the `ModelClient` conformance suite | Todo |
| M3-03 | Prompt rendering (Jinja2 StrictUndefined), template hashing, tokenizer budgeting | P1 | 3 | 11-07 | L-04 | M1 | SPEC §7.13.4–7.13.5; rendering twice is byte-identical | Todo |
| M3-04 | Question parser + `parse.frame.v1` | P1 | 5 | 11-08 | M3-02, M3-03, M1-02 | M2 | SPEC §7.4; schema-valid frames on ≥ 98% of training questions; invalid → `E_PARSE_INVALID` | Todo |
| M3-05 | Solver: context pack, `solve.sql.v1`, `repair.sql.v1`, attempt loop | P1 | 8 | 11-08 | M3-04, M1-11, M2-04 | M2 | SPEC §7.7.1, §7.7.4; sections 1–5 byte-identical per business (D3); repairs bounded; soft deadline respected | Todo |
| M3-06 | `check_sql`, contract check, `to_typed_value` | P1 | 4 | 11-08 | L-04 | M2 | SPEC §7.7.3, §7.7.5; each violation code tested | Todo |
| M3-07 | Sandbox: killable worker pool, read-only DuckDB, limits, tagged value encoding | P1 | 5 | 11-08 | L-04, M1-11 | M4 | SPEC §7.8 tests; passes the `Executor` conformance suite | Todo |
| M3-08 | Model bake-off runs (analysis by L-13) | INT | 6 | 11-09 | L-06 | L | AP §8.2 protocol for 2–3 candidates; PA, determinism, throughput table | Todo |
| M3-09 | Prompt and few-shot improvements from error analysis | P2 | 6 | 11-11 | L-14 | L | Each change has a run record; held-out PA not lower | Todo |
| M3-10 | Few-shot bank builder (`training_code/data_generation/build_fewshot.py`) + selection with CV leakage guard | P2 | 4 | 11-10 | M3-05 | L | SPEC §7.7.2; leakage test passes; bank listed in `data_manifest.json` | Todo |
| M3-11 | Python fallback (`solve.python.v1`), import guard | P2 | 4 | 11-11 | M3-07 | M4 | SPEC §7.7.4 P2, §7.8 Python rules; switch default off | Todo |
| M3-12 | Multi-strategy agreement experiment | P3 | 6 | 11-12 | M3-09, M2-12 | L | PA, runtime, and determinism vs. single strategy; adopted only by L-07 | Todo |
| M3-13 | **Recorded `ModelCall` fixtures** for CPU integration tests (refreshed when a template version changes) | COL | 4 | **11-08 12:00** | M3-04, M3-05 | L | Fixtures under `tests/fixtures/model_calls/` with template versions in their metadata; integration and determinism CI run on CPU | Todo |

---

## 5. M4 — Platform & Compliance (`run.py`, `config.py`, `runtime/`, `llm/replicas.py`, `llm/inprocess.py`, Docker, `tools/`, compliance docs)

| ID | Task | Ph | Est | Due | Depends on | Rev | Done when | Status |
|---|---|---|---|---|---|---|---|---|
| M4-01 | Pull candidate base images on E4; extract `pip freeze` locks | P1 | 4 | 11-06 | — | L | Lock per candidate base image; vLLM/torch/CUDA versions recorded | Todo |
| M4-02 | Colab environment from lock; Drive layout with checksummed data/model snapshots; session bootstrap notebook | COL | 3 | **11-07** | M4-01 | L | Fresh G4 session reaches a running harness in ≤ 20 min; every member uses the same snapshot SHA-256s (plan §5.3) | Todo |
| M4-03 | Replica manager: launch, health, warm-up, restart, log capture | P1 | 6 | 11-07 | M4-01 | M3 | SPEC §7.13.1; works with `replicas=1` on G4; restart tested | Todo |
| M4-04 | Writer: log-then-submission fsync ordering, duplicate rejection, existing-file rename | P1 | 3 | 11-07 | L-04 | L | SPEC §7.11; passes the `SubmissionSink` conformance suite; crash-in-the-middle test | Todo |
| M4-05 | Orchestrator: plan/assignment, queues, workers, deadlines, degrade mode, global stop, SIGTERM | P1 | 8 | 11-08 | L-04, M4-04 | M3 | SPEC §7.12; assignment identical across runs; global stop writes abstains for all unwritten ids | Todo |
| M4-06 | `run.py` lifecycle and `config.py` (validation, defaults, hashing, `--dev` overrides) with **stub pipeline** usable from day 2 | P1 | 5 | 11-08 | L-04 | L | SPEC §2.1–2.3, §6.1; stub mode lets L-05 integrate components one at a time; exit codes per §2.1 | Todo |
| M4-07 | Record assembly: `LogRecord`, `BusinessLogRecord`, `RunRecord` | P1 | 4 | 11-08 | L-04 | L | SPEC §8.3–8.5 schemas validate; `thinking`/`code`/`output` rules (SC-7) tested | Todo |
| M4-08 | Runtime projection on G4 | P1 | 2 | 11-09 | L-06 | L | AP §7.8 projection reported for 500 and 1,000 questions (G3) | Todo |
| M4-09 | Dockerfile, `predict.sh`, `.dockerignore`, first image build | P1 | 5 | 11-10 | L-07 (DEC-3), M4-06 | L | ARCH §7.1; `linux/amd64`; DG §4 layout; `training_code/` not excluded | Todo |
| M4-10 | 10-question smoke run on E5 with the exact scoring command | INT | 3 | 11-10 | M4-09, L-03 | L | `--network none`, `/data:ro`, both GPUs; loopback serving works (SPEC V10) | Todo |
| M4-11 | Fault-injection tests (replica kill, setup crash, SQL timeout storm, SIGTERM) | P2 | 4 | 11-11 | M4-05 | M3 | Each fault yields the outcome in ARCH §5.3; run completes with valid outputs | Todo |
| M4-12 | Runbooks: build/export/upload, E5 run, private-test run | INT | 2 | 11-12 | M4-09 | L | The lead can execute each runbook without M4 | Todo |
| M4-13 | README (approach, model declarations with `tools/count_params.py`), `training_code/`, `data_manifest.json` | INT | 4 | 11-12 | L-07 (DEC-3), M3-10 | L | SPEC §13.1–13.2; parameter count from shipped safetensors; no-training statement unless DEC-9 adopts LoRA | Todo |
| M4-14 | `tools/precheck.sh` (DG §10 checklist automation) | INT | 3 | 11-12 | M4-07 | L | SPEC §13.3; fails on any missing log field or line | Todo |
| M4-15 | Release candidate RC1 image | INT | 2 | 11-12 | M4-13, M4-14 | L | Built from a tagged commit; size measured | Todo |
| M4-16 | Full rehearsal on E5: training split, exact scoring command | INT | 3 | 11-13 | M4-15, L-03 | L | G6 passes; precheck clean | Todo |
| M4-17 | Safety submission: export, md5, upload, second-machine verify | INT | 2 | 11-14 | M4-16 | L | IMPLEMENTATION_PLAN §8.1 steps 1–9 complete | Todo |
| M4-18 | Final candidate packaging checks (G8) and final export | INT | 3 | 11-16 12:00 | L-17 | L | Uncompressed tar ≤ 100 GB; md5 verified; README final | Todo |

---

## 6. Cross-member handoffs

Each row is a promise from a producer to its consumers. A late handoff is raised at stand-up the same day; consumers keep working against the fake or test double named in the last column.

| # | Artifact | Producer | Consumers | Needed by | Until then, consumers use |
|---|---|---|---|---|---|
| H1 | `contracts/` v1.0.0 + test doubles | L (L-04) | all | 11-07 12:00 | Draft branch of `contracts/` |
| H2 | Format decisions V1–V5 | L (L-11) | M2, L | 11-07 10:00 | SPEC §17 defaults |
| H3 | Fake catalogs | M1 (M1-11) | M2, M3, M4 | 11-07 EOD | Hand-written `BusinessCatalog` in tests |
| H4 | `HttpModelClient` on Colab | M3 (M3-02) | M2 (M2-05), M1 (M1-13) | 11-07 EOD | `ScriptedModelClient` |
| H5 | Replica manager on Colab | M4 (M4-03) | M3 | 11-07 EOD | Manually started vLLM server |
| H6 | `resolve_windows()` P1 | M2 (M2-04) | M3 | 11-08 12:00 | Literal windows in solver tests |
| H7 | Recorded `ModelCall` fixtures | M3 (M3-13) | L, M2, M4 | 11-08 12:00 | `ScriptedModelClient` |
| H8 | Real `setup_business` on fixtures | M1 (M1-10) | M3, L | 11-08 EOD | Fake catalogs (H3) |
| H9 | Formatter + rule gate | M2 (M2-06, M2-07) | M4, L | 11-08 EOD | Stub decision in `run.py` stub mode |
| H10 | `run.main` stub mode + writer | M4 (M4-04, M4-06) | L | 11-08 EOD | Direct pipeline calls in tests |
| H11 | Scorer | L (L-10) | M2, M3 | 11-07 EOD | Brief goldens only |
| H12 | Harness on Colab | L (L-12) | all | 11-09 | Ad-hoc scripts (no accuracy claims allowed) |

---

## 7. Dependency map (P1 critical path)

```
L-02 ─► L-04 ──┬─► M1-03..M1-06 ─► M1-09 ─► M1-10 ─────────────┐
   (11-07)     ├─► M2-03 ─► M2-04 ──────────────────────────────┤
               ├─► M3-02, M3-03 ─► M3-04 ─► M3-05 (+M3-06/07) ──┼─► L-05 ─► L-06 ─► M3-08/L-13 ─► L-07 (DEC-3) ─► M4-09 ─► M4-10
               ├─► L-10, M2-06, M2-07 ──────────────────────────┤                                                     │
               └─► M4-04 ─► M4-05, M4-06, M4-07 ────────────────┘                                                     ▼
L-03 (E5 host) ─────────────────────────────────────────────────────────────────────────────────► M4-16 ─► M4-17 ─► M4-18 ─► L-09
M4-01 ─► M3-01, M4-02, M4-03 (base-image validation, day 0–1)
M1-11 fake catalogs, M3-13 replay fixtures ─► unblock M2/M3/M4/L tests before real components exist
```

---

## 8. Load summary

| Owner | P1 | P2 | P3 | INT | COL | Total | Available (approx.) |
|---|---|---|---|---|---|---|---|
| Lead | 29 | — | — | 26 | 7 | 62 | 75 (after ~15 h of stand-ups, reviews, decisions) |
| M1 | 38 | 14 | — | 10 | 2 | 64 | 90 |
| M2 | 33 | 18 | 6 | 8 | — | 65 | 90 |
| M3 | 34 | 14 | 6 | 6 | 4 | 64 | 90 |
| M4 | 37 | 4 | — | 22 | 3 | 66 | 90 |

Review time (about 1 h per member per day) is part of the slack. P3 hours are spent only if the 11-12 go/no-go approves them.

---

## 9. v1.0 → v1.1 ID mapping

| v1.0 | v1.1 | v1.0 | v1.1 | v1.0 | v1.1 |
|---|---|---|---|---|---|
| A-01 | M1-01 | B-01 | M2-01 | D-01 | L-10 |
| A-02 | M1-03 | B-02 | M1-02 | D-02 | L-11 |
| A-03 | M1-04 | B-03 | M2-02 | D-03 | M2-06 |
| A-04 | M1-05 | B-04 | M2-03 | D-04 | M2-07 |
| A-05 | M1-06 | B-05 | M2-04 | D-05 | L-12 |
| A-06 | M1-07 | B-06 | M2-05 | D-06 | L-13 |
| A-07 | M1-08 | B-07 | M2-08 | D-07 | L-14 |
| A-08 | M1-09 | B-08 | M2-09 | D-08 | M2-11 |
| A-09 | M1-10 | B-09 | M1-13 | D-09 | L-15 |
| A-10 | M1-12 | B-10 | M2-10 | D-10 | M2-12 |
| A-11 | M1-14 | B-11 | M2-14 | D-11 | M2-13 |
| C-01…C-13 | M3-01…M3-13 | E-01…E-18 | M4-01…M4-18 | D-12, D-13, D-14 | L-16, L-17, L-18 |

New in v1.1: L-19, L-20, M1-11.

---

## 10. Backlog (not scheduled; only if time remains after 11-12 and approved by the lead)

| ID | Item | Reason deferred |
|---|---|---|
| X-01 | LoRA fine-tuning experiment (DEC-9) | Off critical path; requires full DG §8 evidence package |
| X-02 | Embedding-based entity linking | Parameter budget; lexical linking first (AP §8.3) |
| X-03 | Thinking-mode solving with bounded budget (DEC-10) | Runtime and reproducibility cost; only if bake-off shows a gain |
| X-04 | TP=2 serving path | Contingency only (DEC-13) |
