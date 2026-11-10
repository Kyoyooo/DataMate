"""Concurrent orchestrator (SPEC §7.12, TASKS M4-05). Owner: M4.

Layout: one queue and ``concurrency.questions_per_replica`` worker threads per
replica; businesses are assigned to replicas before any work starts and set up in
a thread pool; a business's questions are enqueued on its replica when its
catalog is ready. The model client is synchronous (DC-5), so each worker thread
simply blocks on HTTP calls.

Timing: ``elapsed_ms`` of a question starts when a worker takes it (inside
``answer_question``), so queue waiting and business setup are shared costs that
are logged separately (setup_ms, run.json), as the Docker guide §3.3 allows.

Determinism: assignment, setup order and per-replica queue order are fixed.
Records are written the moment a question finishes (an early stop loses
nothing); the caller then calls ``ResultWriter.finalize_canonical`` so the final
files do not depend on thread scheduling.

Stops: ``request_stop`` (SIGTERM) and ``deadlines.global_hard_stop_s`` end the
run; every unwritten id gets ``abstain`` (E_GLOBAL_STOP). In-flight model calls
are capped by the question deadline, so threads finish soon after; workers are
daemon threads and results that arrive after finalization are dropped.
"""

from __future__ import annotations

import queue
import threading
import time
from collections import Counter, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from datamate.config import RunConfig
from datamate.contracts import (
    BusinessCatalog,
    LogRecord,
    Question,
    SplitContext,
    SubmissionRecord,
    codes,
)
from datamate.llm import ModelClient
from datamate.prompts.budget import ContextBuilder
from datamate.runtime.pipeline import answer_question
from datamate.runtime.promptstore import PromptBlobStore
from datamate.runtime.writer import ResultWriter

SetupFn = Callable[[str], "tuple[BusinessCatalog | None, str | None]"]
TICK_S = 0.05


class ReplicaSupervisor(Protocol):
    """The part of ``llm.replicas.ReplicaManager`` the orchestrator uses."""

    def poll(self) -> list[int]: ...
    def restart(self, index: int) -> bool: ...


def assign_businesses(counts: dict[str, int], replicas: int) -> dict[str, int]:
    """SPEC §7.12-1,2: order by (count desc, id asc); give each business to the replica with
    the smaller assigned question total (tie → lower index)."""
    totals = [0] * replicas
    out: dict[str, int] = {}
    for biz in sorted(counts, key=lambda b: (-counts[b], b)):
        i = min(range(replicas), key=lambda r: (totals[r], r))
        out[biz] = i
        totals[i] += counts[biz]
    return out


class QuestionDeadline:
    """Soft/hard deadline of one question; the hard deadline is capped by the global stop."""

    def __init__(self, clock: Callable[[], float], started: float, soft_s: float, hard_s: float,
                 global_stop_at: float, stop: threading.Event, degrade: threading.Event):
        self._clock, self._soft_at = clock, started + soft_s
        self._hard_at = min(started + hard_s, global_stop_at)
        self._global_stop_at, self._stop, self._degrade = global_stop_at, stop, degrade

    @property
    def soft_expired(self) -> bool:
        return self._clock() >= self._soft_at or self.hard_expired

    @property
    def hard_expired(self) -> bool:
        return self._stop.is_set() or self._clock() >= self._hard_at

    @property
    def degrade(self) -> bool:
        return self._degrade.is_set()

    @property
    def stop_reason_code(self) -> str:
        stopped = self._stop.is_set() or self._clock() >= self._global_stop_at
        return codes.E_GLOBAL_STOP if stopped else codes.E_DEADLINE

    def remaining_s(self) -> float:
        return max(0.0, self._hard_at - self._clock())


@dataclass
class OrchestratorStats:
    assignment: dict[str, int] = field(default_factory=dict)
    catalogs: dict[str, BusinessCatalog | None] = field(default_factory=dict)
    setup_ms: dict[str, int] = field(default_factory=dict)
    outcome: Counter[str] = field(default_factory=Counter)
    reasons: Counter[str] = field(default_factory=Counter)
    errors: list[str] = field(default_factory=list)
    stop_reason: str | None = None  # None | "global_stop" | "sigterm" | "replicas_down"
    degrade_activated_ms: int | None = None
    first_answer_ms: int | None = None
    total_ms: int = 0
    replica_events: list[dict[str, Any]] = field(default_factory=list)
    questions_per_replica: list[int] = field(default_factory=list)  # answered by each replica


class Orchestrator:
    def __init__(self, *, cfg: RunConfig, split: SplitContext, questions: list[Question],
                 clients: list[ModelClient], writer: ResultWriter, setup: SetupFn,
                 supervisor: ReplicaSupervisor | None = None,
                 clock: Callable[[], float] = time.monotonic, t0: float | None = None,
                 progress_log: Path | None = None, blobs: PromptBlobStore | None = None,
                 context: ContextBuilder | None = None):
        self.cfg, self.split, self.questions = cfg, split, list(questions)
        self.clients, self.writer, self._setup = clients, writer, setup
        self._supervisor, self._clock = supervisor, clock
        self._t0 = clock() if t0 is None else t0
        self._progress_log, self._blobs, self._context = progress_log, blobs, context
        n = len(clients)
        self._queues: list[queue.Queue[tuple[Question, BusinessCatalog | None, str | None]]] = [
            queue.Queue() for _ in range(n)]
        self._up = [threading.Event() for _ in range(n)]
        for e in self._up:
            e.set()
        self._dead = [False] * n
        self._handling: set[int] = set()
        self._stop, self._degrade, self._done = threading.Event(), threading.Event(), threading.Event()
        self._lock = threading.Lock()
        self._finished = 0
        self._completions: deque[float] = deque(maxlen=50)
        self._by_business: dict[str, list[Question]] = {}
        for q in self.questions:
            self._by_business.setdefault(q.business_id, []).append(q)
        counts = {b: len(qs) for b, qs in self._by_business.items()}
        self.stats = OrchestratorStats(assignment=assign_businesses(counts, n) if n else {},
                                       questions_per_replica=[0] * n)
        self._sigterm = False

    # -- control ---------------------------------------------------------------------------

    def request_stop(self) -> None:
        """SIGTERM path (SPEC §7.12-9): finalize immediately with abstains for unwritten ids."""
        self._sigterm = True
        self._stop.set()

    @property
    def _global_stop_at(self) -> float:
        return self._t0 + self.cfg.deadlines.global_hard_stop_s

    def _route(self, replica: int) -> int | None:
        if not self._dead[replica]:
            return replica
        alive = [i for i in range(len(self.clients)) if not self._dead[i]]
        return alive[0] if alive else None

    # -- business setup --------------------------------------------------------------------

    def _run_setup(self, business_id: str) -> None:
        started = self._clock()
        cat: BusinessCatalog | None = None
        err: str | None = None
        try:
            cat, err = self._setup(business_id)
        except Exception as exc:  # business boundary
            with self._lock:
                self.stats.errors.append(f"setup {business_id}: {type(exc).__name__}: {exc}")
        with self._lock:
            self.stats.catalogs[business_id] = cat
            self.stats.setup_ms[business_id] = int((self._clock() - started) * 1000)
        target = self._route(self.stats.assignment.get(business_id, 0)) if self.clients else None
        if target is None:
            return  # no replica left; finalization abstains these ids
        for q in self._by_business[business_id]:
            self._queues[target].put((q, cat, err))

    # -- workers ---------------------------------------------------------------------------

    def _worker(self, replica: int) -> None:
        q = self._queues[replica]
        while not self._stop.is_set():
            if not self._up[replica].wait(0.1):
                continue
            if self._dead[replica]:
                return
            try:
                question, cat, err = q.get(timeout=0.1)
            except queue.Empty:
                continue
            self._process(replica, question, cat, err)

    def _process(self, replica: int, q: Question, cat: BusinessCatalog | None,
                 err: str | None) -> None:
        d = self.cfg.deadlines
        deadline = QuestionDeadline(self._clock, self._clock(), d.question_soft_s, d.question_hard_s,
                                    self._global_stop_at, self._stop, self._degrade)
        try:
            record, log = answer_question(q, self.split, cat, self.clients[replica], self.cfg,
                                          pipeline_error=err, deadline=deadline, blobs=self._blobs,
                                          context=self._context)
        except BaseException as exc:  # answer_question already guards Exception; be total
            record, log = _abstain(q, codes.E_INTERNAL, f"{type(exc).__name__}: {exc}")
        if not self.writer.try_write(record, log):
            return  # finalization or a duplicate got there first
        self._count(replica, record, log)

    def _count(self, replica: int | None, record: SubmissionRecord, log: LogRecord) -> None:
        with self._lock:
            kind = record.type if record.type in ("abstain", "unanswerable") else "answer"
            self.stats.outcome[kind] += 1
            self.stats.reasons[log.decision.get("reason_code", "")] += 1
            if replica is not None:
                self.stats.questions_per_replica[replica] += 1
            now = self._clock()
            self._completions.append(now)
            if self.stats.first_answer_ms is None:
                self.stats.first_answer_ms = int((now - self._t0) * 1000)
            self._finished += 1
            if self._finished >= len(self.questions):
                self._done.set()

    # -- supervision -----------------------------------------------------------------------

    def projected_finish_s(self) -> float | None:
        """elapsed + remaining × recent per-question throughput time (SPEC §7.12-7)."""
        with self._lock:
            if len(self._completions) < 10:
                return None
            span = self._completions[-1] - self._completions[0]
            per_q = span / (len(self._completions) - 1)
            remaining = len(self.questions) - self._finished
        return (self._clock() - self._t0) + remaining * per_q

    def _tick(self, last_progress: float) -> float:
        now = self._clock()
        if self._supervisor is not None:
            for i in self._supervisor.poll():
                with self._lock:
                    if i in self._handling or self._dead[i]:
                        continue
                    self._handling.add(i)
                threading.Thread(target=self._recover, args=(i,), daemon=True).start()
        for i in range(len(self.clients)):  # sweep items stranded on a permanently dead replica
            if self._dead[i]:
                self._drain(i)
        if now - last_progress < self.cfg.deadlines.progress_interval_s:
            return last_progress
        projected = self.projected_finish_s()
        if (projected is not None and not self._degrade.is_set()
                and projected > self.cfg.deadlines.degrade_if_projected_finish_s):
            self._degrade.set()
            self.stats.degrade_activated_ms = int((now - self._t0) * 1000)
        self._progress(now, projected)
        return now

    def _progress(self, now: float, projected: float | None) -> None:
        if self._progress_log is None:
            return
        line = (f"t={now - self._t0:.0f}s done={self._finished}/{len(self.questions)} "
                f"outcome={dict(self.stats.outcome)} projected_finish_s="
                f"{'n/a' if projected is None else f'{projected:.0f}'} "
                f"degrade={self._degrade.is_set()} dead={self._dead}\n")
        with open(self._progress_log, "a", encoding="utf-8") as fh:
            fh.write(line)

    def _recover(self, i: int) -> None:
        assert self._supervisor is not None
        self._up[i].clear()  # workers of this replica pause; nothing fails against a down server
        ok = False
        try:
            ok = self._supervisor.restart(i)
        except Exception as exc:
            with self._lock:
                self.stats.errors.append(f"replica {i} restart: {type(exc).__name__}: {exc}")
        if not ok:
            self._dead[i] = True
            self._drain(i)
        self._up[i].set()
        with self._lock:
            self._handling.discard(i)

    def _drain(self, i: int) -> None:
        """Move queued questions of a permanently dead replica to a live one."""
        while True:
            try:
                item = self._queues[i].get_nowait()
            except queue.Empty:
                return
            target = self._route(i)
            if target is None or target == i:
                return  # nowhere to go: finalization abstains them (E_REPLICA_DOWN)
            self._queues[target].put(item)

    # -- run -------------------------------------------------------------------------------

    def run(self) -> OrchestratorStats:
        from concurrent.futures import ThreadPoolExecutor

        if not self.questions:
            self._done.set()
        workers = [threading.Thread(target=self._worker, args=(i,), daemon=True,
                                    name=f"worker-{i}-{k}")
                   for i in range(len(self.clients))
                   for k in range(self.cfg.concurrency.questions_per_replica)]
        for w in workers:
            w.start()
        pool = ThreadPoolExecutor(max_workers=self.cfg.concurrency.setup_workers,
                                  thread_name_prefix="setup")
        for biz in sorted(self._by_business, key=lambda b: (-len(self._by_business[b]), b)):
            pool.submit(self._run_setup, biz)
        last_progress = self._clock()
        while not self._done.wait(TICK_S):
            if self._stop.is_set():
                self.stats.stop_reason = "sigterm" if self._sigterm else self.stats.stop_reason
                break
            if self._clock() >= self._global_stop_at:
                self.stats.stop_reason = "global_stop"
                break
            last_progress = self._tick(last_progress)
            if all(self._dead):
                self.stats.stop_reason = "replicas_down"
                break
        self._stop.set()
        pool.shutdown(wait=False, cancel_futures=True)
        reason = {"replicas_down": codes.E_REPLICA_DOWN}.get(self.stats.stop_reason or "",
                                                              codes.E_GLOBAL_STOP)
        written = self.writer.written_ids()
        for q in self.questions:
            if q.id not in written:
                record, log = _abstain(q, reason, None)
                if self.writer.try_write(record, log):
                    self._count(None, record, log)
        self.stats.total_ms = int((self._clock() - self._t0) * 1000)
        return self.stats


def _abstain(q: Question, reason: str, detail: str | None) -> tuple[SubmissionRecord, LogRecord]:
    decision: dict[str, Any] = {"kind": "abstain", "reason_code": reason, "features": {}}
    if detail:
        decision["error"] = detail
    log = LogRecord(id=q.id, answer={"type": "abstain"}, elapsed_ms=0, thinking=None, code=None,
                    output=None, business_id=q.business_id, decision=decision)
    return SubmissionRecord(id=q.id, type="abstain"), log
