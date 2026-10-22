"""Science Wave 3 PR-1: water_year, grouped_bootstrap, scope, annual_lag1_autocorrelation."""
from __future__ import annotations

import numpy as np
import pytest

from aihydro_core.science import (
    annual_lag1_autocorrelation,
    grouped_bootstrap,
    make_scope,
    scope_excludes,
    water_year,
    water_year_sampling_scope,
)


def _daily(n_years: int, start="1990-10-01"):
    d = np.arange(np.datetime64(start), np.datetime64(start) + np.timedelta64(365 * n_years, "D"))
    return d, water_year(d)


class TestWaterYear:
    def test_boundaries(self):
        d = ["2000-09-30", "2000-10-01", "2001-01-15", "2001-09-30", "2001-10-01"]
        assert water_year(d).tolist() == [2000, 2001, 2001, 2001, 2002]

    def test_leap_day_and_pandas_free_types(self):
        assert water_year(["2000-02-29"]).tolist() == [2000]
        import datetime
        assert water_year([datetime.date(2019, 12, 31)]).tolist() == [2020]

    def test_nat_rejected(self):
        with pytest.raises(ValueError):
            water_year(np.array(["NaT"], dtype="datetime64[D]"))


class TestGroupedBootstrap:
    def test_groups_never_split(self):
        _, wy = _daily(15)
        seen = []

        def fn(idx):
            seen.append(idx.copy())
            return float(idx.size)

        grouped_bootstrap({"n": fn}, wy.size, wy, n=50)
        sizes = {int(g): int((wy == g).sum()) for g in np.unique(wy)}
        for idx in seen[1:]:
            ys, counts = np.unique(wy[idx], return_counts=True)
            for y, c in zip(ys, counts):
                # each drawn group appears as a whole multiple of its size
                assert c % sizes[int(y)] == 0
            # a full-size resample (n_groups draws) is built from whole groups
            assert idx.size == sum(
                sizes[int(y)] * (c // sizes[int(y)]) for y, c in zip(ys, counts)
            )

    def test_deterministic_with_seed(self):
        rng = np.random.default_rng(1)
        _, wy = _daily(15)
        x = rng.normal(size=wy.size)
        f = {"m": lambda i: x[i].mean()}
        a = grouped_bootstrap(f, x.size, wy, n=200, random_state=7)
        b = grouped_bootstrap(f, x.size, wy, n=200, random_state=7)
        c = grouped_bootstrap(f, x.size, wy, n=200, random_state=8)
        assert a == b
        assert (a["m"]["ci_low"], a["m"]["ci_high"]) != (c["m"]["ci_low"], c["m"]["ci_high"])

    def test_output_contract(self):
        rng = np.random.default_rng(2)
        _, wy = _daily(25)
        x = rng.normal(size=wy.size)
        r = grouped_bootstrap({"m": lambda i: x[i].mean()}, x.size, wy, n=300)["m"]
        assert r["method"] == "bootstrap_group"
        assert r["n_groups"] == 25 and r["group"] == "water_year" and r["B"] == 300
        assert r["low_n"] is False and r["ci_level"] == 0.90
        assert r["ci_low"] <= r["value"] <= r["ci_high"]
        assert r["scope"] == water_year_sampling_scope()
        assert "interannual_persistence" in r["scope"]["excludes"]

    def test_paired_indices(self):
        """RR = sum(q)/sum(p) uses the SAME indices for q and p."""
        rng = np.random.default_rng(3)
        _, wy = _daily(20)
        p = rng.gamma(2.0, 2.0, size=wy.size)
        q = 0.6 * p
        # exact pairing => ratio is 0.6 in every resample; any misalignment would vary it
        r = grouped_bootstrap({"rr": lambda i: q[i].sum() / p[i].sum()}, p.size, wy, n=200)["rr"]
        assert r["value"] == pytest.approx(0.6)
        assert r["ci_low"] == pytest.approx(0.6) and r["ci_high"] == pytest.approx(0.6)
        # per-year-varying ratio => CI has width and brackets the point
        ratio = {y: 0.4 + 0.02 * (y - wy.min()) for y in np.unique(wy)}
        q2 = p * np.array([ratio[y] for y in wy])
        r2 = grouped_bootstrap({"rr": lambda i: q2[i].sum() / p[i].sum()}, p.size, wy, n=500)["rr"]
        assert r2["ci_high"] > r2["ci_low"]
        assert r2["ci_low"] <= r2["value"] <= r2["ci_high"]

    def test_within_year_ar1_persistence_widens_interval(self):
        """Within-year persistence is captured: IID-day CI under-covers, grouped is wider."""
        n_years, L = 20, 365

        def series(phi, seed):
            rng = np.random.default_rng(seed)
            out = np.empty((n_years, L))
            for y in range(n_years):
                e = rng.normal(size=L)
                v = np.empty(L)
                v[0] = e[0]
                for t in range(1, L):
                    v[t] = phi * v[t - 1] + e[t]
                out[y] = v
            return out.ravel()

        wy = np.repeat(np.arange(n_years), L)

        def width(phi):
            x = series(phi, 11)
            r = grouped_bootstrap({"m": lambda i: x[i].mean()}, x.size, wy, n=500)["m"]
            return r["ci_high"] - r["ci_low"]

        w0, w9 = width(0.0), width(0.95)
        assert w9 > 3 * w0

    def test_between_year_persistence_is_not_captured(self):
        """
        Documented limitation: groups are treated as exchangeable.  An annual
        series with strong year-to-year persistence gets (about) the same
        interval as a shuffled copy of it, because resampling years erases order.
        """
        n_years, L = 30, 30
        rng = np.random.default_rng(5)
        annual = np.empty(n_years)
        annual[0] = 0.0
        for y in range(1, n_years):
            annual[y] = 0.9 * annual[y - 1] + rng.normal()
        shuffled = rng.permutation(annual)
        wy = np.repeat(np.arange(n_years), L)

        def ci(a):
            x = np.repeat(a, L)
            r = grouped_bootstrap({"m": lambda i: x[i].mean()}, x.size, wy, n=4000)["m"]
            return r["ci_high"] - r["ci_low"]

        # same multiset of years => same distribution; only MC noise differs
        assert ci(annual) == pytest.approx(ci(shuffled), rel=0.1)  # order-blind
        # ...which is why the persistence is reported separately:
        assert annual_lag1_autocorrelation(annual)["high"] is True

    def test_refuses_below_min_groups(self):
        _, wy = _daily(9)
        with pytest.raises(ValueError, match="needs >=10 groups"):
            grouped_bootstrap({"m": lambda i: float(i.size)}, wy.size, wy, n=10)
        grouped_bootstrap({"m": lambda i: float(i.size)}, wy.size, wy, n=10, min_groups=9)

    def test_low_n_flag(self):
        for n_years, expected in [(10, True), (19, True), (20, False)]:
            _, wy = _daily(n_years)
            r = grouped_bootstrap({"m": lambda i: float(i.size)}, wy.size, wy, n=20)["m"]
            assert r["low_n"] is expected and r["n_groups"] == n_years

    def test_shape_mismatch_rejected(self):
        with pytest.raises(ValueError):
            grouped_bootstrap({"m": lambda i: 0.0}, 10, np.arange(5))


class TestScope:
    def test_shape_and_helpers(self):
        s = make_scope(["a"], ["b"], ["c", "c"])
        assert s == {"varies": ["a"], "assumes": ["b"], "excludes": ["c"]}
        assert scope_excludes(s, "c") and not scope_excludes(s, "b")
        assert scope_excludes(None, "forcing_product")  # undeclared => treated as excluded

    def test_varied_and_excluded_conflict(self):
        with pytest.raises(ValueError):
            make_scope(["a"], [], ["a"])


class TestLag1:
    def test_annual_series_and_grouped_daily(self):
        rng = np.random.default_rng(9)
        iid = rng.normal(size=200)
        assert abs(annual_lag1_autocorrelation(iid)["r1"]) < 0.3
        ar = np.cumsum(rng.normal(size=60))
        assert annual_lag1_autocorrelation(ar)["high"] is True
        g = np.repeat(np.arange(40), 5)
        res = annual_lag1_autocorrelation(np.repeat(ar[:40], 5), g)
        assert res["n_years"] == 40 and res["r1"] == pytest.approx(
            annual_lag1_autocorrelation(ar[:40])["r1"]
        )

    def test_too_short_is_nan_not_high(self):
        r = annual_lag1_autocorrelation([1.0, 2.0, 3.0])
        assert np.isnan(r["r1"]) and r["high"] is False


def test_uncertainty_method_lists_every_emitted_method():
    from typing import get_args
    from aihydro_core.science import UncertaintyMethod, bootstrap_ci, block_bootstrap_ci, bootstrap_dict
    x = np.random.default_rng(0).normal(size=200)
    emitted = {
        bootstrap_ci(np.mean, x)["method"],
        block_bootstrap_ci(np.mean, x)["method"],
        bootstrap_dict({"m": np.mean}, x, use_block=True)["m"]["method"],
        bootstrap_dict({"m": np.mean}, x)["m"]["method"],
        grouped_bootstrap({"m": lambda i: 0.0}, 200, np.arange(200) % 20)["m"]["method"],
    }
    assert emitted <= set(get_args(UncertaintyMethod))
