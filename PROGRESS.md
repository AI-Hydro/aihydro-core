# aihydro-core progress

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
