# M1 compatibility repair verification

Verified on 2026-11-11 against `origin/main` commit `8cd5ff8`.
Review branch: `m1/M1-14-main-compatibility`. The earlier bootstrap-based
`m1/M1-14-implementation-handoff` is superseded by this branch.

| Lead finding | Resolution | Regression evidence |
|---|---|---|
| Old contracts and temporal parameters | Keep main's 1.10.0 types/exports unchanged; explicit projection of internal ingestion diagnostics to shared catalog | Contract suite; public catalog/fake/load round trips; temporal provenance regression |
| Warning objects break the decision gate | Shared warnings are strings, top values remain tuples; register new warning codes additively | Actual `pre_solve_decision` call with ingestion warnings; main decision tests |
| SchemaCard exceeds 8,000 tokens | Wire the same tokenizer into M1's schema selector and M3's existing ContextBuilder hooks; reduce examples, then whole tables; overflow before model calls | 370,000-character regression and captured parse request; 3,000-question development-estimator report |
| Runtime churn and misleading package | Engine lives under `ingest/engine.py` and `ingest/common.py`; minimal setup/context hooks in `run.py` | Runtime, decision, parser, solver and prompts unchanged from main; no shared type rollback |

## Commands and actual results

Linux (Ubuntu 22.04 through WSL, Python 3.10.12, isolated development environment):

```bash
python -m pytest -o addopts= -q -rs --junitxml=out/m1/main-compatibility/pytest-linux-final.xml
# 548 passed, 4 skipped in 117.71s
```

Skipped: two optional tests expect `train/answers.jsonl` (the supplied data is at
`data/train/train`); the optional local-model tokenizer test requires
`transformers`; a Python-fallback test requires `pandas`. Linux read-only source
directory enforcement, main contract/decision tests, replay determinism,
orchestration, process sandbox and packaging tests passed.

Windows checkout shell scripts had CRLF line endings. Their local checkout was
normalized to the LF bytes already present in Git before the successful Linux
run. No shell-script logic changes are included. The initial Linux attempt's
12 shell-related failures are retained in `pytest-linux.xml`; the final XML is
the authoritative passing run. Windows-only attempts are not represented as a
passing production-platform suite.

```bash
ruff check src tests tools
# All checks passed!
git diff --check
# No whitespace errors
python -m datamate.eval.score --pred out/m1/main-compatibility/fixture/submission.jsonl --answers tests/fixtures/split_mini/answers.jsonl
# PA = 1.0000 (n=13, correct=13, wrong=0, abstain=0)
```

The fixture ran through the current CLI with the scripted client and explicit
development in-process execution. Replay requests were re-recorded through
`RecordingModelClient` after the SchemaCard changed; the final Linux suite also
passed process-isolated fixture and replay tests. This is plumbing evidence,
not training-model accuracy.

```bash
python tools/audit_m1.py --split-dir data/train/train --output-dir out/m1/main-compatibility/training --role train
python tools/finalize_m1_audit.py --audit-dir out/m1/main-compatibility/training
# 30/30 ready, 339 tables, 3,996,993 rows; no setup failures
# 162 source file hashes unchanged; 30/30 README activity cutoffs match
python tools/check_m1_context.py --audit-dir out/m1/main-compatibility/training --questions data/train/train/questions.jsonl --output out/m1/main-compatibility/context-estimate.json --estimate
# contracts_version=1.10.0, questions=3000, schema_budget_tokens=8000
# tokenizer=chars-estimate, production_tokenizer_verified=false, failures=[], valid=true
```

The full training run took 682.375 seconds on the current Windows host while
other validation was running; it is not a reference-hardware benchmark.
`biz_118` and `biz_122` full cards contain 374,087 and 368,543 characters;
their maximum selected estimated counts were 8,000 and 7,997 respectively.
No business/question ID is used by schema-selection logic. The context checker
does not read answers or call a model.

## CI replay correction: fixture line endings

GitHub CI exposed a replay mismatch that the first WSL run did not reveal: WSL
read the Windows checkout's CRLF rulebook, whereas a clean Linux checkout uses
LF. `load_split` deliberately preserves rulebook bytes (after UTF-8 decoding/NFC),
so the prompt and request hashes differ. The old recording contained CRLF-based
requests. With Python **3.12.16** and the exact `requirements-cpu.lock`, changing
only the synthetic rulebook checkout to Git's LF bytes reproduced the CI failure:
all 13 questions returned `E_REPLAY_MISS`.

The fix pins the synthetic replay rulebook and model-call JSONL files to LF via
`.gitattributes`, and re-records calls through the existing scripted client on
Python 3.12.16. It does not normalize mounted competition rulebooks, relax replay
matching, or remove the exact-answer assertion. A regression test checks the
fixture's line endings, and replay failures now print per-question reason codes.

Re-record command (development fixture only):

```bash
python -m datamate.run --dev --config config/dev.json --data-dir tests/fixtures/split_mini --result-dir out/m1/ci-debug/record-lf --set exec_limits.isolation=inprocess --set model.record_path=tests/fixtures/model_calls/split_mini.scripted.jsonl --set concurrency.questions_per_replica=1 --set work_dir=out/m1/ci-debug/record-work
```

The regenerated fixture run scores 13/13 correct. For an existing Windows
checkout that still contains CRLF after pulling the attributes file, restore
the fixture checkout using its pinned attributes:

```bash
git checkout-index --force -- tests/fixtures/split_mini/rulebook.md
```

Final verification uses Python **3.12.16**, every version pinned in
`requirements-cpu.lock`, and source/interpreter/environment on the native Linux
filesystem: **549 passed, 4 skipped in 58.51s**. The four optional skips are the
same ones listed above. Report: `out/m1/ci-debug/pytest-python312-linux-fs.xml`.

Running that environment from the mounted Windows filesystem exposed a separate
2-second worker-start timeout in the existing sandbox replacement test. The
unchanged test passed on native Linux storage along with the complete suite;
no sandbox timeout, assertion or production code was changed by this repair.
The earlier Python 3.10 run above remains historical evidence, not a substitute
for this pinned Python 3.12 verification.

## Review boundary

Review additive config and warning registry entries, SchemaCard selection,
the small `run.py` integration diff, and regenerated synthetic replay evidence.
Detailed audit models/schemas are explicitly internal to M1; shared version,
temporal provenance and warning representation remain main's contract.

Production measurements must use the shipped model tokenizer via
`--tokenizer-dir` instead of `--estimate`. Selection quality and M1-12/M1-13
accuracy gates still require model evaluation; these optional features remain
disabled and are not activated by the main runner. Notebook snapshots and
submission-image acceptance are outside this repair.
