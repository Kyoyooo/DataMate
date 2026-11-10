"""Result writer (SPEC §7.11, C11). Owner: M4.

The only code that writes under the result directory.
- For each question: append the log line, flush+fsync; then append the
  submission line, flush+fsync. So an answer never exists without its log.
- A second record for an id already written is rejected (E_DUPLICATE_WRITE).
- Existing ``submission.jsonl`` / ``logs/questions.jsonl`` are renamed to
  ``*.prev-<n>``, never deleted or appended to.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import IO

from datamate.contracts import LogRecord, SubmissionRecord, codes, dumps


class DuplicateWriteError(RuntimeError):
    code = codes.E_DUPLICATE_WRITE


class WriterClosedError(RuntimeError):
    """A record arrived after finalization began (late result of an abandoned question)."""


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
        self._lock = threading.Lock()  # workers write concurrently; one record at a time
        self._closed = False

    @staticmethod
    def _append(fh: IO[str], line: str) -> None:
        fh.write(line + "\n")
        fh.flush()
        os.fsync(fh.fileno())

    def write(self, record: SubmissionRecord, log: LogRecord) -> None:
        if record.id != log.id:
            raise ValueError(f"record id {record.id!r} != log id {log.id!r}")
        with self._lock:
            if self._closed:
                raise WriterClosedError("writer is closed")
            if record.id in self._written:
                raise DuplicateWriteError(f"duplicate write for id {record.id!r}")
            self._append(self._log, dumps(log.model_dump(mode="python")))
            self._append(self._sub, dumps(record.to_wire()))
            self._written.add(record.id)

    def try_write(self, record: SubmissionRecord, log: LogRecord) -> bool:
        """Write unless the id is already written or the writer is closed (late worker results)."""
        try:
            self.write(record, log)
        except (DuplicateWriteError, WriterClosedError):
            return False
        return True

    def written_ids(self) -> frozenset[str]:
        with self._lock:
            return frozenset(self._written)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._log.close()
            self._sub.close()

    def finalize_canonical(self, order: Iterable[str]) -> None:
        """Rewrite both files in ``order`` (ids not listed follow in file order).

        Records are appended in completion order while the run is live so that an early stop
        loses nothing; the final files are re-ordered so the submission bytes do not depend on
        thread scheduling or worker count (SPEC D2, D13). Atomic: temp file + rename.
        """
        self.close()
        ranking = {qid: i for i, qid in enumerate(order)}
        for path in (self.questions_log_path, self.submission_path):
            index: list[tuple[int, int, int, str]] = []  # (rank, offset, length, id)
            with open(path, "rb") as fh:
                offset = 0
                for line in fh:
                    qid = json.loads(line)["id"]
                    index.append((ranking.get(qid, len(ranking)), offset, len(line), qid))
                    offset += len(line)
            index.sort(key=lambda t: (t[0], t[1]))
            tmp = path.with_name(path.name + ".tmp")
            with open(path, "rb") as src, open(tmp, "wb") as dst:
                for _, off, length, _qid in index:
                    src.seek(off)
                    dst.write(src.read(length))
                dst.flush()
                os.fsync(dst.fileno())
            os.replace(tmp, path)

    def __enter__(self) -> ResultWriter:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
