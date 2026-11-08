"""Prompt templates (SPEC §7.13.5). Owner: M3.

Templates are plain Python format strings (no Jinja2 dependency yet). Rules:
- Any wording change creates a new template id suffix (``.v2``); the SHA-256 of
  every template is recorded in run.json so runs can be compared.
- Templates must not contain business- or question-specific content; all such
  content arrives through the render arguments.
- Sections that are identical for every question of a business come first so a
  serving prefix cache can reuse them (SPEC §7.7.1).

The v1 wording is a minimal baseline written for the bootstrap; improving it
against the training split is TASKS M3-04/M3-05.
"""

from __future__ import annotations

import hashlib

from datamate.contracts import BusinessCatalog, Question, QuestionFrame, SplitContext, TimeWindow

PARSE_SYSTEM_V2 = """You read Vietnamese business questions and return a JSON object describing them.
Follow the JSON schema exactly. Do not answer the question and do not compute dates.

Field guide:
- expected_type: one of number, percent, string, date, boolean, list, table.
- numeric_kind (required for number): "money" for VND amounts (including averages of money),
  "count" for counts of orders/items/customers, "measure" for other quantities.
- date_granularity (required for date): "day", or "month" when the answer is a month.
- list_order (required for list): "ranked" for top-k / ranking / "liệt kê" lists;
  "question_order" when the question names the elements in a fixed order
  (e.g. several months "lần lượt", or "mấy hộp chẵn, mấy viên lẻ").
- ranking (required iff list_order is ranked): k (null = all), direction (top|bottom), criterion_text.
- time: each time expression with its verbatim span copied from the question and a structured expr:
  {{"kind":"date","date":"YYYY-MM-DD"}}, {{"kind":"date_range","start":...,"end":...}},
  {{"kind":"calendar_period","unit":"month|quarter|year","year":2025|null,"index":3|null}},
  {{"kind":"relative_period","unit":"day|week|month|quarter|year","offset":0|-1|...,"to_date":true|false}},
  {{"kind":"rolling","unit":"day|week|month","count":N}},
  {{"kind":"same_period_prior_year","ref":0}}, {{"kind":"same_days_previous_month","ref":0}},
  {{"kind":"all_time"}}, {{"kind":"unsupported","reason":"..."}}.
  Use ISO dates for explicit years. For any date or range endpoint without a year, emit
  {{"month":3,"day":5,"year":null}} as its value. Leave year inference to the resolver.
  "Tháng trước" is a calendar-relative month; "N tháng gần nhất" is rolling.
  Comparison ref is the zero-based index of the source expression in time. Include the source
  separately. Use same_days_previous_month only for a source from day 1 through a day in that month.
  role is "primary", or "comparison"/"baseline" for the period compared against.
- answerability: "missing_field" with the missing information names when the data clearly cannot
  contain what the question needs; otherwise "answerable".

RULEBOOK (authoritative business rules for this split):
{rulebook}

DATA SCHEMA:
{schema_card}"""

PARSE_USER_V2 = """as_of_date (today): {as_of_date}
QUESTION: {question}"""

SOLVE_SYSTEM_V1 = """You write one DuckDB SQL SELECT statement that answers a Vietnamese business question.
Return JSON: {{"sql": "...", "notes": "..."}}.

Rules:
- Exactly one SELECT (WITH allowed). Only the tables below. No LIMIT without ORDER BY.
- Apply the rulebook definitions (valid orders, revenue, ranking criteria) unless the question says otherwise.
- Use the resolved date windows given with the question as literal inclusive dates. Ignore records after as_of_date.
- Do not round; the formatter rounds. Percent values are in percent units (12.5 means 12.5%).
- If no rows match, return NULL unless the quantity is legitimately zero (e.g. COALESCE(SUM(...), 0)
  for "how many sold" over a period that has data).

Result shape by expected type:
- number, percent, string, boolean: one row, one column named value.
- date: one row, column value of type DATE (day) or text 'YYYY-MM' (month).
- list, ranked: one row per candidate with columns item, sort_key, tie_code (the entity code, or NULL);
  return all candidates — ordering and top-k truncation are applied afterwards.
- list, question_order: columns ord (1-based position in the question) and item.
- table: first column is the entity name, then one column per requested measure in question order.

RULEBOOK:
{rulebook}

README:
{readme}

DATA SCHEMA:
{schema_card}"""

SOLVE_USER_V1 = """as_of_date (today): {as_of_date}
QUESTION: {question}
QUESTION FRAME: {frame_json}
RESOLVED WINDOWS (inclusive):
{windows}"""

REPAIR_USER_V1 = """The previous answer failed: {error_code}
{error_text}
Return corrected JSON with the same schema."""

TEMPLATES: dict[str, tuple[str, ...]] = {
    "parse.frame.v2": (PARSE_SYSTEM_V2, PARSE_USER_V2),
    "solve.sql.v1": (SOLVE_SYSTEM_V1, SOLVE_USER_V1),
    "repair.sql.v1": (REPAIR_USER_V1,),
}


def template_sha256() -> dict[str, str]:
    return {
        tid: hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()
        for tid, parts in sorted(TEMPLATES.items())
    }


def render_parse(q: Question, split: SplitContext, cat: BusinessCatalog) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": PARSE_SYSTEM_V2.format(
            rulebook=split.rulebook_text, schema_card=cat.schema_card)},
        {"role": "user", "content": PARSE_USER_V2.format(
            as_of_date=q.as_of_date.isoformat(), question=q.question)},
    ]


def _windows_text(windows: list[TimeWindow]) -> str:
    if not windows:
        return "(none: no time constraint)"
    return "\n".join(
        f"- [{w.ref_index}] {w.role}: {w.start.isoformat()} .. {w.end.isoformat()} ({w.granularity})"
        for w in windows
    )


def render_solve(q: Question, frame: QuestionFrame, windows: list[TimeWindow],
                 split: SplitContext, cat: BusinessCatalog) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SOLVE_SYSTEM_V1.format(
            rulebook=split.rulebook_text, readme=cat.readme_text or "(none)",
            schema_card=cat.schema_card)},
        {"role": "user", "content": SOLVE_USER_V1.format(
            as_of_date=q.as_of_date.isoformat(), question=q.question,
            frame_json=frame.model_dump_json(), windows=_windows_text(windows))},
    ]


def render_repair(messages: list[dict[str, str]], previous_content: str, error_code: str,
                  error_text: str | None) -> list[dict[str, str]]:
    return messages + [
        {"role": "assistant", "content": previous_content},
        {"role": "user", "content": REPAIR_USER_V1.format(
            error_code=error_code, error_text=error_text or "")},
    ]
