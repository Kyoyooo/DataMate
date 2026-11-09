"""Training-only evidence for M1-01/M1-14. Never used by inference."""

from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path

from datamate.catalog.build import setup_business
from datamate.config import RunConfig
from datamate.lexicon import fold
from datamate.preprocessing.common import inventory_files, verify_inventory, write_json
from datamate.preprocessing.qa import load_questions


def readme_observations(catalog) -> dict:
    text = catalog.readme_text or ""
    headers = sorted({column.original_name for table in catalog.tables for column in table.columns})
    folded = fold(text)
    mentioned = [header for header in headers if fold(header) in folded]
    return {
        "characters": len(text),
        "declared_column_bullets": text.count("**") // 2,
        "unique_headers": len(headers),
        "headers_mentioned_exactly_after_fold": len(mentioned),
        "headers_not_mentioned": [header for header in headers if header not in mentioned],
        "quality_band_heuristic": "absent"
        if not text
        else "contains_dictionary"
        if text.count("**") >= 4
        else "sparse_notes",
        "quality_policy": "Structural observations, not a claim that business definitions are complete",
    }


def audit_training(
    split_dir: Path, output_dir: Path, *, role: str, limit: int | None = None
) -> dict:
    """The caller must explicitly declare training provenance; no label-derived parser policies."""
    if role != "train":
        raise ValueError(
            "M1 audit accepts training only; test splits must never drive training or tuning"
        )
    source, output = split_dir.resolve(), output_dir.resolve()
    if output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError("Training and report directories must be separate")
    output.mkdir(parents=True, exist_ok=True)
    questions, rejected, counts = load_questions(source)
    businesses = sorted({q["business_id"] for q in questions})
    selected = businesses[:limit] if limit else businesses
    paths = [
        source / "questions.jsonl",
        source / "answers.jsonl",
        source / "rulebook.md",
        source / "calendar.csv",
    ]
    paths += [
        p for business in selected for p in (source / "data" / business).rglob("*") if p.is_file()
    ]
    inventory = inventory_files(source, paths)
    write_json(output / "source_inventory.json", inventory)
    cfg = RunConfig(work_dir=str(output / "work"))
    results, warnings = [], Counter()
    started = time.monotonic()
    for index, business in enumerate(selected, 1):
        catalog = setup_business(source / "data" / business, business, cfg)
        record = catalog.model_dump(mode="json")
        record["readme_audit"] = readme_observations(catalog)
        results.append(record)
        warnings.update(w.code for w in catalog.warnings)
        write_json(output / "catalogs" / f"{catalog.bkey}.json", record)
        print(
            json.dumps(
                {
                    "business": business,
                    "index": index,
                    "total": len(selected),
                    "status": catalog.status,
                    "tables": len(catalog.tables),
                    "rows": sum(t.row_count for t in catalog.tables),
                    "setup_ms": catalog.setup_ms,
                }
            ),
            flush=True,
        )
    unchanged = verify_inventory(source, inventory)
    failures = [c["business_id"] for c in results if c["status"] != "ready"]
    report = {
        "source": str(source),
        "source_role": role,
        "businesses_total": len(businesses),
        "businesses_processed": len(results),
        "questions": len(questions),
        "rejected_questions": rejected,
        "question_counters": counts,
        "full_run": len(selected) == len(businesses),
        "setup_failures": failures,
        "warning_counts": dict(sorted(warnings.items())),
        "files_by_extension": dict(Counter(Path(p["path"]).suffix.lower() for p in inventory)),
        "input_unchanged": unchanged,
        "elapsed_s": round(time.monotonic() - started, 3),
        "tables": sum(len(c["tables"]) for c in results),
        "rows": sum(t["row_count"] for c in results for t in c["tables"]),
        "valid": bool(results)
        and not failures
        and not rejected
        and unchanged["valid"]
        and len(selected) == len(businesses),
    }
    write_json(output / "training_audit.json", report)
    text = "# M1 training ingestion audit\n\n" + "\n".join(
        f"- {key}: `{json.dumps(value, ensure_ascii=False)}`" for key, value in report.items()
    )
    text += (
        "\n\nPer-business schema, formats, README observations and warnings are in `catalogs/`.\n"
    )
    (output / "TRAINING_AUDIT.md").write_text(text, encoding="utf-8")
    return report
