# Runbook — model bake-off and determinism investigation (M3-01, M3-08)

Hand this to the lead; no DEC-3 decision is taken by the notebook.

## What you need
- Colab **G4** (Blackwell, compute capability 12.0) — the only valid hardware for target evidence. An L4/A100 session runs but every result is flagged `NOT TARGET HARDWARE`.
- Drive folder with the **training** split (`answers.jsonl` present; the notebook refuses anything else).
- For each candidate: Hugging Face repo id and a **40-hex revision** from the model card (never `main`).
- A commit of `main` containing this work. The notebook checks out that commit and refuses a commit that is not an ancestor of `origin/main`.

## Steps
1. Open `notebooks/BAKEOFF_G4.ipynb` from that commit; edit only the parameter cell (`REPO_COMMIT`, `TRAIN_DIR`, `CANDIDATES`; leave `FOLD = 0`).
2. Run all cells. Expected time per candidate: model download + 2 held-out runs + 10 determinism runs on a small subset; plan 2–3 h for two candidates.
3. Read in this order: the verification table (any `FAIL`/`UNVERIFIED` must be resolved by a human against the model card before the candidate can be chosen), the per-candidate PA / determinism line, the determinism matrix.
4. Copy `bakeoff_results.json` and the printed tables into the DEC-3 record.

## How to read the determinism matrix
`identical_output_rate` = share of calls where an identical request (same `request_sha256`) returned identical raw text, between two runs with the same concurrency. 1.0 with `submissions_identical = true` means that variant is deterministic on that subset. A variant that raises the rate and keeps PA is a candidate setting for `config/run_config.json` (e.g. `serving.env.VLLM_BATCH_INVARIANT`, `serving.max_num_seqs`, `serving.enable_prefix_caching`); changing it is the lead's call (SPEC D2: these values are fixed per run, never tuned at run time) and needs a full-split run record. `model.structured_outputs=false` is an experiment only: the parser then relies on prompt wording for valid JSON.

## What this does not establish
Final accuracy (the subset is a quarter of the businesses), 2-GPU throughput (one GPU here; do not multiply without checking), image size, offline behavior, or license terms beyond the hub metadata.

## Local self-check (CPU)
`python tools/make_bakeoff_notebook.py` regenerates the notebook; `pytest tests/unit/test_bakeoff.py` checks the helpers and that the committed notebook equals the generator output.
