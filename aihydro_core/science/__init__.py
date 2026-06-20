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
