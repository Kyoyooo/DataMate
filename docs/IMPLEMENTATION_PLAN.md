# DataMate 2026 — Implementation Plan

| Field | Value |
|---|---|
| **Document** | `IMPLEMENTATION_PLAN.md` |
| **Version** | 1.1 — one lead and four members |
| **Status** | Baseline schedule; updated daily by the lead |
| **Date** | 2026-11-06 (GMT+7) |
| **Window** | 2026-11-06 (Fri, afternoon) → 2026-11-16 (Mon) 23:59 GMT+7 — final Docker solution deadline |
| **Inputs** | `ARCHITECTURE_PROPOSAL.md` v2.1 (AP), `ARCHITECTURE.md` v1.1 (ARCH), `SPEC.md` v1.1 (SPEC) |
| **Task list** | `TASKS.md` v1.1 (IDs `L-xx`, `M1-xx` … `M4-xx`; the prefix is the owner) |

All times are GMT+7. Dates are written `MM-DD` (2026).

---

## 1. Objectives and priorities

1. **Ship a valid, compliant, reproducible image** by 11-14 (safety) and 11-16 18:00 (final).
2. **Reach a working end-to-end baseline (P1)** on the full training split by **11-09**.
3. **Improve held-out PA** through P2 features between 11-10 and 11-12, each behind a switch.
4. **Freeze features on 11-13** after the container rehearsal; bug fixes only afterwards.

When time is short, the priority order is: **compliance and validity → determinism → runtime → accuracy** (AP §10).

---

## 2. Team and ownership

### 2.1 Roles
| Role | Person | Mission | Owns (packages) | Components |
|---|---|---|---|---|
| **Lead** | Team lead | Keep the pieces compatible and the measurements trustworthy; make the calls | `contracts/`, `eval/`, CI, `CODEOWNERS` | C14; contract module; integration; decisions; submissions |
| **M1 — Data & Semantics** | Member 1 | Turn arbitrary business files into a correct, queryable catalog | `ingest/`, `catalog/`, `entities/`, `lexicon/`, `semantics/` | C2, C3 (P2), C6 (P2) |
| **M2 — Rules, Time & Answers** | Member 2 | Everything deterministic between the rulebook and the wire value | `rules/`, `temporal/`, `decision/`, `formatting/` | C1, C5, C9, C10 |
| **M3 — Reasoning Engine** | Member 3 | Get correct SQL out of the model, reliably and reproducibly | `llm/client.py`, `prompts/`, `parse/`, `solver/`, `sandbox/` | C4, C7, C8, C13 client |
| **M4 — Platform & Compliance** | Member 4 | Make it run inside the container, on time, with compliant outputs | `run.py`, `config.py`, `runtime/`, `llm/replicas.py`, `llm/inprocess.py`, Docker, `tools/`, compliance docs | C11, C12, C13 replicas |

**Why this split.**
- Each member owns a contiguous slice of the pipeline with **few, typed seams** to the others (§4 and ARCH §10), so four people can build at once.
- The lead owns the **contracts** (what crosses the seams) and the **scorer and harness** (how we know it works). The scorer is written by someone other than the formatter's author (M2), so the oracle is independent of the code it checks.
- M2 holds all deterministic answer logic (dates in, typed answer out). This keeps rule interpretation, the gate, and formatting under one owner who can see how they interact.
- Planned load is balanced: 62–66 hours each (§12).

### 2.2 The lead's responsibilities
1. Contracts: write v1.0.0 by 11-07 12:00; approve every later change (SPEC §15).
2. Integration: run the daily merge window; keep `main` green; run the walking skeleton and the first full run.
3. Measurement: own the scorer, harness, nightly runs, determinism checks, and error analysis. No accuracy claim counts unless it comes from the harness with a run record.
4. Decisions: DEC-3, -4, -8, -10, -11, -13, -14, P3 go/no-go, freeze (§7).
5. Release: sign off the safety and final submissions.
6. Unblocking: the lead takes over a member's P1 task if it slips by more than half a day.

### 2.3 Backups
| If unavailable | Backup | Reason |
|---|---|---|
| M1 | M2 | Both work on CPU-side data code and share `lexicon/` |
| M2 | Lead | Lead owns the scorer and goldens that M2's formatter must match |
| M3 | Lead, with M4 for serving | Lead runs the bake-off analysis; M4 owns replicas |
| M4 | Lead | Runbooks (M4-12) are written so the lead can build, export, and submit |
| Lead | M4 for release, M3 for decisions input | Release runbooks; bake-off data |

---

## 3. Milestones

| Date | Milestone / integration stage | Exit criteria | Gate (AP §9.2) |
|---|---|---|---|
| Fri 11-06 PM | **Kickoff** | Roles assigned; repo created; E5 search started; Colab G4 access confirmed | — |
| Sat 11-07 12:00 | **I0 Contracts frozen** | `contracts/` v1.0.0 merged; schemas exported; test doubles and conformance suites available | Contract tests green |
| Sat 11-07 EOD | **M0 Foundations** | Scorer passes Brief examples; data-inspection report; fake catalogs published; Colab lock env; **E5 identified (DEC-14)**; DEC-11/13 decided | G0 |
| Sun 11-08 EOD | **I1 Walking skeleton** | `run.main` end-to-end on fixtures with `ReplayModelClient`; valid outputs and logs; determinism CI green | Integration test green |
| Mon 11-09 EOD | **M1 / I2 Baseline** | Full training split on G4; PA per type; runtime projection; **DEC-3, DEC-8, DEC-10 decided** | G1, G2, G3 |
| Tue 11-10 EOD | **First container build** | Image builds on E4; smoke run on E5 (10 questions, scoring command) | — |
| Wed 11-11 EOD | **M2 / I3 Accuracy** | P2 features merged or dropped; determinism check; gate value check; **DEC-4 decided** | G4, G5 |
| Thu 11-12 EOD | **P3 go/no-go; release candidate** | P3 decided; RC1 image built; README and declarations drafted | — |
| Fri 11-13 EOD | **M3 / I4 Rehearsal + freeze** | Full training split in the container on E5 with the exact scoring command | G6 |
| Sat 11-14 | **Safety submission** | Solution #1 uploaded; md5 verified from a second machine | G8 (partial) |
| Sun 11-15 EOD | **M4 Final candidate** | Re-run comparison; packaging checks; final README | G7, G8 |
| Mon 11-16 18:00 | **M5 Final** | Final image uploaded, verified, submitted | — |
| After release (date TBC, AP Q6) | **Private-test run** | Frozen image run on E5; `submission.jsonl` uploaded | — |

---

## 4. Collaboration protocol

### 4.1 Interface first
1. **Contracts before code.** Every type that crosses a package boundary lives in `contracts/` (SPEC §5) and is frozen at I0. Members implement against the contracts, not against each other's code.
2. **Fakes before real components.** By 11-07 EOD every consumer has something to code against: test doubles (L-04), fake catalogs (M1-11), scripted model clients (L-04); by 11-08 12:00 recorded model calls (M3-13). See the handoff table in `TASKS.md` §6.
3. **Public API only.** A package may import another package only through names exported in that package's `__init__.py` `__all__` (SPEC §4.3). Internal refactors never break other members.
4. **Conformance suites.** Every implementation of a protocol (`ModelClient`, `Executor`, `LunarCalendar`, `SubmissionSink`) must pass the shared suite in `tests/contract/conformance/` (SPEC §14.3). The test doubles pass the same suite, so a component tested against a double works against the real thing.
5. **Consumer tests.** When a member relies on a behavior of another member's output (for example, "SchemaCard lists distinct values for status columns"), the consumer writes a test in `tests/contract/consumers/`. The producer cannot merge a change that breaks it (SPEC §14.4).
6. **Switches for anything unfinished.** P2/P3 code merges with its switch off (SPEC §1.3), so partially finished work never changes production behavior.

### 4.2 Review matrix
Every merge request needs one approval from the reviewer below (enforced by `CODEOWNERS`, L-19). The reviewer is the main **consumer** of the code, because they are best placed to spot a broken assumption.

| Code owned by | Required reviewer | Reason |
|---|---|---|
| Lead (`contracts/`) | The member(s) whose components produce or consume the changed type | Contract changes affect them first |
| Lead (`eval/`) | M2 (scoring rules) or M4 (harness/run records) | Independent check of the oracle |
| M1 | M3 | Solver is the main consumer of SchemaCard and catalog |
| M2 (`rules/`, `temporal/`) | M3 | Solver consumes windows and rule parameters |
| M2 (`decision/`, `formatting/`) | Lead | Must agree with the scorer |
| M3 | M2 | Gate consumes attempts and typed values |
| M4 | M3 (serving, orchestration) or Lead (records, compliance) | Boundary partners |

Review turnaround target: **4 working hours**. A review not done by then may be taken over by the lead.

### 4.3 Daily cadence
| Time | Event | Owner |
|---|---|---|
| 09:00 | Stand-up, 15 min: yesterday, today, blockers, **handoffs due today** | Lead |
| 09:15 | Nightly report reviewed: PA, answers that changed since the previous night, new reason codes | Lead |
| 14:00–15:00 | **Merge window**: lead merges approved requests in dependency order; CI on `main` after each merge | Lead |
| 15:00 | `main` tagged `daily-MMDD` if green | Lead |
| 20:00 | Nightly harness run on Colab G4 from the daily tag (L-18) | Lead |

Outside the merge window, merges are allowed only for fixes that unblock someone.

### 4.4 Communication
- One project channel. Handoff delays, contract change requests, and decisions are posted there the same hour.
- Decisions are recorded in AP §13 and ARCH §9 the same day.
- A blocker is raised immediately, not at the next stand-up.

---

## 5. Shared environments and reproducibility

### 5.1 Environments
| Env | Purpose | Who |
|---|---|---|
| E1 Colab G4 (sm_120) | Serving, bake-off, full runs, runtime and determinism numbers | M3 (day), Lead (night), M4 (serving tests) |
| E2 Colab A100/H100 | Accuracy experiments when G4 is unavailable | M3, Lead |
| E3 CPU (Colab or laptops) | Unit, contract, integration, determinism CI | everyone |
| E4 Build host | `docker build`, `save`, checksum, upload | M4 |
| E5 Rehearsal / private-run host (sm_120 + Docker) | Exact scoring command; private-test run | M4, Lead |

E5 requirements: sm_120 GPU(s), preferably 2 × RTX 5090; NVIDIA driver R570 or newer; Docker with NVIDIA Container Toolkit; available 11-10, 11-13, 11-14/11-15, and during the private-test window. Options in order of preference (AP DEC-14): a member's RTX 5090 workstation; a cloud VM with a Blackwell GPU and full Docker support; a bare-metal rental.

### 5.2 Colab setup
- Shared Google Drive folder `DataMate/` with `data/train/`, `models/<candidate>/`, `locks/requirements.lock`, `runs/<date>-<commit>/`.
- Each session: copy data and model from Drive to local disk; create a venv from the lock; install the package from the commit under test (M4-02 notebook).
- Every harness run sets `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` and the G4 memory-cap override (`model.gpu_memory_utilization=0.30`, `model.replicas=1`).

### 5.3 Reproducibility rules (apply to every member)
| # | Rule | Enforced by |
|---|---|---|
| R1 | **One environment.** Everyone installs from the same `requirements.lock`, generated inside the chosen base image. No ad-hoc `pip install` in runs whose results are shared. | Harness environment fingerprint (L-12) |
| R2 | **One data snapshot.** `DataMate/data/train/` and each model directory have a `SHA256SUMS` file; the harness records and checks them. | L-12, M4-02 |
| R3 | **No local config edits.** Only `--dev --set key=value`, recorded in the run record. | `config.py` (M4-06) |
| R4 | **Run records or it didn't happen.** Any accuracy or runtime claim in a merge request links a run record under `runs/`. | Merge-request template (L-19) |
| R5 | **Compare like with like.** `compare_runs` refuses runs with different environment fingerprints, data snapshots, or model revisions unless explicitly overridden. | L-12 |
| R6 | **Prompt changes are versioned.** A wording change creates a new template version; recorded `ModelCall` fixtures are refreshed in the same merge. | SPEC §7.13.5, M3-13 |
| R7 | **Determinism CI.** Two runs on fixtures must be byte-identical before any merge. | L-20 |
| R8 | **Nightly golden diff.** Answers that change from one night to the next are listed with the commit range that caused them. | L-18 |

---

## 6. Engineering workflow

### 6.1 Branching and merging
- Trunk-based: short-lived branches `<owner>/<task-id>-<slug>` (for example `m2/M2-04-resolver`), merged in the daily window.
- `main` always passes unit, contract, conformance, consumer, integration, and determinism tests on CPU.
- Contract changes follow SPEC §15 and are merged only by the lead.

### 6.2 Definition of done (per task)
1. Code matches the SPEC section named in the task.
2. Every MUST in that section has a test named after it (`test_spec_<section>_<short_name>`, SPEC §14.2); tests pass on CPU.
3. Conformance and consumer tests for the touched packages pass.
4. No new static-check failures (import graph, public-API rule, id-literal scan, `ruff`, `mypy` where required).
5. Accuracy-affecting tasks: run record attached (held-out PA before/after).
6. Runtime-affecting tasks: G4 timing attached.
7. Approved by the required reviewer (§4.2).

### 6.3 Experiment discipline
- A feature is merged **on** only if it improves held-out PA and passes the runtime and determinism checks; otherwise it is merged **off** or dropped.
- No tuning against the public leaderboard; at most 5 public sanity submissions per day (AP §6.12).

---

## 7. Decision calendar

| When | Decision | Input | Default if undecided |
|---|---|---|---|
| 11-06 | DEC-11 + SPEC SC-2 (accent folding scope) | `CLAUDE.md` rule, SPEC §7.6.1 | Fold retrieval keys and identifiers only |
| 11-06 | DEC-13 (serving topology) | AP §6.3 | Two single-GPU replicas |
| **11-07** | **DEC-14 (E5 host)** | Availability, cost | **No default — escalate** |
| 11-09 | DEC-3 (model + base image) | Bake-off (M3-08, L-13) | Qwen3-8B on the reference image |
| 11-09 | DEC-8 (decision policy) | G2 results | Rule gate |
| 11-09 | DEC-10 (thinking) | Bake-off with/without | Off |
| 11-11 | DEC-4 (compiled views) | M1-13 measurement | Off |
| 11-12 | P3 adoption (calibrator, multi-strategy, LoRA) | M2-13, M3-12 | Off |
| 11-13 | Feature freeze | G6 | — |

---

## 8. Submission procedure

### 8.1 Solution submissions (11-14 safety, 11-16 final)
1. Confirm `main` commit, `run_config.json`, and model revision match the last passing G6 run.
2. Build: `docker build --platform linux/amd64 -t zaic2026_datamate_<team_name>:final .`
3. Inspect: platform `linux/amd64`; folder layout per DG §4.
4. Run the exact scoring command on E5 on the training split; run `tools/precheck.sh`.
5. Export: `set -o pipefail; docker save … | pigz -p 8 > zaic2026_datamate_<team_name>.tar.gz`.
6. Measure uncompressed size: `pigz -dc … | wc -c` (must be ≤ 100 GB).
7. `md5sum … > ….tar.gz.md5`; never rename the archive afterwards.
8. Upload; download on a second machine; `md5sum -c` must print `OK`.
9. Submit the link, the md5 line, and the uncompressed size; record everything in the submission log.

### 8.2 Private-test run (after release)
1. Use the **frozen** final image; no rebuild.
2. Run on E5 with the exact scoring command and the private test mounted at `/data:ro`.
3. Check: one line per question; logs complete; `run.json` counts.
4. Upload `submission.jsonl` for the provisional leaderboard.
5. Archive the full `/result` directory (evidence for any reproducibility review, DG §6).

---

## 9. Day-by-day plan

### Fri 11-06 (afternoon) — Kickoff
| Who | Work |
|---|---|
| Lead | Assign M1–M4; decide DEC-11 and DEC-13; start E5 search; create repository, CI, `CODEOWNERS` (L-01, L-02, L-03, L-19) |
| M1 | Inspect training split; start fixture set (M1-01) |
| M2 | Inspect `rulebook.md` and `calendar.csv` (M2-01) |
| M3 | Prepare Colab G4 venvs for candidate vLLM versions (M3-01) |
| M4 | Pull candidate base images; extract locks (M4-01) |

### Sat 11-07 — I0 and M0
| Who | Work |
|---|---|
| Lead | Format decisions by 10:00 (L-11); contracts v1.0.0 by 12:00 (L-04); scorer (L-10) |
| M1 | `fold()` and lexicon (M1-02); readers (M1-03–M1-05); numeric parser (M1-06); **fake catalogs (M1-11)** |
| M2 | Calendar (M2-02); period arithmetic (M2-03); start resolver (M2-04) |
| M3 | Model client (M3-02); prompt rendering (M3-03); serve tests (M3-01) |
| M4 | Colab env and data snapshots (M4-02); replica manager (M4-03); writer (M4-04) |
| **Exit** | G0; fake catalogs and client available; E5 identified |

### Sun 11-08 — I1 walking skeleton
| Who | Work |
|---|---|
| Lead | Integrate components into the skeleton (L-05); determinism CI (L-20) |
| M1 | Date parser (M1-07); Excel structure detection (M1-08); materialization and SchemaCard (M1-09, M1-10) |
| M2 | Resolver by 12:00 (M2-04); formatter (M2-06); rule gate (M2-07) |
| M3 | Parser (M3-04); solver (M3-05, M3-06); sandbox (M3-07); **recorded fixtures by 12:00 (M3-13)** |
| M4 | Orchestrator (M4-05); `run.py` with stub mode (M4-06); records (M4-07) |
| **Exit** | I1 integration test and determinism CI green |

### Mon 11-09 — M1 baseline
| Who | Work |
|---|---|
| Lead | First full run by 15:00 (L-06); harness (L-12); bake-off analysis (L-13); **DEC-3, DEC-8, DEC-10** at 18:00 |
| M1 | Fix ingestion crashers from the full run (M1-14) |
| M2 | TemporalParams extraction (M2-05); fixes (M2-14) |
| M3 | Bake-off runs (M3-08) |
| M4 | Runtime projection (M4-08); Dockerfile draft (M4-09) |
| **Exit** | G1, G2, G3 |

### Tue 11-10 — Error analysis and first container
| Who | Work |
|---|---|
| Lead | Error analysis with owners (L-14); nightly report (L-18) |
| M1 | Entity linker (M1-12, P2) |
| M2 | RuleProfile (M2-08); table conventions (M2-11) |
| M3 | Few-shot bank builder (M3-10); prompt improvements start (M3-09) |
| M4 | Image build (M4-09); E5 smoke (M4-10) |
| **Exit** | Error-analysis report; container smoke passes |

### Wed 11-11 — M2 accuracy
| Who | Work |
|---|---|
| Lead | Determinism check (L-15); merge or drop each P2 feature; **DEC-4** |
| M1 | Compiled views (M1-13, P2) |
| M2 | Lunar windows (M2-09); perturbation suite (M2-10); gate value check (M2-12) |
| M3 | Prompt improvements (M3-09); Python fallback (M3-11) |
| M4 | Fault-injection tests (M4-11) |
| **Exit** | G4, G5 |

### Thu 11-12 — P3 decision and release candidate
| Who | Work |
|---|---|
| Lead | **P3 go/no-go**; LoRA not started unless approved (AP DEC-9) |
| M1 | Fixes (M1-14) |
| M2 | Calibrator experiment if approved (M2-13) |
| M3 | Multi-strategy experiment if approved (M3-12) |
| M4 | Runbooks (M4-12); README and `training_code/` (M4-13); precheck (M4-14); RC1 (M4-15) |
| **Exit** | RC1 image built |

### Fri 11-13 — M3 rehearsal and freeze
| Who | Work |
|---|---|
| M4 | Full rehearsal on E5 (M4-16) |
| Lead | Compare container and G4 runs (L-16); **feature freeze** after G6 |
| M1, M2, M3 | Fix only defects found by the rehearsal |
| **Exit** | G6 |

### Sat 11-14 — Safety submission
| Who | Work |
|---|---|
| M4 + Lead | Export, checksum, upload, verify, submit (M4-17, L-08) |
| Lead | Second container run comparison (L-17) |

### Sun 11-15 — M4 final candidate
| Who | Work |
|---|---|
| All | Fixes only for defects found since 11-13, each re-validated on E5 |
| M4 | Final README; packaging checks (M4-18) |
| Lead | Approve final candidate |

### Mon 11-16 — M5 final
| Time | Step |
|---|---|
| by 12:00 | Final image built; G6 re-run on E5 if anything changed since the safety submission |
| by 15:00 | Export, md5, upload started |
| by 18:00 | Second-machine `md5sum -c` OK; form submitted (L-09) |
| 18:00–23:59 | Buffer only; no code changes |

---

## 10. Critical path

```
L-04 contracts ─► M1 catalog (M1-03..M1-10) ─┐
                 M2 temporal (M2-03, M2-04) ──┤
                 M3 solver (M3-02..M3-07) ────┼─► L-05 skeleton ─► L-06 full run ─► DEC-3 ─► M4-09 image ─► M4-16 rehearsal ─► M4-17 safety ─► L-09 final
                 M2 answer (M2-06, M2-07) ────┤                                                      ▲
                 M4 runtime (M4-03..M4-07) ───┘                                                      │
 DEC-14 E5 host (L-03) ──────────────────────────────────────────────────────────────────────────────┘
```
- **Longest chain:** contracts → catalog → solver → full run → model decision → image → rehearsal → submission.
- **External dependency:** the E5 host (DEC-14). Without it, the rehearsal and the private-test run cannot happen (AP RISK-1).
- **Parallel track:** base-image validation on G4 (M3-01, M4-01) starts on day 0 because it gates DEC-3.

---

## 11. Contingency plans

| Trigger | Response | Decision owner |
|---|---|---|
| No E5 host by 11-09 | Escalate; try an Apptainer `--nv` run of the exported image on Colab G4 (unofficial, AP RISK-1); keep searching | Lead |
| Preferred model fails sm_120 or determinism by 11-09 | Select the fallback model on the reference image | Lead |
| P1 baseline not end-to-end by 11-09 EOD | Stop all P2 work; everyone on the critical path until G2 passes | Lead |
| A handoff (TASKS §6) is late by > 4 h | Consumers continue on the fake; lead pairs with the producer | Lead |
| A contract defect is found after I0 | Patch/minor fix through SPEC §15 the same day; major change only with lead approval and same-day notice | Lead |
| Runtime projection > 2.5 h | Reduce `max_repairs`, context budget, few-shot count | M4 + M3 |
| Determinism check fails | Disable thinking; reduce concurrency; batch-invariant mode if validated | M4 |
| P2 feature lowers held-out PA | Merge with switch off, or drop | Lead |
| Rehearsal fails on 11-13 | Fix and re-run 11-14 morning; safety submission by 11-14 evening at the latest | M4 + Lead |
| Upload or md5 failure on 11-16 | Re-export and re-upload; the 11-14 safety image remains as fallback | M4 |
| A person unavailable for > 1 day | Backup per §2.3 takes over that person's P1 tasks first | Lead |

---

## 12. Effort overview

From `TASKS.md` §8, in engineer-hours.

| Owner | P1 | P2 | P3 | INT | COL | Total | Available (approx.) |
|---|---|---|---|---|---|---|---|
| Lead | 29 | — | — | 26 | 7 | 62 | 75 (after ~15 h of stand-ups, reviews, decisions) |
| M1 | 38 | 14 | — | 10 | 2 | 64 | 90 |
| M2 | 33 | 18 | 6 | 8 | — | 65 | 90 |
| M3 | 34 | 14 | 6 | 6 | 4 | 64 | 90 |
| M4 | 37 | 4 | — | 22 | 3 | 66 | 90 |

That leaves about 13 hours of slack for the lead and 24–26 hours for each member, for defects found by full runs and for reviews (about 1 h per day each). P3 hours are spent only if the 11-12 go/no-go approves them.
