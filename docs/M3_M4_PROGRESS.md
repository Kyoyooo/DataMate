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
