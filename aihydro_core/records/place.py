"""
Canonical place identity (ADR-003 and its Amendment): ``BasinRef``,
``OutletRef``, ``ReachRef``, ``PlaceAlias`` and the geometry identity
algorithm ``aihydro.geom/1``.

Stdlib-only. This module is the *specification* of the types and algorithms;
aihydro-watershed is the only package that mints a ``BasinRef``.

Identity is a **network anchor**, not a polygon digest. ``BasinRef.id`` is
``"aihydro:basin:" + digest({"schema": "aihydro.basin_anchor/1", kind,
network, network_version, element})``. Aliases and geometry are excluded, so
the id is stable when an alias is added or the polygon is re-realised. The
polygon digest (``geometry_digest``, algorithm ``aihydro.geom/1``) identifies
one geometry *realisation* only. Different delineation methods anchor to
different network elements and so give different ``BasinRef`` ids; sameness
across methods is asserted through shared aliases or an explicit comparison
record, never by this module.

``aihydro.geom/1`` (``geometry_id``)
------------------------------------
Input: a GeoJSON-like mapping of type Polygon, MultiPolygon, Point or
MultiPoint, or ``{"type": "GaugeID", "scheme": ..., "id": ...}``.

1. Coordinates are EPSG:4326 lon/lat in degrees, used exactly as given (a third
   ordinate is ignored). Non-finite values, and lon outside [-180, 180] or lat
   outside [-90, 90], are rejected. There is no antimeridian unwrapping.
2. Quantise: each ordinate ``v`` becomes ``round(v * 1e6)`` (an ``int``;
   ``round`` is half-to-even on the IEEE-754 product).
3. Per ring: drop consecutive duplicate vertices and the closing vertex (if it
   repeats the first). Drop rings with fewer than 3 vertices or zero area
   (exact integer shoelace). A polygon whose exterior is dropped is dropped; if
   no polygon remains, ``PlaceIdentityError("DEGENERATE_GEOMETRY")``.
4. Exterior rings are counter-clockwise, holes clockwise (by the integer
   shoelace sign); each ring is rotated to start at its lexicographically
   smallest ``(x, y)`` vertex.
5. Holes are sorted within each polygon, then polygons are sorted, by their
   canonical integer lists. A single Polygon is emitted as a one-member
   MultiPolygon, so Polygon and an equivalent MultiPolygon share an id.
6. MultiPoint members are sorted and de-duplicated. Point and MultiPoint stay
   distinct types.
7. ``geometry_id`` is ``digest({"alg": "aihydro.geom/1", "q_exp": 6,
   "type": <type>, "coordinates": <ints>})`` (``aihydro.c14n/1``). For
   ``GaugeID`` the payload carries ``scheme`` and ``id`` instead of
   ``coordinates``.

Limits, stated plainly:

- The id is **not** tolerance-invariant. A perturbation that moves a
  coordinate across a quantisation boundary (a multiple of 5e-7 degrees,
  half-way between 1e-6 steps) changes the digest. About 2 in 20,000
  coordinates flip under a 1e-10 degree perturbation, which is why identity is
  an anchor and the digest only names a realisation.
- Antimeridian: a single polygon that crosses +-180 and is written with a
  longitude jump is treated as planar, so its shoelace area and orientation are
  those of the unwrapped-in-the-wrong-way ring. Such inputs are not rejected;
  :func:`crosses_antimeridian` flags them (an edge with ``|dlon| > 180``), and
  callers should split them into a MultiPolygon at +-180 before minting.
  Polygons split at the antimeridian canonicalise correctly.
- Polar caps and geodesic (great-circle) edges are not modelled.
"""
from __future__ import annotations

import dataclasses
import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from aihydro_core.records.canonical import digest, is_digest

BASIN_REF_SCHEMA = "aihydro.basin_ref/1"
BASIN_ANCHOR_SCHEMA = "aihydro.basin_anchor/1"
BASIN_ID_PREFIX = "aihydro:basin:"
GEOMETRY_ALGORITHM = "aihydro.geom/1"
GEOM_Q_EXP = 6
ALIAS_RELATIONS = ("same_as", "located_at", "derived_from", "fallback_of")
ANCHOR_KINDS = ("gauge_index", "network_element", "grid_cell")
UNVERSIONED = "unversioned"

_Q = 10 ** GEOM_Q_EXP


class PlaceIdentityError(ValueError):
    """A place or geometry could not be given an identity. ``code`` is stable."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code


# ------------------------------------------------------------------ helpers
def _need_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string, got {value!r}")
    return value


def _drop_none(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


def _split_unknown(d: Mapping[str, Any], known: Sequence[str]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    return ({k: d[k] for k in known if k in d}, {k: v for k, v in d.items() if k not in known})


def _merge_unknown(d: Dict[str, Any], unknown: Mapping[str, Any]) -> Dict[str, Any]:
    for key, value in unknown.items():
        d.setdefault(key, value)
    return d


def _set(obj: Any, name: str, value: Any) -> None:
    object.__setattr__(obj, name, value)


def _coerce_aliases(value: Any) -> Tuple["PlaceAlias", ...]:
    out: List[PlaceAlias] = []
    for a in value or ():
        out.append(a if isinstance(a, PlaceAlias) else PlaceAlias.from_dict(a))
    return tuple(out)


# ------------------------------------------------------------------ aliases
@dataclasses.dataclass(frozen=True)
class PlaceAlias:
    """An authority-namespaced identifier for the same or a related place."""

    scheme: str
    id: str
    relation: str = "same_as"
    source: Optional[str] = None
    verified: bool = False
    unknown: Dict[str, Any] = dataclasses.field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        _need_str(self.scheme, "PlaceAlias.scheme")
        if ":" in self.scheme:
            raise ValueError(f"PlaceAlias.scheme must not contain ':', got {self.scheme!r}")
        _need_str(self.id, "PlaceAlias.id")
        if self.relation not in ALIAS_RELATIONS:
            raise ValueError(f"PlaceAlias.relation must be one of {ALIAS_RELATIONS}, got {self.relation!r}")
        if self.source is not None and not isinstance(self.source, str):
            raise ValueError("PlaceAlias.source must be a string or None")
        if not isinstance(self.verified, bool):
            raise ValueError("PlaceAlias.verified must be a bool")

    def curie(self) -> str:
        return f"{self.scheme}:{self.id}"

    _KNOWN = ("scheme", "id", "relation", "source", "verified")

    def to_dict(self) -> Dict[str, Any]:
        d = _drop_none({k: getattr(self, k) for k in self._KNOWN})
        return _merge_unknown(d, self.unknown)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "PlaceAlias":
        known, unknown = _split_unknown(d, cls._KNOWN)
        return cls(**known, unknown=unknown)


# --------------------------------------------------------------- snap/outlet
@dataclasses.dataclass(frozen=True)
class SnapRef:
    """Where an outlet snapped on a named network (product and version)."""

    network: str
    network_version: str
    element: str
    distance_m: Optional[float] = None
    unknown: Dict[str, Any] = dataclasses.field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        _need_str(self.network, "SnapRef.network")
        _need_str(self.network_version, "SnapRef.network_version")
        _need_str(self.element, "SnapRef.element")
        if self.distance_m is not None:
            if isinstance(self.distance_m, bool) or not isinstance(self.distance_m, (int, float)) \
                    or not math.isfinite(self.distance_m) or self.distance_m < 0:
                raise ValueError(f"SnapRef.distance_m must be a finite number >= 0, got {self.distance_m!r}")

    _KNOWN = ("network", "network_version", "element", "distance_m")

    def to_dict(self) -> Dict[str, Any]:
        d = _drop_none({k: getattr(self, k) for k in self._KNOWN})
        return _merge_unknown(d, self.unknown)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "SnapRef":
        known, unknown = _split_unknown(d, cls._KNOWN)
        return cls(**known, unknown=unknown)


def _check_lonlat(lon: Any, lat: Any, what: str) -> None:
    for name, v, lim in (("lon", lon, 180.0), ("lat", lat, 90.0)):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or abs(v) > lim:
            raise ValueError(f"{what}.{name} must be a finite number within +-{lim:g}, got {v!r}")


@dataclasses.dataclass(frozen=True)
class OutletRef:
    """An outlet point, optionally snapped to a network, with aliases."""

    lon: float
    lat: float
    snap: Optional[SnapRef] = None
    aliases: Tuple[PlaceAlias, ...] = ()
    unknown: Dict[str, Any] = dataclasses.field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        _check_lonlat(self.lon, self.lat, "OutletRef")
        if isinstance(self.snap, Mapping):
            _set(self, "snap", SnapRef.from_dict(self.snap))
        elif self.snap is not None and not isinstance(self.snap, SnapRef):
            raise ValueError("OutletRef.snap must be a SnapRef, its dict, or None")
        _set(self, "aliases", _coerce_aliases(self.aliases))

    _KNOWN = ("lon", "lat", "snap", "aliases")

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"lon": self.lon, "lat": self.lat}
        if self.snap is not None:
            d["snap"] = self.snap.to_dict()
        d["aliases"] = [a.to_dict() for a in self.aliases]
        return _merge_unknown(d, self.unknown)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "OutletRef":
        known, unknown = _split_unknown(d, cls._KNOWN)
        return cls(**known, unknown=unknown)


@dataclasses.dataclass(frozen=True)
class ReachRef:
    """A river reach: a network element of a named, versioned network."""

    network: str
    network_version: str
    element: str
    aliases: Tuple[PlaceAlias, ...] = ()
    unknown: Dict[str, Any] = dataclasses.field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        _need_str(self.network, "ReachRef.network")
        _need_str(self.network_version, "ReachRef.network_version")
        _need_str(self.element, "ReachRef.element")
        _set(self, "aliases", _coerce_aliases(self.aliases))

    _KNOWN = ("network", "network_version", "element", "aliases")

    def to_dict(self) -> Dict[str, Any]:
        d = {"network": self.network, "network_version": self.network_version,
             "element": self.element, "aliases": [a.to_dict() for a in self.aliases]}
        return _merge_unknown(d, self.unknown)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "ReachRef":
        known, unknown = _split_unknown(d, cls._KNOWN)
        return cls(**known, unknown=unknown)


# -------------------------------------------------------------------- basin
@dataclasses.dataclass(frozen=True)
class BasinAnchor:
    """The network element a basin is anchored to. This alone fixes the id."""

    kind: str
    network: str
    network_version: str
    element: str

    def __post_init__(self) -> None:
        if self.kind not in ANCHOR_KINDS:
            raise ValueError(f"BasinAnchor.kind must be one of {ANCHOR_KINDS}, got {self.kind!r}")
        _need_str(self.network, "BasinAnchor.network")
        _need_str(self.network_version, "BasinAnchor.network_version (use 'unversioned' if unknown)")
        _need_str(self.element, "BasinAnchor.element")

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "network": self.network,
                "network_version": self.network_version, "element": self.element}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "BasinAnchor":
        extra = set(d) - {"kind", "network", "network_version", "element"}
        if extra:
            raise ValueError(f"BasinAnchor has unexpected fields {sorted(extra)}")
        return cls(**{k: d.get(k) for k in ("kind", "network", "network_version", "element")})


def basin_id_from_anchor(anchor: Any) -> str:
    """``"aihydro:basin:" + digest({"schema": "aihydro.basin_anchor/1", **anchor})``."""
    a = anchor if isinstance(anchor, BasinAnchor) else BasinAnchor.from_dict(anchor)
    return BASIN_ID_PREFIX + digest({"schema": BASIN_ANCHOR_SCHEMA, **a.to_dict()})


@dataclasses.dataclass(frozen=True)
class BasinRef:
    """A basin identity: network anchor + one geometry realisation + aliases.

    ``id`` defaults to the anchor-derived id. A supplied ``id`` is kept as
    given so that :func:`verify_basin_ref_dict` can detect a mismatch.
    """

    anchor: BasinAnchor
    method: str
    id: Optional[str] = None
    outlet: Optional[OutletRef] = None
    geometry_digest: Optional[str] = None
    geometry_algorithm: str = GEOMETRY_ALGORITHM
    area_km2: Optional[float] = None
    aliases: Tuple[PlaceAlias, ...] = ()
    minted_by: Dict[str, Any] = dataclasses.field(default_factory=dict)
    quality_flags: Tuple[str, ...] = ()
    schema: str = BASIN_REF_SCHEMA
    unknown: Dict[str, Any] = dataclasses.field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        if isinstance(self.anchor, Mapping):
            _set(self, "anchor", BasinAnchor.from_dict(self.anchor))
        elif not isinstance(self.anchor, BasinAnchor):
            raise ValueError("BasinRef.anchor must be a BasinAnchor or its dict")
        _need_str(self.method, "BasinRef.method")
        if self.id is None:
            _set(self, "id", basin_id_from_anchor(self.anchor))
        else:
            _need_str(self.id, "BasinRef.id")
        if isinstance(self.outlet, Mapping):
            _set(self, "outlet", OutletRef.from_dict(self.outlet))
        elif self.outlet is not None and not isinstance(self.outlet, OutletRef):
            raise ValueError("BasinRef.outlet must be an OutletRef, its dict, or None")
        if self.geometry_digest is not None and not is_digest(self.geometry_digest):
            raise ValueError(f"BasinRef.geometry_digest must be 'sha256:<64 hex>' or None, got {self.geometry_digest!r}")
        _need_str(self.geometry_algorithm, "BasinRef.geometry_algorithm")
        if self.area_km2 is not None:
            if isinstance(self.area_km2, bool) or not isinstance(self.area_km2, (int, float)) \
                    or not math.isfinite(self.area_km2) or self.area_km2 < 0:
                raise ValueError(f"BasinRef.area_km2 must be a finite number >= 0, got {self.area_km2!r}")
        _set(self, "aliases", _coerce_aliases(self.aliases))
        if not isinstance(self.minted_by, Mapping):
            raise ValueError("BasinRef.minted_by must be a dict {tool, version}")
        _set(self, "minted_by", dict(self.minted_by))
        flags = tuple(self.quality_flags or ())
        if not all(isinstance(f, str) and f for f in flags):
            raise ValueError("BasinRef.quality_flags must be non-empty strings")
        _set(self, "quality_flags", flags)
        _need_str(self.schema, "BasinRef.schema")

    def anchor_id(self) -> str:
        """The id the anchor implies (equals ``id`` for an honest ref)."""
        return basin_id_from_anchor(self.anchor)

    _KNOWN = ("schema", "id", "anchor", "outlet", "method", "geometry_digest", "geometry_algorithm",
              "area_km2", "aliases", "minted_by", "quality_flags")

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "schema": self.schema,
            "id": self.id,
            "anchor": self.anchor.to_dict(),
            "outlet": self.outlet.to_dict() if self.outlet is not None else None,
            "method": self.method,
            "geometry_digest": self.geometry_digest,
            "geometry_algorithm": self.geometry_algorithm,
            "area_km2": self.area_km2,
            "aliases": [a.to_dict() for a in self.aliases],
            "minted_by": dict(self.minted_by),
            "quality_flags": list(self.quality_flags),
        }
        return _merge_unknown(_drop_none(d), self.unknown)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "BasinRef":
        known, unknown = _split_unknown(d, cls._KNOWN)
        return cls(**known, unknown=unknown)


def verify_basin_ref_dict(d: Mapping[str, Any]) -> bool:
    """True iff ``d`` parses as a BasinRef and its ``id`` matches its anchor.

    Never trusts the declared id; aliases and geometry are not part of it.
    """
    try:
        ref = BasinRef.from_dict(d)
        return ref.schema == BASIN_REF_SCHEMA and ref.id == basin_id_from_anchor(ref.anchor)
    except Exception:
        return False


# ----------------------------------------------------------------- geometry
def _q(v: Any, what: str) -> int:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise PlaceIdentityError("INVALID_COORDINATE", f"{what}: {v!r} is not a number")
    if not math.isfinite(v):
        raise PlaceIdentityError("INVALID_COORDINATE", f"{what}: non-finite value {v!r}")
    return int(round(float(v) * _Q))


def _qpos(pos: Any, what: str) -> Tuple[int, int]:
    if not isinstance(pos, (list, tuple)) or len(pos) < 2:
        raise PlaceIdentityError("INVALID_COORDINATE", f"{what}: position must be [lon, lat], got {pos!r}")
    lon, lat = pos[0], pos[1]
    q_lon, q_lat = _q(lon, what), _q(lat, what)
    if abs(q_lon) > 180 * _Q or abs(q_lat) > 90 * _Q:
        raise PlaceIdentityError("INVALID_COORDINATE", f"{what}: ({lon!r}, {lat!r}) outside EPSG:4326 lon/lat range")
    return (q_lon, q_lat)


def _shoelace2(ring: Sequence[Tuple[int, int]]) -> int:
    """Twice the signed area in exact integer arithmetic (CCW positive)."""
    total = 0
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return total


def _clean_ring(raw: Any, what: str) -> Optional[List[Tuple[int, int]]]:
    if not isinstance(raw, (list, tuple)):
        raise PlaceIdentityError("INVALID_GEOMETRY", f"{what}: ring must be a list of positions")
    pts: List[Tuple[int, int]] = []
    for p in raw:
        q = _qpos(p, what)
        if not pts or pts[-1] != q:
            pts.append(q)
    while len(pts) > 1 and pts[-1] == pts[0]:
        pts.pop()
    if len(pts) < 3 or _shoelace2(pts) == 0:
        return None
    return pts


def _orient_rotate(ring: List[Tuple[int, int]], ccw: bool) -> List[List[int]]:
    if (_shoelace2(ring) > 0) != ccw:
        ring = ring[::-1]
    start = min(range(len(ring)), key=lambda i: ring[i])
    ring = ring[start:] + ring[:start]
    return [[x, y] for x, y in ring]


def _canonical_polygon(rings: Any, what: str) -> Optional[List[List[List[int]]]]:
    if not isinstance(rings, (list, tuple)) or not rings:
        raise PlaceIdentityError("INVALID_GEOMETRY", f"{what}: polygon needs at least an exterior ring")
    exterior = _clean_ring(rings[0], what + " exterior")
    if exterior is None:
        return None
    holes = []
    for i, h in enumerate(rings[1:]):
        cleaned = _clean_ring(h, f"{what} hole {i}")
        if cleaned is not None:
            holes.append(_orient_rotate(cleaned, ccw=False))
    holes.sort()
    return [_orient_rotate(exterior, ccw=True)] + holes


def canonical_geometry(geojson: Mapping[str, Any]) -> Dict[str, Any]:
    """The ``aihydro.geom/1`` payload (before hashing) for ``geojson``."""
    if not isinstance(geojson, Mapping):
        raise PlaceIdentityError("INVALID_GEOMETRY", "geometry must be a mapping")
    gtype = geojson.get("type")
    payload: Dict[str, Any] = {"alg": GEOMETRY_ALGORITHM, "q_exp": GEOM_Q_EXP}
    if gtype == "GaugeID":
        scheme, gid = geojson.get("scheme"), geojson.get("id")
        if not isinstance(scheme, str) or not scheme or not isinstance(gid, str) or not gid:
            raise PlaceIdentityError("INVALID_GEOMETRY", "GaugeID needs non-empty string scheme and id")
        payload.update({"type": "GaugeID", "scheme": scheme, "id": gid})
        return payload
    coords = geojson.get("coordinates")
    if gtype == "Point":
        payload.update({"type": "Point", "coordinates": list(_qpos(coords, "Point"))})
    elif gtype == "MultiPoint":
        if not isinstance(coords, (list, tuple)) or not coords:
            raise PlaceIdentityError("INVALID_GEOMETRY", "MultiPoint needs at least one position")
        pts = sorted({_qpos(p, "MultiPoint") for p in coords})
        payload.update({"type": "MultiPoint", "coordinates": [list(p) for p in pts]})
    elif gtype in ("Polygon", "MultiPolygon"):
        polys_in = [coords] if gtype == "Polygon" else coords
        if not isinstance(polys_in, (list, tuple)):
            raise PlaceIdentityError("INVALID_GEOMETRY", f"{gtype}: coordinates must be a list")
        polys = []
        for i, rings in enumerate(polys_in):
            p = _canonical_polygon(rings, f"{gtype}[{i}]")
            if p is not None:
                polys.append(p)
        if not polys:
            raise PlaceIdentityError("DEGENERATE_GEOMETRY", "no polygon with a non-degenerate exterior ring")
        polys.sort()
        payload.update({"type": "MultiPolygon", "coordinates": polys})
    else:
        raise PlaceIdentityError("UNSUPPORTED_GEOMETRY", f"geometry type {gtype!r} is not supported by {GEOMETRY_ALGORITHM}")
    return payload


def geometry_id(geojson: Mapping[str, Any]) -> str:
    """``sha256:`` digest of the canonical geometry (``aihydro.geom/1``). See module docstring."""
    return digest(canonical_geometry(geojson))


def crosses_antimeridian(geojson: Mapping[str, Any]) -> bool:
    """True if any polygon edge jumps more than 180 degrees of longitude.

    Such a ring is almost certainly an antimeridian crossing written without
    splitting; :func:`geometry_id` treats it as planar. Split it first.
    """
    gtype = geojson.get("type")
    coords = geojson.get("coordinates")
    if gtype == "Polygon":
        polys: Iterable[Any] = [coords]
    elif gtype == "MultiPolygon":
        polys = coords or []
    else:
        return False
    for rings in polys:
        for ring in rings or []:
            for a, b in zip(ring, list(ring[1:]) + list(ring[:1])):
                if abs(float(a[0]) - float(b[0])) > 180:
                    return True
    return False
