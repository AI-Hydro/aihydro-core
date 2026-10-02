# aihydro-core roadmap

1. Preserve stable primitive and result contracts across consuming packages.
2. Verify local numeric-array hash hardening against package consumers before release. Status 2026-09-29: core 113 tests and selected data cache tests pass; complete cross-package release check pending.
3. Define a versioned canonical serialization contract for pandas, xarray, masked/object arrays and legacy cache identities if the publication pilot requires them. Do not claim this exists yet.

Ecosystem research and publication sequencing lives in `../../papers/RESEARCH_PROGRAM.md`.
