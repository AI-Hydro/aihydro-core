"""
RunRecord — the sealed, self-describing record of one tool or compute run
(schema ``aihydro.run/2``), plus the small value types it references.

Identity versus integrity (ADR-001):

- ``run_id`` is a unique *event* identifier.
- ``input_digest`` / ``output_digest`` / ``input_refs[].digest`` identify
  *content*: two runs over the same inputs share an ``input_digest``.
- ``record_digest`` protects the record's *integrity*: it is computed over
  every other field (including ``recorded_at`` and any unknown fields carried
  forward), so editing a sealed record is detectable with :meth:`verify`.

Records are append-only. Writers seal once; readers verify. Unknown fields
read from newer writers are preserved verbatim so that re-serialising a
record never changes its digest (forward compatibility).
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
from typing import Any, Dict, List, Optional

from aihydro_core.records.canonical import CANONICALIZATION, digest, is_digest

RUN_SCHEMA = "aihydro.run/2"

RUN_STATUSES = ("ok", "error", "refused")
ACTOR_KINDS = ("human", "agent", "package", "system")
INPUT_ROLES = ("parameters", "served_data", "upstream_output", "artifact", "place", "other")


def utc_now() -> str:
    """UTC transaction time, ISO-8601 with a ``Z`` suffix."""
    return _dt.datetime.now(tz=_dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _drop_none(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


@dataclasses.dataclass
class Actor:
    """Who or what performed an action. Required on approval records."""

    kind: str
    id: str
    model_id: Optional[str] = None
    client: Optional[str] = None
    skill_set_digest: Optional[str] = None

    def __post_init__(self) -> None:
        if self.kind not in ACTOR_KINDS:
            raise ValueError(f"Actor.kind must be one of {ACTOR_KINDS}, got {self.kind!r}")
        if not self.id:
            raise ValueError("Actor.id must be non-empty")

    def to_dict(self) -> Dict[str, Any]:
        return _drop_none(dataclasses.asdict(self))

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Actor":
        return cls(**{f.name: d.get(f.name) for f in dataclasses.fields(cls) if f.name in d})


@dataclasses.dataclass
class ArtifactRef:
    """Reference to an artifact by content digest (blobs are not stored here)."""

    ref: str
    digest: str
    media_type: Optional[str] = None
    license: Optional[str] = None
    permission_status: Optional[str] = None

    def __post_init__(self) -> None:
        if not is_digest(self.digest):
            raise ValueError(f"ArtifactRef.digest must be 'sha256:<64 hex>', got {self.digest!r}")

    def to_dict(self) -> Dict[str, Any]:
        return _drop_none(dataclasses.asdict(self))


def input_ref(ref: str, digest_value: Optional[str], role: str = "other") -> Dict[str, Any]:
    """Build one ``input_refs`` entry: a reference plus the digest of what was used."""
    if role not in INPUT_ROLES:
        raise ValueError(f"input role must be one of {INPUT_ROLES}, got {role!r}")
    if digest_value is not None and not is_digest(digest_value):
        raise ValueError(f"input digest must be 'sha256:<64 hex>' or None, got {digest_value!r}")
    return _drop_none({"ref": ref, "digest": digest_value, "role": role})


_KNOWN_FIELDS = (
    "schema", "canonicalization", "run_id", "tool", "tool_version", "version_source",
    "session_id", "recorded_at", "status", "input_digest", "input_refs", "output_digest",
    "parents", "env_digest", "actor", "record_error", "extra", "record_digest",
)


@dataclasses.dataclass
class RunRecord:
    """One run, sealed. See module docstring for field semantics."""

    run_id: str
    tool: str
    tool_version: Optional[str] = None
    version_source: Optional[str] = None      # "result_meta" | "distribution" | ...
    session_id: Optional[str] = None
    recorded_at: str = dataclasses.field(default_factory=utc_now)
    status: str = "ok"
    input_digest: Optional[str] = None
    input_refs: List[Dict[str, Any]] = dataclasses.field(default_factory=list)
    output_digest: Optional[str] = None
    parents: List[str] = dataclasses.field(default_factory=list)
    env_digest: Optional[str] = None
    actor: Optional[Dict[str, Any]] = None
    record_error: Optional[str] = None        # why a digest is missing, never silent
    extra: Dict[str, Any] = dataclasses.field(default_factory=dict)
    schema: str = RUN_SCHEMA
    canonicalization: str = CANONICALIZATION
    record_digest: Optional[str] = None
    unknown: Dict[str, Any] = dataclasses.field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("RunRecord.run_id must be non-empty")
        if not self.tool:
            raise ValueError("RunRecord.tool must be non-empty")
        if self.status not in RUN_STATUSES:
            raise ValueError(f"RunRecord.status must be one of {RUN_STATUSES}, got {self.status!r}")
        for name in ("input_digest", "output_digest", "env_digest", "record_digest"):
            value = getattr(self, name)
            if value is not None and not is_digest(value):
                raise ValueError(f"RunRecord.{name} must be 'sha256:<64 hex>' or None, got {value!r}")
        if isinstance(self.actor, Actor):
            self.actor = self.actor.to_dict()
        elif self.actor is not None:
            Actor.from_dict(self.actor)  # validates kind/id; keeps the dict as given
        for ref in self.input_refs:
            if not isinstance(ref, dict) or not isinstance(ref.get("ref"), str):
                raise ValueError(f"RunRecord.input_refs entries need a string 'ref', got {ref!r}")
            input_ref(ref["ref"], ref.get("digest"), ref.get("role", "other"))
        if not all(isinstance(p, str) and p for p in self.parents):
            raise ValueError("RunRecord.parents must be non-empty run_id strings")

    # -- serialisation -------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        """Plain dict including preserved unknown fields."""
        d = {name: getattr(self, name) for name in _KNOWN_FIELDS}
        d = {k: v for k, v in d.items() if v is not None}
        for key, value in self.unknown.items():
            d.setdefault(key, value)
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RunRecord":
        known = {k: d[k] for k in _KNOWN_FIELDS if k in d}
        unknown = {k: v for k, v in d.items() if k not in _KNOWN_FIELDS}
        return cls(**known, unknown=unknown)

    # -- integrity -----------------------------------------------------
    def _sealing_payload(self) -> Dict[str, Any]:
        payload = self.to_dict()
        payload.pop("record_digest", None)
        return payload

    def compute_digest(self) -> str:
        return digest(self._sealing_payload())

    def seal(self) -> "RunRecord":
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


def verify_record_dict(d: Dict[str, Any]) -> bool:
    """Verify a serialised run record without trusting its declared digest."""
    try:
        return RunRecord.from_dict(d).verify()
    except Exception:
        return False
