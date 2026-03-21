from __future__ import annotations

import numpy as np
import pandas as pd


def mse(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Mean Squared Error."""
    return float(np.mean((actual - predicted) ** 2))


def mae(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Mean Absolute Error."""
    return float(np.mean(np.abs(actual - predicted)))


def qlike(actual_var: np.ndarray, predicted_var: np.ndarray) -> float:
    """QLIKE loss function — preferred for variance forecasts.

    QLIKE = mean(actual / predicted + log(predicted))

    Lower is better.  Both *actual_var* and *predicted_var* must be positive.
    """
    predicted_var = np.maximum(predicted_var, 1e-12)
    return float(np.mean(actual_var / predicted_var + np.log(predicted_var)))


def hmse(actual_var: np.ndarray, predicted_var: np.ndarray) -> float:
    """Heteroskedasticity-adjusted MSE.

    HMSE = mean((1 - actual / predicted)^2)
    """
    predicted_var = np.maximum(predicted_var, 1e-12)
    ratio = actual_var / predicted_var
    return float(np.mean((1 - ratio) ** 2))


def r2_log(actual_var: np.ndarray, predicted_var: np.ndarray) -> float:
    """R-squared on log-variances."""
    log_actual = np.log(np.maximum(actual_var, 1e-12))
    log_pred = np.log(np.maximum(predicted_var, 1e-12))
    ss_res = np.sum((log_actual - log_pred) ** 2)
    ss_tot = np.sum((log_actual - np.mean(log_actual)) ** 2)
    return float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0
