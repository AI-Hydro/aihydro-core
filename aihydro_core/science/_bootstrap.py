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

def _year_month(dates: Any) -> tuple[np.ndarray, np.ndarray]:
    """Calendar (year, month) arrays using the LOCAL wall-clock date (tz dropped, never converted)."""
    # pandas Series / DatetimeIndex (tz-aware too): .year/.month are wall-clock fields.
    acc = dates.dt if hasattr(dates, "dt") else dates
    if hasattr(acc, "year") and hasattr(acc, "month") and not isinstance(acc, (str, bytes)):
        try:
            y, m = np.asarray(acc.year), np.asarray(acc.month)
            if y.ndim >= 1:
                if y.dtype.kind == "f" and np.isnan(y).any():
                    raise ValueError("water_year: dates contain NaT")
                return y.astype(int), m.astype(int)
        except TypeError:
            pass
    arr = np.asarray(dates)
    if arr.dtype.kind in "biuf":
        raise TypeError(
            f"water_year needs dates, got numeric dtype {arr.dtype}; "
            "convert to datetime64/date objects first (epoch units are ambiguous)."
        )
    if arr.dtype.kind == "O":  # python date/datetime objects (tz-aware: wall clock)
        ys, ms = [], []
        for el in arr.ravel():
            if hasattr(el, "year") and hasattr(el, "month"):
                if el != el:  # pandas NaT
                    raise ValueError("water_year: dates contain NaT")
                ys.append(el.year); ms.append(el.month)
            else:
                d = np.datetime64(el, "D")
                if np.isnat(d):
                    raise ValueError("water_year: dates contain NaT")
                mo = d.astype("datetime64[M]")
                ys.append(int(mo.astype("datetime64[Y]").astype(int)) + 1970)
                ms.append(int(mo.astype(int) % 12) + 1)
        return np.array(ys, dtype=int).reshape(arr.shape), np.array(ms, dtype=int).reshape(arr.shape)
    d = arr.astype("datetime64[D]")
    if np.isnat(d).any():
        raise ValueError("water_year: dates contain NaT")
    months = d.astype("datetime64[M]")
    return months.astype("datetime64[Y]").astype(int) + 1970, (months.astype(int) % 12) + 1


def water_year(dates: Any) -> np.ndarray:
    """
    USGS water year of each date: Oct 1 starts a water year, labelled by the
    calendar year in which it ends (2000-10-01 .. 2001-09-30 -> 2001).

    ``dates`` may be datetime64 arrays, pandas DatetimeIndex/Series, ISO
    strings, or ``datetime.date``/``datetime`` objects.  Timezone-aware inputs
    use the LOCAL wall-clock date (the tz is dropped, not converted to UTC),
    because daily hydrologic records are local-date series: 2000-09-30 23:00
    in any zone is water year 2000, 2000-10-01 00:00 is 2001.

    Returns an int array of the same length.  NaT raises ValueError; numeric
    (int/float) input raises TypeError.
    """
    years, month = _year_month(dates)
    return np.where(month >= 10, years + 1, years).astype(int)


class GroupedBootstrapResult(UncertaintyResult, total=False):
    """UncertaintyResult plus grouped-bootstrap provenance (all keys always set)."""
    n_groups: int
    group: str
    B: int
    B_valid: int
    valid_frac: float
    ci_degraded: bool
    ci_reason: str
    low_n: bool
    coverage_note: str
    scope: dict


#: Fewer than this many groups is permitted (down to ``min_groups``) but flagged ``low_n``.
LOW_N_GROUPS = 30

#: Engineering constants (labelled, not statistical results): a metric is flagged
#: ``ci_degraded`` below this fraction of valid replicates, and its CI is NaN below the cutoff.
DEGRADED_VALID_FRAC = 0.95
NAN_CI_VALID_FRAC = 0.5

#: Engineering constant: minimum consecutive year-pairs for a lag-1 estimate.
MIN_LAG1_PAIRS = 8

#: Minimum replicates; fewer makes percentile tails meaningless.
MIN_REPLICATES = 100

#: Surface this next to any grouped-bootstrap interval.  Measured by the seeded
#: coverage test (iid years, 20 groups, 90% nominal): see tests/test_grouped_bootstrap.py.
COVERAGE_NOTE = (
    "Percentile group-bootstrap intervals under-cover at small group counts: "
    "about 88% empirical coverage for a nominal 90% interval of a sample mean "
    "with 20 iid years (2000 seeded trials; statistic-dependent, skewed or "
    "ratio statistics can be worse). Treat intervals from <30 groups as optimistic."
)


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
    ``fn(arange(n_items))`` on the same item set.  All metrics in ``fns``
    share the same group draws in each replicate (so their intervals are
    jointly comparable, not independent).

    Parameters
    ----------
    fns          : metric name -> fn(index_array) -> float.
    n_items      : length of the aligned arrays the fns index into.
    groups       : length-``n_items`` group label per item (e.g. ``water_year(dates)``);
                   NaN/None labels are rejected.
    n            : bootstrap replicates, >= 100 (default 2000; 500 leaves ~25
                   draws per tail for a 90% interval, which is unstable).
    min_groups   : >= 2; refuse (ValueError) below this many distinct groups.
                   Below 30 groups the result is flagged ``low_n``.

    Replicates where ``fn`` raises or returns a non-finite value are dropped
    and reported: ``B_valid``, ``valid_frac``; ``ci_degraded`` when
    ``valid_frac < DEGRADED_VALID_FRAC`` (0.95); the interval is NaN (with
    ``ci_reason``) when ``valid_frac < NAN_CI_VALID_FRAC`` (0.5) or the point estimate is NaN / raises.  A raising fn
    logs one warning per metric with the exception type and count.

    Coverage (honest): percentile group bootstrap under-covers for few groups.
    In the seeded simulation in the test-suite (iid years, 20 groups, nominal
    90%, sample mean) empirical coverage was 0.88 over 2000 trials (0.905 over
    the 200 trials the test-suite runs); ``coverage_note`` says so.

    Scope: sampling uncertainty of the group draw only.  Within-group
    dependence (seasonality, intra-year persistence) is preserved; **between-
    group persistence is NOT captured** (groups are treated as exchangeable) —
    see ``annual_lag1_autocorrelation``.  The returned ``scope`` says so.
    """
    if n_items < 1:
        raise ValueError("grouped_bootstrap: n_items must be >= 1")
    if not (0.0 < ci < 1.0):
        raise ValueError(f"grouped_bootstrap: ci must be in (0, 1), got {ci}")
    if min_groups < 2:
        raise ValueError(f"grouped_bootstrap: min_groups must be >= 2, got {min_groups}")
    if n < MIN_REPLICATES:
        raise ValueError(f"grouped_bootstrap: n must be >= {MIN_REPLICATES}, got {n}")
    g = np.asarray(groups)
    if g.shape != (n_items,):
        raise ValueError(
            f"grouped_bootstrap: groups must have shape ({n_items},), got {g.shape}"
        )
    if g.dtype.kind == "f":
        bad = bool(np.isnan(g).any())
    elif g.dtype.kind == "M":
        bad = bool(np.isnat(g).any())
    elif g.dtype.kind == "O":
        bad = any(x is None or x != x for x in g.tolist())
    else:
        bad = False
    if bad:
        raise ValueError("grouped_bootstrap: group labels contain NaN/None/NaT; drop or fix those items")
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
    point_reason: dict[str, str] = {}
    for k, fn in fns.items():
        try:
            point[k] = float(fn(all_idx))
            if not np.isfinite(point[k]):
                point_reason[k] = "point estimate is not finite"
        except Exception as exc:
            point[k] = float("nan")
            point_reason[k] = f"point estimate raised {type(exc).__name__}: {exc}"

    rng = np.random.default_rng(random_state)
    boot: dict[str, list[float]] = {k: [] for k in fns}
    raised: dict[str, dict[str, int]] = {k: {} for k in fns}
    for _ in range(n):
        draw = rng.integers(0, n_groups, size=n_groups)
        idx = np.concatenate([members[j] for j in draw])
        for k, fn in fns.items():
            try:
                v = float(fn(idx))
            except Exception as exc:
                nm = type(exc).__name__
                raised[k][nm] = raised[k].get(nm, 0) + 1
                continue
            if np.isfinite(v):
                boot[k].append(v)

    for k, errs in raised.items():
        if errs:
            log.warning(
                "grouped_bootstrap: metric %r raised in %d of %d replicates (%s); those replicates were dropped.",
                k, sum(errs.values()), n, ", ".join(f"{a}x{b}" for a, b in sorted(errs.items())),
            )

    low_n = n_groups < LOW_N_GROUPS
    out: dict[str, GroupedBootstrapResult] = {}
    for k in fns:
        samps = boot[k]
        frac = len(samps) / n
        degraded = frac < DEGRADED_VALID_FRAC
        reason = ""
        if k in point_reason:
            lo = hi = float("nan"); reason = point_reason[k]; degraded = True
        elif frac < NAN_CI_VALID_FRAC:
            lo = hi = float("nan")
            reason = f"only {len(samps)} of {n} replicates were finite (<50%)"
        else:
            lo, hi = _quantile_bounds(samps, ci)
            if degraded:
                reason = f"{len(samps)} of {n} replicates were finite (<95%); interval may be biased"
        out[k] = GroupedBootstrapResult(
            value=point[k], ci_low=lo, ci_high=hi,
            method="bootstrap_group", n=n_items, ci_level=ci,
            n_groups=n_groups, group=group_name, B=int(n), B_valid=len(samps),
            valid_frac=float(frac), ci_degraded=bool(degraded), ci_reason=reason,
            low_n=low_n, coverage_note=COVERAGE_NOTE,
            scope=water_year_sampling_scope(),
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

    ``values`` is either already one value per consecutive year
    (``groups=None``; NaN marks a missing year) or an item-level series
    aggregated by group mean, with integer year labels in ``groups``.  Only
    truly consecutive years are paired: years on either side of a missing
    (NaN / absent) year are never treated as adjacent; ``has_gaps`` reports it.
    ``high_threshold`` is a labelled engineering threshold, not a test.

    Returns ``{"r1","n_years","n_pairs","has_gaps","low_n","high","threshold"}``.
    With fewer than ``MIN_LAG1_PAIRS`` (8, an engineering constant) consecutive
    pairs, ``r1`` is NaN, ``low_n`` is True and ``high`` is never set; likewise
    for zero variance.  ``high_threshold`` (0.3) is also an engineering constant.
    """
    v = np.asarray(values, dtype=float)
    if groups is not None:
        g = np.asarray(groups)
        if g.shape != v.shape:
            raise ValueError("annual_lag1_autocorrelation: values and groups must align")
        if g.dtype.kind not in "iu":
            raise TypeError("annual_lag1_autocorrelation: groups must be integer years")
        ok = ~np.isnan(v)
        by = {int(lab): float(v[ok & (g == lab)].mean()) for lab in np.unique(g[ok])}
        span = range(int(g.min()), int(g.max()) + 1)
        series = np.array([by.get(y, np.nan) for y in span])
    else:
        series = v
    fin = np.isfinite(series)
    pair = fin[:-1] & fin[1:]
    a, b = series[:-1][pair], series[1:][pair]
    r1 = float("nan")
    low_n = a.size < MIN_LAG1_PAIRS
    if not low_n:
        a0, b0 = a - a.mean(), b - b.mean()
        den = float(np.sqrt((a0 * a0).sum() * (b0 * b0).sum()))
        if den > 0:
            r1 = float((a0 * b0).sum() / den)
    return {
        "r1": r1, "n_years": int(fin.sum()), "n_pairs": int(pair.sum()),
        "has_gaps": bool(series.size and not fin.all()), "low_n": bool(low_n),
        "high": bool(np.isfinite(r1) and r1 >= high_threshold),
        "threshold": high_threshold,
    }
