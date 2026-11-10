"""Per-question deadline protocol (SPEC §5.10, §7.12-6). Owner: M3/M4.

The orchestrator supplies an implementation; parse/solver only consult it:
soft expiry stops new repair attempts, hard expiry (or global stop) stops all
model calls and ends the question as ``abstain`` (E_DEADLINE / E_GLOBAL_STOP).
Model calls are capped to ``remaining_s()`` so a hard deadline is enforced
without killing threads.
"""

from __future__ import annotations

from typing import Protocol


class DeadlineExceeded(Exception):
    """Raised between pipeline steps once the hard deadline or a global stop has passed."""


class Deadline(Protocol):
    @property
    def soft_expired(self) -> bool: ...
    @property
    def hard_expired(self) -> bool: ...
    @property
    def degrade(self) -> bool: ...
    def remaining_s(self) -> float: ...


class _NoDeadline:
    soft_expired = False
    hard_expired = False
    degrade = False

    def remaining_s(self) -> float:
        return float("inf")


NO_DEADLINE: Deadline = _NoDeadline()


def check(deadline: Deadline) -> None:
    if deadline.hard_expired:
        raise DeadlineExceeded
