# DataMate 2026 — Architecture Proposal

| Field | Value |
|---|---|
| **Document** | `ARCHITECTURE_PROPOSAL.md` |
| **Version** | 2.1 — ownership updated for one lead and four members |
| **Status** | **Baseline for implementation.** The approved decisions in §3 are binding. Items marked **[DEC-n] OPEN** in §13 still require team-lead sign-off by the date shown. |
| **Date** | 2026-11-06 (GMT+7) |
| **Owner** | Principal Software Architect, on behalf of the team lead |
| **Supersedes** | Version 1.0 (draft, 2026-11-06) |
| **Feeds** | `SPEC.md`, `ARCHITECTURE.md`, `IMPLEMENTATION_PLAN.md`, `TASKS.md` (to be produced in later tasks) |

### Source authority
1. **Official competition rules** (`COMPETITION_BRIEF.md`, cited as **Brief §x**) and the **Docker Submission Guide** (`zac2026_DataMate_docker_guideline_final.md`, cited as **DG §x**) are authoritative. If this document conflicts with either, they prevail, and this document must be corrected.
2. `CLAUDE.md` defines team engineering conventions.
3. This document defines the architecture within those constraints.

### Labeling convention
| Tag | Meaning |
|---|---|
| **[REQ]** | Requirement from the Brief or the Docker guide |
| **[APPROVED]** | Decision confirmed by the team lead |
| **[OBS]** | Observed fact from the workspace or a cited external source |
| **[HYP]** | Hypothesis; must be validated before it is relied upon |
| **[PROP]** | Proposed engineering choice within approved decisions |
| **[DEC-n]** | Decision identifier (register in §13) |
| **[RISK-n]** | Risk identifier (register in §12) |

---

## 0. Executive summary

DataMate answers informal Vietnamese questions over per-business CSV, XLSX, and SQLite data under exact-match scoring (+1 / 0 / −1), on 2 × RTX 5090 inside an offline Docker container, within 6 hours, with a 15B total parameter budget. The final Docker solution is due **2026-11-16 23:59 GMT+7**, ten calendar days from today.

The approved architecture is a **hybrid pipeline**: deterministic data ingestion and profiling, a schema-grounded LLM that writes **DuckDB SQL** (with a bounded Python fallback), **deterministic** temporal resolution, ranking, typing, and formatting driven by the **split-specific rulebook**, and a conservative answer/abstain gate. Ensembles, learned calibration, and fine-tuning are explicitly **outside the initial critical path**.

This revision makes three structural changes relative to v1:

1. **Development environment.** Development and evaluation run on **Google Colab**, which offers a Blackwell **G4 (RTX PRO 6000, sm_120)** runtime but **cannot run Docker** and provides **one GPU per runtime**. The architecture is therefore designed so that everything except the final container rehearsal can be validated in Colab (§4).
2. **Serving topology.** Two **independent single-GPU model replicas** (data parallelism), with **no tensor parallelism and no NCCL** in the baseline. This removes the NCCL hang and shared-memory failure modes described in DG §9–10 and makes the serving path fully testable on a single Colab GPU (§6.3, DEC-13).
3. **Phased delivery.** Components are assigned to Phase 1 (baseline, end-to-end by 2026-11-09), Phase 2 (accuracy), or Phase 3 (optional, gated). Phase 1 alone must produce a valid, compliant, reproducible submission (§10).

The most serious unresolved risk is **infrastructure, not modeling**: the team needs a **Docker-capable sm_120 GPU host** for the container rehearsal and for running the frozen image on the private test (DG §1). That host is not yet identified (RISK-1, DEC-14).

---

## 1. Scope and inputs

### 1.1 In scope
Architecture of the inference system packaged in the Docker image: components, data flow, interfaces, serving, determinism, runtime, logging, compliance, development environment, validation criteria, and risks.

### 1.2 Out of scope for this document
Field-level schemas (→ `SPEC.md`), module-level design (→ `ARCHITECTURE.md`), schedule and owners (→ `IMPLEMENTATION_PLAN.md`, `TASKS.md`), and production code.

### 1.3 Inputs and their status
- **[OBS]** Available to this revision: `ARCHITECTURE_PROPOSAL.md` v1 and the Docker Submission Guide. `CLAUDE.md` and `COMPETITION_BRIEF.md` were not attached to this session. **Brief citations below are carried forward from v1** and should be spot-checked by the team lead against the Brief before `SPEC.md` is written.
- **[OBS]** No training split, repository, or GPU was inspected by the author. Statements about data shape and question distribution remain **[HYP]** until the M0 data-inspection report (§11).

---

## 2. Requirements summary

### 2.1 Scoring
- **[REQ]** +1 correct, 0 abstain or missing, −1 wrong; no partial credit; a type mismatch is wrong (Brief §2.1, §2.3).
- **[REQ]** `unanswerable` is a scored answer class: +1 if the reference is unanswerable, −1 otherwise.
- **Derived.** Answering is worthwhile only if p(correct) > 0.5. Expected score ≈ Σᵢ max(2pᵢ − 1, 0) when confidence is calibrated. **The answer/abstain decision is a first-class component.**
- **Derived.** Choosing the wrong answer type costs as much as computing the wrong value.

### 2.2 Answer types (Brief §2.1–2.2; DG §3.2)
| Type | Architectural consequence |
|---|---|
| `number` | Round to 2 decimals. **[HYP]** Emit an integer literal when the rounded value is integral; int/float handling must be confirmed (Q5). |
| `percent` | Percent units (−12.45, not −0.1245), 2 decimals, correct sign; formula direction from the rulebook or a documented convention. |
| `string` | Local scorer reproduces normalization exactly (NFC → lowercase → non-letter/digit/space → space → collapse). **Diacritics preserved.** Output copied verbatim from data values. |
| `date` | `yyyy-mm-dd`, or `yyyy-mm` for month-level questions. Granularity is part of correctness. |
| `boolean` | **[REQ]** Listed as a value type in DG §3.2. Encoding (JSON `true`/`false`) to be confirmed in `SPEC.md`. |
| `list` | Order matters; ties broken by code ascending; ranking over valid orders only; truncate at k. |
| `table` | Columns matched after normalization with positional fallback; rows matched as a set. |
| `unanswerable` | May include `reason` (DG §3.2). |
| `abstain` | Needs no answer; a missing line also counts as abstain (DG §3.2). |

### 2.3 Inputs (DG §3.1)
```
/data/                      (read-only)
├── data/<business_id>/  *.csv | *.xlsx | *.sqlite, README.md
├── rulebook.md             split-specific rules and vocabulary
├── calendar.csv            shared solar–lunar calendar
└── questions.jsonl         id, business_id, question, as_of_date
```
- **[REQ]** The private rulebook may differ from the training rulebook; no rule may be hard-coded (Brief §3.4).
- **[REQ]** Private test includes unseen business types (Brief §3.1, §3.3). README quality varies from complete to useless (Brief §3.2).
- **[REQ]** 12–30 months of data per business, up to ~300,000 rows, across one or more files.

### 2.4 Outputs (DG §3.2–3.3)
- **[REQ]** `/result/submission.jsonl`: one JSON object per line with `id`, `type`, `answer` (`reason` optional for `unanswerable`). Write each answer **immediately**; only saved answers count if the run stops.
- **[REQ]** `/result/logs/`: one record per question with `id`, `answer`, `elapsed_ms`, `thinking`; plus `code` and `output` when code was executed. `thinking` must be **as generated, not summarized or truncated**; a list of strings in call order when several model calls were made; `null` if no reasoning was generated. Referenced helper functions must exist inside the image.
- **[REQ]** `elapsed_ms` is wall-clock from question start to final answer, including data reads, reasoning, and code execution; with batching, measured from when the question enters its batch. Shared model loading is excluded from `elapsed_ms` but counts toward the 6 hours.

### 2.5 Execution environment (DG §2, §5, §10)
| Item | Requirement |
|---|---|
| GPUs | 2 × RTX 5090, 32 GB each; compute capability 12.0; **no P2P** on the tested pair (DG Fig. 1) |
| RAM | 512 GB |
| CUDA stack | CUDA ≥ 12.8; PyTorch/vLLM with Blackwell support. Recommended base `vllm/vllm-openai:v0.10.1.1`; alternatives must support sm_120 |
| Network | None during inference (`--network none`) |
| Invocation | `bash /code/predict.sh`, no arguments; fixed defaults for model, seed, temperature, batch size; no manual intervention |
| Scoring command | `--gpus '"device=0,1"' --network none --shm-size=16g --entrypoint bash -v …:/data:ro -v …:/result` |
| Time | 6 hours for the full private test, including model loading |
| Models | ≤ 15B total parameters over **all** inference models (language, embedding, reranking, classification; every MoE parameter); quantization allowed; weights released before 2026-10-26 under a permitting license |
| Image | `linux/amd64`; uncompressed `docker save` tar ≤ 100 GB |
| Prohibited | Hard-coded answers; logic keyed on question or business IDs; training on test data; collecting test answers |

### 2.6 Reproducibility and submission workflow (DG §1, §6, §11)
- **[REQ]** Submit and **freeze** the image before the private test is released, **then run that image** on the private test and upload `submission.jsonl`. The organizers' re-run determines the final score.
- **[REQ]** |PA(uploaded) − PA(re-run)| ≤ 0.03; larger unexplained differences lead to disqualification. At N = 500 this is ≤ 15 net points: roughly 7 correct↔wrong flips or 15 correct↔abstain flips.
- **[REQ]** Tie-break: lower total inference time in the organizers' re-run, then earlier submission (DG §7).
- **[REQ]** After the deadline, nothing in the image, code, configs, models, or training artifacts may change (DG §11).

---

## 3. Approved decisions

| ID | Decision | Status | Architectural consequence |
|---|---|---|---|
| **DEC-1** | Hybrid architecture (v1 Option E) | **[APPROVED]** | §5–§7 |
| **DEC-2** | DuckDB SQL primary; bounded Python fallback | **[APPROVED]** | §7.3; fallback is Phase 2 |
| **DEC-3** | Evidence-driven model selection compatible with Colab | **[APPROVED] process**; outcome due 2026-11-09 | §8 bake-off on Colab G4 |
| **DEC-5** | Deterministic temporal processing | **[APPROVED]** | §7.1; the LLM extracts expressions, code resolves dates |
| **DEC-6** | Split-specific rules; nothing hard-coded from the training rulebook | **[APPROVED]** | §7.2 |
| **DEC-7** | Ensembles outside the initial critical path | **[APPROVED] deferral** | Phase 3 only, behind a gate |
| **DEC-9** | Fine-tuning outside the initial critical path | **[APPROVED] deferral** | Phase 3 only, go/no-go 2026-11-12 |
| **DEC-12** | Keep the 2026-11-16 deadline; safety submission first | **[APPROVED]** | §11 |
| — | Working end-to-end baseline is the top priority | **[APPROVED]** | Phase 1 definition in §10 |
| — | Exact answer formatting and evaluation compliance | **[APPROVED]** | §7.5, §7.6, §9 |

Open decisions (DEC-4, DEC-8, DEC-10, DEC-11, DEC-13, DEC-14) are listed in §13.

---

## 4. Environments

The team develops on Google Colab, builds images elsewhere, and is scored on 2 × RTX 5090 in Docker. The architecture must be correct under all three.

### 4.1 Environment matrix
| Environment | Hardware | Docker | Network | Purpose |
|---|---|---|---|---|
| **E1 Colab G4** | 1 × RTX PRO 6000 Blackwell, 96 GB, **sm_120** [OBS] | No [OBS] | Yes | Primary: kernel compatibility, runtime benchmarks, determinism tests, bake-off |
| **E2 Colab A100 / H100** | 1 × 40/80 GB, sm_80 / sm_90 | No | Yes | Accuracy experiments when G4 is unavailable |
| **E3 Colab CPU / laptops** | CPU | Varies | Yes | Ingestion, temporal resolver, scorer, formatter, unit tests |
| **E4 Build host** | Any x86_64 Linux, ≥ 200 GB free disk; no GPU needed | Yes | Yes | `docker build`, `docker save`, checksum, upload |
| **E5 Rehearsal / private-run host** | **sm_120 GPU(s)**, ideally 2 × RTX 5090 | **Yes**, with NVIDIA Container Toolkit | Disabled at run time | Exact scoring-command rehearsal; running the frozen image on the private test |
| **E6 Organizer** | 2 × RTX 5090, 512 GB RAM | Yes | None | Official re-run |

- **[OBS]** Colab lists a G4 runtime backed by the RTX PRO 6000 (Blackwell). The RTX PRO 6000 and RTX 5090 both report compute capability 12.0, so kernel availability on G4 is a strong proxy for the target. G4 memory bandwidth (~1.6 TB/s) is somewhat below the RTX 5090's (~1.8 TB/s), so decode throughput measured on G4 should be slightly conservative. **[HYP]** to be confirmed by one benchmark on E5.
- **[OBS]** Colab does not support running Docker containers directly. Rootless workarounds (udocker, Apptainer with `--nv`) exist but are unofficial.
- **E5 is not yet identified.** See RISK-1 and DEC-14.

### 4.2 Design rules imposed by Colab
| Colab property | Architectural rule |
|---|---|
| One GPU per runtime | Serving must work as **independent single-GPU replicas**. No tensor parallelism in the baseline (DEC-13). Two-GPU behavior is tested only on E5. |
| 96 GB on G4 vs 32 GB on target | All benchmarks run with vLLM `gpu_memory_utilization` set so the engine's budget equals the target's (≈ 0.30 on 96 GB ≈ 0.90 × 32 GB), plus a fixed `max_model_len` and `max_num_seqs`. Any configuration that only works with more memory is rejected. |
| No Docker | Colab runs the **same Python package and the same pinned dependency lock** as the image, installed in an isolated virtual environment. The lock is generated from the chosen base image (`pip freeze` inside the container) so library versions match. |
| Network available | Every harness run sets `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, and loads models from a local path, so accidental network dependence fails in Colab rather than on the organizer's machine. |
| Ephemeral sessions, quota limits | The harness is **resumable**: results are appended per question (same atomic writer as production) and runs restart from the last completed question. Weights and the training split are cached on Google Drive and copied to local disk at session start. |
| Different GPU SKUs across sessions | Every run record stores GPU name, driver, CUDA, vLLM, and model revision. Accuracy comparisons across SKUs are valid for development decisions; **runtime and determinism numbers are only valid from G4 or E5**. |

---

## 5. Architecture overview

### 5.1 Processing levels
```
Build time (offline, baked into image)
  model weights · prompt templates · few-shot bank (training split only)
  Vietnamese abbreviation lexicon · frozen run configuration

Split startup (once per run)
  rulebook.md (verbatim) ─► RuleProfile (Phase 2)      calendar.csv ─► LunarCalendar
  start model replicas (GPU0, GPU1)

Business startup (once per business, cached under /tmp)
  discover files ─► ingest ─► DuckDB ─► profile ─► SchemaCard
                                         └─► SemanticAnnotations + validated views (Phase 2)
                                         └─► EntityIndex (Phase 2)

Per question
  normalize ─► parse (QuestionFrame) ─► resolve time ─► link entities
  ─► solve (SQL; Python fallback) ─► execute (sandbox) ─► verify ─► decide
  ─► format ─► persist submission line + log record
```

### 5.2 Component map
```
                         ┌──────────────────────────────────────────────┐
 /data (ro) ──────────►  │ C1 Split Bootstrap   C2 Ingestion & Catalog   │
                         │ C3 Semantic Compiler (P2)  C6 Entity Linker   │
                         └──────────────┬───────────────────────────────┘
                                        │ SplitContext, BusinessCatalog
 questions.jsonl ─► C12 Orchestrator ───┤
                   (scheduler, budget)  ▼
                         ┌──────────────────────────────────────────────┐
                         │ C4 Question Parser ─► C5 Temporal Resolver    │
                         │ C7 Solver ◄──► C8 Sandbox Executor            │
                         │ C9 Verifier & Decision ─► C10 Formatter       │
                         └──────────────┬───────────────────────────────┘
                                        ▼
                         C11 Persistence & Compliance Logging ─► /result
 C13 Model Serving (replica GPU0, replica GPU1) ◄── used by C3, C4, C7
 C14 Evaluation Harness & Local Scorer (development only, not on the inference path)
```

### 5.3 Design principles
1. **Deterministic wherever the rule is generic.** Dates, ranking, tie-breaks, typing, rounding, and serialization are code, not model output.
2. **Model reasoning only where the schema is specific.** Table roles, column meaning, and query logic are inferred by the LLM from profiled evidence.
3. **The rulebook is data.** It is always passed verbatim; no training-rulebook parameter appears in code.
4. **Fail toward abstain.** Any unhandled condition produces `abstain`, never a crash and never a guess.
5. **Logs are captured, never reconstructed.** Every logged string comes from the exact object returned by the model or executor.
6. **Same code path everywhere.** Colab, E5, and the organizer run the same entry point with the same frozen configuration.

---

## 6. Components

Phase legend: **P1** baseline (required for the first end-to-end run), **P2** accuracy, **P3** optional and gated.

| ID | Component | Responsibility | Phase | Owner |
|---|---|---|---|---|
| C1 | Split Bootstrap | Load rulebook verbatim; load calendar; (P2) extract and validate RuleProfile | P1 / P2 | M2 |
| C2 | Ingestion & Catalog | Read CSV/XLSX/SQLite; parse Vietnamese numbers and dates; materialize DuckDB; profile; produce SchemaCard | P1 | M1 |
| C3 | Semantic Compiler | Per-business annotations and validated views for core rulebook definitions | P2 (DEC-4) | M1 |
| C4 | Question Parser | LLM → QuestionFrame (answer type, metric, mentions, time expressions, ranking spec) | P1 | M3 |
| C5 | Temporal Resolver | Deterministic date windows from `as_of_date`, rulebook, calendar | P1 core / P2 lunar | M2 |
| C6 | Entity Linker | Accent-folded, fuzzy candidate retrieval against real values and codes | P2 | M1 |
| C7 | Solver | Build context pack; LLM writes DuckDB SQL; bounded repair; (P2) Python fallback | P1 / P2 | M3 |
| C8 | Sandbox Executor | Run SQL/Python in a subprocess with read-only access and resource limits | P1 | M3 |
| C9 | Verifier & Decision | Type contract and plausibility checks; answer / `unanswerable` / abstain | P1 rules / P3 learned | M2 |
| C10 | Formatter | Canonical serialization per type | P1 | M2 |
| C11 | Persistence & Logging | Atomic submission and log writing; compliance fields | P1 | M4 |
| C12 | Orchestrator | Question grouping, concurrency, deadlines, degrade mode, global stop | P1 | M4 |
| C13 | Model Serving | vLLM replicas, client, deterministic decoding settings | P1 | M4 (replicas), M3 (client) |
| C14 | Evaluation Harness | Local scorer, grouped CV, error analysis, run records | P1 | Lead |

### 6.1 C1 Split Bootstrap
- **P1.** Read `rulebook.md` as a UTF-8 string, NFC-normalized, never edited. Load `calendar.csv` into an in-memory solar↔lunar lookup with validation (monotonic dates, no gaps over the data range).
- **P2.** Extract a **RuleProfile** with the LLM (week start, inclusivity of "this month", holiday window definitions, default ranking criterion, revenue and cost definitions as quoted text), then validate: every field must cite a rulebook span, and enumerated fields must take allowed values. A field that fails validation is marked `unresolved`, and consumers fall back to the verbatim rulebook.
- **Failure behavior.** Missing or unreadable calendar: lunar-dependent questions abstain; other questions proceed.

### 6.2 C2 Ingestion & Catalog
- File discovery, encoding and dialect detection for CSV, all sheets for XLSX (header-row detection, total-row detection, multi-table detection), SQLite attached read-only.
- Locale-aware parsing (`1.250.000`, `1,5`, `150k`, `1tr2`), date-format inference from value ranges, Excel serial dates. **Raw columns are kept alongside parsed columns**; nothing is coerced silently.
- Output: a per-business DuckDB file under `/tmp/datamate/<run>/<business>/` and a **SchemaCard** (tables, columns, types, null rates, ranges, low-cardinality distinct values, sample rows, candidate keys, inferred joins, ingestion warnings).
- Budget: **[PROP]** ≤ 60 s per business at 300k rows on the target CPU; XLSX via a fast reader (calamine-class). Business ingestion overlaps with question processing of other businesses.

### 6.3 C13 Model Serving
- **[PROP] Topology (DEC-13).** Two vLLM OpenAI-compatible servers on `127.0.0.1`, one per GPU (`CUDA_VISIBLE_DEVICES=0` and `=1`), started by `predict.sh`, each holding a full copy of the model. No tensor parallelism and no NCCL in the baseline.
  - Rationale: testable on a single Colab GPU; avoids the NCCL initialization hang, P2P absence, and `/dev/shm` failures documented in DG §9–10; doubles throughput for a model that fits in 32 GB.
  - **[HYP]** The loopback interface is available under `--network none`. Verified in the first E5 rehearsal; the fallback is in-process engines (`AsyncLLM`) with the same client interface.
- **Contingency.** If the selected model does not fit one 32 GB GPU with adequate KV cache, use tensor parallelism across both GPUs with the DG §9 workarounds (`nvidia-nccl-cu12==2.27.7`, `NCCL_P2P_DISABLE=1`), and accept that this path can only be validated on E5.
- **Client.** A single `ModelClient` used by C1, C3, C4, and C7. It sets every decoding parameter explicitly, never relies on server or chat-template defaults (including the thinking switch), and returns the raw content, reasoning content, token counts, and finish reason for logging.
- **Startup.** Both replicas load in parallel; the reference figure is ~2 minutes for Qwen3-14B including CUDA-graph capture (DG §7). Readiness is checked by a deterministic warm-up prompt.

### 6.4 C4 Question Parser
- Input: original question, `as_of_date`, rulebook, SchemaCard summary.
- Output: a **QuestionFrame** in constrained JSON (vLLM guided decoding against a JSON schema): expected answer type, metric description, entity mentions, raw time expressions, grouping, ranking k and direction, comparison spec, and an `answerability_hint` naming any field the question requires.
- Light lexical normalization (abbreviation expansion from the lexicon) is applied to a **copy**; the original question is always kept and passed to the model.

### 6.5 C5 Temporal Resolver
See §7.1.

### 6.6 C6 Entity Linker (P2)
- Index of distinct values and codes per text column, keyed by accent-folded, lowercased tokens (retrieval only, DEC-11), with character n-gram fuzzy scoring.
- Output: ranked candidates `(table, column, value, code, score)` passed to the solver. **Values are emitted exactly as stored**, diacritics included.
- **P1 substitute.** SchemaCard distinct-value lists are included in the context pack, and the model matches them itself.

### 6.7 C7 Solver and C8 Sandbox Executor
See §7.3.

### 6.8 C9 Verifier & Decision
See §7.4.

### 6.9 C10 Formatter
See §7.5.

### 6.10 C11 Persistence & Logging
See §7.6.

### 6.11 C12 Orchestrator
- Reads all questions, groups them by business, and orders businesses deterministically (sorted by business identifier as an ordering key only; IDs never influence answer logic, DG §5.4).
- Assigns businesses to replicas by a fixed rule (greedy balance on question count, ties by order). Assignment depends only on the input files, so it is identical across runs.
- Fixed concurrency per replica, set in the frozen configuration and never adapted at run time.
- Deadlines: per-question soft and hard limits; a projected-finish monitor activates **degrade mode** (no repair, no fallback) if the run falls behind its target; at the global hard stop (default 5 h 30 min after start) all remaining questions are written as `abstain`.
- Crash isolation: any exception inside a question's pipeline yields `abstain` for that question with the error logged; a business-level failure yields `abstain` for that business's questions.

### 6.12 C14 Evaluation Harness
- Local scorer implementing Brief §2.1–2.2 exactly, unit-tested on every Brief example. It is the single source of truth for development metrics.
- Business-grouped 5-fold cross-validation; leave-business-type-out evaluation; (P2) rulebook-perturbation suite.
- Run records: configuration hash, code commit, model revision, environment fingerprint, per-question outcomes, runtime.
- Public leaderboard used for end-to-end sanity checks only (≤ 5 per day); no tuning against it and no answer probing (Brief §5.2.6).

---

## 7. Key design details

### 7.1 Temporal resolution (DEC-5, approved)
- The **LLM extracts** time expressions verbatim into the QuestionFrame. **Code resolves** them into inclusive `[start, end]` date ranges with a granularity (`day`, `week`, `month`, `quarter`, `year`, `lunar-window`).
- Parameters (week start, inclusivity of the current period, "last week" vs "last 7 days", same-period-last-year, holiday windows) come from the rulebook: in P1 from a small set of **parameters filled by the parser from the verbatim rulebook text**, in P2 from the validated RuleProfile. No default from the training rulebook is compiled into code.
- **P1 coverage:** explicit dates and months, relative days/weeks/months/quarters/years, to-date periods, same period last year, comparisons between two windows.
- **P2 coverage:** lunar and holiday windows via `calendar.csv` (Tết across two solar years, mid-autumn, leap lunar months).
- **Unresolvable expression:** P1 → `abstain`. P2 → the model proposes a window with justification from the rulebook; the resolver validates it against the calendar and data coverage; the result is flagged and lowers confidence.
- **Coverage check:** if a window lies wholly or partly outside the business's data range, the overlap ratio becomes a verifier feature. The reference behavior for out-of-range windows (`0` vs `unanswerable`) is learned from training references (Q7).

### 7.2 Rulebook handling (DEC-6, approved)
- The verbatim rulebook is in every model context pack as part of the shared prefix (prefix-cache friendly).
- Deterministic components never hold rule constants; they receive parameters from C1.
- The rulebook-perturbation suite (P2) changes rule parameters on synthetic questions with programmatic answers and verifies that outputs follow the mounted rulebook.

### 7.3 Solving and execution (DEC-2, approved)
- **Context pack** (ordered for prefix reuse): system instructions → rulebook → SchemaCard (or relevant subset) → (P2) annotations and validated views → few-shot examples from training businesses → question, QuestionFrame, resolved windows, entity candidates, type contract.
- **SQL path (P1).** The model writes one DuckDB query. Prompt rules require explicit `ORDER BY` with a code-ascending tie-break for every ranked or listed result and forbid DDL/DML.
- **Repair loop (P1).** At most 2 repairs, triggered by execution error, empty result where the type contract forbids it, or a type-contract violation. Each repair call is logged as a separate entry in `thinking` and `code`.
- **Python fallback (P2).** Triggered when the parser marks the question as needing procedural logic, or after SQL repairs fail. Restricted to pandas/DuckDB over the business database, at most 1 attempt plus 1 repair.
- **Sandbox (C8, P1).** Separate subprocess; DuckDB opened **read-only**; working directory under `/tmp`; wall-time limit (default 20 s), memory limit, result-row limit; no network (already absent) and no writes outside the scratch directory. Python fallback runs with an import allow-list. A timeout or limit breach is an execution error.
- **Packaged helpers.** Generated code may call helpers shipped in `/code/src` (DG §3.3). The log records the actual call and its inputs.

### 7.4 Verification and decision (DEC-8 open)
- **P1 rule gate.** Answer only if all hold: execution succeeded; the result conforms to the type contract; the result is non-empty and non-null; the time window overlaps the data range; no verifier red flag. Otherwise `abstain`.
- **`unanswerable` in P1** is emitted only when the parser's `answerability_hint` names a required field **and** a deterministic catalog check confirms the field is absent. Every other doubt becomes `abstain`.
- **Verifier features (P2):** repair count, row count, magnitude plausibility against column ranges, entity-match score, window coverage ratio, temporal flags, fallback usage.
- **Learned calibrator (P3, gated).** A small classical model (logistic regression or monotonic GBT) over verifier features, trained on training-split runs with business-grouped CV; adopted only if it raises held-out PA over the rule gate. Declared in the README and counted toward the parameter total (negligible).
- **Multi-strategy agreement (P3, DEC-7 deferred).** Greedy runs of alternative strategies; early exit after two agree. Adopted only if it raises held-out PA by a measurable margin and keeps the runtime and determinism gates.

### 7.5 Formatting
- One formatter per type, fed by typed values from the executor, never by model-written strings.
- `number` and `percent`: half-up rounding implemented with `Decimal` (no binary-float rounding), integer emission rule per Q5.
- `date`: granularity from the QuestionFrame and the resolved window.
- `list`: sort by criterion, ties by code ascending, truncate to k.
- `table`: column names follow conventions learned from training references.
- `string`: copied from the data value; no casing or diacritic changes.
- JSON output with `ensure_ascii=False`, UTF-8, one object per line.

### 7.6 Persistence and compliance logging
- **Submission writer.** Append one line per question as soon as its decision is final, then `flush` and `fsync`. A question is written exactly once. At startup the writer creates `/result` and `/result/logs` if missing.
- **Log record** (one JSON line per question in `/result/logs/questions.jsonl`):

| Field | Source | Rule |
|---|---|---|
| `id` | input | — |
| `answer` | decision | Same object as the submission line |
| `elapsed_ms` | orchestrator | Non-negative integer; from when the question enters its worker (its batch) to final answer |
| `thinking` | ModelClient | Exact reasoning text per call, in call order; list if several calls; `null` if none |
| `code` | executor | Exact executed SQL/Python per attempt, in order |
| `output` | executor | Return value or execution output of the final attempt |
| `inputs` | executor | For packaged helpers: actual arguments |
| `calls` (supporting) | ModelClient | Per call: stage, prompt hash, finish reason, token counts |
| `views_used` (supporting, P2) | solver | Names and hashes of compiled views referenced |
| `decision_reason` (supporting) | verifier | Gate outcome and failing check |

- **Business-level log** (`/result/logs/businesses.jsonl`): ingestion warnings, SchemaCard hash, compiled-view DDL and the model calls (with their thinking) that produced them, and setup duration. Per-question records reference it, so any SQL that uses a compiled view can be traced to the actual computation.
- **Capture rule.** Logged strings are taken from the objects returned by the model server and the executor. Nothing is paraphrased, shortened, or regenerated.

### 7.7 Determinism
- Greedy decoding (`temperature = 0`), fixed `seed`, `max_tokens`, stop sequences, and an explicit thinking switch on every call.
- Fixed concurrency; fixed business-to-replica assignment; deterministic ordering in SQL; fixed `PYTHONHASHSEED`, BLAS threads, and DuckDB threads; pinned versions everywhere.
- `VLLM_BATCH_INVARIANT=1` **only if** it validates on sm_120 with the selected model. **[HYP]** v1 noted that vLLM documents support for compute capability ≥ 8.0 but hybrid linear-attention models are not on its tested list; this must be checked on G4 (RISK-4).
- **Structural mitigation.** Model output only affects the answer through SQL text and parsed fields. Small numeric drift that does not change the generated SQL does not change the answer, so short, structured generations are less drift-prone than long free-form reasoning.
- **Acceptance gates** in §9.

### 7.8 Runtime budget
- **Budget.** 6 h = 21,600 s. **[PROP] Target ≤ 2.5 h** (9,000 s) on the reference hardware, provisioned for up to **1,000 questions** in case the count exceeds the "~500" estimate.
- **Throughput requirement.** 1,000 questions over 2 replicas in ~8,700 s of processing ≈ 17 s of throughput per question per replica.
- **Token estimate [HYP].** P1 averages two calls per question (parse, solve) plus occasional repairs, about 4k output tokens per question with bounded thinking → ~4M output tokens ≈ 460 tok/s aggregate. v1 cited a community figure of ~1,280 output tok/s at concurrency 64 for Qwen3.5-9B on one RTX 5090; if that holds, the margin is about 5×. Prefill cost depends on context-pack size and prefix-cache hit rate. **Both are measured at M1 on G4 with the target memory cap.**
- **Projection formula** (DG §10): model loading + business setup (non-overlapped part) + (mean throughput time per question × question count). Must be ≤ 2.5 h at 1,000 questions to pass the runtime gate.

### 7.9 Docker image
- **Base image (DEC-3).** The reference `vllm/vllm-openai:v0.10.1.1` is lowest-risk but cannot serve Qwen3.5 models (the vLLM recipe requires ≥ 0.17.0). Older official vLLM images were reported to lack sm_120 kernels, so **any newer tag must be validated on sm_120 before adoption**, not assumed.
- **Layout** follows DG §4: `/code/predict.sh`, `/code/README.md`, `/code/requirements.txt`, `/code/src/`, `/code/models/`, `/code/training_code/` (with `data_manifest.json` and an explicit statement if no training or data generation was performed).
- **Dockerfile** follows the DG §9 reference: `ENTRYPOINT []`, offline environment variables, separate `COPY` layers with weights before code, `CMD ["bash", "/code/predict.sh"]`.
- **Size budget [derived].** The DG sample image was 50.5 GB with a 28 GB model directory, so the base and dependencies are ~22 GB. A ~20 GB BF16 model gives ~45 GB, well under 100 GB. Only the selected model's weights are shipped, because every loadable model counts toward the 15B limit.
- **Build and export (DG §9, §11).** `docker build --platform linux/amd64 -t zaic2026_datamate_<team_name>:final .`; export with `set -o pipefail` before `docker save | pigz`, measure the uncompressed size from the archive, and write the `.md5` before upload; never rename the archive afterwards. `.dockerignore` must not exclude training data.
- **Upload.** The DG sample compressed from 50.6 GB to 34.4 GB. Upload, download from a second machine, and `md5sum -c` must be complete by 18:00 on 11-16 (§11).

---

## 8. Model strategy (DEC-3, process approved)

### 8.1 Candidates
All facts below must be re-verified from model cards and safetensors metadata (parameter count from the actual checkpoint, release date, license, revision hash) before selection.

| Model | Params incl. all towers (verify) | BF16 weights (approx.) | Fits one 32 GB GPU with KV? | vLLM requirement | Role |
|---|---|---|---|---|---|
| **Qwen3.5-9B** | ~9–10B incl. vision encoder [OBS, conflicting sources] | ~19–20 GB | Yes; hybrid attention suggests a small KV footprint [HYP] | ≥ 0.17.0 → **not** the reference image | Leading candidate |
| **Qwen3-8B** | ~8.2B | ~16.4 GB | Yes | Reference image supports it | Low-risk fallback; v1 noted it is on vLLM's batch-invariance validated list |
| **Qwen3-14B** | ~14.8B | ~29.5 GB | **No** in BF16; yes in FP8 (~15 GB) [HYP] | Reference image supports it | Higher-capacity option; requires FP8 quantization or TP=2 |
| Qwen3.5-4B | ~4–5B incl. vision | ~9 GB | Yes | ≥ 0.17.0 | Speed reference; not a second model in the baseline |
| Gemma 4 (small) | Verify | Verify | Verify | Verify | Include only if release date, license, size, and vLLM support verify |

- **[OBS]** No Qwen3.6 dense model below 15B was found; Qwen3.6 releases are 27B and above, outside the budget.
- **[OBS]** Sources conflict on whether Qwen3.5 small models enable thinking by default. The ModelClient sets it explicitly on every call, so the default does not matter.
- **One model only in the baseline.** Adding a second model (for example 9B + 4B) could approach the 15B limit once vision towers are counted, and doubles memory pressure per GPU.

### 8.2 Bake-off protocol (Colab G4, by 2026-11-09)
1. **Compatibility:** the candidate's vLLM version starts on G4 with the target memory cap, serves greedy outputs, and runs CUDA graphs without errors.
2. **Determinism:** the same 200 training questions run twice with production concurrency must produce identical submission lines.
3. **Accuracy:** P1 pipeline PA on held-out businesses (grouped CV), the same prompts for all models.
4. **Throughput:** questions per hour per replica at target concurrency, including prefill.
5. **Decision rule:** pick the highest held-out PA among candidates that pass 1, 2, and 4 (projected ≤ 2.5 h at 1,000 questions). If Qwen3.5-9B fails 1 or 2 by 11-09, select Qwen3-8B or Qwen3-14B-FP8 on the reference image.

### 8.3 Other models
- **No embedding model** in P1/P2. **[HYP]** Lexical and fuzzy entity linking is sufficient; revisit only if error analysis shows linking is a top error source.
- **Fine-tuning (DEC-9, deferred).** Optional LoRA experiment only after Phase 1 is stable, with a go/no-go on **2026-11-12**: adopt only if it raises held-out-business PA by ≥ 3 points without hurting runtime or determinism. Adoption makes the full training evidence package of DG §8 mandatory (code, configs, data, logs, manifest, checksums); this cost counts against the decision.

---

## 9. Validation strategy and acceptance criteria

### 9.1 Component-level validation
| Component | Validation | Pass criterion |
|---|---|---|
| C2 Ingestion | Fixture files covering title rows, merged headers, totals rows, VN number formats, ambiguous dates, serial dates; all training businesses | All fixtures parse to expected values; zero silent coercions (every failed parse counted in warnings); ≤ 60 s per business at 300k rows |
| C5 Temporal | Table-driven unit tests per expression class and rulebook parameter set; lunar tests against `calendar.csv` | 100% of unit tests; zero off-by-one errors on the training questions' resolved windows (spot-checked against references) |
| C8 Sandbox | Adversarial snippets (infinite loop, large allocation, write attempt, DDL) | Each is terminated or rejected within its limit; the process pool survives |
| C10 Formatter | Golden tests per type, including rounding edge cases (x.xx5), negative percents, empty lists, ties | 100% |
| C11 Logging | Schema validation of every log line; byte-equality check between returned model text and logged text | 100% of questions have a valid record; zero mismatches |
| C14 Scorer | Every example in Brief §2 | 100% agreement |

### 9.2 System-level gates
| Gate | When | Environment | Criterion |
|---|---|---|---|
| **G0 Scorer** | M0, 11-07 | E3 | Scorer passes all Brief examples |
| **G1 Compatibility** | M1, 11-09 | E1 (G4) | Selected model and vLLM version serve on sm_120 within the 32 GB cap |
| **G2 Baseline** | M1, 11-09 | E1 | All training questions processed with zero crashes; 100% valid submission lines and log records; PA reported per type and category |
| **G3 Runtime** | M1 then every milestone | E1, then E5 | Projected ≤ 2.5 h for 1,000 questions (§7.8) |
| **G4 Determinism** | M2, 11-11 | E1 | Two full training runs: identical submission files, or at worst \|ΔPA\| ≤ 0.005 |
| **G5 Gate value** | M2, 11-11 | E1 | Rule gate PA ≥ answer-everything PA on held-out businesses |
| **G6 Container rehearsal** | M3, 11-13 | **E5** | Exact DG §10 scoring command, `--network none`, `/data:ro`, both GPUs, full training split: completes, output and logs valid, runtime within G3, and the result matches the E1 run within \|ΔPA\| ≤ 0.01 |
| **G7 Re-run** | M3–M4 | **E5** | Two container runs on the same input: identical submission files, or \|ΔPA\| ≤ 0.005 |
| **G8 Packaging** | M4, 11-15 | E4 | Image `linux/amd64`; uncompressed tar ≤ 100 GB; README model declarations complete; `training_code/` complete; md5 verified from a second machine |

Quality gates use held-out PA, not public-leaderboard scores. No absolute PA target is set until the M1 baseline exists.

### 9.3 Traceability (requirement → component → validation)
| Requirement | Components | Validated by |
|---|---|---|
| Exact-match typing and formatting | C4, C9, C10 | C10 golden tests, G2 per-type PA |
| Split-specific rules | C1, C3, C5 | Perturbation suite (P2), C5 tests |
| Unseen business types | C2, C3, C7 | Leave-type-out CV |
| Offline, read-only, no-argument entry point | C11, C12, C13, image | G6 |
| Per-question logs with actual thinking/code/output | C7, C8, C11, C13 | C11 byte-equality, G6 |
| 6-hour limit including load | C12, C13 | G3, G6 |
| \|ΔPA\| ≤ 0.03 | C12, C13, §7.7 | G4, G7 |
| ≤ 15B parameters; licensing; release date | §8 | G8 declaration review |

---

## 10. Phased delivery and priorities

| Phase | Content | Exit | Rule |
|---|---|---|---|
| **P1 Baseline** | C1 (verbatim), C2, C4, C5 (solar core), C7 (SQL + repair), C8, C9 (rule gate), C10, C11, C12, C13, C14 | G0–G3 by **11-09** | Nothing from P2/P3 is started by a workstream until its P1 deliverables pass their tests |
| **P2 Accuracy** | RuleProfile, lunar windows, C6, C3 compiled views (DEC-4), Python fallback, verifier features, prompt and few-shot work from error analysis | G4–G5 by **11-11** | Each feature is merged only if held-out PA does not drop, and behind a configuration switch |
| **P3 Optional** | Learned calibrator, multi-strategy agreement, LoRA | Go/no-go **11-12** | Adopted only with measured gain and passing G3/G4 |
| **Freeze** | Bug fixes only | **11-13** after G6 | Any change after the freeze requires re-running G6/G7 |

Priority order when time is short: **compliance and validity → determinism → runtime → accuracy**. A valid, reproducible submission with modest PA is worth more than a stronger system that fails G6.

---

## 11. Milestones

| Milestone | Date | Exit criteria |
|---|---|---|
| **M0 Foundations** | Sat 11-07 | Repository skeleton; contracts v0 frozen; G0; data-inspection report on the training split; Colab environment with pinned lock; **E5 host identified (DEC-14)** |
| **M1 Baseline** | Mon 11-09 | G1–G3; **model and base-image decision (DEC-3)** |
| **M2 Accuracy** | Wed 11-11 | P2 features merged or dropped; G4, G5 |
| **M3 Rehearsal + freeze** | Fri 11-13 | G6; feature freeze |
| **Safety submission** | Sat 11-14 | Solution #1 uploaded and checksum-verified |
| **M4 Final candidate** | Sun 11-15 | G7, G8; README and declarations final |
| **M5 Final** | Mon 11-16, target 18:00 | Final image uploaded, md5 verified from a second machine, form submitted well before 23:59 |

The team is one lead and four members (`IMPLEMENTATION_PLAN.md` §2):

| Role | Owns | Components |
|---|---|---|
| **Lead** | Contracts, scorer and harness, CI, integration, decisions, submissions | C14 |
| **M1** Data & Semantics | `ingest/`, `catalog/`, `entities/`, `lexicon/`, `semantics/` | C2, C3, C6 |
| **M2** Rules, Time & Answers | `rules/`, `temporal/`, `decision/`, `formatting/` | C1, C5, C9, C10 |
| **M3** Reasoning Engine | `llm/client.py`, `prompts/`, `parse/`, `solver/`, `sandbox/` | C4, C7, C8, C13 client |
| **M4** Platform & Compliance | `run.py`, `config.py`, `runtime/`, `llm/replicas.py`, Docker, compliance docs | C11, C12, C13 replicas |

The interface contracts in §14 live in one shared module owned by the lead; changes require lead approval. The seams between members, their stand-ins, and their compatibility tests are described in `ARCHITECTURE.md` §10.

---

## 12. Risk register

Likelihood (L) and impact (I): H / M / L.

| ID | Risk | L | I | Mitigation | Trigger / contingency | Owner |
|---|---|---|---|---|---|---|
| **RISK-1** | **No Docker-capable sm_120 host** for the G6 rehearsal and for running the frozen image on the private test; Colab cannot run Docker | **H** | **H** | Decide E5 by 11-07 (DEC-14): a team member's RTX 5090 workstation, a cloud VM with RTX PRO 6000 or RTX 5090 and full Docker support, or a bare-metal rental | If no E5 by 11-09: try Apptainer `--nv` on Colab G4 with the exported image **[HYP]**, accepting reduced fidelity | M4 |
| **RISK-2** | **Cross-SKU drift.** Our uploaded run (on E5) and the organizers' re-run (2 × 5090) may differ if E5 is not an RTX 5090 | M | H | Prefer RTX 5090 for E5; short structured generations; batch-invariant mode if valid | Measure the G4 vs. E5 difference on the training split; if \|ΔPA\| > 0.01, reduce generation length and concurrency | M4 |
| **RISK-3** | Newer vLLM image needed for Qwen3.5 fails on sm_120 or in the container | M | H | Validate on G4 at M1; keep a reference-image fallback model ready | Fall back to Qwen3-8B or Qwen3-14B-FP8 on `v0.10.1.1` | M4 |
| **RISK-4** | Batch-invariant mode unsupported for the selected (hybrid) model, causing run-to-run drift | M | H | Test on G4; structural mitigation §7.7 | Lower concurrency; switch to a model on the validated list | M4 |
| **RISK-5** | Colab G4 availability or quota limits block benchmarks | M | M | Book sessions early; resumable harness; run accuracy work on A100/H100 | Runtime numbers from E5 only | Lead |
| **RISK-6** | Private rulebook differs in ways the RuleProfile or prompts mis-handle | M | H | Verbatim rulebook in every context; perturbation suite | Per-parameter fallback to verbatim text; affected questions abstain | M2 |
| **RISK-7** | Unseen business types break ingestion or semantic assumptions | M | H | Schema-driven design; leave-type-out CV; ingestion warnings | Business-level failure → abstain for that business, never a crash | M1 |
| **RISK-8** | Compiled views encode a wrong rule interpretation (correlated errors) | M | M | Invariant checks; per-category kill switch | Disable views per category | M1 |
| **RISK-9** | Scorer ambiguities (int vs float, percent direction, boolean encoding) | M | M | Questions Q5 to organizers; learn from training references | Follow training reference conventions | Lead |
| **RISK-10** | Runtime overrun on the private test (more questions, larger businesses) | L | H | 2.5 h target at 1,000 questions; degrade mode; global hard stop | Abstain on remaining questions; answers already written still count | M4 |
| **RISK-11** | Log fidelity questioned (thinking not identical to generation, missing records) | L | H | Capture at client boundary; byte-equality tests | — | M4 |
| **RISK-12** | Parameter-count interpretation (vision tower; calibrator) | L | H | Count every tensor in shipped checkpoints; declare in README; do not ship unused weights | Choose a text-only model if counting is disputed | M4 |
| **RISK-13** | Colab/image environment mismatch (library versions differ) | M | M | Lock generated from the base image; environment fingerprint in run records | G6 is the authority | M4 |
| **RISK-14** | Image upload time or link failure near the deadline | M | H | Safety submission on 11-14; final upload by 18:00 on 11-16; second-machine md5 check | Resubmit the safety image | M4 |
| **RISK-15** | Interface churn or integration breakage between five engineers working in parallel for ten days | M | M | Contracts frozen at I0 with lead approval for changes; fakes and test doubles for every seam; conformance and consumer tests; public-API rule; daily merge window; determinism CI (`ARCHITECTURE.md` §10) | Late handoff → consumers continue on the stand-in; lead pairs with the producer | Lead |

---

## 13. Decisions register

| ID | Decision | Status | Recommendation | Needed by |
|---|---|---|---|---|
| DEC-1 | Hybrid architecture | **APPROVED** | — | — |
| DEC-2 | SQL primary, bounded Python fallback | **APPROVED** | — | — |
| DEC-3 | Model and base image | **APPROVED process; outcome OPEN** | Bake-off §8.2; prefer Qwen3.5-9B if it passes G1, G3, G4 | 11-09 |
| **DEC-4** | Per-business compiled views | **OPEN** | Adopt in P2 behind a per-category switch, only if held-out PA improves | 11-11 |
| DEC-5 | Deterministic temporal resolution | **APPROVED** | — | — |
| DEC-6 | Split-specific rules, nothing hard-coded | **APPROVED** | — | — |
| DEC-7 | Ensembles | **APPROVED as deferred** | P3 only | 11-12 |
| **DEC-8** | Abstention policy | **OPEN** | P1 rule gate (§7.4); learned thresholds only in P3 | 11-09 |
| DEC-9 | Fine-tuning | **APPROVED as deferred** | Go/no-go 11-12, ≥ +3 PA | 11-12 |
| **DEC-10** | Thinking mode | **OPEN** | Off for parsing; bounded budget for solving only if it raises PA within the runtime gate | 11-09 |
| **DEC-11** | Accent folding for entity retrieval keys only | **OPEN** | Approve; scoring normalization and output strings keep diacritics. Needs confirmation against the `CLAUDE.md` diacritics rule | 11-07 |
| DEC-12 | Deadline and safety submission | **APPROVED** | — | — |
| **DEC-13** | Serving topology | **OPEN (new)** | Two independent single-GPU replicas; TP=2 only as contingency | 11-07 |
| **DEC-14** | Rehearsal and private-run host (E5) | **OPEN (new), critical** | Secure a Docker-capable sm_120 host, preferably 2 × RTX 5090 | **11-07** |

---

## 14. Interface contracts

Field-level schemas are defined in `SPEC.md`. This section fixes ownership and the fields each consumer relies on.

| Contract | Producer → Consumer | Required fields | Invariants |
|---|---|---|---|
| `RunConfig` | image → all | model path, revision, decoding params, seed, concurrency, limits, feature switches | Frozen in the image; `predict.sh` takes no arguments |
| `SplitContext` | C1 → all | rulebook text, rulebook hash, RuleProfile (P2, may be partial), LunarCalendar | Rulebook text is never modified |
| `BusinessCatalog` | C2 → C3–C9 | DuckDB path, tables, column metadata (raw and parsed), SchemaCard text, data date range, warnings | Read-only after creation |
| `SemanticAnnotations` | C3 → C7 | table roles, value semantics, join paths, views with DDL and validation results | Only validated views are exposed |
| `QuestionFrame` | C4 → C5–C10 | answer-type contract, metric, mentions, raw time expressions, ranking spec, answerability hint | Schema-constrained JSON |
| `TimeWindow` | C5 → C7, C9 | inclusive start/end, granularity, provenance (rule source), coverage ratio, flags | start ≤ end; dates ISO |
| `EntityCandidates` | C6 → C7 | mention → ranked (table, column, value, code, score) | Values exactly as stored |
| `SolverAttempt` | C7/C8 → C9, C11 | strategy, prompt hash, raw output, thinking, code, execution output, error, duration | One per attempt, ordered |
| `Decision` | C9 → C10, C11 | typed value or `unanswerable`/`abstain`, reason, features | — |
| `SubmissionRecord` | C10 → C11 | `id`, `type`, `answer` (`reason` optional) | Exactly DG §3.2 |
| `LogRecord` | C11 → `/result/logs` | `id`, `answer`, `elapsed_ms`, `thinking`, `code`, `output` (+ supporting fields §7.6) | Exactly DG §3.3; captured, not reconstructed |

---

## 15. Implementation trade-offs

| Topic | Chosen | Alternative | Why chosen | Cost accepted |
|---|---|---|---|---|
| Serving topology | 2 × single-GPU replicas | TP=2 across GPUs | Testable on Colab; no NCCL/P2P/shm risk; 2× throughput | Model must fit 32 GB with KV |
| Serving interface | Local OpenAI-compatible servers | In-process engine | Same client in Colab and Docker; process isolation | Loopback under `--network none` must be verified |
| Execution language | DuckDB SQL | Python agent | Declarative, deterministic, fast on 300k rows | Procedural logic needs a fallback (P2) |
| Temporal logic | Deterministic resolver | LLM computes dates | Exactness and testability | Unsupported expressions abstain until P2 |
| Confidence | Rule gate (P1) | Learned calibrator / ensemble | Simple and robust with little data | Misses some recoverable answers |
| Base image | Decided by bake-off | Reference image now | Possible accuracy gain from Qwen3.5 | Extra compatibility validation |
| Precision | BF16 by default | FP8 / AWQ | No quantization accuracy loss | Rules out Qwen3-14B on one GPU unless FP8 |
| Entity linking | Lexical + fuzzy | Embedding model | No parameter cost; deterministic | Weaker on paraphrased mentions |
| Thinking | Explicit per stage | Always on | Runtime and reproducibility | May lose accuracy on hard questions |

---

## 16. Open questions

1. **(Critical) E5 host.** Which Docker-capable sm_120 machine will run G6 and the frozen image on the private test? Is any team member's RTX 5090 available?
2. Is the training split available locally (and on Google Drive for Colab)? Does a baseline or public-round submission exist?
3. Which Colab plan and compute-unit budget does the team have, and is G4 consistently obtainable?
4. Is the upload channel (public Google Drive link) confirmed for a ~35–45 GB archive?
5. Can the organizers clarify integer vs. float handling for `number`, percent-change direction when the rulebook is silent, and `boolean` encoding?
6. When is the private test released, and how long is the window between release and the `submission.jsonl` upload? This sizes the E5 booking.
7. What is the reference answer when a question's window lies outside the data range (`0` or `unanswerable`)? To be learned from training references.
8. Should per-business setup time (ingestion, compilation) be attributed to each question's `elapsed_ms`? Proposed: no; it is logged separately in the business log, and per-question time includes only that question's own reads, reasoning, and execution.
9. Confirm that per-business LLM preprocessing at inference time (C3) is permitted as computation on mounted inputs.
10. Confirm DEC-11 against the `CLAUDE.md` rule on Vietnamese diacritics.

---

## Appendix A. Changes from v1

| Area | v1 | v2 |
|---|---|---|
| Status | Draft for approval | Baseline for implementation with approved decisions |
| Environments | Not addressed | Colab-based development, environment matrix, Colab design rules (§4) |
| Serving | DP or TP, undecided | DP replicas, no NCCL; TP as contingency (DEC-13) |
| Delivery | Single pipeline | P1/P2/P3 phases with merge rules (§10) |
| Decision layer | Ensemble + calibrator in the main design | Rule gate in P1; learned components gated in P3 |
| Logging | Field list | Field-by-field capture rules, business-level log for compiled views (§7.6) |
| Validation | Metrics list | Component tests, system gates G0–G8, traceability (§9) |
| Risks | Option-E risks only | Full register incl. infrastructure (§12) |
| Model table | Candidate list | Memory fit on 32 GB, vLLM requirements, one-model baseline (§8) |
| Output types | — | `boolean` added from DG §3.2 |
| New decisions | — | DEC-13 serving topology, DEC-14 E5 host |
| Team model (v2.1) | Five workstreams WS-A…WS-E | One lead (contracts, evaluation, integration) and four members M1–M4; component and risk owners updated |

## Appendix B. Sources
- Zalo AI Challenge 2026 — DataMate Docker Submission Guide (project document `zac2026_DataMate_docker_guideline_final.md`)
- DataMate Architecture Proposal v1 (sources listed therein: Qwen3.5 model reports, vLLM Qwen3.5-9B recipe, Hugging Face RTX 5090 benchmark discussion, vLLM batch-invariance documentation)
- [Colab GPUs: features and pricing (McCormick ML)](https://mccormickml.com/2024/04/23/colab-gpus-features-and-pricing/) — G4 runtime is an RTX PRO 6000 Blackwell
- [Running LLMs in Google Colab (datawookie, 2026-07)](https://datawookie.dev/blog/2026-07-31-running-llms-google-colab/) — current Colab runtime list including G4
- [Running Qwen3.5-35B on an RTX 5090 with vLLM](https://joshua8-ai-website.pages.dev/qwen35-35b-rtx-5090-vllm-practical-guide) — RTX PRO 6000 and RTX 5090 share sm_120
- [vLLM forum: v0.9.0 image does not work on RTX 5090](https://discuss.vllm.ai/t/docker-image-vllm-vllm-openai-v0-9-0-doesnt-work-on-5090/761) — older images lacked sm_120 kernels
- [vLLM recipe — Qwen3.5-9B](https://recipes.vllm.ai/Qwen/Qwen3.5-9B.md) — requires vLLM ≥ 0.17.0
- [Qwen3.5 small models overview (besthub.dev)](https://besthub.dev/articles/qwen3-5-small-models-unveiled-from-0-8b-to-9b-with-full-capabilities-e409056d2b3c) — parameter counts including vision; thinking-default claim
- [Docker is not supported on Colab (Stack Overflow archive)](https://kiwix.lema.org/stackoverflow.com_en_all_2023-11/questions/60235353/docker-is-not-running-on-colab)
- [Google Cloud GPU plans (vpsbenchmarks)](https://www.vpsbenchmarks.com/gpu_plans/google_compute_engine) — G4 VM option for E5
