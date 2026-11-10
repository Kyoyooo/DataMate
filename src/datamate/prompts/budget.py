"""Deterministic context reduction and per-call budgets (M3-03).

Runtime sections are reduced, not the template wording. Rulebook, question,
frame, windows, and repair history are never truncated. Full catalogs remain
unchanged for business logs. Question-specific reductions explicitly change
the prefix scope; only the normal business prefix is shared across questions.
"""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Callable
from typing import Any

from datamate.catalog import render_schema_card
from datamate.config import RunConfig
from datamate.contracts import (
    BusinessCatalog,
    ModelCall,
    PromptPlan,
    Question,
    QuestionFrame,
    SplitContext,
    Stage,
    TimeWindow,
    codes,
)
from datamate.lexicon import fold
from datamate.llm import ModelClient, TokenCounter, get_token_counter
from datamate.prompts.templates import render_parse, render_solve

BUDGET_POLICY_VERSION = "context-reduction.v1"
_README_MARKER = "\n[README truncated by prompt budget]"


def _clip_readme(text: str, budget: int, counter: TokenCounter) -> str:
    if counter.count_text(text) <= budget:
        return text
    if counter.count_text(_README_MARKER) > budget:
        return ""
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if counter.count_text(text[:mid] + _README_MARKER) <= budget:
            low = mid
        else:
            high = mid - 1
    return text[:low] + _README_MARKER


def _card(cat: BusinessCatalog, value_limit: int) -> str:
    tables = [t.model_copy(update={"columns": [c.model_copy(update={
        "top_values": c.top_values[:value_limit]}) for c in t.columns]}) for t in cat.tables]
    return render_schema_card(tables, cat.data_range, cat.warnings)


def _relevant_card(cat: BusinessCatalog, query: str, top: int, value_limit: int) -> tuple[str, list[str]]:
    tokens = set(fold(query).split())

    def rank(table: Any) -> tuple[int, str]:
        text = table.name + " " + " ".join(c.name + " " + c.original_name for c in table.columns)
        return -len(tokens & set(fold(text).split())), table.name

    tables = sorted(cat.tables, key=rank)
    chosen = tables[:top]
    temporary = cat.model_copy(update={"tables": chosen})
    card = _card(temporary, value_limit)
    omitted = sorted(t.name for t in tables[top:])
    if omitted:
        card += "OTHER TABLES (column details omitted): " + ", ".join(omitted) + "\n"
    return card, [t.name for t in chosen]


def _prepare(q: Question, cat: BusinessCatalog, cfg: RunConfig, stage: Stage,
             render: Callable[[BusinessCatalog], list[dict[str, str]]], query: str, *,
             history: list[dict[str, str]] | None = None,
             fewshots: list[dict[str, str]] | None = None,
             counter: TokenCounter | None = None) -> PromptPlan:
    counter = counter or get_token_counter(cfg)
    budget = cfg.input_budget(stage)
    settings = cfg.prompt_budget
    thinking = cfg.model.enable_thinking.get(stage, False)
    actions: list[str] = []
    source_readme = (cat.readme_text or "") if stage != "parse" else ""
    readme = _clip_readme(source_readme, settings.readme_budget_tokens, counter)
    if readme != source_readme:
        actions.append("readme_section_cap")
    card = cat.schema_card
    value_limit = 20
    for limit in (10, 5):
        if counter.count_text(card) <= settings.schema_card_budget_tokens:
            break
        card, value_limit = _card(cat, limit), limit
        actions.append(f"schema_values_{limit}")
    examples = copy.deepcopy(fewshots or [])
    suffix = copy.deepcopy(history or [])

    def messages() -> list[dict[str, str]]:
        prepared_cat = cat.model_copy(update={"readme_text": readme or None, "schema_card": card})
        base = render(prepared_cat)
        return base[:-1] + examples + base[-1:] + suffix

    prepared = messages()
    initial_tokens = counter.count_messages(prepared, thinking=thinking)
    tokens = initial_tokens
    while examples and tokens > budget:
        examples.pop()
        actions.append("drop_last_fewshot")
        prepared = messages()
        tokens = counter.count_messages(prepared, thinking=thinking)
    dynamic_prefix = False
    if tokens > budget and readme and stage != "parse":
        # The complete conversation is counted after each deterministic halving.
        readme_limit = counter.count_text(readme)
        while readme and tokens > budget:
            readme_limit //= 2
            readme = _clip_readme(source_readme, readme_limit, counter)
            actions.append(f"reduce_readme_{readme_limit}")
            prepared = messages()
            tokens = counter.count_messages(prepared, thinking=thinking)
        dynamic_prefix = True
    selected: list[str] = []
    if tokens > budget or counter.count_text(card) > settings.schema_card_budget_tokens:
        card, selected = _relevant_card(cat, query, settings.relevant_tables, value_limit)
        actions.append("schema_relevant_subset")
        dynamic_prefix = True
        prepared = messages()
        tokens = counter.count_messages(prepared, thinking=thinking)
    overflow = tokens > budget or counter.count_text(card) > settings.schema_card_budget_tokens
    prefix = prepared[0]["content"]
    diagnostics = {
        "policy": BUDGET_POLICY_VERSION, "stage": stage,
        "counter": counter.fingerprint, "input_tokens": tokens, "initial_input_tokens": initial_tokens,
        "input_limit": budget, "max_model_len": cfg.serving.max_model_len,
        "max_output_tokens": cfg.model.max_tokens[stage],
        "safety_margin_tokens": settings.safety_margin_tokens,
        "readme_tokens": counter.count_text(readme), "schema_tokens": counter.count_text(card),
        "history_messages": len(suffix), "fewshots_kept": len(examples), "actions": actions,
        "selected_tables": selected, "prefix_scope": "reduced" if dynamic_prefix else "business",
        "prefix_sha256": hashlib.sha256(prefix.encode("utf-8")).hexdigest(), "client_called": False,
    }
    return PromptPlan(messages=prepared, diagnostics=diagnostics,
                      error_code=codes.E_CONTEXT_OVERFLOW if overflow else None)


def prepare_parse(q: Question, split: SplitContext, cat: BusinessCatalog, cfg: RunConfig, *,
                  counter: TokenCounter | None = None) -> PromptPlan:
    return _prepare(q, cat, cfg, "parse", lambda c: render_parse(q, split, c), q.question,
                    counter=counter)


def prepare_solve(q: Question, frame: QuestionFrame, windows: list[TimeWindow], split: SplitContext,
                  cat: BusinessCatalog, cfg: RunConfig, *, stage: Stage = "solve",
                  history: list[dict[str, str]] | None = None,
                  fewshots: list[dict[str, str]] | None = None,
                  counter: TokenCounter | None = None) -> PromptPlan:
    return _prepare(q, cat, cfg, stage, lambda c: render_solve(q, frame, windows, split, c),
                    q.question + " " + frame.metric_text, history=history,
                    fewshots=fewshots, counter=counter)


def complete_prompt(plan: PromptPlan, client: ModelClient, cfg: RunConfig, *, stage: Stage,
                    template_id: str, json_schema: dict[str, Any], call_id: str) -> ModelCall:
    """A local overflow record explicitly says not_sent; no model output is fabricated."""
    if plan.error_code:
        return ModelCall(call_id=call_id, stage=stage, template_id=template_id,
                         backend=client.backend, request_sha256="", params={}, content="",
                         reasoning=None, finish_reason="not_sent", latency_ms=0,
                         error=plan.error_code, prompt_budget=plan.diagnostics)
    call = client.complete(stage=stage, template_id=template_id, messages=plan.messages,
                           json_schema=json_schema, max_tokens=cfg.model.max_tokens[stage],
                           call_id=call_id)
    return call.model_copy(update={"prompt_budget": {**plan.diagnostics, "client_called": True}})
