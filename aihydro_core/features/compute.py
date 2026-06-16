"""
feature_compute — the @feature_tool decorator.

Every spatial tool that is addressable by geometry composes from this block.

Usage
-----
Authors write a **pure sync kernel** that receives a bare GeoJSON geometry dict
and returns a result envelope. The decorator handles:

    resolve → cache check → compute → store → provenance → commit

Example::

    from aihydro_core.features.compute import feature_tool

    @feature_tool(product="twi", citations=["usgs_3dep", "copernicus_glo30"])
    def _twi_stats_kernel(geom: dict, *, resolution: int = 30) -> dict:
        # geom is already resolved — pure computation only.
        # (The domain kernel is imported by the *caller's* package, never here:
        #  core depends on nobody.)
        return compute_twi_stats(geom, resolution=resolution)

    # Domain-side thin wrapper (in the tools package, not core):
    store = load_store(store_id)
    result = _twi_stats_kernel(store=store, feature=feature_ref, resolution=30)

Wrapped function signature
--------------------------
    fn_wrapped(store: Store, feature: str | dict | None = None, **params) -> dict

Parameters
~~~~~~~~~~
store : Store
    A loaded Store instance (typically a HydroSession). The caller is
    responsible for loading and passing it. Core never imports HydroSession.
feature : str | dict | None
    Feature reference — resolved via FeatureRegistry. str → id/name lookup;
    dict → inline GeoJSON (registered on the fly); None → active feature.
**params
    Compute parameters forwarded to the wrapped kernel unchanged. These form
    the params_key for the three-level cache.

Result
------
The result dict from the kernel (or a cached envelope on hit).
Always includes ``feature_id`` and ``_cache_hit`` keys.

Cache key
---------
``param_hash(params)`` — deterministic SHA-256 hex of the sorted JSON params.
Same geometry + same params → hit. Different geometry → miss (different key).
"""
from __future__ import annotations

import functools
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, TypeVar

from ..primitives.hashing import param_hash, content_hash
from ..features.registry import FeatureRegistry

if TYPE_CHECKING:
    from ..store.protocol import Store

log = logging.getLogger("aihydro_core.features.compute")

F = TypeVar("F", bound=Callable[..., dict])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# @feature_tool decorator
# ---------------------------------------------------------------------------

def feature_tool(
    product: str,
    citations: list[str] | None = None,
) -> Callable[[F], "FeatureToolWrapper"]:
    """
    Decorator factory that wraps a pure sync spatial kernel.

    Parameters
    ----------
    product : str
        The result product name — e.g. "twi", "cn", "signatures".
        Used as the top-level key in the three-level result store.
    citations : list[str] | None
        Citation keys (data source identifiers) to record on every run.
        Accumulated in the store's citation set.

    Returns
    -------
    A decorator that wraps ``fn(geom: dict, **params) -> dict``
    into ``fn_wrapped(store, feature=None, **params) -> dict``.
    """
    _citations: list[str] = citations or []

    def decorator(fn: F) -> "FeatureToolWrapper":

        @functools.wraps(fn)
        def wrapper(
            store: "Store",
            feature: "str | dict | list | None" = None,
            **params: Any,
        ) -> dict:
            """
            Resolve → cache check → compute → store → provenance → commit.

            Parameters
            ----------
            store : Store
                Loaded Store instance (e.g. HydroSession).
            feature : str | dict | list | None
                Feature reference. None → active/single feature.
                **list** → batch fan-out: each element resolved independently;
                returns ``{"batch": True, "n_features": N, "results": {...}}``.
            **params
                Forwarded to the kernel; also form the cache key.
            """
            # C3: batch fan-out — feature is a list of refs
            if isinstance(feature, list):
                results: dict[str, dict] = {}
                errors: dict[str, str] = {}
                for ref in feature:
                    try:
                        r = wrapper(store, feature=ref, **params)
                        results[r.get("feature_id", str(ref))] = r
                    except Exception as exc:
                        fid = str(ref)
                        errors[fid] = str(exc)
                        log.warning(
                            "Batch feature_tool %s failed for ref=%r: %s",
                            product, ref, exc,
                        )
                return {
                    "batch": True,
                    "product": product,
                    "n_features": len(feature),
                    "n_success": len(results),
                    "n_error": len(errors),
                    "results": results,
                    **({"errors": errors} if errors else {}),
                }

            # 1. Resolve feature ref → Feature
            registry = FeatureRegistry(store)
            feat = registry.resolve(feature)

            # 2. Cache check
            key = param_hash(params) if params else param_hash({})
            cached = store.get_result(product, feat.feature_id, key)
            if cached is not None:
                log.debug(
                    "Cache hit: product=%s feature_id=%s key=%s",
                    product, feat.feature_id, key,
                )
                return {**cached, "feature_id": feat.feature_id, "_cache_hit": True}

            # 3. Compute
            log.debug(
                "Cache miss — computing: product=%s feature_id=%s key=%s",
                product, feat.feature_id, key,
            )
            raw = fn(feat.geojson, **params)

            # 4. Normalise result into {data, meta} envelope
            if isinstance(raw, dict) and "data" in raw and "meta" in raw:
                # Kernel already returned an envelope
                envelope: dict = dict(raw)
                envelope["meta"] = {
                    **raw["meta"],
                    "computed_at": raw["meta"].get("computed_at") or _now_iso(),
                    "feature_id": feat.feature_id,
                    "feature_name": feat.name,
                    "params": params,
                }
            else:
                # Kernel returned bare data dict — wrap it
                envelope = {
                    "data": raw,
                    "meta": {
                        "computed_at": _now_iso(),
                        "tool": fn.__name__,
                        "feature_id": feat.feature_id,
                        "feature_name": feat.name,
                        "params": params,
                    },
                }

            # 5. Store result
            store.put_result(product, feat.feature_id, key, envelope)

            # 6. Provenance
            if _citations:
                store.add_citations(_citations)

            try:
                from ..primitives.provenance import Artifact as _Artifact
                art = _Artifact(
                    artifact_id=f"{product}_{feat.feature_id}_{key[:8]}",
                    type="derived",
                    source=product,
                    params=params,
                    param_hash=key,
                    content_hash=content_hash(envelope.get("data", {})),
                )
                store.store_artifact(art)
            except Exception as _e:
                log.debug("Provenance artifact recording failed (non-fatal): %s", _e)

            # 7. Commit
            store.commit()

            return {**envelope, "feature_id": feat.feature_id}

        # Attach metadata so callers can introspect decoration intent
        wrapper._feature_tool_product = product          # type: ignore[attr-defined]
        wrapper._feature_tool_citations = _citations      # type: ignore[attr-defined]
        wrapper._feature_tool_inner = fn                  # type: ignore[attr-defined]

        return wrapper  # type: ignore[return-value]

    return decorator


# ---------------------------------------------------------------------------
# FeatureToolWrapper type alias (for documentation only)
# ---------------------------------------------------------------------------

class FeatureToolWrapper:
    """
    Callable returned by @feature_tool.

    Not instantiated directly — used only as a type annotation target so IDE
    tooling can show the wrapper's signature.
    """
    _feature_tool_product: str
    _feature_tool_citations: list[str]
    _feature_tool_inner: Callable[..., dict]

    def __call__(
        self,
        store: "Store",
        feature: str | dict | None = None,
        **params: Any,
    ) -> dict: ...


__all__ = ["feature_tool", "FeatureToolWrapper"]
