# Runbook — GPU check (closes the GPU half of Phase 2)

One Colab session collects every acceptance check that needs the model or a GPU. The notebook only produces raw files; the verdicts are computed on your own computer. Nothing here chooses the model (DEC-3).

## Before the session
- Main contains the commit you want to check (the notebook clones `main` and records the commit).
- `MyDrive/DataMate/train.zip` exists (the training split). The model is downloaded once and kept under `MyDrive/DataMate/models/`.
- Colab runtime: a Blackwell GPU (compute capability 12.0) if available. On another GPU the results are indicative only, and the report says so.

## 1. On Colab (about 40-60 min)
Open `notebooks/GPU_CHECK.ipynb`, edit the first cell if needed (`MODEL_REPO`, `VLLM_VERSION` = the base image's vLLM, currently `0.10.1.1`), then **Run all**. It saves to `MyDrive/DataMate/gpu_check/<date-time>/`:

| Saved | Produced by | Checks |
|---|---|---|
| `runs/fixture/`, `split_mini.recorded.jsonl` | fixture run with the real model, every call recorded | M3-02, M3-13 |
| `runs/train-A1/`, `runs/train-A2/`, `answers.jsonl`, `subset/` | two identical runs, 2 questions × 30 training businesses | M3-04, M3-05, M3-03 (overflow), L-15, PA, M4-02, M4-08 |
| `runs/thinking-on/`, `subset_think/` | thinking on, `serving.reasoning_parser` set | M4-19 |
| `runs/restart/` | model server killed after 3 answers | M4-03 |
| `context_check.json`, `context_check.log` | real tokenizer, all 3,000 training questions (CPU, background) | M3-03, M1-10 |
| `env/count_params.json`, `env/nvidia-smi.txt`, `env/pip-freeze.txt`, `meta.json` | environment | 15 B limit, records |

If a cell fails, fix the cause and **Run all** again: every step overwrites its own run folder.

## 2. On your computer (no GPU)
Download the folder, then:
```bash
.venv/bin/python tools/gpu_check_report.py --runs <folder>
```
One line per check: `PASS`, `FAIL` or `NOT RUN`, plus `INFO` values (PA, expected_type accuracy, solve rates, throughput). It writes `report.json` into the folder and exits 1 if anything failed. For a single run: `tools/gpu_check_report.py --stages <run dir> --answers <answers.jsonl>`.

## 3. After the report
- Copy `split_mini.recorded.jsonl` to `tests/fixtures/model_calls/split_mini.<model>.jsonl` and commit it: the fixture is synthetic, so this file contains no competition data. **Never commit** the training runs, the training recordings or `subset*/`: they contain training data, and the repository is public.
- Update `docs/TASKS.md` with the report lines (command + result) for M3-02, M3-03, M3-04, M3-05, M3-13, M4-02, M4-03, M4-07, M4-19, L-20.
- Lead decisions that follow: DEC-3 (model, revision, base image), template `v1` vs `v2`, `enable_thinking`, and the serving values in `config/run_config.json`.
- Comparing several candidates: `notebooks/BAKEOFF_G4.ipynb` and `docs/runbooks/bakeoff.md` (held-out whole businesses, determinism experiments). Fold-based training runs: `python -m datamate.eval.harness run ...` (SPEC §7.14).
