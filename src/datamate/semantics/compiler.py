"""Model-proposed semantic views with transactional, offline validation (SPEC 7.3)."""

from __future__ import annotations

import asyncio
import hashlib
import re
import threading

import duckdb
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from datamate.catalog import catalog_artifact
from datamate.catalog.models import IngestionCatalog as BusinessCatalog
from datamate.catalog.models import (
    JoinEdge,
    SemanticAnnotations,
    TableRole,
    ValueSemantic,
    ViewCheck,
    ViewSpec,
    ViewValidation,
)
from datamate.config import RunConfig
from datamate.contracts import SplitContext
from datamate.ingest import referenced_tables, render_catalog, sql_quote
from datamate.llm import ModelClient

COMPILE_TEMPLATE_ID = "semantics.compile.v1"
COMPILE_SYSTEM = """Compile an offline business data catalog into semantic annotations.
Return JSON matching the supplied schema. Read the mounted rulebook and README;
do not assume rules from another business or split. Propose at most eight views.
DDL must be exactly CREATE VIEW v_<name> AS SELECT ... over the provided tables.
Do not change source tables or read files. Include actual dependencies, grain,
key columns and category. For monetary exclusion views provide exclusion_check
with source_table, source_column, view_column and span quoting the authoritative
rulebook; this requests a SUM(view)<=SUM(source) check. Do not invent evidence.
Validation/enabled decisions belong to the executor, never the model."""


class ViewProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^v_[a-z][a-z0-9_]*$")
    purpose: str
    ddl: str
    depends_on: list[str] = []
    category: str = "other"
    key_columns: list[str] = []
    exclusion_check: dict[str, str] | None = None


class SemanticProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    table_roles: dict[str, TableRole] = {}
    value_semantics: list[ValueSemantic] = []
    join_paths: list[JoinEdge] = []
    views: list[ViewProposal] = Field(default=[], max_length=8)


def validate_view(
    proposal: ViewProposal,
    connection,
    catalog: BusinessCatalog,
    split: SplitContext,
    cfg: RunConfig,
    enabled_views: set[str],
) -> ViewSpec:
    checks, executed, rows = [], False, 0
    view = ViewSpec(**proposal.model_dump())
    if (
        cfg.features.compiled_views_categories is not None
        and view.category not in cfg.features.compiled_views_categories
    ):
        return view.model_copy(
            update={
                "validation": ViewValidation(
                    checks=[
                        ViewCheck(
                            name="category_enabled", passed=False, detail="Category kill switch"
                        )
                    ]
                )
            }
        )
    timer = threading.Timer(cfg.exec_limits.sql_timeout_s, connection.interrupt)
    transaction = False
    try:
        match = re.fullmatch(
            r"\s*CREATE\s+VIEW\s+(v_[a-z][a-z0-9_]*)\s+AS\s+(.+?)\s*;?\s*", view.ddl, re.I | re.S
        )
        if not match or match[1] != view.name:
            raise ValueError("DDL must create exactly the declared view")
        query = match[2]
        statements = duckdb.extract_statements(query)
        if len(statements) != 1 or statements[0].type != duckdb.StatementType.SELECT:
            raise ValueError("View body must contain one SELECT")
        qualified_sources = referenced_tables(query, qualified=True)
        if any("." in source and not source.startswith("main.") for source in qualified_sources):
            raise ValueError("Views may use only the advertised main-schema tables")
        sources = {source.removeprefix("main.") for source in qualified_sources}
        known = {t.name for t in catalog.tables} | enabled_views
        if not sources or not sources <= known or set(view.depends_on) != sources:
            raise ValueError("Actual sources must match declared known dependencies")
        checks.append(ViewCheck(name="ddl_and_dependencies", passed=True))
        connection.execute("BEGIN TRANSACTION")
        transaction = True
        timer.start()
        connection.execute(view.ddl)
        executed = True
        name = sql_quote(view.name)
        rows = connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        if rows == 0:
            raise ValueError("View is empty")
        checks.append(ViewCheck(name="nonempty", passed=True, detail=str(rows)))
        if view.key_columns:
            keys = ",".join(sql_quote(k) for k in view.key_columns)
            nulls = " OR ".join(f"{sql_quote(k)} IS NULL" for k in view.key_columns)
            if connection.execute(f"SELECT COUNT(*) FROM {name} WHERE {nulls}").fetchone()[0]:
                raise ValueError("Declared view key contains NULL")
            if connection.execute(
                f"SELECT COUNT(*) FROM (SELECT {keys} FROM {name} GROUP BY {keys} HAVING COUNT(*)>1)"
            ).fetchone()[0]:
                raise ValueError("Declared view key has duplicates")
            checks.append(ViewCheck(name="key_unique_and_nonnull", passed=True))
        if view.exclusion_check:
            evidence = view.exclusion_check
            span = evidence.get("span", "")
            if not span or " ".join(span.split()) not in " ".join(split.rulebook_text.split()):
                raise ValueError("Exclusion rule needs an exact rulebook span")
            if evidence.get("source_table") not in sources:
                raise ValueError("Exclusion source must be a view dependency")
            source = sql_quote(evidence["source_table"])
            source_column, view_column = (
                sql_quote(evidence["source_column"]),
                sql_quote(evidence["view_column"]),
            )
            base = connection.execute(f"SELECT SUM({source_column}) FROM {source}").fetchone()[0]
            actual = connection.execute(f"SELECT SUM({view_column}) FROM {name}").fetchone()[0]
            if base is None or actual is None or actual > base:
                raise ValueError("Exclusion view sum exceeds source or is NULL")
            checks.append(
                ViewCheck(
                    name="exclusion_sum", passed=True, detail=f"actual={actual};source={base}"
                )
            )
        connection.execute("COMMIT")
        transaction = False
        return view.model_copy(
            update={
                "enabled": True,
                "validation": ViewValidation(executed=executed, row_count=rows, checks=checks),
            }
        )
    except (ValueError, KeyError, duckdb.Error) as error:
        if transaction:
            connection.execute("ROLLBACK")
        checks.append(
            ViewCheck(name="validation", passed=False, detail=f"{type(error).__name__}: {error}")
        )
        return view.model_copy(
            update={
                "enabled": False,
                "validation": ViewValidation(executed=executed, row_count=rows, checks=checks),
            }
        )
    finally:
        timer.cancel()


def compile_semantics_sync(
    catalog: BusinessCatalog,
    split: SplitContext,
    client: ModelClient,
    replica: int = 0,
    cfg: RunConfig | None = None,
) -> SemanticAnnotations:
    config = cfg or RunConfig()
    if not config.features.compiled_views or catalog.status != "ready":
        return SemanticAnnotations(warnings=["SEMANTICS_DISABLED"])
    messages = [
        {"role": "system", "content": COMPILE_SYSTEM},
        {
            "role": "user",
            "content": f"RULEBOOK:\n{split.rulebook_text}\nREADME:\n{catalog.readme_text or ''}\nSCHEMA:\n{catalog.schema_card}",
        },
    ]
    call = client.complete(
        stage="compile",
        template_id=COMPILE_TEMPLATE_ID,
        messages=messages,
        json_schema=SemanticProposal.model_json_schema(),
        max_tokens=config.model.max_tokens.get("compile", 4096),
        call_id=f"{catalog.bkey}:compile:{replica}:1",
    )
    if call.error:
        return SemanticAnnotations(
            compile_calls=[call], warnings=[f"SEMANTICS_MODEL_ERROR {call.error}"]
        )
    try:
        proposal = SemanticProposal.model_validate_json(call.content)
    except ValidationError as error:
        return SemanticAnnotations(compile_calls=[call], warnings=[f"SEMANTICS_INVALID {error}"])
    known_tables = {t.name for t in catalog.tables}
    known_columns = {t.name + "." + c.name for t in catalog.tables for c in t.columns}
    warnings = []
    roles = {name: role for name, role in proposal.table_roles.items() if name in known_tables}
    values = [v for v in proposal.value_semantics if v.column in known_columns]
    edges = [e for e in proposal.join_paths if e.left in known_columns and e.right in known_columns]
    if (
        len(roles) != len(proposal.table_roles)
        or len(values) != len(proposal.value_semantics)
        or len(edges) != len(proposal.join_paths)
    ):
        warnings.append("SEMANTICS_UNKNOWN_SCHEMA_REFERENCE")
    views, enabled = [], set()
    with duckdb.connect(
        catalog.db_path,
        config={
            "threads": 1,
            "enable_external_access": False,
            "autoinstall_known_extensions": False,
            "autoload_known_extensions": False,
        },
    ) as connection:
        connection.execute("SET lock_configuration=true")
        for view in proposal.views:
            result = validate_view(view, connection, catalog, split, config, enabled)
            views.append(result)
            if result.enabled:
                enabled.add(result.name)
        connection.execute("CHECKPOINT")
    return SemanticAnnotations(
        table_roles=roles,
        value_semantics=values,
        join_paths=edges,
        views=views,
        compile_calls=[call],
        warnings=warnings,
    )


async def compile_semantics(
    catalog: BusinessCatalog,
    split: SplitContext,
    client: ModelClient,
    replica: int = 0,
    cfg: RunConfig | None = None,
) -> SemanticAnnotations:
    return await asyncio.to_thread(compile_semantics_sync, catalog, split, client, replica, cfg)


def attach_semantics(catalog: BusinessCatalog, annotations: SemanticAnnotations) -> BusinessCatalog:
    updated = catalog.model_copy(
        update={
            "views": annotations.views,
            "compile_calls": annotations.compile_calls,
            "semantic_annotations": annotations,
        }
    )
    card = render_catalog(catalog_artifact(updated))
    return updated.model_copy(
        update={
            "schema_card": card,
            "schema_card_sha256": hashlib.sha256(card.encode()).hexdigest(),
        }
    )
