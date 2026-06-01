"""
Tests for aihydro_core.primitives — hashing, geometry (Feature), provenance (Artifact).
"""
import pytest
from aihydro_core.primitives import param_hash, content_hash, Feature, Artifact


class TestHashing:
    def test_deterministic(self):
        p = {"resolution": 30, "year": 2019}
        assert param_hash(p) == param_hash(p)

    def test_order_independent(self):
        assert param_hash({"a": 1, "b": 2}) == param_hash({"b": 2, "a": 1})

    def test_different_params_differ(self):
        assert param_hash({"resolution": 30}) != param_hash({"resolution": 60})

    def test_non_serialisable_tolerant(self):
        # Should not raise
        h = param_hash({"path": object()})
        assert len(h) == 16

    def test_content_hash_same(self):
        data = {"mean": 8.2, "std": 1.4}
        assert content_hash(data) == content_hash(data)

    def test_content_hash_differs(self):
        assert content_hash({"a": 1}) != content_hash({"a": 2})

    def test_hash_is_16_chars(self):
        assert len(param_hash({"x": 1})) == 16
        assert len(content_hash({"x": 1})) == 16


class TestFeature:
    def test_roundtrip(self):
        f = Feature(
            feature_id="ann1",
            geojson={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
            name="Annotation 1",
            source="map_annotation",
        )
        d = f.to_dict()
        f2 = Feature.from_dict(d)
        assert f2.feature_id == "ann1"
        assert f2.name == "Annotation 1"
        assert f2.source == "map_annotation"

    def test_geometry_dict_unwraps_feature(self):
        geojson_feature = {
            "type": "Feature",
            "properties": {},
            "geometry": {"type": "Point", "coordinates": [0, 0]},
        }
        f = Feature(feature_id="x", geojson=geojson_feature)
        assert f.geometry_dict()["type"] == "Point"

    def test_geometry_dict_bare(self):
        bare = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [0, 0]]]}
        f = Feature(feature_id="y", geojson=bare)
        assert f.geometry_dict()["type"] == "Polygon"

    def test_created_at_set(self):
        f = Feature(feature_id="z", geojson={})
        assert f.created_at


class TestArtifact:
    def test_roundtrip(self):
        a = Artifact(
            artifact_id="twi_ann1",
            type="raster",
            source="usgs_3dep",
            params={"resolution": 30},
            param_hash="abc123",
            content_hash="def456",
            units="dimensionless",
        )
        d = a.to_dict()
        a2 = Artifact.from_dict(d)
        assert a2.artifact_id == "twi_ann1"
        assert a2.source == "usgs_3dep"
        assert a2.units == "dimensionless"
