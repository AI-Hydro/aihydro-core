"""
Replay status vocabulary (ADR-005).

Reproducibility claims must say exactly what was checked. These levels are
ordered from weakest to strongest; an export or report states the strongest
level actually achieved, never an implied one.
"""
from __future__ import annotations

import enum


class ReplayStatus(str, enum.Enum):
    """What a replay of a record or capsule actually established."""

    NOT_PERFORMED = "not_performed"
    """Nothing was checked."""

    ARCHIVE_INTEGRITY = "archive_integrity"
    """Retained files/records match their recorded digests. Says nothing about
    whether the computation would produce them again."""

    CROSS_CHECK = "cross_check"
    """Retained values agree with each other across stores (e.g. run log vs
    session outputs). Still no recomputation."""

    RECOMPUTED = "recomputed"
    """The computation was re-executed from recorded inputs and environment and
    its outputs matched within a stated tolerance."""

    INDEPENDENTLY_REPLICATED = "independently_replicated"
    """Someone other than the original authors re-executed it in an independent
    environment and the outputs matched."""


#: Weakest to strongest. ``NOT_PERFORMED`` is the floor.
REPLAY_ORDER = (
    ReplayStatus.NOT_PERFORMED,
    ReplayStatus.ARCHIVE_INTEGRITY,
    ReplayStatus.CROSS_CHECK,
    ReplayStatus.RECOMPUTED,
    ReplayStatus.INDEPENDENTLY_REPLICATED,
)

#: Persisted by older tools exporters. Partiality is *coverage*, a separate
#: dimension from the kind of check, so it is not an enum member (R2): readers
#: map it with :func:`read_legacy_replay_status`. Persisted manifests are never
#: rewritten.
LEGACY_PARTIAL = "archive_integrity_partial"


def replay_rank(status: "ReplayStatus | str") -> int:
    """Position of ``status`` in :data:`REPLAY_ORDER` (higher is stronger)."""
    return REPLAY_ORDER.index(ReplayStatus(status))


def min_replay_status(*statuses: "ReplayStatus | str") -> ReplayStatus:
    """The weakest of ``statuses`` (an export never claims more than any input)."""
    return min((ReplayStatus(s) for s in statuses), key=replay_rank)


def read_legacy_replay_status(value: str):
    """Map a persisted replay-status string to ``(ReplayStatus, complete)``.

    ``"archive_integrity_partial"`` becomes ``(ARCHIVE_INTEGRITY, False)``:
    the check kind, plus the fact that coverage was below 1. Every enum value
    maps to ``(value, True)`` -- the string alone says nothing about coverage,
    so callers that have counts should use them. Unknown strings raise
    ``ValueError``.
    """
    if value == LEGACY_PARTIAL:
        return ReplayStatus.ARCHIVE_INTEGRITY, False
    return ReplayStatus(value), True
