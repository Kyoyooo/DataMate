"""Token-bounded schema selection. Full profiles remain available in audit snapshots."""

from __future__ import annotations

import json
import re
from collections import Counter
from functools import lru_cache, partial
from pathlib import Path

from datamate.config import RunConfig
from datamate.contracts import BusinessCatalog
from datamate.ingest.engine import column_hint
from datamate.lexicon import fold
from datamate.prompts.budget import ContextBuilder, ContextOverflow


class SchemaContextOverflow(ContextOverflow):
    """A complete usable table schema cannot fit the configured budget."""


@lru_cache(maxsize=32)
def _load_diagnostics(path: str, modified_ns: int, size: int):
    # The stat fields invalidate cached metadata when setup promotes a new catalog.
    from datamate.catalog.io import load_ingestion_catalog

    return load_ingestion_catalog(Path(path))


def _diagnostics(catalog):
    if hasattr(catalog, "joins"):
        return catalog
    path = Path(catalog.db_path).parent / "business_catalog.json"
    if not path.is_file():
        return catalog
    try:
        stat = path.stat()
        rich = _load_diagnostics(str(path.resolve()), stat.st_mtime_ns, stat.st_size)

        def signature(cat):
            return [
                (
                    table.name,
                    table.row_count,
                    [(column.name, column.sql_type) for column in table.columns],
                )
                for table in cat.tables
            ]

        if (
            rich.business_id == catalog.business_id
            and Path(rich.db_path).resolve() == Path(catalog.db_path).resolve()
            and signature(rich) == signature(catalog)
        ):
            return rich
    except (OSError, ValueError):
        pass  # A main-only catalog has no M1 metadata; its core schema still works.
    return catalog


def build_context(tokenizer, cfg: RunConfig) -> ContextBuilder:
    """Wire M1 to main's existing prompt-budget hooks, using the same tokenizer."""
    return ContextBuilder(
        tokenizer,
        cfg.solver,
        schema_fn=partial(select_schema_context, tokenizer=tokenizer, cfg=cfg),
        schema_subset_fn=partial(
            select_schema_context, tokenizer=tokenizer, cfg=cfg, relevant_only=True
        ),
    )


def _words(text: str) -> set[str]:
    return set(re.findall(r"[^\W_]+", fold(text)))


def _table_text(table, *, samples: bool) -> str:
    lines = [f"TABLE {table.name} ({table.row_count} rows; source {table.source_file})"]
    for column in table.columns:
        line = f"  {column.name} {column.sql_type} [{json.dumps(column.original_name, ensure_ascii=False)}]"
        hint = getattr(column, "semantic_hint", None) or column_hint(column.original_name)
        if column.top_values and (hint == "status" or (samples and column.distinct_count <= 50)):
            line += " values: " + ", ".join(
                json.dumps(value, ensure_ascii=False) for value, _ in column.top_values
            )
        for key in ("raw_column", "status_column", "unit_column"):
            if value := getattr(column, key, None):
                line += f" {key}={value}"
        lines.append(line)
    keys = getattr(table, "candidate_keys", [])
    if keys:
        lines.append("KEYS " + json.dumps(keys, ensure_ascii=False))
    return "\n".join(lines) + "\n"


def select_schema_context(
    catalog: BusinessCatalog,
    query: str,
    tokenizer,
    cfg: RunConfig | None = None,
    *,
    budget_tokens: int | None = None,
    relevant_only: bool = False,
) -> str:
    """Return <= budget tokens or raise ContextOverflow; never silently skip budgeting.

    Accepts main's unchanged catalog and M1 internal diagnostics. Reductions keep
    complete table schemas and status vocabularies; no SQL/text is sliced mid-line.
    """
    if tokenizer is None:
        raise SchemaContextOverflow("E_CONTEXT_OVERFLOW: tokenizer required for schema budgeting")
    budget = (
        budget_tokens
        if budget_tokens is not None
        else (cfg or RunConfig()).solver.schema_card_budget_tokens
    )

    def fits(text):
        return len(tokenizer.encode(text, add_special_tokens=False)) <= budget

    if not relevant_only and fits(catalog.schema_card):
        return catalog.schema_card
    catalog = _diagnostics(catalog)
    tokens = _words(query)

    def score(table):
        names = " ".join(column.original_name + " " + column.name for column in table.columns)
        return 2 * len(tokens & _words(table.name)) + len(tokens & _words(names))

    ranked = sorted(catalog.tables, key=lambda table: (-score(table), table.name))
    if not ranked:
        raise SchemaContextOverflow("E_CONTEXT_OVERFLOW: no usable tables")
    counts = Counter(warning.split(" ", 1)[0] for warning in catalog.warnings)
    footer = "".join(
        f"WARN {code} ({count} occurrences; see audit)\n" for code, count in sorted(counts.items())
    )
    if catalog.data_range:
        footer += (
            f"DATES {catalog.data_range.start.isoformat()}..{catalog.data_range.end.isoformat()}\n"
        )

    def render(tables, samples):
        names = {table.name for table in tables}
        text = "".join(_table_text(table, samples=samples) for table in tables)
        for edge in getattr(catalog, "joins", []):
            if edge.left.rsplit(".", 1)[0] in names and edge.right.rsplit(".", 1)[0] in names:
                text += f"JOIN {edge.left} -> {edge.right} ({edge.cardinality})\n"
        for view in getattr(catalog, "views", []):
            if view.enabled and set(view.depends_on) <= names:
                text += f"VIEW {view.name} {view.purpose}\n{view.ddl}\n"
        omitted = len(ranked) - len(tables)
        if omitted:
            text += f"SCHEMA_SUBSET {omitted} tables omitted; full catalog available in audit\n"
        return text + footer

    for samples in (True, False):
        text = render(ranked, samples)
        if not relevant_only and fits(text):
            return text
    kept = []
    for table in ranked:
        if relevant_only and kept and score(table) == 0:
            continue
        if fits(render([*kept, table], False)):
            kept.append(table)
        elif not kept:
            raise SchemaContextOverflow(
                "E_CONTEXT_OVERFLOW: highest-ranked complete table exceeds schema budget"
            )
    text = render(kept, False)
    if not kept or not fits(text):
        raise SchemaContextOverflow("E_CONTEXT_OVERFLOW: relevant schema exceeds configured budget")
    return text
