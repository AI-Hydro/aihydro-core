"""
aihydro-core — the universal tool-output contract
==================================================

Every tool in the AI-Hydro ecosystem returns a ``HydroResult``: a typed,
JSON-serializable envelope carrying the output data plus full FAIR provenance
metadata. Promoting this contract into the substrate (rather than housing it
inside ``aihydro-tools``) lets every package — data, watershed, lsh, modelling —
return the *same* typed result without duplicating the definition.

This module depends on ``pydantic`` (v2). To keep the ``aihydro-core`` *base*
import (``import aihydro_core``) dependency-free, the contract is re-exported
lazily from the package ``__init__`` via PEP 562 ``__getattr__`` — pydantic is
only imported when a contract name is actually accessed. Install the dependency
explicitly with ``pip install aihydro-core[contracts]``.

Usage
-----
>>> from aihydro_core import HydroResult, HydroMeta, DataSource
>>> result.data['area_km2']          # float
>>> result.meta.cite()               # BibTeX string
>>> result.to_dict()                 # fully serializable dict
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Data provenance building blocks
# ---------------------------------------------------------------------------

class DataSource(BaseModel):
    """A single data source used in computing a result."""
    name: str = Field(..., description="Short name, e.g. 'USGS NLDI'")
    url: str | None = Field(None, description="API endpoint or dataset URL")
    accessed: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).date().isoformat(),
        description="ISO date the source was accessed"
    )
    citation: str | None = Field(
        None,
        description="BibTeX or APA citation for the data source"
    )


class HydroMeta(BaseModel):
    """
    FAIR provenance metadata attached to every HydroResult.

    Contains everything needed to reproduce the computation and cite
    the data sources in a manuscript methods section.
    """
    tool: str = Field(..., description="Full tool identifier, e.g. 'aihydro_watershed.delineate_watershed'")
    version: str = Field(..., description="Package version, e.g. '1.0.0'")
    gauge_id: str | None = Field(None, description="USGS gauge ID if applicable")
    sources: list[DataSource] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict, description="Exact inputs used")
    computed_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 timestamp of computation"
    )

    def cite(self) -> str:
        """Generate a BibTeX block for all data sources used."""
        entries = []
        for src in self.sources:
            if src.citation:
                entries.append(src.citation)
        if not entries:
            return f"% No citations available for {self.tool}"
        return "\n\n".join(entries)

    def to_methods_text(self) -> str:
        """Generate a manuscript-ready methods paragraph."""
        source_names = [s.name for s in self.sources]
        sources_str = ", ".join(source_names) if source_names else "undocumented sources"
        params_str = ", ".join(f"{k}={v!r}" for k, v in self.params.items())
        return (
            f"This result was computed using {self.tool} (version {self.version}) "
            f"with parameters: {params_str}. "
            f"Data sourced from: {sources_str}. "
            f"Computed on {self.computed_at[:10]}."
        )


# ---------------------------------------------------------------------------
# The universal tool output type
# ---------------------------------------------------------------------------

class HydroResult(BaseModel):
    """
    Standardized output for every AI-Hydro tool.

    All data is stored in a flat, JSON-serializable dictionary.
    Geometry is always GeoJSON (dict), never Shapely.
    Time series are always {dates: [...], values: [...]} dicts.
    All numeric values are Python float/int, never numpy scalars.
    """
    data: dict[str, Any] = Field(..., description="Flat, JSON-serializable output dict")
    meta: HydroMeta

    @model_validator(mode='after')
    def _validate_json_serializable(self) -> HydroResult:
        """Ensure data dict contains only JSON-serializable values."""
        import json
        try:
            json.dumps(self.data)
        except (TypeError, ValueError) as e:
            raise ValueError(
                f"HydroResult.data must be fully JSON-serializable. "
                f"Found non-serializable value: {e}. "
                f"Convert Shapely geometries to GeoJSON dicts, "
                f"numpy arrays to lists, and numpy scalars to Python floats."
            ) from e
        return self

    def to_dict(self) -> dict[str, Any]:
        """Return fully JSON-serializable dict including metadata."""
        return {
            "data": self.data,
            "meta": self.meta.model_dump()
        }


# ---------------------------------------------------------------------------
# Community tool base class
# ---------------------------------------------------------------------------

class HydroTool:
    """
    Base class for all AI-Hydro community tools.

    Community contributors subclass this and implement ``run()`` and ``validate()``.
    The MCP server discovers and registers all subclasses automatically.
    """
    name: str = ""
    description: str = ""
    category: str = ""
    version: str = "0.1.0"
    data_sources: list[DataSource] = []

    def run(self, **kwargs) -> HydroResult:
        raise NotImplementedError("Subclasses must implement run()")

    def validate(self) -> bool:
        raise NotImplementedError("Subclasses must implement validate()")

    @classmethod
    def get_schema(cls) -> dict:
        """Return MCP-compatible tool schema."""
        return {
            "name": cls.name,
            "description": cls.description,
            "category": cls.category,
            "version": cls.version,
            "sources": [s.model_dump() for s in cls.data_sources],
        }


__all__ = ["DataSource", "HydroMeta", "HydroResult", "HydroTool"]
