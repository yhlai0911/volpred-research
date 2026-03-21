"""CARR (Conditional Autoregressive Range) model.

Uses daily high-low price range for volatility forecasting.
Range is a 5-8x more efficient volatility estimator than squared returns.

Reference: Chou (2005) "Forecasting Financial Volatilities with Extreme Values"
"""
from __future__ import annotations

from abc import abstractmethod
from datetime import datetime

import numpy as np
from scipy.optimize import minimize

from volpred.core.interfaces import BaseVolatilityModel
from volpred.core.types import DataRequirement, ForecastResult
from volpred.models.registry import ModelRegistry


@ModelRegistry.register("carr")
class CARR(BaseVolatilityModel):
    """CARR(1,1) with asymmetric response.

    lambda_t = omega + alpha*R_{t-1} + gamma*R_{t-1}*I(r_{t-1}<0) + beta*lambda_{t-1}

    where R_t = ln(H_t/L_t) is the daily log range.
    Assumes exponential distribution: f(R|lambda) = (1/lambda)*exp(-R/lambda)

    The asymmetric term allows negative-return days to increase
    the expected range more (leverage effect on range).

    Output: variance forecast = (lambda / correction)^2
    where correction = 2*sqrt(ln2) ≈ 1.665 converts range to std dev.
    """

    RANGE_TO_STD = 2 * np.sqrt(np.log(2))  # ≈ 1.665

    def __init__(self, asymmetric: bool = True, **kwargs):
        self._asymmetric = asymmetric
        self._params = None
        self._ranges = None
        self._returns = None
        self._fit_result = None
        self._data = None

    def get_name(self) -> str:
        return f"CARR{'J' if self._asymmetric else ''}(1,1)"

    def get_data_requirement(self) -> DataRequirement:
        return DataRequirement(
            fields=["returns", "high", "low"],
            frequency="daily",
            min_periods=100,
        )

    def fit(self, data) -> dict:
        if "high" in data.columns and "low" in data.columns:
            self._ranges = np.log(data["high"].values / data["low"].values)
        else:
            # Fallback: use absolute returns * sqrt(pi/2) as range proxy
            returns = data["returns"].values if "returns" in data.columns else data.iloc[:, 0].values
            self._ranges = np.abs(returns) * np.sqrt(np.pi / 2)

        self._returns = data["returns"].values if "returns" in data.columns else data.iloc[:, 0].values
        self._data = data

        init = self._initial_params()
        bounds = self._bounds()

        # Multi-start optimization
        best = None
        rng = np.random.RandomState(42)
        starts = [init]
        for _ in range(3):
            p = init * (1 + 0.3 * rng.randn(len(init)))
            for j, (lo, hi) in enumerate(bounds):
                p[j] = np.clip(p[j], lo * 1.01, hi * 0.99)
            starts.append(p)

        for x0 in starts:
            try:
                result = minimize(
                    lambda p: -self._log_likelihood(p),
                    x0=x0, method="L-BFGS-B", bounds=bounds,
                    options={"maxiter": 2000, "ftol": 1e-12, "gtol": 1e-8},
                )
                if best is None or result.fun < best.fun:
                    best = result
            except Exception:
                continue

        self._params = best.x
        self._fit_result = best
        return {
            "converged": bool(best.success),
            "loglik": -best.fun,
            "params": dict(zip(self._param_names(), best.x)),
            "n_iter": int(best.nit),
        }

    def forecast(self, steps: int = 1) -> ForecastResult:
        lambdas = self._conditional_range(self._params)
        last_lambda = lambdas[-1]
        last_R = self._ranges[-1]

        omega, alpha, beta = self._params[0], self._params[1], self._params[-1]
        if self._asymmetric:
            gamma = self._params[2]
            indicator = 1.0 if self._returns[-1] < 0 else 0.0
            next_lambda = omega + alpha * last_R + gamma * last_R * indicator + beta * last_lambda
        else:
            next_lambda = omega + alpha * last_R + beta * last_lambda

        next_lambda = max(next_lambda, 1e-8)
        # Convert range forecast to variance: sigma = range / (2*sqrt(ln2))
        sigma = next_lambda / self.RANGE_TO_STD
        variance = sigma ** 2

        return ForecastResult(
            date=datetime.now(),
            point_forecast=sigma,
            variance_forecast=variance,
            distribution_params=dict(zip(self._param_names(), self._params)),
            model_name=self.get_name(),
            fit_info={
                "converged": self._fit_result.success if self._fit_result else False,
                "loglik": -self._fit_result.fun if self._fit_result else None,
                "lambda_forecast": next_lambda,
            },
        )

    def _param_names(self) -> list[str]:
        if self._asymmetric:
            return ["omega", "alpha", "gamma", "beta"]
        return ["omega", "alpha", "beta"]

    def _initial_params(self) -> np.ndarray:
        mean_R = np.mean(self._ranges) if self._ranges is not None else 0.01
        if self._asymmetric:
            return np.array([mean_R * 0.05, 0.05, 0.03, 0.90])
        return np.array([mean_R * 0.05, 0.08, 0.90])

    def _bounds(self) -> list[tuple]:
        if self._asymmetric:
            return [(1e-8, 0.1), (1e-8, 0.5), (1e-8, 0.5), (0.01, 0.999)]
        return [(1e-8, 0.1), (1e-8, 0.5), (0.01, 0.999)]

    def _conditional_range(self, params: np.ndarray) -> np.ndarray:
        """Compute conditional expected range series."""
        T = len(self._ranges)
        omega = params[0]
        alpha = params[1]
        if self._asymmetric:
            gamma = params[2]
            beta = params[3]
        else:
            gamma = 0.0
            beta = params[2]

        lambdas = np.zeros(T)
        mean_R = np.mean(self._ranges)
        lambdas[0] = mean_R

        for t in range(1, T):
            indicator = 1.0 if self._returns[t - 1] < 0 else 0.0
            lambdas[t] = (omega
                          + alpha * self._ranges[t - 1]
                          + gamma * self._ranges[t - 1] * indicator
                          + beta * lambdas[t - 1])

        return np.maximum(lambdas, 1e-8)

    def _log_likelihood(self, params: np.ndarray) -> float:
        """Exponential distribution log-likelihood for range."""
        lambdas = self._conditional_range(params)
        # f(R|lambda) = (1/lambda)*exp(-R/lambda)
        # log f = -log(lambda) - R/lambda
        ll = -np.log(lambdas) - self._ranges / lambdas
        return float(np.sum(ll))
