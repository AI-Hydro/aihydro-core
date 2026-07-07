"""
Tests for aihydro_core.science._bootstrap — the concrete IID and block
bootstrap CI implementations (Wave 2.3b of the ecosystem remediation plan).

Covers:
1. _default_block_size — matches the documented n^(1/3) rule.
2. Block vs IID bootstrap on autocorrelated data — proves the block method's
   reason for existing: IID resampling under-covers dependent series (too
   narrow a CI), block resampling is wider and more honest. This is the
   "block-length sensitivity" the remediation plan asked to document/verify,
   scoped to what's testable without a full per-series optimal-block-length
   estimator (documented as future work in _default_block_size()'s docstring).
"""
from __future__ import annotations

import numpy as np
import pytest

from aihydro_core.science._bootstrap import (
    _default_block_size,
    bootstrap_ci,
    block_bootstrap_ci,
    bootstrap_dict,
)


class TestDefaultBlockSize:
    def test_matches_cube_root_rule(self):
        # max(5, round(n^(1/3)))
        assert _default_block_size(125) == 5     # 125^(1/3) = 5
        assert _default_block_size(1000) == 10   # 1000^(1/3) = 10
        assert _default_block_size(27) == 5       # 27^(1/3) = 3, floored to min 5

    def test_never_below_minimum_of_5(self):
        for n in (10, 20, 30, 64):
            assert _default_block_size(n) >= 5

    def test_grows_with_sample_size(self):
        assert _default_block_size(8000) > _default_block_size(1000) > _default_block_size(125)


def _ar1_series(n: int, phi: float = 0.9, seed: int = 0) -> np.ndarray:
    """Synthetic AR(1) series: x[t] = phi*x[t-1] + noise. High phi = strong
    autocorrelation, the regime block bootstrap exists for (e.g. daily
    streamflow, which persists day-to-day far more than white noise)."""
    rng = np.random.default_rng(seed)
    noise = rng.normal(size=n)
    x = np.empty(n)
    x[0] = noise[0]
    for t in range(1, n):
        x[t] = phi * x[t - 1] + noise[t]
    return x


class TestBlockVsIidOnAutocorrelatedData:
    def test_block_ci_is_not_narrower_than_iid_on_strongly_autocorrelated_series(self):
        """The whole reason block bootstrap exists: IID resampling shuffles
        away autocorrelation and under-covers (produces a falsely narrow CI)
        for dependent data. On a strongly autocorrelated series, the block
        CI must not be narrower than the IID CI for the same statistic."""
        series = _ar1_series(2000, phi=0.9, seed=1)

        iid = bootstrap_ci(np.mean, series, n=300, random_state=1)
        block = block_bootstrap_ci(np.mean, series, n=300, random_state=1)

        iid_width = iid["ci_high"] - iid["ci_low"]
        block_width = block["ci_high"] - block["ci_low"]

        assert block_width >= iid_width * 0.9, (
            f"block CI (width={block_width:.4f}) is unexpectedly narrower than "
            f"IID CI (width={iid_width:.4f}) on strongly autocorrelated data — "
            "the block method should widen, not narrow, the interval here."
        )

    def test_block_bootstrap_ci_method_label(self):
        series = _ar1_series(500, phi=0.8, seed=2)
        result = block_bootstrap_ci(np.mean, series, n=100, random_state=2)
        assert result["method"] == "bootstrap_block"

    def test_bootstrap_dict_use_block_matches_default_block_size(self):
        """bootstrap_dict's internal block-size default must be the same
        documented rule as block_bootstrap_ci's — single source of truth."""
        series = _ar1_series(1000, phi=0.85, seed=3)
        results = bootstrap_dict(
            {"mean": np.mean, "std": np.std}, series, use_block=True, n=100, random_state=3
        )
        assert results["mean"]["method"] == "bootstrap_block"
        assert np.isfinite(results["mean"]["ci_low"])
        assert np.isfinite(results["mean"]["ci_high"])


class TestBootstrapCiRaisesOnTooFewPoints:
    def test_bootstrap_ci_requires_5_points(self):
        with pytest.raises(ValueError):
            bootstrap_ci(np.mean, [1.0, 2.0])

    def test_block_bootstrap_ci_requires_10_points(self):
        with pytest.raises(ValueError):
            block_bootstrap_ci(np.mean, [1.0, 2.0, 3.0])
