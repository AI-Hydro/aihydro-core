"""
Concrete bootstrap uncertainty implementations — requires numpy ([science] extra).

Kept separate from uncertainty.py so the protocol definitions stay stdlib-only.
Import via: from aihydro_core.science.uncertainty import bootstrap_ci, ...
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Mapping, TypedDict

import numpy as np

from .scope import water_year_sampling_scope

log = logging.getLogger(__name__)


class UncertaintyResult(TypedDict):
    """
    Standard uncertainty container returned by all CI functions.

    Satisfies the UncertaintyEstimate contract (superset of required keys).
    """
    value: float
    ci_low: float
    ci_high: float
    method: str
    n: int
    ci_level: float


def _quantile_bounds(samples: list[float], ci: float) -> tuple[float, float]:
    lo = (1.0 - ci) / 2.0
    hi = 1.0 - lo
    arr = np.asarray(samples, dtype=float)
    return float(np.quantile(arr, lo)), float(np.quantile(arr, hi))


def bootstrap_ci(
    fn: Callable[[np.ndarray], float],
    data: np.ndarray,
    *,
    n: int = 500,
    ci: float = 0.90,
    random_state: int = 0,
) -> UncertaintyResult:
    """
    Estimate a confidence interval for fn(data) by IID bootstrap resampling.

    Parameters
    ----------
    fn          : scalar-valued function of a 1-D numpy array.
    data        : 1-D array-like; NaN values are stripped before resampling.
    n           : number of bootstrap replicates (default 500).
    ci          : confidence level (default 0.90 → 5th/95th percentiles).
    random_state: RNG seed for reproducibility.

    Returns
    -------
    UncertaintyResult with method='bootstrap_iid'.
    """
    arr = np.asarray(data, dtype=float)
    arr = arr[~np.isnan(arr)]
    size = arr.size
    if size < 5:
        raise ValueError(
            f"bootstrap_ci needs ≥5 valid data points, got {size}. "
            "Increase the data length or reduce the required minimum."
        )

    point = float(fn(arr))

    rng = np.random.default_rng(random_state)
    samples: list[float] = []
    for _ in range(n):
        resample = rng.choice(arr, size=size, replace=True)
        try:
            samples.append(float(fn(resample)))
        except Exception:
            continue

    if len(samples) < 10:
        log.warning(
            "bootstrap_ci: only %d of %d replicates succeeded; CI may be unreliable.",
            len(samples), n,
        )
        return UncertaintyResult(
            value=point, ci_low=float("nan"), ci_high=float("nan"),
            method="bootstrap_iid", n=size, ci_level=ci,
        )

    lo, hi = _quantile_bounds(samples, ci)
    return UncertaintyResult(value=point, ci_low=lo, ci_high=hi,
                              method="bootstrap_iid", n=size, ci_level=ci)


def _default_block_size(size: int) -> int:
    """
    Default moving-block length: ``max(5, round(n^(1/3)))``.

    This is the standard cube-root growth rate for block length in a moving-
    block bootstrap of dependent data (Hall, Horowitz & Jing 1995; see also
    Politis & White 2004 for the more elaborate "optimal" block-length
    estimators this codebase does NOT implement — n^(1/3) is the simple,
    data-independent heuristic, not a per-series-optimized one). It grows
    slowly with sample size so blocks stay short relative to the series
    (preserving bootstrap variability) while still being long enough to
    capture short-range autocorrelation in daily streamflow/precipitation.

    Known limitation: this heuristic does not adapt to the ACTUAL
    autocorrelation structure of a given series — a basin with strong
    multi-week persistence (e.g. snowmelt-dominated) may need a longer block
    than a flashy basin gets from the same n. If block-length sensitivity
    becomes a documented reviewer concern, replace this with a per-series
    estimator (e.g. Politis & White's automatic block-length selection)
    rather than adjusting this constant by hand.
    """
    return max(5, int(round(size ** (1.0 / 3.0))))


def block_bootstrap_ci(
    fn: Callable[[np.ndarray], float],
    data: np.ndarray,
    *,
    block_size: int | None = None,
    n: int = 500,
    ci: float = 0.90,
    random_state: int = 0,
) -> UncertaintyResult:
    """
    Estimate a CI for fn(data) using a moving-block bootstrap.

    Suitable for streamflow or precipitation series with temporal
    autocorrelation, where IID resampling under-covers the true interval.
    See _default_block_size() for the block-length rule and its citation.

    IMPORTANT — what this CI does and does not capture: block bootstrap
    resampling estimates SAMPLING uncertainty (how much the point estimate
    would vary across different realizations of the same underlying
    process). It does NOT capture model-structural error — e.g. for a
    hydrology signature computed from modelled (not observed) streamflow,
    this CI can look precise while the underlying GEOGLOWS/reanalysis
    discharge itself is systematically biased relative to the true
    catchment. A tight CI on a modelled-streamflow metric is not evidence
    of accuracy; see the "nominal_nse_range" quality flag on hydrology
    AttrProvenance (aihydro-lsh) for the closest available proxy of that
    structural uncertainty, and _modelled_streamflow_warning() in
    aihydro_lsh/contracts.py for the caveat this drives.

    Parameters
    ----------
    fn          : scalar-valued function of a 1-D numpy array.
    data        : 1-D array-like; NaN values are stripped before resampling.
    block_size  : length of each block (default: see _default_block_size()).
    n           : number of bootstrap replicates (default 500).
    ci          : confidence level (default 0.90).
    random_state: RNG seed.

    Returns
    -------
    UncertaintyResult with method='bootstrap_block'.
    """
    arr = np.asarray(data, dtype=float)
    arr = arr[~np.isnan(arr)]
    size = arr.size
    if size < 10:
        raise ValueError(
            f"block_bootstrap_ci needs ≥10 valid data points, got {size}."
        )

    bs = block_size
    if bs is None:
        bs = _default_block_size(size)
    bs = int(max(1, min(bs, size)))

    point = float(fn(arr))

    rng = np.random.default_rng(random_state)
    n_blocks = int(np.ceil(size / bs))
    max_start = size

    samples: list[float] = []
    for _ in range(n):
        starts = rng.integers(0, max_start, size=n_blocks)
        parts = []
        for s in starts:
            end = s + bs
            if end <= size:
                parts.append(arr[s:end])
            else:
                parts.append(np.concatenate([arr[s:], arr[: end - size]]))
        resample = np.concatenate(parts)[:size]
        try:
            samples.append(float(fn(resample)))
        except Exception:
            continue

    if len(samples) < 10:
        log.warning(
            "block_bootstrap_ci: only %d of %d replicates succeeded; CI may be unreliable.",
            len(samples), n,
        )
        return UncertaintyResult(
            value=point, ci_low=float("nan"), ci_high=float("nan"),
            method="bootstrap_block", n=size, ci_level=ci,
        )

    lo, hi = _quantile_bounds(samples, ci)
    return UncertaintyResult(value=point, ci_low=lo, ci_high=hi,
                              method="bootstrap_block", n=size, ci_level=ci)


def bootstrap_dict(
    fns: dict[str, Callable[[np.ndarray], float]],
    data: np.ndarray,
    *,
    use_block: bool = False,
    block_size: int | None = None,
    n: int = 500,
    ci: float = 0.90,
    random_state: int = 0,
) -> dict[str, UncertaintyResult]:
    """
    Run bootstrap CI for multiple metrics over the same data in one pass.

    Parameters
    ----------
    fns        : mapping of metric_name → scalar fn(array).
    data       : shared data array.
    use_block  : use block bootstrap instead of IID (for autocorrelated data).
                 See _default_block_size() for the default block-length rule.
    block_size : only used when use_block=True.

    Returns
    -------
    dict[metric_name, UncertaintyResult]

    Note: these CIs capture sampling uncertainty only, not model-structural
    error — see block_bootstrap_ci()'s docstring for why a tight CI on a
    modelled-streamflow-derived metric is not evidence of accuracy.
    """
    arr = np.asarray(data, dtype=float)
    arr = arr[~np.isnan(arr)]
    size = arr.size

    if size < (10 if use_block else 5):
        raise ValueError(
            f"bootstrap_dict: need ≥{'10' if use_block else '5'} points, got {size}."
        )

    bs = block_size
    if use_block and bs is None:
        bs = _default_block_size(size)

    rng = np.random.default_rng(random_state)
    n_blocks = int(np.ceil(size / (bs or 1))) if use_block else None
    point_ests: dict[str, float] = {}
    boot_samples: dict[str, list[float]] = {k: [] for k in fns}

    for k, fn in fns.items():
        try:
            point_ests[k] = float(fn(arr))
        except Exception:
            point_ests[k] = float("nan")

    for _ in range(n):
        if use_block:
            starts = rng.integers(0, size, size=n_blocks)
            parts = []
            for s in starts:
                end = s + bs
                if end <= size:
                    parts.append(arr[s:end])
                else:
                    parts.append(np.concatenate([arr[s:], arr[: end - size]]))
            resample = np.concatenate(parts)[:size]
        else:
            resample = rng.choice(arr, size=size, replace=True)

        for k, fn in fns.items():
            try:
                boot_samples[k].append(float(fn(resample)))
            except Exception:
                continue

    method = "bootstrap_block" if use_block else "bootstrap_iid"
    results: dict[str, UncertaintyResult] = {}
    for k in fns:
        samps = boot_samples[k]
        if len(samps) >= 10:
            lo, hi = _quantile_bounds(samps, ci)
        else:
            lo, hi = float("nan"), float("nan")
        results[k] = UncertaintyResult(
            value=point_ests.get(k, float("nan")),
            ci_low=lo, ci_high=hi,
            method=method, n=size, ci_level=ci,
        )
    return results


# ---------------------------------------------------------------------------
# Water-year grouping + grouped (cluster) bootstrap — Science Wave 3, PR-1
# ---------------------------------------------------------------------------

def water_year(dates: Any) -> np.ndarray:
    """
    USGS water year of each date: Oct 1 starts a water year, labelled by the
    calendar year in which it ends (2000-10-01 .. 2001-09-30 -> 2001).

    ``dates`` may be anything ``numpy.asarray(..., dtype="datetime64[D]")``
    accepts (datetime64 arrays, pandas DatetimeIndex/Series, ISO strings,
    ``datetime.date`` objects).  Returns an int array of the same length.
    NaT is not supported (raises ValueError).
    """
    d = np.asarray(dates).astype("datetime64[D]")
    if np.isnat(d).any():
        raise ValueError("water_year: dates contain NaT")
    months = d.astype("datetime64[M]")
    years = months.astype("datetime64[Y]").astype(int) + 1970
    month = (months.astype(int) % 12) + 1
    return np.where(month >= 10, years + 1, years).astype(int)


class GroupedBootstrapResult(UncertaintyResult, total=False):
    """UncertaintyResult plus grouped-bootstrap provenance (all keys always set)."""
    n_groups: int
    group: str
    B: int
    B_valid: int
    low_n: bool
    scope: dict


#: 10-19 groups is permitted but flagged ``low_n`` (percentile CI is unstable).
LOW_N_GROUPS = 20


def grouped_bootstrap(
    fns: Mapping[str, Callable[[np.ndarray], float]],
    n_items: int,
    groups: Any,
    *,
    n: int = 2000,
    ci: float = 0.90,
    random_state: int = 0,
    min_groups: int = 10,
    group_name: str = "water_year",
) -> dict[str, GroupedBootstrapResult]:
    """
    Percentile-interval bootstrap that resamples whole groups (e.g. water
    years) with replacement.

    Each ``fn`` receives a 1-D integer array of item indices — the
    concatenation of every item index in the resampled groups (a group drawn
    twice contributes its indices twice, groups are never split).  The caller
    closes over its own aligned arrays and indexes them, so paired statistics
    (e.g. sum(q[idx]) / sum(p[idx])) stay paired.  The point estimate is
    ``fn(arange(n_items))`` on the same item set.

    Parameters
    ----------
    fns          : metric name -> fn(index_array) -> float.
    n_items      : length of the aligned arrays the fns index into.
    groups       : length-``n_items`` group label per item (e.g. ``water_year(dates)``).
    n            : bootstrap replicates (default 2000; 500 leaves ~25 draws per
                   tail for a 90% interval, which is unstable).
    min_groups   : refuse (ValueError) below this many distinct groups.
                   Between ``min_groups`` and 19 groups the result is flagged
                   ``low_n=True``.

    Scope: sampling uncertainty of the group draw only.  Within-group
    dependence (seasonality, intra-year persistence) is preserved; **between-
    group persistence is NOT captured** (groups are treated as exchangeable) —
    see ``annual_lag1_autocorrelation``.  The returned ``scope`` says so.
    """
    if n_items < 1:
        raise ValueError("grouped_bootstrap: n_items must be >= 1")
    g = np.asarray(groups)
    if g.shape != (n_items,):
        raise ValueError(
            f"grouped_bootstrap: groups must have shape ({n_items},), got {g.shape}"
        )
    labels, inverse = np.unique(g, return_inverse=True)
    n_groups = int(labels.size)
    if n_groups < min_groups:
        raise ValueError(
            f"grouped_bootstrap needs >={min_groups} groups ({group_name}), got {n_groups}. "
            "Refusing to report an interval from too few groups."
        )
    members = [np.flatnonzero(inverse == k) for k in range(n_groups)]

    all_idx = np.arange(n_items)
    point: dict[str, float] = {}
    for k, fn in fns.items():
        try:
            point[k] = float(fn(all_idx))
        except Exception:
            point[k] = float("nan")

    rng = np.random.default_rng(random_state)
    boot: dict[str, list[float]] = {k: [] for k in fns}
    for _ in range(n):
        draw = rng.integers(0, n_groups, size=n_groups)
        idx = np.concatenate([members[j] for j in draw])
        for k, fn in fns.items():
            try:
                v = float(fn(idx))
            except Exception:
                continue
            if np.isfinite(v):
                boot[k].append(v)

    low_n = n_groups < LOW_N_GROUPS
    out: dict[str, GroupedBootstrapResult] = {}
    for k in fns:
        samps = boot[k]
        if len(samps) >= 10:
            lo, hi = _quantile_bounds(samps, ci)
        else:
            lo, hi = float("nan"), float("nan")
        out[k] = GroupedBootstrapResult(
            value=point[k], ci_low=lo, ci_high=hi,
            method="bootstrap_group", n=n_items, ci_level=ci,
            n_groups=n_groups, group=group_name, B=int(n), B_valid=len(samps),
            low_n=low_n, scope=water_year_sampling_scope(),
        )
    return out


def annual_lag1_autocorrelation(
    values: Any,
    groups: Any = None,
    *,
    high_threshold: float = 0.3,
) -> dict[str, Any]:
    """
    Lag-1 (Pearson) autocorrelation of an annual series, to flag the between-
    year persistence that ``grouped_bootstrap`` does not capture.

    ``values`` is either already one value per year (``groups=None``) or an
    item-level series aggregated by group mean (groups in sorted label order).
    ``high_threshold`` is a labelled engineering threshold, not a test.

    Returns ``{"r1", "n_years", "high", "threshold"}``; ``r1`` is NaN (and
    ``high`` False) when fewer than 4 years or zero variance.
    """
    v = np.asarray(values, dtype=float)
    if groups is not None:
        g = np.asarray(groups)
        if g.shape != v.shape:
            raise ValueError("annual_lag1_autocorrelation: values and groups must align")
        ok = ~np.isnan(v)
        labels = np.unique(g[ok])
        v = np.array([v[ok & (g == lab)].mean() for lab in labels])
    else:
        v = v[~np.isnan(v)]
    r1 = float("nan")
    if v.size >= 4:
        a, b = v[:-1] - v[:-1].mean(), v[1:] - v[1:].mean()
        den = float(np.sqrt((a * a).sum() * (b * b).sum()))
        if den > 0:
            r1 = float((a * b).sum() / den)
    return {
        "r1": r1, "n_years": int(v.size),
        "high": bool(np.isfinite(r1) and r1 >= high_threshold),
        "threshold": high_threshold,
    }
