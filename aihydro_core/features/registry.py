"""
FeatureRegistry — resolve geometry references to Feature objects.

This is the agent-facing geometry-addressing layer. An agent passes a short
string id (or name), not a raw GeoJSON blob. The registry resolves that ref
to a fully-loaded Feature so the compute kernel receives a clean geometry.

Resolution chain (resolve(ref)):
    str  → id lookup → name lookup → GeoJSON-string parse → register-on-fly
    dict → treat as GeoJSON, register on the fly
    None → active feature (preserves single-watershed back-compat)
"""
from __future__ import annotations

import json
import re
import uuid
from typing import TYPE_CHECKING

from ..primitives.geometry import Feature
from ..primitives.errors import FeatureNotFoundError

if TYPE_CHECKING:
    from ..store.protocol import Store


def _slugify(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return (s[:32] or uuid.uuid4().hex[:12])


def _extract_geometry(raw: dict) -> dict:
    """Return the bare geometry dict from either a GeoJSON Feature or bare geometry."""
    if raw.get("type") == "Feature":
        return raw.get("geometry", raw)
    return raw


class FeatureRegistry:
    """
    Geometry registry backed by a Store.

    Every spatial tool receives a FeatureRegistry built from the session's Store.
    The registry is the single resolution authority — tools never read geometries
    directly from the session.
    """

    def __init__(self, store: Store) -> None:
        self._store = store

    # ------------------------------------------------------------------ #
    # Registration                                                         #
    # ------------------------------------------------------------------ #

    def register(
        self,
        geojson: dict | str,
        name: str = "",
        source: str = "",
        feature_id: str | None = None,
        set_active: bool = False,
        area_km2: float | None = None,
        bbox: tuple[float, float, float, float] | None = None,
    ) -> Feature:
        """
        Register a geometry and return the Feature with its stable id.

        Parameters
        ----------
        geojson : dict | str
            GeoJSON dict or JSON string. Accepts bare geometry or GeoJSON Feature.
        name : str
            Human-readable label. Used as the display name and as a lookup alias.
        source : str
            Registration source tag ("delineate_watershed", "map_annotation", ...).
        feature_id : str | None
            Explicit id to assign. If None, derived from name (slugified) or UUID.
        set_active : bool
            If True, mark this feature as the active (default) feature.
        """
        if isinstance(geojson, str):
            try:
                geojson = json.loads(geojson)
            except json.JSONDecodeError as e:
                raise ValueError(f"geojson is not valid JSON: {e}") from e

        geom = _extract_geometry(geojson)

        if feature_id is None:
            feature_id = _slugify(name) if name else uuid.uuid4().hex[:12]

        feature = Feature(
            feature_id=feature_id,
            geojson=geom,
            name=name,
            source=source,
            bbox=bbox,
            area_km2=area_km2,
        )
        self._store.put_feature(feature)
        if set_active:
            self._store.set_active_feature_id(feature_id)
        self._store.commit()
        return feature

    # ------------------------------------------------------------------ #
    # Resolution                                                           #
    # ------------------------------------------------------------------ #

    def resolve(self, ref: str | dict | None) -> Feature:
        """
        Resolve a reference to a Feature.

        ref=None    → active feature (single-watershed back-compat)
        ref=str     → id lookup, then name lookup, then GeoJSON parse
        ref=dict    → treat as raw GeoJSON, register on the fly

        Raises FeatureNotFoundError with the list of available ids if ref
        cannot be resolved — so the error itself tells the agent what to do.
        """
        if ref is None:
            return self._resolve_active()

        if isinstance(ref, dict):
            return self.register(ref, source="on-the-fly")

        # --- string: id → name → GeoJSON parse → not found ---
        feat = self._store.get_feature(ref)
        if feat is not None:
            return feat

        for f in self._store.list_features():
            if f.name and f.name == ref:
                return f

        try:
            parsed = json.loads(ref)
            if isinstance(parsed, dict):
                return self.register(parsed, source="on-the-fly")
        except (json.JSONDecodeError, ValueError):
            pass

        available = [f.feature_id for f in self._store.list_features()]
        raise FeatureNotFoundError(ref=ref, available=available)

    def resolve_many(self, refs: list[str | dict]) -> list[Feature]:
        """Resolve a list of refs; raises FeatureNotFoundError on first miss."""
        return [self.resolve(r) for r in refs]

    def _resolve_active(self) -> Feature:
        active_id = self._store.get_active_feature_id()
        if active_id:
            feat = self._store.get_feature(active_id)
            if feat is not None:
                return feat
        # Fall back: return the most recently registered feature if only one exists
        features = self._store.list_features()
        if len(features) == 1:
            return features[0]
        raise FeatureNotFoundError(
            ref="<active>",
            available=[f.feature_id for f in features] if features else None,
        )

    # ------------------------------------------------------------------ #
    # Listing + active                                                     #
    # ------------------------------------------------------------------ #

    def list(self) -> list[Feature]:
        """Return all registered features."""
        return self._store.list_features()

    def set_active(self, feature_id: str) -> None:
        """Set the active (default) feature by id."""
        feat = self._store.get_feature(feature_id)
        if feat is None:
            available = [f.feature_id for f in self._store.list_features()]
            raise FeatureNotFoundError(ref=feature_id, available=available)
        self._store.set_active_feature_id(feature_id)
        self._store.commit()

    def get_active_id(self) -> str | None:
        return self._store.get_active_feature_id()
