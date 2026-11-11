"""Internal M1 audit models. Runtime boundaries use datamate.contracts unchanged.

These models persist ingestion diagnostics and optional experimental semantics;
they are not a replacement for the lead-owned shared contracts.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from datamate.contracts import DateRange, ModelCall


class M1Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class CompileCall(ModelCall):
    """Experimental compile evidence; not emitted through shared runtime logs."""

    stage: Literal["compile"] = "compile"


class DroppedRows(M1Contract):
    total_rows: int = 0
    note_rows: int = 0
    blank_rows: int = 0
    summary_rows: int = 0
    source_indices: dict[str, list[int]] = {}


class JoinEdge(M1Contract):
    left: str
    right: str
    cardinality: Literal["n:1", "1:1", "n:n"]
    match_rate: float = Field(ge=0, le=1)


class DateColumn(M1Contract):
    column: str
    min: date
    max: date
    included_in_data_range: bool = True
    exclusion_reason: str | None = None

    @model_validator(mode="after")
    def _ordered(self):
        if self.min > self.max:
            raise ValueError("Date column minimum exceeds maximum")
        return self


class ColumnInfo(M1Contract):
    name: str  # SQL identifier (ASCII, folded; SPEC SC-2)
    original_name: str  # header exactly as found
    sql_type: Literal[
        "BIGINT", "DECIMAL(38,6)", "DOUBLE", "VARCHAR", "DATE", "TIMESTAMP", "BOOLEAN"
    ]
    null_count: int = Field(ge=0)
    distinct_count: int = Field(ge=0)
    min: str | None = None
    max: str | None = None
    top_values: list[tuple[str, int]] = []
    semantic_hint: (
        Literal["money", "quantity", "percent", "code", "name", "status", "date"] | None
    ) = None
    null_rate: float = Field(default=0, ge=0, le=1)
    raw_column: str | None = None
    parse_rate: float = Field(default=1, ge=0, le=1)
    format_note: str | None = None
    status_column: str | None = None
    unit_column: str | None = None
    observed_units: list[str] = []


class TableInfo(M1Contract):
    name: str
    source_file: str  # relative to the business directory
    row_count: int = Field(ge=0)
    columns: list[ColumnInfo]
    source_part: str | None = None
    candidate_keys: list[list[str]] = []
    dropped_rows: DroppedRows = DroppedRows()
    source_details: dict[str, Any] = {}

    @model_validator(mode="after")
    def _keys_exist(self):
        names = {column.name for column in self.columns}
        if len(names) != len(self.columns) or any(
            not key or not set(key) <= names for key in self.candidate_keys
        ):
            raise ValueError("Duplicate columns or invalid candidate key")
        return self


class IngestionCatalog(M1Contract):
    business_id: str
    bkey: str
    db_path: str
    tables: list[TableInfo]
    data_range: DateRange | None  # union over date columns; None if no dates
    readme_text: str | None
    schema_card: str
    schema_card_sha256: str
    warnings: list[str] = []
    status: Literal["ready", "failed"] = "ready"
    joins: list[JoinEdge] = []
    date_columns: list[DateColumn] = []
    setup_ms: int = Field(default=0, ge=0)
    schema_card_budget_verified: bool = False
    schema_card_needs_subset: bool = False
    views: list[ViewSpec] = []
    compile_calls: list[CompileCall] = []
    semantic_annotations: SemanticAnnotations | None = None


class Mention(M1Contract):
    text: str
    kind: Literal[
        "product", "category", "customer", "supplier", "employee", "store", "channel", "other"
    ] = "other"


class EntityCandidate(M1Contract):
    mention: str
    table: str
    column: str
    value: str
    code: str | None = None
    score: float = Field(ge=0, le=100)
    strength: Literal["strong", "weak"]


class ViewCheck(M1Contract):
    name: str
    passed: bool
    detail: str = ""


class ViewValidation(M1Contract):
    executed: bool = False
    row_count: int = 0
    checks: list[ViewCheck] = []


class ViewSpec(M1Contract):
    name: str = Field(pattern=r"^v_[a-z][a-z0-9_]*$")
    purpose: str
    ddl: str
    depends_on: list[str] = []
    category: str = "other"
    key_columns: list[str] = []
    exclusion_check: dict[str, str] | None = None
    validation: ViewValidation = ViewValidation()
    enabled: bool = False


class TableRole(M1Contract):
    role: Literal["fact", "dimension", "lookup", "log", "other"]
    grain: str


class ValueSemantic(M1Contract):
    column: str
    value: str
    meaning: str


class SemanticAnnotations(M1Contract):
    table_roles: dict[str, TableRole] = {}
    value_semantics: list[ValueSemantic] = []
    join_paths: list[JoinEdge] = []
    views: list[ViewSpec] = Field(default=[], max_length=8)
    compile_calls: list[CompileCall] = []
    warnings: list[str] = []


IngestionCatalog.model_rebuild()
