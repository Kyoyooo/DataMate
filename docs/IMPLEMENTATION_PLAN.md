# DataMate 2026 — Implementation Plan

| Field | Value |
|---|---|
| **Document** | `IMPLEMENTATION_PLAN.md` |
| **Version** | 2.0 — rebased on the bootstrap codebase |
| **Status** | Phases, schedule, and process. Task status lives **only** in `TASKS.md` |
| **Date** | 2026-11-07 (GMT+7) |
| **Window** | 2026-11-06 (Fri, afternoon) → 2026-11-16 (Mon) 23:59 GMT+7 — final Docker solution deadline |
| **Inputs** | `ARCHITECTURE_PROPOSAL.md` v2.1 (AP), `ARCHITECTURE.md` v1.1 (ARCH), `SPEC.md` v1.1 (SPEC) |
| **Task list** | `TASKS.md` v2.0 (IDs `L-xx`, `M1-xx` … `M4-xx`; the prefix is the owner) |
| **Engineering workflow** | `CONTRIBUTING.md` (branches, PRs, reviews, GitHub settings) |

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
| **Lead** | Team lead | Keep the pieces compatible and the measurements trustworthy; make the calls | `contracts/`, `eval/`, `tests/integration/`, CI | C14; contract module; integration; decisions; submissions |
| **M1 — Data & Semantics** | Member 1 | Turn arbitrary business files into a correct, queryable catalog | `ingest/`, `catalog/`, `lexicon/`; later `entities/`, `semantics/` (P2) | C2, C3 (P2), C6 (P2) |
| **M2 — Rules, Time & Answers** | Member 2 | Everything deterministic between the rulebook and the wire value | `rules/`, `temporal/`, `decision/`, `formatting/` | C1, C5, C9, C10 |
| **M3 — Reasoning Engine** | Member 3 | Get correct SQL out of the model, reliably and reproducibly | `llm/client.py`, `prompts/`, `parse/`, `solver/`, `sandbox/` | C4, C7, C8, C13 client |
| **M4 — Platform & Compliance** | Member 4 | Make it run inside the container, on time, with compliant outputs | `run.py`, `config.py`, `runtime/` (orchestration, writer), `llm/replicas.py` (model serving), Docker, `tools/`, compliance docs | C11, C12, C13 replicas |

**Why this split.**
- Each member owns a contiguous slice of the pipeline with **few, typed seams** to the others (§4 and ARCH §10), so four people can build at once.
- The lead owns the **contracts** (what crosses the seams) and the **scorer and harness** (how we know it works). The scorer is written by someone other than the formatter's author (M2), so the oracle is independent of the code it checks.
- M2 holds all deterministic answer logic (dates in, typed answer out). This keeps rule interpretation, the gate, and formatting under one owner who can see how they interact.

### 2.2 The lead's responsibilities
1. Contracts: 0.1.0 is merged (bootstrap); freeze v1.0.0 (TASKS L-04); approve every later change (SPEC §15).
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

## 3. Phases and milestones

The backlog in `TASKS.md` is organized in the same seven phases. Dates are targets; the exit criterion is what counts.

| Phase | Target | Content | Exit criterion |
|---|---|---|---|
| **1. Shared foundation and fixture pipeline** | 11-07 | Package, contracts 0.1.0, fixture business, scripted CPU pipeline, tests, CI file, docs (TASKS L-21) | **Engineering criterion reached 11-07:** `pytest` green on CPU; fixture run exits 0; production mode refuses dev-only components. **Phase not closed** until L-02, L-04, and L-19 finish (`TASKS.md` Phase 1) |
| **2. Real P1 components in parallel** | 11-08 → 11-09 | Each owner replaces their stand-in with the real component behind the same contracts | Each component's acceptance tests pass on CPU; contracts v1.0.0 frozen (11-08 12:00) |
| **3. First real end-to-end run on Colab** | 11-09 | `HttpModelClient` + real ingestion on the full training split | All 3,000 questions written with valid logs; PA per type from the harness; runtime projection; **DEC-3** |
| **4. Evaluation and correctness fixes** | 11-10 → 11-11 | Error analysis, owner fixes, determinism check | Top error classes owned; two identical Colab runs within \|ΔPA\| ≤ 0.005 |
| **5. P2 features (only when justified)** | 11-10 → 11-12 | Switch-guarded features; each turned on only with a held-out gain | Each switch decided by L-07 with a run record; **feature freeze 11-13** |
| **6. Docker and target hardware** | 11-10 → 11-13 | Image, `predict.sh`, E5 smoke and full rehearsal | G6: full training split in the container with the exact organizer command |
| **7. Reproducibility and release** | 11-14 → 11-16 | Second container run, safety submission (11-14), final (11-16 18:00) | G7/G8; final image verified from a second machine |
| Private test | 11-20 → 11-23 | Run the frozen image; upload | Uploaded before 11-23 23:59 (TASKS L-22) |

---

## 4. Collaboration protocol

### 4.1 Interface first
1. **Contracts before code.** Every type that crosses a package boundary lives in `contracts/` (SPEC §5) and is frozen at I0. Members implement against the contracts, not against each other's code.
2. **Stand-ins before real components.** Every consumer already has something to code against: the fixture business catalog (`tests/fixtures/split_mini`), `ScriptedModelClient`, the in-process executor, and generic `TemporalParams`; recorded model calls follow (M3-13). Each Phase 2 row in `TASKS.md` names its stand-in.
3. **Public API only.** A package may import another package only through names exported in that package's `__init__.py` `__all__` (SPEC §4.3). Internal refactors never break other members.
4. **Shared tests over ceremony.** Real implementations must pass the same tests their stand-ins pass (for example, `HttpModelClient` and `ScriptedModelClient` both return errors as `ModelCall.error`). Formal conformance suites are added only when a second implementation of a protocol exists.
5. **Consumer tests.** When a member relies on a behavior of another member's output (for example, "SchemaCard lists distinct values for status columns"), the consumer writes a test in `tests/contract/consumers/`. The producer cannot merge a change that breaks it (SPEC §14.4).
6. **Switches for anything unfinished.** P2/P3 code merges with its switch off (SPEC §1.3), so partially finished work never changes production behavior.

### 4.2 Review
The only enforced rule is that changes reach `main` through a pull request (TASKS L-19). Review is optional; `CONTRIBUTING.md` names a suggested reviewer per package. Shared-interface changes are announced to the affected members before merging.

### 4.3 Daily cadence
| Time | Event | Owner |
|---|---|---|
| 09:00 | Stand-up, 15 min: yesterday, today, blockers, **handoffs due today** | Lead |
| 09:15 | Nightly report reviewed: PA, answers that changed since the previous night, new reason codes | Lead |
| 14:00–15:00 | **Merge window**: lead merges ready pull requests in dependency order; CI on `main` after each merge | Lead |
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
| R4 | **Run records or it didn't happen.** Any accuracy or runtime claim in a merge request links a run record under `runs/`. | Pull request description (`CONTRIBUTING.md`) |
| R5 | **Compare like with like.** `compare_runs` refuses runs with different environment fingerprints, data snapshots, or model revisions unless explicitly overridden. | L-12 |
| R6 | **Prompt changes are versioned.** A wording change creates a new template version; recorded `ModelCall` fixtures are refreshed in the same merge. | SPEC §7.13.5, M3-13 |
| R7 | **Determinism CI.** Two runs on fixtures must be byte-identical before any merge. | L-20 |
| R8 | **Nightly golden diff.** Answers that change from one night to the next are listed with the commit range that caused them. | L-18 |

---

## 6. Engineering workflow

Branching, PR size, the definition of done, and the GitHub setting are in `CONTRIBUTING.md`. In short: short-lived `<owner>/<task-id>-<slug>` branches, small PRs into `main`, and shared-interface changes announced to the affected members.

### 6.1 Experiment discipline
- A feature is merged **on** only if it improves held-out PA and passes the runtime and determinism checks; otherwise it is merged **off** or dropped.
- No tuning against the public leaderboard; at most 5 public sanity submissions per day (Brief §5.3).
- No accuracy claim without a harness run record; fixture results are plumbing checks, not accuracy.

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

## 9. Day-by-day focus

Task IDs refer to `TASKS.md`; status is tracked there only.

| Day | Lead | M1 | M2 | M3 | M4 |
|---|---|---|---|---|---|
| Sat 11-07 | L-21 bootstrap (done); L-04, L-11 | M1-01 | M2-01 | M3-01 | M4-01 |
| Sun 11-08 | L-04 freeze 12:00; L-03 escalate if no E5; L-10 | M1-04, M1-09, M1-06 | M2-04, M2-05 (scripted) | M3-02, M3-03 | M4-02, M4-03 |
| Mon 11-09 | L-05, L-12, L-06; **DEC-3** | M1-07, M1-08, M1-10 | M2-05 (real), M2-06, M2-07 | M3-04, M3-05, M3-13 | M4-05, M4-08 |
| Tue 11-10 | L-14, L-18, L-20 | M1-14, M1-05 | M2-14, M2-08 | M3-09, M3-07 | M4-09, M4-10 |
| Wed 11-11 | L-15, L-07 (P2 switches) | P2 by evidence (M1-15, M1-12) | P2 by evidence (M2-09, M2-12) | M3-10, M3-11 | M4-11, M4-19 |
| Thu 11-12 | L-07 (P3 go/no-go) | M1-14 | M2-14 | M3-09 | M4-12, M4-13, M4-14, M4-15 |
| Fri 11-13 | L-16; **freeze** | fixes only | fixes only | fixes only | M4-16 |
| Sat 11-14 | L-08, L-17 | — | — | — | M4-17 |
| Sun 11-15 | approve final candidate | fixes only, each re-validated on E5 | ← | ← | M4-18 |
| Mon 11-16 | L-09 by 18:00 | — | — | — | support |

---

## 10. Critical path

See `TASKS.md` "Critical path". Summary: **real ingestion (xlsx) and `HttpModelClient` → first full run → DEC-3 → image → E5 rehearsal → safety submission → final.** The E5 host (L-03) is the main external dependency.

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

## 12. Effort

Hour estimates from v1.1 were removed when the backlog was rebased on the bootstrap codebase; the lead re-estimates at the 11-08 stand-up if needed. Review time (about 1 h per member per day) remains part of the slack.
