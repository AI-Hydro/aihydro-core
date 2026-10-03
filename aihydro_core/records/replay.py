"""
Replay status vocabulary (ADR-005).

Reproducibility claims must say exactly what was checked. These levels are
ordered from weakest to strongest; an export or report states the strongest
level actually achieved, never an implied one.

Terminology follows Essawy et al. 2020 and NASEM 2019: *reproducibility* is
obtaining the same results from the same data and procedure (by the original
team: repeatability; by a new researcher: reproduction), while *replicability*
is obtaining consistent results with **new data**. This platform never
asserts replicability: nothing here involves new data.
"""
from __future__ import annotations

import enum

#: Persisted spelling of the top level before the Essawy terminology fix. It named a
#: same-data re-execution by a third party, which is reproduction, not replication.
LEGACY_INDEPENDENTLY_REPLICATED = "independently_replicated"


class ReplayStatus(str, enum.Enum):
    """What a replay of a record or capsule actually established.

    Mapping to Essawy et al. 2020 (reproducibility/replicability vocabulary):
    ``not_performed`` and ``archive_integrity`` are below the floor (archive
    integrity is the prerequisite of Essawy section 2.1: the retained
    material is the material that was archived), ``cross_check`` is internal
    consistency, ``recomputed`` is repeatability/runnability, and
    ``independently_reproduced`` is reproduction by a new researcher on the
    same data. Replicability (new data) is never asserted.
    """

    NOT_PERFORMED = "not_performed"
    """Nothing was checked (sub-floor)."""

    ARCHIVE_INTEGRITY = "archive_integrity"
    """Retained files/records match their recorded digests (sub-floor; the
    prerequisite of Essawy section 2.1). Says nothing about whether the
    computation would produce them again."""

    CROSS_CHECK = "cross_check"
    """Internal consistency across stores (e.g. run log vs session outputs):
    retained values agree with each other. No re-fetch and no recomputation."""

    RECOMPUTED = "recomputed"
    """The computation was re-executed from recorded inputs and environment and
    its outputs matched within a stated tolerance. The recomputation entity must
    record the actor and the machine, so that repeatability (same team, same
    machine) can be told apart from runnability (another machine)."""

    INDEPENDENTLY_REPRODUCED = "independently_reproduced"
    """A new researcher re-executed it on the same data (and an independent
    environment) and the outputs matched. This is reproduction in the Essawy /
    NASEM sense. It is not replicability, which would need new data."""

    @classmethod
    def _missing_(cls, value):
        # Persisted capsules may still say "independently_replicated": same meaning, old name.
        if value == LEGACY_INDEPENDENTLY_REPLICATED:
            return cls.INDEPENDENTLY_REPRODUCED
        return None


#: Weakest to strongest. ``NOT_PERFORMED`` is the floor.
REPLAY_ORDER = (
    ReplayStatus.NOT_PERFORMED,
    ReplayStatus.ARCHIVE_INTEGRITY,
    ReplayStatus.CROSS_CHECK,
    ReplayStatus.RECOMPUTED,
    ReplayStatus.INDEPENDENTLY_REPRODUCED,
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
    the check kind, plus the fact that coverage was below 1. The legacy string
    ``"independently_replicated"`` maps to ``INDEPENDENTLY_REPRODUCED`` (renamed:
    a same-data re-execution is reproduction, not replication). Every enum value
    maps to ``(value, True)`` -- the string alone says nothing about coverage,
    so callers that have counts should use them. Unknown strings raise
    ``ValueError``.
    """
    if value == LEGACY_PARTIAL:
        return ReplayStatus.ARCHIVE_INTEGRITY, False
    return ReplayStatus(value), True
