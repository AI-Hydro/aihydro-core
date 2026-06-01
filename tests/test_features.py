"""
Tests for aihydro_core.features — FeatureRegistry (resolve, register, list, active).
"""
import json
import pytest
from aihydro_core.features import FeatureRegistry, Feature, FeatureNotFoundError
from aihydro_core.store import InMemoryStore


POLY = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}
POLY2 = {"type": "Polygon", "coordinates": [[[2, 2], [3, 2], [3, 3], [2, 2]]]}
GEOJSON_FEATURE = {"type": "Feature", "properties": {}, "geometry": POLY}


@pytest.fixture
def store():
    return InMemoryStore()


@pytest.fixture
def registry(store):
    return FeatureRegistry(store)


class TestRegistration:
    def test_register_bare_geometry(self, registry):
        f = registry.register(POLY, name="Basin A", source="test")
        assert f.name == "Basin A"
        assert f.source == "test"
        assert f.geojson["type"] == "Polygon"

    def test_register_geojson_feature_unwraps(self, registry):
        f = registry.register(GEOJSON_FEATURE, name="Basin B")
        # stored as bare geometry, not wrapped Feature
        assert f.geojson["type"] == "Polygon"

    def test_register_json_string(self, registry):
        f = registry.register(json.dumps(POLY), name="Basin C")
        assert f.geojson["type"] == "Polygon"

    def test_explicit_feature_id(self, registry):
        f = registry.register(POLY, feature_id="ann1")
        assert f.feature_id == "ann1"

    def test_name_slugified_as_id(self, registry):
        f = registry.register(POLY, name="Upper Basin #3")
        assert f.feature_id == "upper-basin-3"

    def test_set_active_on_register(self, registry, store):
        registry.register(POLY, feature_id="ann1", set_active=True)
        assert store.get_active_feature_id() == "ann1"

    def test_invalid_json_string_raises(self, registry):
        with pytest.raises(ValueError, match="not valid JSON"):
            registry.register("not json at all", name="Bad")


class TestResolution:
    def test_resolve_by_id(self, registry):
        registry.register(POLY, feature_id="ann1")
        f = registry.resolve("ann1")
        assert f.feature_id == "ann1"

    def test_resolve_by_name(self, registry):
        registry.register(POLY, name="Annotation 2", feature_id="ann2")
        f = registry.resolve("Annotation 2")
        assert f.feature_id == "ann2"

    def test_resolve_on_the_fly_dict(self, registry):
        f = registry.resolve(POLY)
        assert f.geojson["type"] == "Polygon"
        assert f.source == "on-the-fly"

    def test_resolve_on_the_fly_geojson_string(self, registry):
        f = registry.resolve(json.dumps(POLY))
        assert f.geojson["type"] == "Polygon"

    def test_resolve_none_uses_active(self, registry, store):
        registry.register(POLY, feature_id="ann1", set_active=True)
        f = registry.resolve(None)
        assert f.feature_id == "ann1"

    def test_resolve_none_single_feature_fallback(self, registry):
        registry.register(POLY, feature_id="solo")
        f = registry.resolve(None)
        assert f.feature_id == "solo"

    def test_resolve_none_no_active_no_features_raises(self, registry):
        with pytest.raises(FeatureNotFoundError):
            registry.resolve(None)

    def test_resolve_unknown_raises_with_available(self, registry):
        registry.register(POLY, feature_id="ann1")
        with pytest.raises(FeatureNotFoundError) as exc_info:
            registry.resolve("nonexistent")
        assert "ann1" in exc_info.value.message

    def test_resolve_many(self, registry):
        registry.register(POLY, feature_id="ann1")
        registry.register(POLY2, feature_id="ann2")
        features = registry.resolve_many(["ann1", "ann2"])
        assert [f.feature_id for f in features] == ["ann1", "ann2"]


class TestActiveCases:
    def test_set_active(self, registry, store):
        registry.register(POLY, feature_id="ann1")
        registry.set_active("ann1")
        assert store.get_active_feature_id() == "ann1"

    def test_set_active_unknown_raises(self, registry):
        with pytest.raises(FeatureNotFoundError):
            registry.set_active("nonexistent")

    def test_list(self, registry):
        registry.register(POLY, feature_id="ann1")
        registry.register(POLY2, feature_id="ann2")
        ids = [f.feature_id for f in registry.list()]
        assert set(ids) == {"ann1", "ann2"}


class TestCacheNonCollision:
    """Verifies the core invariant: two features' results never collide in the store."""

    def test_two_features_same_product(self, store, registry):
        """ann1 and ann2 results for 'twi' are independent — the trigger scenario."""
        registry.register(POLY, feature_id="ann1")
        registry.register(POLY2, feature_id="ann2")

        # Simulate what @feature_tool will do:
        store.put_result("twi", "ann1", "key_30m", {"mean": 8.2})
        store.put_result("twi", "ann2", "key_30m", {"mean": 6.1})

        # No clear_session needed. Both coexist.
        assert store.get_result("twi", "ann1", "key_30m")["mean"] == 8.2
        assert store.get_result("twi", "ann2", "key_30m")["mean"] == 6.1

        # Listing shows both
        listing = store.list_results("twi")
        assert set(listing.keys()) == {"ann1", "ann2"}
