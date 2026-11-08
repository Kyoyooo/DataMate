# Contributing

## Ownership

Ownership is by package. The owner is responsible for changes to their package. Review is encouraged but not required; the suggested reviewer is the person most affected by the change.

| Path (under `src/datamate/` unless noted) | Owner | Suggested reviewer |
|---|---|---|
| `contracts/`, `eval/`, `tests/integration/`, `.github/` | Lead | Every member whose component produces or consumes the changed type (contracts); M2 for scoring; M4 for CI |
| `ingest/`, `catalog/`, `lexicon/` (later `entities/`, `semantics/`) | M1 | M3 |
| `rules/`, `temporal/` | M2 | M3 |
| `decision/`, `formatting/` | M2 | Lead |
| `llm/client.py`, `llm/scripted.py`, `prompts/`, `parse/`, `solver/`, `sandbox/` | M3 | M2 |
| `run.py`, `config.py`, `runtime/`, `llm/__init__.py`, `llm/replicas.py`, Docker, `tools/` | M4 | M3 (serving, orchestration) or Lead (records, compliance) |
| `tests/unit/test_<area>.py`, `tests/fixtures/` | owner of the area | as above |

### Shared interfaces (tell the people affected)

A change to any of these can break other members' code. Note it in the PR description and tell the affected members before merging:

- `contracts/` types and `CONTRACTS_VERSION` (SPEC §15: patch / minor / major)
- `config.py` keys (add with a default; never rename silently)
- reason codes in `contracts/codes.py` (never reuse a code with a new meaning)
- the SchemaCard text format (`catalog/build.py: render_schema_card`) — consumed by prompts
- prompt template ids (`prompts/templates.py`) — a wording change is a new `.vN` id
- `lexicon.fold()` behavior

## Workflow

1. Pick a task from `docs/TASKS.md`; set it to `Partial`/`Review` in your PR, not before.
2. Branch from `main`: `<owner>/<task-id>-<slug>`, e.g. `m2/M2-04-resolver`. Keep branches short-lived (≤ 1 day).
3. Keep PRs small and reviewable (aim < 400 changed lines excluding fixtures). One task per PR.
4. Before pushing:
   ```bash
   .venv/bin/ruff check src tests
   ```
   ```bash
   .venv/bin/python -m pytest
   ```
5. PR description: task ID; what changed; **commands run and their actual output** (tests, fixture run, harness PA if accuracy-affecting); shared-interface impact; what is still missing.
6. Merge through the pull request once CI is green. Rebase on `main` rather than merging `main` into your branch.

### Definition of done
- The task's deliverable exists and its acceptance criteria in `docs/TASKS.md` pass, with the command and result in the PR.
- New behavior has a test with an independently derived expected value (hand-computed, from the Brief, or from the rulebook — not copied from the code's own output).
- No new lint errors; CPU tests pass without GPU, weights, or network.
- Accuracy claims cite a harness run on the training split (not the fixture, never the public test).

### Rules that protect the submission
- No logic keyed on `question_id` or `business_id`; no hard-coded answers; no training-rulebook constants in code (the mounted split's `rulebook.md` is authoritative at run time).
- Never write under the data directory; scratch goes under `work_dir`.
- Development-only code (`ScriptedModelClient`) must stay rejected outside `--dev`.
- Log only what actually happened: real model output, real executed SQL, real results.
- Do not strip Vietnamese diacritics from answers or data values; `fold()` is for matching keys only.

## GitHub setting

The only rule enforced on GitHub is that changes reach `main` through a pull request. In Settings → Branches, add a rule for `main` and enable:

- **Require a pull request before merging** (leave "Require approvals" unchecked)
- **Do not allow bypassing the above settings**, so the rule also applies to admins

Everything else stays at its default: no CODEOWNERS, required approvals, or required status checks. CI still runs on every pull request; check it before merging. (On a private repository, branch protection needs a paid GitHub plan.)
