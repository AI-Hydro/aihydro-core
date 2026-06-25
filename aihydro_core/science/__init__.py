"""
science — defensibility protocols + bootstrap implementations for AI-Hydro.

Three cross-cutting blocks:

    claim       — claim lifecycle (status, evidence spans, ClaimStore Protocol)
    audit       — prose provenance checking (AuditReport, Auditor Protocol)
    uncertainty — quantified estimate shape, Provider Protocol, AND concrete
                  bootstrap implementations (bootstrap_ci, block_bootstrap_ci,
                  bootstrap_dict).  Requires the [science] extra (numpy).

The protocol types (UncertaintyProvider, UncertaintyEstimate, etc.) are
stdlib-only.  The bootstrap functions additionally need numpy — import them
only after installing aihydro-core[science].
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .claim import (
    ClaimStatus,
    EvidenceSpan,
    Claim,
    ClaimStore,
)
from .audit import (
    ViolationKind,
    AuditViolationRecord,
    AuditReportRecord,
    Auditor,
)
from .uncertainty import (
    UncertaintyMethod,
    UncertaintyEstimate,
    UncertaintyProvider,
)

_BOOTSTRAP_EXPORTS = {
    "UncertaintyResult",
    "bootstrap_ci",
    "block_bootstrap_ci",
    "bootstrap_dict",
}


def __getattr__(name: str):
    """Lazily expose numpy-backed uncertainty functions when [science] is installed."""
    if name in _BOOTSTRAP_EXPORTS:
        from . import uncertainty

        return getattr(uncertainty, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(list(globals()) + list(_BOOTSTRAP_EXPORTS))


if TYPE_CHECKING:
    from .uncertainty import (
        UncertaintyResult,
        bootstrap_ci,
        block_bootstrap_ci,
        bootstrap_dict,
    )

__all__ = [
    # claim
    "ClaimStatus",
    "EvidenceSpan",
    "Claim",
    "ClaimStore",
    # audit
    "ViolationKind",
    "AuditViolationRecord",
    "AuditReportRecord",
    "Auditor",
    # uncertainty — protocol
    "UncertaintyMethod",
    "UncertaintyEstimate",
    "UncertaintyProvider",
    # uncertainty — implementations
    "UncertaintyResult",
    "bootstrap_ci",
    "block_bootstrap_ci",
    "bootstrap_dict",
]
