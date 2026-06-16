"""
Claim protocol — the abstract shape of a scientific claim and its lifecycle.

Domain-free: no hydrology-specific fields. The hydrology binding in
aihydro-tools adds scope (basins, period, metric), limitations, citations, etc.
The kernel defines only the lifecycle vocabulary, evidence-linking shape, and
the ClaimStore Protocol so any domain can plug into the defensibility pipeline.

Design choices
--------------
- TypedDict for data shapes: plain dicts that satisfy the type, no class overhead.
- Protocol (runtime_checkable) for the store: structural subtyping — HydroSession
  satisfies ClaimStore without inheriting from it.
- ClaimStatus is a string alias, not an Enum, so it round-trips through JSON
  without a custom encoder.
"""
from __future__ import annotations

from typing import Any, List, Protocol, runtime_checkable

# Python 3.8+ ships Literal in typing; 3.7 needs typing_extensions.
# aihydro-core targets 3.9+ so the plain import is safe.
from typing import Literal


# ---------------------------------------------------------------------------
# Claim lifecycle
# ---------------------------------------------------------------------------

ClaimStatus = Literal[
    "proposed",        # claim drafted; no evidence yet
    "tested",          # evidence collected; pending evaluation
    "supported",       # confirmed by evidence (quantitative CIs required)
    "weakly_supported",# corroborating but not conclusive evidence
    "contradicted",    # active counter-evidence found
    "retracted",       # formally withdrawn (error discovered)
    "stale",           # source data or code has changed; needs re-evaluation
]

ClaimType = Literal[
    "empirical_result",   # measured or modelled quantity with a numeric result
    "methodological",     # describes a method choice or calibration decision
    "hypothesis",         # statement to be tested; no CIs required for promotion
    "negative_result",    # a null result worth recording explicitly
]


# ---------------------------------------------------------------------------
# Evidence span — links a claim to the evidence that supports it
# ---------------------------------------------------------------------------

class EvidenceSpan(dict):
    """
    Dict representation of a single evidence link.

    Preferred fields
    ----------------
    source_type : "run" | "paper" | "dataset"
    source_id   : run_id | passage_hash | dataset_id
    metric_ref  : optional field path within the source (e.g. "kge")
    description : optional human label

    Implemented as a plain dict subclass so it serialises to JSON without
    a custom encoder and satisfies isinstance(span, dict) checks everywhere.
    """
    __slots__ = ()


# ---------------------------------------------------------------------------
# Claim shape (TypedDict)
# ---------------------------------------------------------------------------

# Not a proper TypedDict because we want to allow extra keys from domain
# bindings (basins, period, limitations, citations, …) without triggering
# TypedDict's strict-key checker. Use a plain class-level doc instead.
#
# Minimum required keys that every Claim dict MUST carry:
#   id           str              — unique within a session
#   claim        str              — the natural-language assertion
#   claim_type   ClaimType        — one of the four Literal values
#   status       ClaimStatus      — lifecycle position
#   confidence   str              — "low" | "medium" | "high"
#   evidence_spans list[dict]     — EvidenceSpan-shaped dicts

# Runtime validator used by ClaimStore.is_valid_claim():
_CLAIM_REQUIRED_KEYS = frozenset(
    {"id", "claim", "claim_type", "status", "confidence", "evidence_spans"}
)

# Type alias kept for documentation / isinstance targets downstream.
Claim = dict  # dict[str, Any] with at least _CLAIM_REQUIRED_KEYS


# ---------------------------------------------------------------------------
# ClaimStore Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class ClaimStore(Protocol):
    """
    Persistence interface for the claims ledger.

    HydroSession in aihydro-tools satisfies this Protocol via structural
    subtyping — no inheritance required. Any store that exposes a ``claims``
    attribute (dict keyed by claim_id) and a ``save()`` method is compatible.

    Usage
    -----
    The Auditor (science.audit) accepts a ClaimStore to resolve
    [claim:<id>] markers at proof-time without depending on HydroSession.
    """

    @property
    def claims(self) -> "dict[str, Any]":
        """Return the claims dict {claim_id: claim_dict}."""
        ...

    def save(self) -> None:
        """Persist the current state to durable storage."""
        ...


def claim_has_required_keys(claim: "dict[str, Any]") -> bool:
    """Return True if claim dict carries all minimum-required keys."""
    return _CLAIM_REQUIRED_KEYS.issubset(claim.keys())
