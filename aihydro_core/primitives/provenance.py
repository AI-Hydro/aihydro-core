"""
Artifact — the provenance record every data fetch and compute emits.

A shared vocabulary for provenance across all blocks and packages. Both
aihydro-data (data fetch artifacts) and the feature block (computed-product
artifacts) produce Artifact instances with the same shape, so manifest records
and citations line up uniformly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


@dataclass
class Artifact:
    """
    Provenance record for one fetched or computed data item.

    param_hash   — hash of the parameters that produced it (from hashing.param_hash)
    content_hash — hash of the data content (from hashing.content_hash); used to
                   detect if the same params produced different data (e.g. API update)
    """
    artifact_id: str
    type: str                      # "raster" | "timeseries" | "vector" | "scalar" | "model"
    source: str                    # canonical source name: "usgs_3dep", "nlcd_2019", ...
    params: dict                   # the fetch/compute parameters (for re-run)
    param_hash: str                # deterministic hash of params
    content_hash: str              # fingerprint of the actual data
    units: str | None = None       # SI unit string if applicable
    created_at: str = field(default_factory=_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "artifact_id": self.artifact_id,
            "type": self.type,
            "source": self.source,
            "params": self.params,
            "param_hash": self.param_hash,
            "content_hash": self.content_hash,
            "units": self.units,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Artifact":
        return cls(
            artifact_id=d["artifact_id"],
            type=d.get("type", "unknown"),
            source=d.get("source", ""),
            params=d.get("params", {}),
            param_hash=d.get("param_hash", ""),
            content_hash=d.get("content_hash", ""),
            units=d.get("units"),
            created_at=d.get("created_at", _now_iso()),
            metadata=d.get("metadata", {}),
        )
