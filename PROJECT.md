# aihydro-core

## What it is

Shared result, provenance, hashing, storage and job primitives for the AI-Hydro Python packages. Base import remains standard-library-only; optional scientific contracts are loaded lazily. See [README.md](README.md) for usage.

## Status

2026-10-02: research-pilot hardening verified for repository synchronization. Numeric NumPy arrays now contribute their full bytes, shape and dtype to `content_hash`; 113 offline tests pass. This is not a package release. Historical content hashes involving NumPy arrays will differ under this implementation.

## Where to read next

- Continue work: [ROADMAP.md](ROADMAP.md), then [PROGRESS.md](PROGRESS.md).
- Design rationale: [DECISIONS.md](DECISIONS.md).
- Hash implementation and tests: `aihydro_core/primitives/hashing.py`, `tests/test_primitives.py`.
- Parent ecosystem: `../../PROJECT.md`.

## Current state

The array-hash alias reproduced in the September watershed audit is fixed locally. Do not infer that all scientific object types have canonical content encodings: large pandas objects and arbitrary user-defined objects still fall back to string representation. A broader serialization contract and cache migration require a separate design.

## Non-goals

No hydrology-specific routing or signatures in core.

## How to test

`/opt/miniconda3/bin/python -m pytest tests -q -m 'not live'`
