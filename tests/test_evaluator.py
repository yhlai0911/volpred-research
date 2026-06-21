from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from volpred.core.types import ExperimentConfig, ExperimentResult, ForecastResult
from volpred.evaluation.evaluator import Evaluator
from volpred.stats.model_evaluation import qlike_pointwise


def _experiment_result(experiment_id: str, predicted_vars: list[float]) -> ExperimentResult:
    dates = [datetime(2026, 1, 1), datetime(2026, 1, 2)]
    forecasts = [
        ForecastResult(
            date=date,
            point_forecast=float(np.sqrt(predicted_var)),
            variance_forecast=predicted_var,
            model_name=experiment_id,
        )
        for date, predicted_var in zip(dates, predicted_vars)
    ]
    return ExperimentResult(
        experiment_id=experiment_id,
        config=ExperimentConfig(model_name=experiment_id),
        forecasts=forecasts,
    )


def test_compare_models_uses_canonical_pointwise_qlike_for_dm(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, np.ndarray] = {}

    def fake_dm_test(loss1: np.ndarray, loss2: np.ndarray, h: int = 1) -> dict:
        captured["loss1"] = loss1.copy()
        captured["loss2"] = loss2.copy()
        captured["h"] = np.array([h])
        return {"statistic": 0.0, "p_value": 1.0}

    import volpred.evaluation.statistical_tests as statistical_tests

    monkeypatch.setattr(statistical_tests, "diebold_mariano_test", fake_dm_test)

    actual = np.array([1.0, 1.0])
    actual_data = pd.DataFrame(
        {"rv_proxy": actual},
        index=pd.to_datetime(["2026-01-01", "2026-01-02"]),
    )

    model_a = _experiment_result("model_a", [2.0, 0.5])
    model_b = _experiment_result("model_b", [1.0, 1.0])

    Evaluator().compare_models(
        [(model_a, {"qlike": 0.1}), (model_b, {"qlike": 0.0})],
        actual_data,
    )

    assert captured["loss1"] == pytest.approx(qlike_pointwise(actual, np.array([2.0, 0.5])))
    assert captured["loss2"] == pytest.approx(np.zeros(2))
    assert captured["h"].item() == 1
