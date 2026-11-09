"""Shared data contracts (SPEC §5, P1 subset). Owner: Lead.

Every type that crosses a package boundary lives here. Rules:
- Text is kept exactly as found (NFC). Nothing here holds accent-folded text.
- Money and other exact numbers are ``decimal.Decimal`` in memory; never float.
- Dates are ``datetime.date``; ISO strings on the wire.
- Models are frozen and reject unknown fields, so a typo in model output or a
  stale producer fails loudly instead of being silently dropped.

Changes follow SPEC §15: bump CONTRACTS_VERSION and get review from every
producer/consumer of the changed type.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CONTRACTS_VERSION = "0.2.0"  # M1 catalog/entity/semantics expansion; legacy fields remain accepted.


class Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


AnswerType = Literal["number", "percent", "string", "date", "boolean", "list", "table"]
DecisionKind = Literal["answer", "unanswerable", "abstain"]
DateGranularity = Literal["day", "month"]
Granularity = Literal["day", "week", "month", "quarter", "year", "range"]
Stage = Literal["parse", "solve", "repair", "compile", "rule_profile"]
# How a number is rounded on the wire (design correction DC-1, see SPEC §18).
NumericKind = Literal["money", "count", "measure"]
# Ranked list (sorted by the formatter) vs. list in the order the question gives (DC-2).
ListOrder = Literal["ranked", "question_order"]


# --------------------------------------------------------------------------- inputs


class Question(Contract):
    id: str = Field(min_length=1)
    business_id: str = Field(min_length=1)
    question: str
    as_of_date: date
    line_no: int = Field(ge=1)


# --------------------------------------------------------------------------- split level


class TemporalParams(Contract):
    """Time conventions of the active split (SPEC §5.5).

    P1 uses the generic defaults below (ISO conventions), *not* values learned
    from the training rulebook. Extraction from the mounted rulebook is TASKS M2-05.
    """

    week_start: Literal["mon", "sun"] = "mon"
    to_date_end: Literal["as_of", "day_before_as_of"] = "as_of"
    rolling_includes_as_of: bool = True
    prior_period_full: bool = True
    source: Literal["generic", "rulebook"] = "generic"


class SplitContext(Contract):
    rulebook_text: str  # verbatim, NFC
    rulebook_sha256: str
    temporal: TemporalParams
    calendar_path: str | None  # lunar calendar is P2 (TASKS M2-02/M2-09)
    warnings: list[str] = []


# --------------------------------------------------------------------------- business level


class DateRange(Contract):
    start: date
    end: date

    @model_validator(mode="after")
    def _ordered(self) -> DateRange:
        if self.start > self.end:
            raise ValueError("DateRange.start must be <= end")
        return self


class M1Contract(Contract):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class TopValue(M1Contract):
    value: str
    count: int = Field(ge=0)

    @model_validator(mode="before")
    @classmethod
    def _legacy_pair(cls, value):
        if isinstance(value, (list, tuple)) and len(value) == 2:
            return {"value": value[0], "count": value[1]}
        return value

    def __iter__(self):
        yield self.value
        yield self.count


class CatalogWarning(M1Contract):
    code: str
    detail: str = ""

    @model_validator(mode="before")
    @classmethod
    def _legacy_text(cls, value):
        if isinstance(value, str):
            code, _, detail = value.partition(" ")
            return {"code": code, "detail": detail}
        return value

    def __str__(self):
        return self.code + (" " + self.detail if self.detail else "")


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
    top_values: list[TopValue] = []
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


class BusinessCatalog(M1Contract):
    business_id: str
    bkey: str
    db_path: str
    tables: list[TableInfo]
    data_range: DateRange | None  # union over date columns; None if no dates
    readme_text: str | None
    schema_card: str
    schema_card_sha256: str
    warnings: list[CatalogWarning] = []
    status: Literal["ready", "failed"] = "ready"
    joins: list[JoinEdge] = []
    date_columns: list[DateColumn] = []
    setup_ms: int = Field(default=0, ge=0)
    schema_card_budget_verified: bool = False
    schema_card_needs_subset: bool = False
    views: list[ViewSpec] = []
    compile_calls: list[ModelCall] = []
    semantic_annotations: SemanticAnnotations | None = None


# --------------------------------------------------------------------------- question level


class DateExpr(Contract):
    kind: Literal["date"] = "date"
    date: date


class DateRangeExpr(Contract):
    kind: Literal["date_range"] = "date_range"
    start: date
    end: date


class CalendarPeriodExpr(Contract):
    """'tháng 3/2025', 'quý 2', 'năm 2024'. ``year=None`` → year-omitted policy."""

    kind: Literal["calendar_period"] = "calendar_period"
    unit: Literal["month", "quarter", "year"]
    year: int | None = None
    index: int | None = None  # month 1-12 or quarter 1-4; None for unit=year


class RelativePeriodExpr(Contract):
    """'hôm nay' (day,0), 'hôm qua' (day,-1), 'tuần rồi' (week,-1), 'tháng này' (month,0,to_date)."""

    kind: Literal["relative_period"] = "relative_period"
    unit: Literal["day", "week", "month", "quarter", "year"]
    offset: int = Field(le=0)
    to_date: bool = True


class RollingExpr(Contract):
    """'7 ngày qua', 'N ngày gần nhất'."""

    kind: Literal["rolling"] = "rolling"
    unit: Literal["day"]  # week/month rolling windows: TASKS M2-04
    count: int = Field(ge=1)


class AllTimeExpr(Contract):
    kind: Literal["all_time"] = "all_time"


class UnsupportedExpr(Contract):
    kind: Literal["unsupported"] = "unsupported"
    reason: str = ""


TimeExpr = Annotated[
    DateExpr
    | DateRangeExpr
    | CalendarPeriodExpr
    | RelativePeriodExpr
    | RollingExpr
    | AllTimeExpr
    | UnsupportedExpr,
    Field(discriminator="kind"),
]


class TimeRef(Contract):
    span: str  # verbatim substring of the question
    role: Literal["primary", "comparison", "baseline"] = "primary"
    expr: TimeExpr


class RankingSpec(Contract):
    k: int | None = Field(default=None, ge=1)  # None → all candidates
    direction: Literal["top", "bottom"] = "top"
    criterion_text: str | None = None  # None → rulebook default criterion


class Answerability(Contract):
    status: Literal["answerable", "missing_field", "unclear"] = "answerable"
    missing_fields: list[str] = []


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


class QuestionFrame(Contract):
    """Structured reading of a question, produced by the model (SPEC §5.7, C4)."""

    expected_type: AnswerType
    metric_text: str = Field(default="", max_length=200)
    numeric_kind: NumericKind | None = None  # required for number (DC-1)
    date_granularity: DateGranularity | None = None  # required for date
    list_order: ListOrder | None = None  # required for list (DC-2)
    ranking: RankingSpec | None = None  # required iff list_order == "ranked"
    time: list[TimeRef] = Field(default=[], max_length=4)
    answerability: Answerability = Answerability()
    mentions: list[Mention] = Field(default=[], max_length=30)

    @model_validator(mode="after")
    def _invariants(self) -> QuestionFrame:
        t = self.expected_type
        if t == "number" and self.numeric_kind is None:
            raise ValueError("numeric_kind is required when expected_type is number")
        if (t == "date") != (self.date_granularity is not None):
            raise ValueError("date_granularity is required iff expected_type is date")
        if (t == "list") != (self.list_order is not None):
            raise ValueError("list_order is required iff expected_type is list")
        if (self.list_order == "ranked") != (self.ranking is not None):
            raise ValueError("ranking is required iff list_order is ranked")
        return self


class TimeWindow(Contract):
    ref_index: int
    role: Literal["primary", "comparison", "baseline"]
    start: date  # inclusive
    end: date  # inclusive
    granularity: Granularity
    coverage_ratio: float | None  # overlap with data_range / window length; None if unknown
    flags: list[str] = []

    @model_validator(mode="after")
    def _ordered(self) -> TimeWindow:
        if self.start > self.end:
            raise ValueError("TimeWindow.start must be <= end")
        return self


# --------------------------------------------------------------------------- model calls


class ModelCall(Contract):
    """One model call, captured exactly (SPEC §5.7). Errors are values, never raised."""

    call_id: str
    stage: Stage
    template_id: str
    backend: str  # "scripted" (dev only) | "http" | ...
    request_sha256: str
    params: dict[str, Any]
    content: str  # exact message content returned
    reasoning: str | None  # exact reasoning returned, or None
    finish_reason: str
    latency_ms: int = Field(ge=0)
    error: str | None = None


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
    compile_calls: list[ModelCall] = []
    warnings: list[str] = []


class SolverOutput(Contract):
    """Model output for the solve/repair stages (SPEC §7.7.3)."""

    sql: str
    notes: str = Field(default="", max_length=300)


class ExecutionResult(Contract):
    code: str  # exact executed text
    ok: bool
    error_code: str | None = None
    error_text: str | None = None
    columns: list[str] = []
    column_types: list[str] = []
    rows: list[list[Any]] = []  # Decimal / int / str / bool / date / None; never float
    row_count: int = 0
    truncated: bool = False
    duration_ms: int = 0


# --------------------------------------------------------------------------- typed values


class ScalarValue(Contract):
    type: Literal["number", "percent", "string", "boolean"]
    value: Decimal | str | bool
    numeric_kind: NumericKind | None = None  # rounding class for number values (DC-1)

    @model_validator(mode="after")
    def _match(self) -> ScalarValue:
        expected = {"number": Decimal, "percent": Decimal, "string": str, "boolean": bool}[
            self.type
        ]
        if type(self.value) is not expected:
            raise ValueError(f"{self.type} value must be {expected.__name__}")
        return self


class DateValue(Contract):
    type: Literal["date"] = "date"
    value: date
    granularity: DateGranularity


class ListItem(Contract):
    item: Decimal | str
    sort_key: Decimal | str | None = None  # ranked lists
    tie_code: str | None = None  # ranked lists: ties broken by code ascending
    position: int | None = None  # question_order lists: 1-based position


class ListValue(Contract):
    type: Literal["list"] = "list"
    order: ListOrder
    items: list[ListItem]
    numeric_kind: NumericKind | None = None  # rounding class for numeric items


class TableValue(Contract):
    type: Literal["table"] = "table"
    columns: list[str]
    rows: list[list[Decimal | str | None]]
    numeric_kind: NumericKind | None = None  # one class for all numeric cells (per-column: M2-11)


TypedValue = Annotated[
    ScalarValue | DateValue | ListValue | TableValue, Field(discriminator="type")
]


class SolverAttempt(Contract):
    attempt_no: int
    stage: Stage
    model_call: ModelCall
    solver_output: SolverOutput | None  # None if model output was invalid
    execution: ExecutionResult | None
    ok: bool
    error_code: str | None = None
    value: TypedValue | None = None  # set iff ok


class Decision(Contract):
    kind: DecisionKind
    value: TypedValue | None = None  # iff kind == "answer"
    reason_code: str
    unanswerable_reason: str | None = None
    features: dict[str, Any] = {}

    @model_validator(mode="after")
    def _value_iff_answer(self) -> Decision:
        if (self.kind == "answer") != (self.value is not None):
            raise ValueError("Decision.value is required iff kind == 'answer'")
        return self


# --------------------------------------------------------------------------- outputs


class SubmissionRecord(Contract):
    """One line of submission.jsonl (Brief §4). ``answer`` is already in wire form."""

    id: str
    type: AnswerType | Literal["unanswerable", "abstain"]
    answer: Any = None
    reason: str | None = None

    def to_wire(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "type": self.type}
        if self.type == "unanswerable":
            if self.reason is not None:
                out["reason"] = self.reason
        elif self.type != "abstain":
            out["answer"] = self.answer
        return out


class LogRecord(Contract):
    """One line of logs/questions.jsonl (Docker guide §3.3 + SPEC §8.3, P1 subset)."""

    id: str
    answer: dict[str, Any]  # the submission object without "id"
    elapsed_ms: int = Field(ge=0)
    thinking: list[str] | None  # None iff no call returned reasoning (SPEC SC-7)
    code: str | list[str] | None  # exact executed SQL, in order
    output: dict[str, Any] | str | None
    contracts_version: str = CONTRACTS_VERSION
    business_id: str
    calls: list[ModelCall] = []
    attempts: list[dict[str, Any]] = []
    windows: list[TimeWindow] = []
    decision: dict[str, Any] = {}
    entities: list[EntityCandidate] = []
    views_used: list[dict[str, str]] = []


BusinessCatalog.model_rebuild()
