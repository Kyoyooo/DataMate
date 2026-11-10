# DataMate 2026 — Task Backlog

| Field | Value |
|---|---|
| **Document** | `TASKS.md` — the single, ordered backlog (source of truth for task status) |
| **Version** | 2.3 — Phase 1 closed (2026-11-08) |
| **Date** | 2026-11-08 (GMT+7) |
| **Inputs** | `SPEC.md` (incl. §18 corrections/deferrals), `IMPLEMENTATION_PLAN.md` (phases, process), `COMPETITION_BRIEF.md` |
| **Status owner** | Each task owner updates their rows in their PR; the lead reviews daily |

### Conventions
- **IDs** are stable. v1.1 IDs are kept; new tasks are appended (L-21+, M1-15+, M2-15+, M3-14+, M4-19+). The prefix is the owner: `L` lead, `M1`–`M4` members (roles in `IMPLEMENTATION_PLAN.md` §2).
- **Rev**: suggested reviewer; review is not enforced. Tell affected members about shared-interface changes (`contracts/`, `config.py` keys, SchemaCard format, prompt ids, reason codes, `fold()`) before merging (`CONTRIBUTING.md`).
- **Env**: `CPU` = any laptop/CI, no GPU or weights; `Colab` = single Colab GPU with model weights; `Docker` = target image on an sm_120 host (E5) with `--network none`.
- **Status**: `Done` = deliverable exists **and** its acceptance checks pass (command and result recorded in the PR); `Review` = deliverable exists, acceptance not yet observed; `Partial` = a bootstrap version is merged and usable as a stand-in, acceptance not met; `Todo`; `Dropped` (with reason).
- **P1/P2/P3** per SPEC §1.3. P2/P3 code merges behind a config switch, default off, until its gate passes.
- Package paths are under `src/datamate/` unless noted.

---

## Phase 1 — Shared foundation and fixture pipeline (target 11-07)

What exists now (commands in `README.md`): one package, contracts 1.0.0, a synthetic fixture business, and a CPU pipeline that reads CSV → DuckDB → scripted parse → time windows → scripted SQL → DuckDB execution → decision → formatting → `submission.jsonl` + logs. On 2026-11-08: `pytest` 123 passed locally (2 of them need `train/` and skip in CI); `ruff` clean.

**Phase 1 status (2026-11-08): closed.** All ten rows below are `Done`. L-02 and L-04 were checked against GitHub; L-19 is recorded on the lead's report that direct pushes to `main` are rejected.

| ID | Title | Owner | Rev | Deps | Package | Deliverable | Acceptance | Env | Status |
|---|---|---|---|---|---|---|---|---|---|
| L-21 | Bootstrap codebase and fixture pipeline | L | M1–M4 | — | all P1 packages, `tests/`, `config/` | Package skeleton, contracts 0.1.0, fixture split `tests/fixtures/split_mini`, scripted dev path, tests, README/CONTRIBUTING | `pytest` 84 passed at completion (123 after L-04/L-11); `ruff check src tests` clean; fixture run exits 0 and scores PA 1.0 against hand-computed answers; production mode refuses scripted backend (exit 2, no output) | CPU | Done |
| L-02 | CPU CI workflow | L | M4 | L-21 | `.github/workflows/ci.yml` | Workflow: install from `requirements-cpu.lock`, `ruff check`, `pytest` | First green run on GitHub on a PR into `main`. Verified 2026-11-08: workflow badge `passing` for `event=pull_request` after PR #4 | CPU | Done |
| L-04 | Contract freeze v1.0.0 | L | M1–M4 (optional) | L-21 | `contracts/` | Contracts v1.0.0; `CONTRACTS_VERSION = "1.0.0"`; DC-1…DC-7 (SPEC §18) accepted by merging | The lead merged PR #4 (`8ca9879` on `main`, 2026-11-08); all tests pass; SPEC §5 and §18 updated in the same PR | CPU | Done |
| L-11 | Verify wire-format assumptions on training references | L | M2 | L-21 | `eval/`, SPEC §17 | Note in SPEC §17 closing V1–V5: list/table shapes, boolean, rounding, tie-code order (already observed: lists are JSON arrays, tables `{columns, rows}`, all 1,884 `number` refs integral) | `score.py` scores `train/answers.jsonl` against itself as PA 1.0; every V-item has evidence or an explicit open question to organizers. Verified 2026-11-08: `python -m datamate.eval.score --pred train/answers.jsonl --answers train/answers.jsonl` → PA 1.0000 (n=3000); `tests/integration/test_train_references.py` passes; SPEC §17 V1–V5 closed, with one question for organizers (percent tie rounding, V3) | CPU | Done |
| L-19 | Protect `main` | L | — | — | GitHub settings | Branch protection on `main`: pull request required, no bypass (`CONTRIBUTING.md`). CODEOWNERS and required approvals **Dropped** (2026-11-08): not needed for this team | `git push origin main` is rejected, and merging a pull request works. Direct-push rejection reported by the lead 2026-11-08; merging confirmed by PR #4 | — | Done |
| M4-04 | Result writer | M4 | L | L-21 | `runtime/writer.py` | Log-then-submission with fsync, duplicate rejection, `.prev-<n>` rotation | `tests/unit/test_writer_and_inputs.py` passes | CPU | Done |
| M4-06 | `run.py` lifecycle and `config.py` | M4 | L | L-21 | `run.py`, `config.py` | Startup checks, `--dev`/`--set`, exit codes 0/1/2, run.json; production refuses dev-only or missing components | `tests/integration/test_fixture_pipeline.py` passes. SPEC's `--stub <stage>` mode is **Dropped**: replaced by the fixture + `ScriptedModelClient` path | CPU | Done |
| M3-06 | `check_sql`, type contract, `to_typed_value` | M3 | M2 | L-21 | `solver/sql_rules.py`, `solver/typed.py` | Single-SELECT check, LIMIT-needs-ORDER-BY, result-shape and type conversion; NULL/no rows → `E_EMPTY_RESULT`; non-finite → `D_IMPLAUSIBLE` | `tests/unit/test_solver_decision.py` passes | CPU | Done |
| M2-03 | Period arithmetic | M2 | M1 | L-21 | `temporal/resolve.py` | Week (mon/sun start), month, quarter, year, shifts, leap years | `tests/unit/test_temporal.py` table cases pass | CPU | Done |
| M1-11 | Catalog fakes for other members | M1 | M3 | L-21 | `tests/fixtures/` | **Replaced** by the real `setup_business` on `tests/fixtures/split_mini` (fixture `catalog` in `tests/conftest.py`) | Any test can build and query a catalog without real data | CPU | Done |

---

## Phase 2 — Real P1 components, developed in parallel (target 11-08 → 11-09)

Every row names the **stand-in now**: the code other members keep using until the task lands. Replacing a stand-in must not change any contract type; if it must, raise a contract change (L-04 process) first.

### M1 — Data & catalog (`ingest/`, `catalog/`, `lexicon/`)

| ID | Title | Owner | Rev | Deps | Package | Stand-in now | Deliverable | Acceptance | Env | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| M1-01 | Training-data inspection report and fixture set v1 | M1 | L | — | `tests/fixtures/businesses/` | `split_mini` (clean CSV only) | Report: file types (train: 107 xlsx, 20 csv, 1 sqlite), sheets, header layouts, number/date formats ("560,000", "1 thg 6 2025"), README quality; small anonymized fixtures, one per pattern | Every pattern in the report has a fixture with a hand-written expected table | CPU | Todo |
| M1-02 | Lexicon: abbreviations and text normalization | M1 | M2 | L-21 | `lexicon/` | `fold()`, `nfc()`, `to_identifier()` exist | `abbrev_vi.tsv` from training questions ("dthu", "sp", "dc", "ko", "nhiu"); `normalize_question()` | Covers every abbreviation seen ≥ 3 times in training questions; `fold` behavior unchanged (consumer tests) | CPU | Partial |
| M1-03 | CSV reader: encoding and dialect | M1 | M3 | M1-01 | `ingest/` | `read_csv` (UTF-8/BOM, sniffed delimiter) | SPEC §7.2.2 encoding cascade, warnings | cp1258, UTF-16, UTF-8-SIG fixtures read identically to their UTF-8 versions | CPU | Partial |
| M1-06 | Numeric parsing | M1 | M2 | M1-01 | `ingest/` | `infer_column_type` (plain ints/decimals only) | SPEC §7.2.5: null tokens, currency, `k/tr/ty` suffixes, `1tr2`, VN/EN/PLAIN voting, raw column kept, BIGINT/DECIMAL | Fixtures `1.250.000`, `560,000`, `1,5`, `150k`, `1tr2`, `12,5%` parse exactly; ambiguous column stays VARCHAR with warning | CPU | Todo |
| M1-07 | Date parsing | M1 | M2 | M1-06 | `ingest/` | ISO dates only | SPEC §7.2.6 formats incl. "1 thg 6 2025", DMY/MDY evidence, Excel serials, month columns, sheet-year for dates without year (rulebook §8) | Every date format in M1-01's report parses; ambiguous `01/02/2025` follows the spec | CPU | Todo |
| M1-04 | Excel reader | M1 | M3 | M1-01 | `ingest/` | xlsx skipped with `W_UNSUPPORTED_FILE` → business `failed` | All sheets via `python-calamine` (openpyxl fallback); native cell types kept | All training xlsx files open; cell types preserved on fixtures | CPU | Todo |
| M1-08 | Excel structure: blocks, headers, totals, notes | M1 | M3 | M1-04 | `ingest/` | — | SPEC §7.2.3 detection rules | Title-row, merged-header, two-block, total-row, note-row fixtures pass | CPU | Todo |
| M1-05 | SQLite reader | M1 | M4 | M1-01 | `ingest/` | sqlite skipped | stdlib `mode=ro&immutable=1`; no DuckDB extension (SC-3) | WAL-mode fixture on a read-only directory reads with zero writes | CPU | Todo |
| M1-09 | Fast materialization | M1 | M3 | M1-03 | `catalog/build.py` | row-by-row `executemany` (too slow: training split not finished in 10 min) | Arrow/columnar bulk load, SC-2 identifiers, extension autoload off | 300k-row file ≤ 60 s; full training split setup measured and logged | CPU | Partial |
| M1-10 | Profiling, keys, joins, data range, SchemaCard | M1 | M3 | M1-09, M3-03 | `catalog/` | basic profile + plain card; `data_range` = union of all DATE columns | SPEC §7.2.8–7.2.9; `data_range` only from fact tables; card budgeted by tokenizer | Byte-identical cards across two setups; `data_range` on training businesses matches README "Dữ liệu có đến hết …" | CPU | Partial |

### M2 — Rules, time, decision, formatting (`rules/`, `temporal/`, `decision/`, `formatting/`)

| ID | Title | Owner | Rev | Deps | Package | Stand-in now | Deliverable | Acceptance | Env | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| M2-01 | Rulebook and calendar inspection | M2 | L | — | docs, `tests/fixtures/rulebooks/` | [Preliminary audit](M2_RULEBOOK_CALENDAR.md); real snapshots pending | Diff of train vs public_test rulebooks (public adds rules; never hard-code either); calendar columns `date,weekday,lunar_day,lunar_month,lunar_year,lunar_leap,holiday` | Report lists every rule the P1 pipeline relies on and where it comes from at runtime | CPU | Partial |
| M2-04 | Resolver completion | M2 | M3 | M2-03 | `temporal/` | P1 subset (see SPEC §18.2) | Year-omitted dates and ranges, rolling weeks/months, `same_period_prior_year`, "same days of previous month" comparison, property test (handoff in SPEC §18.4) | 10,000 random `(as_of, expr)` cases: `start ≤ end`, lengths match the rule | CPU | Review |
| M2-05 | TemporalParams from the rulebook | M2 | M3 | M2-04, M3-02 | `rules/` | [Opt-in CPU boundary and validator](M2_RULEBOOK_CALENDAR.md#h7-temporal-profile-proposal-m2-05); CLI uses generic defaults | One `rule_profile` call (`rules.temporal.v1`), span validation, generic fallback per field | Paraphrased spans rejected; empty rulebook → all generic; train and public_test rulebooks give the expected params; result in run.json | CPU (scripted) → Colab | Partial |
| M2-02 | Lunar calendar | M2 | M1 | M2-01 | `temporal/` | CSV validation and lookup tested on synthetic schema | `LunarCalendar` over `calendar.csv` with validation | Gap/duplicate/leap fixtures; round-trip over the file's range | CPU | Review |
| M2-06 | Formatter completion and shared goldens | M2 | L | L-11 | `formatting/` | [Shared CPU goldens](M2_FORMATTING_DECISION.md) pass for formatter and scorer | `tests/golden/` cases from Brief and rulebook §9 used by both formatter and scorer | Goldens pass for formatter **and** `eval/score.py` | CPU | Review |
| M2-07 | Decision gate completion | M2 | L | M1-10 | `decision/` | [Gate and diagnostic tests](M2_FORMATTING_DECISION.md#m2-07-decision-rule-matrix) pass on CPU; real-data check pending | Fuzzy catalog check (SPEC §7.9), README-aware, features recorded | Each rule tested on fixture catalogs; no false "unanswerable" on the 70 training unanswerables' answerable neighbours (measured in L-14) | CPU | Partial |

### M3 — Model client, prompts, parser, solver, sandbox (`llm/client.py`, `prompts/`, `parse/`, `solver/`, `sandbox/`)

| ID | Title | Owner | Rev | Deps | Package | Stand-in now | Deliverable | Acceptance | Env | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| M3-01 | Serve candidate models on Colab | M3 | M4 | M4-01 | notebooks/notes | — | Greedy serving of 2–3 candidates (≤ 15 B total params, released before 2026-10-26, license checked) with the 32 GB-equivalent cap | Results table: memory, tokens/s, JSON-schema output works, determinism of 2 identical requests. **2026-11-11**: `notebooks/BAKEOFF_G4.ipynb` (generated by `tools/make_bakeoff_notebook.py`, pinned to a commit on `main`, verifies revision/license/release date/parameters, 32 GB cap, held-out whole businesses, two identical runs, throughput) + `tools/bakeoff.py` (tested) + `docs/runbooks/bakeoff.md`. **Not run**: needs Colab G4 and a merged commit | Colab | Partial |
| M3-02 | `HttpModelClient` | M3 | M4 | L-04, M3-01 | `llm/http.py`, `llm/schema.py` | HTTP client implemented; scripted remains development-only | OpenAI-compatible client to vLLM: explicit params, JSON schema adapter, thinking, actual-body hash, timeout/retry, exact generated text and transport evidence (SPEC §18.5) | CPU fake-server tests in `tests/unit/test_model_client.py`; real Colab acceptance pending in `notebooks/M3_02_HTTP_CLIENT_CHECK.ipynb`. No claim of GPU acceptance or M4 review. Rebased onto `main` (contracts `1.4.0`) 2026-11-11: `pytest` 366 passed, `ruff` clean, fixture PA 1.0000 (13/13), production config without `model.base_url` exits 2 | CPU + Colab | Review |
| M3-13 | `ReplayModelClient` and recorded calls | M3 | L | M3-02 | `llm/replay.py`, `tests/fixtures/model_calls/` | `ScriptedModelClient` | Record real `ModelCall`s on Colab for the fixture + ~30 training questions; replay by `request_sha256` | CPU CI runs the pipeline on recorded calls; template change without re-record fails with `E_REPLAY_MISS`. **CPU half done 2026-11-11**: client, recorder, format, `tools/record_model_calls.py`, runbook and a fixture recording made through the scripted client; **no real-model recording yet** (needs Colab) | Colab → CPU | Partial |
| M3-03 | Prompt rendering and token budgeting | M3 | M1 | M3-01 | `prompts/` | Python format templates `*.v1`, hashes in run.json | Tokenizer-based budget (SPEC §7.7.1), sections 1–5 byte-identical per business | Render twice → identical bytes; over-budget → documented reduction order. **2026-11-11**: `llm/tokenizer.py` (local-only HF tokenizer; dev-only character estimate), `prompts/budget.py` (`ContextBuilder`: README head-truncation, few-shot dropped last-first, README dropped, injected SchemaCard-subset hook, then `E_CONTEXT_OVERFLOW`), wired into the pipeline and logged per question; `tests/unit/test_context_budget.py` (370,000-character card, order, determinism, rulebook never truncated). **Open**: real tokenizer test skipped (no local model); SchemaCard subsetting is M1's `select_schema_context` (on `m1/M1-14-implementation-handoff`, not merged) and is **not** wired — until then an oversized card overflows (abstain) | CPU | Review |
| M3-04 | Parser prompt and validation | M3 | M2 | M3-02, M1-02 | `parse/` | validation + `parse.frame.v1` baseline wording | Prompt producing valid `QuestionFrame`s (DC-1, DC-2 fields) | ≥ 98 % schema-valid frames on the training questions; `expected_type` accuracy reported vs `answers.jsonl` | Colab | Partial |
| M3-05 | Solver context and repair loop | M3 | M2 | M3-03, M3-04 | `solver/` | attempt loop with 1 repair | Context pack (rulebook, README, card, windows, type contract), soft deadline | Bounded repairs; per-attempt logs; solve success rate on training reported. **2026-11-11**: `solve.sql.v2` / `repair.sql.v2` (ranked vs `question_order` lists, no rounding in SQL, `COALESCE` only for real zeros, `NULLIF` guards) behind `solver.template_version` (default `v1`; v1 text pinned by a test). **No accuracy measured** — needs a Colab run (held-out PA gate of M3-09) | Colab | Partial |
| M3-07 | Sandbox worker pool | M3 | M4 | L-21 | `sandbox/` | in-process read-only DuckDB, timer interrupt (not isolation) | Killable spawn pool, RLIMIT_AS, per-worker connection cache, same encoding | SPEC §7.8 tests: runaway CTE killed, memory bomb contained, 16 concurrent readers. **2026-11-11**: `sandbox/pool.py` (spawn pool, `RLIMIT_AS`, per-worker connection cache and scratch dir, kill-and-replace on timeout, `E_EXEC_CRASH`), wired into `run.main` (`exec_limits.isolation=process`, `workers=16`); `tests/unit/test_sandbox_pool.py` (9 tests: runaway CTE, hung worker SIGKILLed, killed worker replaced, memory bomb, `COPY`/`read_csv`/`ATTACH`/`INSTALL` rejected, 16 concurrent readers, Decimal 1e14 exactness) pass | CPU | Review |

### M4 — Configuration, orchestration, serving, packaging (`run.py`, `config.py`, `runtime/`, `llm/replicas.py`)

| ID | Title | Owner | Rev | Deps | Package | Stand-in now | Deliverable | Acceptance | Env | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| M4-01 | Base image and lock | M4 | L | — | `requirements.lock` | `requirements-cpu.lock` (CPU only) | Lock from `pip freeze` inside the chosen base image (reference `vllm/vllm-openai:v0.10.1.1`); duckdb/pydantic versions compatible with `pyproject.toml`. [Decision record](decisions/M4-01-base-image.md) and `tools/gen_requirements_lock.sh` written 2026-11-11; the lock itself is **not yet generated** (image not cached locally, not pulled) | CPU tests pass when installed from the lock | Docker (build host) | Partial |
| M4-02 | Colab environment | M4 | L | M4-01 | `notebooks/colab_bootstrap.ipynb` | — | Notebook: mount data/model snapshot with SHA256SUMS, install from lock, run fixture then training subset | Fresh session reaches a scored run in ≤ 20 min. **Written 2026-11-11**: `notebooks/colab_bootstrap.ipynb` (generated by `tools/make_colab_notebook.py`), `config/colab.json`, `tools/colab_helpers.py` (SHA256SUMS create/check, training-subset split); CPU tests in `tests/unit/test_colab_bootstrap.py`. **Not run on Colab**: the 20-minute target is unmeasured | Colab | Review |
| M4-03 | Replica manager | M4 | M3 | M4-01, M3-01 | `llm/replicas.py` | none (manual `vllm serve` on Colab) | Launch/health/warm-up/restart of 1–2 vLLM servers on loopback; logs to `/result/logs/replica-<i>.log` | Works with `replicas=1` on Colab; restart tested. **CPU part done 2026-11-11** (`llm/replicas.py`, `serving.*` config, `tests/unit/test_replicas.py`: 11 tests on a fake server, incl. restart, timeout, busy port, clean shutdown); **real vLLM on a GPU not yet observed** | Colab | Partial |
| M4-05 | Concurrent orchestrator | M4 | M3 | M4-03, M3-02 | `runtime/` | sequential loop in `run.py` | Thread-pool workers per replica, fixed assignment, per-question soft/hard deadlines, global stop, SIGTERM → abstain for unwritten ids | Same submission bytes with 1 and N workers on recorded calls; global stop writes every id. **Done on CPU 2026-11-11** with scripted clients (recorded calls arrive with M3-13): `tests/unit/test_orchestrator.py` — 1 vs 8 workers byte-identical on a two-business split over two replicas, hard/soft deadline, global stop, SIGTERM path, dead-replica drain, managed serving end to end on the fake server | CPU (replay) | Review |
| M4-07 | Records completion | M4 | L | L-04 | `runtime/`, `run.py` | `LogRecord`, businesses.jsonl, run.json (partial fields) | SPEC §8.3–8.5 fields incl. environment fingerprint, replica timings | Schema-validate every log line; `thinking` rule (SC-7) tested with a reasoning-producing client. **2026-11-11**: `LogRecord.degrade`, run.json `model`/`environment`/`timings`/`replicas`, `setup_ms`, bounded prompt logging (`tests/unit/test_records.py`: every line validates, rebuilt request hashes to `request_sha256`); SC-7 covered by `test_model_client.py` | CPU | Review |

### Lead — evaluation (`eval/`)

| ID | Title | Owner | Rev | Deps | Package | Stand-in now | Deliverable | Acceptance | Env | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| L-10 | Scorer completion | L | M2 | L-11 | `eval/score.py` | Brief §2.1 scorer, PA, per-type report | Shared goldens (with M2-06); per-reason-code report | 100 % agreement on goldens; `answers.jsonl` vs itself = 1.0 | CPU | Partial |
| L-12 | Harness | L | M4 | L-10, M4-02 | `eval/harness.py` | `python -m datamate.run` + `python -m datamate.eval.score` | Business folds, run record (config hash, git commit, env fingerprint, model revision), `compare_runs` | Resumable on Colab; refuses mismatched fingerprints without `--allow-env-diff` | CPU + Colab | Todo |
| L-20 | Determinism CI on replayed calls | L | M4 | M3-13 | `tests/determinism/` | `test_fixture_pipeline_is_deterministic` (scripted) | Two fresh processes on recorded calls, byte-compare outputs (timing fields removed) | Fails on any byte difference. `tests/determinism/test_replayed_pipeline.py` (two fresh processes on the fixture recording) passes 2026-11-11 | CPU | Review |
| L-03 | Secure the E5 host (sm_120 + Docker) | L | — | — | — | — | Booked host for 11-10, 11-13…11-15 and the private-test window | `nvidia-smi` works inside a container on that host | Docker | Todo |

---

## Phase 3 — First real end-to-end run on Colab (target 11-09)

| ID | Title | Owner | Rev | Deps | Package | Deliverable | Acceptance | Env | Status |
|---|---|---|---|---|---|---|---|---|---|
| L-05 | Integrate real components | L | M4 | M1-04, M1-06, M1-09, M3-02, M3-04, M3-05, M4-03 | `run.py`, `runtime/` | `config/colab.json`; pipeline runs with `HttpModelClient` on real ingestion | 50 training questions run end-to-end with valid outputs and logs; no scripted component in the path (`run.json.model_backend == "http"`) | Colab | Todo |
| L-06 | First full training-split run | L | M3, M4 | L-05, L-12 | `eval/` | Run record + per-type PA + crash list | All 3,000 questions written; PA reported by type and reason code (harness only — no accuracy claim otherwise) | Colab | Todo |
| M4-08 | Runtime projection | M4 | L | L-06 | `eval/` | Load time + mean per-question time; projection for 500 and 1,000 questions on 2 × 5090 | Projection ≤ 50 % of the 6 h budget or a mitigation plan | Colab | Todo |
| M3-08 | Model bake-off | M3 | L | L-06 | — | 2–3 candidates on the same run protocol | PA, determinism (2 runs), throughput per candidate. **Protocol and notebook ready 2026-11-11** (same notebook as M3-01, plus the determinism matrix: `max_num_seqs`, prefix caching, `VLLM_BATCH_INVARIANT`, structured outputs); **no measurements yet** | Colab | Partial |
| L-13 | DEC-3: model and base image | L | M3, M4 | M3-08, M4-08 | `IMPLEMENTATION_PLAN.md` §7 | Decision record with evidence; parameter count from shipped safetensors | Model ≤ 15 B total params, public before 2026-10-26, license permits use | Colab | Todo |

---

## Phase 4 — Evaluation and correctness fixes (target 11-10 → 11-11)

| ID | Title | Owner | Rev | Deps | Package | Deliverable | Acceptance | Env | Status |
|---|---|---|---|---|---|---|---|---|---|
| L-14 | Error analysis | L | — | L-06 | `eval/` | Top error classes by type, reason code, owning component, with examples | Every class above 1 % of questions has an owner and a task | CPU | Todo |
| L-18 | Nightly run and diff | L | — | L-12 | `eval/` | Nightly harness on the day's `main`; changed answers vs previous night with commit range | Report before stand-up each day 11-10 → 11-15 | Colab | Todo |
| M1-14 | Ingestion fixes from full runs | M1 | M3 | L-14 | `ingest/`, `catalog/` | Fixes + a fixture per fixed pattern | Zero setup failures on training; each fix has a regression fixture | CPU | Todo |
| M2-14 | Temporal / decision / format fixes | M2 | L | L-14 | M2 packages | Fixes with regression tests | Each assigned class reduced or explained in the PR | CPU | Todo |
| M3-09 | Prompt and SQL-rule improvements | M3 | L | L-14 | `prompts/`, `solver/` | New template versions (`.v2`…), refreshed recorded calls | Held-out PA (by business fold) not lower; run record attached | Colab | Todo |
| M4-19 | Logging review against DG §3.3 | M4 | L | L-06 | `runtime/` | Check `thinking`/`code`/`output` on a real run (e.g. thinking on vs off) | Every log line has the required fields; `thinking` is exact model reasoning or `null`. CPU side covered by M4-07; **the check on a real run (thinking on vs off) still needs Colab** | Colab | Partial |
| L-15 | Determinism check: two full runs | L | M4 | L-12 | `eval/` | `compare_runs` on two identical Colab runs | Identical submissions or \|ΔPA\| ≤ 0.005 | Colab | Todo |

---

## Phase 5 — P2 features, each added only when results justify it (target 11-10 → 11-12)

Each feature merges behind its switch (default **off**) and is turned on only by L-07 with a run record showing held-out PA gain without runtime or determinism regressions.

| ID | Title | Owner | Rev | Deps | Package | Deliverable | Acceptance (gate) | Env | Status |
|---|---|---|---|---|---|---|---|---|---|
| M2-08 | RuleProfile: definitions, ranking default, rounding rules | M2 | M3 | M2-05 | `rules/` | `rules.profile.v1`; rounding/`money_decimals` and list-order rules read from the mounted rulebook (replaces config defaults of DC-1) | Same profile values on train and public_test where their rulebooks agree; differences picked up where they differ | Colab | Todo |
| M2-09 | Lunar windows (Tết, rằm, mùng) | M2 | M1 | M2-02, M2-08 | `temporal/` | `lunar_holiday`, `lunar_date_range` from rulebook-defined windows | Tết across two solar years; held-out PA gain on lunar questions | CPU | Todo |
| M2-15 | Sub-day windows (ca sáng/chiều, giờ cao điểm) | M2 | M3 | M2-08 | `temporal/`, `contracts/` | Time-of-day ranges from the rulebook passed to the solver | Fixture with timestamps; gain on shift questions | CPU | Todo |
| M2-10 | Rulebook-perturbation suite | M2 | L | M2-05 | `tests/` | Altered rulebooks (week start, inclusivity, Tết window) | Windows change exactly as the altered rule says | CPU | Todo |
| M2-11 | Table column conventions | M2 | L | L-11 | `formatting/` | `formatting/table_conventions.md`; per-column numeric kind | Table-type PA reported before/after | CPU | Todo |
| M2-12 | Gate value check, verifier features | M2 | L | M2-07, L-12 | `decision/` | Features recorded; abstain thresholds evaluated | G5: gate PA ≥ answer-everything PA on held-out businesses | Colab | Todo |
| M1-12 | Entity linker | M1 | M3 | M1-10, M1-02 | `entities/` (new) | Fuzzy lexical candidates with codes; values exactly as stored | Held-out PA with switch on vs off | CPU | Todo |
| M1-13 | Semantic compiler / validated views (DEC-4) | M1 | M2 | M1-10, M3-02 | `semantics/` (new) | Rulebook-derived views (valid orders, revenue lines, base-unit quantities) with validation | Failing views disabled and logged; held-out PA per category | Colab | Todo |
| M1-15 | Unit conversion tables | M1 | M2 | M1-10 | `catalog/` | Parse README / conversion sheets into a `unit_conversion` table (base vs large units) | "Tồn theo đơn vị lớn" and "bán được bao nhiêu <đơn vị>" fixtures answer correctly | CPU | Todo |
| M3-10 | Few-shot bank with leakage guard | M3 | L | M3-05 | `solver/`, `training_code/` | Bank built from the training split only | Leakage test (fold exclusion) passes; bank in `data_manifest.json`. **2026-11-11, partial**: `solver/fewshot.py` (deterministic selection, `fewshot_exclude_businesses` guard), `training_code/data_generation/build_fewshot.py` (keeps only answers scoring correct; refuses runs/splits without training answers), pipeline wiring for v2, tests in `tests/unit/test_prompts_fewshot.py`. **Bank not built**: needs a real model run on the training split; manifest entry follows | CPU | Partial |
| M3-11 | Python fallback | M3 | M4 | M3-07 | `sandbox/` | `solve.python.v1`, import allow-list, killable worker | Default off; gain on procedural questions. **2026-11-11, CPU part**: `sandbox/python_exec.py` (import allow-list, no `open`/`eval`/`exec`/`compile`/`input`, exact Decimal conversion), `SandboxPool.run_python` (killable), `solve.python.v1`, solver fallback stage behind `solver.python_fallback` (default **false**), `tests/unit/test_python_fallback.py` (17). **Gain unmeasured**; the lead's L-07 decides the switch | CPU + Colab | Review |
| M2-13 | Calibrator (P3) | M2 | L | M2-12 | `decision/` | Grouped-CV calibrator | Adopted only by L-07 | Colab | Todo |
| M3-12 | Multi-strategy agreement (P3) | M3 | L | M3-09, M2-12 | `solver/` | Agreement-based answer/abstain | Adopted only by L-07; runtime within budget | Colab | Todo |
| L-07 | Decision reviews (DEC-3/4/8/10, P2 switches, P3 go/no-go, freeze 11-13) | L | — | per decision | `IMPLEMENTATION_PLAN.md` §7 | Decision records with evidence | Each switch change cites a run record | — | Todo |

---

## Phase 6 — Docker and target-hardware validation (target 11-10 → 11-13)

| ID | Title | Owner | Rev | Deps | Package | Deliverable | Acceptance | Env | Status |
|---|---|---|---|---|---|---|---|---|---|
| M4-09 | Dockerfile and `predict.sh` | M4 | L | L-13, M4-01, M4-05 | `Dockerfile`, `predict.sh`, `.dockerignore` | Image per DG §4 layout; `predict.sh` no args, fixed env (SPEC §2.4), `python -m datamate.run --config /code/config/run_config.json --data-dir /data --result-dir /result` | `docker build --platform linux/amd64` succeeds; inside the image, `predict.sh` on the fixture split writes valid outputs when the model is present, and exits 2 with no submission when it is absent. **2026-11-11, partial**: Dockerfile, `predict.sh`, `.dockerignore`, frozen `config/run_config.json` (model path `UNSELECTED`, serving params are placeholders pending DEC-3), `tools/build_image.sh`; static tests in `tests/unit/test_packaging.py`; CPU smoke build and runs on a **stand-in base image** (a locally cached vLLM 0.22.1 image, not the reference image, no GPU): exit 2 with no `submission.jsonl` when weights are absent; exit 0, 13 lines, `--network none`, two loopback fake replicas when a fake model is mounted. **Not done**: build on the reference base (`requirements.lock` not generated), real weights, sm_120 | Docker | Partial |
| M4-10 | E5 smoke run | M4 | L | M4-09, L-03 | — | 10 training questions with the exact organizer command (`--network none`, `/data:ro`, 2 GPUs) | Valid submission and logs; loopback serving works offline (SPEC V10) | Docker | Todo |
| M4-11 | Fault injection | M4 | M3 | M4-05 | `tests/` | Replica kill, setup crash, SQL-timeout storm, SIGTERM | Each fault ends with valid outputs and every id written | CPU + Colab | Todo |
| M4-13 | Compliance README, `training_code/`, `data_manifest.json` | M4 | L | L-13, M3-10 | `/code/README.md`, `training_code/` | Model declarations (name, URL, revision, release date, license, param count from `tools/count_params.py`); data manifest with SHA-256; "no fine-tuning" statement unless DEC-9 | Reviewed against DG §8 checklist. **2026-11-11, partial**: `tools/count_params.py` (tested on hand-built safetensors), `training_code/` (README, manifest builder, empty `data_manifest.json`), `docs/SUBMISSION_README.md` (shipped as `/code/README.md`, model fields marked `TO FILL`). **Open**: model declarations (need DEC-3), few-shot bank (M3-10), lead decision to package the full train split | CPU | Partial |
| M4-14 | `tools/precheck.sh` | M4 | L | M4-07 | `tools/` | DG §10 checks: one line per question, log fields, size, platform. **2026-11-11**: `tools/precheck.sh` + `precheck.py` (submission/log validation, run.json counts, runtime projection, two-run comparison, PA on training answers, image platform/files/README placeholders/tar size) | Fails on a deliberately broken result dir: `tests/unit/test_precheck.py` (8 broken variants, compare, usage errors) passes; the `--image` checks are written but **not run** (no reference image built) | CPU | Review |
| M4-15 | Release candidate RC1 | M4 | L | M4-13, M4-14 | — | Image from a tagged commit; uncompressed size measured | ≤ 100 GB uncompressed `docker save` | Docker | Todo |
| M4-16 | Full rehearsal on E5 | M4 | L | M4-15, L-03 | — | Full training split in the container, exact command | G6: completes within budget; precheck clean | Docker | Todo |
| L-16 | Container vs Colab comparison | L | M4 | M4-16, L-06 | `eval/` | `compare_runs` report | \|ΔPA\| ≤ 0.01 or differences explained | Docker | Todo |

---

## Phase 7 — Reproducibility checks and release (target 11-14 → 11-16; private test 11-20 → 11-23)

| ID | Title | Owner | Rev | Deps | Package | Deliverable | Acceptance | Env | Status |
|---|---|---|---|---|---|---|---|---|---|
| M4-12 | Runbooks | M4 | L | M4-09 | `docs/runbooks/` | Build/export/upload, E5 run, private-test run. **Drafted 2026-11-11** in `docs/runbooks/` (build-export-upload, e5-run, private-test-run, record-model-calls) from DG §9–§11; none has been executed end to end | The lead can execute each without M4 — needs the lead's dry run | — | Review |
| L-17 | Second container run (G7) | L | M4 | M4-16 | `eval/` | Two container runs on the same input | Identical submissions or \|ΔPA\| ≤ 0.005 (organizer bound is 0.03) | Docker | Todo |
| M4-17 | Safety submission | M4 | L | M4-16 | — | Export, md5, upload, second-machine `md5sum -c` | IMPLEMENTATION_PLAN §8.1 steps complete by 11-14 | Docker | Todo |
| L-08 | Safety submission sign-off | L | — | M4-17 | — | Link, md5, size recorded | Submitted via the official form | — | Todo |
| M4-18 | Final packaging checks (G8) | M4 | L | L-17 | — | Final image, README final | ≤ 100 GB; md5 verified; frozen config matches last G6 run | Docker | Todo |
| L-09 | Final submission | L | — | M4-18 | — | Final image submitted | Before 2026-11-16 18:00 (deadline 23:59) | — | Todo |
| L-22 | Private-test run | L | M4 | L-09 | — | Frozen image run on E5 after 11-20 09:00; `submission.jsonl` uploaded; full `/result` archived | Uploaded before 2026-11-23 23:59; no rebuild of the frozen image | Docker | Todo |

---

## Dependency map (compact)

```
Phase 1 (done) ── L-21 bootstrap ─┬─ L-04 contract freeze ─────────────────────────────┐
                                  │                                                     │
Phase 2   M1: M1-01 → M1-04 → M1-08      M1-06 → M1-07      M1-03 → M1-09 → M1-10 ───┤
          M2: M2-04 ─┬─ M2-05 (needs M3-02)    M2-06, M2-07 ───────────────────────────┤
          M3: M3-01 → M3-02 → M3-04 → M3-05 ;  M3-02 → M3-13 → L-20                     │
          M4: M4-01 → M4-02, M4-03 → M4-05                                              │
          L : L-11 → L-10 → L-12 ;  L-03 (E5 host, external)                            │
                                                                                        ▼
Phase 3   L-05 integrate ─► L-06 full train run ─► M3-08 bake-off + M4-08 projection ─► L-13 DEC-3
Phase 4   L-06 ─► L-14 error analysis ─► M1-14 / M2-14 / M3-09 ;  L-15 determinism
Phase 5   L-14 + switches ─► M2-08/09/15, M1-12/13/15, M3-10/11 ─► L-07 decisions
Phase 6   L-13 + M4-05 ─► M4-09 image ─► M4-10 smoke (needs L-03) ─► M4-13/14 ─► M4-15 RC1 ─► M4-16 rehearsal ─► L-16
Phase 7   M4-16 ─► M4-17 safety (11-14) ─► L-17 ─► M4-18 ─► L-09 final (11-16) ─► L-22 private run
```

## Critical path

`M3-01 → M3-02 HttpModelClient` and `M1-04/M1-06/M1-09 real ingestion (xlsx is 107 of 128 training files)` → `L-05 integrate` → `L-06 first full run` → `L-13 DEC-3` → `M4-09 image` → `M4-16 rehearsal on E5` → `M4-17 safety submission` → `L-09 final`.

- Slack is near zero: the deadline is 9 days away. Anything not on this path waits if the path slips (IMPLEMENTATION_PLAN §11).
- **External dependency: L-03 (E5 host).** Without it there is no target-hardware validation; escalate on 11-08 if not booked.
- Model choice (DEC-3) gates the image; M3-01 must start on day 1.

## Handoffs

| # | Artifact | Producer → consumers | Needed by | Consumers use until then |
|---|---|---|---|---|
| H1 | Contracts v1.0.0 (L-04) | L → all | Delivered 11-08 (PR #4) | — |
| H2 | Real catalog on training businesses (M1-04/06/09/10) | M1 → M3, M2, L | 11-09 | `tests/fixtures/split_mini` catalog |
| H3 | `HttpModelClient` (M3-02) | M3 → M2 (M2-05), M1 (M1-13), L (L-05) | 11-08 EOD | `ScriptedModelClient` |
| H4 | Replica manager on Colab (M4-03) | M4 → M3, L | 11-08 EOD | manually started `vllm serve` |
| H5 | Recorded calls + `ReplayModelClient` (M3-13) | M3 → L (L-20), M4 (M4-05), M2 | 11-09 | `ScriptedModelClient` scripts |
| H6 | Resolver completion (M2-04) | M2 → M3 | 11-09 | P1 subset; unsupported → abstain |
| H7 | TemporalParams from rulebook (M2-05) | M2 → M3, L | 11-09 | generic `TemporalParams` |
| H8 | Harness + run records (L-12) | L → all | 11-09 | `datamate.run` + `datamate.eval.score` |
| H9 | Orchestrator concurrency (M4-05) | M4 → L | 11-10 | sequential `run.py` |
| H10 | DEC-3 model decision (L-13) | L → M4 (M4-09, M4-13) | 11-09 EOD | reference base image `vllm/vllm-openai:v0.10.1.1` |
| H11 | Image + `predict.sh` (M4-09) | M4 → L | 11-10 | `python -m datamate.run` |

## First three actionable tasks per person

| Person | 1 | 2 | 3 |
|---|---|---|---|
| Lead | **L-04** review and freeze contracts; accept/revert DC-1…DC-7 | **L-11** verify wire formats on `train/answers.jsonl`; close SPEC V1–V5 | **L-03** book the E5 host (escalate on 11-08 if none) |
| M1 | **M1-01** training-file inspection report + fixtures | **M1-04** Excel reader (most training files are xlsx) | **M1-09** fast bulk load (current reader is too slow for real files) |
| M2 | **M2-01** rulebook (train vs public_test) and calendar inspection | **M2-04** resolver completion + property test | **M2-05** TemporalParams extraction against `ScriptedModelClient`, then real client |
| M3 | **M3-01** serve 2–3 candidate models on Colab | **M3-02** `HttpModelClient` (unit-tested on a local fake server) | **M3-13** record calls + `ReplayModelClient` for CPU CI |
| M4 | **M4-01** base-image lock | **M4-02** Colab bootstrap notebook | **M4-03** replica manager |

## Not scheduled (only if time remains after 11-12 and approved by the lead)

| ID | Item | Reason deferred |
|---|---|---|
| X-01 | LoRA fine-tuning (DEC-9) | Off critical path; needs full DG §8 evidence package |
| X-02 | Embedding-based entity linking | Parameter budget; lexical linking first |
| X-03 | Thinking-mode solving (DEC-10) | Runtime and reproducibility cost |
| X-04 | TP=2 serving | Contingency only (DEC-13) |

## ID history
- Kept from v1.1 with the same meaning: all `L-`, `M1-`…`M4-` IDs listed above.
- New in v2.0: L-21, L-22, M1-15, M2-15, M4-19.
- Changed: M1-11 is satisfied by the real fixture catalog instead of fake catalogs; M4-06 drops `--stub` mode in favor of the scripted fixture path.
- v1.0 → v1.1 mapping: see `TASKS.md` v1.1 in git history (commit `94c6132`).
