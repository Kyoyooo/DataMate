# DataMate 2026 — submission README (`/code/README.md`)

Zalo AI Challenge 2026 — DataMate. Offline agent that answers Vietnamese questions over business CSV/Excel/SQLite data, or returns `unanswerable` / `abstain`. Source repository layout and design: `docs/SPEC.md` in the repository; this file is the compliance README required by the Docker guide §8.

> **Release checklist — items marked `TO FILL` must be completed from the verified model card and the shipped files before the image is frozen (TASKS M4-13). Nothing below is a claim until filled.**

## 1. Approach

1. **Setup (per business).** Files in `/data/data/<business_id>/` are read (CSV, XLSX, SQLite), normalized into a DuckDB database under `/tmp/datamate/`, profiled, and summarized as a *SchemaCard*. `/data` is never written.
2. **Split context.** `rulebook.md` and `calendar.csv` of the mounted split are read at run time; temporal conventions come from the rulebook (model-assisted extraction with span validation, generic fallbacks logged), never from constants learned on training data.
3. **Per question.** A local LLM (served by vLLM on loopback, one replica per GPU) turns the question into a structured *QuestionFrame*; a deterministic resolver turns time expressions into date windows using the as-of date; the LLM writes one DuckDB `SELECT`, which is statically checked and executed read-only with a timeout; an optional repair turn feeds the error back. A rule-based decision gate chooses answer / `unanswerable` / `abstain`; a deterministic formatter writes the exact wire value (rounding, list order, types).
4. **Code execution.** Generated SQL runs inside the container in a read-only DuckDB connection with external access disabled. Each executed statement and its result is logged (`code`, `output`).
5. **Answer choice.** Wrong answers cost −1 and abstain 0, so the gate abstains when evidence is missing (failed parse, empty result, implausible value, deadline).
6. **Offline.** No network use except loopback to the local vLLM servers; `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`.

## 2. Models (all inference models; total ≤ 15 B parameters)

| # | Name | Public source URL | Fixed revision | Original release date | License | Parameters (from `python tools/count_params.py /code/models/<dir>`) |
|---|---|---|---|---|---|---|
| 1 | `TO FILL` | `TO FILL` | `TO FILL` | `TO FILL` (must be before 2026-10-26) | `TO FILL` | `TO FILL` |

No embedding, reranking or classification model is used. Total: `TO FILL` (must be ≤ 15,000,000,000). The configuration records `model.revision`; `run.json` records the file list and sizes of the shipped weights.

## 3. Data

- Training split provided by the organizers (30 businesses, ~3,000 questions with reference answers), packaged under `training_code/data/train/` with SHA-256 checksums in `training_code/data_manifest.json`. Used for development evaluation and (if built) the few-shot bank. Counts: see the manifest.
- Public test and private test data are **not** used for training, tuning, few-shot selection or answer collection.
- No data generation with external or commercial models was performed. `TO FILL` if this changes.

## 4. Training / fine-tuning

**No model fine-tuning, distillation or data generation was performed** (`TO FILL`: confirm at freeze; if a few-shot bank is built from the training split, its builder is in `training_code/`).

## 5. Running

```bash
docker run --rm --gpus '"device=0,1"' --network none --shm-size=16g --entrypoint bash \
  -v /path/to/split:/data:ro -v /path/to/output:/result \
  zaic2026_datamate_<team_name>:final /code/predict.sh
```

`predict.sh` takes no arguments, reads `/data`, and writes `/result/submission.jsonl` and logs under `/result/logs/` (`questions.jsonl` one record per question with `id`, `answer`, `elapsed_ms`, `thinking`, and `code`/`output` where SQL was executed; `run.json`; `businesses.jsonl`; `replica-<i>.log`). All settings are fixed in `/code/config/run_config.json`.

## 6. Folder layout

```
/code/predict.sh  /code/README.md  /code/requirements.txt
/code/src/datamate/        inference package (PYTHONPATH=/code/src)
/code/config/run_config.json   frozen configuration
/code/models/<model>/      inference weights, tokenizer, configs
/code/tools/               count_params.py, precheck.sh, record_model_calls.py
/code/training_code/       verification package (README, data_manifest.json, data/)
/code/docs/runbooks/       operator runbooks
```

## 7. Environment

Base image `vllm/vllm-openai:v0.10.1.1` (PyTorch 2.7.1+cu128), `ENTRYPOINT []`, `NCCL_P2P_DISABLE=1`. Exact package versions: `/code/requirements.txt` (output of `pip freeze` inside the base image). Target hardware: 2 × RTX 5090 (32 GB), 6 h limit; the run stops itself at 5 h 30 min and writes `abstain` for unanswered ids.
