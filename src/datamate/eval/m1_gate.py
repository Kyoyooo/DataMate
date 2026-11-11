"""Held-out P2 comparison; consumes real prediction artifacts, never creates answers."""

from __future__ import annotations

import json
from pathlib import Path

from datamate.config import RunConfig
from datamate.contracts import loads_exact
from datamate.eval.score import score_files


def evaluate_m1_gate(
    split_dir: Path, off_predictions: Path, on_predictions: Path, manifest_path: Path, feature: str
) -> dict:
    if feature not in {"entity_linker", "compiled_views"}:
        raise ValueError("Unknown M1 P2 feature")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("source_role") != "train":
        raise ValueError("Only training held-out evidence is permitted")
    off = RunConfig.model_validate(manifest["off_config"]).model_dump()
    on = RunConfig.model_validate(manifest["on_config"]).model_dump()
    if off["features"][feature] or not on["features"][feature]:
        raise ValueError("Configurations must switch exactly the requested feature off/on")
    on["features"][feature] = False
    off.pop("work_dir", None)
    on.pop("work_dir", None)
    if on != off:
        raise ValueError("Other effective settings differ; cannot attribute PA to this feature")
    questions = [
        loads_exact(line)
        for line in (split_dir / "questions.jsonl").read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]
    by_id = {q["id"]: q for q in questions}
    businesses = {q["business_id"] for q in questions}
    covered = set()
    for fold in manifest["folds"]:
        held_out = set(fold["held_out_business_ids"])
        training = set(fold["training_business_ids"])
        fewshot = set(fold.get("fewshot_business_ids", []))
        if not held_out or held_out & covered or held_out | training != businesses:
            raise ValueError("Folds must partition all training businesses")
        if held_out & (training | fewshot) or not fewshot <= training:
            raise ValueError("Held-out business leaked into training or few-shot sources")
        expected_ids = {q["id"] for q in questions if q["business_id"] in held_out}
        if set(fold["question_ids"]) != expected_ids:
            raise ValueError("Fold question IDs do not match held-out businesses")
        covered |= held_out
    if covered != businesses or len(manifest["folds"]) < 2:
        raise ValueError("Need complete business-held-out folds")
    for path in (off_predictions, on_predictions):
        seen = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = loads_exact(line)
            if row.get("id") not in by_id or row["id"] in seen:
                raise ValueError("Prediction contains an unknown or duplicate question ID")
            seen.add(row["id"])
    baseline = score_files(off_predictions, split_dir / "answers.jsonl")
    enabled = score_files(on_predictions, split_dir / "answers.jsonl")
    categories = {}
    for question in questions:
        if "category" in question:
            categories.setdefault(question["category"], []).append(question["id"])
    for category, ids in list(categories.items()):
        before = sum(baseline["per_id"][qid] for qid in ids) / len(ids)
        after = sum(enabled["per_id"][qid] for qid in ids) / len(ids)
        categories[category] = {
            "n": len(ids),
            "off_pa": before,
            "on_pa": after,
            "non_degrading": after >= before,
        }
    return {
        "feature": feature,
        "source_role": "train",
        "business_held_out": True,
        "n": enabled["n"],
        "off_pa": baseline["pa"],
        "on_pa": enabled["pa"],
        "delta_pa": enabled["pa"] - baseline["pa"],
        "by_category": categories,
        "category_evidence_available": bool(categories),
        "gate_passed": (
            enabled["pa"] > baseline["pa"]
            if feature == "compiled_views"
            else enabled["pa"] >= baseline["pa"]
        )
        and all(row["non_degrading"] for row in categories.values()),
        "automatic_enable": False,
    }
