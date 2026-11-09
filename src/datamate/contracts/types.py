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

import re
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CONTRACTS_VERSION = "1.4.0"  # additive M3-02 ModelCall transport evidence (on top of 1.3.0)


class Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


AnswerType = Literal["number", "percent", "string", "date", "boolean", "list", "table"]
DecisionKind = Literal["answer", "unanswerable", "abstain"]
DateGranularity = Literal["day", "month"]
Granularity = Literal["day", "week", "month", "quarter", "year", "range"]
Stage = Literal["rule_profile", "parse", "solve", "repair"]
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


class ParamProvenance(Contract):
    source: Literal["rulebook", "generic"]
    span: str | None = None  # verbatim rulebook quote when source == "rulebook"


class TemporalParams(Contract):
    """Time conventions of the active split (SPEC §5.5).

    Defaults are generic ISO conventions, *not* values learned from the training
    rulebook. Extraction from the mounted rulebook is TASKS M2-05 and validates
    field by field, so provenance is per field; a field absent from
    ``provenance`` is generic.
    """

    week_start: Literal["mon", "sun"] = "mon"
    to_date_end: Literal["as_of", "day_before_as_of"] = "as_of"
    rolling_includes_as_of: bool = True
    prior_period_full: bool = True
    year_omitted_policy: Literal["most_recent_not_after_as_of"] = "most_recent_not_after_as_of"
    same_period_alignment: Literal["calendar_dates", "elapsed_days"] = "calendar_dates"
    provenance: dict[str, ParamProvenance] = {}

    def uses_generic(self) -> bool:
        """True if any parameter did not come from the mounted rulebook."""
        names = type(self).model_fields.keys() - {"provenance"}
        return any(n not in self.provenance or self.provenance[n].source == "generic"
                   for n in names)


class CalendarDiagnostic(Contract):
    code: str
    row: int | None = None
    message: str


class SplitContext(Contract):
    rulebook_text: str  # verbatim, NFC
    rulebook_sha256: str
    temporal: TemporalParams
    calendar_path: str | None
    calendar_ok: bool = False
    calendar_diagnostic: CalendarDiagnostic | None = None
    rule_profile_calls: list[ModelCall] = Field(default_factory=list)
    temporal_diagnostics: dict[str, str] = Field(default_factory=dict)
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


class ColumnInfo(Contract):
    name: str  # SQL identifier (ASCII, folded; SPEC SC-2)
    original_name: str  # header exactly as found
    sql_type: str  # BIGINT | DECIMAL(38,6) | DATE | VARCHAR
    null_count: int
    distinct_count: int
    min: str | None = None
    max: str | None = None
    top_values: list[tuple[str, int]] = []  # only for low-cardinality text columns


class TableInfo(Contract):
    name: str
    source_file: str  # relative to the business directory
    row_count: int
    columns: list[ColumnInfo]


class BusinessCatalog(Contract):
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


# --------------------------------------------------------------------------- question level


class MonthDay(Contract):
    """A calendar date whose year was omitted from the question."""

    month: int = Field(ge=1, le=12)
    day: int = Field(ge=1, le=31)
    year: None = None

    @model_validator(mode="after")
    def _valid_month_day(self) -> MonthDay:
        date(2000, self.month, self.day)  # Leap year: allow February 29.
        return self


class DateExpr(Contract):
    kind: Literal["date"] = "date"
    date: date


class DateRangeExpr(Contract):
    kind: Literal["date_range"] = "date_range"
    start: date
    end: date


class YearlessDateExpr(Contract):
    kind: Literal["yearless_date"] = "yearless_date"
    date: MonthDay


class YearlessDateRangeExpr(Contract):
    kind: Literal["yearless_date_range"] = "yearless_date_range"
    start: date | MonthDay
    end: date | MonthDay

    @model_validator(mode="after")
    def _has_yearless_endpoint(self) -> YearlessDateRangeExpr:
        if isinstance(self.start, date) and isinstance(self.end, date):
            raise ValueError("yearless_date_range requires at least one yearless endpoint")
        return self


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
    """Consecutive days, weeks or months ending on or just before as_of_date."""

    kind: Literal["rolling"] = "rolling"
    unit: Literal["day", "week", "month"]
    count: int = Field(ge=1)


class SamePeriodPriorYearExpr(Contract):
    kind: Literal["same_period_prior_year"] = "same_period_prior_year"
    ref: int = Field(ge=0)


class SameDaysPreviousMonthExpr(Contract):
    kind: Literal["same_days_previous_month"] = "same_days_previous_month"
    ref: int = Field(ge=0)


class AllTimeExpr(Contract):
    kind: Literal["all_time"] = "all_time"


class UnsupportedExpr(Contract):
    kind: Literal["unsupported"] = "unsupported"
    reason: str = ""


TimeExpr = Annotated[
    DateExpr
    | DateRangeExpr
    | YearlessDateExpr
    | YearlessDateRangeExpr
    | CalendarPeriodExpr
    | RelativePeriodExpr
    | RollingExpr
    | SamePeriodPriorYearExpr
    | SameDaysPreviousMonthExpr
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
    transport: dict[str, Any] | None = None  # optional HTTP request/response/error evidence


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
        expected = {"number": Decimal, "percent": Decimal, "string": str, "boolean": bool}[self.type]
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


_WIRE_DATE = re.compile(r"\d{4}-\d{2}(-\d{2})?")


class SubmissionRecord(Contract):
    """One line of submission.jsonl (Brief §4). ``answer`` is already in wire form."""

    id: str
    type: AnswerType | Literal["unanswerable", "abstain"]
    answer: Any = None
    reason: str | None = None

    @model_validator(mode="after")
    def _wire_shape(self) -> SubmissionRecord:
        """Each type has exactly one wire format; a wrong format scores as wrong (Brief §4)."""
        t, a = self.type, self.answer
        if t in ("unanswerable", "abstain"):
            if a is not None or (t == "abstain" and self.reason is not None):
                raise ValueError(f"{t} records carry no answer")
            return self
        if self.reason is not None:
            raise ValueError("reason is only valid for unanswerable")

        def is_num(x: Any) -> bool:
            return isinstance(x, (int, Decimal)) and not isinstance(x, bool)

        if t in ("number", "percent"):
            ok = is_num(a)
        elif t == "string":
            ok = isinstance(a, str)
        elif t == "date":
            ok = isinstance(a, str) and _WIRE_DATE.fullmatch(a) is not None
        elif t == "boolean":
            ok = isinstance(a, bool)
        elif t == "list":
            ok = isinstance(a, list) and all(isinstance(x, str) or is_num(x) for x in a)
        else:  # table
            ok = (isinstance(a, dict) and set(a) == {"columns", "rows"}
                  and isinstance(a["columns"], list) and isinstance(a["rows"], list)
                  and all(isinstance(r, list) and len(r) == len(a["columns"])
                          and all(c is None or isinstance(c, str) or is_num(c) for c in r)
                          for r in a["rows"]))
        if not ok:
            raise ValueError(f"answer is not a valid wire value for type {t}: {a!r}")
        return self

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
