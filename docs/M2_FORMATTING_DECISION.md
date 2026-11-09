# M2-06 and M2-07 review evidence

## M2-06 formatter and L-10 scorer

`tests/golden/answers.jsonl` contains synthetic typed inputs and hand-written wire literals. Each row names its rule. The formatter test checks exact JSON, including key order and numeric versus string literals. The scorer reads the expected wire and wrong predictions independently of the formatter. Ranked inputs are also replayed in reverse input order. A separate test passes a DuckDB `DECIMAL(38,2)` through the scripted pipeline.

| Surface | Accepted behavior and coverage |
|---|---|
| Number and percent | SPEC DC-1 and §7.10. Money rounds to whole VND with `ROUND_HALF_UP`. Percent and other measures use two decimal places. Exact percent and average ties still use the documented V3 default pending organizer confirmation. Formatter quantization is independent of the default decimal precision. The shared JSON writer preserves all digits and emits integral values as JSON integers. |
| Boolean, string and date | V4 requires JSON booleans. Stored text stays accented and is NFC-normalized and trimmed. Day and month date shapes are preserved. |
| Lists | DC-2 preserves question positions. V5 sorts tied decimal codes numerically when every supplied code is decimal. Mixed and fixed-width alphanumeric codes use lexical order. A type fallback stabilizes otherwise equal display keys. The golden empty list uses an explicitly typed value. |
| Tables | V2 uses `columns` and `rows`. Formatter preserves column and row order. The scorer supports name-based column reordering and one-to-one row matching, including overlapping aliases. Nullable cells and empty tables are synthetic cases from the frozen wire contract. Naming conventions for additional table types remain M2-11. |
| Declines | `unanswerable` carries an optional reason and no value. `abstain` scores zero. Tests reject numeric strings, fake booleans, wrong list positions, malformed tables and non-finite numbers. Existing scorer numeric tolerance and PA weights are retained. |

The historical baseline passes native values through small number/percent helpers and uses Python `round()` in several rules. Its final verifier distinguishes missing information from an uncertain answer and checks README/column hints. The present changes keep that distinction with typed values and auditable metadata. Historical rounding, fixed synonym lists, and subjective-question heuristics stay outside the implementation. The historical public run and synthetic CPU fixture measure different inputs.

Lead can run `python -m pytest tests/golden tests/unit/test_scorer.py` for L-10. The shared serializer and scorer changes are ready for Lead review. L-10's other reporting and real-data checks remain with Lead.

## M2-07 decision rule matrix

The existing gate retains its order of decisions. An explicit comparison or baseline reference without a corresponding window is a temporal error before SQL. Zero overlap uses accepted DC-3, including for comparison windows, and respects `decision.zero_coverage`. Unknown or partial overlap is recorded separately.

| Rule | Required evidence | Decision and code | Prior coverage | New direct coverage |
|---|---|---|---|---|
| 1. Pipeline failure | Parse/setup/time error or unresolved explicit comparison | `abstain`, pipeline code or `E_TIME_UNSUPPORTED` | Invalid parser output | Parse error, omitted comparison, no SQL on omitted comparison |
| 2. Unclear frame | Parser reports `unclear` | `abstain`, `D_UNCLEAR` | No direct test | Unclear frame precedence over zero coverage |
| 3. Confirmed absence | All reported missing fields lack evidence in a complete catalog | `unanswerable`, `D_UNANSWERABLE_CONFIRMED` | Missing cost and exact column | Qualified/original labels, mapped README aliases, stale mappings, conflicts, ambiguous fuzzy matches and incomplete catalog |
| 4. No overlap | Any resolved window has zero coverage | `unanswerable` by default, `D_UNANSWERABLE_OUT_OF_RANGE` | Primary and comparison windows | Both policy values, full/partial/zero/unknown comparison coverage |
| 5. No successful result | No typed successful attempt | `abstain`, attempt code or `E_NO_SUCCESS` | SQL failure, NULL scalar and empty SQL | Direct reason codes and execution-state distinctions |
| 6. Wrong type | Typed result differs from expected type | `abstain`, `E_TYPE_CONTRACT` | Invalid SQL result shape | Direct successful-attempt type mismatch |
| 7. Implausible value | Non-finite value or percent beyond the existing bound | `abstain`, `D_IMPLAUSIBLE` | DuckDB division by zero | Direct percent bound and unchanged solver failure handling |
| 8. Valid answer | Successful typed value survives the checks | `answer`, `D_ANSWER` | Computed zero and partial coverage | Zero/nonzero, typed empty list, full/partial/unknown coverage |

Gate tests are in `tests/unit/test_decision_gate.py`, `tests/unit/test_solver_decision.py` and `tests/integration/test_fixture_pipeline.py`. Empty SQL results that the existing solver flags as `E_EMPTY_RESULT` retain their abstain behavior. An already validated empty collection is an answer under the frozen wire shape. NULL scalar results retain `E_EMPTY_RESULT`.

### Catalog and L-14 handoff

The gate uses `BusinessCatalog.tables`, table and column identifiers, `ColumnInfo.original_name`, `readme_text`, catalog warnings and resolved windows. It uses the structured catalog as the source for names also displayed in SchemaCard. An exact folded column or qualified label provides physical evidence. A complete `label: column` or `column: label` README entry supports an alias when its target resolves to the catalog. An explicit README denial that conflicts with a physical column is logged and leaves solving available. Free-text mentions are uncertainty evidence.

The CPU implementation uses reordered tokens or a near-complete single-token spelling as guarded fuzzy candidates for SPEC §7.9. It does not promote the raw 60-point token-set cutoff to proof of availability. Uncertain, conflicting or incomplete evidence keeps the solver path available. Only all-absent claims on a ready, sufficiently populated catalog can trigger the missing-field rule. There is no lookup by question or business ID.

`logs/questions.jsonl` keeps the existing decision kind and reason code. Its feature map adds per-window coverage and comparison references, model claims, evidence status/source and qualified candidate column names, SQL execution state and error code, row count and NULL presence. The percent scale signal is diagnostic only. The feature map does not include raw README excerpts or data rows. Submission shape and reason codes are unchanged.

M1-10 still needs to deliver fact-table coverage, authoritative labels and any approved semantic hints or aliases. The frozen `ColumnInfo` currently has no dedicated alias or semantic-hint field. Integrate those through the approved catalog API when available. L-14 should compare false unanswerables, false answers, abstains and coverage/match errors using the features above. The authorized training answers and L-14 run evidence were unavailable locally. The acceptance check on answerable neighbours of the 70 training unanswerables remains pending. M2-14 can add regressions to the existing matrix once those cases are identified.

## Local verification

Windows Python 3.14.0 was available. The `8a4296f` baseline had 225 passing tests and 2 train-reference skips. After the changes, pytest reported 327 passing tests and the same 2 skips. Ruff passed. The 23 shared goldens include 22 incorrect predictions across 16 cases. The focused scorer/golden run passed 71 tests, and the focused gate/solver/integration run passed 68. Two isolated synthetic fixture runs each produced 13 valid answers. The scorer reported 13/13 and PA 1.0000, and both submissions matched the baseline byte for byte.
