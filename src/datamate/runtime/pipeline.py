"""Per-question pipeline (SPEC §7.12 step 5). Owner: M4.

parse → resolve windows → (pre-solve decision) → solve/execute → decide →
format → (SubmissionRecord, LogRecord). Any exception is caught at the
question boundary and becomes ``abstain`` with E_INTERNAL; the traceback is
kept in the log record's decision field.
"""

from __future__ import annotations

import hashlib
import time
import traceback
from typing import Any

from datamate.catalog import SchemaContextOverflow, select_schema_context
from datamate.config import RunConfig
from datamate.contracts import (
    BusinessCatalog,
    Decision,
    LogRecord,
    ModelCall,
    Question,
    QuestionFrame,
    SolverAttempt,
    SplitContext,
    SubmissionRecord,
    TimeWindow,
    codes,
)
from datamate.decision import decide, pre_solve_decision
from datamate.entities import EntityIndex, build_entity_index
from datamate.formatting import to_submission
from datamate.ingest import referenced_tables
from datamate.llm import ModelClient
from datamate.parse import parse_question
from datamate.solver import solve
from datamate.temporal import resolve_windows


def _execution_fields(attempts: list[SolverAttempt], max_rows: int) -> tuple[Any, Any]:
    executed = [a.execution for a in attempts if a.execution is not None]
    if not executed:
        return None, None
    code: str | list[str] = executed[0].code if len(executed) == 1 else [e.code for e in executed]
    final = next((a.execution for a in reversed(attempts) if a.ok and a.execution), executed[-1])
    if final.ok:
        output: Any = {
            "columns": final.columns,
            "rows": final.rows[:max_rows],
            "row_count": final.row_count,
            "truncated": final.truncated,
        }
    else:
        output = final.error_text
    return code, output


def _thinking(calls: list[ModelCall]) -> list[str] | None:
    """SPEC SC-7: None if no call produced reasoning; else one entry per call, in order."""
    if all(c.reasoning is None for c in calls):
        return None
    return [c.reasoning or "" for c in calls]


def answer_question(
    q: Question,
    split: SplitContext,
    cat: BusinessCatalog | None,
    client: ModelClient,
    cfg: RunConfig,
    pipeline_error: str | None = None,
    *,
    entity_index: EntityIndex | None = None,
    tokenizer=None,
) -> tuple[SubmissionRecord, LogRecord]:
    started = time.monotonic()
    calls: list[ModelCall] = []
    attempts: list[SolverAttempt] = []
    windows: list[TimeWindow] = []
    frame: QuestionFrame | None = None
    error_detail: str | None = None
    entities = []
    schema_card = None
    try:
        if pipeline_error is None and (cat is None or cat.status != "ready"):
            pipeline_error = codes.E_BUSINESS_SETUP
        if pipeline_error is None:
            schema_card = select_schema_context(cat, q.question, tokenizer, cfg)
            context_catalog = cat.model_copy(update={"schema_card": schema_card})
            frame, call, pipeline_error = parse_question(q, split, context_catalog, client, cfg)
            calls.append(call)
        if pipeline_error is None and cfg.features.entity_linker:
            index = (
                entity_index if entity_index is not None else build_entity_index(cat, cfg.entities)
            )
            entities = [
                candidate
                for mention in frame.mentions
                for candidate in index.query(mention, cfg.entities)
            ]
        if pipeline_error is None:
            windows, pipeline_error = resolve_windows(
                frame.time, q.as_of_date, split.temporal, cat.data_range
            )
        if pipeline_error is None and pre_solve_decision(frame, windows, cat, cfg) is None:
            attempts = solve(q, frame, windows, context_catalog, split, client, cfg)
            calls.extend(a.model_call for a in attempts)
        decision = decide(frame, windows, attempts, cat, cfg, pipeline_error)
        record = to_submission(q.id, decision, frame.ranking if frame else None, cfg.formatting)
    except SchemaContextOverflow:
        decision = Decision(kind="abstain", reason_code=codes.E_CONTEXT_OVERFLOW)
        record = SubmissionRecord(id=q.id, type="abstain")
    except Exception:  # question boundary: never let one question stop the run
        error_detail = traceback.format_exc(limit=20)
        decision = Decision(kind="abstain", reason_code=codes.E_INTERNAL)
        record = SubmissionRecord(id=q.id, type="abstain")

    code, output = _execution_fields(attempts, cfg.logging.max_output_rows_logged)
    wire = record.to_wire()
    wire.pop("id")
    decision_log: dict[str, Any] = {
        "kind": decision.kind,
        "reason_code": decision.reason_code,
        "features": decision.features,
    }
    if error_detail:
        decision_log["error"] = error_detail
    views_used = []
    if cat is not None and any(view.enabled for view in cat.views):
        import duckdb

        referenced = set()
        for attempt in attempts:
            if attempt.execution is not None:
                try:
                    referenced.update(referenced_tables(attempt.execution.code))
                except duckdb.Error:
                    pass
        views_used = [
            {"name": v.name, "ddl_sha256": hashlib.sha256(v.ddl.encode()).hexdigest()}
            for v in cat.views
            if v.enabled and v.name in referenced
        ]
    log = LogRecord(
        id=q.id,
        answer=wire,
        elapsed_ms=int((time.monotonic() - started) * 1000),
        thinking=_thinking(calls),
        code=code,
        output=output,
        business_id=q.business_id,
        calls=calls,
        attempts=[
            {
                "attempt_no": a.attempt_no,
                "stage": a.stage,
                "ok": a.ok,
                "error_code": a.error_code,
                "duration_ms": a.execution.duration_ms if a.execution else None,
            }
            for a in attempts
        ],
        windows=windows,
        decision=decision_log,
        entities=entities,
        views_used=views_used,
    )
    return record, log
