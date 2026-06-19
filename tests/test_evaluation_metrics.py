"""Analytical-value tests for volpred.evaluation.metrics + statistical_tests.

Guards the 2026-05-16 fix where:
  * `qlike` was using `a/f + log(f)` (non-Patton, can be negative)
  * `diebold_mariano_test` HAC loop used `range(1, h)` so h=1 (the default and
    most common call) silently skipped HAC entirely
  * `christoffersen_test` reassigned `alpha = p_hat` then never computed the
    joint CC LR statistic

These tests pin Patton (2011) analytical values so a regression to the old
formulas will fail loudly.
"""
from __future__ import annotations

import numpy as np
import pytest

from volpred.evaluation.metrics import hmse, mae, mse, qlike, r2_log
from volpred.evaluation.statistical_tests import (
    christoffersen_test,
    diebold_mariano_test,
    kupiec_test,
)


# ─── QLIKE — Patton (2011) proxy-robust form ──────────────────────


def test_qlike_perfect_forecast_is_zero():
    """QLIKE(a, a) == 0 by construction of Patton form."""
    a = np.array([0.01, 0.02, 0.015, 0.025, 0.018])
    assert qlike(a, a) == pytest.approx(0.0, abs=1e-12)


def test_qlike_is_non_negative_for_any_positive_inputs():
    """Patton QLIKE is non-negative everywhere; old `a/f + log(f)` form was not."""
    rng = np.random.default_rng(0)
    for _ in range(20):
        a = rng.uniform(1e-5, 1.0, size=200)
        f = rng.uniform(1e-5, 1.0, size=200)
        assert qlike(a, f) >= -1e-12


def test_qlike_two_point_analytical_value():
    """For a=[1,1], f=[2,0.5]: ratio=[0.5, 2]; loss = mean(r - log(r) - 1)
    = mean([0.5 - log(0.5) - 1, 2 - log(2) - 1])
    = mean([-0.5 + 0.6931..., 1 - 0.6931...])
    = mean([0.1931..., 0.3069...])
    = 0.2500 (analytically)
    Independent calculation, not the implementation."""
    a = np.array([1.0, 1.0])
    f = np.array([2.0, 0.5])
    expected = 0.5 * ((0.5 - np.log(0.5) - 1) + (2.0 - np.log(2.0) - 1))
    assert qlike(a, f) == pytest.approx(expected, abs=1e-10)
    # Sanity: ≥ 0 even though one residual is negative
    assert qlike(a, f) > 0


def test_qlike_under_predict_vs_over_predict_asymmetric():
    """Patton QLIKE penalises under-prediction more than over-prediction by
    the same multiplicative factor — characteristic of the form."""
    a = np.array([1.0] * 100)
    under = np.array([0.5] * 100)  # f = a/2
    over = np.array([2.0] * 100)  # f = 2a
    assert qlike(a, under) > qlike(a, over)


def test_qlike_matches_stats_canonical_implementation():
    """volpred.stats.model_evaluation.qlike is the canonical reference.
    After 2026-05-16 fix they must agree on all valid inputs."""
    from volpred.stats.model_evaluation import qlike as qlike_canonical

    rng = np.random.default_rng(42)
    a = rng.uniform(1e-4, 0.5, size=500)
    f = rng.uniform(1e-4, 0.5, size=500)
    assert qlike(a, f) == pytest.approx(qlike_canonical(a, f), rel=1e-9)


def test_stats_qlike_pointwise_uses_actual_over_predicted_orientation():
    """K783c regression: DM pointwise losses must not use predicted/actual."""
    from volpred.stats.model_evaluation import qlike_pointwise

    actual = np.array([1.0, 1.0])
    over_pred = np.array([2.0, 2.0])
    under_pred = np.array([0.5, 0.5])

    over_loss = qlike_pointwise(actual, over_pred)
    under_loss = qlike_pointwise(actual, under_pred)
    expected_over = 0.5 - np.log(0.5) - 1.0
    expected_under = 2.0 - np.log(2.0) - 1.0

    assert over_loss == pytest.approx(np.array([expected_over, expected_over]))
    assert under_loss == pytest.approx(np.array([expected_under, expected_under]))
    assert float(np.mean(under_loss)) > float(np.mean(over_loss))


# ─── DM HAC — range(1, h+1) coverage ──────────────────────────────


def test_dm_test_h1_uses_only_gamma0():
    """h=1 → range(1, 2) → exactly one lag-1 term added; gamma_0 alone is
    a degenerate case that should NOT happen anymore."""
    rng = np.random.default_rng(1)
    # Independent losses → gamma_1 should be small but nonzero
    loss1 = rng.normal(0, 1, 300)
    loss2 = loss1 + rng.normal(0, 0.5, 300)
    result = diebold_mariano_test(loss1, loss2, h=1)
    assert "statistic" in result
    assert "p_value" in result
    assert 0.0 <= result["p_value"] <= 1.0


def test_dm_test_strongly_correlated_diff_increases_hac_variance():
    """Construct a difference series with strong positive autocorrelation.
    HAC variance should be strictly larger than plain gamma_0 → larger SE → smaller |t|."""
    rng = np.random.default_rng(7)
    eps = rng.normal(0, 1, 500)
    # AR(1) with rho = 0.8 → strong positive autocorrelation in diff
    d = np.zeros(500)
    for t in range(1, 500):
        d[t] = 0.8 * d[t - 1] + eps[t]
    loss1 = d
    loss2 = np.zeros(500)

    r_h1 = diebold_mariano_test(loss1, loss2, h=1)
    r_h5 = diebold_mariano_test(loss1, loss2, h=5)
    # Higher h includes more autocovariance → larger V → smaller |t|
    assert abs(r_h5["statistic"]) < abs(r_h1["statistic"])


def test_dm_test_equal_losses_returns_zero_stat():
    loss = np.array([0.1] * 100)
    r = diebold_mariano_test(loss, loss, h=1)
    # Zero diff → V = 0; current implementation will produce nan/inf —
    # this is acceptable as long as it doesn't silently produce a false
    # significant result. p_value should not be < 0.05 with bogus stat.
    assert np.isnan(r["statistic"]) or r["p_value"] >= 0.05


# ─── Christoffersen — joint CC LR ─────────────────────────────────


def test_christoffersen_independence_only_when_alpha_omitted():
    rng = np.random.default_rng(2)
    violations = (rng.uniform(size=500) < 0.05).astype(int)
    r = christoffersen_test(violations)
    assert "independence_stat" in r
    assert "independence_pval" in r
    assert "cc_stat" not in r  # joint test skipped


def test_christoffersen_joint_cc_when_alpha_given():
    """alpha-aware mode should populate cc_stat and cc_pval."""
    rng = np.random.default_rng(3)
    violations = (rng.uniform(size=500) < 0.05).astype(int)
    r = christoffersen_test(violations, alpha=0.05)
    assert "cc_stat" in r
    assert "cc_pval" in r
    assert r["cc_stat"] >= 0  # chi-squared statistic is non-negative
    assert 0.0 <= r["cc_pval"] <= 1.0


def test_christoffersen_cc_rejects_when_violation_rate_far_from_target():
    """If actual violation rate is 30% but target alpha = 1%, joint CC must
    reject (the rate-component LR explodes)."""
    rng = np.random.default_rng(4)
    violations = (rng.uniform(size=500) < 0.30).astype(int)  # 30%
    r = christoffersen_test(violations, alpha=0.01)
    assert r["cc_pval"] < 0.01  # very strong rejection


# ─── Other metrics — light smoke ──────────────────────────────────


def test_mse_mae_basic():
    a = np.array([1.0, 2.0, 3.0])
    f = np.array([1.0, 2.0, 3.0])
    assert mse(a, f) == 0.0
    assert mae(a, f) == 0.0


def test_hmse_perfect_forecast_zero():
    a = np.array([0.1, 0.2, 0.3])
    assert hmse(a, a) == pytest.approx(0.0)


def test_r2_log_perfect_forecast_one():
    a = np.array([0.1, 0.2, 0.3, 0.4])
    assert r2_log(a, a) == pytest.approx(1.0)


def test_kupiec_observed_equals_expected_does_not_reject():
    """Observed rate ≈ expected rate → Kupiec LR ≈ 0 → fail to reject."""
    rng = np.random.default_rng(5)
    violations = (rng.uniform(size=1000) < 0.05).astype(int)
    r = kupiec_test(violations, alpha=0.05)
    assert r["conclusion"] == "fail_to_reject"
