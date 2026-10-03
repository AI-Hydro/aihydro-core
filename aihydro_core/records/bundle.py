"""
Bundle — the sealed identity of one session's exported evidence set
(schema ``aihydro.bundle/1``; ADR-001 "a Research Object is a Bundle with an id").

A Bundle is a *manifest of pointers*, not a store. It lists

- ``objects``: content-addressed files (``ArtifactRef``-style ``sha256:``
  digest, size, role), and
- ``records``: sealed records (and unsealed working views, labelled as such)
  that live in those files, each located by a JSON Pointer and optionally
  bound to its row body with a body binding (``aihydro.entry/1``).

It never copies a record body.

Identity versus assessment (M6)
-------------------------------
``bundle_id`` is the digest of ``{schema, session_id, objects, records}`` only,
so it names *content*. Everything an exporter or verifier *judged*
(``created_at``, the replay assessment, record coverage, gates, effective
tier) lives in the sealed envelope: ``record_digest`` covers every field,
including ``bundle_id``. Changing the verifier therefore cannot change the id
of identical content, and editing any field is still detectable.

A seal proves integrity, not origin: anyone can build a self-consistent
Bundle. Signing ``bundle_id`` is a later step (ADR-002b).

Locations
---------
``record_location`` and ``body_location`` are ``"<relative file path>#<JSON
Pointer>"`` (RFC 6901 pointer, *not* URI-fragment percent-encoded). The file
part is a relative POSIX path that must not contain ``#``, ``..`` segments, a
leading ``/`` or a backslash. The pointer escapes ``~`` as ``~0`` and ``/`` as
``~1`` (apply ``~`` first when escaping, ``~1`` first when unescaping), so a
run id such as ``a/b~c`` is the single token ``a~1b~0c``. Array tokens are
decimal indices without leading zeros. See :func:`make_location`,
:func:`split_location`, :func:`resolve_location`.

Unknown fields round-trip: top-level unknown fields are carried in the sealed
envelope; unknown fields inside ``objects``/``records`` entries are part of the
identity (they are inside those lists).
"""
from __future__ import annotations

import dataclasses
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from aihydro_core.records.canonical import CANONICALIZATION, digest, is_digest
from aihydro_core.records.replay import ReplayStatus
from aihydro_core.records.run import utc_now

BUNDLE_SCHEMA = "aihydro.bundle/1"

#: Kinds of ``records[]`` entries. ``claim_view`` is an *unsealed* working view
#: (no ``record_digest``/``record_location``); every other kind is sealed.
RECORD_KINDS = ("run", "claim_revision", "approval", "basin_ref", "claim_view")
UNSEALED_KINDS = ("claim_view",)

#: Gate codes owned by the gate modules; free text is never classified (C3).
GATE_CODES = ("APPROVAL_REQUIRED",)
GATE_OUTCOMES = ("refused", "error")

_IDENTITY_FIELDS = ("schema", "session_id", "objects", "records")
_KNOWN_FIELDS = (
    "schema", "canonicalization", "session_id", "objects", "records", "bundle_id",
    "created_at", "exporter", "replay", "coverage", "gates", "effective_tier", "record_digest",
)


class BundleError(ValueError):
    """Raised for a malformed Bundle or location."""


# ------------------------------------------------------------------ pointers
def escape_pointer_token(token: str) -> str:
    """RFC 6901 escape: ``~`` -> ``~0`` first, then ``/`` -> ``~1``."""
    return token.replace("~", "~0").replace("/", "~1")


def unescape_pointer_token(token: str) -> str:
    """RFC 6901 unescape: ``~1`` -> ``/`` first, then ``~0`` -> ``~``.

    A ``~`` not followed by ``0`` or ``1`` is malformed and raises.
    """
    out: List[str] = []
    i = 0
    while i < len(token):
        ch = token[i]
        if ch == "~":
            nxt = token[i + 1] if i + 1 < len(token) else ""
            if nxt == "0":
                out.append("~")
            elif nxt == "1":
                out.append("/")
            else:
                raise BundleError(f"bad JSON Pointer escape in {token!r}")
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def make_pointer(tokens: Iterable[Any]) -> str:
    """Build a JSON Pointer from path tokens (ints become array indices)."""
    return "".join("/" + escape_pointer_token(str(t)) for t in tokens)


def _check_file_part(path: str) -> None:
    if not path or path.startswith("/") or "\\" in path or "#" in path or "\x00" in path:
        raise BundleError(f"location file part must be a relative POSIX path without '#': {path!r}")
    if any(seg in ("", ".", "..") for seg in path.split("/")):
        raise BundleError(f"location file part has an empty, '.' or '..' segment: {path!r}")


def make_location(path: str, tokens: Iterable[Any]) -> str:
    """``"<path>#<pointer>"`` for ``tokens`` (see module docstring)."""
    _check_file_part(path)
    return path + "#" + make_pointer(tokens)


def split_location(location: str) -> Tuple[str, List[str]]:
    """``(file path, unescaped pointer tokens)``; raises :class:`BundleError`."""
    if not isinstance(location, str) or "#" not in location:
        raise BundleError(f"location must be '<file>#<pointer>': {location!r}")
    path, _, pointer = location.partition("#")
    _check_file_part(path)
    if pointer == "":
        return path, []
    if not pointer.startswith("/"):
        raise BundleError(f"JSON Pointer must be empty or start with '/': {pointer!r}")
    return path, [unescape_pointer_token(t) for t in pointer[1:].split("/")]


def resolve_tokens(doc: Any, tokens: Sequence[str]) -> Any:
    """Follow ``tokens`` through ``doc``; raises :class:`BundleError` if absent."""
    cur = doc
    for tok in tokens:
        if isinstance(cur, dict):
            if tok not in cur:
                raise BundleError(f"pointer token {tok!r} not found")
            cur = cur[tok]
        elif isinstance(cur, list):
            if not tok.isdigit() or (len(tok) > 1 and tok[0] == "0") or int(tok) >= len(cur):
                raise BundleError(f"bad array index {tok!r}")
            cur = cur[int(tok)]
        else:
            raise BundleError(f"cannot descend into {type(cur).__name__} at {tok!r}")
    return cur


def resolve_location(docs: Mapping[str, Any], location: str) -> Any:
    """Resolve ``location`` against ``docs`` (``{relative path: parsed JSON}``)."""
    path, tokens = split_location(location)
    if path not in docs:
        raise BundleError(f"location file {path!r} not available")
    return resolve_tokens(docs[path], tokens)


# --------------------------------------------------------------- entry makers
def make_object_entry(
    ref: str, digest_value: str, size: int, role: str,
    media_type: Optional[str] = None, license: Optional[str] = None,
    permission_status: Optional[str] = None,
) -> Dict[str, Any]:
    """One ``objects[]`` entry: an ArtifactRef-style ref plus ``size`` and ``role``."""
    entry: Dict[str, Any] = {"ref": ref, "digest": digest_value, "size": size, "role": role}
    for name, value in (("media_type", media_type), ("license", license),
                        ("permission_status", permission_status)):
        if value is not None:
            entry[name] = value
    _check_object(entry)
    return entry


def make_record_entry(
    kind: str, id: str, record_digest: Optional[str], record_location: Optional[str],
    body_location: Optional[str] = None, binding: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """One ``records[]`` entry (see module docstring)."""
    entry: Dict[str, Any] = {"kind": kind, "id": id}
    if record_digest is not None:
        entry["record_digest"] = record_digest
    if record_location is not None:
        entry["record_location"] = record_location
    if body_location is not None:
        entry["body_location"] = body_location
    if binding is not None:
        entry["binding"] = dict(binding)
    _check_record(entry)
    return entry


def _check_object(o: Any) -> None:
    if not isinstance(o, dict):
        raise BundleError(f"objects entries must be dicts, got {o!r}")
    _check_file_part(o.get("ref") if isinstance(o.get("ref"), str) else "")
    if not is_digest(o.get("digest")):
        raise BundleError(f"objects[].digest must be 'sha256:<64 hex>', got {o.get('digest')!r}")
    size = o.get("size")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise BundleError(f"objects[].size must be an int >= 0, got {size!r}")
    if not isinstance(o.get("role"), str) or not o["role"]:
        raise BundleError("objects[].role must be a non-empty string")


def _check_record(r: Any) -> None:
    if not isinstance(r, dict):
        raise BundleError(f"records entries must be dicts, got {r!r}")
    kind, rid = r.get("kind"), r.get("id")
    if not isinstance(kind, str) or not kind:
        raise BundleError("records[].kind must be a non-empty string")
    if not isinstance(rid, str) or not rid:
        raise BundleError("records[].id must be a non-empty string")
    sealed = kind not in UNSEALED_KINDS
    if sealed and (not is_digest(r.get("record_digest")) or not r.get("record_location")):
        raise BundleError(f"records[{kind}:{rid}] needs record_digest and record_location")
    if not sealed and (r.get("record_digest") is not None or r.get("record_location") is not None):
        raise BundleError(f"records[{kind}:{rid}] is an unsealed view and must not claim a seal")
    for loc in ("record_location", "body_location"):
        if r.get(loc) is not None:
            split_location(r[loc])
    if kind in UNSEALED_KINDS and r.get("body_location") is None:
        raise BundleError(f"records[{kind}:{rid}] needs a body_location")
    b = r.get("binding")
    if b is not None:
        if not isinstance(b, dict) or not isinstance(b.get("scheme"), str) or not is_digest(b.get("digest")):
            raise BundleError(f"records[{kind}:{rid}].binding must be {{scheme, digest}}")
        if r.get("body_location") is None:
            raise BundleError(f"records[{kind}:{rid}] has a binding but no body_location")


def make_coverage(verified: int, total: int, unverifiable_ids: Iterable[str] = ()) -> Dict[str, Any]:
    """``{records_verified, records_total, unverifiable_ids}`` (sorted ids)."""
    cov = {"records_verified": verified, "records_total": total,
           "unverifiable_ids": sorted(set(unverifiable_ids))}
    _check_coverage(cov)
    return cov


def _check_coverage(c: Any) -> None:
    if not isinstance(c, dict):
        raise BundleError("coverage must be a dict")
    v, t, u = c.get("records_verified"), c.get("records_total"), c.get("unverifiable_ids")
    for name, val in (("records_verified", v), ("records_total", t)):
        if isinstance(val, bool) or not isinstance(val, int) or val < 0:
            raise BundleError(f"coverage.{name} must be an int >= 0")
    if v > t:
        raise BundleError("coverage.records_verified exceeds records_total")
    if not isinstance(u, list) or not all(isinstance(i, str) for i in u) or u != sorted(set(u)):
        raise BundleError("coverage.unverifiable_ids must be a sorted list of unique strings")
    if len(u) != t - v:
        raise BundleError("coverage.unverifiable_ids must name exactly the unverified records")


def coverage_complete(c: Optional[Mapping[str, Any]]) -> bool:
    """True iff every counted record was verified."""
    return bool(c) and c["records_verified"] == c["records_total"]


def _check_tool(t: Any, what: str) -> None:
    if not isinstance(t, dict) or not isinstance(t.get("name"), str) or not t["name"]:
        raise BundleError(f"{what} must be a dict with a non-empty string name")
    if not isinstance(t.get("version"), str) or not t["version"]:
        raise BundleError(f"{what}.version is required (RO-Crate 1.3 check 32.3: a SoftwareApplication needs a version)")
    if t.get("url") is not None and not (isinstance(t["url"], str) and t["url"]):
        raise BundleError(f"{what}.url must be a non-empty string")
    sha = t.get("sha256")
    if sha is not None and not (isinstance(sha, str) and len(sha) == 64
                                and all(c in "0123456789abcdef" for c in sha)):
        raise BundleError(f"{what}.sha256 must be 64 lowercase hex chars (bare)")


def _check_replay(r: Any) -> None:
    if not isinstance(r, dict):
        raise BundleError("replay must be a dict")
    if r.get("assessor") is not None:
        _check_tool(r["assessor"], "replay.assessor")
    for name in ("status", "manifest_status", "checked_status"):
        if name in r:
            try:
                ReplayStatus(r[name])
            except ValueError:
                raise BundleError(f"replay.{name} is not a ReplayStatus value: {r[name]!r}") from None
    if "status" not in r:
        raise BundleError("replay.status is required")


def _check_gates(g: Any) -> None:
    if not isinstance(g, list):
        raise BundleError("gates must be a list")
    for item in g:
        if not isinstance(item, dict) or not isinstance(item.get("run_id"), str):
            raise BundleError("gates[] entries need a string run_id")
        if item.get("code") not in GATE_CODES:
            raise BundleError(f"gates[].code {item.get('code')!r} is not an allowlisted gate code {GATE_CODES}")
        if item.get("outcome") not in GATE_OUTCOMES:
            raise BundleError(f"gates[].outcome must be one of {GATE_OUTCOMES}")


def _okey_objects(o: Mapping[str, Any]) -> str:
    return o["ref"]


def _okey_records(r: Mapping[str, Any]) -> Tuple[str, str]:
    return (r["kind"], r["id"])


# --------------------------------------------------------------------- Bundle
@dataclasses.dataclass
class Bundle:
    """One session's sealed evidence-set identity. See module docstring.

    ``bundle_id`` and ``record_digest`` are computed by :meth:`seal`; construct
    with the content and the sealed-envelope assessments, then ``seal()``.
    """

    session_id: str
    objects: List[Dict[str, Any]] = dataclasses.field(default_factory=list)
    records: List[Dict[str, Any]] = dataclasses.field(default_factory=list)
    created_at: str = dataclasses.field(default_factory=utc_now)
    exporter: Optional[Dict[str, Any]] = None
    replay: Optional[Dict[str, Any]] = None
    coverage: Optional[Dict[str, Any]] = None
    gates: Optional[List[Dict[str, Any]]] = None
    effective_tier: Optional[str] = None
    schema: str = BUNDLE_SCHEMA
    canonicalization: str = CANONICALIZATION
    bundle_id: Optional[str] = None
    record_digest: Optional[str] = None
    unknown: Dict[str, Any] = dataclasses.field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if not self.session_id or not isinstance(self.session_id, str):
            raise BundleError("Bundle.session_id must be a non-empty string")
        for o in self.objects:
            _check_object(o)
        for r in self.records:
            _check_record(r)
        if len({_okey_objects(o) for o in self.objects}) != len(self.objects):
            raise BundleError("Bundle.objects has duplicate refs")
        if len({_okey_records(r) for r in self.records}) != len(self.records):
            raise BundleError("Bundle.records has duplicate (kind, id)")
        for name in ("bundle_id", "record_digest"):
            value = getattr(self, name)
            if value is not None and not is_digest(value):
                raise BundleError(f"Bundle.{name} must be 'sha256:<64 hex>' or None")
        if self.exporter is not None:
            _check_tool(self.exporter, "exporter")
        if self.replay is not None:
            _check_replay(self.replay)
        if self.coverage is not None:
            _check_coverage(self.coverage)
        if self.gates is not None:
            _check_gates(self.gates)

    # -- serialisation -------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        """Plain dict including preserved unknown fields."""
        d = {name: getattr(self, name) for name in _KNOWN_FIELDS}
        d = {k: v for k, v in d.items() if v is not None}
        for key, value in self.unknown.items():
            d.setdefault(key, value)
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Bundle":
        known = {k: d[k] for k in _KNOWN_FIELDS if k in d}
        unknown = {k: v for k, v in d.items() if k not in _KNOWN_FIELDS}
        return cls(**known, unknown=unknown)

    # -- identity and integrity ----------------------------------------
    def identity_payload(self) -> Dict[str, Any]:
        """The content the id covers: ``{schema, session_id, objects, records}``."""
        return {k: getattr(self, k) for k in _IDENTITY_FIELDS}

    def compute_id(self) -> str:
        """Content digest of the identity payload (does not mutate)."""
        return digest(self.identity_payload())

    def _sealing_payload(self) -> Dict[str, Any]:
        payload = self.to_dict()
        payload.pop("record_digest", None)
        return payload

    def compute_digest(self) -> str:
        return digest(self._sealing_payload())

    def normalise(self) -> "Bundle":
        """Sort ``objects`` by ref and ``records`` by (kind, id) (canonical order)."""
        self.objects.sort(key=_okey_objects)
        self.records.sort(key=_okey_records)
        return self

    def in_canonical_order(self) -> bool:
        return (self.objects == sorted(self.objects, key=_okey_objects)
                and self.records == sorted(self.records, key=_okey_records))

    def seal(self) -> "Bundle":
        """Normalise order, set ``bundle_id`` then ``record_digest``. Idempotent."""
        self.normalise()
        self.bundle_id = self.compute_id()
        self.record_digest = self.compute_digest()
        return self

    def verify_identity(self) -> bool:
        """True iff ``bundle_id`` still names the content and the order is canonical."""
        try:
            return (self.bundle_id is not None and self.in_canonical_order()
                    and self.compute_id() == self.bundle_id)
        except Exception:
            return False

    def verify(self) -> bool:
        """True iff identity and seal both hold. Any edit to any field fails."""
        if self.record_digest is None or not self.verify_identity():
            return False
        try:
            return self.compute_digest() == self.record_digest
        except Exception:
            return False

    # -- lookups ---------------------------------------------------------
    def record(self, kind: str, id: str) -> Optional[Dict[str, Any]]:
        for r in self.records:
            if r["kind"] == kind and r["id"] == id:
                return r
        return None

    def object(self, ref: str) -> Optional[Dict[str, Any]]:
        for o in self.objects:
            if o["ref"] == ref:
                return o
        return None


def verify_bundle_dict(d: Mapping[str, Any]) -> bool:
    """Verify a serialised bundle without trusting its declared id or seal."""
    try:
        return Bundle.from_dict(d).verify()
    except Exception:
        return False
