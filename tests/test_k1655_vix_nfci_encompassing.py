from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "experiments" / "K1655" / "K1655_vix_nfci_encompassing.py"
SPEC = importlib.util.spec_from_file_location("k1655_vix_nfci_test_module", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_offline_loader_never_uses_network(monkeypatch):
    def blocked(*_args, **_kwargs):
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(MODULE.BASE.requests, "get", blocked)
    monkeypatch.setattr(MODULE.BASE.yf, "download", blocked)
    manifest = MODULE.frozen_manifest()
    panel = MODULE.load_frozen_panel(manifest)
    assert len(panel) == 788
    assert str(panel.index.min().date()) == "2011-05-27"
    assert str(panel.index.max().date()) == "2026-06-26"
    assert all(panel.attrs["timing_gates"].values())


def test_frozen_manifest_rejects_forecast_hash_drift(monkeypatch):
    original = MODULE.sha256_file

    def drift(path):
        if Path(path) == MODULE.BASE_FORECASTS:
            return "0" * 64
        return original(Path(path))

    monkeypatch.setattr(MODULE, "sha256_file", drift)
    with pytest.raises(RuntimeError, match="forecast artifact hash drift"):
        MODULE.frozen_manifest()


def test_frozen_pairs_are_exact_and_loss_recomputes():
    paired = MODULE.load_frozen_expanding_pairs()
    assert paired.groupby("horizon_weeks").size().to_dict() == {1: 536, 4: 530, 12: 514}
    assert not paired.duplicated(["horizon_weeks", "origin"]).any()
    for forecast, loss in (("q_nfci", "loss_nfci"), ("q_vix", "loss_vix")):
        recomputed = MODULE.BASE.pinball_loss(
            paired["realized"].to_numpy(float), paired[forecast].to_numpy(float), MODULE.TAU
        )
        np.testing.assert_allclose(recomputed, paired[loss], rtol=0, atol=2e-15)


def test_paired_loss_direction_is_candidate_minus_benchmark():
    rng = np.random.default_rng(7)
    benchmark = 1.0 + rng.uniform(0.0, 0.4, size=300)
    candidate = benchmark - 0.2 + rng.normal(0.0, 0.03, size=300)
    result = MODULE.paired_loss_test(
        candidate,
        benchmark,
        1,
        candidate_name="candidate",
        benchmark_name="benchmark",
    )
    assert result["candidate_better"] is True
    assert result["mean_loss_differential_candidate_minus_benchmark"] < 0
    assert result["canonical_dm_t"] < -3
    assert result["harvey_t_better_gate"] is True


def _synthetic_panel(n: int = 80) -> pd.DataFrame:
    index = pd.date_range("2020-01-03", periods=n, freq="W-FRI")
    rng = np.random.default_rng(11)
    returns = rng.normal(0.001, 0.02, size=n)
    close = 100 * np.exp(np.cumsum(returns))
    nfci = np.sin(np.arange(n) / 9.0) + rng.normal(0, 0.05, n)
    vix = 20 + 3 * np.cos(np.arange(n) / 7.0) + rng.normal(0, 0.2, n)
    frame = pd.DataFrame(
        {
            "wclose": close,
            "wrv": returns**2,
            "nfci": nfci,
            "vix": vix,
            "nfci_obs_date": index - pd.Timedelta(days=7),
            "nfci_realtime_start": index - pd.Timedelta(days=2),
            "nfci_realtime_end": pd.NaT,
        },
        index=index,
    )
    return frame


def test_rolling_forecasts_have_exact_counts_and_strict_embargo():
    MODULE._reset_fit_diagnostics()
    panel = _synthetic_panel()
    forecasts = MODULE.rolling_forecasts(panel, 20, include_nfci_only=True)
    expected = {h: len(panel) - 20 - 2 * h for h in MODULE.HORIZONS}
    assert forecasts.groupby("horizon_weeks").size().to_dict() == expected
    assert (forecasts["latest_training_target_end"] < forecasts["origin"]).all()
    assert (forecasts["target_end"] > forecasts["origin"]).all()
    assert {"q_nfci", "q_vix", "q_vix_nfci"}.issubset(forecasts.columns)
    assert {"scale_mean_vix_nfci_vix", "scale_mean_vix_nfci_nfci"}.issubset(
        forecasts.columns
    )


def test_cqfe_covariance_is_finite_on_identified_synthetic_forecasts():
    rng = np.random.default_rng(19)
    n = 350
    q_vix = rng.normal(-0.04, 0.01, n)
    q_joint = q_vix + rng.normal(0, 0.006, n)
    y = 0.1 * q_vix + 0.9 * q_joint + rng.standard_t(df=6, size=n) * 0.015
    MODULE._reset_fit_diagnostics()
    x = np.column_stack([q_vix, q_joint])
    fitted = MODULE.BASE.fit_quantreg(x, y, MODULE.TAU)
    covariance, audit = MODULE.cqfe_covariance(fitted, x, y, MODULE.TAU, lag=8)
    assert covariance.shape == (3, 3)
    assert np.isfinite(covariance).all()
    assert audit["standardized_design_condition_number"] < MODULE.CONDITION_NUMBER_GATE


def test_circular_block_indices_are_deterministic_and_valid():
    first = MODULE._circular_block_indices(17, 5, np.random.default_rng(23))
    second = MODULE._circular_block_indices(17, 5, np.random.default_rng(23))
    np.testing.assert_array_equal(first, second)
    assert len(first) == 17
    assert first.min() >= 0 and first.max() < 17


def test_holm_family_cannot_promote_a_large_p_value():
    family = {
        1: {"p": 0.001},
        4: {"p": 0.04},
        12: {"p": 0.40},
    }
    MODULE.apply_holm_family(family, "p")
    assert family[1]["p_holm_below_0_05"] is True
    assert family[12]["p_holm_below_0_05"] is False
    assert family[12]["p_holm"] >= family[12]["p"]
