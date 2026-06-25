# aihydro-core — Architecture

Zero-dependency substrate for the AI-Hydro ecosystem.  Every other package
depends down onto `aihydro-core`; nothing in core imports aihydro-data,
aihydro-watershed, aihydro-lsh, or ai_hydro (aihydro-tools).

---

## Position in the ecosystem

```
         ╔══════════════════════════════════╗
         ║          aihydro-core            ║  ← THIS PACKAGE
         ║  contracts · science · store     ║
         ║  primitives · jobs · features    ║
         ╚═════════════════════════════════╧╗
                    ▲         ▲            ║
       ┌────────────┤         ├───────────┐║
  aihydro-data  pygeoglim  aihydro-       ║║
  (routing,     (geology)  watershed      ║║
   products)               (delineation)  ║║
       │                       │          ║║
       └──────────────┬────────┘          ║║
                      ▼                   ║║
                 aihydro-lsh              ║║
                 (CAMELS recipes)         ║║
                      │                   ║║
                      ▼                   ║║
                 aihydro-tools            ║║
                 (MCP surface, meta-pkg)  ║╝
```

---

## Module map

```
aihydro_core/
│
├── contracts.py         ┐
│   HydroResult          │  The shared contract:
│   HydroMeta            │  all compute functions across the ecosystem
│   DataSource           │  return HydroResult (lazy PEP-562 re-export;
│   HydroTool            │  pydantic only if [contracts] extra installed)
│                        ┘
├── primitives/
│   ├── errors.py        ToolError(code, message, details, tool, recovery, alternatives)
│   │                    FeatureNotFoundError · StoreError
│   ├── hashing.py       deterministic_hash() → hex string (SHA-256 of canonical JSON)
│   ├── provenance.py    ProvenanceRecord, stamp(), verify()
│   └── geometry.py      geometry utilities (bbox normalisation, CRS helpers)
│
├── science/
│   ├── claim.py         Claim protocol + ClaimStore protocol
│   ├── audit.py         Auditor protocol (can_audit, audit → AuditResult)
│   ├── uncertainty.py   UncertaintyProvider protocol; re-exports _bootstrap symbols
│   └── _bootstrap.py    bootstrap_ci · block_bootstrap_ci · bootstrap_dict
│                        UncertaintyResult dataclass
│                        (numpy in [science] extra; stdlib-only for import)
│
├── store/
│   ├── protocol.py      HydroStore protocol (get/put/list/delete, typed)
│   └── memory.py        InMemoryStore — reference impl for tests
│
├── jobs/
│   └── __init__.py      Job · JobResult · run_job() — lightweight task wrapper
│
├── features/
│   ├── registry.py      FeatureRegistry — maps name → FeatureTool
│   └── compute.py       compute_features() — batch dispatch
│
└── __init__.py          Lazy PEP-562 module (heavy deps imported on first attr access)
```

---

## Dependency extras

```
pip install aihydro-core            # stdlib only — contracts via dicts
pip install aihydro-core[contracts] # + pydantic — typed HydroResult validation
pip install aihydro-core[science]   # + numpy  — bootstrap CI, uncertainty math
```

The stdlib-only install is intentional: downstream packages that only need
primitive errors, hashing, provenance, stores, jobs, or feature registries do not
pull in numpy/pydantic. Packages that validate or construct typed `HydroResult`
objects declare `aihydro-core[contracts]`.

---

## Key data flows

### HydroResult contract

Every compute function in the ecosystem wraps its output in `HydroResult`:

```
any_computation(params) → HydroResult(
    data        = <xarray / GeoDataFrame / dict>,
    meta        = HydroMeta(
                    tool="fetch_precipitation",
                    version="0.2.0",
                    sources=[DataSource(name="CHIRPS", ...)],
                    params={...},
                  ),
    warnings    = [...],
    errors      = [...],
)
```

### Science protocol chain (audit/uncertainty)

```
ClaimStore.put(claim)          ← store a research claim
    │
    ▼
Auditor.audit(claim)           ← check claim validity
    │
    ▼
UncertaintyProvider
  .bootstrap_ci(data, stat)   ← bootstrap confidence intervals
    │
    ▼
UncertaintyResult(
    estimate, lower, upper,
    n_bootstrap, confidence
)
```

### Provenance chain

```
deterministic_hash(params) → run_id
    │
    ├── stamp(result, run_id) → ProvenanceRecord
    └── verify(record)        → bool
```

---

## Design principles

1. **Zero heavy deps at top level** — `import aihydro_core` never triggers numpy,
   pydantic, or geopandas.  All heavy deps are lazy or extra-gated.
2. **Protocol-oriented** — ClaimStore, Auditor, HydroStore are runtime-checkable
   `typing.Protocol`s.  `aihydro-tools` ships concrete implementations;
   tests use the in-memory stubs here.
3. **Stable semver** — anything exported from `contracts.py` is part of the public
   API; breaking changes require a major bump.

---

## Test suite

```
tests/
├── test_contracts.py    HydroResult construction + pydantic round-trip
├── test_primitives.py   hashing, provenance stamp/verify, ToolError subclasses
├── test_science.py      ClaimStore conformance, Auditor protocol, bootstrap CI
├── test_store.py        InMemoryStore get/put/list/delete round-trips
├── test_jobs.py         run_job() dispatch
├── test_features.py     FeatureRegistry + compute_features()
├── test_feature_tool.py HydroTool conformance
└── test_layering.py     AST guard — zero imports of ai_hydro / aihydro_data / etc.
```
