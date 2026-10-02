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
