"""L-11: the published training references against our scorer and wire contract.

Needs the competition data at ./train (git-ignored), so it skips in CI.
"""

from __future__ import annotations

import pytest

from datamate.contracts import SubmissionRecord, loads_exact
from datamate.eval.score import score_files

from conftest import REPO

ANSWERS = REPO / "train" / "answers.jsonl"

pytestmark = pytest.mark.skipif(not ANSWERS.exists(), reason="train/answers.jsonl not available")


def test_references_score_perfectly_against_themselves():
    result = score_files(ANSWERS, ANSWERS)
    assert result["n"] == 3000 and result["pa"] == 1.0


def test_every_reference_fits_the_wire_contract():
    for line in ANSWERS.read_text(encoding="utf-8").splitlines():
        r = loads_exact(line)
        SubmissionRecord(id=r["id"], type=r["type"], answer=r["answer"])
