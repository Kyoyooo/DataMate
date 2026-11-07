"""Result writer (SPEC §7.11, C11). Owner: M4.

The only code that writes under the result directory.
- For each question: append the log line, flush+fsync; then append the
  submission line, flush+fsync. So an answer never exists without its log.
- A second record for an id already written is rejected (E_DUPLICATE_WRITE).
- Existing ``submission.jsonl`` / ``logs/questions.jsonl`` are renamed to
  ``*.prev-<n>``, never deleted or appended to.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import IO

from datamate.contracts import LogRecord, SubmissionRecord, codes, dumps


class DuplicateWriteError(RuntimeError):
    code = codes.E_DUPLICATE_WRITE


def _rotate(path: Path) -> None:
    if not path.exists():
        return
    n = 1
    while path.with_name(f"{path.name}.prev-{n}").exists():
        n += 1
    path.rename(path.with_name(f"{path.name}.prev-{n}"))


class ResultWriter:
    def __init__(self, result_dir: Path):
        self.result_dir = result_dir
        self.logs_dir = result_dir / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.submission_path = result_dir / "submission.jsonl"
        self.questions_log_path = self.logs_dir / "questions.jsonl"
        _rotate(self.submission_path)
        _rotate(self.questions_log_path)
        self._sub: IO[str] = open(self.submission_path, "a", encoding="utf-8", newline="\n")
        self._log: IO[str] = open(self.questions_log_path, "a", encoding="utf-8", newline="\n")
        self._written: set[str] = set()

    @staticmethod
    def _append(fh: IO[str], line: str) -> None:
        fh.write(line + "\n")
        fh.flush()
        os.fsync(fh.fileno())

    def write(self, record: SubmissionRecord, log: LogRecord) -> None:
        if record.id != log.id:
            raise ValueError(f"record id {record.id!r} != log id {log.id!r}")
        if record.id in self._written:
            raise DuplicateWriteError(f"duplicate write for id {record.id!r}")
        self._append(self._log, dumps(log.model_dump(mode="python")))
        self._append(self._sub, dumps(record.to_wire()))
        self._written.add(record.id)

    def written_ids(self) -> frozenset[str]:
        return frozenset(self._written)

    def close(self) -> None:
        self._log.close()
        self._sub.close()

    def __enter__(self) -> ResultWriter:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
