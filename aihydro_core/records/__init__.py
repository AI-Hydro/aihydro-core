"""
aihydro_core.records — the canonical scientific record contract (ADR-001).

Stdlib-only. Provides one strict canonical encoding and ``sha256:`` digest
(``aihydro.c14n/1``), the sealed :class:`RunRecord` (schema ``aihydro.run/2``),
the sealed :class:`ClaimRevision` (schema ``aihydro.claim_revision_record/1``), the sealed-identity :class:`Bundle` (``aihydro.bundle/1``) with the generic ``aihydro.entry/1`` body binding, the :class:`Actor` and :class:`ArtifactRef` value types, place identity (:class:`BasinRef`, ``aihydro.geom/1`` geometry ids), an environment
fingerprint, and the :class:`ReplayStatus` vocabulary.

Legacy digests elsewhere in the ecosystem (16-hex ``param_hash`` /
``content_hash``, registry ``sha256-v2`` fingerprints) are different
algorithms. They stay verifiable under their own tags and are never
recomputed or mapped onto this format.
"""
from aihydro_core.records.canonical import (
    CANONICALIZATION,
    DIGEST_PREFIX,
    UnencodableError,
    canonical_json,
    digest,
    digest_bytes,
    digest_or_error,
    is_digest,
)
from aihydro_core.records.claim import (
    CLAIM_REVISION_SCHEMA,
    ClaimRevision,
    verify_chain,
    verify_claim_revision_dict,
)
from aihydro_core.records.bundle import (
    BUNDLE_SCHEMA,
    GATE_CODES,
    GATE_OUTCOMES,
    RECORD_KINDS,
    UNSEALED_KINDS,
    Bundle,
    BundleError,
    coverage_complete,
    escape_pointer_token,
    make_coverage,
    make_location,
    make_object_entry,
    make_pointer,
    make_record_entry,
    resolve_location,
    resolve_tokens,
    split_location,
    unescape_pointer_token,
    verify_bundle_dict,
)
from aihydro_core.records.entry import (
    ENTRY_BINDING,
    entry_digest,
    make_binding,
    verify_binding,
)
from aihydro_core.records.env import environment_fingerprint
from aihydro_core.records.place import (
    ALIAS_RELATIONS,
    ANCHOR_KINDS,
    BASIN_REF_SCHEMA,
    GEOMETRY_ALGORITHM,
    BasinAnchor,
    BasinRef,
    OutletRef,
    PlaceAlias,
    PlaceIdentityError,
    ReachRef,
    SnapRef,
    basin_id_from_anchor,
    canonical_geometry,
    crosses_antimeridian,
    geometry_id,
    verify_basin_ref_dict,
)
from aihydro_core.records.replay import (
    LEGACY_PARTIAL,
    REPLAY_ORDER,
    ReplayStatus,
    min_replay_status,
    read_legacy_replay_status,
    replay_rank,
)
from aihydro_core.records.run import (
    ACTOR_KINDS,
    INPUT_ROLES,
    RUN_SCHEMA,
    RUN_STATUSES,
    Actor,
    ArtifactRef,
    RunRecord,
    input_ref,
    utc_now,
    verify_record_dict,
)

__all__ = [
    "CANONICALIZATION", "DIGEST_PREFIX", "UnencodableError", "canonical_json", "digest",
    "digest_bytes", "digest_or_error", "is_digest", "environment_fingerprint", "ReplayStatus",
    "ACTOR_KINDS", "INPUT_ROLES", "RUN_SCHEMA", "RUN_STATUSES", "Actor", "ArtifactRef",
    "RunRecord", "input_ref", "utc_now", "verify_record_dict",
    "CLAIM_REVISION_SCHEMA", "ClaimRevision", "verify_chain", "verify_claim_revision_dict",
    "ALIAS_RELATIONS", "ANCHOR_KINDS", "BASIN_REF_SCHEMA", "GEOMETRY_ALGORITHM", "BasinAnchor",
    "BasinRef", "OutletRef", "PlaceAlias", "PlaceIdentityError", "ReachRef", "SnapRef",
    "basin_id_from_anchor", "canonical_geometry", "crosses_antimeridian", "geometry_id",
    "verify_basin_ref_dict",
    "BUNDLE_SCHEMA", "GATE_CODES", "GATE_OUTCOMES", "RECORD_KINDS", "UNSEALED_KINDS", "Bundle",
    "BundleError", "coverage_complete", "escape_pointer_token", "make_coverage", "make_location",
    "make_object_entry", "make_pointer", "make_record_entry", "resolve_location",
    "resolve_tokens", "split_location", "unescape_pointer_token", "verify_bundle_dict",
    "ENTRY_BINDING", "entry_digest", "make_binding", "verify_binding",
    "LEGACY_PARTIAL", "REPLAY_ORDER", "min_replay_status", "read_legacy_replay_status",
    "replay_rank",
]
