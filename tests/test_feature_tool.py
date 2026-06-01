"""
Tests for aihydro_core.features.compute — @feature_tool decorator.

Verifies the resolve → cache check → compute → store → provenance → commit
pipeline, using InMemoryStore so no HydroSession/disk I/O is needed.
"""
from __future__ import annotations

import pytest
from aihydro_core.features.compute import feature_tool
from aihydro_core.store import InMemoryStore
from aihydro_core.primitives import Feature


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store():
    return InMemoryStore()


@pytest.fixture
def ann1_feature():
    return Feature(
        feature_id="ann1",
        geojson={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
        name="Annotation 1",
        source="map_annotation",
    )


@pytest.fixture
def ann2_feature():
    return Feature(
        feature_id="ann2",
        geojson={"type": "Polygon", "coordinates": [[[2, 2], [3, 2], [3, 3], [2, 2]]]},
        name="Annotation 2",
        source="map_annotation",
    )


def _make_store_with_features(*feats: Feature) -> InMemoryStore:
    """Return an InMemoryStore with pre-registered features."""
    s = InMemoryStore()
    for f in feats:
        s.put_feature(f)
    if feats:
        s.set_active_feature_id(feats[0].feature_id)
    return s


# ---------------------------------------------------------------------------
# Kernel stubs
# ---------------------------------------------------------------------------

def _identity_kernel(geom: dict, *, value: float = 1.0) -> dict:
    """Trivial kernel: returns the value passed as param. Does not use geom."""
    return {"data": {"value": value}, "meta": {"tool": "_identity_kernel"}}


def _geom_aware_kernel(geom: dict, *, resolution: int = 30) -> dict:
    """Kernel that encodes the geometry hash so we can verify distinct geoms."""
    import hashlib, json
    geom_hash = hashlib.md5(json.dumps(geom, sort_keys=True).encode()).hexdigest()[:8]
    return {"data": {"geom_hash": geom_hash, "resolution": resolution}, "meta": {}}


# ---------------------------------------------------------------------------
# 1. Basic decoration
# ---------------------------------------------------------------------------

class TestFeatureToolDecoration:
    def test_decorated_function_is_callable(self):
        wrapped = feature_tool(product="test")(_identity_kernel)
        assert callable(wrapped)

    def test_product_metadata_attached(self):
        wrapped = feature_tool(product="test", citations=["src_a"])(_identity_kernel)
        assert wrapped._feature_tool_product == "test"
        assert "src_a" in wrapped._feature_tool_citations

    def test_inner_function_accessible(self):
        wrapped = feature_tool(product="test")(_identity_kernel)
        assert wrapped._feature_tool_inner is _identity_kernel


# ---------------------------------------------------------------------------
# 2. Resolve → compute → store
# ---------------------------------------------------------------------------

class TestFeatureToolResolveAndStore:
    def test_compute_and_store_result(self, ann1_feature):
        s = _make_store_with_features(ann1_feature)
        wrapped = feature_tool(product="demo")(_identity_kernel)
        result = wrapped(store=s, feature="ann1", value=7.0)
        assert result["data"]["value"] == 7.0
        assert result["feature_id"] == "ann1"
        assert result.get("_cache_hit") is not True

    def test_result_stored_in_three_level_slot(self, ann1_feature):
        s = _make_store_with_features(ann1_feature)
        wrapped = feature_tool(product="demo")(_identity_kernel)
        wrapped(store=s, feature="ann1", value=5.0)
        # Should be retrievable via get_result
        stored = s.get_result("demo", "ann1", s.list_results("demo")["ann1"][0])
        assert stored is not None
        assert stored["data"]["value"] == 5.0

    def test_none_feature_uses_active(self, ann1_feature):
        s = _make_store_with_features(ann1_feature)
        wrapped = feature_tool(product="demo")(_identity_kernel)
        result = wrapped(store=s, feature=None, value=3.0)
        assert result["feature_id"] == "ann1"  # active feature

    def test_dict_feature_registers_on_fly(self):
        s = InMemoryStore()
        inline_geojson = {"type": "Polygon", "coordinates": [[[5, 5], [6, 5], [6, 6], [5, 5]]]}
        wrapped = feature_tool(product="demo")(_identity_kernel)
        result = wrapped(store=s, feature=inline_geojson, value=9.0)
        # Feature was registered on the fly
        assert result["feature_id"] is not None
        assert len(s.list_features()) == 1


# ---------------------------------------------------------------------------
# 3. Cache — the core invariant
# ---------------------------------------------------------------------------

class TestFeatureToolCache:
    def test_cache_hit_on_second_call(self, ann1_feature):
        """Same feature + same params → cache hit on second call."""
        call_count = [0]

        def counting_kernel(geom, *, value=1.0):
            call_count[0] += 1
            return {"data": {"value": value}, "meta": {}}

        s = _make_store_with_features(ann1_feature)
        wrapped = feature_tool(product="demo")(counting_kernel)

        wrapped(store=s, feature="ann1", value=2.0)
        assert call_count[0] == 1

        result2 = wrapped(store=s, feature="ann1", value=2.0)
        assert call_count[0] == 1  # kernel not called again
        assert result2.get("_cache_hit") is True

    def test_different_feature_different_cache_slot(self, ann1_feature, ann2_feature):
        """ann1 and ann2 are independent cache slots — never collide."""
        call_count = [0]

        def counting_kernel(geom, *, resolution=30):
            call_count[0] += 1
            return {"data": {"geom_hash": id(geom)}, "meta": {}}

        s = _make_store_with_features(ann1_feature, ann2_feature)
        wrapped = feature_tool(product="twi")(counting_kernel)

        r1 = wrapped(store=s, feature="ann1", resolution=30)
        assert call_count[0] == 1
        assert r1.get("_cache_hit") is not True

        r2 = wrapped(store=s, feature="ann2", resolution=30)
        assert call_count[0] == 2  # kernel called again for ann2
        assert r2.get("_cache_hit") is not True

        # Re-read ann1 — must be a hit, not ann2's value
        r1_again = wrapped(store=s, feature="ann1", resolution=30)
        assert call_count[0] == 2
        assert r1_again.get("_cache_hit") is True

    def test_different_params_different_cache_slot(self, ann1_feature):
        """Same feature, different params → different cache slot → two separate results."""
        s = _make_store_with_features(ann1_feature)
        wrapped = feature_tool(product="twi")(_geom_aware_kernel)

        r30 = wrapped(store=s, feature="ann1", resolution=30)
        r60 = wrapped(store=s, feature="ann1", resolution=60)

        assert r30["data"]["resolution"] == 30
        assert r60["data"]["resolution"] == 60
        # Both stored independently
        listing = s.list_results("twi")
        assert len(listing["ann1"]) == 2

    def test_trigger_scenario_no_clear_needed(self, ann1_feature, ann2_feature):
        """
        Trigger scenario: TWI for ann1 then ann2, no store wipe.
        This is the core invariant that justified the entire Feature Store build.
        """
        s = _make_store_with_features(ann1_feature, ann2_feature)
        wrapped = feature_tool(product="twi")(_geom_aware_kernel)

        # Step 1: compute TWI for ann1
        r_ann1 = wrapped(store=s, feature="ann1", resolution=30)
        ann1_hash = r_ann1["data"]["geom_hash"]

        # Step 2: compute TWI for ann2 — NO store.clear() or reset
        r_ann2 = wrapped(store=s, feature="ann2", resolution=30)
        ann2_hash = r_ann2["data"]["geom_hash"]

        # Geometry hashes are different (different geoms → different input → different hash)
        assert ann1_hash != ann2_hash

        # Step 3: re-read ann1 — must still be the original value, not ann2's
        r_ann1_again = wrapped(store=s, feature="ann1", resolution=30)
        assert r_ann1_again.get("_cache_hit") is True
        assert r_ann1_again["data"]["geom_hash"] == ann1_hash


# ---------------------------------------------------------------------------
# 4. Provenance
# ---------------------------------------------------------------------------

class TestFeatureToolProvenance:
    def test_citations_accumulated(self, ann1_feature):
        s = _make_store_with_features(ann1_feature)
        wrapped = feature_tool(product="twi", citations=["usgs_3dep", "copernicus"])(_identity_kernel)
        wrapped(store=s, feature="ann1", value=1.0)
        cites = s.get_citations()
        assert "usgs_3dep" in cites
        assert "copernicus" in cites

    def test_artifact_recorded(self, ann1_feature):
        s = _make_store_with_features(ann1_feature)
        wrapped = feature_tool(product="twi", citations=[])(_identity_kernel)
        wrapped(store=s, feature="ann1", value=1.0)
        artifacts = s.get_artifacts()
        assert len(artifacts) == 1
        assert artifacts[0].source == "twi"

    def test_no_duplicate_artifact_on_cache_hit(self, ann1_feature):
        """Cache hits must not record a second artifact."""
        s = _make_store_with_features(ann1_feature)
        wrapped = feature_tool(product="twi")(_identity_kernel)
        wrapped(store=s, feature="ann1", value=1.0)
        wrapped(store=s, feature="ann1", value=1.0)  # cache hit
        assert len(s.get_artifacts()) == 1

    def test_commit_called_after_compute(self, ann1_feature, monkeypatch):
        """commit() must be called exactly once per cache miss."""
        commit_calls = [0]
        s = _make_store_with_features(ann1_feature)
        _real_commit = s.commit
        monkeypatch.setattr(s, "commit", lambda: (commit_calls.__setitem__(0, commit_calls[0] + 1), _real_commit())[-1])

        wrapped = feature_tool(product="twi")(_identity_kernel)
        wrapped(store=s, feature="ann1", value=1.0)
        assert commit_calls[0] == 1

        # Cache hit: commit must NOT be called again
        commit_calls[0] = 0
        wrapped(store=s, feature="ann1", value=1.0)
        assert commit_calls[0] == 0


# ---------------------------------------------------------------------------
# 5. Bare-data kernel (kernel returns bare dict, not envelope)
# ---------------------------------------------------------------------------

class TestBareDataKernel:
    def test_bare_dict_wrapped_into_envelope(self, ann1_feature):
        """Kernels that return a bare dict (not {data, meta}) must be wrapped."""

        def bare_kernel(geom, *, resolution=30):
            return {"mean_twi": 8.2, "resolution": resolution}

        s = _make_store_with_features(ann1_feature)
        wrapped = feature_tool(product="twi")(bare_kernel)
        result = wrapped(store=s, feature="ann1", resolution=30)
        # The result stored should be wrapped into {data: ..., meta: ...}
        stored = s.get_result("twi", "ann1", s.list_results("twi")["ann1"][0])
        assert "data" in stored
        assert stored["data"]["mean_twi"] == 8.2


# ---------------------------------------------------------------------------
# C3 batch fan-out tests
# ---------------------------------------------------------------------------

class TestFeatureToolBatch:
    """@feature_tool with feature=[list] → batch fan-out."""

    def _make_store_with_features(self):
        from aihydro_core.store.memory import InMemoryStore
        from aihydro_core.primitives import Feature
        store = InMemoryStore()
        for fid, name in [("ann1", "Ann 1"), ("ann2", "Ann 2"), ("ann3", "Ann 3")]:
            store.put_feature(Feature(
                feature_id=fid,
                geojson={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
                name=name,
            ))
        store.set_active_feature_id("ann1")
        return store

    def test_batch_returns_batch_flag(self):
        from aihydro_core.features.compute import feature_tool

        @feature_tool(product="test_batch")
        def _kernel(geom, **p):
            return {"value": 42}

        store = self._make_store_with_features()
        result = _kernel(store, feature=["ann1", "ann2"])
        assert result["batch"] is True
        assert result["n_features"] == 2
        assert result["n_success"] == 2

    def test_batch_results_keyed_by_feature_id(self):
        from aihydro_core.features.compute import feature_tool

        call_count = [0]

        @feature_tool(product="test_keyed")
        def _kernel(geom, **p):
            call_count[0] += 1
            return {"call": call_count[0]}

        store = self._make_store_with_features()
        result = _kernel(store, feature=["ann1", "ann2", "ann3"])
        assert set(result["results"].keys()) == {"ann1", "ann2", "ann3"}
        assert call_count[0] == 3   # kernel called once per feature

    def test_batch_each_result_cached_independently(self):
        from aihydro_core.features.compute import feature_tool
        from aihydro_core.primitives.hashing import param_hash

        @feature_tool(product="test_cached_batch")
        def _kernel(geom, **p):
            return {"ok": True}

        store = self._make_store_with_features()
        _kernel(store, feature=["ann1", "ann2"])

        key = param_hash({})
        r1 = store.get_result("test_cached_batch", "ann1", key)
        r2 = store.get_result("test_cached_batch", "ann2", key)
        assert r1 is not None
        assert r2 is not None
        assert r1 is not r2   # separate objects

    def test_batch_partial_error_isolates(self):
        from aihydro_core.features.compute import feature_tool

        @feature_tool(product="test_partial_err")
        def _kernel(geom, **p):
            if p.get("fail"):
                raise ValueError("forced error")
            return {"ok": True}

        store = self._make_store_with_features()
        # ann2 will fail because we can't pass feature-specific params via the
        # decorator — so we test via a side-effect flag (mock the registry)
        # Simpler: just pass an unknown feature ref to trigger FeatureNotFoundError
        result = _kernel(store, feature=["ann1", "NONEXISTENT_FEATURE"])
        assert result["n_success"] == 1
        assert result["n_error"] == 1
        assert "ann1" in result["results"]
        assert "errors" in result

    def test_batch_cache_hits_respected(self):
        from aihydro_core.features.compute import feature_tool
        from aihydro_core.primitives.hashing import param_hash

        calls = [0]

        @feature_tool(product="test_cache_hit_batch")
        def _kernel(geom, **p):
            calls[0] += 1
            return {"v": calls[0]}

        store = self._make_store_with_features()
        # First run — 2 computes
        _kernel(store, feature=["ann1", "ann2"])
        assert calls[0] == 2

        # Second run — both should cache hit, kernel not called
        result = _kernel(store, feature=["ann1", "ann2"])
        assert calls[0] == 2   # no new calls
        assert all(r.get("_cache_hit") for r in result["results"].values())
