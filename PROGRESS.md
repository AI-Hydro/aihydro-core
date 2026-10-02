# aihydro-core progress

## 2026-10-02 — ClaimRevision (2040 slice 2 P0, branch `vision2040/claim-revision`, 0.2.2)

- Added `aihydro_core.records.claim`: `ClaimRevision` with seal, verify,
  unknown-field round-trip, `verify_chain` and `verify_claim_revision_dict`.
- Version bumped to 0.2.2. The stdlib-only guard test stays green.
- `pytest -q`: 168 passed (138 + 30 new incl. existing guard). Not merged or released.

## 2026-09-29 — Numeric-array content identity hardening

- Reproduced the reported large-array abbreviated-string collision from the September audit.
- Encoded numeric NumPy objects with complete bytes, shape and dtype through a standard-library-only JSON callback. Added nested and shape/dtype regressions.
- `/opt/miniconda3/bin/python -m pytest tests -q -m 'not live'`: 113 passed.
- Selected aihydro-data cache tests: 14 passed after this core change. This is local, uncommitted work; no cache migration or release performed.
# Repository synchronization — 2026-10-02

Re-ran the complete offline suite: 113 passed. Reviewed the numeric-array hashing
repair and its regression tests for commit/push; no PyPI release requested.

## 2026-10-02 — Canonical scientific records (2040 program slice 1, branch `vision2040/records-v2`)

- Added `aihydro_core.records`:
  - strict canonical JSON and `sha256:` digests;
  - `RunRecord` with seal and verify;
  - `Actor` and `ArtifactRef`;
  - an environment fingerprint;
  - `ReplayStatus`.
- The module is stdlib-only, enforced by an AST import test.
- `pytest -q`: 138 passed (113 existing + 25 new). `ruff check`: clean.
- The work lives on a branch in a git worktree. It is not merged or released.

## 2026-10-02 — Records contract hardened after adversarial review (T14)

- `aihydro.c14n/1` is now tagging plus RFC 8785 JCS serialisation, with ECMAScript numbers and UTF-16 key order. Integers above 2^53 are tagged.
  - Golden vectors in `tests/data/c14n_vectors.json`.
  - An independent JavaScript JCS check agreed byte-for-byte and digest-for-digest on 8 of 8 vectors.
- Masked-array masks and structured-dtype field names are now encoded, closing the aliasing the reviewer reproduced. Lone surrogates raise `UnencodableError`. `RunRecord` validates the nested actor, input refs and parents.
- The README now says seals prove integrity, not origin.
- `pytest -q`: 163 passed. `ruff`: clean.
