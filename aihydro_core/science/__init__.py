"""
science — domain-free defensibility protocols for AI-Hydro.

Three cross-cutting blocks that define the abstract vocabulary any research
platform must implement to produce defensible, auditable outputs:

    claim       — claim lifecycle (status, evidence spans, ClaimStore Protocol)
    audit       — prose provenance checking (AuditReport, Auditor Protocol)
    uncertainty — quantified estimate shape (UncertaintyEstimate, Provider Protocol)

These are *Protocols*, not implementations. The hydrology binding lives in
aihydro-tools; the marine/atmospheric/climate binding would live in its own
domain package. Any package that implements these structural interfaces gains
the full defensibility pipeline for free.

All types here are stdlib-only (TypedDict, Protocol, Literal, runtime_checkable).
No pydantic, no numpy, no domain knowledge.
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
    # uncertainty
    "UncertaintyMethod",
    "UncertaintyEstimate",
    "UncertaintyProvider",
]
