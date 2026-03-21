"""HAR-RV (Heterogeneous Autoregressive Realized Variance) model.

Uses multi-scale squared returns as a proxy for realized variance.
No GARCH recursion — purely regression-based.

Reference: Corsi (2009) "A Simple Approximate Long-Memory Model
of Realized Volatility"
"""
from __future__ import annotations

from datetime import datetime

import numpy as np

from volpred.core.interfaces import BaseVolatilityModel
from volpred.core.types import DataRequirement, ForecastResult
from volpred.models.registry import ModelRegistry


@ModelRegistry.register("har_rv")
class HARRV(BaseVolatilityModel):
    """HAR-RV model using squared returns as RV proxy.

    RV_t = c + b1*RV_{t-1} + b5*MA5_RV + b22*MA22_RV + epsilon

    where RV_t ≈ r_t² (squared return as daily RV proxy).

    Also includes an asymmetric term (HAR-RV-J style):
    RV_t = c + b1*RV_{t-1} + b5*MA5_RV + b22*MA22_RV + bJ*RV_neg_{t-1}

    where RV_neg = r²*I(r<0) captures leverage/jump effect.
    """

    def __init__(self, asymmetric: bool = True, **kwargs):
        self._asymmetric = asymmetric
        self._params = None
        self._returns = None
        self._fit_info = {}

    def get_name(self) -> str:
        return f"HAR-RV{'J' if self._asymmetric else ''}"

    def get_data_requirement(self) -> DataRequirement:
        return DataRequirement(fields=["returns"], frequency="daily", min_periods=100)

    def fit(self, data) -> dict:
        returns = data["returns"].values if "returns" in data.columns else data.iloc[:, 0].values
        self._returns = returns
        T = len(returns)
        r2 = returns ** 2

        # Build HAR regressors
        y = r2[22:]  # target: RV_t
        X = []
        for t in range(22, T):
            rv_1 = r2[t - 1]
            rv_5 = np.mean(r2[t - 5:t])
            rv_22 = np.mean(r2[t - 22:t])
            row = [1, rv_1, rv_5, rv_22]
            if self._asymmetric:
                rv_neg = returns[t - 1] ** 2 if returns[t - 1] < 0 else 0.0
                row.append(rv_neg)
            X.append(row)

        X = np.array(X)
        y = y[:len(X)]

        # OLS estimation
        XtX = X.T @ X
        Xty = X.T @ y
        try:
            self._params = np.linalg.solve(XtX, Xty)
        except np.linalg.LinAlgError:
            self._params = np.linalg.lstsq(X, y, rcond=None)[0]

        # Fit statistics
        y_hat = X @ self._params
        residuals = y - y_hat
        sse = np.sum(residuals ** 2)
        sst = np.sum((y - np.mean(y)) ** 2)
        r2_stat = 1 - sse / sst if sst > 0 else 0.0
        n, k = X.shape
        adj_r2 = 1 - (1 - r2_stat) * (n - 1) / (n - k - 1)

        param_names = ["const", "b1", "b5", "b22"]
        if self._asymmetric:
            param_names.append("bJ")

        self._fit_info = {
            "converged": True,
            "r2": r2_stat,
            "adj_r2": adj_r2,
            "params": dict(zip(param_names, self._params)),
            "n_obs": n,
            "residual_std": float(np.std(residuals)),
        }
        return self._fit_info

    def forecast(self, steps: int = 1) -> ForecastResult:
        r2 = self._returns ** 2
        rv_1 = r2[-1]
        rv_5 = np.mean(r2[-5:])
        rv_22 = np.mean(r2[-22:])

        features = [1, rv_1, rv_5, rv_22]
        if self._asymmetric:
            rv_neg = self._returns[-1] ** 2 if self._returns[-1] < 0 else 0.0
            features.append(rv_neg)

        forecast_var = max(np.dot(self._params, features), 1e-12)

        return ForecastResult(
            date=datetime.now(),
            point_forecast=forecast_var ** 0.5,
            variance_forecast=forecast_var,
            distribution_params=self._fit_info.get("params", {}),
            model_name=self.get_name(),
            fit_info=self._fit_info,
        )

    def get_tunable_params(self) -> dict:
        return {
            "asymmetric": {"type": "bool", "current": self._asymmetric},
        }
