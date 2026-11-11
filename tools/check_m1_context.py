"""Check every training question against runtime contracts and SchemaCard budgets.

Does not read answers or call a model. Use --tokenizer-dir for production evidence;
--estimate is explicitly development-only and is never accuracy certification.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from datamate.catalog import to_runtime_catalog
from datamate.catalog.context import SchemaContextOverflow, select_schema_context
from datamate.catalog.models import IngestionCatalog
from datamate.config import RunConfig
from datamate.contracts import CONTRACTS_VERSION, BusinessCatalog
from datamate.llm.tokenizer import CharEstimateTokenizer, load_tokenizer


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-dir", type=Path, required=True)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--tokenizer-dir")
    group.add_argument("--estimate", action="store_true")
    args = parser.parse_args()
    tok = CharEstimateTokenizer() if args.estimate else load_tokenizer(args.tokenizer_dir)
    if tok is None:
        parser.error("local tokenizer could not be loaded")
    catalogs, lengths = {}, {}
    for path in sorted((args.audit_dir / "catalogs").glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        record.pop("readme_audit", None)
        rich = IngestionCatalog.model_validate_json(json.dumps(record, ensure_ascii=False))
        cat = to_runtime_catalog(rich)
        # Independently exercise the public consumer JSON boundary.
        cat = BusinessCatalog.model_validate_json(cat.model_dump_json())
        catalogs[cat.business_id] = cat
        lengths[cat.business_id] = {
            "full_characters": len(cat.schema_card),
            "max_tokens": 0,
            "questions": 0,
            "reductions": 0,
        }
    failures = []
    cfg = RunConfig()
    for line in args.questions.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        question = json.loads(line)
        cat = catalogs[question["business_id"]]
        result = lengths[cat.business_id]
        result["questions"] += 1
        try:
            text = select_schema_context(cat, question["question"], tok, cfg)
            count = len(tok.encode(text, add_special_tokens=False))
            if count > cfg.solver.schema_card_budget_tokens:
                raise ValueError("budget was not enforced")
            result["max_tokens"] = max(result["max_tokens"], count)
            result["reductions"] += text != cat.schema_card
        except (SchemaContextOverflow, ValueError) as exc:
            failures.append({"id": question["id"], "error": str(exc)})
    report = {
        "contracts_version": CONTRACTS_VERSION,
        "tokenizer": tok.name,
        "production_tokenizer_verified": not args.estimate,
        "schema_budget_tokens": cfg.solver.schema_card_budget_tokens,
        "businesses": lengths,
        "questions": sum(row["questions"] for row in lengths.values()),
        "failures": failures,
        "valid": bool(lengths) and not failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "businesses"}))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
