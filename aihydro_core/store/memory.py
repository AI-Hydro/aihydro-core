"""
InMemoryStore — a fully-functional in-memory Store implementation.

Used by tests and anywhere a lightweight, non-persistent store suffices.
Implements the Store protocol exactly — no inheritance, structural subtyping.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..primitives.geometry import Feature
    from ..primitives.provenance import Artifact


class InMemoryStore:
    """
    In-memory implementation of the Store protocol.

    All state lives in plain dicts. commit() is a no-op.
    Thread-safety: not guaranteed — this is for single-threaded tests.
    """

    def __init__(self) -> None:
        self._features: dict[str, Feature] = {}
        self._active_feature_id: str | None = None
        # _results[product][feature_id][params_key] = result_dict
        self._results: dict[str, dict[str, dict[str, dict]]] = {}
        self._artifacts: list[Artifact] = []
        self._citations: set[str] = set()

    # ------------------------------------------------------------------ #
    # Feature registry                                                     #
    # ------------------------------------------------------------------ #

    def put_feature(self, feature: Feature) -> None:
        self._features[feature.feature_id] = feature

    def get_feature(self, feature_id: str) -> Feature | None:
        return self._features.get(feature_id)

    def list_features(self) -> list[Feature]:
        return list(self._features.values())

    def get_active_feature_id(self) -> str | None:
        return self._active_feature_id

    def set_active_feature_id(self, feature_id: str) -> None:
        self._active_feature_id = feature_id

    # ------------------------------------------------------------------ #
    # Keyed result store                                                   #
    # ------------------------------------------------------------------ #

    def put_result(
        self,
        product: str,
        feature_id: str,
        params_key: str,
        value: dict,
    ) -> None:
        self._results.setdefault(product, {}).setdefault(feature_id, {})[params_key] = value

    def get_result(
        self,
        product: str,
        feature_id: str,
        params_key: str,
    ) -> dict | None:
        return self._results.get(product, {}).get(feature_id, {}).get(params_key)

    def list_results(self, product: str) -> dict[str, list[str]]:
        by_feature = self._results.get(product, {})
        return {fid: list(keys.keys()) for fid, keys in by_feature.items()}

    # ------------------------------------------------------------------ #
    # Provenance                                                           #
    # ------------------------------------------------------------------ #

    def store_artifact(self, art: Artifact) -> None:
        self._artifacts.append(art)

    def add_citations(self, keys: list[str]) -> None:
        self._citations.update(keys)

    def get_citations(self) -> set[str]:
        return set(self._citations)

    def get_artifacts(self) -> list[Artifact]:
        return list(self._artifacts)

    # ------------------------------------------------------------------ #
    # Persistence                                                          #
    # ------------------------------------------------------------------ #

    def commit(self) -> None:
        """No-op for in-memory store."""
