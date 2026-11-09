"""Questions for inference; reference answers in a separate training-only branch."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from .common import (
    component_run,
    finish_component,
    implementation_digest,
    inventory_files,
    nfc_text,
    safe_business_dir,
    verify_inventory,
    write_json,
    write_jsonl,
)


def load_questions(split_dir: Path) -> tuple[list[dict], list[dict], dict]:
    questions, rejected, seen, counters = [], [], set(), {}
    for line_no, line in enumerate(
        (split_dir / "questions.jsonl").read_text(encoding="utf-8-sig").splitlines(), 1
    ):
        if not line.strip():
            continue
        row = None
        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("Question must be an object")
            qid = row.get("id")
            if not isinstance(qid, str) or not qid.strip():
                raise ValueError("Missing question id")
            if qid in seen:
                counters["ignored_duplicate_id"] = counters.get("ignored_duplicate_id", 0) + 1
                continue
            seen.add(qid)
            if not isinstance(row.get("question"), str) or not row["question"].strip():
                raise ValueError("Missing question text")
            business = safe_business_dir(split_dir, row.get("business_id"))
            if not isinstance(row.get("as_of_date"), str) or not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}", row["as_of_date"]
            ):
                raise ValueError("as_of_date must be YYYY-MM-DD")
            date.fromisoformat(row["as_of_date"])
            if not business.is_dir():
                raise FileNotFoundError("E_INPUT_BUSINESS_MISSING")
            questions.append(
                {
                    "id": qid,
                    "business_id": row["business_id"],
                    "question": nfc_text(row["question"]),
                    "as_of_date": row["as_of_date"],
                    "line_no": line_no,
                }
            )
        except (ValueError, TypeError, KeyError, OSError) as error:
            rejected.append(
                {
                    "line_no": line_no,
                    "id": row.get("id") if isinstance(row, dict) else None,
                    "reason": str(error),
                    "raw_line": line,
                }
            )
    return questions, rejected, counters


def numeric_answer(value) -> bool:
    return (
        isinstance(value, (int, Decimal))
        and not isinstance(value, bool)
        and Decimal(value).is_finite()
    )


def validate_answer(row: dict) -> list[str]:
    kind, value, issues = row.get("type"), row.get("answer"), []
    if not isinstance(row.get("id"), str) or not row["id"]:
        issues.append("Missing answer id")
    if kind in {"number", "percent"}:
        valid = numeric_answer(value)
    elif kind == "string":
        valid = isinstance(value, str)
    elif kind == "boolean":
        valid = isinstance(value, bool)
    elif kind == "date":
        try:
            valid = isinstance(value, str) and bool(re.fullmatch(r"\d{4}-\d{2}(?:-\d{2})?", value))
            if valid:
                date.fromisoformat(value + "-01" if len(value) == 7 else value)
        except ValueError:
            valid = False
    elif kind == "list":
        valid = isinstance(value, list) and all(
            isinstance(v, str) or numeric_answer(v) for v in value
        )
    elif kind == "table":
        valid = (
            isinstance(value, dict)
            and isinstance(value.get("columns"), list)
            and all(isinstance(c, str) for c in value["columns"])
            and isinstance(value.get("rows"), list)
            and all(
                isinstance(r, list)
                and len(r) == len(value["columns"])
                and all(isinstance(v, str) or numeric_answer(v) for v in r)
                for r in value["rows"]
            )
        )
    elif kind in {"unanswerable", "abstain"}:
        valid = value is None
    else:
        valid = False
    if not valid:
        issues.append(f"Invalid answer type/value: {kind}")
    if "alias" in row and not isinstance(row["alias"], list):
        issues.append("alias must be a list; accepted forms must be preserved")
    return issues


def load_training_answers(split_dir: Path, questions: list[dict]) -> tuple[list[dict], list[dict]]:
    """Call only for an explicitly selected training split. Never called by data ingestion."""
    path = split_dir / "answers.jsonl"
    if not path.is_file():
        return [], [{"reason": "Training answers.jsonl is missing"}]
    answers, errors, seen = [], [], set()
    question_ids = {q["id"] for q in questions}
    for line_no, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line, parse_float=Decimal)
            if not isinstance(row, dict):
                raise ValueError("Answer must be an object")
            issues = validate_answer(row)
            if row.get("id") in seen:
                issues.append("Duplicate answer id")
            if row.get("id") not in question_ids:
                issues.append("Answer has no valid question")
            if issues:
                raise ValueError("; ".join(issues))
            seen.add(row["id"])
            answers.append(row)
        except (ValueError, TypeError) as error:
            errors.append({"line_no": line_no, "reason": str(error)})
    errors.extend(
        {"id": qid, "reason": "Missing training answer"} for qid in sorted(question_ids - seen)
    )
    return answers, errors


def business_folds(questions: list[dict], folds: int = 5) -> list[dict]:
    if folds < 2:
        raise ValueError("Use at least two folds")
    businesses = sorted(
        {q["business_id"] for q in questions}, key=lambda b: hashlib.sha256(b.encode()).hexdigest()
    )
    return [
        {"business_id": business, "fold": index % folds}
        for index, business in enumerate(businesses)
    ]


def prepare_qa(
    split_dir: Path,
    output_dir: Path,
    *,
    split_role: str = "inference",
    folds: int = 5,
    code_sha256: str | None = None,
) -> dict:
    if split_role not in {"train", "inference"}:
        raise ValueError("split_role must be train or inference")
    paths = [split_dir / "questions.jsonl"]
    if split_role == "train":
        paths.append(split_dir / "answers.jsonl")
    inventory = inventory_files(split_dir, paths)
    folder = component_run(
        split_dir,
        output_dir,
        "qa",
        inventory,
        {"split_role": split_role, "folds": folds},
        code_sha256 or implementation_digest(globals()),
    )
    questions, rejected, counters = load_questions(split_dir)
    write_jsonl(folder / "inference/questions.jsonl", questions)
    write_jsonl(folder / "rejected_questions.jsonl", rejected)
    write_json(folder / "businesses.json", sorted({q["business_id"] for q in questions}))
    answers, answer_errors = [], []
    if split_role == "train":
        answers, answer_errors = load_training_answers(split_dir, questions)
        write_jsonl(folder / "evaluation/answers.jsonl", answers)
        write_jsonl(folder / "evaluation/business_folds.jsonl", business_folds(questions, folds))
        write_jsonl(folder / "evaluation/answer_errors.jsonl", answer_errors)
    unchanged = verify_inventory(split_dir, inventory)
    validation = {
        "valid": bool(questions) and not rejected and not answer_errors and unchanged["valid"],
        "questions": len(questions),
        "rejected": len(rejected),
        "counters": counters,
        "split_role": split_role,
        "answers_read": split_role == "train",
        "answers": len(answers),
        "answer_errors": len(answer_errors),
        "input_unchanged": unchanged,
    }
    finish_component(folder, validation)
    return {"folder": folder, "questions": questions, "validation": validation}
