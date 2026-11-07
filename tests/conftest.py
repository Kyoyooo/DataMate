"""Shared test helpers. Fixture data lives in tests/fixtures/ (see its README)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from datamate.catalog import setup_business
from datamate.config import RunConfig, load_config
from datamate.contracts import BusinessCatalog, Question, SplitContext
from datamate.llm import ScriptedModelClient
from datamate.rules import load_split
from datamate.runtime import answer_question

REPO = Path(__file__).resolve().parents[1]
SPLIT = REPO / "tests" / "fixtures" / "split_mini"
SCRIPT = REPO / "tests" / "fixtures" / "scripted" / "split_mini.jsonl"
AS_OF = date(2026, 3, 4)


@pytest.fixture
def cfg(tmp_path: Path) -> RunConfig:
    return load_config(None, [f"work_dir={tmp_path / 'work'}", "model.backend=scripted",
                              f"model.script_path={SCRIPT}"])


@pytest.fixture
def split() -> SplitContext:
    return load_split(SPLIT)


@pytest.fixture
def catalog(tmp_path: Path) -> BusinessCatalog:
    return setup_business(SPLIT / "data" / "biz_fx01", "biz_fx01", tmp_path / "work")


def question(text: str, qid: str = "t_q1", as_of: date = AS_OF) -> Question:
    return Question(id=qid, business_id="biz_fx01", question=text, as_of_date=as_of, line_no=1)


def scripted(text: str, parse: dict | str, *solves: dict | str) -> ScriptedModelClient:
    """Client with one parse response and solve/repair responses in order."""
    def content(x: dict | str) -> str:
        return x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)

    entries = [{"stage": "parse", "question": text, "content": content(parse)}]
    for i, s in enumerate(solves):
        entries.append({"stage": "solve" if i == 0 else "repair", "question": text,
                        "content": content(s)})
    return ScriptedModelClient(entries)


def run_one(text: str, parse: dict | str, *solves: dict | str, cfg: RunConfig,
            split: SplitContext, catalog: BusinessCatalog):
    """Answer one question on the fixture business; returns (wire submission, log)."""
    client = scripted(text, parse, *solves)
    record, log = answer_question(question(text), split, catalog, client, cfg)
    return record.to_wire(), log
