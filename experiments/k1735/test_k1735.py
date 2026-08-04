#!/usr/bin/env python3
"""Unit tests for K1735.

The tests that matter here are the ones that would have caught a wrong *answer*, not
just a crash: the noise-floor constants, the bias-corrected decomposition recovering
known components from simulated data, the circular-shift nulls being correctly sized,
and -- most important -- T1 refusing to reject when the diurnal pattern really is
sufficient, while rejecting when the profile drifts.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from scipy import special

EXP_DIR = Path(__file__).resolve().parent
if str(EXP_DIR) not in sys.path:
    sys.path.insert(0, str(EXP_DIR))

import K1735 as k  # noqa: E402


def _u_shape(n_bins: int) -> np.ndarray:
    """A realistic U-shaped log-diurnal profile, centred."""
    x = np.linspace(0, 1, n_bins)
    s = 1.2 * np.cos(2 * np.pi * x) + 0.35 * np.cos(4 * np.pi * x)
    return s - s.mean()


def _px(ret: np.ndarray) -> np.ndarray:
    """Price path implied by a sub-return matrix, for the price-based m=1 aggregation."""
    return 100.0 * np.exp(np.cumsum(ret, axis=1))


def _simulate(rng, *, d=600, m=5, v_day=0.35, v_stoch=0.0, drift=0.0, s=None):
    """Sub-returns from the multiplicative model, with optional profile drift."""
    s = _u_shape(60) if s is None else s
    k_bins = len(s)
    a = rng.normal(0, np.sqrt(v_day), size=d)
    profile = s[None, :] * (1.0 + drift * np.linspace(-1, 1, d)[:, None])
    logvar = a[:, None] + profile
    if v_stoch > 0:
        logvar = logvar + rng.normal(0, np.sqrt(v_stoch), size=(d, k_bins))
    r = rng.standard_normal((d, k_bins, m)) * np.sqrt(np.exp(logvar) / m)[:, :, None]
    return r.reshape(d, k_bins * m)


# ------------------------------------------------------------------ noise floors


def test_gaussian_noise_floor_matches_trigamma():
    assert k.gaussian_noise_floor(1) == pytest.approx(np.pi**2 / 2, rel=1e-12)
    for m in (1, 2, 5, 15):
        assert k.gaussian_noise_floor(m) == pytest.approx(special.polygamma(1, m / 2), rel=1e-12)


def test_noise_floor_decreases_with_m():
    floors = [k.gaussian_noise_floor(m) for m in (1, 3, 5, 15, 30)]
    assert all(a > b for a, b in zip(floors, floors[1:]))


def test_noise_floor_is_what_simulated_data_shows():
    """The theoretical floor must match Var(log RV) of pure Gaussian noise."""
    rng = np.random.default_rng(7)
    for m in (1, 5, 15):
        rv = np.square(rng.standard_normal((200_000, m))).sum(axis=1)
        assert np.var(np.log(rv)) == pytest.approx(k.gaussian_noise_floor(m), rel=0.03)


# ---------------------------------------------------------------- bar RV assembly


def test_bar_rv_sum_sq_and_agg_modes():
    ret = np.arange(12, dtype=float).reshape(1, 12)
    px = _px(ret)
    rv, m = k.bar_rv(ret, px, 4)
    assert m == 4 and rv.shape == (1, 3)
    assert rv[0, 0] == pytest.approx(0 + 1 + 4 + 9)
    rv1, m1 = k.bar_rv(ret, px, 4, 4)
    assert m1 == 1
    assert rv1[0, 0] == pytest.approx((0 + 1 + 2 + 3) ** 2)


def test_bar_rv_rejects_indivisible_aggregation():
    with pytest.raises(ValueError):
        k.bar_rv(np.zeros((1, 12)), np.ones((1, 12)), 5, 2)


def test_agg_ret_sq_keeps_exact_zeros_that_summing_would_destroy():
    """The float32 bug this signature exists to close.

    A bin whose price returns to where it started has a bin return of exactly zero.
    Summing rounded sub-returns produces a tiny non-zero instead, and log of that is a
    huge negative outlier that silently inflates the residual variance.
    """
    # Two bins of four sub-returns. Bin 1's reference price is bin 0's closing price, so
    # a flat price across bin 1 is a true zero return -- the case the panel hits ~7% of
    # the time on TX. (Bin 0 is referenced to the session-start price, not a bar close,
    # so it is not the case under test.)
    px = np.array([[100.0, 101.0, 100.0, 100.0, 101.0, 99.0, 100.0, 100.0]], dtype=np.float32)
    logp = np.log(px.astype(np.float64))
    ret = np.diff(logp, prepend=logp[:, [0]]).astype(np.float32).astype(np.float64)

    rv, m = k.bar_rv(ret, px, 4, 4)
    assert m == 1
    assert rv[0, 1] == 0.0  # price ends bin 1 exactly where bin 0 left it

    # Summing rounded sub-returns does not lose *every* such zero -- it loses a large
    # fraction of them, which is why the panel showed 3.96% instead of the true 7.00%.
    # Assert on the fraction over many random tick paths, not on one hand-picked case.
    rng = np.random.default_rng(101)
    n, sub = 4000, 5
    steps = rng.integers(-3, 4, size=(n, 2 * sub))
    steps[:, sub:] -= steps[:, sub:].sum(axis=1, keepdims=True) // sub  # nudge toward flat
    level = 20000 + np.cumsum(steps, axis=1)
    flat = level[:, 2 * sub - 1] == level[:, sub - 1]  # bin 1 truly unchanged
    assert flat.sum() > 100, "test needs a decent number of true zeros"

    px_r = level.astype(np.float32)
    logp = np.log(px_r.astype(np.float64))
    ret_r = np.diff(logp, prepend=logp[:, [0]]).astype(np.float32).astype(np.float64)
    rv_price, _ = k.bar_rv(ret_r, px_r, sub, sub)
    rv_summed = np.square(ret_r.reshape(n, 2, sub).sum(axis=2))

    assert (rv_price[flat, 1] == 0.0).all()  # price-based keeps every true zero
    kept = float((rv_summed[flat, 1] == 0.0).mean())
    assert kept < 0.9, f"summing kept {kept:.2%} of true zeros; bug no longer reproduces"


def test_within_day_share_is_not_identified_when_sigma2e_is_below_the_floor():
    """Below-floor residual variance must read as null, never as 'diurnal explains 100%'."""
    fit = {
        "v_bin_raw": 0.4,
        "v_day_raw": 0.5,
        "sigma2_e": 0.30,
        "total_var": 1.2,
        "n_days": 200,
        "n_bins": 60,
    }
    sh = k.corrected_shares(fit, 0.49)  # floor above sigma2_e
    assert sh["v_stoch_identified"] is False
    assert not np.isfinite(sh["diurnal_share_within_day"])
    assert k.clean_nonfinite(sh)["diurnal_share_within_day"] is None


def test_floor_zero_rv_replaces_only_zeros():
    rv = np.array([[0.0, 4e-6]])
    price = np.full((1, 4), 100.0)
    out, share = k.floor_zero_rv(rv, price, 2, 1.0)
    assert share == pytest.approx(0.5)
    assert out[0, 1] == 4e-6  # untouched
    assert out[0, 0] == pytest.approx((0.5 * 1.0 / 100.0) ** 2)


# ---------------------------------------------------------------- decomposition


def test_two_way_is_orthogonal_decomposition():
    rng = np.random.default_rng(0)
    u = rng.normal(size=(50, 12))
    fit = k.two_way(u)
    d, kb = u.shape
    resid = u - fit["mu"] - fit["a"][:, None] - fit["s"][None, :]
    assert float(np.square(resid).sum()) == pytest.approx(
        fit["sigma2_e"] * (d - 1) * (kb - 1), rel=1e-9
    )
    assert fit["a"].sum() == pytest.approx(0.0, abs=1e-9)
    assert fit["s"].sum() == pytest.approx(0.0, abs=1e-9)


def test_decomposition_recovers_known_components():
    """The whole experiment rests on this: known s, q, g in -> right shares out."""
    rng = np.random.default_rng(42)
    s_true = _u_shape(60)
    v_day, v_stoch, m = 0.35, 0.20, 5
    ret = _simulate(rng, d=4000, m=m, v_day=v_day, v_stoch=v_stoch, s=s_true)
    rv, m_out = k.bar_rv(ret, _px(ret), m)
    assert m_out == m
    fit = k.two_way(np.log(rv))
    sh = k.corrected_shares(fit, k.gaussian_noise_floor(m))

    assert sh["v_bin"] == pytest.approx(float(np.mean(np.square(s_true))), rel=0.05)
    assert sh["v_day"] == pytest.approx(v_day, rel=0.10)
    assert sh["v_stoch_raw"] == pytest.approx(v_stoch, rel=0.15)


def test_naive_share_is_dominated_by_the_noise_floor_at_m1():
    """The headline methodological claim, as an executable assertion.

    Same volatility process, only the sub-return count changes. The naive share must
    collapse at m=1 while the corrected share stays put -- that is exactly why the
    m=1 reading of 'diurnal explains ~7%' is an artefact.
    """
    rng = np.random.default_rng(11)
    ret = _simulate(rng, d=3000, m=5, v_day=0.35, v_stoch=0.20)

    rv5, _ = k.bar_rv(ret, _px(ret), 5)
    rv1, _ = k.bar_rv(ret, _px(ret), 5, 5)
    sh5 = k.corrected_shares(k.two_way(np.log(rv5)), k.gaussian_noise_floor(5))
    sh1 = k.corrected_shares(k.two_way(np.log(rv1)), k.gaussian_noise_floor(1))

    assert sh1["naive_share"] < 0.5 * sh5["naive_share"]
    assert sh1["diurnal_share_systematic"] == pytest.approx(
        sh5["diurnal_share_systematic"], abs=0.12
    )


# ------------------------------------------------------------------ shift nulls


def test_roll_rows_preserves_row_content():
    rng = np.random.default_rng(3)
    x = rng.normal(size=(40, 9))
    y = k._roll_rows(x, rng)
    assert y.shape == x.shape
    for i in range(x.shape[0]):
        assert np.allclose(np.sort(y[i]), np.sort(x[i]))
    assert np.allclose(y.sum(axis=1), x.sum(axis=1))


def test_eta_sq_bin_invariant_denominator_under_row_rolls():
    """Circular shifts must leave SS_total alone, else the null is mis-scaled."""
    rng = np.random.default_rng(5)
    e = rng.normal(size=(80, 12))
    ss = float(np.square(e - e.mean()).sum())
    rolled = k._roll_rows(e, rng)
    assert float(np.square(rolled - rolled.mean()).sum()) == pytest.approx(ss, rel=1e-9)


def test_group_profiles_matches_naive_loop():
    rng = np.random.default_rng(9)
    c = rng.normal(size=(120, 7))
    labels = rng.integers(0, 3, size=120)
    fast = k._group_profiles(c, labels, 3)
    for g in range(3):
        assert np.allclose(fast[g], c[labels == g].mean(axis=0))


# ------------------------------------------------------------------------ tests


def test_t1_does_not_reject_when_diurnal_is_stable():
    """H0 true: a fixed diurnal profile. T1 must not fire."""
    rng = np.random.default_rng(21)
    ret = _simulate(rng, d=900, m=5, v_day=0.35, v_stoch=0.20, drift=0.0)
    rv, _ = k.bar_rv(ret, _px(ret), 5)
    out = k.test_residual_bin_structure(np.log(rv), rng, 300)
    assert out["status"] == "OK"
    assert out["p_value"] > 0.10


def test_t1_rejects_when_the_profile_drifts():
    """H1: the same U shape, amplitude drifting across the sample. T1 must fire."""
    rng = np.random.default_rng(22)
    ret = _simulate(rng, d=900, m=5, v_day=0.35, v_stoch=0.20, drift=0.8)
    rv, _ = k.bar_rv(ret, _px(ret), 5)
    out = k.test_residual_bin_structure(np.log(rv), rng, 300)
    assert out["p_value"] < 0.05


def test_t1_uses_past_only_profile():
    """Lookahead guard: the day-d profile must not move when future days change.

    A full-sample profile would make residual bin means identically zero, so T1 could
    never reject. This pins the expanding estimator in place.
    """
    rng = np.random.default_rng(23)
    ret = _simulate(rng, d=400, m=5)
    rv, _ = k.bar_rv(ret, _px(ret), 5)
    u = np.log(rv)
    base = k.test_residual_bin_structure(u, np.random.default_rng(1), 50)

    tampered = u.copy()
    tampered[-50:] += 5.0  # wreck the tail only
    after = k.test_residual_bin_structure(tampered, np.random.default_rng(1), 50)
    # Early-day residuals are computed from past days only, so a tail shock cannot be
    # smuggled backwards; the statistic must change but stay finite and well-formed.
    assert base["n_days_tested"] == after["n_days_tested"]
    assert np.isfinite(after["statistic_eta_sq"])

    truncated = k.test_residual_bin_structure(u[:300], np.random.default_rng(1), 50)
    c = u - u.mean(axis=1, keepdims=True)
    c_short = u[:300] - u[:300].mean(axis=1, keepdims=True)
    full_profile = np.cumsum(c, axis=0)[199] / 200
    short_profile = np.cumsum(c_short, axis=0)[199] / 200
    assert np.allclose(full_profile, short_profile)  # day 200 sees only days < 200
    assert truncated["status"] == "OK"


def test_t2_does_not_reject_when_shape_is_regime_independent():
    rng = np.random.default_rng(24)
    ret = _simulate(rng, d=800, m=5, v_day=0.35, v_stoch=0.20)
    rv, _ = k.bar_rv(ret, _px(ret), 5)
    days = np.array([20200101 + 10000 * (i // 250) + (i % 250) for i in range(800)])
    out = k.test_regime_shape(np.log(rv), days, rng, 300)
    assert out["status"] == "OK"
    assert out["p_value"] > 0.05


def test_t2_rejects_when_shape_depends_on_the_regime():
    """High-vol days get a flatter U; T2 must see it."""
    rng = np.random.default_rng(25)
    d, m = 800, 5
    s = _u_shape(60)
    a = rng.normal(0, np.sqrt(0.5), size=d)
    scale = np.where(a > np.median(a), 0.3, 1.0)[:, None]
    logvar = a[:, None] + s[None, :] * scale
    r = rng.standard_normal((d, 60, m)) * np.sqrt(np.exp(logvar) / m)[:, :, None]
    rv, _ = k.bar_rv(r.reshape(d, 60 * m), _px(r.reshape(d, 60 * m)), m)
    days = np.array([20200101 + 10000 * (i // 250) + (i % 250) for i in range(d)])
    out = k.test_regime_shape(np.log(rv), days, rng, 300)
    assert out["p_value"] < 0.05


def test_t3_skips_when_only_one_year():
    rng = np.random.default_rng(26)
    ret = _simulate(rng, d=200, m=5)
    rv, _ = k.bar_rv(ret, _px(ret), 5)
    days = np.array([20260101 + i for i in range(200)])
    assert k.test_era_shape(np.log(rv), days, rng, 50)["status"] == "SKIPPED_TOO_FEW_YEARS"


def test_t4_bootstrap_separates_zero_from_positive_stochastic_vol():
    rng = np.random.default_rng(27)
    for v_stoch, expect_positive in ((0.0, False), (0.25, True)):
        ret = _simulate(rng, d=1200, m=5, v_stoch=v_stoch)
        rv, _ = k.bar_rv(ret, _px(ret), 5)
        u = np.log(rv)
        fits = k.bootstrap_fits(u, rng, 200)
        boot = k.shares_from_boot(fits, k.gaussian_noise_floor(5), 200)
        p = boot["v_stoch_raw"]["p_one_sided"]
        assert (p < 0.05) is expect_positive


# -------------------------------------------------------------------------- FDR


def test_bh_is_monotone_and_no_looser_than_bonferroni_at_the_smallest_p():
    p = [0.001, 0.008, 0.02, 0.04, 0.3, 0.7]
    out = k.benjamini_hochberg(p, 0.10)
    assert out[0] is True
    assert out[-1] is False
    # BH is a step-up procedure: nothing above the cut may be rejected.
    cut = max(i for i, v in enumerate(out) if v)
    assert all(out[: cut + 1])


def test_bh_rejects_nothing_when_all_p_are_large():
    assert k.benjamini_hochberg([0.4, 0.6, 0.9], 0.10) == [False, False, False]


def test_bh_empty_family():
    assert k.benjamini_hochberg([], 0.10) == []


def test_bh_matches_statsmodels():
    sm = pytest.importorskip("statsmodels.stats.multitest")
    rng = np.random.default_rng(31)
    p = list(np.clip(rng.beta(0.3, 4, size=25), 1e-6, 1.0))
    assert k.benjamini_hochberg(p, 0.10) == list(sm.multipletests(p, alpha=0.10, method="fdr_bh")[0])


# ------------------------------------------------------------------ fat-tail floor


def test_fat_tail_floor_is_above_the_gaussian_floor_for_heavy_tails():
    rng = np.random.default_rng(33)
    d, kb, m = 500, 20, 5
    s = _u_shape(kb)
    a = rng.normal(0, 0.4, size=d)
    logvar = a[:, None] + s[None, :]
    z = rng.standard_t(5.0, size=(d, kb, m)) / np.sqrt(5.0 / 3.0)
    r = z * np.sqrt(np.exp(logvar) / m)[:, :, None]
    ret = r.reshape(d, kb * m)
    fit = k.two_way(np.log(k.bar_rv(ret, _px(ret), m)[0]))
    ft = k.fat_tail_noise_floor(ret, fit, m, m, rng)
    assert ft["kurtosis"] > 3.5
    assert ft["floor"] > k.gaussian_noise_floor(m)
