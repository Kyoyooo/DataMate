"""Few-shot example bank with a leakage guard (SPEC §7.7.2, TASKS M3-10). Owner: M3.

The bank is a JSONL file built from the TRAINING split only, from questions the pipeline answered
correctly against the reference answers (``training_code/data_generation/build_fewshot.py``).
Entry: ``{entry_id, source_business_id, question, metric_text, expected_type, frame, sql}``.

Selection (deterministic, total order): score = token-set Jaccard x 100 over folded
question+metric tokens, +10 when ``expected_type`` matches; best ``k``, ties by ``entry_id``.
SPEC §7.7.2 names rapidfuzz's token_set_ratio; this dependency-free Jaccard is a stand-in with the
same role and an explicit tie-break (documented deviation).
Leakage guard: entries whose ``source_business_id`` is in ``exclude_businesses`` are never
returned (cross-validation folds).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from datamate.lexicon import fold


@dataclass(frozen=True)
class FewshotEntry:
    entry_id: str
    source_business_id: str
    question: str
    metric_text: str
    expected_type: str
    frame: dict
    sql: str

    def render(self) -> str:
        return (f"Q: {self.question}\nFRAME: {json.dumps(self.frame, ensure_ascii=False, sort_keys=True)}"
                f"\nSQL: {self.sql}\n")


def _tokens(text: str) -> set[str]:
    return set(fold(text).split())


class FewshotBank:
    def __init__(self, entries: list[FewshotEntry]):
        self.entries = sorted(entries, key=lambda e: e.entry_id)
        self._tokens = {e.entry_id: _tokens(e.question + " " + e.metric_text) for e in self.entries}

    @classmethod
    def from_file(cls, path: str | Path) -> FewshotBank:
        rows = [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]
        return cls([FewshotEntry(**r) for r in rows])

    def select(self, question: str, metric_text: str, expected_type: str, k: int,
               exclude_businesses: frozenset[str] | set[str] = frozenset()) -> list[FewshotEntry]:
        if k <= 0:
            return []
        want = _tokens(question + " " + metric_text)
        scored = []
        for e in self.entries:
            if e.source_business_id in exclude_businesses:
                continue
            have = self._tokens[e.entry_id]
            union = want | have
            score = 100.0 * len(want & have) / len(union) if union else 0.0
            if e.expected_type == expected_type:
                score += 10
            scored.append((-score, e.entry_id, e))
        scored.sort(key=lambda t: (t[0], t[1]))
        return [e for _, _, e in scored[:k]]
