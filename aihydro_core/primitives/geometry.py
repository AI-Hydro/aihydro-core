"""
Feature — the addressable geometry primitive.

A Feature is a named, registered geometry that tools resolve by id/name rather
than by passing raw GeoJSON. Stored in the Feature registry (FeatureRegistry)
and referenced by a stable feature_id string.

Why this is in primitives (not features/):
  Both the Store protocol and the features block import this type. Placing it
  in primitives/ breaks the circular dependency.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


@dataclass
class Feature:
    """
    A named, registered geometry with a stable id.

    geojson is stored as a bare geometry dict ({"type": ..., "coordinates": ...})
    or a GeoJSON Feature dict. Callers that need a shapely geometry call
    shapely.geometry.shape(feature.geojson) — shapely is NOT imported here so
    that aihydro-core stays heavy-dep-free.

    Sources
    -------
    - "delineate_watershed" — auto-registered by the delineation tool
    - "map_annotation"     — registered from a VS Code map annotation (id reused verbatim)
    - "upload"             — user-uploaded GeoJSON file
    - "on-the-fly"         — transient registration from a raw GeoJSON string arg
    """

    feature_id: str
    geojson: dict                  # bare geometry or GeoJSON Feature dict
    name: str = ""                 # human label ("Annotation 2", "Upper basin")
    source: str = ""               # see docstring sources above
    bbox: tuple[float, float, float, float] | None = None  # (minx, miny, maxx, maxy)
    area_km2: float | None = None
    created_at: str = field(default_factory=_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    def geometry_dict(self) -> dict:
        """Return the bare geometry dict (unwrap GeoJSON Feature wrapper if present)."""
        if self.geojson.get("type") == "Feature":
            return self.geojson.get("geometry", self.geojson)
        return self.geojson

    def to_dict(self) -> dict:
        return {
            "feature_id": self.feature_id,
            "name": self.name,
            "source": self.source,
            "bbox": list(self.bbox) if self.bbox else None,
            "area_km2": self.area_km2,
            "created_at": self.created_at,
            "geojson": self.geojson,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Feature":
        bbox = d.get("bbox")
        return cls(
            feature_id=d["feature_id"],
            geojson=d["geojson"],
            name=d.get("name", ""),
            source=d.get("source", ""),
            bbox=tuple(bbox) if bbox else None,  # type: ignore[arg-type]
            area_km2=d.get("area_km2"),
            created_at=d.get("created_at", _now_iso()),
            metadata=d.get("metadata", {}),
        )
