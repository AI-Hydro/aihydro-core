# aihydro-core — Decisions (ADR-style)

Append-only. Newest first. One entry per non-obvious choice, with the **why**.

---

## 2026-10-02 — ClaimRevision record (slice 2, P0; core 0.2.2)

**Decision.** Add a stdlib `ClaimRevision` (`aihydro.claim_revision_record/1`)
to `aihydro_core.records`. `revision_digest` is supplied by the writer, not
computed in core; `supersedes` links to the previous `revision_digest`; `actor`
is required; `cause.reason` is a free non-empty string so tools can extend it.

**Why.** Claim authority (ADR-002) needs an append-only revision chain that
approvals bind to. The digest of the authority fields already exists in tools
(`aihydro.claim_revision/2`), and it must not be re-derived in two places.
Core therefore seals rows and checks chains, and the writer owns the content
digest.

**Reference.** ADR-001, ADR-002; `docs/vision-2040/plans/slice-2.md`.

---

## 2026-10-02 — Strict canonical records alongside legacy hashing

**Decision.** Add `aihydro_core.records` with its own strict canonicalization
(`aihydro.c14n/1`, full `sha256:` digests) and a sealed `RunRecord`. Leave
`primitives.hashing` unchanged.

**Why.** `content_hash` truncates to 16 hex characters and falls back to
`str(value)` for unknown types. A DataFrame's abbreviated repr therefore
aliases different data, the same failure class as the 2026-09-29 array fix.
Changing `content_hash` in place would silently invalidate every persisted
cache key. A provenance digest must refuse what it cannot encode. A cache key
may be best-effort.

**Alternative rejected.** Making `content_hash` strict was rejected because it
breaks existing caches, and callers that hash arbitrary request payloads
would start raising.

**Reference.** AI-Hydro 2040 program ADR-001
(`docs/vision-2040/adr/ADR-001-canonical-record-model.md` in the workspace root).

## 2026-09-29 — Full numeric-array bytes in content identities

`content_hash` previously serialized a NumPy array through abbreviated `str()`,
so distinct long arrays with equal visible edges had the same fingerprint.
Encode full bytes, shape and dtype through the standard-library serializer
without importing NumPy into the base package. This changes hash values for
NumPy-containing objects; historical cache keys must be treated as different
identities, not silently interpreted as canonical. Arbitrary pandas/user objects
remain outside this narrow repair and need a separate versioned contract.


## 2026-06-19 — Result contract promoted into core, behind a lazy pydantic boundary

**Decision.** The universal tool-output contract — `HydroResult`, `HydroMeta`,
`DataSource`, `HydroTool` — now lives in `aihydro_core/contracts.py` (promoted
from `aihydro-tools`' `ai_hydro/core/types.py`). Every ecosystem package
(data, watershed, lsh, modelling) returns this one typed result instead of
duplicating it. Version bumped `0.1.1 → 0.2.0`.

**Why promote.** Without a shared contract in the substrate, each new package
re-copies it — the monolith trap one layer up (see ecosystem ADR-002).

**The pydantic tension + how it's resolved.** The contract is pydantic, but
`aihydro-core`'s product thesis (ADR-001 §4.3) is a *showable zero-dep substrate*.
To preserve that: the base import `import aihydro_core` stays **stdlib-only**;
the contract is re-exported **lazily** from `__init__.py` via PEP 562
`__getattr__`, so pydantic is imported only when a contract name is first accessed
(`from aihydro_core import HydroResult`). pydantic is declared as the optional
extra `aihydro-core[contracts]` (and `[science]`, which already needed it).
Verified: base import does not load pydantic; `from aihydro_core import HydroResult`
works; the tools shim re-exports the *same* class object (single definition).

**Alternative rejected.** Making pydantic a hard top-level dependency — simpler,
but dilutes the zero-dep narrative the founder explicitly values. Reversible if
that narrative is later dropped.

**Backward compatibility.** `ai_hydro/core/types.py` is now a re-export shim;
`from ai_hydro.core import HydroResult` keeps working. Shim kept ≥ one release.
Gate: full `aihydro-tools` suite green (929 passed) + `aihydro-core` (100 passed).

**`ToolError` unified (Wave A2a, 2026-06-19).** The superset signature is:
`(code, message, details=None, *, tool=None, recovery=None, alternatives=None)`.
`tool/recovery/alternatives` are keyword-only so the old positional
`(code, message, details)` form — used by `FeatureNotFoundError` and
`StoreError` — keeps working unchanged. `ToolError` is now exported eagerly at
core's top level (stdlib-only, no lazy needed). The tools shim re-exports from
core; `from ai_hydro.core import ToolError` and `from aihydro_core import ToolError`
return the same class object. Gate: 103 core tests green + identity check passed.
