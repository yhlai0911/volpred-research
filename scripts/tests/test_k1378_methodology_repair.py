"""Regression coverage for the K1378 methodology and provenance repair."""

from __future__ import annotations

import importlib.util
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "experiments" / "k1378" / "k1378.py"


@pytest.fixture(scope="module")
def k1378():
    spec = importlib.util.spec_from_file_location("k1378_repair_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_actual_first_qlike_and_canonical_hac_are_pinned() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "qlike_pointwise(actual_oos, forecast_gjr)" in source
    assert "qlike_pointwise(actual_oos, forecast_a4f)" in source
    assert "canonical_dm_test(a4f, gjr, h=HORIZON)" in source
    assert "def dm_test(" not in source
    assert "range(1, h)" not in source


def test_pinned_input_is_unique_fixed_and_reproduces_oos_counts(k1378) -> None:
    frame, metadata = k1378.load_analysis_data()
    assert metadata["snapshot_sha256"] == k1378.EXPECTED_SNAPSHOT_SHA256
    assert frame.index.is_monotonic_increasing
    assert not frame.index.has_duplicates
    oos = frame.loc[k1378.OOS_START : k1378.OOS_END]
    actual = oos["log_ret"].to_numpy() ** 2
    assert len(oos) == 1854
    assert int(np.sum(actual > 1e-16)) == 1852
    assert [
        str(value.date()) for value in oos.index[actual <= 1e-16]
    ] == ["2022-08-11", "2023-07-21"]


def test_a4f_forecast_uses_vix_t_minus_1_not_vix_t(k1378, monkeypatch) -> None:
    monkeypatch.setattr(
        k1378,
        "fit_gjr",
        lambda returns: np.array([1e-5, 0.05, 0.05, 0.85]),
    )
    a4f_params = np.array([1e-4, 1e-7, 0.05, 0.05, 0.05, 0.80])
    monkeypatch.setattr(
        k1378,
        "fit_a4f",
        lambda returns, log_vix: a4f_params.copy(),
    )
    returns = np.array([0.01, -0.02, 0.015, -0.01, 0.012, -0.008, 0.4])
    vix = np.array([18.0, 19.0, 17.0, 20.0, 21.0, 22.0, 999.0])
    indices = np.array([6])

    _, baseline, _ = k1378.rolling_forecasts(
        returns, vix, indices, time.time()
    )
    target_vix_changed = vix.copy()
    target_vix_changed[6] = 1.0
    _, target_changed, _ = k1378.rolling_forecasts(
        returns, target_vix_changed, indices, time.time()
    )
    lagged_vix_changed = vix.copy()
    lagged_vix_changed[5] = 35.0
    _, lag_changed, _ = k1378.rolling_forecasts(
        returns, lagged_vix_changed, indices, time.time()
    )

    assert baseline[0] == pytest.approx(target_changed[0])
    assert baseline[0] != pytest.approx(lag_changed[0])


def test_optimizer_rejections_fail_closed(k1378, monkeypatch) -> None:
    failed = SimpleNamespace(
        success=False,
        fun=1.0,
        x=np.array([1e-5, 0.05, 0.05, 0.85, 0.0, 0.0]),
    )
    monkeypatch.setattr(k1378.optimize, "minimize", lambda *args, **kwargs: failed)
    returns = np.linspace(-0.02, 0.02, 100)
    log_vix = np.log(np.linspace(15.0, 25.0, 100))
    assert k1378.fit_gjr(returns) is None
    assert k1378.fit_a4f(returns, log_vix) is None


def test_sign_aware_period_verdict(k1378) -> None:
    rng = np.random.default_rng(1378)
    n = 250
    gjr = 1.0 + rng.normal(0.0, 0.02, n)
    a4f = 0.8 + rng.normal(0.0, 0.02, n)
    result = k1378.summarize_period(
        "synthetic",
        np.ones(n, dtype=bool),
        pd.date_range("2020-01-01", periods=n, freq="D"),
        a4f,
        gjr,
    )
    assert result["dm_t"] < -3.0
    assert result["harvey_winner"] == "A4f"
    assert (
        k1378.corrected_verdict(result)
        == "A4F_ROBUST_OUTSIDE_BROAD_COVID_WINDOW"
    )


def test_atomic_json_failure_preserves_previous_final(k1378, monkeypatch, tmp_path) -> None:
    destination = tmp_path / "result.json"
    original = b'{"old": true}\n'
    destination.write_bytes(original)

    def fail_dump(*args, **kwargs):
        raise RuntimeError("injected dump failure")

    monkeypatch.setattr(k1378.json, "dump", fail_dump)
    with pytest.raises(RuntimeError, match="injected"):
        k1378.atomic_write_json(destination, {"new": True})
    assert destination.read_bytes() == original
    assert not (tmp_path / ".result.json.tmp").exists()
