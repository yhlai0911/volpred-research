from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def test_gjr_garch_rolling_warns_when_arch_fit_fails(monkeypatch, capsys) -> None:
    import gbm_qlike_cross_validation as mod  # type: ignore

    fake_arch = ModuleType("arch")

    def _raise_fit_failure(*args, **kwargs):
        raise RuntimeError("arch fit unavailable")

    fake_arch.arch_model = _raise_fit_failure
    monkeypatch.setitem(sys.modules, "arch", fake_arch)

    returns_pct = np.linspace(-1.0, 1.0, 503)
    forecasts = mod.gjr_garch_rolling(
        returns_pct,
        oos_start_idx=500,
        oos_end_idx=503,
        window=500,
    )
    output = capsys.readouterr().out

    assert np.isnan(forecasts).all()
    assert "GJR rolling forecast failed" in output
    assert "RuntimeError: arch fit unavailable" in output
    assert "train_n=500" in output


def test_gbm_rolling_warns_when_prediction_fails(monkeypatch, capsys) -> None:
    import gbm_qlike_cross_validation as mod  # type: ignore

    fake_sklearn = ModuleType("sklearn")
    fake_ensemble = ModuleType("sklearn.ensemble")

    class BrokenGradientBoostingRegressor:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def fit(self, *args, **kwargs):
            return self

        def predict(self, *args, **kwargs):
            raise ValueError("prediction failed")

    fake_ensemble.GradientBoostingRegressor = BrokenGradientBoostingRegressor
    monkeypatch.setitem(sys.modules, "sklearn", fake_sklearn)
    monkeypatch.setitem(sys.modules, "sklearn.ensemble", fake_ensemble)

    merged = pd.DataFrame(
        {
            "feature": [0.1, 0.2, 0.3],
            "rv_proxy": [1.0, 1.1, 1.2],
        }
    )
    forecasts = mod.gbm_rolling(
        merged,
        ["feature"],
        oos_start_idx=1,
        oos_end_idx=3,
        retrain_every=1,
        min_train=1,
    )
    output = capsys.readouterr().out

    assert np.isnan(forecasts).all()
    assert "GBM forecast failed" in output
    assert "ValueError: prediction failed" in output
    assert "features=['feature']" in output
