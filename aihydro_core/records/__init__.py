"""
aihydro_core.records — the canonical scientific record contract (ADR-001).

Stdlib-only. Provides one strict canonical encoding and ``sha256:`` digest
(``aihydro.c14n/1``), the sealed :class:`RunRecord` (schema ``aihydro.run/2``),
the sealed :class:`ClaimRevision` (schema ``aihydro.claim_revision_record/1``), the :class:`Actor` and :class:`ArtifactRef` value types, an environment
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
from aihydro_core.records.env import environment_fingerprint
from aihydro_core.records.replay import ReplayStatus
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
]
