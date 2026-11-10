"""Solver attempt loop (SPEC §7.7.4, C7, P1 subset). Owner: M3.

attempt 1: solve → validate JSON → static SQL checks → execute → type contract.
On failure, up to ``solver.max_repairs`` repair turns are appended to the same
conversation with the error code and text. Every attempt is returned (and
logged), successful or not.

Deferred (TASKS M3-05, M3-10, M3-11): context budgeting, few-shot selection,
Python fallback, soft deadlines.
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import ValidationError

from datamate.config import ExecLimits, RunConfig
from datamate.contracts import (
    BusinessCatalog,
    ExecutionResult,
    PythonSolverOutput,
    Question,
    QuestionFrame,
    SolverAttempt,
    SolverOutput,
    SplitContext,
    TimeWindow,
    codes,
)
from datamate.llm import NO_DEADLINE, Deadline, ModelClient
from datamate.prompts import render_repair, render_solve
from datamate.sandbox import run_python, run_sql
from datamate.solver.sql_rules import check_sql
from datamate.solver.typed import to_typed_value

SqlExecutor = Callable[[str, str, ExecLimits], ExecutionResult]
PythonExecutor = Callable[[str, str, ExecLimits], ExecutionResult]
FALLBACK_TEMPLATE = "solve.python.v1"
# Failures that say "the data has no answer", not "the code was wrong": never sent to the fallback.
_NO_FALLBACK = (codes.E_EMPTY_RESULT, codes.D_IMPLAUSIBLE, codes.E_SQL_TIMEOUT, codes.E_EXEC_CRASH)
SOLVE_TEMPLATE = "solve.sql.v1"
REPAIR_TEMPLATE = "repair.sql.v1"


def solve(q: Question, frame: QuestionFrame, windows: list[TimeWindow], cat: BusinessCatalog,
          split: SplitContext, client: ModelClient, cfg: RunConfig,
          deadline: Deadline = NO_DEADLINE,
          executor: SqlExecutor | None = None,
          examples: list[str] | None = None,
          python_executor: PythonExecutor | None = None) -> list[SolverAttempt]:
    attempts: list[SolverAttempt] = []
    v2 = cfg.solver.template_version == "v2"
    solve_id, repair_id = ("solve.sql.v2", "repair.sql.v2") if v2 else (SOLVE_TEMPLATE, REPAIR_TEMPLATE)
    messages = render_solve(q, frame, windows, split, cat, solve_id, examples)
    stage, template = "solve", solve_id
    for attempt_no in range(1, cfg.solver.max_repairs + 2):
        if deadline.hard_expired:  # hard deadline / global stop: the pipeline abstains (E_DEADLINE)
            break
        remaining = deadline.remaining_s()
        call = client.complete(
            stage=stage, template_id=template, messages=messages,
            json_schema=SolverOutput.model_json_schema(),
            max_tokens=cfg.model.max_tokens[stage], call_id=f"{q.id}:{stage}:{attempt_no}",
            timeout_s=None if remaining == float("inf") else remaining,
        )
        output = execution = value = None
        error_code: str | None
        error_text: str | None = None
        if call.error:
            error_code = call.error
        else:
            try:
                output = SolverOutput.model_validate_json(call.content)
            except ValidationError as exc:
                error_code, error_text = codes.E_SOLVER_OUTPUT_INVALID, str(exc)[:500]
            else:
                error_code, error_text = check_sql(output.sql)
                if error_code is None:
                    execution = (executor or run_sql)(cat.db_path, output.sql, cfg.exec_limits)
                    if execution.ok:
                        value, error_code = to_typed_value(frame, execution)
                    else:
                        error_code, error_text = execution.error_code, execution.error_text
        ok = error_code is None
        attempts.append(SolverAttempt(
            attempt_no=attempt_no, stage=stage, model_call=call, solver_output=output,
            execution=execution, ok=ok, error_code=error_code, value=value,
        ))
        # Model/transport errors, empty results, and non-finite values are not
        # repaired: they are signals about the data, not about SQL syntax.
        if ok or call.error or error_code in (codes.E_EMPTY_RESULT, codes.D_IMPLAUSIBLE):
            break
        if deadline.soft_expired or deadline.degrade:
            break  # soft deadline / degrade mode (SPEC §7.12): no new repair starts
        messages = render_repair(messages, call.content, error_code, error_text, repair_id)
        stage, template = "repair", repair_id
    if (cfg.solver.python_fallback and attempts and not attempts[-1].ok
            and not attempts[-1].model_call.error and attempts[-1].error_code not in _NO_FALLBACK
            and not deadline.hard_expired and not deadline.soft_expired and not deadline.degrade):
        attempts.append(_fallback(q, frame, windows, cat, split, client, cfg, deadline,
                                  python_executor, len(attempts) + 1))
    return attempts


def _fallback(q: Question, frame: QuestionFrame, windows: list[TimeWindow], cat: BusinessCatalog,
              split: SplitContext, client: ModelClient, cfg: RunConfig, deadline: Deadline,
              python_executor: PythonExecutor | None, attempt_no: int) -> SolverAttempt:
    """One python attempt (SPEC §7.7.4, P2). No repair turn."""
    remaining = deadline.remaining_s()
    call = client.complete(
        stage="fallback", template_id=FALLBACK_TEMPLATE,
        messages=render_solve(q, frame, windows, split, cat, FALLBACK_TEMPLATE),
        json_schema=PythonSolverOutput.model_json_schema(), max_tokens=cfg.model.max_tokens["fallback"],
        call_id=f"{q.id}:fallback:{attempt_no}",
        timeout_s=None if remaining == float("inf") else remaining)
    output = execution = value = None
    if call.error:
        error_code: str | None = call.error
    else:
        try:
            output = PythonSolverOutput.model_validate_json(call.content)
        except ValidationError:
            error_code = codes.E_SOLVER_OUTPUT_INVALID
        else:
            execution = (python_executor or run_python)(cat.db_path, output.python, cfg.exec_limits)
            if execution.ok:
                value, error_code = to_typed_value(frame, execution)
            else:
                error_code = execution.error_code
    return SolverAttempt(attempt_no=attempt_no, stage="fallback", model_call=call, python_output=output,
                         execution=execution, ok=error_code is None, error_code=error_code, value=value)
