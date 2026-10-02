"""
ClaimRevision — the sealed, append-only record of one authority-bearing
change to a claim (schema ``aihydro.claim_revision_record/1``).

A claim is a chain of revisions. ``revision`` counts from 0; ``supersedes`` is
the ``revision_digest`` of the previous revision (``None`` only at revision 0).
``revision_digest`` is the content digest of the authority fields (computed by
the writer, for example tools' ``aihydro.claim_revision/2``); ``content`` holds
those fields. ``record_digest`` seals the whole row, including ``recorded_at``
and any unknown fields carried forward, so editing a stored row is detectable.

As with :class:`~aihydro_core.records.run.RunRecord`, a seal proves integrity,
not origin. Unknown fields from newer writers round-trip unchanged.
"""
from __future__ import annotations

import dataclasses
from typing import Any, Dict, Optional, Sequence

from aihydro_core.records.canonical import CANONICALIZATION, digest, is_digest
from aihydro_core.records.run import Actor, utc_now

CLAIM_REVISION_SCHEMA = "aihydro.claim_revision_record/1"

_KNOWN_FIELDS = (
    "schema", "canonicalization", "session_id", "claim_id", "revision", "supersedes",
    "revision_digest", "content", "cause", "actor", "recorded_at", "record_digest",
)


@dataclasses.dataclass
class ClaimRevision:
    """One sealed revision of a claim. See module docstring."""

    session_id: str
    claim_id: str
    revision: int
    revision_digest: str
    content: Dict[str, Any]
    cause: Dict[str, Any]
    actor: Dict[str, Any]
    supersedes: Optional[str] = None
    recorded_at: str = dataclasses.field(default_factory=utc_now)
    schema: str = CLAIM_REVISION_SCHEMA
    canonicalization: str = CANONICALIZATION
    record_digest: Optional[str] = None
    unknown: Dict[str, Any] = dataclasses.field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if not self.session_id:
            raise ValueError("ClaimRevision.session_id must be non-empty")
        if not self.claim_id:
            raise ValueError("ClaimRevision.claim_id must be non-empty")
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 0:
            raise ValueError(f"ClaimRevision.revision must be an int >= 0, got {self.revision!r}")
        for name in ("revision_digest", "record_digest"):
            value = getattr(self, name)
            if value is None and name == "record_digest":
                continue
            if not is_digest(value):
                raise ValueError(f"ClaimRevision.{name} must be 'sha256:<64 hex>', got {value!r}")
        if self.supersedes is not None and not is_digest(self.supersedes):
            raise ValueError(f"ClaimRevision.supersedes must be 'sha256:<64 hex>' or None, got {self.supersedes!r}")
        if self.revision == 0 and self.supersedes is not None:
            raise ValueError("ClaimRevision revision 0 cannot supersede anything")
        if self.revision > 0 and self.supersedes is None:
            raise ValueError("ClaimRevision revision > 0 must name the revision it supersedes")
        if not isinstance(self.content, dict):
            raise ValueError("ClaimRevision.content must be a dict of authority fields")
        if not isinstance(self.cause, dict):
            raise ValueError("ClaimRevision.cause must be a dict")
        if not isinstance(self.cause.get("tool"), str) or not self.cause["tool"]:
            raise ValueError("ClaimRevision.cause needs a non-empty string 'tool'")
        if not isinstance(self.cause.get("reason"), str) or not self.cause["reason"]:
            raise ValueError("ClaimRevision.cause needs a non-empty string 'reason'")
        run_id = self.cause.get("run_id")
        if run_id is not None and (not isinstance(run_id, str) or not run_id):
            raise ValueError("ClaimRevision.cause.run_id must be a non-empty string when present")
        if isinstance(self.actor, Actor):
            self.actor = self.actor.to_dict()
        elif isinstance(self.actor, dict):
            Actor.from_dict(self.actor)  # validates kind/id; keeps the dict as given
        else:
            raise ValueError("ClaimRevision.actor is required (an Actor or its dict)")

    # -- serialisation -------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        """Plain dict including preserved unknown fields."""
        d = {name: getattr(self, name) for name in _KNOWN_FIELDS}
        d = {k: v for k, v in d.items() if v is not None}
        for key, value in self.unknown.items():
            d.setdefault(key, value)
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ClaimRevision":
        known = {k: d[k] for k in _KNOWN_FIELDS if k in d}
        unknown = {k: v for k, v in d.items() if k not in _KNOWN_FIELDS}
        return cls(**known, unknown=unknown)

    # -- integrity -----------------------------------------------------
    def compute_digest(self) -> str:
        payload = self.to_dict()
        payload.pop("record_digest", None)
        return digest(payload)

    def seal(self) -> "ClaimRevision":
        """Compute and set ``record_digest``. Sealing twice is idempotent."""
        self.record_digest = self.compute_digest()
        return self

    def verify(self) -> bool:
        """True iff the record is sealed and unchanged since sealing."""
        if self.record_digest is None:
            return False
        try:
            return self.compute_digest() == self.record_digest
        except Exception:
            return False


def verify_chain(revisions: Sequence[ClaimRevision]) -> bool:
    """True iff ``revisions`` is one claim's complete, intact chain.

    Each record must verify, share ``session_id`` and ``claim_id``, count
    ``revision`` 0, 1, 2, ... in order, and each ``supersedes`` must equal the
    previous record's ``revision_digest``.
    """
    if not revisions:
        return False
    first = revisions[0]
    prev: Optional[ClaimRevision] = None
    for i, rev in enumerate(revisions):
        if not rev.verify() or rev.revision != i:
            return False
        if rev.session_id != first.session_id or rev.claim_id != first.claim_id:
            return False
        if prev is not None and rev.supersedes != prev.revision_digest:
            return False
        prev = rev
    return True


def verify_claim_revision_dict(d: Dict[str, Any]) -> bool:
    """Verify a serialised revision without trusting its declared digest."""
    try:
        return ClaimRevision.from_dict(d).verify()
    except Exception:
        return False
