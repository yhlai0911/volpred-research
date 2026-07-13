"""Regression gates added by the K1702 primary-path Codex re-review."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from experiments.k1702.k1702 import (
    annualized_metrics,
    circular_shift_drawdown_randomization,
    holm_bonferroni,
)


def test_drawdown_includes_initial_wealth() -> None:
    returns = pd.Series([-0.20] + [0.0] * 11)
    assert math.isclose(annualized_metrics(returns)["max_drawdown"], -0.20)


def test_complete_phase_enumeration_uses_exact_p() -> None:
    index = pd.period_range("2000-01", periods=24, freq="M")
    returns = pd.Series(
        [0.02, -0.01, 0.03, -0.04, 0.01, -0.02] * 4, index=index,
    )
    weights = pd.Series(np.linspace(0.2, 1.4, len(index)), index=index)

    result = circular_shift_drawdown_randomization(returns, weights, cost_bps=25)

    gaps = result["null_exposure_matched_gaps"]
    observed = result["observed_exposure_matched_gap"]
    exceedances = sum(gap >= observed for gap in gaps)
    assert len(gaps) == result["n_months_and_shifts"] == 24
    assert math.isclose(result["one_sided_p"], exceedances / 24)


def test_holm_adjustment_is_monotone_in_sorted_p_values() -> None:
    raw = {"a": 0.01, "b": 0.03, "c": 0.20}
    adjusted = holm_bonferroni(raw)
    assert adjusted == {"a": 0.03, "b": 0.06, "c": 0.20}

