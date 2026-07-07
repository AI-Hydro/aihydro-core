"""
Concrete bootstrap uncertainty implementations — requires numpy ([science] extra).

Kept separate from uncertainty.py so the protocol definitions stay stdlib-only.
Import via: from aihydro_core.science.uncertainty import bootstrap_ci, ...
"""
from __future__ import annotations

import logging
from typing import Callable, TypedDict

import numpy as np

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
