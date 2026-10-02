# aihydro-core

Robustness substrate for the AI-Hydro ecosystem.

Provides the single hashing and provenance vocabulary (`content_hash`, `param_hash`,
`ProvenanceRecord`) shared across all AI-Hydro packages, plus the `Store` protocol and
`AsyncJobRegistry` used by higher-level layers.

**Zero heavy dependencies** — pure Python stdlib. Designed to be the lowest layer in the
stack so it can be safely depended on by any AI-Hydro package without pulling in numpy,
pandas, or geo libraries.

## Scientific records (`aihydro_core.records`)

The canonical record contract for runs, evidence and bundles (AI-Hydro 2040
program, ADR-001). It is stdlib-only.

- `digest(obj)` returns a `sha256:<64 hex>` digest of a **strict** canonical
  encoding (`aihydro.c14n/1`). This is a small Python tagging step followed by
  the JSON Canonicalization Scheme (RFC 8785), so any JCS implementation, for
  example in TypeScript, can verify digests. Golden vectors are in
  `tests/data/c14n_vectors.json`. Unknown types raise `UnencodableError`
  rather than being stringified, so abbreviated reprs (large arrays,
  DataFrames) can never alias. Masked-array masks, structured-dtype field
  names, big integers, non-finite floats, dates, bytes and sets all have
  tagged, deterministic encodings.
- `RunRecord` (schema `aihydro.run/2`) records a run's tool, version, input
  and output digests, input references, parent runs, environment digest,
  actor and an explicit `record_error`. `seal()` and `verify()` detect accidental or
  unsophisticated modification. A seal proves **integrity, not origin**:
  anyone who can write the record can edit it and re-seal it. Origin needs a
  signature or an independent store. Unknown fields round-trip unchanged.
- `ClaimRevision` (schema `aihydro.claim_revision_record/1`) is one sealed,
  append-only revision of a claim: `session_id`, `claim_id`, `revision` (>= 0),
  `supersedes` (the previous `revision_digest`), `revision_digest` (digest of
  the authority fields, computed by the writer), `content`, `cause`
  (`{tool, run_id?, reason}`), a required `actor`, `recorded_at` and
  `record_digest`. `verify_chain()` checks a claim's whole chain. The same
  integrity-not-origin caveat as `RunRecord` applies.
- `BasinRef` / `OutletRef` / `ReachRef` / `PlaceAlias` (`records/place.py`,
  ADR-003) are the canonical place-identity types, with `to_dict`/`from_dict`
  that preserve unknown fields. `BasinRef.id` is `"aihydro:basin:" +
  digest(anchor)`, where the anchor is `{kind, network, network_version,
  element}`; aliases and geometry are **excluded**, so the id is stable when
  an alias is added or the polygon is re-delineated. Different delineation
  methods give different ids; sameness across methods is asserted by shared
  aliases or an explicit comparison record. `verify_basin_ref_dict` recomputes
  the id. This package defines the types and algorithms; aihydro-watershed is
  the only minter.
- `geometry_id(geojson)` implements `aihydro.geom/1`: EPSG:4326 lon/lat
  quantised to 1e-6 degrees (integers), duplicate and closing vertices
  dropped, degenerate rings dropped, exterior CCW / holes CW, rings rotated to
  the smallest vertex, holes and polygons sorted, Polygon emitted as a
  one-member MultiPolygon, then `digest()`. It is invariant to ring rotation,
  reversal, duplicate vertices and hole/polygon order, and **not**
  tolerance-invariant: a coordinate that crosses a quantisation boundary
  changes the digest, which is why identity is the anchor and the digest
  names only one geometry realisation. Antimeridian-crossing polygons must be
  split first (`crosses_antimeridian` flags them). Golden vectors are in
  `tests/data/place_vectors.json`; `tests/data/place_crosscheck.js` re-derives
  them independently in Node.
- `environment_fingerprint(...)` describes the running interpreter, platform
  and named distributions.
- `ReplayStatus` names what a replay established: `not_performed`,
  `archive_integrity`, `cross_check`, `recomputed` or
  `independently_replicated`.

Legacy 16-hex `content_hash`/`param_hash` values are a different algorithm.
They remain valid as cache keys and are not mapped onto record digests.

## Install

```bash
pip install aihydro-core
```

## Part of the AI-Hydro ecosystem

- [aihydro-data](https://github.com/AI-Hydro/AIhydro-data) — global hydrology dataverse
- [AI-Hydro](https://github.com/AI-Hydro/AI-Hydro) — AI-native hydrologic modelling platform

## Citation

If you use `aihydro-core` in your research, please cite:

```bibtex
@software{aihydro_core_2026,
  title   = {aihydro-core: Zero-Dependency Substrate for Scientific Defensibility},
  author  = {Galib, Mohammad and Merwade, Venkatesh},
  year    = {2026},
  version = {0.2.0},
  doi     = {10.5281/zenodo.20823444},
  url     = {https://doi.org/10.5281/zenodo.20823444}
}
```
