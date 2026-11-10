# Runbook — record real model calls for replay CI (M3-13)

Purpose: turn a real Colab/GPU run on a **training** subset into a replay file that CPU CI can run (`ReplayModelClient`, L-20 determinism test). Replay answers are exactly what the model produced; they prove plumbing and determinism of everything except the model.

## Steps (Colab, vLLM server running or `serving.mode=managed`)
1. Check out the commit under test; install from the lock (`requirements.lock`, see M4-01).
2. Use a run config with the real `model.base_url` and the decoding values you want CI to freeze. Replay keys include every `model.*` sampling value, the schema and the prompt text, so **record and replay configs must agree** (only `backend`, `replay_path`, `record_path`, `base_url`, `path` may differ).
3. Record:
   ```bash
   python tools/record_model_calls.py --config config/colab.json --data-dir /content/train \
     --out tests/fixtures/model_calls/train_sample.jsonl --per-business 2 --max-questions 30
   ```
   The script refuses a split without `answers.jsonl`.
4. Commit the JSONL. Create the replay config (copy `config/replay.json`, set `replay_path`, same sampling values).
5. Verify on CPU: `python -m datamate.run --dev --config <replay config> --data-dir <train subset> ...` reports no `E_REPLAY_MISS` in `run.json.counts.by_reason`.

## After any template, schema or decoding change
Recorded requests no longer match: the replayed pipeline abstains every question with `E_REPLAY_MISS` and CI fails. Re-record in the same change (SPEC §7.13.5).

## Notes
- `tests/fixtures/model_calls/split_mini.scripted.jsonl` was recorded **through the scripted fixture client** (its header says so). It exercises the format and CI only; it is not model output. Regenerate: `python -m datamate.run --dev --config config/dev.json --data-dir tests/fixtures/split_mini --result-dir /tmp/x --set model.record_path=tests/fixtures/model_calls/split_mini.scripted.jsonl`.
- Identical requests that produced different outputs during recording are counted in `RecordingModelClient.conflicts`; the first output wins in the file (this is how non-determinism shows up).
