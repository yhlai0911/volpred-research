"""EGARCH implementations.

Two variants:
  - ArchEGARCH: wraps the `arch` package (EGARCH volatility process)
  - CustomEGARCH: self-built MLE via scipy

The EGARCH model captures the *leverage effect* — negative shocks tend to
increase volatility more than positive shocks of the same magnitude.
"""
from __future__ import annotations

from datetime import datetime

import numpy as np

from volpred.core.custom_model import CustomVolModel
from volpred.core.interfaces import BaseVolatilityModel
from volpred.core.types import DataRequirement, ForecastResult
from volpred.models.registry import ModelRegistry


@ModelRegistry.register("egarch_arch")
class ArchEGARCH(BaseVolatilityModel):
    """EGARCH using the ``arch`` package.

    Captures the leverage effect via an asymmetric volatility specification.
    The ``o`` parameter controls the asymmetric (leverage) order.
    """

    # Map our dist names to arch package names
    _DIST_MAP = {"normal": "normal", "studentt": "t", "skewt": "skewt"}

    def __init__(self, p=1, o=1, q=1, dist="normal", mean="Zero"):
        self.p = p  # GARCH order
        self.o = o  # asymmetric order
        self.q = q  # ARCH order
        self.dist = dist  # 'normal', 'studentt', 'skewt'
        self.mean = mean
        self._result = None
        self._last_data = None

    def get_name(self):
        return f"EGARCH({self.p},{self.o},{self.q})_arch_{self.dist}"

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
            vol="EGARCH",
            p=self.p,
            o=self.o,
            q=self.q,
            dist=arch_dist,
            mean=self.mean,
            rescale=False,
        )
        self._result = model.fit(disp="off", show_warning=False)

        # Sanity check: detect false convergence (absurd parameters)
        params = dict(self._result.params)
        alpha_vals = [v for k, v in params.items() if "alpha" in k]
        gamma_vals = [v for k, v in params.items() if "gamma" in k]
        beta_vals = [v for k, v in params.items() if "beta" in k]
        sane = all(abs(v) < 10 for v in alpha_vals + gamma_vals) and all(abs(v) <= 1.0 for v in beta_vals)
        self._sane_params = sane

        return {
            "converged": self._result.convergence_flag == 0 and sane,
            "loglik": self._result.loglikelihood,
            "params": params,
            "aic": self._result.aic,
            "bic": self._result.bic,
            "sane_params": sane,
        }

    def forecast(self, steps=1):
        # If parameters are insane, fallback to unconditional variance
        if not self._sane_params:
            uncond_var = float(np.var(self._last_data)) / 10000
            return ForecastResult(
                date=datetime.now(),
                point_forecast=uncond_var**0.5,
                variance_forecast=uncond_var,
                distribution_params=dict(self._result.params),
                model_name=self.get_name(),
                fit_info={"aic": self._result.aic, "fallback": True},
            )

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


@ModelRegistry.register("egarch_custom")
class CustomEGARCH(CustomVolModel):
    """Custom EGARCH(1,1) with scipy MLE.

    log(sigma2_t) = omega + alpha * (|z_{t-1}| - sqrt(2/pi))
                    + gamma * z_{t-1} + beta * log(sigma2_{t-1})

    where z_t = r_t / sigma_t (standardised residuals).

    gamma < 0 captures the leverage effect (negative shocks
    increase volatility more than positive shocks).
    """

    def __init__(self, dist="normal"):
        super().__init__(dist=dist)

    def get_name(self):
        return f"EGARCH(1,1)_custom_{self._dist}"

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
        params = [-0.1, 0.1, -0.05, 0.95]
        if self._dist == "studentt":
            params.append(8.0)
        return np.array(params)

    def _bounds(self):
        bounds = [(-10, 10), (-1, 1), (-1, 1), (-0.999, 0.999)]
        if self._dist == "studentt":
            bounds.append((2.01, 100))
        return bounds

    def _conditional_variance(self, params, returns):
        omega, alpha, gamma, beta = params[0], params[1], params[2], params[3]
        T = len(returns)
        log_sigma2 = np.zeros(T)
        log_sigma2[0] = (
            omega / (1 - beta) if abs(beta) < 1 else np.log(np.var(returns))
        )
        for t in range(1, T):
            sigma_prev = np.exp(log_sigma2[t - 1] / 2)
            z = returns[t - 1] / max(sigma_prev, 1e-8)
            log_sigma2[t] = (
                omega
                + alpha * (abs(z) - np.sqrt(2 / np.pi))
                + gamma * z
                + beta * log_sigma2[t - 1]
            )
        # Clamp to avoid overflow in exp
        log_sigma2 = np.clip(log_sigma2, -50, 50)
        return np.exp(log_sigma2)

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
        last_sigma = last_sigma2**0.5
        z_last = self._returns[-1] / max(last_sigma, 1e-8)

        log_last_sigma2 = np.log(max(last_sigma2, 1e-12))
        log_next_sigma2 = (
            omega
            + alpha * (abs(z_last) - np.sqrt(2 / np.pi))
            + gamma * z_last
            + beta * log_last_sigma2
        )
        next_sigma2 = float(np.exp(log_next_sigma2))

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
