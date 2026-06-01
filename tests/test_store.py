"""
Tests for aihydro_core.store — Store Protocol + InMemoryStore.
"""
import pytest
from aihydro_core.store import InMemoryStore, Store
from aihydro_core.primitives import Feature, Artifact


@pytest.fixture
def store():
    return InMemoryStore()


@pytest.fixture
def ann1():
    return Feature(
        feature_id="ann1",
        geojson={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
        name="Annotation 1",
        source="map_annotation",
    )


@pytest.fixture
def ann2():
    return Feature(
        feature_id="ann2",
        geojson={"type": "Polygon", "coordinates": [[[2, 2], [3, 2], [3, 3], [2, 2]]]},
        name="Annotation 2",
        source="map_annotation",
    )


class TestInMemoryStore:
    def test_implements_protocol(self, store):
        assert isinstance(store, Store)

    def test_feature_roundtrip(self, store, ann1):
        store.put_feature(ann1)
        out = store.get_feature("ann1")
        assert out is ann1

    def test_missing_feature_returns_none(self, store):
        assert store.get_feature("nonexistent") is None

    def test_list_features(self, store, ann1, ann2):
        store.put_feature(ann1)
        store.put_feature(ann2)
        ids = [f.feature_id for f in store.list_features()]
        assert "ann1" in ids
        assert "ann2" in ids

    def test_active_feature(self, store, ann1):
        assert store.get_active_feature_id() is None
        store.put_feature(ann1)
        store.set_active_feature_id("ann1")
        assert store.get_active_feature_id() == "ann1"

    def test_result_keyed_by_feature(self, store):
        """Core invariant: ann1 and ann2 results never collide."""
        result1 = {"mean_twi": 8.2, "feature_id": "ann1"}
        result2 = {"mean_twi": 6.1, "feature_id": "ann2"}
        store.put_result("twi", "ann1", "params_key_1", result1)
        store.put_result("twi", "ann2", "params_key_1", result2)

        assert store.get_result("twi", "ann1", "params_key_1") == result1
        assert store.get_result("twi", "ann2", "params_key_1") == result2
        # Cross-check: ann1's result is not accessible under ann2
        assert store.get_result("twi", "ann1", "params_key_1")["mean_twi"] == 8.2

    def test_result_miss_returns_none(self, store):
        assert store.get_result("twi", "nonexistent", "key") is None
        assert store.get_result("nonexistent_product", "ann1", "key") is None

    def test_result_keyed_by_params(self, store):
        """Same feature + different params → different cache slot."""
        r30 = {"resolution": 30, "mean": 8.2}
        r60 = {"resolution": 60, "mean": 7.9}
        store.put_result("twi", "ann1", "key_30m", r30)
        store.put_result("twi", "ann1", "key_60m", r60)
        assert store.get_result("twi", "ann1", "key_30m")["mean"] == 8.2
        assert store.get_result("twi", "ann1", "key_60m")["mean"] == 7.9

    def test_list_results(self, store):
        store.put_result("twi", "ann1", "k1", {"v": 1})
        store.put_result("twi", "ann2", "k1", {"v": 2})
        store.put_result("twi", "ann1", "k2", {"v": 3})
        listing = store.list_results("twi")
        assert "ann1" in listing
        assert set(listing["ann1"]) == {"k1", "k2"}
        assert listing["ann2"] == ["k1"]

    def test_provenance(self, store):
        art = Artifact(
            artifact_id="twi_ann1_30m",
            type="raster",
            source="usgs_3dep",
            params={"resolution": 30},
            param_hash="abc",
            content_hash="def",
        )
        store.add_artifact(art)
        store.add_citations(["usgs_3dep", "copernicus_glo30"])
        assert len(store.get_artifacts()) == 1
        assert "usgs_3dep" in store.get_citations()

    def test_commit_noop(self, store):
        store.commit()   # must not raise
