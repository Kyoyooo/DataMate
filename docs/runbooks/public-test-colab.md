# Runbook — Round 1 public test on Colab (reference leaderboard)

Round 1 is for development: the public leaderboard is a reference only (COMPETITION_BRIEF §5.1). The final score comes
from the organizers' re-run of the frozen Docker image on 2 × RTX 5090 (§5.2 rule 8). A Colab run does **not** replace the
image, the private-test run ([private-test-run.md](private-test-run.md)) or the 2 × RTX 5090 timing and reproducibility checks.

Rules that apply to this run:
- Only run on the public test. Never tune prompts, rules or few-shot examples on its questions or on its leaderboard score
  per question (§5.2 rule 6: no training on test data).
- Never commit public-test data, submissions or logs: the repository is public. They stay on your Drive.
- Keep one GPU type for runs you compare (see the GPU section below).

## Before the session
- Put the public test zip in `MyDrive/DataMate/` (default name `public_test.zip`; set `PUBLIC_ZIP` if it differs), or an
  unzipped copy in `MyDrive/DataMate/data/public_test/`. It must contain one split folder with `questions.jsonl` and
  `rulebook.md`, and no `answers.jsonl`.
- `train.zip` must also be there: the 30 training questions run first as a smoke test.
- GPU: **G4** if you can select it (Blackwell, like the RTX 5090). Otherwise an **A100**: correct and usable, but its speed
  is indicative only and it does not exercise the Blackwell kernels. T4 and TPUs cannot serve the model (the notebook stops).

## Run
1. Open `notebooks/colab_bootstrap.ipynb` in Colab and set the first cell:
   `BRANCH` (the code to run), `MODEL_REPO`, `RUN_PUBLIC_TEST = True`, `PUBLIC_RUN` (results folder name).
2. *Runtime → Run all*. Cells 1–7 run 30 training questions (stop if they fail). Cells 8–9 split the public test into
   chunks of `BUSINESSES_PER_CHUNK` whole businesses and run them one after another; each chunk is checked with
   `tools/precheck.py` and copied to `MyDrive/DataMate/runs/<PUBLIC_RUN>/chunk-XX/` with a `DONE` file.
3. After a disconnect or a failed chunk: *Run all* again with the same `PUBLIC_RUN`. Finished chunks are skipped. The
   notebook refuses to continue a run that was started with another commit or model; use a new `PUBLIC_RUN` instead.
4. When every chunk is done, the notebook writes `runs/<PUBLIC_RUN>/submission.jsonl` (all answers, in the order of
   `questions.jsonl`; every id exactly once) and `meta.json` (commit, branch, model, config, GPU, Python environment,
   minutes per chunk). Upload `submission.jsonl` to the Round 1 leaderboard.

## Notes
- Each chunk starts and stops its own model server (a few minutes of load time per chunk); fewer, larger chunks are faster
  but lose more work on a disconnect.
- Only `submission.jsonl` is merged. Each chunk keeps its own genuine `logs/` and `run.json`; no combined log is written.
- Settings: `config/colab.json` (one replica, about 32 GB of GPU memory) with the model path and vLLM command set by the
  notebook, the same as the GPU check. `model.path` in `config/run_config.json` stays `UNSELECTED` until DEC-3.
- Record the leaderboard score with `PUBLIC_RUN`, the commit and the model from `meta.json` (for example in the team's
  notes), not in the repository together with any per-question data.
