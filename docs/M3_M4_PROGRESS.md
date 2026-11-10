# M3 / M4 progress log

Owner of this log: whoever holds the M3/M4 backlog. Source of task status remains `docs/TASKS.md`. Entries record commands actually run and their actual output; "needs" lists what only a GPU, Colab, the E5 host or a human can do.

## 2026-11-11

### Baseline review (discrepancies with the hand-over note)
- `main` (`d240011`) is at **contracts 1.3.0**, not 1.1.0 (M2-05 temporal profile extension was already merged). `notebooks/MODEL_COMPARISION_L4.ipynb` referenced 1.3.0 and `parse.frame.v3`; both exist on `main`, but the notebook still is not reproducible evidence (L4 / sm_89, licenses and release dates unverified, no pinned commit).
- Consequence: the M3-02 additions are released as **contracts 1.4.0**, not 1.2.0 (a downgrade would break the additive-minor rule of SPEC §15).

### M3-02 `HttpModelClient` — branch `m3/M3-02-http-client-rebased`
- Original branch `m3/M3-02-http-client` untouched; its two commits were cherry-picked onto `main` (author Phong Nguyen preserved).
- Conflicts resolved in `src/datamate/contracts/types.py` (version) and `README.md` (package table). Both contract additions kept (`1.3.0` from main + `ModelCall.transport`, `E_MODEL_TIMEOUT`, `E_MODEL_TRANSPORT`); SPEC §18.4 and §18.5 kept, §18.5 corrected to `1.4.0`.
- Removed `notebooks/MODEL_COMPARISION_L4.ipynb` (and the superseded `MODEL_EVALUATION_Qwen3_8B.ipynb`). `notebooks/M3_02_HTTP_CLIENT_CHECK.ipynb` kept.
- Commands and results:
  - `.venv/bin/ruff check src tests` → `All checks passed!`
  - `.venv/bin/python -m pytest -o addopts="" -q` → `366 passed`
  - `.venv/bin/python -m datamate.run --dev --config config/dev.json --data-dir tests/fixtures/split_mini --result-dir <tmp>` → exit 0; scorer `PA = 1.0000 (n=13, correct=13, wrong=0, abstain=0)`
  - `.venv/bin/python -m datamate.run --config config/run_config.json ...` → `error: refusing to run: model.base_url is required for HTTP backend (M3-02)`, exit 2, no output directory
- Needs: real vLLM call on GPU (Colab) re-confirmed by the lead; M4 review of `model.*` keys.

### M4-03 replica manager — branch `m4/M4-03-replica-manager` (stacked on `m3/M3-02-http-client-rebased`: needs its config keys)
- `src/datamate/llm/replicas.py`: `build_command` (SPEC §7.13.1 flags, pure), `build_env` (fixed env + `CUDA_VISIBLE_DEVICES`), `ReplicaManager` (`start`, `poll`, `restart` with budget, `stop`, `client_configs`, `record` for run.json). Config section `serving.*` (README table). Deviation from SPEC §6.2: the keys live in a new `serving` section, not under `model`, because `model` already follows the HTTP client's flat layout; contracts unchanged.
- Tests: `tests/unit/test_replicas.py` + `tests/fixtures/fake_vllm_server.py` (stdlib fake server; same argv). `.venv/bin/python -m pytest -o addopts="" -q tests/unit/test_replicas.py` → `11 passed` (three consecutive runs).
- Not observed: a real vLLM start. `--no-enable-prefix-caching`, `--generation-config vllm` spellings are [VERIFY] against the pinned vLLM (SPEC §7.13.1). Needs: Colab/E5 run with `serving.mode=managed`.

### M4-05 orchestrator — branch `m4/M4-05-orchestrator` (stacked on `m4/M4-03-replica-manager`)
- `runtime/orchestrator.py` (assignment per SPEC §7.12, per-replica queues + worker threads, setup thread pool, soft/hard deadlines, global stop, SIGTERM, degrade projection, dead-replica drain), `ResultWriter` made thread-safe with `try_write` and `finalize_canonical`, `run.py` rewired (managed serving: start replicas → clients → run → stop; unstartable servers still produce a complete all-abstain submission, reason `E_REPLICA_DOWN`; missing `model.path` exits 2 with no output). Contracts **1.5.0** (codes only), SPEC §18.6 documents it and the deviations.
- Bug found by the concurrency run and fixed: DuckDB shares one instance per file in a process, so the second concurrent `SET lock_configuration` raised and every query returned `E_SQL_EXEC`; `open_readonly` now tolerates it. (M3-07 will replace this path with a real process pool.)
- Commands: `.venv/bin/ruff check src tests` → `All checks passed!`; `.venv/bin/python -m pytest -o addopts="" -q` → `390 passed`; fixture run with `--set concurrency.questions_per_replica=1` and `=24` → both `PA = 1.0000 (n=13, correct=13)`, `cmp` of the two `submission.jsonl` → identical.
- Not done / limits: a question in flight on a replica at the moment it crashes abstains (no re-queue); hard deadline is cooperative (no thread kill); no run on real vLLM.

### M3-13 replay client and recording — branch `m3/M3-13-replay-client` (stacked on `m4/M4-05-orchestrator`)
- `llm/replay.py` (`RecordingModelClient`, `ReplayModelClient`, `call_key`), `build_request_body` factored out of `HttpModelClient`, `model.replay_path` / `model.record_path` / backend `replay` (dev-only, `ProductionGuardError` otherwise), `E_REPLAY_MISS` (contracts **1.6.0**), `tools/record_model_calls.py`, `docs/runbooks/record-model-calls.md`, `config/replay.json`, fixture `tests/fixtures/model_calls/split_mini.scripted.jsonl` (recorded **through the scripted client**, labelled in its header; no real-model recording exists yet).
- L-20 test `tests/determinism/test_replayed_pipeline.py`: two fresh subprocesses → identical `submission.jsonl` bytes and identical `questions.jsonl` after removing `elapsed_ms`/`latency_ms`/`duration_ms`; replayed run scores 13/13; a changed seed (stands in for a template edit) → all abstain `E_REPLAY_MISS`.
- Commands: `.venv/bin/ruff check src tests` → clean; `.venv/bin/python -m pytest -o addopts="" -q` → `401 passed`.
- Needs (Colab): run `tools/record_model_calls.py` against Qwen on a training subset, commit the file; the tool itself has not been run against a live server.

### M4-07 / M4-19 records — branch `m4/M4-07-records` (stacked on `m3/M3-13-replay-client`)
- `runtime/promptstore.py` (prompt blobs, compacted `transport.request_body`), `runtime/environment.py` (environment fingerprint, model record), `LogRecord.degrade` (contracts **1.7.0**), `model.revision`, run.json and businesses.jsonl fields (SPEC §18.8).
- Commands: `.venv/bin/ruff check src tests tools` → clean; `.venv/bin/python -m pytest -o addopts="" -q` → `404 passed`. The end-to-end record test runs the real `HttpModelClient` against the fake vLLM server through managed serving.
- Needs: a real-model run to confirm `thinking` with thinking on/off (M4-19), and `nvidia-smi` fields on a GPU host.

### M4-01 base image and lock — branch `m4/M4-01-base-image` (from `main`; also cherry-picked below this entry's later branches so the Dockerfile has `requirements.in`)
- Added `docs/decisions/M4-01-base-image.md` (reference image facts from DG, candidate-serving table with evidence labels, what is unverified), `requirements.in`, `tools/gen_requirements_lock.sh` (`bash -n` → syntax ok; **not executed**: needs `docker pull` of an image that is not cached; `/` has ~17 GB free).
- `requirements.lock` intentionally absent. Needs: build host with Docker + network runs the script, commits the three outputs, then runs CPU tests inside the image.
- TASKS M4-01 → `Partial`.

### M4-09 Dockerfile / predict.sh and M4-13 compliance files — branch `m4/M4-09-docker` (stacked on `m4/M4-07-records`, plus the two M4-01 commits cherry-picked)
- Added `Dockerfile` (reference base by default; `ENTRYPOINT []`; fixed env; lock used as pip constraints; weights → training_code → code), `predict.sh`, `.dockerignore`, `config/run_config.json` (managed serving, 2 replicas; model path `/code/models/UNSELECTED` is a placeholder), `tools/build_image.sh`, `tools/count_params.py`, `training_code/*`, `docs/SUBMISSION_README.md`.
- Static tests: `tests/unit/test_packaging.py`, `tests/unit/test_count_params.py`. `.venv/bin/pytest` → `413 passed`; `ruff` clean.
- **Docker smoke (actually run)**: Docker 29.4.1 is installed, but no vLLM base image from the DG is cached and `/` has ~17 GB free, so I did **not** pull `vllm/vllm-openai:v0.10.1.1`. I built the Dockerfile with `--build-arg BASE_IMAGE=<a vLLM 0.22.1 / torch 2.11+cu130 image already present on this machine>`, a lock made by `pip freeze` in that image, and an empty `models/`: build OK (8.7 s). `docker run --network none … /code/predict.sh` (a) with the production config → `error: refusing to run: model.path '/code/models/UNSELECTED' is not a directory`, exit 2, no `submission.jsonl`; (b) with a mounted config pointing at `tests/fixtures/fake_vllm_server.py` → exit 0, 13 submission lines (all abstain `E_PARSE_INVALID`, as the fake server answers "pong"), `replica-0/1.log`, `run.json` with environment/model/timings. The smoke image was removed afterwards.
- This proves the packaging mechanics and offline loopback serving only. It says nothing about the reference base, sm_120, real weights, vLLM flags, or image size.
- Needs: `tools/gen_requirements_lock.sh`; DEC-3; `tools/build_image.sh <team> <model_dir>` on the build host; E5 run with the organizer command.

### M4-14 precheck and M4-12 runbooks — branch `m4/M4-14-precheck-runbooks` (stacked on `m4/M4-09-docker`)
- `tools/precheck.sh` / `tools/precheck.py`; runbooks `docs/runbooks/{build-export-upload,e5-run,private-test-run}.md` (plus `record-model-calls.md` from M3-13).
- `.venv/bin/pytest -o addopts="" -q` → `425 passed`; precheck on a real fixture result: C1–C3 PASS, PA 1.0000. Broken-dir tests: missing/duplicate/bad-type submission lines, missing `thinking`, negative `elapsed_ms`, missing log, log≠submission, missing `run.json`.
- Not run: `precheck --image` (no reference image), `--measure-tar`. Runbooks are untested by a person other than the author.

### M3-03 token budgeting — branch `m3/M3-03-token-budget` (stacked on `m4/M4-14-precheck-runbooks`)
- `llm/tokenizer.py`, `prompts/budget.py`, `solver.*` budget keys, `E_CONTEXT_OVERFLOW` (contracts **1.8.0**), pipeline + run.json integration, SPEC §18.9. Dev configs (`config/dev.json`, `config/replay.json`) use `solver.tokenizer=estimate`; production requires the real tokenizer (exit 2 otherwise).
- `.venv/bin/pytest -o addopts="" -q` → all pass (426 incl. 1 skipped real-tokenizer test: no local model/tokenizer files); ruff clean.
- **Coordination with M1**: M1's `select_schema_context` (branch `m1/M1-14-implementation-handoff`) already does SchemaCard budgeting/relevant-subset with an HF-style tokenizer; it was not copied. After M1 merges and rebases on the new contracts, wire it as `ContextBuilder(schema_fn=…, schema_subset_fn=…)` in `run._context_builder`. M1's branch also replaces `runtime/pipeline.py`; expect a conflict there with M4-05/M4-07/M3-03 (all of mine touch `answer_question`) — M1 should rebase onto main after these merge.

### M3-07 sandbox worker pool — branch `m3/M3-07-sandbox-pool` (stacked on `m3/M3-03-token-budget`)
- `sandbox/pool.py`, `SqlExecutor` threaded through solver → pipeline → orchestrator → `run.main`, `exec_limits.{isolation,workers,kill_grace_s}`, `E_EXEC_CRASH` (contracts **1.9.0**), SPEC §18.10.
- `.venv/bin/pytest -o addopts="" -q` → all pass; `tests/unit/test_sandbox_pool.py` 9 passed (≈8 s). RLIMIT_AS verified only through the memory-bomb behaviour (either `E_SQL_EXEC` from DuckDB's limit or `E_EXEC_CRASH`; both accepted, pool recovers).
- Not done: Python fallback executor (M3-11), RLIMIT value on the 8 GB production setting not exercised, behaviour under `--network none` irrelevant (no sockets used).

### M3-04/05/10 prompts v2 and few-shot bank — branch `m3/M3-04-prompts-fewshot` (stacked on `m3/M3-07-sandbox-pool`)
- `prompts/templates.py` (v2, v1 untouched and hash-pinned), `solver/fewshot.py`, `training_code/data_generation/build_fewshot.py`, `ContextBuilder.fit_fewshot`, pipeline/orchestrator/run wiring, `solver.template_version|fewshot_bank_path|fewshot_exclude_businesses`, SPEC §18.11. Default behaviour unchanged (v1, no bank).
- Tests: `tests/unit/test_prompts_fewshot.py` (8). Full suite passes.
- **No accuracy claim**: v2 and few-shot were never run against a model. Needs Colab: run the training split with v1 and v2, compare held-out PA by business fold (M3-09 gate), then build the bank from the better run.

### M3-11 python fallback — branch `m3/M3-11-python-fallback` (stacked on `m3/M3-04-prompts-fewshot`)
- `sandbox/python_exec.py`, `SandboxPool.run_python`, `solve.python.v1`, solver fallback stage, `solver.python_fallback` **default off**, contracts **1.10.0**, SPEC §18.12. M3-12 (P3 multi-strategy agreement) is not started, as instructed.
- Tests: `tests/unit/test_python_fallback.py` — 16 passed, 1 skipped (pandas DataFrame case: pandas is not installed locally). Full suite passes.
- No GPU evidence of any gain; leave off until L-07.

### M3-01 / M3-08 bake-off notebook — branch `m3/M3-01-bakeoff-notebook` (stacked on `m3/M3-11-python-fallback`)
- `notebooks/BAKEOFF_G4.ipynb` (generated, no outputs; refuses to run without a 40-hex commit that is an ancestor of `origin/main`, a training split with `answers.jsonl`, and 40-hex model revisions), `tools/bakeoff.py`, `tools/make_bakeoff_notebook.py`, `docs/runbooks/bakeoff.md`, `model.structured_outputs`.
- Tests: `tests/unit/test_bakeoff.py` (8). `.venv/bin/pytest -o addopts="" -q` → `476 passed, 2 skipped`; ruff clean.
- **Not run on any GPU.** The notebook cells were only syntax-checked (`ast.parse`); vLLM behaviours (`VLLM_BATCH_INVARIANT` support in the installed version, FP8 on sm_120, `--no-enable-prefix-caching` spelling) are unobserved. DEC-3 is the lead's.
