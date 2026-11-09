"""Exact-tokenizer SchemaCard budgeting with deterministic relevant-table selection."""

from __future__ import annotations

from datamate.catalog.build import catalog_artifact
from datamate.config import RunConfig
from datamate.contracts import BusinessCatalog
from datamate.ingest import DataConfig, budget_schema_card, render_catalog
from datamate.lexicon import fold


class SchemaContextOverflow(ValueError):
    pass


def select_schema_context(
    catalog: BusinessCatalog, query: str, tokenizer, cfg: RunConfig | None = None
) -> str:
    config = cfg or RunConfig()
    if tokenizer is None:
        return catalog.schema_card
    artifact = catalog_artifact(catalog)
    artifact["low_cardinality_max"] = config.ingest.low_cardinality_max
    settings = DataConfig(
        **config.ingest.model_dump(),
        schema_card_budget_tokens=config.solver.schema_card_budget_tokens,
    )
    budgeted = budget_schema_card(artifact, settings, tokenizer)
    if not budgeted["needs_relevant_subset"]:
        return budgeted["text"]
    tokens = set(fold(query).split())
    ranked = sorted(
        artifact["tables"],
        key=lambda t: (
            -len(
                tokens
                & set(
                    fold(
                        t["name"] + " " + " ".join(c["original_name"] for c in t["columns"])
                    ).split()
                )
            ),
            t["name"],
        ),
    )
    keep = {t["name"] for t in ranked[:4]}
    subset = {
        **artifact,
        "tables": [t for t in ranked if t["name"] in keep],
        "joins": [
            e for e in artifact["joins"] if e["left_table"] in keep and e["right_table"] in keep
        ],
        "date_columns": [d for d in artifact["date_columns"] if d["table"] in keep],
    }
    text = render_catalog(subset, top_limit=5)
    text += "".join(
        f"TABLE {t['name']} (columns omitted by relevant-subset policy)\n" for t in ranked[4:]
    )
    if len(tokenizer.encode(text, add_special_tokens=False)) > settings.schema_card_budget_tokens:
        raise SchemaContextOverflow(
            "E_CONTEXT_OVERFLOW: relevant schema exceeds configured token budget"
        )
    return text
