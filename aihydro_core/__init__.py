"""
aihydro-core — the robustness substrate for AI-Hydro tools.

Five cross-cutting blocks, each solving one axis of tool reliability:

    primitives  — hashing, provenance (Artifact), errors (ToolError)
    store       — Store protocol (persistence-agnostic keyed result + feature store)
    jobs        — async execution (start/status/result/cancel/list + PID registry)
    features    — geometry addressing (Feature registry + @feature_tool decorator)
    science     — defensibility protocols: Claim lifecycle, Auditor, UncertaintyProvider
                  (Phase 3.1 kernel extraction — proves domain portability)

Domain packages (aihydro-tools, aihydro-data) depend on this package.
This package has zero heavy dependencies — it is stdlib only.

See AIHYDRO_CORE_DESIGN.md (local-docs/) for the full architecture.
"""

__version__ = "0.1.1"
