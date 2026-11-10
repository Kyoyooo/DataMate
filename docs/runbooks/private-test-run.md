# Runbook — private-test run of the frozen image (L-22; opens 2026-11-20 09:00 GMT+7)

Rules: **do not rebuild, retag, edit or reconfigure the frozen image.** Use the image that was submitted (check `docker image inspect -f '{{.Id}}' …` against the id recorded at submission). Upload `submission.jsonl` before 2026-11-23 23:59 GMT+7.

1. Get the private split from the organizers; keep it read-only; do not open the data or the questions beyond what the run needs (no tuning on it, Brief §5.2-6).
2. Host: E5 (see `e5-run.md` §0), nothing else running on the GPUs.
3. Run with the exact command, no extra flags or environment:
   ```bash
   docker run --rm --gpus '"device=0,1"' --network none --shm-size=16g --entrypoint bash \
     -v /path/to/private_test:/data:ro -v /path/to/out_private:/result \
     zaic2026_datamate_<team>:final /code/predict.sh 2>&1 | tee /path/to/private_run.console.log
   ```
   Expected duration: model load a few minutes, then the per-question projection from the rehearsal; the run stops itself at 5 h 30 min and writes `abstain` for unanswered ids.
4. Check: `tools/precheck.sh --data-dir /path/to/private_test --result-dir /path/to/out_private`. All PASS required (C4 projection is informative here).
5. If precheck fails because of a missing line or id: do **not** edit `submission.jsonl` by hand for answers. Report to the lead; the writer is crash-safe and `logs/progress.log`, `replica-*.log`, `run.json.errors` say what happened.
6. Upload `/path/to/out_private/submission.jsonl`. Archive the whole `/result` (`tar czf private_result.tar.gz`) and the console log. Record image id, start/end times, `md5sum submission.jsonl` in `docs/M3_M4_PROGRESS.md`.
7. Reproducibility: organizers re-run the image; |PA(uploaded) − PA(re-run)| must be ≤ 0.03. Keep `out_private` untouched in case the organizers ask for logs.
