"""
Machine-readable scope for uncertainty estimates (Science Wave 3, critique M6).

A confidence interval is only meaningful relative to what was resampled, what
was assumed fixed, and what was never in play.  ``make_scope`` builds that
declaration as plain data so a claim gate can refuse "differs from X" claims
whenever the quantity that would explain the difference is in ``excludes``.

Stdlib-only.  Shape::

    {"varies": [...], "assumes": [...], "excludes": [...]}
"""
from __future__ import annotations

from typing import Iterable

#: Terms the grouped (water-year) bootstrap resamples / assumes / leaves out.
VARIES_WATER_YEAR_SAMPLE = "water_year_sample"
ASSUMES_EXCHANGEABLE_YEARS = "exchangeable_years"
ASSUMES_FIXED_PERIOD = "fixed_period"

#: Default exclusions for a sampling-only interval (critique M6).
SAMPLING_ONLY_EXCLUDES: tuple[str, ...] = (
    "forcing_product",
    "rating_measurement",
    "catchment_area",
    "method_definition",
    "interannual_persistence",
    "nonstationarity",
)

_KEYS = ("varies", "assumes", "excludes")


def make_scope(
    varies: Iterable[str],
    assumes: Iterable[str] = (),
    excludes: Iterable[str] = (),
) -> dict[str, list[str]]:
    """Return a ``{"varies","assumes","excludes"}`` dict of de-duplicated, ordered lists."""
    def _clean(items: Iterable[str]) -> list[str]:
        out: list[str] = []
        for it in items:
            if not isinstance(it, str) or not it:
                raise ValueError(f"scope terms must be non-empty strings, got {it!r}")
            if it not in out:
                out.append(it)
        return out

    scope = {"varies": _clean(varies), "assumes": _clean(assumes), "excludes": _clean(excludes)}
    overlap = set(scope["varies"]) & set(scope["excludes"])
    if overlap:
        raise ValueError(f"scope terms cannot be both varied and excluded: {sorted(overlap)}")
    return scope


def water_year_sampling_scope() -> dict[str, list[str]]:
    """Scope of an inter-annual (water-year grouped) sampling-only interval."""
    return make_scope(
        varies=[VARIES_WATER_YEAR_SAMPLE],
        assumes=[ASSUMES_EXCHANGEABLE_YEARS, ASSUMES_FIXED_PERIOD],
        excludes=SAMPLING_ONLY_EXCLUDES,
    )


def scope_excludes(scope: "dict | None", term: str) -> bool:
    """
    Conservative: ``term`` counts as excluded unless it is explicitly in
    ``scope["varies"]``.  A malformed or absent scope excludes everything.
    Membership is exact list membership (no substring matching); ``varies`` and
    ``excludes`` must be lists/tuples of strings or the scope is treated as malformed.
    """
    if not isinstance(scope, dict):
        return True
    for key in ("varies", "excludes"):
        val = scope.get(key)
        if not isinstance(val, (list, tuple)) or not all(isinstance(x, str) for x in val):
            return True
    return term not in scope["varies"]
