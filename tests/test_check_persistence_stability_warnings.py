from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    module_path = ROOT / "scripts" / "check_persistence_stability.py"
    spec = importlib.util.spec_from_file_location("check_persistence_stability", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_check_persistence_stability_warns_on_garch_fit_failures(monkeypatch, capsys) -> None:
    module = _load_module()
    returns = pd.Series(
        np.linspace(0.001, 0.01, 507),
        index=pd.date_range("2024-01-01", periods=507, freq="D"),
    )

    class DummyDataManager:
        def get_model_data(self, asset, start, end):
            return {"returns": returns}

    class FailingModel:
        def fit(self, disp):
            raise RuntimeError("fit did not converge")

    monkeypatch.setattr(module, "DataManager", DummyDataManager)
    monkeypatch.setattr(module, "arch_model", lambda *args, **kwargs: FailingModel())

    result = module.check_persistence_stability("SPY")

    captured = capsys.readouterr()
    assert result["asset"] == "SPY"
    assert result["recommended_window"] == 378
    assert "[persistence-stability] WARN GARCH fit failed; skipping rolling window" in captured.err
    assert "asset=SPY" in captured.err
    assert "RuntimeError: fit did not converge" in captured.err
