"""Result writer and input loading (M4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from datamate.contracts import LogRecord, SubmissionRecord
from datamate.run import load_questions
from datamate.runtime import DuplicateWriteError, ResultWriter


def _pair(qid: str, value: int = 1):
    rec = SubmissionRecord(id=qid, type="number", answer=value)
    log = LogRecord(id=qid, answer={"type": "number", "answer": value}, elapsed_ms=1,
                    thinking=None, code=None, output=None, business_id="b")
    return rec, log


def _lines(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


def test_duplicate_submission_is_rejected(tmp_path):
    with ResultWriter(tmp_path) as w:
        w.write(*_pair("q1", 1))
        with pytest.raises(DuplicateWriteError):
            w.write(*_pair("q1", 2))
        assert w.written_ids() == frozenset({"q1"})
    assert _lines(tmp_path / "submission.jsonl") == [{"id": "q1", "type": "number", "answer": 1}]
    assert len(_lines(tmp_path / "logs" / "questions.jsonl")) == 1


def test_existing_outputs_are_rotated_not_overwritten(tmp_path):
    with ResultWriter(tmp_path) as w:
        w.write(*_pair("q1"))
    with ResultWriter(tmp_path) as w:
        w.write(*_pair("q2"))
    assert [r["id"] for r in _lines(tmp_path / "submission.jsonl")] == ["q2"]
    assert [r["id"] for r in _lines(tmp_path / "submission.jsonl.prev-1")] == ["q1"]


def test_log_is_persisted_before_submission(tmp_path, monkeypatch):
    with ResultWriter(tmp_path) as w:
        order: list[str] = []
        real = w._append
        monkeypatch.setattr(w, "_append", lambda fh, line: (order.append(fh.name), real(fh, line)))
        w.write(*_pair("q1"))
    assert order == [str(tmp_path / "logs" / "questions.jsonl"), str(tmp_path / "submission.jsonl")]


def test_duplicate_and_invalid_input_lines(tmp_path):
    p = tmp_path / "questions.jsonl"
    rows = [
        {"id": "q1", "business_id": "b", "question": "a", "as_of_date": "2026-03-04"},
        {"id": "q1", "business_id": "b", "question": "dup", "as_of_date": "2026-03-04"},
        {"id": "q2", "business_id": "b", "question": "bad date", "as_of_date": "04/03/2026"},
        {"business_id": "b", "question": "no id"},
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n{broken\n", encoding="utf-8")
    valid, invalid, counts = load_questions(p)
    assert [q.id for q in valid] == ["q1"] and valid[0].question == "a"
    assert invalid == [("q2", "b", "E_INPUT_INVALID")]
    assert counts == {"ignored_duplicate_id": 1, "skipped_missing_id": 1, "skipped_invalid_json": 1}
