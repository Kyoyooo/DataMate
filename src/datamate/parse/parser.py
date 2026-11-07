"""Question parser (SPEC §7.4, C4). Owner: M3.

One model call returns a ``QuestionFrame`` as JSON. Invalid output is not
retried in P1: the question abstains with E_PARSE_INVALID. Every time span must
appear in the question (compared after ``fold``); a span the model invented is
treated as invalid output rather than silently dropped, because dropping a
time constraint would change the meaning of the question.

Deferred (TASKS M3-04): abbreviation normalization ("dthu", "sp", "dc"),
JSON-schema-constrained decoding, few-shot examples.
"""

from __future__ import annotations

from pydantic import ValidationError

from datamate.config import RunConfig
from datamate.contracts import (
    BusinessCatalog,
    ModelCall,
    Question,
    QuestionFrame,
    SplitContext,
    codes,
)
from datamate.lexicon import fold
from datamate.llm import ModelClient
from datamate.prompts import render_parse

TEMPLATE_ID = "parse.frame.v1"


def parse_question(q: Question, split: SplitContext, cat: BusinessCatalog, client: ModelClient,
                   cfg: RunConfig) -> tuple[QuestionFrame | None, ModelCall, str | None]:
    """Return (frame, call, error_code). ``frame`` is None iff ``error_code`` is set."""
    call = client.complete(
        stage="parse", template_id=TEMPLATE_ID, messages=render_parse(q, split, cat),
        json_schema=QuestionFrame.model_json_schema(),
        max_tokens=cfg.model.max_tokens["parse"], call_id=f"{q.id}:parse:1",
    )
    if call.error:
        return None, call, call.error
    try:
        frame = QuestionFrame.model_validate_json(call.content)
    except ValidationError:
        return None, call, codes.E_PARSE_INVALID
    folded_q = fold(q.question)
    if any(fold(ref.span) not in folded_q for ref in frame.time):
        return None, call, codes.E_PARSE_INVALID
    return frame, call, None
