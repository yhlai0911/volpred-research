"""GJR-GARCH implementations.

Two variants:
  - ArchGJR: wraps the `arch` package (GARCH with o parameter for GJR asymmetry)
  - CustomGJR: self-built MLE via scipy

The GJR-GARCH model (Glosten-Jagannathan-Runkle) captures the leverage
effect through an indicator function on negative returns.
"""
from __future__ import annotations

from datetime import datetime

import numpy as np

from volpred.core.custom_model import CustomVolModel
from volpred.core.interfaces import BaseVolatilityModel
from volpred.core.types import DataRequirement, ForecastResult
from volpred.models.registry import ModelRegistry


@ModelRegistry.register("gjr_arch")
class ArchGJR(BaseVolatilityModel):
    """GJR-GARCH using the ``arch`` package.

    Uses ``vol='GARCH'`` with the ``o`` parameter to enable the GJR
    asymmetric leverage term.
    """

    # Map our dist names to arch package names
    _DIST_MAP = {"normal": "normal", "studentt": "t", "skewt": "skewt", "ged": "ged"}

    def __init__(self, p=1, o=1, q=1, dist="normal", mean="Zero"):
        self.p = p  # GARCH order
        self.o = o  # asymmetric (GJR) order
        self.q = q  # ARCH order
        self.dist = dist  # 'normal', 'studentt', 'skewt'
        self.mean = mean
        self._result = None
        self._last_data = None

    def get_name(self):
        return f"GJR-GARCH({self.p},{self.o},{self.q})_arch_{self.dist}"

    def get_data_requirement(self):
        return DataRequirement(
            fields=["returns"], frequency="daily", min_periods=100
        )

    def fit(self, data):
        from arch import arch_model

        returns = (
            data["returns"].values
            if "returns" in data.columns
            else data.iloc[:, 0].values
        )
        returns = returns * 100  # arch expects percentage returns
        self._last_data = returns
        arch_dist = self._DIST_MAP.get(self.dist, self.dist)
        model = arch_model(
            returns,
            vol="GARCH",
            p=self.p,
            o=self.o,
            q=self.q,
            dist=arch_dist,
            mean=self.mean,
            rescale=False,
        )
        self._result = model.fit(disp="off", show_warning=False)
        return {
            "converged": self._result.convergence_flag == 0,
            "loglik": self._result.loglikelihood,
            "params": dict(self._result.params),
            "aic": self._result.aic,
            "bic": self._result.bic,
        }

    def forecast(self, steps=1):
        fcast = self._result.forecast(horizon=steps)
        variance = fcast.variance.iloc[-1, 0] / 10000  # convert back from pct
        return ForecastResult(
            date=datetime.now(),
            point_forecast=variance**0.5,
            variance_forecast=variance,
            distribution_params=dict(self._result.params),
            model_name=self.get_name(),
            fit_info={"aic": self._result.aic},
        )

    def get_tunable_params(self):
        return {
            "p": {"type": "int", "range": [1, 3], "current": self.p},
            "o": {"type": "int", "range": [1, 3], "current": self.o},
            "q": {"type": "int", "range": [1, 3], "current": self.q},
            "dist": {
                "type": "categorical",
                "options": ["normal", "studentt", "skewt"],
                "current": self.dist,
            },
        }


@ModelRegistry.register("gjr_custom")
class CustomGJR(CustomVolModel):
    """Custom GJR-GARCH(1,1) with scipy MLE.

    sigma2_t = omega + alpha * r_{t-1}^2
               + gamma * r_{t-1}^2 * I(r_{t-1} < 0)
               + beta * sigma2_{t-1}

    gamma > 0 means negative shocks increase volatility more than
    positive shocks of the same magnitude (leverage effect).
    """

    def __init__(self, dist="normal"):
        super().__init__(dist=dist)

    def get_name(self):
        return f"GJR-GARCH(1,1)_custom_{self._dist}"

    def get_data_requirement(self):
        return DataRequirement(
            fields=["returns"], frequency="daily", min_periods=100
        )

    def _param_names(self):
        names = ["omega", "alpha", "gamma", "beta"]
        if self._dist == "studentt":
            names.append("nu")
        return names

    def _initial_params(self):
        var = np.var(self._returns) if self._returns is not None else 0.0001
        params = [var * 0.05, 0.03, 0.04, 0.90]
        if self._dist == "studentt":
            params.append(8.0)
        return np.array(params)

    def _bounds(self):
        bounds = [(1e-8, 1.0), (1e-8, 0.999), (1e-8, 0.999), (1e-8, 0.999)]
        if self._dist == "studentt":
            bounds.append((2.01, 100))
        return bounds

    def _conditional_variance(self, params, returns):
        omega, alpha, gamma, beta = params[0], params[1], params[2], params[3]
        T = len(returns)
        sigma2 = np.zeros(T)
        sigma2[0] = (
            omega / (1 - alpha - 0.5 * gamma - beta)
            if (alpha + 0.5 * gamma + beta) < 1
            else np.var(returns)
        )
        for t in range(1, T):
            indicator = 1.0 if returns[t - 1] < 0 else 0.0
            sigma2[t] = (
                omega
                + alpha * returns[t - 1] ** 2
                + gamma * returns[t - 1] ** 2 * indicator
                + beta * sigma2[t - 1]
            )
        return np.maximum(sigma2, 1e-12)

    def forecast(self, steps=1):
        if self._params is None or self._returns is None:
            raise RuntimeError("Model has not been fitted yet.")

        omega, alpha, gamma, beta = (
            self._params[0],
            self._params[1],
            self._params[2],
            self._params[3],
        )

        sigma2 = self._conditional_variance(self._params, self._returns)
        last_sigma2 = sigma2[-1]
        last_r2 = self._returns[-1] ** 2
        indicator = 1.0 if self._returns[-1] < 0 else 0.0

        next_sigma2 = (
            omega
            + alpha * last_r2
            + gamma * last_r2 * indicator
            + beta * last_sigma2
        )

        return ForecastResult(
            date=datetime.now(),
            point_forecast=next_sigma2**0.5,
            variance_forecast=next_sigma2,
            distribution_params=dict(zip(self._param_names(), self._params)),
            model_name=self.get_name(),
            fit_info={
                "converged": (
                    self._fit_result.success if self._fit_result else False
                ),
                "loglik": (
                    -self._fit_result.fun if self._fit_result else None
                ),
            },
        )

    def get_tunable_params(self):
        return {
            "dist": {
                "type": "categorical",
                "options": ["normal", "studentt"],
                "current": self._dist,
            },
        }
