"""Place identity: aihydro.geom/1 invariances, BasinRef anchor id, golden vectors."""
import copy
import json
from pathlib import Path

import pytest

from aihydro_core.records import (
    BasinRef,
    OutletRef,
    PlaceAlias,
    PlaceIdentityError,
    ReachRef,
    basin_id_from_anchor,
    canonical_geometry,
    crosses_antimeridian,
    digest,
    geometry_id,
    input_ref,
    verify_basin_ref_dict,
)

EXT = [[0.0, 0.0], [4.0, 0.0], [4.0, 4.0], [0.0, 4.0], [0.0, 0.0]]  # CCW, closed
HOLE_A = [[1.0, 1.0], [1.0, 2.0], [2.0, 2.0], [2.0, 1.0], [1.0, 1.0]]  # CW
HOLE_B = [[3.0, 3.0], [3.0, 3.5], [3.5, 3.5], [3.5, 3.0], [3.0, 3.0]]  # CW
SQ2 = [[10.0, 10.0], [11.0, 10.0], [11.0, 11.0], [10.0, 11.0], [10.0, 10.0]]


def poly(*rings):
    return {"type": "Polygon", "coordinates": [list(r) for r in rings]}


def rotate(ring, k):
    body = ring[:-1]
    body = body[k:] + body[:k]
    return body + [body[0]]


def test_rotation_reversal_duplicates_invariance():
    base = geometry_id(poly(EXT, HOLE_A))
    for k in range(1, 4):
        assert geometry_id(poly(rotate(EXT, k), HOLE_A)) == base
        assert geometry_id(poly(EXT, rotate(HOLE_A, k))) == base
    assert geometry_id(poly(EXT[::-1], HOLE_A)) == base  # exterior reversed (CW input)
    assert geometry_id(poly(EXT, HOLE_A[::-1])) == base  # hole reversed (CCW input)
    dup = EXT[:2] + [EXT[1], EXT[1]] + EXT[2:]
    assert geometry_id(poly(dup, HOLE_A)) == base
    unclosed = EXT[:-1]
    assert geometry_id(poly(unclosed, HOLE_A)) == base
    # 3-D positions: z is ignored
    z = [[x, y, 99.0] for x, y in EXT]
    assert geometry_id(poly(z, HOLE_A)) == base


def test_hole_and_polygon_order_invariance():
    assert geometry_id(poly(EXT, HOLE_A, HOLE_B)) == geometry_id(poly(EXT, HOLE_B, HOLE_A))
    p1, p2 = [EXT, HOLE_A], [SQ2]
    m1 = {"type": "MultiPolygon", "coordinates": [p1, p2]}
    m2 = {"type": "MultiPolygon", "coordinates": [p2, p1]}
    assert geometry_id(m1) == geometry_id(m2)


def test_polygon_equals_one_member_multipolygon_but_points_stay_distinct():
    assert geometry_id(poly(EXT)) == geometry_id({"type": "MultiPolygon", "coordinates": [[EXT]]})
    assert geometry_id({"type": "Point", "coordinates": [1, 2]}) != geometry_id(
        {"type": "MultiPoint", "coordinates": [[1, 2]]})


def test_multipoint_order_and_duplicates():
    a = {"type": "MultiPoint", "coordinates": [[1, 2], [3, 4], [1, 2]]}
    b = {"type": "MultiPoint", "coordinates": [[3, 4], [1, 2]]}
    assert geometry_id(a) == geometry_id(b)


def test_canonical_orientation_and_start():
    payload = canonical_geometry(poly(EXT[::-1], HOLE_A[::-1]))
    ext, hole = payload["coordinates"][0]
    assert ext[0] == [0, 0] and ext[1] == [4_000_000, 0]  # CCW from smallest vertex
    assert hole[0] == [1_000_000, 1_000_000] and hole[1] == [1_000_000, 2_000_000]  # CW
    assert payload["alg"] == "aihydro.geom/1" and payload["q_exp"] == 6 and payload["type"] == "MultiPolygon"


def test_quantisation_boundary_non_invariance_is_documented():
    """Not tolerance-invariant: crossing a quantum boundary changes the digest."""
    def tri(x):
        return poly([[10.0, 10.0], [x, 10.0], [10.0, 11.0], [10.0, 10.0]])

    # Same quantum: invariant under a sub-quantum shift ...
    assert geometry_id(tri(11.0000001)) == geometry_id(tri(11.0000002))
    # ... a shift of about 2e-7 deg that straddles the 5e-7 boundary changes it.
    assert geometry_id(tri(11.0000004)) != geometry_id(tri(11.0000006))


def test_degenerate_geometry_raises():
    with pytest.raises(PlaceIdentityError) as e:
        geometry_id(poly([[0, 0], [1, 1], [2, 2], [0, 0]]))  # zero area
    assert e.value.code == "DEGENERATE_GEOMETRY"
    with pytest.raises(PlaceIdentityError) as e:
        geometry_id(poly([[0, 0], [0.0000001, 0], [0, 0.0000001], [0, 0]]))  # collapses on quantising
    assert e.value.code == "DEGENERATE_GEOMETRY"
    with pytest.raises(PlaceIdentityError):
        geometry_id(poly([[0, 0], [1, 0], [0, 0]]))
    # degenerate hole is dropped, not fatal
    assert geometry_id(poly(EXT, [[1, 1], [2, 2], [3, 3], [1, 1]])) == geometry_id(poly(EXT))
    # a degenerate member polygon is dropped when another remains
    deg = [[0, 0], [1, 1], [2, 2], [0, 0]]
    assert geometry_id({"type": "MultiPolygon", "coordinates": [[deg], [EXT]]}) == geometry_id(poly(EXT))


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_non_finite_rejected(bad):
    with pytest.raises(PlaceIdentityError) as e:
        geometry_id(poly([[0, 0], [1, 0], [bad, 1], [0, 0]]))
    assert e.value.code == "INVALID_COORDINATE"


def test_out_of_range_and_unsupported_rejected():
    with pytest.raises(PlaceIdentityError):
        geometry_id({"type": "Point", "coordinates": [181, 0]})
    with pytest.raises(PlaceIdentityError):
        geometry_id({"type": "Point", "coordinates": [0, 91]})
    with pytest.raises(PlaceIdentityError):
        geometry_id({"type": "Point", "coordinates": [True, 0]})
    with pytest.raises(PlaceIdentityError) as e:
        geometry_id({"type": "LineString", "coordinates": [[0, 0], [1, 1]]})
    assert e.value.code == "UNSUPPORTED_GEOMETRY"


def test_gauge_id_geometry():
    a = geometry_id({"type": "GaugeID", "scheme": "usgs", "id": "01013500"})
    assert a == geometry_id({"type": "GaugeID", "scheme": "usgs", "id": "01013500"})
    assert a != geometry_id({"type": "GaugeID", "scheme": "usgs", "id": "01013501"})
    assert a != geometry_id({"type": "GaugeID", "scheme": "camels", "id": "01013500"})
    with pytest.raises(PlaceIdentityError):
        geometry_id({"type": "GaugeID", "scheme": "usgs", "id": ""})


def test_antimeridian_limitation():
    """A split polygon canonicalises; an unsplit crossing is flagged, not rejected."""
    west = poly([[179.0, 0.0], [180.0, 0.0], [180.0, 1.0], [179.0, 1.0], [179.0, 0.0]])
    east = poly([[-180.0, 0.0], [-179.0, 0.0], [-179.0, 1.0], [-180.0, 1.0], [-180.0, 0.0]])
    split = {"type": "MultiPolygon", "coordinates": [west["coordinates"], east["coordinates"]]}
    assert not crosses_antimeridian(split)
    geometry_id(split)
    unsplit = poly([[179.0, 0.0], [-179.0, 0.0], [-179.0, 1.0], [179.0, 1.0], [179.0, 0.0]])
    assert crosses_antimeridian(unsplit)
    geometry_id(unsplit)  # treated as planar (documented); callers must split first
    assert not crosses_antimeridian({"type": "Point", "coordinates": [0, 0]})


# ------------------------------------------------------------------ BasinRef
ANCHOR = {"kind": "gauge_index", "network": "nldi-usgs", "network_version": "unversioned", "element": "01013500"}


def _basin(**kw):
    base = dict(anchor=ANCHOR, method="nldi_gauge_basin", minted_by={"tool": "aihydro-watershed", "version": "0.0"})
    base.update(kw)
    return BasinRef(**base)


def test_basin_id_formula_and_alias_independence():
    expected = "aihydro:basin:" + digest({"schema": "aihydro.basin_anchor/1", **ANCHOR})
    assert basin_id_from_anchor(ANCHOR) == expected
    plain = _basin()
    rich = _basin(
        aliases=[PlaceAlias("usgs", "01013500", "same_as", "nldi", True)],
        geometry_digest=geometry_id(poly(EXT)), area_km2=123.4,
        outlet=OutletRef(-68.58, 47.23, aliases=[PlaceAlias("geoconnex", "x", "same_as")]),
        quality_flags=["gauge_basin_comid_fallback"],
    )
    assert plain.id == rich.id == expected
    other = _basin(anchor={**ANCHOR, "network_version": "2024-01"})
    assert other.id != expected
    other_kind = _basin(anchor={**ANCHOR, "kind": "network_element"})
    assert other_kind.id != expected


def test_basin_ref_round_trip_and_unknown_fields():
    ref = _basin(
        aliases=[PlaceAlias("usgs", "01013500", "same_as", "nldi", True, unknown={"note": 1})],
        geometry_digest=geometry_id(poly(EXT)), area_km2=5.0,
        outlet=OutletRef(-68.58, 47.23, snap=None), quality_flags=["a"],
    )
    d = ref.to_dict()
    d["future"] = {"x": 1}
    d["outlet"]["future_outlet"] = 2
    d["aliases"][0]["future_alias"] = 3
    back = BasinRef.from_dict(d)
    assert back.to_dict() == d
    assert back.aliases[0].curie() == "usgs:01013500"
    assert json.loads(json.dumps(d)) == d  # JSON-clean
    assert verify_basin_ref_dict(d)


def test_outlet_snap_and_reach_round_trip():
    o = OutletRef.from_dict({"lon": 1.5, "lat": 2.5, "aliases": [],
                             "snap": {"network": "nhdplusv2", "network_version": "2.1", "element": "123",
                                      "distance_m": 12.5, "extra": True}})
    assert o.snap.element == "123" and o.to_dict()["snap"]["extra"] is True
    r = ReachRef("nhdplusv2", "2.1", "123", aliases=[PlaceAlias("nhdplusv2", "123", "same_as")], unknown={"z": 1})
    assert ReachRef.from_dict(r.to_dict()) == r and r.to_dict()["z"] == 1


def test_verify_detects_tamper_and_never_trusts_declared_id():
    d = _basin().to_dict()
    assert verify_basin_ref_dict(d)
    t = copy.deepcopy(d)
    t["anchor"]["element"] = "01013501"
    assert not verify_basin_ref_dict(t)
    t = copy.deepcopy(d)
    t["id"] = "aihydro:basin:sha256:" + "0" * 64
    assert not verify_basin_ref_dict(t)
    t = copy.deepcopy(d)
    t["aliases"] = [{"scheme": "usgs", "id": "9", "relation": "same_as"}]  # aliases do not affect id
    assert verify_basin_ref_dict(t)
    t = copy.deepcopy(d)
    t["schema"] = "aihydro.basin_ref/2"
    assert not verify_basin_ref_dict(t)
    assert not verify_basin_ref_dict({"schema": "aihydro.basin_ref/1"})


def test_validation_errors():
    with pytest.raises(ValueError):
        PlaceAlias("usgs", "1", "equals")
    with pytest.raises(ValueError):
        PlaceAlias("us:gs", "1")
    with pytest.raises(ValueError):
        _basin(anchor={**ANCHOR, "kind": "polygon"})
    with pytest.raises(ValueError):
        _basin(anchor={**ANCHOR, "network_version": ""})
    with pytest.raises(ValueError):
        _basin(geometry_digest="abc")
    with pytest.raises(ValueError):
        OutletRef(200, 0)
    with pytest.raises(ValueError):
        OutletRef(0, float("nan"))


def test_place_is_a_run_input_role():
    ref = input_ref("basin", digest({"a": 1}), role="place")
    assert ref["role"] == "place"


# ------------------------------------------------------------ golden vectors
_VECTORS = Path(__file__).resolve().parent / "data" / "place_vectors.json"


def test_golden_vectors_are_stable():
    vectors = json.loads(_VECTORS.read_text(encoding="utf-8"))
    assert vectors["algorithm"] == "aihydro.geom/1"
    assert len(vectors["geometry"]) >= 6
    for case in vectors["geometry"]:
        payload = canonical_geometry(case["input"])
        assert payload == case["payload"], case["name"]
        assert geometry_id(case["input"]) == case["digest"], case["name"]
    for case in vectors["anchors"]:
        assert basin_id_from_anchor(case["anchor"]) == case["id"], case["name"]


def test_independent_node_crosscheck():
    """Re-derive every vector in Node (skipped when node is absent)."""
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    script = Path(__file__).resolve().parent / "data" / "place_crosscheck.js"
    r = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
