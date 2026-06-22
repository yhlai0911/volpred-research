from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def test_run_forecasts_for_asset_warns_when_garch_strategy_fails(monkeypatch, capsys) -> None:
    import experiment_adaptive_window_var as mod  # type: ignore

    def _raise_fit_failure(_train_pct):
        raise RuntimeError("garch failed")

    monkeypatch.setattr(mod, "run_garch_forecast", _raise_fit_failure)

    dates = pd.bdate_range("2020-01-01", periods=506)
    returns = np.linspace(-0.01, 0.01, len(dates))
    data = pd.DataFrame({"return": returns}, index=dates)

    results = mod.run_forecasts_for_asset("TEST", data, dates[-2:])
    output = capsys.readouterr().out

    assert results["Fixed_504"] == []
    assert results["Adaptive_CUSUM"] == []
    assert results["Expanding"] == []
    assert len(results["EWMA_094"]) == 2
    assert "asset=TEST strategy=Fixed_504" in output
    assert "strategy=Adaptive_CUSUM" in output
    assert "strategy=Expanding" in output
    assert "RuntimeError: garch failed" in output
