"""
Store — the persistence-agnostic interface that all blocks depend on.

Core knows nothing about HydroSession. It depends on this Protocol; HydroSession
implements it. This seam keeps aihydro-core domain-free so the substrate cannot
rot from hydrology-layer churn.

Any class that implements these methods is a valid Store — no inheritance needed
(structural subtyping via Protocol). The runtime_checkable decorator lets you use
isinstance(obj, Store) in tests, though structural checks are preferred.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ..primitives.geometry import Feature
    from ..primitives.provenance import Artifact


@runtime_checkable
class Store(Protocol):
    """
    Persistence interface for the feature registry and keyed result store.

    Result schema (two-level keyed store):
        product     — the compute product name: "twi", "cn", "signatures", ...
        feature_id  — the geometry the product was computed for
        params_key  — param_hash(compute_params) — exact param combination

    A result is uniquely addressed by (product, feature_id, params_key).
    Two features never collide. Same feature at different params never collides.
    """

    # ------------------------------------------------------------------ #
    # Feature registry                                                     #
    # ------------------------------------------------------------------ #

    def put_feature(self, feature: "Feature") -> None:
        """Register or update a Feature in the store."""
        ...

    def get_feature(self, feature_id: str) -> "Feature | None":
        """Look up a Feature by id. Returns None if not found."""
        ...

    def list_features(self) -> "list[Feature]":
        """Return all registered features (order: insertion)."""
        ...

    def get_active_feature_id(self) -> "str | None":
        """Return the id of the currently active (default) feature, or None."""
        ...

    def set_active_feature_id(self, feature_id: str) -> None:
        """Set the active (default) feature by id."""
        ...

    # ------------------------------------------------------------------ #
    # Keyed result store  (product × feature_id × params_key → result)   #
    # ------------------------------------------------------------------ #

    def put_result(
        self,
        product: str,
        feature_id: str,
        params_key: str,
        value: dict,
    ) -> None:
        """Store a computed result under the three-part key."""
        ...

    def get_result(
        self,
        product: str,
        feature_id: str,
        params_key: str,
    ) -> "dict | None":
        """
        Retrieve a result. Returns None on cache miss.

        A miss is returned for:
          - unknown product
          - unknown feature_id under that product
          - unknown params_key under that (product, feature_id)
        """
        ...

    def list_results(self, product: str) -> "dict[str, list[str]]":
        """
        Return all cached (feature_id → [params_key, ...]) entries for a product.

        Example: {"ann1": ["a3f7c9d1b2e4"], "ann2": ["a3f7c9d1b2e4", "ff01234567ab"]}
        """
        ...

    # ------------------------------------------------------------------ #
    # Provenance                                                           #
    # ------------------------------------------------------------------ #

    def add_artifact(self, art: "Artifact") -> None:
        """Record an Artifact in the store's provenance manifest."""
        ...

    def add_citations(self, keys: "list[str]") -> None:
        """Accumulate citation keys (Tier 1 data sources)."""
        ...

    # ------------------------------------------------------------------ #
    # Persistence                                                          #
    # ------------------------------------------------------------------ #

    def commit(self) -> None:
        """
        Persist state to durable storage.

        For HydroSession this is session.save(). For InMemoryStore this is a no-op.
        Blocks call commit() after every mutation so state survives MCP restarts.
        """
        ...
