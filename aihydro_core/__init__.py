"""
aihydro-core — the robustness substrate for AI-Hydro tools.

Five cross-cutting blocks, each solving one axis of tool reliability:

    primitives  — hashing, provenance (Artifact), errors (ToolError)
    store       — Store protocol (persistence-agnostic keyed result + feature store)
    jobs        — async execution (start/status/result/cancel/list + PID registry)
    features    — geometry addressing (Feature registry + @feature_tool decorator)
    science     — defensibility protocols: Claim lifecycle, Auditor, UncertaintyProvider
                  (Phase 3.1 kernel extraction — proves domain portability)

Domain packages (aihydro-tools, aihydro-data, aihydro-watershed, ...) depend on
this package. The *base* import (``import aihydro_core``) is stdlib-only.

The universal tool-output contract (``HydroResult``/``HydroMeta``/``DataSource``/
``HydroTool``) lives in ``contracts.py`` and requires pydantic. To keep the base
import dependency-free, the contract names are re-exported **lazily** here via
PEP 562 ``__getattr__`` — pydantic is imported only when a contract name is first
accessed (``from aihydro_core import HydroResult``). Install with
``pip install aihydro-core[contracts]``.

See AIHYDRO_CORE_DESIGN.md (local-docs/) for the full architecture.
"""

from typing import TYPE_CHECKING

__version__ = "0.2.0"

# Contract names re-exported lazily (pydantic-backed; see contracts.py).
_LAZY_CONTRACT_EXPORTS = {"HydroResult", "HydroMeta", "DataSource", "HydroTool"}


def __getattr__(name: str):
    """PEP 562 lazy attribute access — defers the pydantic import to first use."""
    if name in _LAZY_CONTRACT_EXPORTS:
        from aihydro_core import contracts
        return getattr(contracts, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(list(globals().keys()) + list(_LAZY_CONTRACT_EXPORTS))


if TYPE_CHECKING:  # static analyzers / IDEs see the names without triggering pydantic
    from aihydro_core.contracts import DataSource, HydroMeta, HydroResult, HydroTool
