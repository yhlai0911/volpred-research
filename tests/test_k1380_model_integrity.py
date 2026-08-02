from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import optimize

from volpred.models.garch.fixed_span_midas import (
    build_fixed_span_midas_panel,
    fixed_span_log_vix_lags,
    forecast_fixed_span_garch_midas,
)
from volpred.research.optimization import bounded_multistart_minimize

ROOT = Path(__file__).resolve().parents[1]
BASE_SCRIPT = ROOT / "experiments/K1380_v4/k1380_v4.py"
CORRECTION_SCRIPT = ROOT / "experiments/K1380_v4/k1380_v4_rc_correction.py"
PIPELINE_SCRIPT = ROOT / "experiments/K1380_v4/run_pipeline.py"


def test_bounded_multistart_fit_cannot_accept_a5s_reversed_vix_slope() -> None:
    """The old K1380 outer fit selected theta_1=-0.351 despite theta_1>0."""

    def objective(params: np.ndarray) -> float:
        theta_0, theta_1 = params
        return float((theta_0 + 2.474) ** 2 + (theta_1 + 0.351) ** 2)

    fit = bounded_multistart_minimize(
        objective,
        starts=[(0.0, 0.05), (-0.5, 0.1)],
        bounds=[(-5.0, 5.0), (0.001, 1.0)],
    )

    assert fit.params[1] >= 0.001
    assert np.isclose(fit.params[1], 0.001, atol=1e-8)
    assert fit.optimizer_success is True


def test_bounded_multistart_rejects_failed_iterate_even_when_objective_is_lower(
    monkeypatch,
) -> None:
    results = iter(
        [
            optimize.OptimizeResult(
                x=np.array([0.2]), fun=-100.0, success=False, nit=2, message="failed"
            ),
            optimize.OptimizeResult(
                x=np.array([0.7]), fun=1.0, success=True, nit=3, message="converged"
            ),
        ]
    )
    monkeypatch.setattr(optimize, "minimize", lambda *args, **kwargs: next(results))

    fit = bounded_multistart_minimize(
        lambda params: float(params[0] ** 2),
        starts=[(0.2,), (0.7,)],
        bounds=[(0.0, 1.0)],
    )

    np.testing.assert_allclose(fit.params, [0.7])
    assert fit.objective == 1.0


def test_fixed_span_panel_aligns_every_daily_return_to_prior_months() -> None:
    dates = pd.bdate_range("2024-01-02", "2024-06-28")
    returns = np.linspace(-0.02, 0.02, len(dates))
    vix = np.array([10.0 + date.month for date in dates])

    panel = build_fixed_span_midas_panel(
        returns=returns,
        return_dates=dates,
        vix_history=vix,
        vix_history_dates=dates,
        lag_months=2,
        min_observations=1,
    )

    expected_start = int(np.flatnonzero(dates.to_period("M") == pd.Period("2024-03"))[0])
    assert panel.valid_start == expected_start
    assert panel.returns.shape == (len(dates) - expected_start,)
    assert panel.log_vix_lags.shape == (len(dates) - expected_start, 2)

    march_rows = panel.dates.to_period("M") == pd.Period("2024-03")
    expected = np.log([12.0, 11.0])  # February, then January
    np.testing.assert_allclose(panel.log_vix_lags[march_rows], np.tile(expected, (march_rows.sum(), 1)))


def test_fixed_span_panel_uses_full_vix_history_when_return_window_starts_midmonth() -> None:
    history_dates = pd.bdate_range("2024-01-02", "2024-06-28")
    history_vix = np.array([10.0 + date.month for date in history_dates])
    return_mask = history_dates >= pd.Timestamp("2024-03-15")
    return_dates = history_dates[return_mask]
    returns = np.linspace(-0.02, 0.02, return_mask.sum())

    panel = build_fixed_span_midas_panel(
        returns=returns,
        return_dates=return_dates,
        vix_history=history_vix,
        vix_history_dates=history_dates,
        lag_months=2,
        min_observations=1,
    )

    assert panel.dates[0] == pd.Timestamp("2024-03-15")
    np.testing.assert_allclose(panel.log_vix_lags[0], np.log([12.0, 11.0]))


def test_fixed_span_forecast_excludes_partial_current_month_vix() -> None:
    dates = pd.bdate_range("2024-01-02", "2024-06-14")
    baseline = np.array([10.0 + date.month for date in dates])
    shocked = baseline.copy()
    shocked[dates.to_period("M") == pd.Period("2024-06")] = 99.0

    baseline_lags = fixed_span_log_vix_lags(
        history_vix=baseline,
        history_dates=dates,
        forecast_date=pd.Timestamp("2024-06-17"),
        lag_months=3,
    )
    shocked_lags = fixed_span_log_vix_lags(
        history_vix=shocked,
        history_dates=dates,
        forecast_date=pd.Timestamp("2024-06-17"),
        lag_months=3,
    )

    np.testing.assert_allclose(shocked_lags, baseline_lags)
    np.testing.assert_allclose(baseline_lags, np.log([15.0, 14.0, 13.0]))


def test_fixed_span_state_uses_forecast_month_tau_per_equation_four() -> None:
    params = np.array([-4.0, 1.0, 2.0, 0.10, 0.20, 0.60])

    forecast = forecast_fixed_span_garch_midas(
        params=params,
        g_previous=1.2,
        previous_return=-0.10,
        log_vix_lags=np.log(np.array([20.0, 18.0])),
    )

    intercept = 1.0 - 0.10 - 0.20 / 2.0 - 0.60
    scaled_previous = -0.10 / np.sqrt(forecast.tau)
    expected_g = (
        intercept
        + 0.10 * scaled_previous**2
        + 0.20 * scaled_previous**2
        + 0.60 * 1.2
    )
    assert np.isclose(forecast.g, expected_g)


def test_base_producer_does_not_emit_known_false_spa_or_rc_labels() -> None:
    source = BASE_SCRIPT.read_text(encoding="utf-8")

    for forbidden in (
        '"hansen_spa_test"',
        '"white_rc_test"',
        '"c3_verdict"',
        "survives multiple testing",
    ):
        assert forbidden not in source

    assert '"legacy_raw_scale_joint_diagnostic"' in source
    assert '"a4f_single_spec_bootstrap_dm"' in source


def test_b_series_optimizer_uses_canonical_fail_closed_helper() -> None:
    source = BASE_SCRIPT.read_text(encoding="utf-8")
    start = source.index("def fit_midas(")
    end = source.index("\n\n# ", start)
    implementation = source[start:end]

    assert "bounded_multistart_minimize" in implementation
    assert "optimize.minimize" not in implementation
    assert "except Exception" not in implementation


def test_scheduled_refit_clears_stale_state_before_every_model_fit() -> None:
    source = BASE_SCRIPT.read_text(encoding="utf-8")

    assert "states[spec_name] = {}" in source
    assert "states[bspec] = {}" in source
    assert "states[cspec] = {}" in source
    assert "states['B0'] = {}" in source
    assert "'B1', 'B2', 'B3'" in source
    assert "no successful finite in-bounds optimizer result" in source


def test_one_canonical_pipeline_owns_full_chain_reproduce_spec() -> None:
    base_source = BASE_SCRIPT.read_text(encoding="utf-8")
    correction_source = CORRECTION_SCRIPT.read_text(encoding="utf-8")
    pipeline_source = PIPELINE_SCRIPT.read_text(encoding="utf-8")

    assert "finalize_experiment" not in base_source
    assert "finalize_experiment" not in correction_source
    assert "finalize_experiment" in pipeline_source
    assert "_run_child(BASE_SCRIPT)" in pipeline_source
    assert "_run_child(CORRECTION_SCRIPT)" in pipeline_source
    assert 'outputs=["k1380_v4_results.json", "k1380_v4_losses_all.npy"]' in pipeline_source


def test_archived_k1380_artifacts_enforce_the_corrected_inference_contract() -> None:
    experiment_dir = ROOT / "experiments/K1380_v4"
    base = json.loads((experiment_dir / "k1380_v4_results.json").read_text())
    corrected = json.loads(
        (experiment_dir / "k1380_v4_rc_correction_results.json").read_text()
    )
    spec = json.loads((experiment_dir / "reproduce_spec.json").read_text())

    assert {"hansen_spa_test", "white_rc_test", "c3_verdict"}.isdisjoint(base)
    assert base["c3_status"] == "PENDING_CANONICAL_CORRECTION_ARTIFACT"
    assert {"elapsed_seconds", "timestamp"}.isdisjoint(base["metadata"])
    assert spec["entrypoint"]["path"] == "run_pipeline.py"
    assert spec["runtime"]["runtime_seconds"] > 1_000

    bootstrap_draws = corrected["provenance"]["bootstrap_B"]
    minimum_p = 1.0 / (bootstrap_draws + 1)
    spa = corrected["hansen_spa_corrected"]
    assert spa["primary_pval"] >= minimum_p
    assert corrected["white_rc_corrected"]["pval"] >= minimum_p
    assert all(value > 0.0 for value in spa["long_run_omega"].values())

    for model in ("A5", "B1", "B2", "B3", "C1", "C2", "C3", "B0"):
        receipts = base["fit_diagnostics"][model]
        assert len(receipts) == 31
        assert all(
            receipt.get("optimizer_contract") == "successful_finite_in_bounds"
            or receipt.get("status") == "rejected"
            for receipt in receipts
        )


def test_canonical_correction_does_not_hardcode_superseded_c3_claims() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "experiments"
        / "K1380_v4"
        / "k1380_v4_rc_correction.py"
    ).read_text(encoding="utf-8")

    forbidden = (
        "p=0.2886, non-rejecting",
        "A5 t=-11.2",
        "C2 t=-21.1",
        "significant after RC correction",
    )
    assert all(claim not in source for claim in forbidden)
