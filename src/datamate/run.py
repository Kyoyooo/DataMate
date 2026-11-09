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
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from datamate.catalog import setup_business
from datamate.config import RunConfig, load_config
from datamate.contracts import (
    CONTRACTS_VERSION,
    BusinessCatalog,
    LogRecord,
    Question,
    SubmissionRecord,
    codes,
)
from datamate.entities import build_entity_index
from datamate.lexicon import nfc
from datamate.llm import ModelClient, ProductionGuardError, make_client
from datamate.prompts import template_sha256
from datamate.rules import load_split
from datamate.runtime import ResultWriter, answer_question
from datamate.semantics import attach_semantics, compile_semantics_sync


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
            valid.append(
                Question(
                    id=qid,
                    business_id=obj["business_id"],
                    question=nfc(obj["question"]),
                    as_of_date=date.fromisoformat(obj["as_of_date"]),
                    line_no=line_no,
                )
            )
        except (KeyError, TypeError, ValueError, ValidationError):
            invalid.append((qid, str(obj.get("business_id", "")), "E_INPUT_INVALID"))
    return valid, invalid, dict(counts)


def _abstain_log(qid: str, business_id: str, reason: str) -> tuple[SubmissionRecord, LogRecord]:
    rec = SubmissionRecord(id=qid, type="abstain")
    log = LogRecord(
        id=qid,
        answer={"type": "abstain"},
        elapsed_ms=0,
        thinking=None,
        code=None,
        output=None,
        business_id=business_id,
        decision={"kind": "abstain", "reason_code": reason, "features": {}},
    )
    return rec, log


def run(
    cfg: RunConfig,
    client: ModelClient,
    data_dir: Path,
    result_dir: Path,
    *,
    dev: bool,
    overrides: list[str],
) -> int:
    t0 = time.monotonic()
    split = load_split(data_dir)
    questions, invalid, counts = load_questions(data_dir / "questions.jsonl")
    errors: list[str] = []
    catalogs: dict[str, BusinessCatalog | None] = {}
    outcome: Counter[str] = Counter()
    reasons: Counter[str] = Counter()

    with ResultWriter(result_dir) as writer:
        for qid, biz, reason in invalid:
            writer.write(*_abstain_log(qid, biz, reason))
            outcome["abstain"] += 1
            reasons[reason] += 1
        by_business: dict[str, list[Question]] = {}
        for q in questions:
            by_business.setdefault(q.business_id, []).append(q)
        for business_id in sorted(by_business):
            biz_dir = data_dir / "data" / business_id
            pipeline_error = None
            entity_index = None
            if not biz_dir.is_dir():
                catalogs[business_id] = None
                pipeline_error = codes.E_INPUT_BUSINESS_MISSING
            else:
                try:
                    catalogs[business_id] = setup_business(biz_dir, business_id, cfg)
                    cat = catalogs[business_id]
                    if cfg.features.compiled_views and cat.status == "ready":
                        semantic = compile_semantics_sync(cat, split, client, cfg=cfg)
                        catalogs[business_id] = cat = attach_semantics(cat, semantic)
                    if cfg.features.entity_linker and cat.status == "ready":
                        entity_index = build_entity_index(cat, cfg.entities)
                except Exception as exc:  # business boundary
                    catalogs[business_id] = None
                    errors.append(f"setup {business_id}: {type(exc).__name__}: {exc}")
            for q in by_business[business_id]:
                record, log = answer_question(
                    q,
                    split,
                    catalogs[business_id],
                    client,
                    cfg,
                    pipeline_error=pipeline_error,
                    entity_index=entity_index,
                )
                writer.write(record, log)
                outcome[
                    record.type if record.type in ("abstain", "unanswerable") else "answer"
                ] += 1
                reasons[log.decision.get("reason_code", "")] += 1
        distinct = len(questions) + len(invalid)
        complete = len(writer.written_ids()) == distinct

    businesses_log = result_dir / "logs" / "businesses.jsonl"
    with open(businesses_log, "w", encoding="utf-8") as fh:
        for business_id, cat in sorted(catalogs.items()):
            row: dict[str, Any] = {"business_id": business_id}
            row.update(cat.model_dump(mode="json") if cat else {"status": "missing_or_failed"})
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    run_record = {
        "contracts_version": CONTRACTS_VERSION,
        "dev_mode": dev,
        "model_backend": cfg.model.backend,
        "overrides": overrides,
        "config": cfg.model_dump(mode="json"),
        "config_sha256": cfg.sha256(),
        "template_sha256": template_sha256(),
        "split": {
            "rulebook_sha256": split.rulebook_sha256,
            "temporal_params": split.temporal.model_dump(mode="json"),
            "warnings": split.warnings,
        },
        "counts": {
            "questions": distinct,
            "written": distinct if complete else None,
            **counts,
            "by_outcome": dict(outcome),
            "by_reason": dict(sorted(reasons.items())),
        },
        "errors": errors,
        "total_ms": int((time.monotonic() - t0) * 1000),
    }
    (result_dir / "logs" / "run.json").write_text(
        json.dumps(run_record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0 if complete else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m datamate.run", description=__doc__.split("\n")[0])
    p.add_argument(
        "--config", type=Path, default=None, help="run config JSON (default: built-in defaults)"
    )
    p.add_argument("--data-dir", type=Path, default=Path("/data"))
    p.add_argument("--result-dir", type=Path, default=Path("/result"))
    p.add_argument("--dev", action="store_true", help="development mode (allows scripted backend)")
    p.add_argument(
        "--set",
        dest="overrides",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="config override, --dev only",
    )
    args = p.parse_args(argv)
    if args.overrides and not args.dev:
        print("error: --set is only accepted with --dev", file=sys.stderr)
        return 2
    # Startup checks: any failure here exits 2 before a single output file is opened.
    try:
        cfg = load_config(args.config, args.overrides)
        client = make_client(cfg.model, dev=args.dev)
        if not (args.data_dir / "questions.jsonl").is_file():
            raise FileNotFoundError(f"{args.data_dir / 'questions.jsonl'} not found")
    except (ProductionGuardError, NotImplementedError, ValidationError, ValueError, OSError) as exc:
        print(f"error: refusing to run: {exc}", file=sys.stderr)
        return 2
    return run(cfg, client, args.data_dir, args.result_dir, dev=args.dev, overrides=args.overrides)


if __name__ == "__main__":
    sys.exit(main())
