"""
Audit protocol — the abstract interface for prose provenance checking.

The concrete implementation in aihydro-tools (ai_hydro/audit/) resolves
[run:id#path] markers against session run_logs, [claim:id] markers against
the claims ledger, and [lit:hash] markers against the passage index.

The kernel specifies:
  - ViolationKind — the fixed set of violation categories
  - AuditViolationRecord — the shape of one failed check
  - AuditReportRecord — the full audit verdict with coverage metrics
  - Auditor — the Protocol that any audit implementation must satisfy

All types are stdlib-only (TypedDict, Protocol, Literal).
"""
from __future__ import annotations

from typing import Any, List, Optional, Protocol, runtime_checkable
from typing import Literal


# ---------------------------------------------------------------------------
# Violation vocabulary
# ---------------------------------------------------------------------------

ViolationKind = Literal[
    "uncited_number",       # numeric literal with no binding marker
    "run_id_not_found",     # [run:X#...] but X not in session run-log
    "value_mismatch",       # prose number ≠ run-log value within rounding tol
    "json_path_not_found",  # JSON-path not resolvable in run-log entry
    "claim_not_found",      # [claim:X] not in session claims ledger
    "claim_bad_status",     # claim status not in the allowed-for-citation set
    "malformed_marker",     # marker syntax is invalid
    "lit_unresolvable",     # [lit:<hash>] not found in passage index (advisory)
]

# Allowed claim statuses when citing a claim as established fact.
ALLOWED_CLAIM_STATUSES = frozenset({"tested", "supported", "weakly_supported"})


# ---------------------------------------------------------------------------
# Violation record (plain dict shape — no pydantic in core)
# ---------------------------------------------------------------------------

# Minimum required keys for an AuditViolationRecord:
#   kind         : ViolationKind
#   text_excerpt : str    — the prose snippet around the violation
#   message      : str    — human-readable explanation
#   fix_hint     : str    — machine-actionable instruction to the LLM
#   marker_raw   : str | None
#   prose_value  : str | None
#   stored_value : Any | None

AuditViolationRecord = dict  # dict[str, Any] matching the above shape

_VIOLATION_REQUIRED_KEYS = frozenset(
    {"kind", "text_excerpt", "message", "fix_hint"}
)


# ---------------------------------------------------------------------------
# Audit report record
# ---------------------------------------------------------------------------

# Minimum required keys for an AuditReportRecord:
#   passed               : bool
#   violations           : list[AuditViolationRecord]
#   numeric_coverage     : float   — 0.0–1.0
#   total_numeric_count  : int
#   cited_numeric_count  : int
#   claim_count          : int
#   claim_pass_count     : int
#
# Optional extended keys (Phase 2.4 lit resolution):
#   lit_span_count       : int
#   lit_resolved_count   : int
#   lit_advisories       : list[AuditViolationRecord]

AuditReportRecord = dict  # dict[str, Any] matching the above shape

_REPORT_REQUIRED_KEYS = frozenset(
    {
        "passed",
        "violations",
        "numeric_coverage",
        "total_numeric_count",
        "cited_numeric_count",
        "claim_count",
        "claim_pass_count",
    }
)


# ---------------------------------------------------------------------------
# Auditor Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class Auditor(Protocol):
    """
    Protocol satisfied by any object that can audit prose against a session.

    The concrete ``ai_hydro.audit.resolver.resolve_prose`` function satisfies
    this via a module-level ``audit`` callable wrapper; the Protocol is
    runtime_checkable so tests can use isinstance() checks.

    Implementing classes must provide:
        audit(prose, session_id) -> AuditReportRecord

    The session_id is a string key used to load run_log and claims from
    whatever persistence layer is in use (HydroSession, InMemoryStore, …).
    """

    def audit(self, prose: str, session_id: str) -> "AuditReportRecord":
        """
        Audit prose against the session identified by session_id.

        Returns an AuditReportRecord; never raises — errors appear as
        violations in the report with kind "malformed_marker".
        """
        ...


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def violation_is_blocking(violation: "dict[str, Any]") -> bool:
    """
    Return True if a violation prevents the interpretation from being saved.

    lit_unresolvable is the only non-blocking kind — the number IS cited,
    only the passage-index lookup failed. All other kinds block the gate.
    """
    return violation.get("kind") != "lit_unresolvable"


def report_has_required_keys(report: "dict[str, Any]") -> bool:
    """Return True if report dict carries all minimum-required keys."""
    return _REPORT_REQUIRED_KEYS.issubset(report.keys())
