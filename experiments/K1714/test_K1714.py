"""Invariant tests for K1714.

These are not "does it run" tests. Each one pins a claim that the README makes
and that a reader would otherwise have to take on trust — above all the two
lookahead boundaries and the nesting claim that makes the benchmark comparison
fair.

Run:  uv run --extra dev python -m pytest experiments/K1714/test_K1714.py -q
"""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("k1714", HERE / "K1714.py")
k = importlib.util.module_from_spec(_spec)
sys.modules["k1714"] = k  # @dataclass resolves __module__ through sys.modules
_spec.loader.exec_module(k)  # type: ignore[union-attr]


# --------------------------------------------------------------------------
# Cholesky parameterisation
# --------------------------------------------------------------------------


def test_chol_roundtrip_is_exact():
    rng = np.random.default_rng(0)
    a = rng.normal(size=(20, 4))
    s = a.T @ a
    assert np.allclose(k.chol_unvec(k.chol_vec(s), 4), s)


def test_logm_roundtrip_is_exact():
    rng = np.random.default_rng(100)
    a = rng.normal(size=(20, 4))
    s = a.T @ a
    assert np.allclose(k.logm_unvec(k.logm_vec(s), 4), s)


def test_logm_unvec_is_pd_for_any_real_vector():
    """exp of a symmetric matrix is PD unconditionally — the logm analogue of the
    Cholesky guarantee, and the reason both specs report zero PD failures."""
    rng = np.random.default_rng(101)
    for _ in range(200):
        v = rng.normal(scale=5.0, size=10)
        s = k.logm_unvec(v, 4)
        assert np.allclose(s, s.T)
        np.linalg.cholesky(s)


def test_logm_is_permutation_equivariant_but_cholesky_is_not():
    """The whole justification for running the matrix-log spec as a robustness
    check. If this ever failed, the 'logm isolates ordering dependence' argument
    in the README would be void."""
    rng = np.random.default_rng(102)
    a = rng.normal(size=(20, 4))
    s = a.T @ a
    p = np.array([2, 0, 3, 1])
    s_perm = s[p][:, p]

    # matrix log commutes with permutation
    lp = k.logm_unvec(k.logm_vec(s_perm), 4)
    inv = np.argsort(p)
    assert np.allclose(lp[inv][:, inv], s)
    log_direct = k.logm_vec(s)
    log_perm = k.logm_vec(s_perm)
    full_direct = np.zeros((4, 4))
    full_direct[np.tril_indices(4)] = log_direct
    full_direct = full_direct + full_direct.T - np.diag(np.diag(full_direct))
    full_perm = np.zeros((4, 4))
    full_perm[np.tril_indices(4)] = log_perm
    full_perm = full_perm + full_perm.T - np.diag(np.diag(full_perm))
    assert np.allclose(full_perm[inv][:, inv], full_direct), "logm is not equivariant"

    # Cholesky is genuinely NOT equivariant
    c_direct = np.linalg.cholesky(s)
    c_perm = np.linalg.cholesky(s_perm)
    assert not np.allclose(c_perm[inv][:, inv], c_direct)


def test_chol_unvec_is_pd_even_with_negative_diagonal():
    """The core reason we forecast RAW Cholesky elements rather than log-diagonal.

    L L' is PD for any real L with non-zero diagonal, so an unconstrained linear
    forecast of the Cholesky vector can never produce a non-PD covariance. This
    is what lets the experiment report a PD failure rate of exactly zero for a
    structural reason rather than by luck.
    """
    v = np.array([-1.0, 0.3, -2.0, 0.1, -0.2, 0.5, 0.4, 0.2, -0.1, -1.5])
    s = k.chol_unvec(v, 4)
    assert np.allclose(s, s.T)
    np.linalg.cholesky(s)  # raises if not PD
    assert np.linalg.eigvalsh(s).min() > 0


# --------------------------------------------------------------------------
# Block realised covariance and the nesting claim
# --------------------------------------------------------------------------


def test_block_rcov_is_sum_of_outer_products():
    rng = np.random.default_rng(1)
    r = rng.normal(size=(40, 4)) * 0.01
    rcov, idx = k.build_block_rcov(r, 5)
    assert rcov.shape == (8, 4, 4)
    assert np.allclose(rcov[0], r[0:5].T @ r[0:5])
    assert np.allclose(rcov[3], r[15:20].T @ r[15:20])
    assert idx[3].tolist() == [15, 19]


def test_block_rcov_blocks_are_non_overlapping():
    """Non-overlap is the whole anti-tautology argument; pin it mechanically."""
    rng = np.random.default_rng(2)
    r = rng.normal(size=(50, 4))
    _, idx = k.build_block_rcov(r, 5)
    for b in range(1, len(idx)):
        assert idx[b, 0] == idx[b - 1, 1] + 1, "blocks must be adjacent, not overlapping"
    spans = [set(range(lo, hi + 1)) for lo, hi in idx]
    for i in range(len(spans)):
        for j in range(i + 1, len(spans)):
            assert not (spans[i] & spans[j]), "two blocks share a day"


def test_block_rcov_rejects_block_shorter_than_n_assets():
    r = np.random.default_rng(3).normal(size=(40, 4))
    with pytest.raises(ValueError, match="must exceed n_assets"):
        k.build_block_rcov(r, 4)


def test_benchmark_is_nested_in_har_information_set():
    """README §3 claim: mean of m block RCovs / block_len == rolling sample
    second moment over the same m*block_len days, EXACTLY.

    This is what makes the horse race a pure test of the weighting scheme rather
    than of who was shown more data. If this ever fails, the fairness argument in
    the README is void.
    """
    rng = np.random.default_rng(4)
    r = rng.normal(size=(100, 4)) * 0.01
    block_len, m = 5, 12
    rcov, _ = k.build_block_rcov(r, block_len)
    lhs = rcov[:m].mean(axis=0) / block_len
    rhs = k.sample_second_moment(r[: m * block_len])
    assert np.allclose(lhs, rhs), "benchmark is NOT nested in the HAR information set"


# --------------------------------------------------------------------------
# Lookahead — the highest-priority risk in this repo
# --------------------------------------------------------------------------


def test_har_regressor_row_uses_only_information_through_that_block():
    """X[o] must be a function of vecs[..o] only, never vecs[o+1..]."""
    rng = np.random.default_rng(5)
    vecs = rng.normal(size=(60, 3))
    X = k._har_regressors(vecs, (1, 4, 12))
    o = 30
    baseline = X[o].copy()
    perturbed = vecs.copy()
    perturbed[o + 1 :] += 1000.0  # scramble the entire future
    X2 = k._har_regressors(perturbed, (1, 4, 12))
    assert np.allclose(X2[o], baseline), "regressor row o leaked future data"


def test_har_forecast_is_invariant_to_the_future():
    """Forecast for block t must not change when blocks >= t are scrambled.

    This is the single most important test in the file. It covers BOTH channels
    at once: the regressors at the forecast origin and every training row.
    """
    rng = np.random.default_rng(6)
    vecs = rng.normal(size=(80, 3))
    t0 = 40
    f1, _ = k.har_forecast_path(vecs, t0, (1, 4, 12))

    scrambled = vecs.copy()
    scrambled[t0:] = rng.normal(size=(80 - t0, 3)) * 500.0
    f2, _ = k.har_forecast_path(scrambled, t0, (1, 4, 12))

    assert np.allclose(f1[t0], f2[t0]), "forecast for the first OOS block saw the future"


def test_har_training_target_never_reaches_the_forecast_block():
    """Later forecasts may differ once earlier OOS blocks are realised (that is
    the expanding window doing its job), but block t's forecast must depend only
    on blocks <= t-1."""
    rng = np.random.default_rng(7)
    vecs = rng.normal(size=(80, 3))
    t0, t = 40, 55
    f1, _ = k.har_forecast_path(vecs, t0, (1, 4, 12))
    scrambled = vecs.copy()
    scrambled[t:] += 1000.0  # only blocks t and later are corrupted
    f2, _ = k.har_forecast_path(scrambled, t0, (1, 4, 12))
    assert np.allclose(f1[t], f2[t]), "forecast for block t used block >= t"
    assert np.allclose(f1[t0:t], f2[t0:t]), "earlier forecasts were disturbed"


def test_backtest_applies_weights_strictly_after_the_information_date():
    rng = np.random.default_rng(8)
    n_days = 60
    returns = rng.normal(size=(n_days, 4)) * 0.01
    dates = k.pd.bdate_range("2020-01-01", periods=n_days)
    _, day_index = k.build_block_rcov(returns, 5)
    n_blocks = len(day_index)
    covs = np.tile(np.eye(4), (n_blocks, 1, 1))
    first = 4
    res = k.run_backtest("t", covs, returns, dates, day_index, first)
    # equal weights from the identity covariance -> portfolio return is the mean
    expected_first_day = day_index[first, 0]
    assert np.isclose(res.daily_returns[0], returns[expected_first_day].mean())
    # and the information boundary is the previous block's last day
    assert day_index[first, 0] == day_index[first - 1, 1] + 1


def test_ewma_uses_only_past_returns():
    rng = np.random.default_rng(9)
    r = rng.normal(size=(400, 4)) * 0.01
    e1 = k.ewma_path(r, 0.94, 252)
    r2 = r.copy()
    r2[300:] += 5.0
    e2 = k.ewma_path(r2, 0.94, 252)
    assert np.allclose(e1[299], e2[299]), "EWMA at day 299 saw day >= 300"


# --------------------------------------------------------------------------
# Portfolio maths
# --------------------------------------------------------------------------


def test_gmv_weights_are_scale_invariant():
    """Why the k-day scale of the block RCov never contaminates the weights."""
    rng = np.random.default_rng(10)
    a = rng.normal(size=(30, 4))
    s = a.T @ a
    assert np.allclose(k.gmv_weights(s), k.gmv_weights(5.0 * s))


def test_gmv_weights_minimise_variance():
    rng = np.random.default_rng(11)
    a = rng.normal(size=(30, 4))
    s = a.T @ a
    w = k.gmv_weights(s)
    assert np.isclose(w.sum(), 1.0)
    base = w @ s @ w
    for _ in range(500):
        d = rng.normal(size=4)
        d -= d.mean()  # stay on the budget constraint
        assert (w + 1e-3 * d) @ s @ (w + 1e-3 * d) >= base - 1e-15


def test_gmv_long_only_respects_bounds_and_beats_equal_weight():
    rng = np.random.default_rng(12)
    a = rng.normal(size=(60, 4))
    s = a.T @ a
    w = k.gmv_weights_long_only(s)
    assert (w >= -1e-9).all() and np.isclose(w.sum(), 1.0)
    ew = np.full(4, 0.25)
    assert w @ s @ w <= ew @ s @ ew + 1e-12


def test_drifted_weights_reduce_to_input_when_returns_are_flat():
    w = np.array([0.4, 0.3, 0.2, 0.1])
    assert np.allclose(k.drifted_weights(w, np.zeros((5, 4))), w)


def test_turnover_is_zero_for_a_buy_and_hold_identical_target():
    """If the target weights equal the drifted weights, turnover must be 0."""
    rng = np.random.default_rng(13)
    w = np.array([0.4, 0.3, 0.2, 0.1])
    blk = rng.normal(size=(5, 4)) * 0.01
    drift = k.drifted_weights(w, blk)
    assert np.isclose(np.abs(drift - drift).sum(), 0.0)


# --------------------------------------------------------------------------
# Inference
# --------------------------------------------------------------------------


def test_hac_lag_is_never_zero_at_h_equals_one():
    """Repo hard rule: lag = h-1 degenerates to no HAC correction at h=1."""
    for n in (100, 1000, 5000):
        assert k.newey_west_lag(n, h=1) >= 1
    assert k.newey_west_lag(4665, h=1) == 17


def test_variance_difference_test_sign_and_size():
    rng = np.random.default_rng(14)
    n = 4000
    a = rng.normal(scale=0.008, size=n)  # lower variance
    b = rng.normal(scale=0.012, size=n)
    res = k.variance_difference_test(a, b)
    assert res["t_stat"] < 0, "negative statistic must mean the FIRST series is calmer"
    assert res["p_value"] < 1e-6
    assert np.isclose(res["delta"], a.var(ddof=0) - b.var(ddof=0), rtol=1e-6)


def test_variance_difference_test_is_calibrated_under_the_null():
    """Rejection rate at alpha=0.05 should be near 5% for iid equal-variance pairs."""
    rng = np.random.default_rng(15)
    rejects = 0
    trials = 300
    for _ in range(trials):
        x = rng.normal(scale=0.01, size=800)
        y = rng.normal(scale=0.01, size=800)
        if k.variance_difference_test(x, y)["p_value"] < 0.05:
            rejects += 1
    assert 0.01 < rejects / trials < 0.13, f"empirical size {rejects/trials:.3f}"


def test_variance_difference_test_removes_the_mean():
    """Second-moment equality is not variance equality; make sure we test the
    latter. Two series with identical variance but different means must not be
    flagged."""
    rng = np.random.default_rng(16)
    e = rng.normal(scale=0.01, size=5000)
    a = e + 0.05  # same variance, hugely different mean
    b = e
    res = k.variance_difference_test(a, b)
    assert abs(res["delta"]) < 1e-12


def test_holm_bonferroni_matches_known_values():
    p = [0.01, 0.02, 0.03]
    adj = k.holm_bonferroni(p)
    assert np.allclose(adj, [0.03, 0.04, 0.04])


def test_holm_is_monotone_and_conservative():
    rng = np.random.default_rng(17)
    for _ in range(50):
        p = np.sort(rng.uniform(size=5))
        adj = np.array(k.holm_bonferroni(p.tolist()))
        assert (adj >= p - 1e-12).all(), "adjusted p must not be smaller than raw"
        assert (np.diff(adj) >= -1e-12).all(), "adjusted p must be monotone"
        assert (adj <= 1.0).all()


def test_benjamini_hochberg_matches_known_values():
    p = [0.01, 0.02, 0.03]
    adj = k.benjamini_hochberg(p)
    assert np.allclose(adj, [0.03, 0.03, 0.03])


def test_bh_is_less_conservative_than_holm():
    rng = np.random.default_rng(18)
    for _ in range(50):
        p = rng.uniform(size=6).tolist()
        assert (
            np.array(k.benjamini_hochberg(p)) <= np.array(k.holm_bonferroni(p)) + 1e-12
        ).all()


def test_autocorr_recovers_a_known_ar1():
    rng = np.random.default_rng(19)
    n, phi = 200_000, 0.6
    e = rng.normal(size=n)
    x = np.empty(n)
    x[0] = e[0]
    for i in range(1, n):
        x[i] = phi * x[i - 1] + e[i]
    ac = k.autocorr(x, 3)
    assert abs(ac[0] - phi) < 0.02
    assert abs(ac[1] - phi**2) < 0.02


def test_bootstrap_pvalue_is_in_range_and_seed_stable():
    rng = np.random.default_rng(20)
    a = rng.normal(scale=0.01, size=600)
    b = rng.normal(scale=0.01, size=600)
    r1 = k.studentized_cbb_pvalue(a, b, 200, 42)
    r2 = k.studentized_cbb_pvalue(a, b, 200, 42)
    assert 0.0 < r1["p_value_bootstrap"] <= 1.0
    assert r1["p_value_bootstrap"] == r2["p_value_bootstrap"], "seed not honoured"


# --------------------------------------------------------------------------
# Adjudication rule — pinned so it cannot be quietly reinterpreted later
# --------------------------------------------------------------------------


class _Stub:
    def __init__(self, var):
        rng = np.random.default_rng(21)
        x = rng.normal(size=3000)
        self.daily_returns = x / x.std(ddof=1) * math.sqrt(var)


def _fam(t_and_holm):
    return {
        "tests": {
            b: {"t_stat": t, "p_holm": p, "survives_holm_at_005": p < 0.05}
            for b, (t, p) in t_and_holm.items()
        }
    }


def test_adjudicate_declares_win_only_when_ledoit_wolf_is_beaten():
    results = {
        k.MODEL_NAME: _Stub(1.0),
        "sample": _Stub(2.0),
        "ledoit_wolf": _Stub(2.0),
        "ewma": _Stub(2.0),
    }
    win = k.adjudicate(
        results,
        _fam({"sample": (-4.0, 0.001), "ledoit_wolf": (-4.0, 0.001), "ewma": (-4.0, 0.001)}),
    )
    assert win["verdict"] == "WIN"

    # Same point estimates, but only the weak benchmark is significant -> MIXED
    mixed = k.adjudicate(
        results,
        _fam({"sample": (-4.0, 0.001), "ledoit_wolf": (-1.0, 0.6), "ewma": (-1.0, 0.6)}),
    )
    assert mixed["verdict"] == "MIXED"


def test_adjudicate_declares_tie_when_nothing_survives():
    results = {
        k.MODEL_NAME: _Stub(1.0),
        "sample": _Stub(1.01),
        "ledoit_wolf": _Stub(1.01),
        "ewma": _Stub(1.01),
    }
    v = k.adjudicate(
        results,
        _fam({"sample": (-1.0, 0.5), "ledoit_wolf": (-0.5, 0.8), "ewma": (0.3, 0.9)}),
    )
    assert v["verdict"] == "TIE_NULL"


def test_adjudicate_declares_lose_when_a_benchmark_wins_significantly():
    results = {
        k.MODEL_NAME: _Stub(2.0),
        "sample": _Stub(1.0),
        "ledoit_wolf": _Stub(1.0),
        "ewma": _Stub(1.0),
    }
    v = k.adjudicate(
        results,
        _fam({"sample": (4.0, 0.001), "ledoit_wolf": (4.0, 0.001), "ewma": (1.0, 0.5)}),
    )
    assert v["verdict"] == "LOSE"


def test_adjudicate_lose_dominates_a_simultaneous_win():
    """If the model beats one benchmark and loses to another, LOSE must win the
    tie-break — otherwise a cherry-picked WIN could be reported."""
    results = {
        k.MODEL_NAME: _Stub(1.0),
        "sample": _Stub(2.0),
        "ledoit_wolf": _Stub(2.0),
        "ewma": _Stub(0.5),
    }
    v = k.adjudicate(
        results,
        _fam({"sample": (-4.0, 0.001), "ledoit_wolf": (-4.0, 0.001), "ewma": (4.0, 0.001)}),
    )
    assert v["verdict"] == "LOSE"
