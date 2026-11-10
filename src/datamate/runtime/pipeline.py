"""Per-question pipeline (SPEC §7.12 step 5). Owner: M4.

parse → resolve windows → (pre-solve decision) → solve/execute → decide →
format → (SubmissionRecord, LogRecord). Any exception is caught at the
question boundary and becomes ``abstain`` with E_INTERNAL; the traceback is
kept in the log record's decision field.
"""

from __future__ import annotations

import time
import traceback
from typing import Any

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
from datamate.formatting import to_submission
from datamate.llm import NO_DEADLINE, Deadline, DeadlineExceeded, ModelClient
from datamate.parse import parse_question
from datamate.prompts.budget import ContextBuilder, ContextOverflow
from datamate.runtime.promptstore import PromptBlobStore
from datamate.solver import solve
from datamate.solver.solve import SqlExecutor
from datamate.temporal import resolve_windows


def _execution_fields(attempts: list[SolverAttempt], max_rows: int) -> tuple[Any, Any]:
    executed = [a.execution for a in attempts if a.execution is not None]
    if not executed:
        return None, None
    code: str | list[str] = executed[0].code if len(executed) == 1 else [e.code for e in executed]
    final = next((a.execution for a in reversed(attempts) if a.ok and a.execution), executed[-1])
    if final.ok:
        output: Any = {"columns": final.columns, "rows": final.rows[:max_rows],
                       "row_count": final.row_count, "truncated": final.truncated}
    else:
        output = final.error_text
    return code, output


def _thinking(calls: list[ModelCall]) -> list[str] | None:
    """SPEC SC-7: None if no call produced reasoning; else one entry per call, in order."""
    if all(c.reasoning is None for c in calls):
        return None
    return [c.reasoning or "" for c in calls]


def answer_question(q: Question, split: SplitContext, cat: BusinessCatalog | None,
                    client: ModelClient, cfg: RunConfig,
                    pipeline_error: str | None = None,
                    deadline: Deadline = NO_DEADLINE,
                    blobs: PromptBlobStore | None = None,
                    context: ContextBuilder | None = None,
                    executor: SqlExecutor | None = None) -> tuple[SubmissionRecord, LogRecord]:
    started = time.monotonic()
    calls: list[ModelCall] = []
    attempts: list[SolverAttempt] = []
    windows: list[TimeWindow] = []
    frame: QuestionFrame | None = None
    error_detail: str | None = None
    context_log: dict[str, Any] | None = None
    prompt_cat = cat  # the catalog as shown to the model (budgeted README / SchemaCard)
    try:
        if pipeline_error is None and (cat is None or cat.status != "ready"):
            pipeline_error = codes.E_BUSINESS_SETUP
        if pipeline_error is None and context is not None:
            try:
                plan = context.plan(q, split, cat)
                prompt_cat = plan.catalog
                context_log = {"tokens": plan.total_tokens, "reductions": plan.reductions,
                               "tokenizer": plan.tokenizer}
            except ContextOverflow as exc:
                pipeline_error = codes.E_CONTEXT_OVERFLOW
                context_log = {"overflow": str(exc)}
        if pipeline_error is None:
            frame, call, pipeline_error = parse_question(q, split, prompt_cat, client, cfg,
                                                         deadline)
            calls.append(call)
        if pipeline_error is None:
            windows, pipeline_error = resolve_windows(frame.time, q.as_of_date, split.temporal,
                                                      cat.data_range)
        if pipeline_error is None and pre_solve_decision(frame, windows, cat, cfg) is None:
            attempts = solve(q, frame, windows, prompt_cat, split, client, cfg, deadline, executor)
            calls.extend(a.model_call for a in attempts)
        decision = decide(frame, windows, attempts, cat, cfg, pipeline_error)
        if deadline.hard_expired and decision.kind != "answer":
            raise DeadlineExceeded  # out of time: report E_DEADLINE / E_GLOBAL_STOP, not a guess
        record = to_submission(q.id, decision, frame.ranking if frame else None, cfg.formatting)
    except DeadlineExceeded:
        decision = Decision(kind="abstain", reason_code=getattr(
            deadline, "stop_reason_code", codes.E_DEADLINE))
        record = SubmissionRecord(id=q.id, type="abstain")
    except Exception:  # question boundary: never let one question stop the run
        error_detail = traceback.format_exc(limit=20)
        decision = Decision(kind="abstain", reason_code=codes.E_INTERNAL)
        record = SubmissionRecord(id=q.id, type="abstain")

    code, output = _execution_fields(attempts, cfg.logging.max_output_rows_logged)
    wire = record.to_wire()
    wire.pop("id")
    decision_log: dict[str, Any] = {"kind": decision.kind, "reason_code": decision.reason_code,
                                    "features": decision.features}
    if error_detail:
        decision_log["error"] = error_detail
    if context_log:
        decision_log["context"] = context_log
    log = LogRecord(
        id=q.id,
        answer=wire,
        elapsed_ms=int((time.monotonic() - started) * 1000),
        thinking=_thinking(calls),
        code=code,
        output=output,
        business_id=q.business_id,
        calls=[blobs.compact(c) for c in calls] if blobs else calls,
        degrade=deadline.degrade,
        attempts=[{"attempt_no": a.attempt_no, "stage": a.stage, "ok": a.ok,
                   "error_code": a.error_code,
                   "duration_ms": a.execution.duration_ms if a.execution else None}
                  for a in attempts],
        windows=windows,
        decision=decision_log,
    )
    return record, log
