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
        # unequal group sizes + a fn that records the exact index multiset.
        sizes = [3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 2, 4]
        wy = np.repeat(np.arange(len(sizes)), sizes)
        seen = []
        grouped_bootstrap({"n": lambda idx: (seen.append(idx.copy()), 0.0)[1]}, wy.size, wy, n=100)
        sz = dict(zip(range(len(sizes)), sizes))
        assert len(seen) == 101  # point + 100 replicates
        for idx in seen[1:]:
            ys, counts = np.unique(wy[idx], return_counts=True)
            for y, c in zip(ys, counts):
                k, rem = divmod(int(c), sz[int(y)])
                assert rem == 0  # a group is present k whole times, never partially
                members = np.flatnonzero(wy == y)
                assert np.array_equal(np.sort(idx[wy[idx] == y]), np.repeat(members, k))
            assert len(idx) == sum(sz[int(y)] * (c // sz[int(y)]) for y, c in zip(ys, counts))
        # exactly n_groups draws per replicate, so each replicate holds n_groups group-copies
        assert all(
            sum(c // sz[int(y)] for y, c in zip(*np.unique(wy[i], return_counts=True))) == len(sizes)
            for i in seen[1:]
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
        _, wy = _daily(30)
        x = rng.normal(size=wy.size)
        r = grouped_bootstrap({"m": lambda i: x[i].mean()}, x.size, wy, n=300)["m"]
        assert r["method"] == "bootstrap_group"
        assert r["n_groups"] == 30 and r["group"] == "water_year" and r["B"] == 300
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
            grouped_bootstrap({"m": lambda i: float(i.size)}, wy.size, wy, n=100)
        grouped_bootstrap({"m": lambda i: float(i.size)}, wy.size, wy, n=100, min_groups=9)

    def test_low_n_flag(self):
        for n_years, expected in [(10, True), (29, True), (30, False)]:
            _, wy = _daily(n_years)
            r = grouped_bootstrap({"m": lambda i: float(i.size)}, wy.size, wy, n=100)["m"]
            assert r["low_n"] is expected and r["n_groups"] == n_years

    def test_shape_mismatch_rejected(self):
        with pytest.raises(ValueError):
            grouped_bootstrap({"m": lambda i: 0.0}, 10, np.arange(5))


class TestScope:
    def test_shape_and_helpers(self):
        s = make_scope(["a"], ["b"], ["c", "c"])
        assert s == {"varies": ["a"], "assumes": ["b"], "excludes": ["c"]}
        assert scope_excludes(s, "c") and scope_excludes(s, "b") and not scope_excludes(s, "a")
        assert scope_excludes(None, "forcing_product")  # undeclared => treated as excluded

    def test_conservative_and_exact_membership(self):
        s = water_year_sampling_scope()
        assert scope_excludes(s, "some_term_not_mentioned")  # well-formed but silent => excluded
        assert scope_excludes(s, "forcing")  # no substring matching
        assert not scope_excludes(s, "water_year_sample")  # explicitly varied
        bad = {"varies": "water_year_sample", "assumes": [], "excludes": []}  # str, not list
        assert scope_excludes(bad, "water_year_sample")
        assert scope_excludes({"varies": [1], "excludes": []}, "x")

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

    def test_missing_year_is_not_bridged(self):
        # alternating +/-: lag-1 is strongly negative; dropping a year must not pair its neighbours
        v = np.array([1.0, -1.0, 1.0, np.nan, 1.0, -1.0, 1.0, -1.0, 1.0, -1.0])
        r = annual_lag1_autocorrelation(v)
        assert r["has_gaps"] is True and r["n_years"] == 9 and r["n_pairs"] == 7
        assert r["r1"] < -0.9
        # grouped form with an absent year (1992 missing) behaves the same
        yrs = np.array([1990, 1991, 1993, 1994, 1995, 1996, 1997, 1998, 1999, 2000])
        r2 = annual_lag1_autocorrelation(np.arange(10) % 2 * 2 - 1.0, yrs)
        assert r2["has_gaps"] is True and r2["n_pairs"] == 8

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


class TestDroppedReplicates:
    def _setup(self):
        _, wy = _daily(20)
        x = np.random.default_rng(0).normal(size=wy.size)
        return wy, x

    def test_one_sided_nan_degrades_ci(self):
        wy, x = self._setup()
        # NaN whenever the resample mean is high: drops the upper tail only
        fn = lambda i: float("nan") if x[i].mean() > x.mean() + 0.01 else x[i].mean()
        r = grouped_bootstrap({"m": fn}, x.size, wy, n=400)["m"]
        assert r["ci_degraded"] is True or np.isnan(r["ci_low"])
        assert r["valid_frac"] < 0.95 and r["B_valid"] < r["B"] and r["ci_reason"]

    def test_mostly_failing_gives_nan_ci(self, caplog):
        wy, x = self._setup()
        fn = lambda i: 0.0 if i.size == x.size and np.array_equal(i, np.arange(x.size)) else float("nan")
        r = grouped_bootstrap({"m": fn}, x.size, wy, n=200)["m"]
        assert r["valid_frac"] < 0.5 and np.isnan(r["ci_low"]) and np.isnan(r["ci_high"])
        assert "<50%" in r["ci_reason"]

    def test_raising_fn_warns_once_and_is_nan(self, caplog):
        wy, x = self._setup()

        def fn(i):
            if i.size != x.size:
                raise RuntimeError("boom")
            return float(x[i].mean())

        with caplog.at_level("WARNING", logger="aihydro_core.science._bootstrap"):
            r = grouped_bootstrap({"m": fn}, x.size, wy, n=100)["m"]
        warns = [m for m in caplog.records if "raised" in m.getMessage()]
        assert len(warns) == 1 and "RuntimeError" in warns[0].getMessage()
        assert np.isnan(r["ci_low"]) and r["ci_degraded"] and r["ci_reason"]

    def test_nan_or_raising_point_gives_nan_ci(self):
        wy, x = self._setup()

        def point_nan(i):
            return float("nan") if i.size == x.size and np.array_equal(i, np.arange(x.size)) else 1.0

        r = grouped_bootstrap({"m": point_nan}, x.size, wy, n=100)["m"]
        assert np.isnan(r["value"]) and np.isnan(r["ci_low"]) and "point estimate" in r["ci_reason"]

        def point_raise(i):
            if np.array_equal(i, np.arange(x.size)):
                raise ValueError("bad point")
            return 1.0

        r = grouped_bootstrap({"m": point_raise}, x.size, wy, n=100)["m"]
        assert np.isnan(r["ci_low"]) and "ValueError" in r["ci_reason"]

    def test_healthy_has_clean_flags(self):
        wy, x = self._setup()
        r = grouped_bootstrap({"m": lambda i: x[i].mean()}, x.size, wy, n=100)["m"]
        assert r["valid_frac"] == 1.0 and r["ci_degraded"] is False and r["ci_reason"] == ""


class TestArgumentValidation:
    def test_bad_arguments(self):
        _, wy = _daily(12)
        f = {"m": lambda i: 0.0}
        for kw in ({"ci": 0.0}, {"ci": 1.0}, {"ci": 1.5}, {"min_groups": 1}, {"n": 99}):
            with pytest.raises(ValueError):
                grouped_bootstrap(f, wy.size, wy, **{"n": 100, **kw})

    def test_nan_group_labels_rejected(self):
        g = np.repeat(np.arange(12, dtype=float), 5)
        g[3] = np.nan
        with pytest.raises(ValueError, match="NaN"):
            grouped_bootstrap({"m": lambda i: 0.0}, g.size, g, n=100)
        go = np.repeat(np.arange(12), 5).astype(object)
        go[0] = None
        with pytest.raises(ValueError, match="NaN"):
            grouped_bootstrap({"m": lambda i: 0.0}, go.size, go, n=100)


class TestCoverage:
    def test_coverage_iid_20_groups(self):
        """Seeded: percentile group bootstrap under-covers a bit at 20 groups.
        Measured 0.905 over these 200 trials (0.88 over 2000 trials); nominal 0.90."""
        wy = np.repeat(np.arange(20), 3)
        hit = 0
        trials = 200
        for t in range(trials):
            x = np.repeat(np.random.default_rng(1000 + t).normal(size=20), 3)
            r = grouped_bootstrap({"m": lambda i: x[i].mean()}, 60, wy, n=500, random_state=t)["m"]
            hit += r["ci_low"] <= 0.0 <= r["ci_high"]
        cov = hit / trials
        assert cov == pytest.approx(0.905)  # deterministic given seeds
        assert cov >= 0.80

    def test_coverage_note_present_and_low_n_below_30(self):
        _, wy = _daily(25)
        r = grouped_bootstrap({"m": lambda i: 0.0}, wy.size, wy, n=100)["m"]
        assert r["low_n"] is True and "under-cover" in r["coverage_note"] and "<30" in r["coverage_note"]


class TestWaterYearTz:
    def test_tz_aware_pandas_uses_wall_clock(self):
        pd = pytest.importorskip("pandas")
        idx = pd.DatetimeIndex(["2000-09-30 23:00", "2000-10-01 00:00"], tz="America/Denver")
        assert water_year(idx).tolist() == [2000, 2001]
        assert water_year(pd.Series(idx)).tolist() == [2000, 2001]
        # UTC conversion would have moved 23:00 Denver into Oct 1
        assert water_year(pd.DatetimeIndex(["2000-09-30 23:00"], tz="Asia/Tokyo")).tolist() == [2000]

    def test_tz_aware_python_datetimes(self):
        import datetime as dt
        z = dt.timezone(dt.timedelta(hours=-7))
        v = [dt.datetime(2000, 9, 30, 23, 0, tzinfo=z), dt.datetime(2000, 10, 1, 0, 0, tzinfo=z)]
        assert water_year(v).tolist() == [2000, 2001]

    def test_numeric_rejected(self):
        for bad in ([2000, 2001], np.array([1.5e9, 1.6e9]), np.arange(3)):
            with pytest.raises(TypeError, match="numeric"):
                water_year(bad)
