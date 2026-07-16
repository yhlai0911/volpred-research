from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


MODULE_PATH = Path(__file__).with_name("K1704.py")
SPEC = importlib.util.spec_from_file_location("k1704", MODULE_PATH)
assert SPEC and SPEC.loader
k1704 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(k1704)


def test_rv_grid_includes_session_open_and_exact_close() -> None:
    ticks = pd.DataFrame(
        {
            "trade_time": [84500, 84600, 85000, 85500, 134400, 134500],
            "price": [100.0, 101.0, 104.0, 103.0, 105.0, 106.0],
        }
    )
    for minutes in (1, 5, 10):
        observed = k1704._rv_from_ticks(ticks, minutes)
        changed = ticks.copy()
        changed.loc[changed.index[-1], "price"] = 120.0
        assert observed > 0
        assert k1704._rv_from_ticks(changed, minutes) != observed

    with_open = k1704._rv_from_ticks(ticks, 5, include_session_open=True)
    without_open = k1704._rv_from_ticks(ticks, 5, include_session_open=False)
    assert with_open != without_open


def test_pit_consensus_and_scale_ignore_current_and_future_values() -> None:
    rng = np.random.default_rng(42)
    n_obs = 800
    frame = pd.DataFrame(
        {column: np.exp(rng.normal(-8.0, 0.3, n_obs)) for column in k1704.PROXY_COLUMNS}
    )
    origin = 700
    _, weights_before, biases_before = k1704.point_in_time_composite(frame, 500, 500)
    changed = frame.copy()
    changed.loc[origin:, k1704.PROXY_COLUMNS] *= 1e8
    _, weights_after, biases_after = k1704.point_in_time_composite(changed, 500, 500)
    np.testing.assert_allclose(weights_before.loc[origin], weights_after.loc[origin])
    np.testing.assert_allclose(biases_before.loc[origin], biases_after.loc[origin])

    actual = np.exp(rng.normal(-8.0, 0.3, n_obs))
    raw = {name: np.full(n_obs, 2e-4) for name in k1704.MODEL_NAMES}
    calibrated_before, _ = k1704.calibrate_forecasts_to_target(actual, raw, 500, 500)
    changed_actual = actual.copy()
    changed_actual[origin:] *= 1e8
    calibrated_after, _ = k1704.calibrate_forecasts_to_target(changed_actual, raw, 500, 500)
    for name in k1704.MODEL_NAMES:
        assert calibrated_before[name][origin] == calibrated_after[name][origin]


def test_har_origin_is_unchanged_by_current_and_future_rv() -> None:
    rng = np.random.default_rng(7)
    frame = pd.DataFrame({"rv_5min": np.exp(rng.normal(-8.0, 0.2, 100))})
    origin = 80
    before = k1704.har_forecasts(frame, 60, 60)
    changed = frame.copy()
    changed.loc[origin:, "rv_5min"] *= 1000.0
    after = k1704.har_forecasts(changed, 60, 60)
    assert before[origin] == pytest.approx(after[origin])


def test_gjr_refit_and_non_refit_origin_alignment(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeFit:
        convergence_flag = 0
        params = pd.Series(
            {"omega": 1.0, "alpha[1]": 0.1, "gamma[1]": 0.2, "beta[1]": 0.7}
        )

        def forecast(self, horizon: int, reindex: bool) -> object:
            assert horizon == 1 and reindex is False
            variance = pd.DataFrame([[4.0]])
            return type("Forecast", (), {"variance": variance})()

    class FakeModel:
        def fit(self, **_: object) -> FakeFit:
            return FakeFit()

    monkeypatch.setattr(k1704, "arch_model", lambda *args, **kwargs: FakeModel())
    frame = pd.DataFrame({"day_return": [0.01, 0.01, 0.01, -0.01, 0.02, 0.03]})
    forecasts, audit = k1704.gjr_forecasts(frame, oos_start=3, train_window=3, refit_every=2)
    assert forecasts[3] == pytest.approx(4.0 / 10000.0)
    # Origin 4 must consume the negative return at origin 3 and h_3.
    assert forecasts[4] == pytest.approx((1.0 + 0.1 + 0.2 + 0.7 * 4.0) / 10000.0)
    assert forecasts[5] == pytest.approx(4.0 / 10000.0)
    assert audit["refit_count"] == 2


def test_common_ledger_fails_on_forecast_gap_and_is_shared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    n_obs = 300
    actuals = {
        name: np.linspace(1.0, 2.0, n_obs) for name in [*k1704.PROXY_COLUMNS, "consensus_weighted"]
    }
    actuals["r2_day"][7] = 0.0
    forecasts = {
        target: {name: np.linspace(1.1, 2.1, n_obs) for name in k1704.MODEL_NAMES}
        for target in actuals
    }
    mask = k1704.build_common_evaluation_mask(actuals, forecasts, oos_start=5)
    assert int(mask.sum()) == 294
    assert mask[7] == np.False_
    assert mask[8] == np.True_

    broken = {
        target: {name: values.copy() for name, values in model_values.items()}
        for target, model_values in forecasts.items()
    }
    broken["rv_5min"]["HAR_RV5"][8] = np.nan
    with pytest.raises(RuntimeError, match="forecast coverage failure"):
        k1704.build_common_evaluation_mask(actuals, broken, oos_start=5)

    observed_lengths: list[int] = []
    monkeypatch.setattr(k1704, "qlike_pointwise", lambda y, f: np.square(y - f))
    monkeypatch.setattr(k1704, "qlike", lambda y, f: float(np.mean(np.square(y - f))))
    monkeypatch.setattr(k1704, "spearman_corr", lambda y, f: (0.5, 0.1))
    monkeypatch.setattr(k1704, "dm_test", lambda left, right, h: (0.0, 1.0))

    def fake_mcs(losses: dict[str, np.ndarray], **_: object) -> dict[str, object]:
        observed_lengths.extend(len(values) for values in losses.values())
        return {"mcs_models": list(losses), "eliminated": [], "p_values": {}}

    monkeypatch.setattr(k1704, "model_confidence_set", fake_mcs)
    result = k1704.evaluate_target(actuals["rv_1min"], forecasts["rv_1min"], mask)
    assert result["n_oos"] == 294
    assert observed_lengths == [294, 294, 294]


def test_cached_raw_bytes_are_reverified(tmp_path: Path) -> None:
    source = tmp_path / "Daily_2026_01_02TX.csv"
    source.write_bytes(b"original bytes")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    frame = pd.DataFrame(
        {
            "source_file": [source.name],
            "source_size": [source.stat().st_size],
            "source_sha256": [digest],
        }
    )
    audit = k1704.verify_cached_source_bytes(frame, tmp_path)
    assert audit["raw_bytes_reverified"] is True

    source.write_bytes(b"mutated bytes!")
    with pytest.raises(RuntimeError, match="mismatch"):
        k1704.verify_cached_source_bytes(frame, tmp_path)
