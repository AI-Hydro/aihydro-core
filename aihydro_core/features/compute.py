"""
feature_compute — the @feature_tool decorator and FeatureComputation helper.

C2 placeholder. Stub is importable so C0/C1 tests don't break.

Full implementation (C2):
  - @feature_tool(product, citations) decorator
  - Single-feature fast path: resolve → cache-check → compute → store → provenance
  - Batch path (feature=list): fan-out via aihydro_core.jobs, N detached processes,
    parent job_id with cascade cancel
  - Injects (feature, session_id, batch) into the MCP-exposed tool signature

See AIHYDRO_CORE_DESIGN.md §6.2 for the full block spec.
"""
from __future__ import annotations

# C2 stubs — will be replaced with real implementations in C2.

class _Unimplemented:
    def __init__(self, name: str):
        self._name = name
    def __call__(self, *a, **kw):
        raise NotImplementedError(
            f"aihydro_core.features.compute.{self._name} is a C2 placeholder. "
            "It will be implemented after C1 (feature registry + two-level slots) "
            "is proven end-to-end on compute_twi."
        )
    def __repr__(self):
        return f"<C2 placeholder: {self._name}>"


feature_tool = _Unimplemented("feature_tool")
FeatureComputation = _Unimplemented("FeatureComputation")

__all__ = ["feature_tool", "FeatureComputation"]
