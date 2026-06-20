# aihydro-core — Decisions (ADR-style)

Append-only. Newest first. One entry per non-obvious choice, with the **why**.

---

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

**Deferred — `ToolError` unification.** Two `ToolError`s exist: the tool-facing
one (`code/message/tool/recovery/alternatives`, used across aihydro-tools) and
core's `primitives/errors.py` one (`code/message/details`). They are
**not** unified here — the signatures differ and forcing it now would be a
behavior change. The richer `ToolError` stays local in the tools shim. Unify in
a dedicated follow-up (extend core's to accept the richer kwargs as a superset).
