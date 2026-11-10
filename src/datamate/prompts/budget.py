"""Context budgeting (SPEC §7.7.1, TASKS M3-03). Owner: M3.

The system prompt (instructions + rulebook + README + SchemaCard) is shared by every
question of a business, so a serving prefix cache can reuse it. Budgeting never touches the
rulebook (authoritative, never truncated). When the whole context exceeds
``solver.context_budget_tokens`` the reduction order is fixed and deterministic:

  1. few-shot examples, last first            (question-dependent section)
  2. README: head-truncated to ``readme_budget_tokens`` first, then dropped
  3. SchemaCard relevant-table subset         (``schema_subset``: supplied by M1's
                                               ``select_schema_context``; not duplicated here)
  4. ``E_CONTEXT_OVERFLOW`` → the question abstains

``schema_fn`` (optional) returns the question's SchemaCard text within its own budget; M1's
``select_schema_context`` fits this slot. The README truncation is business-level (same bytes for
every question of the business); the SchemaCard result may be question-level when subsetting.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from datamate.config import SolverConfig
from datamate.contracts import BusinessCatalog, Question, SplitContext
from datamate.llm.tokenizer import Tokenizer, count_tokens
from datamate.prompts.templates import render_solve_system

README_MARKER = "\n[... README truncated to fit the context budget ...]"
SchemaFn = Callable[[BusinessCatalog, str], str]


class ContextOverflow(ValueError):
    """Even the smallest context exceeds the budget (reason code E_CONTEXT_OVERFLOW)."""


@dataclass(frozen=True)
class ContextPlan:
    catalog: BusinessCatalog  # copy carrying the budgeted readme_text and schema_card
    fewshot: list[str]
    system_tokens: int
    total_tokens: int
    reductions: list[str] = field(default_factory=list)
    tokenizer: str = ""


def truncate_head(text: str, tok: Tokenizer, max_tokens: int, marker: str = README_MARKER) -> str:
    """Longest prefix of ``text`` + marker that fits in ``max_tokens`` (binary search on chars)."""
    if count_tokens(tok, text) <= max_tokens:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if count_tokens(tok, text[:mid] + marker) <= max_tokens:
            lo = mid
        else:
            hi = mid - 1
    return (text[:lo] + marker) if count_tokens(tok, text[:lo] + marker) <= max_tokens else ""


class ContextBuilder:
    def __init__(self, tok: Tokenizer, cfg: SolverConfig, *, schema_fn: SchemaFn | None = None,
                 schema_subset_fn: SchemaFn | None = None):
        self.tok, self.cfg = tok, cfg
        self._schema_fn, self._subset_fn = schema_fn, schema_subset_fn
        self._readme_cache: dict[tuple[str, int], str] = {}

    def _readme(self, cat: BusinessCatalog) -> str | None:
        if not cat.readme_text:
            return None
        key = (cat.business_id, hash(cat.readme_text))
        if key not in self._readme_cache:  # benign race: identical value computed twice
            self._readme_cache[key] = truncate_head(cat.readme_text, self.tok,
                                                    self.cfg.readme_budget_tokens)
        return self._readme_cache[key] or None

    def _system_tokens(self, split: SplitContext, cat: BusinessCatalog) -> int:
        template = "solve.sql.v2" if self.cfg.template_version == "v2" else "solve.sql.v1"
        return count_tokens(self.tok, render_solve_system(split, cat, template))

    def fit_fewshot(self, plan: ContextPlan, blocks: list[str]) -> list[str]:
        """Few-shot blocks chosen after parsing: keep the longest prefix that still fits (SPEC §7.7.1)."""
        kept = list(blocks[: self.cfg.fewshot_k])
        base = plan.system_tokens + self.cfg.question_block_reserve_tokens
        while kept and base + sum(count_tokens(self.tok, b) for b in kept) > self.cfg.context_budget_tokens:
            kept.pop()
        return kept

    def plan(self, q: Question, split: SplitContext, cat: BusinessCatalog,
             fewshot: list[str] | None = None) -> ContextPlan:
        budget, reserve = self.cfg.context_budget_tokens, self.cfg.question_block_reserve_tokens
        shots = list((fewshot or [])[: self.cfg.fewshot_k])
        reductions: list[str] = []
        readme = self._readme(cat)
        if cat.readme_text and readme != cat.readme_text:
            reductions.append("readme_truncated" if readme else "readme_dropped")
        card = self._schema_fn(cat, q.question) if self._schema_fn else cat.schema_card
        if card != cat.schema_card:
            reductions.append("schema_card_budgeted")

        def ctx(readme_text: str | None, card_text: str) -> BusinessCatalog:
            return cat.model_copy(update={"readme_text": readme_text, "schema_card": card_text})

        def total() -> tuple[int, int]:
            sys_tokens = self._system_tokens(split, ctx(readme, card))
            return sys_tokens, sys_tokens + reserve + sum(count_tokens(self.tok, s) for s in shots)

        sys_tokens, tot = total()
        while tot > budget:
            if shots:
                shots.pop()
                reductions.append("fewshot_dropped")
            elif readme:
                readme = None
                reductions.append("readme_dropped")
            elif self._subset_fn is not None and "schema_subset" not in reductions:
                card = self._subset_fn(cat, q.question)
                reductions.append("schema_subset")
            else:
                raise ContextOverflow(
                    f"context needs {tot} tokens > budget {budget} after {reductions or 'no'} "
                    "reductions")
            sys_tokens, tot = total()
        return ContextPlan(ctx(readme, card), shots, sys_tokens, tot, reductions, self.tok.name)
