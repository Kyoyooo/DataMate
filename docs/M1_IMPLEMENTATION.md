# M1 implementation and integration handoff

## Integration baseline

This branch starts from `origin/main` at `8cd5ff8` (2026-11-11). It replaces the
old bootstrap-based handoff. The shared contracts remain **1.10.0**:
`contracts/types.py`, `contracts/__init__.py`, temporal provenance, frames,
model-call stages, and runtime logs are unchanged from main. Only additive M1
warning registrations are proposed in `contracts/codes.py`.

Runtime `setup_business`, `make_fake_catalog`, and `load_catalog` return exactly
the shared `datamate.contracts.BusinessCatalog`. Warnings are strings in the
format `<CODE>` or `<CODE> <detail>`; top values remain `(value, count)` pairs.
These values pass through the existing decision gate without adapters in M2.

M1-specific profiles, source-row accounting, joins, candidate keys, date
classifications and experimental semantic evidence live in the internal
`catalog.models.IngestionCatalog`. Use `setup_catalog`,
`make_fake_ingestion_catalog`, and `load_ingestion_catalog` for audit work.
`to_runtime_catalog` explicitly projects these diagnostics onto main's contract.
No internal model replaces the shared contract or its version.

## Task ledger

| Task | Implementation | Verification boundary |
|---|---|---|
| M1-01 | `catalog/audit.py`, `tools/audit_m1.py`: file inventory, hashes, formats, sheets/tables, README observations and warnings | Full training run; README observations are structural evidence, not semantic certification |
| M1-02 | `lexicon/normalize.py`, packaged abbreviation/context TSVs | Whole-token expansion; ambiguous abbreviations remain unchanged with hints |
| M1-03 | `ingest/common.py`, `ingest/csv_reader.py` | BOM, UTF-8, UTF-16 and cp1258 regression fixtures; encoding assumptions remain visible |
| M1-04 | `ingest/engine.py`: calamine sheets and openpyxl fallback | Native types, cached formulas, 1904 epoch, all-sheet/fallback tests |
| M1-05 | SQLite immutable reader and scratch snapshot for live WAL | Source hashes and read-only fixture; POSIX directory protection tested on Linux |
| M1-06 | Exact Decimal parsing, scales, percentages, conventions, raw/status columns | Ambiguous values retained as text; failed parsing never becomes zero |
| M1-07 | Column date evidence, native dates, serials, source-year evidence | Missing years never use the machine year; durations remain durations |
| M1-08 | Header/block detection, totals, notes, source ordinals and dropped-row accounting | Independent fixtures preserve data resembling headers; running sums avoid quadratic scans |
| M1-09 | On-disk DuckDB, Arrow bulk load, atomic promotion, shared runtime projection | Public JSON round trips and existing main consumers |
| M1-10 | Profiles, keys, joins, activity coverage and token-bounded schema selection | Runtime hooks enforce the supplied tokenizer's budget; actual-model tokenizer and accuracy remain deployment checks |
| M1-11 | Independent fake catalogs and fixture generator | Consumer fixtures do not invoke source ingestion |
| M1-12 | Experimental entity index with deterministic exact/fuzzy ranking | Standalone tests; real-model off/on PA and runtime adoption remain deferred |
| M1-13 | Experimental semantic proposals and transactional SQL-view validation | Local compile-evidence model; not integrated into main's frozen stage/log contract; real-model gates remain deferred |
| M1-14 | Training audit, warning-fixture map, artifact and source-hash revalidation | All 30 businesses verified; no setup failures |

## Package ownership and prompt budgeting

The ingestion engine now lives in **`ingest/engine.py`**, with shared source
readers in `ingest/common.py`. The remaining `preprocessing/` modules are offline
split-preparation utilities and compatibility exports; runtime ingestion does
not depend on their calendar or rulebook preparation logic. Its training-only
`prepare_data` helper imports the question loader lazily.

`run.py` has only the minimal context-builder hook change. Existing orchestration,
deadlines, execution pools, M2 decision/temporal code, and M3 solver/parser code
are retained from main. There is no runtime-wide formatting rewrite.

The full SchemaCard is persisted for audit and can be large. Before a model call,
`catalog.context.build_context` connects M1's selector to the existing M3
`ContextBuilder.schema_fn` and `schema_subset_fn` hooks. The same tokenizer
counts both the SchemaCard and complete prompt. Production requires a shipped
local tokenizer; the estimate remains explicitly development-only.

Reduction proceeds from full schema to compact complete table descriptions,
then deterministic query-relevant tables. Non-status examples are expendable;
status vocabularies, complete selected columns, raw/status/unit references,
available candidate keys and selected-table joins are retained. Repeated warning
details are summarized by code/count. The full audit remains unchanged. Internal
metadata is loaded from the adjacent generated sidecar only when its database,
business and table signatures match the runtime catalog. If even the highest
ranked complete table cannot fit, the existing `E_CONTEXT_OVERFLOW` path abstains
before any model call. Missing tokenizer never silently bypasses budgeting.

Table ranking is lexical and deterministic; bounded context is not a claim that
retrieval always chooses the correct tables or improves model accuracy.

## APIs

```python
from pathlib import Path
from datamate.catalog import setup_business, setup_catalog, to_runtime_catalog
from datamate.config import RunConfig
from datamate.contracts import BusinessCatalog

cfg = RunConfig(work_dir="out/m1/work")
source = Path("data/train/train/data/<business>")
runtime = setup_business(source, "<business>", Path(cfg.work_dir))
assert type(runtime) is BusinessCatalog

# For audit tooling, instead of a second runtime setup:
details = setup_catalog(source, "<business>", cfg)
runtime = to_runtime_catalog(details)
```

`save_catalog` writes a portable JSON snapshot; `load_catalog` returns the shared
runtime view, while `load_ingestion_catalog` returns complete diagnostics. Internal
audit schemas are under `src/datamate/catalog/schemas/`, regenerated with
`tools/export_m1_schemas.py`. They are not shared-contract schema replacements.

## Reproducible verification

Install the repository and development dependencies in a CPU environment:

```bash
python -m pip install -e '.[dev]'
ruff check src tests tools
python -m pytest -o addopts= -q
python -m datamate.run --dev --config config/dev.json --data-dir tests/fixtures/split_mini --result-dir out/m1/fixture
python -m datamate.eval.score --pred out/m1/fixture/submission.jsonl --answers tests/fixtures/split_mini/answers.jsonl
```

The fixture replay was re-recorded through `RecordingModelClient` using the
existing scripted backend and current prompts. It is synthetic plumbing evidence,
not a real-model recording or accuracy claim.

Training verification (source directory is always read-only to ingestion):

```bash
python tools/audit_m1.py --split-dir data/train/train --output-dir out/m1/main-compatibility/training --role train
python tools/finalize_m1_audit.py --audit-dir out/m1/main-compatibility/training
python tools/check_m1_context.py --audit-dir out/m1/main-compatibility/training --questions data/train/train/questions.jsonl --output out/m1/main-compatibility/context-estimate.json --estimate
# Replace --estimate with --tokenizer-dir /path/to/shipped/model for production evidence.
```

The fresh run succeeded on **30/30 businesses, 339 tables and 3,996,993 rows**.
All **162 source checksums** are unchanged; all **30 README activity cutoffs**
match observed activity coverage. Expiry/payment-deadline dates are retained in
the database and audit metadata but excluded from activity coverage. Bounds are
computed from source values, never capped to a README date.

All **3,000 training questions** fit the **8,000-token schema budget** with the
explicit development estimator (maximum 8,000). Large examples:

| Business | Full audit card characters | Maximum selected estimated tokens |
|---|---:|---:|
| biz_118 | 374,087 | 8,000 |
| biz_122 | 368,543 | 7,997 |

These IDs label observed reports only; they do not occur in selection rules.
No training answers are used by context selection. The scripted fixture remains
**13/13 correct**. Full-suite platform results are recorded in the accompanying
compatibility verification report. Windows cannot certify POSIX process limits;
Linux is the integration-test target.

## Review and remaining boundaries

- Consumer review: additive config sections and warning registry entries,
  SchemaCard reduction policy, minimal `run.py` setup/context hooks, updated replay fixture.
- No shared type/stage/version rollback, new warning object wire format, or
  decision-gate modification is included.
- M1-12/M1-13 remain experimental and default off. The main runner does not
  activate them; compile-call evidence remains internal until a shared API is
  approved. Real-model PA gates remain separate work.
- Actual production-tokenizer measurements and reference-hardware performance
  approval remain outstanding; the estimator report does not substitute for them.
- Header confirmation safeguards the generic score against selecting data as
  headers. Date-year evidence uses source sheet/file text, never the current year.
- Notebook embedded snapshots have not been regenerated in this repair.
