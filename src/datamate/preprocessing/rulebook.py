"""Lossless rulebook structure, source-backed temporal fields and offline retrieval."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

from datamate.ingest.common import (
    component_run,
    finish_component,
    fold_key,
    implementation_digest,
    inventory_files,
    json_text,
    nfc_text,
    verify_inventory,
    write_json,
    write_jsonl,
)

TEMPORAL_DEFAULTS = {
    "week_start": "mon",
    "to_date_end": "as_of",
    "rolling_includes_as_of": True,
    "prior_period_full": True,
    "range_end_inclusive": True,
    "same_period_alignment": "calendar_dates",
}
TEMPORAL_ALLOWED = {
    "week_start": ["mon", "sun"],
    "to_date_end": ["as_of", "day_before_as_of"],
    "rolling_includes_as_of": [True, False],
    "prior_period_full": [True, False],
    "range_end_inclusive": [True, False],
    "same_period_alignment": ["calendar_dates", "elapsed_days"],
}


def markdown_table_cells(line: str) -> list[str]:
    text, cells, buffer, ticks, index = line.strip().strip("|"), [], [], 0, 0
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            buffer.extend(text[index : index + 2])
            index += 2
            continue
        if char == "`":
            end = index + 1
            while end < len(text) and text[end] == "`":
                end += 1
            count = end - index
            ticks = count if not ticks else 0 if ticks == count else ticks
            buffer.extend(text[index:end])
            index = end
            continue
        if char == "|" and not ticks:
            cells.append("".join(buffer).strip())
            buffer = []
        else:
            buffer.append(char)
        index += 1
    cells.append("".join(buffer).strip())
    return cells


def table_separator(line: str) -> bool:
    return line.strip().startswith("|") and all(
        re.fullmatch(r":?-{3,}:?", c.replace(" ", "")) for c in markdown_table_cells(line)
    )


def parse_rules(text: str) -> tuple[list[dict], dict]:
    """Parse headings, table rows, bullets, paragraphs and fenced code with source spans."""
    lines, rules, structural, path, index = text.splitlines(keepends=True), [], [], [], 0
    headers = None
    while index < len(lines):
        line = lines[index].strip()
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if not line or heading or table_separator(line):
            structural.append(index + 1)
            if heading:
                depth = len(heading[1])
                path = path[: depth - 1]
                path.extend([""] * (depth - 1 - len(path)))
                path.append(heading[2])
                headers = None
            index += 1
            continue
        if index + 1 < len(lines) and line.startswith("|") and table_separator(lines[index + 1]):
            headers = markdown_table_cells(line)
            structural.append(index + 1)
            index += 1
            continue
        start = index
        if line.startswith(("```", "~~~")):
            fence = line[:3]
            index += 1
            while index < len(lines) and not lines[index].strip().startswith(fence):
                index += 1
            if index >= len(lines):
                raise ValueError("Unclosed rulebook code fence")
            index += 1
            kind = "code"
        elif line.startswith("|") and headers:
            if len(markdown_table_cells(line)) != len(headers):
                raise ValueError(f"Malformed rulebook table at line {index + 1}")
            index += 1
            kind = "table_row"
        else:
            index += 1
            while (
                index < len(lines)
                and lines[index].strip()
                and not re.match(r"\s*(?:#|\||[-*+]\s|\d+[.)]\s|```|~~~)", lines[index])
            ):
                index += 1
            kind = "bullet" if re.match(r"(?:[-*+]|\d+[.)])\s", line) else "paragraph"
        source = "".join(lines[start:index])
        body = source.strip()
        cells = markdown_table_cells(line) if kind == "table_row" else None
        if cells is not None:
            body = "\n".join(f"{h}: {v}" for h, v in zip(headers, cells, strict=True))
        key = hashlib.sha256(f"{start + 1}:{index}:{source}".encode()).hexdigest()[:20]
        rules.append(
            {
                "rule_id": "r_" + key,
                "kind": kind,
                "heading_path": [p for p in path if p],
                "title": cells[0] if cells else re.sub(r"^[\s*+\-\d.)]+", "", line)[:160],
                "text": body,
                "source_text": source,
                "line_start": start + 1,
                "line_end": index,
                "source": "rulebook.md",
                "table_headers": headers if cells else None,
                "table_cells": cells,
                "content_sha256": hashlib.sha256(source.encode()).hexdigest(),
            }
        )
    covered = {n for r in rules for n in range(r["line_start"], r["line_end"] + 1)}
    uncovered = sorted(set(range(1, len(lines) + 1)) - set(structural) - covered)
    return rules, {
        "valid": not uncovered,
        "source_lines": len(lines),
        "rules": len(rules),
        "structural_lines": structural,
        "uncovered_lines": uncovered,
    }


def build_rule_graph(rules: list[dict]) -> dict:
    """Explicit section references only; no fixed section numbers or invented dependencies."""
    sections = {}
    for rule in rules:
        for heading in rule["heading_path"]:
            match = re.match(r"(\d+(?:\.\d+)*)[.)]?\s", heading)
            if match:
                sections.setdefault(match[1], []).append(rule["rule_id"])
    edges = []
    for rule in rules:
        for section in sorted(set(re.findall(r"§\s*(\d+(?:\.\d+)*)", rule["text"]))):
            edges.extend(
                {
                    "source": rule["rule_id"],
                    "target": target,
                    "type": "EXPLICIT_SECTION_REFERENCE",
                    "section": section,
                }
                for target in sections.get(section, [])
                if target != rule["rule_id"]
            )
    return {
        "nodes": [r["rule_id"] for r in rules],
        "edges": edges,
        "policy": "References supply context; they do not establish rule applicability",
    }


def validate_temporal_fields(text: str, proposed: dict | None) -> dict:
    values, provenance, warnings = {}, {}, []
    normalized = " ".join(text.split())
    for name, fallback in TEMPORAL_DEFAULTS.items():
        item = (proposed or {}).get(name)
        valid = (
            isinstance(item, dict)
            and isinstance(item.get("span"), str)
            and bool(item["span"].strip())
        )
        if valid:
            allowed = TEMPORAL_ALLOWED[name]
            valid = type(item.get("value")) is type(fallback) and item["value"] in allowed
            valid &= " ".join(item["span"].split()) in normalized
        if valid:
            values[name] = item["value"]
            provenance[name] = {"source": "rulebook", "span": item["span"]}
        else:
            values[name] = fallback
            provenance[name] = {"source": "generic", "span": None}
            warnings.append("W_TEMPORAL_GENERIC " + name)
    return {**values, "provenance": provenance, "warnings": warnings}


def local_temporal_call(text: str, model_dir: Path, *, max_tokens: int = 2048) -> tuple[dict, dict]:
    """One optional real, local model call. Missing weights never cause downloads."""
    import os

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    from transformers import AutoModelForCausalLM, AutoTokenizer, set_seed

    if not model_dir.is_dir():
        raise FileNotFoundError(f"Local model directory not found: {model_dir}")
    tokenizer = AutoTokenizer.from_pretrained(
        str(model_dir), local_files_only=True, trust_remote_code=False
    )
    model = AutoModelForCausalLM.from_pretrained(
        str(model_dir), local_files_only=True, trust_remote_code=False
    )
    model.eval()
    set_seed(20261116)
    prompt = (
        "Extract temporal rules. Return only a JSON object whose keys are the fields below. "
        "Each field is {value, span}. span must quote the rulebook exactly. "
        "If not stated, use null for span. Do not invent evidence. Allowed values: "
        + json_text(TEMPORAL_ALLOWED)
        + "\nRULEBOOK:\n"
        + text
    )
    messages = [{"role": "user", "content": prompt}]
    encoded = tokenizer.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=True, return_tensors="pt"
    )
    generated = model.generate(encoded, max_new_tokens=max_tokens, do_sample=False)
    response = tokenizer.decode(generated[0, encoded.shape[1] :], skip_special_tokens=True)
    content = re.sub(r"<think>.*?</think>", "", response, flags=re.S).strip()
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content).strip()
    try:
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            parsed = {}
    except json.JSONDecodeError:
        parsed = {}
    files = inventory_files(model_dir, list(model_dir.rglob("*")))
    return parsed, {
        "stage": "rule_profile",
        "template_id": "rules.temporal.v1",
        "prompt": prompt,
        "raw_response": response,
        "thinking": re.findall(r"<think>(.*?)</think>", response, flags=re.S) or None,
        "model_files": files,
        "parameter_count": sum(p.numel() for p in model.parameters()),
        "temperature": 0,
        "seed": 20261116,
    }


def rule_terms(text: str) -> list[str]:
    return re.findall(r"\w+", fold_key(text))


def bm25_rank(query: str, rules: list[dict]) -> list[dict]:
    if not query.strip():
        raise ValueError("Retrieval query cannot be empty")
    documents = [Counter(rule_terms(" ".join(r["heading_path"]) + " " + r["text"])) for r in rules]
    lengths = [sum(d.values()) for d in documents]
    average = sum(lengths) / len(lengths) if lengths else 1
    scored = []
    for index, document in enumerate(documents):
        score = 0.0
        for term in set(rule_terms(query)):
            frequency = document[term]
            df = sum(d[term] > 0 for d in documents)
            idf = math.log1p((len(documents) - df + 0.5) / (df + 0.5))
            score += (
                idf
                * frequency
                * 2.5
                / (frequency + 1.5 * (0.25 + 0.75 * lengths[index] / (average or 1)))
            )
        scored.append({"rule_id": rules[index]["rule_id"], "bm25": score})
    return sorted(scored, key=lambda r: (-r["bm25"], r["rule_id"]))


def local_rule_embeddings(rules: list[dict], model_dir: Path, *, max_tokens: int = 1024) -> dict:
    """Optional dense index from local weights; canonical rules remain untruncated."""
    import os

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import numpy as np
    from sentence_transformers import SentenceTransformer

    if not model_dir.is_dir():
        raise FileNotFoundError(f"Local embedding model directory not found: {model_dir}")
    encoder = SentenceTransformer(
        str(model_dir), device="cpu", local_files_only=True, trust_remote_code=False
    )
    encoder.max_seq_length = min(max_tokens, encoder.max_seq_length)
    passages = []
    for rule in rules:
        text, start = rule["text"], 0
        header = " / ".join(rule["heading_path"]) + "\n"
        while start < len(text):
            low, high = start + 1, len(text)
            while low <= high:
                middle = (low + high) // 2
                tokens = len(
                    encoder.tokenizer(header + text[start:middle], add_special_tokens=True)[
                        "input_ids"
                    ]
                )
                if tokens <= encoder.max_seq_length:
                    low = middle + 1
                else:
                    high = middle - 1
            if high <= start:
                raise ValueError("Rule heading exceeds embedding context")
            passages.append(
                {
                    "rule_id": rule["rule_id"],
                    "char_start": start,
                    "char_end": high,
                    "text": header + text[start:high],
                }
            )
            if high == len(text):
                break
            start = max(start + 1, high - min(80, (high - start) // 4))
    if not passages:
        return {"passages": [], "vectors": np.empty((0, 0)), "model_files": [], "encoder": encoder}
    vectors = np.asarray(
        encoder.encode(
            [p["text"] for p in passages],
            batch_size=4,
            normalize_embeddings=False,
            convert_to_numpy=True,
            prompt="",
        ),
        dtype=np.float64,
    )
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    if not np.isfinite(vectors).all() or (norms == 0).any():
        raise ValueError("Invalid embedding vectors")
    vectors = np.asarray(vectors / norms, dtype=np.float32)
    return {
        "passages": passages,
        "vectors": vectors,
        "encoder": encoder,
        "model_files": inventory_files(model_dir, list(model_dir.rglob("*"))),
    }


def retrieve_evidence(
    query: str,
    rules: list[dict],
    graph: dict,
    *,
    top_k: int = 20,
    dense_index: dict | None = None,
    query_prefix: str = "",
) -> dict:
    if top_k < 1:
        raise ValueError("top_k must be positive")
    ranking = bm25_rank(query, rules)
    if dense_index is not None and len(dense_index["passages"]):
        import numpy as np

        encoder = dense_index["encoder"]
        query_text = query_prefix + query
        if (
            len(encoder.tokenizer(query_text, add_special_tokens=True)["input_ids"])
            > encoder.max_seq_length
        ):
            raise ValueError("Query exceeds embedding context")
        vector = np.asarray(
            encoder.encode([query_text], normalize_embeddings=False, prompt=""), dtype=np.float64
        )[0]
        norm = np.linalg.norm(vector)
        if not np.isfinite(vector).all() or norm == 0:
            raise ValueError("Invalid query embedding")
        cosine = dense_index["vectors"] @ np.asarray(vector / norm, dtype=np.float32)
        best = {r["rule_id"]: -1.0 for r in rules}
        for passage, score in zip(dense_index["passages"], cosine, strict=True):
            best[passage["rule_id"]] = max(best[passage["rule_id"]], float(score))
        dense_order = sorted(best, key=lambda rid: (-best[rid], rid))
        dense_rank = {rid: index for index, rid in enumerate(dense_order, 1)}
        for index, item in enumerate(ranking, 1):
            item["cosine"] = best[item["rule_id"]]
            item["rrf"] = 1 / (60 + dense_rank[item["rule_id"]]) + (
                1 / (60 + index) if item["bm25"] > 0 else 0
            )
        ranking.sort(key=lambda r: (-r["rrf"], r["rule_id"]))
    seeds = [r["rule_id"] for r in ranking[:top_k] if dense_index is not None or r["bm25"] > 0]
    selected = set(seeds)
    queue = list(seeds)
    for rule_id in queue:
        for edge in graph["edges"]:
            if edge["source"] == rule_id and edge["target"] not in selected:
                selected.add(edge["target"])
                queue.append(edge["target"])
    return {
        "query": query,
        "ranking": ranking,
        "rules": [r for r in rules if r["rule_id"] in selected],
        "semantic_completeness_guaranteed": False,
        "agent_review_performed": False,
        "policy": "Candidate context only. Confirm applicability, exceptions, README, schema and data coverage. Scores are not probabilities.",
    }


def prepare_rulebook(
    split_dir: Path,
    output_dir: Path,
    *,
    temporal_extractor=None,
    embedding_model_dir: Path | None = None,
    query: str = "Doanh thu và đơn hàng hợp lệ được định nghĩa như thế nào?",
    top_k: int = 20,
    query_prefix: str = "",
    code_sha256: str | None = None,
) -> dict:
    path = split_dir / "rulebook.md"
    inventory = inventory_files(split_dir, [path])
    text, warnings = "", []
    try:
        text = nfc_text(path.read_bytes().decode("utf-8-sig"))
    except (OSError, UnicodeError):
        warnings.append("W_RULEBOOK_MISSING")
    # A caller must identify a configured model; otherwise use explicit generic fields.
    proposed, call = (
        temporal_extractor(text) if temporal_extractor is not None and text.strip() else ({}, None)
    )
    temporal = validate_temporal_fields(text, proposed)
    rules, parsing = parse_rules(text)
    graph = build_rule_graph(rules)
    dense = local_rule_embeddings(rules, embedding_model_dir) if embedding_model_dir else None
    settings = {
        "top_k": top_k,
        "query": query,
        "query_prefix": query_prefix,
        "temporal_defaults": TEMPORAL_DEFAULTS,
        "temporal_call": call,
        "embedding_model_files": dense["model_files"] if dense else None,
    }
    folder = component_run(
        split_dir,
        output_dir,
        "rulebook",
        inventory,
        settings,
        code_sha256 or implementation_digest(globals()),
    )
    (folder / "rulebook.md").write_text(text, encoding="utf-8")
    write_jsonl(folder / "rules.jsonl", rules)
    write_json(folder / "rule_graph.json", graph)
    write_json(folder / "temporal_params.json", temporal)
    write_json(folder / "model_call.json", call)
    evidence = retrieve_evidence(
        query, rules, graph, top_k=top_k, dense_index=dense, query_prefix=query_prefix
    )
    write_json(folder / "example_evidence.json", evidence)
    context = (
        evidence["policy"]
        + "\n\n"
        + "\n\n".join(
            f"[{r['rule_id']}] rulebook.md:{r['line_start']}-{r['line_end']}\n{r['text']}"
            for r in evidence["rules"]
        )
    )
    (folder / "example_context.txt").write_text(context, encoding="utf-8")
    if dense is not None:
        import numpy as np

        np.save(folder / "embeddings.npy", dense["vectors"], allow_pickle=False)
        write_jsonl(folder / "passages.jsonl", dense["passages"])
    unchanged = verify_inventory(split_dir, inventory)
    validation = {
        "valid": parsing["valid"] and unchanged["valid"],
        "parse": parsing,
        "warnings": warnings + temporal["warnings"],
        "input_unchanged": unchanged,
        "temporal_model_call_performed": call is not None,
        "temporal_fields_from_rulebook": sum(
            p["source"] == "rulebook" for p in temporal["provenance"].values()
        ),
        "retrieval_backend": "hybrid" if dense is not None else "bm25",
        "answer_accuracy_evaluated": False,
        "semantic_completeness_guaranteed": False,
    }
    finish_component(folder, validation)
    return {
        "folder": folder,
        "rules": rules,
        "temporal": temporal,
        "evidence": evidence,
        "validation": validation,
    }
