"""Canonical sign regression for strategy variance-risk DM comparisons."""

import numpy as np

from volpred.stats.model_evaluation import dm_test, strategy_dm_test


def test_variance_risk_delegates_to_positive_squared_return_losses() -> None:
    returns1 = np.array([0.03, -0.02, 0.01, -0.04] * 40, dtype=float)
    returns2 = np.array([0.01, -0.01, 0.02, -0.01] * 40, dtype=float)

    actual = strategy_dm_test(returns1, returns2, h=1, loss_fn="variance_risk")
    expected = dm_test(returns1**2, returns2**2, h=1)

    np.testing.assert_allclose(actual, expected, rtol=0.0, atol=1e-15)
    assert actual[0] > 0.0


def test_legacy_squared_return_option_keeps_its_opposite_sign() -> None:
    returns1 = np.array([0.03, -0.02, 0.01, -0.04] * 40, dtype=float)
    returns2 = np.array([0.01, -0.01, 0.02, -0.01] * 40, dtype=float)

    variance_risk_t, _ = strategy_dm_test(
        returns1, returns2, h=1, loss_fn="variance_risk"
    )
    legacy_t, _ = strategy_dm_test(
        returns1, returns2, h=1, loss_fn="squared_return"
    )

    assert np.isclose(legacy_t, -variance_risk_t, rtol=0.0, atol=1e-15)
