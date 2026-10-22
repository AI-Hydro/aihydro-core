# aihydro-core progress

## 2026-10-22 — Science Wave 3 PR-1: grouped bootstrap (branch `vision2040/w3-core`, 0.2.11, additive)

- Added `aihydro_core.science.water_year` (USGS: Oct 1 starts the year, labelled by end year).
- Added `grouped_bootstrap(fns, n_items, groups, n=2000, ci=0.90, random_state=0, min_groups=10)`:
  resamples whole groups with replacement, hands each `fn` the concatenated item-index array
  (paired statistics stay paired), percentile intervals. Output: `method="bootstrap_group"`,
  `n_groups`, `group`, `B`, `B_valid`, `low_n` (10-19 groups) and a machine-readable `scope`.
  Fewer than `min_groups` groups raises `ValueError` (no interval is reported).
- Added `aihydro_core.science.scope` (stdlib-only): `make_scope`, `water_year_sampling_scope`,
  `scope_excludes` with the critique-M6 shape `{"varies","assumes","excludes"}`; reusable by watershed.
- Added `annual_lag1_autocorrelation` (critique S2): reports the between-year persistence the
  grouped bootstrap does NOT capture. Its `high` flag uses a labelled engineering threshold (0.3), not a test.
- Limitation, tested and documented: groups are exchangeable, so within-year dependence is kept
  but between-year persistence is not.
- Review fixes: dropped replicates are reported (`B_valid`, `valid_frac`, `ci_degraded` when <95%
  valid, NaN CI with `ci_reason` when <50% valid or the point estimate is NaN/raises; one warning per
  raising metric). `n >= 100`, `0 < ci < 1`, `min_groups >= 2`, NaN group labels rejected.
  `low_n` now means < 30 groups. Metrics in one call share the same group draws.
- Coverage (honest): percentile group bootstrap under-covers at small group counts. Seeded
  simulation, iid years, 20 groups, nominal 90%, sample mean: 0.88 over 2000 trials (0.905 over the
  200 trials in the test-suite; statistic-dependent, skewed/ratio statistics can be worse). Surfaced
  as `coverage_note` / `COVERAGE_NOTE`.
- `water_year` uses the local wall-clock date for tz-aware input (tz dropped, not converted) and
  rejects numeric dtypes (TypeError). `scope_excludes` is conservative: excluded unless explicitly in
  `varies`; malformed scope = excluded. `annual_lag1_autocorrelation` pairs only truly consecutive
  years (`n_pairs`, `has_gaps`).
- Engineering constants (named, labelled, not statistical results): `DEGRADED_VALID_FRAC=0.95`,
  `NAN_CI_VALID_FRAC=0.5`, `MIN_LAG1_PAIRS=8` (below it lag-1 is NaN with `low_n=True`, never `high`),
  lag-1 `high_threshold=0.3`. The coverage test asserts a band (0.82-0.95); the exact 0.905 lives in the docs only.
- B defaults to 2000 (critique M7); the caller is responsible for building groups that are complete
  in every aligned series and for computing the point estimate on that same set (the function
  computes it on all `n_items`).

## 2026-10-03 — RO-Crate export (2040 slice 5 P5.2, branch `vision2040/slice5-core`, 0.2.4)

- Added `aihydro_core.export`: `to_rocrate` (RO-Crate 1.3 + Process Run Crate 0.6, one
  `CreateAction` per tool call, claims with explicit basis, statistics only from bound bodies,
  replay `AssessAction` with coverage, aliases as outlet `identifier`s), `validate_crate`
  (rule ids with spec clauses), `verify_crate` (regenerate-and-byte-compare, seals, bindings,
  chains, BagIt manifest) and the `python -m aihydro_core.export.rocrate` CLI.
- Golden synthetic capsule `tests/data/rocrate/capsule/` (byte-identical rebuild test); tamper
  tests for data, record, body, crate, action, File id, bundle, revision chain, replay level and
  path injection. Regenerate the golden only with `AIHYDRO_REGEN_GOLDEN=1`.
- Namespace for the in-graph terms is unregistered (OPEN-8); no AI-Hydro `conformsTo`.

## 2026-10-03 — Bundle (2040 slice 5 P5.1, branch `vision2040/slice5-core`, 0.2.4)

- Added `aihydro_core.records.bundle`: `Bundle` (`aihydro.bundle/1`). Identity is
  `digest({schema, session_id, objects, records})` only (M6); `created_at`, the replay
  assessment, record coverage, gates and tier sit in the sealed envelope. Unknown fields
  round-trip. `records[]` entries carry JSON Pointer locations (`~0`/`~1` escaping rule
  tested) and an optional body binding.
- Added `aihydro_core.records.entry`: the generic `aihydro.entry/1` body binding (digest of an
  object minus its `record` key) with golden vectors `tests/data/entry_vectors.json`.
- `ReplayStatus` is unchanged (no `archive_integrity_partial`, R2). Added `REPLAY_ORDER`,
  `replay_rank`, `min_replay_status` and `read_legacy_replay_status`, which maps the legacy
  string to `(ARCHIVE_INTEGRITY, complete=False)`. Partiality is the Bundle `coverage` record.
- Layering test extended: `aihydro_core.export` may import only stdlib + `aihydro_core.records`.
- Interface summary for the tools packets: `docs/vision-2040/plans/slice-5-interfaces.md`.

## 2026-10-02 — Place identity (2040 slice 3 P1, branch `vision2040/place-core`, 0.2.3)

- Added `aihydro_core.records.place`: `PlaceAlias`, `OutletRef`, `ReachRef`,
  `BasinRef`, `basin_id_from_anchor`, `verify_basin_ref_dict`, `geometry_id`
  (`aihydro.geom/1`), `canonical_geometry`, `crosses_antimeridian`.
- `INPUT_ROLES` gained `"place"`. Version bumped to 0.2.3. Stdlib-only guard stays green.
- Golden vectors `tests/data/place_vectors.json` re-derived independently by
  `tests/data/place_crosscheck.js` (Node): all 10 vectors agree.
- `pytest -q`: 189 passed (168 + 21 new). Not merged or released.

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
