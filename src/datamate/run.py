"""Entry point: ``python -m datamate.run`` (SPEC §2, §7.0). Owner: M4.

Production (no ``--dev``): no overrides, and development-only components (the
scripted model client) are rejected. Components that are not implemented yet
fail before any output file is opened, so no plausible-looking submission is
ever produced by placeholder code.

Development (``--dev``): ``--set key=value`` overrides are allowed and the
scripted backend may be used. run.json records ``dev_mode`` and the backend.

Exit codes: 0 = one submission line per distinct question id and run.json
written; 1 = incomplete output; 2 = refused to start (configuration or a
missing production component).

BOOTSTRAP SCOPE: questions run sequentially in one process. Replica serving,
concurrency, deadlines, and degrade mode are TASKS M4-03/M4-05.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from datamate.catalog import setup_business
from datamate.catalog.context import build_context
from datamate.config import RunConfig, load_config
from datamate.contracts import (
    CONTRACTS_VERSION,
    BusinessCatalog,
    LogRecord,
    Question,
    SubmissionRecord,
    codes,
)
from datamate.lexicon import nfc
from datamate.llm import ModelClient, ProductionGuardError, make_client
from datamate.llm.tokenizer import CharEstimateTokenizer, load_tokenizer
from datamate.prompts import template_sha256
from datamate.prompts.budget import ContextBuilder
from datamate.rules import load_split
from datamate.runtime import Orchestrator, ResultWriter
from datamate.runtime.environment import fingerprint, model_record
from datamate.runtime.orchestrator import ReplicaSupervisor
from datamate.runtime.promptstore import PromptBlobStore
from datamate.sandbox import SandboxPool
from datamate.solver import FewshotBank
from datamate.solver.solve import SqlExecutor


def load_questions(path: Path) -> tuple[list[Question], list[tuple[str, str, str]], dict[str, int]]:
    """Return (valid questions, invalid (id, business_id, reason) rows, counters)."""
    counts: Counter[str] = Counter()
    seen: set[str] = set()
    valid: list[Question] = []
    invalid: list[tuple[str, str, str]] = []
    text = path.read_bytes().decode("utf-8-sig")
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            counts["skipped_invalid_json"] += 1
            continue
        qid = obj.get("id") if isinstance(obj, dict) else None
        if not isinstance(qid, str) or not qid:
            counts["skipped_missing_id"] += 1
            continue
        if qid in seen:
            counts["ignored_duplicate_id"] += 1
            continue
        seen.add(qid)
        try:
            valid.append(Question(
                id=qid, business_id=obj["business_id"], question=nfc(obj["question"]),
                as_of_date=date.fromisoformat(obj["as_of_date"]), line_no=line_no))
        except (KeyError, TypeError, ValueError, ValidationError):
            invalid.append((qid, str(obj.get("business_id", "")), codes.E_INPUT_INVALID))
    return valid, invalid, dict(counts)


def _abstain_log(qid: str, business_id: str, reason: str) -> tuple[SubmissionRecord, LogRecord]:
    rec = SubmissionRecord(id=qid, type="abstain")
    log = LogRecord(id=qid, answer={"type": "abstain"}, elapsed_ms=0, thinking=None, code=None,
                    output=None, business_id=business_id,
                    decision={"kind": "abstain", "reason_code": reason, "features": {}})
    return rec, log


def run(cfg: RunConfig, client: ModelClient | Sequence[ModelClient], data_dir: Path,
        result_dir: Path, *, dev: bool, overrides: list[str], extract_temporal: bool = False,
        supervisor: ReplicaSupervisor | None = None, context: ContextBuilder | None = None,
        executor: SqlExecutor | None = None, fewshot_bank: FewshotBank | None = None,
        python_executor: SqlExecutor | None = None,
        serving_record: Callable[[], dict[str, Any]] | None = None,
        started_at: float | None = None) -> int:
    """Run the whole split. ``client`` is one client per replica (a single client = one replica).

    An empty client list means the model servers could not be started: every question is
    written as ``abstain`` (E_REPLICA_DOWN) so the submission is still complete.
    """
    # The global stop counts from process start when main() passes ``started_at``: model loading
    # counts toward the organizers' 6 hours (DG §3.3), so it must count toward our budget too.
    t0 = time.monotonic() if started_at is None else started_at
    clients = list(client) if isinstance(client, (list, tuple)) else [client]
    split = load_split(data_dir, client=clients[0] if extract_temporal and clients else None,
                       max_tokens=cfg.model.max_tokens.get("rule_profile"))
    questions, invalid, counts = load_questions(data_dir / "questions.jsonl")
    outcome: Counter[str] = Counter()
    reasons: Counter[str] = Counter()

    def setup(business_id: str) -> tuple[BusinessCatalog | None, str | None]:
        biz_dir = data_dir / "data" / business_id
        if not biz_dir.is_dir():
            return None, codes.E_INPUT_BUSINESS_MISSING
        return setup_business(biz_dir, business_id, cfg), None

    with ResultWriter(result_dir) as writer:
        for qid, biz, reason in invalid:
            writer.write(*_abstain_log(qid, biz, reason))
            outcome["abstain"] += 1
            reasons[reason] += 1
        blobs = PromptBlobStore(result_dir / "logs" / "prompt_blobs.jsonl")
        split_calls = [blobs.compact(c).model_dump(mode="json") for c in split.rule_profile_calls]
        orch = Orchestrator(cfg=cfg, split=split, questions=questions, clients=clients,
                            writer=writer, setup=setup, supervisor=supervisor, t0=t0,
                            progress_log=result_dir / "logs" / "progress.log", blobs=blobs,
                            context=context, executor=executor, fewshot_bank=fewshot_bank,
                            python_executor=python_executor)
        previous = _install_sigterm(orch.request_stop)
        try:
            stats = orch.run()
        finally:
            _restore_sigterm(previous)
        # Canonical order: rows rejected at input first (file order), then questions by line.
        blobs.finalize()
        writer.finalize_canonical([r[0] for r in invalid]
                                  + [q.id for q in sorted(questions, key=lambda q: q.line_no)])
        distinct = len(questions) + len(invalid)
        complete = len(writer.written_ids()) == distinct
    outcome.update(stats.outcome)
    reasons.update(stats.reasons)

    businesses_log = result_dir / "logs" / "businesses.jsonl"
    with open(businesses_log, "w", encoding="utf-8") as fh:
        for business_id in sorted({q.business_id for q in questions}):
            cat = stats.catalogs.get(business_id)
            row: dict[str, Any] = {"business_id": business_id}
            row.update(cat.model_dump(mode="json") if cat else {"status": "missing_or_failed"})
            row["setup_ms"] = stats.setup_ms.get(business_id)
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    run_record = {
        "contracts_version": CONTRACTS_VERSION,
        "dev_mode": dev,
        "model_backend": cfg.model.backend,
        "overrides": overrides,
        "config": cfg.model_dump(mode="json"),
        "config_sha256": cfg.sha256(),
        "template_sha256": template_sha256(),
        "split": {"rulebook_sha256": split.rulebook_sha256,
                  "temporal_params": split.temporal.model_dump(mode="json"),
                  "temporal_diagnostics": split.temporal_diagnostics,
                  "calls": split_calls,
                  "calendar_ok": split.calendar_ok,
                  "calendar_diagnostic": (split.calendar_diagnostic.model_dump(mode="json")
                                          if split.calendar_diagnostic else None),
                  "warnings": split.warnings},
        "model": model_record(cfg.model.path, cfg.model.served_model_name, cfg.model.backend,
                              cfg.model.revision),
        "environment": fingerprint(),
        "context_budget": ({"tokenizer": context.tok.name, **cfg.solver.model_dump(mode="json")}
                           if context else None),
        "replica_assignment": dict(sorted(stats.assignment.items())),
        "replicas": serving_record() if serving_record else None,
        "orchestrator": {"stop_reason": stats.stop_reason,
                         "degrade_activated_ms": stats.degrade_activated_ms,
                         "questions_per_replica": stats.questions_per_replica,
                         "setup_ms": dict(sorted(stats.setup_ms.items()))},
        "counts": {"questions": distinct, "written": distinct if complete else None,
                   **counts, "by_outcome": dict(outcome), "by_reason": dict(sorted(reasons.items()))},
        "errors": stats.errors,
        "timings": {"replica_load_ms": (serving_record() or {}).get("replica_load_ms")
                    if serving_record else None,
                    "first_answer_ms": stats.first_answer_ms,
                    "total_ms": int((time.monotonic() - t0) * 1000)},
        "degrade_activated_ms": stats.degrade_activated_ms,
        "total_ms": int((time.monotonic() - t0) * 1000),
    }
    (result_dir / "logs" / "run.json").write_text(
        json.dumps(run_record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if complete else 1


def _context_builder(cfg: RunConfig) -> ContextBuilder:
    """Token budgeting needs the shipped model's tokenizer; absent in production → exit 2."""
    if cfg.solver.tokenizer == "estimate":
        return build_context(CharEstimateTokenizer(), cfg)
    tok = load_tokenizer(cfg.model.path)
    if tok is None:
        raise ValueError(f"cannot load the tokenizer from model.path {cfg.model.path!r} "
                         "(transformers and local tokenizer files are required; "
                         "solver.tokenizer='estimate' is development-only)")
    return build_context(tok, cfg)


def _install_sigterm(handler: Callable[[], None]) -> Any:
    try:
        return signal.signal(signal.SIGTERM, lambda *_: handler())
    except ValueError:  # not the main thread (tests): no handler
        return None


def _restore_sigterm(previous: Any) -> None:
    if previous is not None:
        signal.signal(signal.SIGTERM, previous)


def main(argv: list[str] | None = None) -> int:
    started_at = time.monotonic()
    p = argparse.ArgumentParser(prog="python -m datamate.run", description=__doc__.split("\n")[0])
    p.add_argument("--config", type=Path, default=None, help="run config JSON (default: built-in defaults)")
    p.add_argument("--data-dir", type=Path, default=Path("/data"))
    p.add_argument("--result-dir", type=Path, default=Path("/result"))
    p.add_argument("--dev", action="store_true", help="development mode (allows scripted backend)")
    p.add_argument("--set", dest="overrides", action="append", default=[], metavar="KEY=VALUE",
                   help="config override, --dev only")
    args = p.parse_args(argv)
    if args.overrides and not args.dev:
        print("error: --set is only accepted with --dev", file=sys.stderr)
        return 2
    # Startup checks: any failure here exits 2 before a single output file is opened.
    try:
        cfg = load_config(args.config, args.overrides)
        managed = cfg.serving.mode == "managed"
        if managed and (not cfg.model.path or not Path(cfg.model.path).is_dir()):
            raise FileNotFoundError(f"model.path {cfg.model.path!r} is not a directory")
        # External serving builds its client now so a missing base_url fails before any output.
        clients = [] if managed else [make_client(cfg.model, dev=args.dev)]
        if managed and cfg.model.backend != "http":
            raise ValueError("serving.mode='managed' requires model.backend='http'")
        if not (args.data_dir / "questions.jsonl").is_file():
            raise FileNotFoundError(f"{args.data_dir / 'questions.jsonl'} not found")
        context = _context_builder(cfg)
        bank = (FewshotBank.from_file(cfg.solver.fewshot_bank_path)
                if cfg.solver.fewshot_bank_path else None)
    except (ProductionGuardError, NotImplementedError, ValidationError, ValueError, OSError) as exc:
        print(f"error: refusing to run: {exc}", file=sys.stderr)
        return 2
    pool = (SandboxPool(cfg.exec_limits.workers, cfg.exec_limits)
            if cfg.exec_limits.isolation == "process" else None)
    executor = pool.run_sql if pool else None
    py_executor = pool.run_python if pool else None
    try:
        if not managed:
            return run(cfg, clients, args.data_dir, args.result_dir, dev=args.dev,
                       overrides=args.overrides, context=context, executor=executor,
                       fewshot_bank=bank, python_executor=py_executor, started_at=started_at)
        from datamate.llm.replicas import ReplicaError, ReplicaManager

        manager = ReplicaManager(cfg, args.result_dir / "logs")
        try:
            try:
                manager.start()
                clients = [make_client(c, dev=args.dev) for c in manager.client_configs()]
            except ReplicaError as exc:
                # Serving failed at run time: still deliver a complete (all-abstain) submission.
                print(f"error: model servers unavailable: {exc}", file=sys.stderr)
                clients = []
            return run(cfg, clients, args.data_dir, args.result_dir, dev=args.dev,
                       overrides=args.overrides, supervisor=manager if clients else None,
                       serving_record=manager.record, context=context, executor=executor,
                       fewshot_bank=bank, python_executor=py_executor, started_at=started_at)
        finally:
            manager.stop()
    finally:
        if pool is not None:
            pool.close()


if __name__ == "__main__":
    sys.exit(main())
