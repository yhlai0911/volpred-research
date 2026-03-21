"""Experimental volatility models — custom designs from research insights.

These are NOT textbook models. They are designed by the research system
based on observed problems with standard models.
"""
from __future__ import annotations

from datetime import datetime

import numpy as np

from volpred.core.custom_model import CustomVolModel
from volpred.core.types import DataRequirement, ForecastResult
from volpred.models.registry import ModelRegistry


@ModelRegistry.register("emd_gjr")
class EMDGJR(CustomVolModel):
    """GJR-GARCH with EMD-based adaptive intercept.

    Motivation: EMD decomposes r² into multi-scale components. The low-frequency
    IMFs (5-8) capture the slow-moving trend of volatility. Using this trend as
    an adaptive omega lets the model respond to regime shifts without changing
    the GARCH dynamics.

    sigma2_t = (omega + delta * trend_t) + alpha*r² + gamma*r²*I(r<0) + beta*sigma2_{t-1}

    where trend_t = sum of low-frequency IMFs (periods > ~100 days)

    Key insight from Phase H research: persistence varies with regime (0.89→0.96),
    and EMD can separate the slow trend from fast dynamics.
    """

    def __init__(self, dist: str = "normal"):
        super().__init__(dist=dist)
        self._trend = None

    def get_name(self) -> str:
        return f"EMD-GJR_custom_{self._dist}"

    def get_data_requirement(self) -> DataRequirement:
        return DataRequirement(fields=["returns"], frequency="daily", min_periods=100)

    def fit(self, data) -> dict:
        # Extract returns
        if isinstance(data, np.ndarray):
            returns = data
        elif "returns" in data.columns:
            returns = data["returns"].values
        else:
            returns = data.iloc[:, 0].values

        # EMD decomposition of squared returns
        r2 = returns ** 2
        try:
            import emd as emd_lib
            imfs = emd_lib.sift.sift(r2, max_imfs=8)
            # Low-frequency trend: sum of IMFs with period > ~100 days (typically IMF 5-8)
            # We identify these by zero-crossing rate
            trend = np.zeros(len(r2))
            for i in range(imfs.shape[1]):
                zc = np.sum(np.diff(np.sign(imfs[:, i])) != 0)
                avg_period = 2 * len(r2) / max(zc, 1)
                if avg_period > 100:  # slow components only
                    trend += imfs[:, i]
            self._trend = trend
        except Exception:
            # Fallback: use rolling MA as trend proxy
            window = min(100, len(r2) // 3)
            trend = np.convolve(r2, np.ones(window) / window, mode='same')
            self._trend = trend

        return super().fit(data)

    def _param_names(self) -> list[str]:
        names = ["omega", "alpha", "gamma", "beta", "delta"]
        if self._dist == "studentt":
            names.append("nu")
        return names

    def _initial_params(self) -> np.ndarray:
        var = np.var(self._returns) if self._returns is not None else 0.0001
        params = [var * 0.03, 0.02, 0.04, 0.88, 0.3]
        if self._dist == "studentt":
            params.append(8.0)
        return np.array(params)

    def _bounds(self) -> list[tuple]:
        bounds = [
            (1e-8, 1.0),     # omega
            (1e-8, 0.5),     # alpha
            (1e-8, 0.999),   # gamma
            (0.01, 0.999),   # beta
            (0.0, 10.0),     # delta (sensitivity to EMD trend)
        ]
        if self._dist == "studentt":
            bounds.append((2.01, 100.0))
        return bounds

    def _conditional_variance(self, params: np.ndarray, returns: np.ndarray) -> np.ndarray:
        omega, alpha, gamma, beta, delta = (
            params[0], params[1], params[2], params[3], params[4],
        )
        T = len(returns)
        sigma2 = np.zeros(T)
        r2 = returns ** 2

        # Use trend if available and matching length
        trend = self._trend if self._trend is not None and len(self._trend) == T else np.zeros(T)

        sigma2[0] = np.var(returns)

        for t in range(1, T):
            indicator = 1.0 if returns[t - 1] < 0 else 0.0
            adaptive_omega = omega + delta * max(trend[t - 1], 0)  # trend can be negative, clamp
            sigma2[t] = (adaptive_omega
                         + alpha * r2[t - 1]
                         + gamma * r2[t - 1] * indicator
                         + beta * sigma2[t - 1])

        return np.maximum(sigma2, 1e-12)

    def forecast(self, steps: int = 1) -> ForecastResult:
        params = self._params
        omega, alpha, gamma, beta, delta = (
            params[0], params[1], params[2], params[3], params[4],
        )
        sigma2 = self._conditional_variance(params, self._returns)
        r2 = self._returns ** 2
        trend = self._trend if self._trend is not None else np.zeros(len(self._returns))

        # Use last trend value for forecast
        trend_last = max(trend[-1], 0) if len(trend) > 0 else 0
        adaptive_omega = omega + delta * trend_last

        indicator = 1.0 if self._returns[-1] < 0 else 0.0
        next_sigma2 = (adaptive_omega
                       + alpha * r2[-1]
                       + gamma * r2[-1] * indicator
                       + beta * sigma2[-1])

        return ForecastResult(
            date=datetime.now(),
            point_forecast=max(next_sigma2, 1e-12) ** 0.5,
            variance_forecast=max(next_sigma2, 1e-12),
            distribution_params=dict(zip(self._param_names(), params)),
            model_name=self.get_name(),
            fit_info={
                "converged": self._fit_result.success if self._fit_result else False,
                "loglik": -self._fit_result.fun if self._fit_result else None,
                "delta": delta,
                "adaptive_omega": adaptive_omega,
                "trend_last": float(trend_last),
            },
        )


@ModelRegistry.register("realized_garch")
class RealizedGARCH(CustomVolModel):
    """Realized GARCH (Hansen, Huang & Shek 2012) with log-linear specification.

    Uses Parkinson RV as realized measure x_t. Three equations:
    (1) r_t = sqrt(h_t) * z_t
    (2) log h_t = omega + beta * log h_{t-1} + gamma * log x_{t-1}
    (3) log x_t = xi + phi * log h_t + tau1*z_t + tau2*(z_t^2-1) + u_t

    Key advantage: uses intraday range info (Parkinson RV) instead of just r².
    Even Parkinson RV from daily OHLC provides ~5x more info than r² alone.

    Reference: Hansen et al. (2012) Journal of Applied Econometrics.
    """

    def __init__(self, dist: str = "normal"):
        super().__init__(dist=dist)
        self._rv = None

    def get_name(self) -> str:
        return f"RealGARCH_custom_{self._dist}"

    def get_data_requirement(self) -> DataRequirement:
        return DataRequirement(
            fields=["returns", "high", "low"],
            frequency="daily",
            min_periods=100,
        )

    def fit(self, data) -> dict:
        # Extract Parkinson RV from high/low
        if "rv_parkinson" in data.columns:
            self._rv = data["rv_parkinson"].values
        elif "high" in data.columns and "low" in data.columns:
            log_range = np.log(data["high"].values / data["low"].values)
            self._rv = log_range ** 2 / (4 * np.log(2))
        else:
            # Fallback: use squared returns
            returns = data["returns"].values if "returns" in data.columns else data.iloc[:, 0].values
            self._rv = returns ** 2
        return super().fit(data)

    def _param_names(self) -> list[str]:
        names = ["omega", "beta", "gamma"]
        if self._dist == "studentt":
            names.append("nu")
        return names

    def _initial_params(self) -> np.ndarray:
        params = [-0.1, 0.6, 0.3]  # log-linear: omega, beta, gamma
        if self._dist == "studentt":
            params.append(8.0)
        return np.array(params)

    def _bounds(self) -> list[tuple]:
        bounds = [
            (-5.0, 5.0),      # omega (log scale)
            (0.01, 0.999),     # beta (persistence in log h)
            (0.001, 0.999),    # gamma (RV sensitivity)
        ]
        if self._dist == "studentt":
            bounds.append((2.01, 100.0))
        return bounds

    def _conditional_variance(self, params: np.ndarray, returns: np.ndarray) -> np.ndarray:
        omega, beta, gamma = params[0], params[1], params[2]
        T = len(returns)
        log_h = np.zeros(T)
        rv = self._rv if self._rv is not None and len(self._rv) == T else returns ** 2

        # Clamp RV to avoid log(0)
        rv = np.maximum(rv, 1e-12)
        log_rv = np.log(rv)

        # Initial value
        log_h[0] = np.log(np.var(returns) + 1e-12)

        for t in range(1, T):
            log_h[t] = omega + beta * log_h[t - 1] + gamma * log_rv[t - 1]

        return np.exp(log_h)

    def forecast(self, steps: int = 1) -> ForecastResult:
        params = self._params
        omega, beta, gamma = params[0], params[1], params[2]

        sigma2 = self._conditional_variance(params, self._returns)
        rv = self._rv if self._rv is not None else self._returns ** 2
        rv = np.maximum(rv, 1e-12)

        # One-step ahead forecast
        log_h_next = omega + beta * np.log(sigma2[-1] + 1e-12) + gamma * np.log(rv[-1])
        next_sigma2 = np.exp(log_h_next)

        return ForecastResult(
            date=datetime.now(),
            point_forecast=max(next_sigma2, 1e-12) ** 0.5,
            variance_forecast=max(next_sigma2, 1e-12),
            distribution_params=dict(zip(self._param_names(), params)),
            model_name=self.get_name(),
            fit_info={
                "converged": self._fit_result.success if self._fit_result else False,
                "loglik": -self._fit_result.fun if self._fit_result else None,
                "omega": omega,
                "beta": beta,
                "gamma": gamma,
            },
        )


@ModelRegistry.register("gjr_floor")
class GJRFloor(CustomVolModel):
    """GJR-GARCH with a volatility floor.

    Motivation: standard GJR fails VaR 1% because its asymmetric term
    suppresses volatility during calm (positive return) periods, leading
    to thin-tailed VaR. Adding a floor prevents excessive compression.

    sigma2_t = max(floor, omega + alpha*r² + gamma*r²*I(r<0) + beta*sigma2_{t-1})

    where floor = phi * unconditional_variance
    phi is estimated via MLE (typically 0.3-0.7)
    """

    def __init__(self, dist: str = "normal"):
        super().__init__(dist=dist)

    def get_name(self) -> str:
        return f"GJR-Floor_custom_{self._dist}"

    def get_data_requirement(self) -> DataRequirement:
        return DataRequirement(fields=["returns"], frequency="daily", min_periods=100)

    def _param_names(self) -> list[str]:
        names = ["omega", "alpha", "gamma", "beta", "phi"]
        if self._dist == "studentt":
            names.append("nu")
        return names

    def _initial_params(self) -> np.ndarray:
        var = np.var(self._returns) if self._returns is not None else 0.0001
        params = [var * 0.05, 0.03, 0.04, 0.90, 0.5]  # phi=0.5 → floor is 50% of unconditional
        if self._dist == "studentt":
            params.append(8.0)
        return np.array(params)

    def _bounds(self) -> list[tuple]:
        bounds = [
            (1e-8, 1.0),     # omega
            (1e-8, 0.999),   # alpha
            (1e-8, 0.999),   # gamma
            (1e-8, 0.999),   # beta
            (0.01, 0.99),    # phi (floor as fraction of unconditional var)
        ]
        if self._dist == "studentt":
            bounds.append((2.01, 100.0))
        return bounds

    def _conditional_variance(self, params: np.ndarray, returns: np.ndarray) -> np.ndarray:
        omega, alpha, gamma, beta, phi = params[0], params[1], params[2], params[3], params[4]
        T = len(returns)
        sigma2 = np.zeros(T)

        # Unconditional variance for the floor
        uncond_var = np.var(returns)
        floor = phi * uncond_var

        # Initial value
        sigma2[0] = max(floor, omega / (1 - alpha - 0.5 * gamma - beta)
                        if (alpha + 0.5 * gamma + beta) < 1 else uncond_var)

        for t in range(1, T):
            indicator = 1.0 if returns[t - 1] < 0 else 0.0
            raw = omega + alpha * returns[t - 1] ** 2 + gamma * returns[t - 1] ** 2 * indicator + beta * sigma2[t - 1]
            sigma2[t] = max(floor, raw)

        return sigma2

    def forecast(self, steps: int = 1) -> ForecastResult:
        omega, alpha, gamma, beta, phi = (
            self._params[0], self._params[1], self._params[2],
            self._params[3], self._params[4],
        )
        sigma2 = self._conditional_variance(self._params, self._returns)
        last_sigma2 = sigma2[-1]
        last_r2 = self._returns[-1] ** 2
        indicator = 1.0 if self._returns[-1] < 0 else 0.0
        uncond_var = np.var(self._returns)
        floor = phi * uncond_var

        raw = omega + alpha * last_r2 + gamma * last_r2 * indicator + beta * last_sigma2
        next_sigma2 = max(floor, raw)

        return ForecastResult(
            date=datetime.now(),
            point_forecast=next_sigma2 ** 0.5,
            variance_forecast=next_sigma2,
            distribution_params=dict(zip(self._param_names(), self._params)),
            model_name=self.get_name(),
            fit_info={
                "converged": self._fit_result.success if self._fit_result else False,
                "loglik": -self._fit_result.fun if self._fit_result else None,
                "floor": floor,
                "uncond_var": uncond_var,
            },
        )


@ModelRegistry.register("gjr_adapt")
class GJRAdaptive(CustomVolModel):
    """GJR-GARCH with adaptive intercept based on recent volatility level.

    Motivation: Standard GJR has a fixed omega. But in practice, the
    'base level' of volatility changes (high-vol regime vs low-vol regime).
    This model adjusts omega based on a short-term MA of squared returns.

    sigma2_t = (omega + delta * MA5_r²) + alpha*r² + gamma*r²*I(r<0) + beta*sigma2_{t-1}

    delta controls how much the base level responds to recent volatility.
    MA5_r² = average of past 5 squared returns.
    """

    def __init__(self, dist: str = "normal", lookback: int = 5):
        super().__init__(dist=dist)
        self._lookback = lookback

    def get_name(self) -> str:
        return f"GJR-Adapt({self._lookback})_custom_{self._dist}"

    def get_data_requirement(self) -> DataRequirement:
        return DataRequirement(fields=["returns"], frequency="daily", min_periods=100)

    def _param_names(self) -> list[str]:
        names = ["omega", "alpha", "gamma", "beta", "delta"]
        if self._dist == "studentt":
            names.append("nu")
        return names

    def _initial_params(self) -> np.ndarray:
        var = np.var(self._returns) if self._returns is not None else 0.0001
        params = [var * 0.03, 0.03, 0.04, 0.88, 0.1]
        if self._dist == "studentt":
            params.append(8.0)
        return np.array(params)

    def _bounds(self) -> list[tuple]:
        bounds = [
            (1e-8, 1.0),     # omega
            (1e-8, 0.999),   # alpha
            (1e-8, 0.999),   # gamma
            (1e-8, 0.999),   # beta
            (0.0, 5.0),      # delta (sensitivity to recent vol)
        ]
        if self._dist == "studentt":
            bounds.append((2.01, 100.0))
        return bounds

    def _conditional_variance(self, params: np.ndarray, returns: np.ndarray) -> np.ndarray:
        omega, alpha, gamma, beta, delta = params[0], params[1], params[2], params[3], params[4]
        T = len(returns)
        sigma2 = np.zeros(T)
        r2 = returns ** 2

        # Initial value
        sigma2[0] = omega / (1 - alpha - 0.5 * gamma - beta) if (alpha + 0.5 * gamma + beta) < 1 else np.var(returns)

        for t in range(1, T):
            # Moving average of recent squared returns
            lookback_start = max(0, t - self._lookback)
            ma_r2 = np.mean(r2[lookback_start:t])

            indicator = 1.0 if returns[t - 1] < 0 else 0.0
            adaptive_omega = omega + delta * ma_r2
            sigma2[t] = adaptive_omega + alpha * r2[t - 1] + gamma * r2[t - 1] * indicator + beta * sigma2[t - 1]

        return np.maximum(sigma2, 1e-12)

    def forecast(self, steps: int = 1) -> ForecastResult:
        omega, alpha, gamma, beta, delta = (
            self._params[0], self._params[1], self._params[2],
            self._params[3], self._params[4],
        )
        sigma2 = self._conditional_variance(self._params, self._returns)
        r2 = self._returns ** 2

        ma_r2 = np.mean(r2[-self._lookback:])
        adaptive_omega = omega + delta * ma_r2

        last_sigma2 = sigma2[-1]
        last_r2 = r2[-1]
        indicator = 1.0 if self._returns[-1] < 0 else 0.0
        next_sigma2 = adaptive_omega + alpha * last_r2 + gamma * last_r2 * indicator + beta * last_sigma2

        return ForecastResult(
            date=datetime.now(),
            point_forecast=max(next_sigma2, 1e-12) ** 0.5,
            variance_forecast=max(next_sigma2, 1e-12),
            distribution_params=dict(zip(self._param_names(), self._params)),
            model_name=self.get_name(),
            fit_info={
                "converged": self._fit_result.success if self._fit_result else False,
                "loglik": -self._fit_result.fun if self._fit_result else None,
                "adaptive_omega": adaptive_omega,
                "ma_r2": ma_r2,
            },
        )


@ModelRegistry.register("gjr_har")
class GJRHAR(CustomVolModel):
    """GJR-GARCH with HAR-style multi-scale volatility components.

    Motivation: Standard GARCH only uses yesterday's info. HAR literature
    shows that volatility has multi-scale persistence: daily, weekly, monthly.
    This model embeds HAR structure into GARCH's intercept.

    sigma2_t = (omega + d5*MA5_r² + d22*MA22_r²)
               + alpha*r²_{t-1} + gamma*r²_{t-1}*I(r<0) + beta*sigma2_{t-1}

    d5 captures weekly volatility persistence
    d22 captures monthly volatility persistence
    This makes the base volatility level respond to multi-scale patterns.
    """

    def __init__(self, dist: str = "normal"):
        super().__init__(dist=dist)

    def get_name(self) -> str:
        return f"GJR-HAR_custom_{self._dist}"

    def get_data_requirement(self) -> DataRequirement:
        return DataRequirement(fields=["returns"], frequency="daily", min_periods=100)

    def _param_names(self) -> list[str]:
        names = ["omega", "alpha", "gamma", "beta", "d5", "d22"]
        if self._dist == "studentt":
            names.append("nu")
        return names

    def _initial_params(self) -> np.ndarray:
        var = np.var(self._returns) if self._returns is not None else 0.0001
        params = [var * 0.02, 0.03, 0.04, 0.85, 0.05, 0.02]
        if self._dist == "studentt":
            params.append(8.0)
        return np.array(params)

    def _bounds(self) -> list[tuple]:
        bounds = [
            (1e-8, 1.0),     # omega
            (1e-8, 0.999),   # alpha
            (1e-8, 0.999),   # gamma
            (1e-8, 0.999),   # beta
            (0.0, 5.0),      # d5
            (0.0, 5.0),      # d22
        ]
        if self._dist == "studentt":
            bounds.append((2.01, 100.0))
        return bounds

    def _conditional_variance(self, params: np.ndarray, returns: np.ndarray) -> np.ndarray:
        omega, alpha, gamma, beta, d5, d22 = (
            params[0], params[1], params[2], params[3], params[4], params[5],
        )
        T = len(returns)
        sigma2 = np.zeros(T)
        r2 = returns ** 2

        sigma2[0] = np.var(returns)

        for t in range(1, T):
            # Multi-scale squared return averages
            start5 = max(0, t - 5)
            start22 = max(0, t - 22)
            ma5 = np.mean(r2[start5:t])
            ma22 = np.mean(r2[start22:t])

            har_omega = omega + d5 * ma5 + d22 * ma22
            indicator = 1.0 if returns[t - 1] < 0 else 0.0
            sigma2[t] = har_omega + alpha * r2[t - 1] + gamma * r2[t - 1] * indicator + beta * sigma2[t - 1]

        return np.maximum(sigma2, 1e-12)

    def forecast(self, steps: int = 1) -> ForecastResult:
        omega, alpha, gamma, beta, d5, d22 = (
            self._params[0], self._params[1], self._params[2],
            self._params[3], self._params[4], self._params[5],
        )
        r2 = self._returns ** 2
        sigma2 = self._conditional_variance(self._params, self._returns)

        ma5 = np.mean(r2[-5:])
        ma22 = np.mean(r2[-22:])
        har_omega = omega + d5 * ma5 + d22 * ma22

        last_sigma2 = sigma2[-1]
        last_r2 = r2[-1]
        indicator = 1.0 if self._returns[-1] < 0 else 0.0
        next_sigma2 = har_omega + alpha * last_r2 + gamma * last_r2 * indicator + beta * last_sigma2

        return ForecastResult(
            date=datetime.now(),
            point_forecast=max(next_sigma2, 1e-12) ** 0.5,
            variance_forecast=max(next_sigma2, 1e-12),
            distribution_params=dict(zip(self._param_names(), self._params)),
            model_name=self.get_name(),
            fit_info={
                "converged": self._fit_result.success if self._fit_result else False,
                "loglik": -self._fit_result.fun if self._fit_result else None,
                "har_omega": har_omega,
                "d5": d5,
                "d22": d22,
                "ma5_r2": ma5,
                "ma22_r2": ma22,
            },
        )


@ModelRegistry.register("cgarch")
class ComponentGARCH(CustomVolModel):
    """Component GARCH (Engle & Lee 1999) with GJR asymmetry.

    Decomposes volatility into long-run trend (q_t) and short-run dynamics.

    sigma2_t = q_t + alpha*(r²_{t-1} - q_{t-1}) + gamma*(r²_{t-1}*I_{t-1} - q_{t-1}/2)
                    + beta*(sigma2_{t-1} - q_{t-1})
    q_t = omega + rho*q_{t-1} + phi*(r²_{t-1} - sigma2_{t-1})

    Key parameters:
    - rho: long-run persistence (close to 1 = very persistent trend)
    - phi: sensitivity of trend to recent shocks
    - alpha, gamma, beta: short-run dynamics (like GJR)
    """

    def __init__(self, dist: str = "normal"):
        super().__init__(dist=dist)

    def get_name(self) -> str:
        return f"CGARCH-GJR_custom_{self._dist}"

    def get_data_requirement(self) -> DataRequirement:
        return DataRequirement(fields=["returns"], frequency="daily", min_periods=100)

    def _param_names(self) -> list[str]:
        names = ["omega", "alpha", "gamma", "beta", "rho", "phi"]
        if self._dist == "studentt":
            names.append("nu")
        return names

    def _initial_params(self) -> np.ndarray:
        var = np.var(self._returns) if self._returns is not None else 0.0001
        params = [var, 0.05, 0.04, 0.85, 0.99, 0.02]
        if self._dist == "studentt":
            params.append(8.0)
        return np.array(params)

    def _bounds(self) -> list[tuple]:
        bounds = [
            (1e-8, 0.01),    # omega (long-run mean)
            (1e-8, 0.5),     # alpha (short-run ARCH)
            (1e-8, 0.5),     # gamma (short-run asymmetry)
            (0.01, 0.999),   # beta (short-run persistence)
            (0.9, 0.9999),   # rho (long-run persistence, very persistent)
            (1e-8, 0.5),     # phi (trend sensitivity)
        ]
        if self._dist == "studentt":
            bounds.append((2.01, 100.0))
        return bounds

    def _conditional_variance(self, params: np.ndarray, returns: np.ndarray) -> np.ndarray:
        omega, alpha, gamma, beta, rho, phi = (
            params[0], params[1], params[2], params[3], params[4], params[5],
        )
        T = len(returns)
        sigma2 = np.zeros(T)
        q = np.zeros(T)  # long-run component

        # Initialize
        q[0] = omega / (1 - rho) if rho < 1 else np.var(returns)
        sigma2[0] = q[0]

        for t in range(1, T):
            # Long-run component (slow-moving trend)
            q[t] = omega + rho * q[t - 1] + phi * (returns[t - 1] ** 2 - sigma2[t - 1])

            # Short-run dynamics around the trend (GJR-style)
            indicator = 1.0 if returns[t - 1] < 0 else 0.0
            sigma2[t] = (q[t]
                         + alpha * (returns[t - 1] ** 2 - q[t - 1])
                         + gamma * (returns[t - 1] ** 2 * indicator - q[t - 1] / 2)
                         + beta * (sigma2[t - 1] - q[t - 1]))

        return np.maximum(sigma2, 1e-12)

    def forecast(self, steps: int = 1) -> ForecastResult:
        params = self._params
        omega, alpha, gamma, beta, rho, phi = (
            params[0], params[1], params[2], params[3], params[4], params[5],
        )
        sigma2 = self._conditional_variance(params, self._returns)
        r2 = self._returns ** 2

        # Long-run component forecast
        q_last = omega + rho * (sigma2[-1] - omega) + phi * (r2[-1] - sigma2[-1])
        # hmm, need the q sequence. Let me recompute
        T = len(self._returns)
        q = np.zeros(T)
        q[0] = omega / (1 - rho) if rho < 1 else np.var(self._returns)
        for t in range(1, T):
            q[t] = omega + rho * q[t - 1] + phi * (r2[t - 1] - sigma2[t - 1])

        q_next = omega + rho * q[-1] + phi * (r2[-1] - sigma2[-1])
        indicator = 1.0 if self._returns[-1] < 0 else 0.0
        next_sigma2 = (q_next
                       + alpha * (r2[-1] - q[-1])
                       + gamma * (r2[-1] * indicator - q[-1] / 2)
                       + beta * (sigma2[-1] - q[-1]))

        return ForecastResult(
            date=datetime.now(),
            point_forecast=max(next_sigma2, 1e-12) ** 0.5,
            variance_forecast=max(next_sigma2, 1e-12),
            distribution_params=dict(zip(self._param_names(), params)),
            model_name=self.get_name(),
            fit_info={
                "converged": self._fit_result.success if self._fit_result else False,
                "loglik": -self._fit_result.fun if self._fit_result else None,
                "q_last": float(q[-1]),
                "sigma2_last": float(sigma2[-1]),
                "rho": rho,
            },
        )


@ModelRegistry.register("gjr_range")
class GJRRange(CustomVolModel):
    """GJR-GARCH enhanced with lagged range information.

    sigma2_t = omega + alpha*r²_{t-1} + gamma*r²_{t-1}*I(r<0)
               + beta*sigma2_{t-1} + delta*R²_{t-1}

    R_{t-1} = ln(H/L)_{t-1} is the previous day's log range.
    The range carries intraday volatility information that r² alone misses.
    """

    def __init__(self, dist: str = "normal"):
        super().__init__(dist=dist)
        self._ranges = None

    def get_name(self) -> str:
        return f"GJR-Range_custom_{self._dist}"

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
            self._ranges = np.abs(data["returns"].values if "returns" in data.columns else data.iloc[:, 0].values) * np.sqrt(np.pi / 2)
        return super().fit(data)

    def _param_names(self) -> list[str]:
        names = ["omega", "alpha", "gamma", "beta", "delta"]
        if self._dist == "studentt":
            names.append("nu")
        return names

    def _initial_params(self) -> np.ndarray:
        var = np.var(self._returns) if self._returns is not None else 0.0001
        params = [var * 0.03, 0.02, 0.03, 0.88, 0.02]
        if self._dist == "studentt":
            params.append(8.0)
        return np.array(params)

    def _bounds(self) -> list[tuple]:
        bounds = [
            (1e-8, 1.0),     # omega
            (1e-8, 0.5),     # alpha
            (1e-8, 0.5),     # gamma
            (0.01, 0.999),   # beta
            (0.0, 2.0),      # delta (range coefficient)
        ]
        if self._dist == "studentt":
            bounds.append((2.01, 100.0))
        return bounds

    def _conditional_variance(self, params: np.ndarray, returns: np.ndarray) -> np.ndarray:
        omega, alpha, gamma, beta, delta = (
            params[0], params[1], params[2], params[3], params[4],
        )
        T = len(returns)
        sigma2 = np.zeros(T)
        r2 = returns ** 2
        # Use stored ranges if available, else approximate
        ranges = self._ranges if self._ranges is not None and len(self._ranges) == T else np.abs(returns) * np.sqrt(np.pi / 2)
        R2 = ranges ** 2

        sigma2[0] = np.var(returns)
        for t in range(1, T):
            indicator = 1.0 if returns[t - 1] < 0 else 0.0
            sigma2[t] = (omega
                         + alpha * r2[t - 1]
                         + gamma * r2[t - 1] * indicator
                         + beta * sigma2[t - 1]
                         + delta * R2[t - 1])
        return np.maximum(sigma2, 1e-12)

    def forecast(self, steps: int = 1) -> ForecastResult:
        params = self._params
        omega, alpha, gamma, beta, delta = (
            params[0], params[1], params[2], params[3], params[4],
        )
        sigma2 = self._conditional_variance(params, self._returns)
        r2 = self._returns ** 2
        ranges = self._ranges if self._ranges is not None else np.abs(self._returns) * np.sqrt(np.pi / 2)
        R2 = ranges ** 2

        indicator = 1.0 if self._returns[-1] < 0 else 0.0
        next_sigma2 = (omega
                       + alpha * r2[-1]
                       + gamma * r2[-1] * indicator
                       + beta * sigma2[-1]
                       + delta * R2[-1])

        return ForecastResult(
            date=datetime.now(),
            point_forecast=max(next_sigma2, 1e-12) ** 0.5,
            variance_forecast=max(next_sigma2, 1e-12),
            distribution_params=dict(zip(self._param_names(), params)),
            model_name=self.get_name(),
            fit_info={
                "converged": self._fit_result.success if self._fit_result else False,
                "loglik": -self._fit_result.fun if self._fit_result else None,
                "delta": delta,
            },
        )


@ModelRegistry.register("gjr_overnight")
class GJROvernight(CustomVolModel):
    """GJR-GARCH with overnight return squared as additional regressor.

    Motivation: 43% of SPY daily variance comes from overnight moves,
    nearly independent from intraday. Adding overnight_r² as a regressor
    provides an orthogonal volatility signal.

    sigma2_t = omega + alpha*r²_{t-1} + gamma*r²*I(r<0) + beta*sigma2_{t-1}
               + delta*overnight_r²_{t-1}

    Requires: open prices in addition to close prices.
    """

    def __init__(self, dist: str = "normal"):
        super().__init__(dist=dist)
        self._overnight_r2 = None

    def get_name(self) -> str:
        return f"GJR-Overnight_custom_{self._dist}"

    def get_data_requirement(self) -> DataRequirement:
        return DataRequirement(
            fields=["returns", "open", "close"],
            frequency="daily",
            min_periods=100,
        )

    def fit(self, data) -> dict:
        if "open" in data.columns and "close" in data.columns:
            open_p = data["open"].values
            close_p = data["close"].values
            overnight_r = np.zeros(len(data))
            overnight_r[1:] = open_p[1:] / close_p[:-1] - 1
            self._overnight_r2 = overnight_r ** 2
        else:
            self._overnight_r2 = None
        return super().fit(data)

    def _param_names(self) -> list[str]:
        names = ["omega", "alpha", "gamma", "beta", "delta"]
        if self._dist == "studentt":
            names.append("nu")
        return names

    def _initial_params(self) -> np.ndarray:
        var = np.var(self._returns) if self._returns is not None else 0.0001
        params = [var * 0.03, 0.02, 0.03, 0.88, 0.05]
        if self._dist == "studentt":
            params.append(8.0)
        return np.array(params)

    def _bounds(self) -> list[tuple]:
        bounds = [
            (1e-8, 1.0),     # omega
            (1e-8, 0.5),     # alpha
            (1e-8, 0.5),     # gamma
            (0.01, 0.999),   # beta
            (0.0, 2.0),      # delta (overnight sensitivity)
        ]
        if self._dist == "studentt":
            bounds.append((2.01, 100.0))
        return bounds

    def _conditional_variance(self, params: np.ndarray, returns: np.ndarray) -> np.ndarray:
        omega, alpha, gamma, beta, delta = (
            params[0], params[1], params[2], params[3], params[4],
        )
        T = len(returns)
        sigma2 = np.zeros(T)
        r2 = returns ** 2
        on_r2 = self._overnight_r2 if self._overnight_r2 is not None and len(self._overnight_r2) == T else np.zeros(T)

        sigma2[0] = np.var(returns)
        for t in range(1, T):
            indicator = 1.0 if returns[t - 1] < 0 else 0.0
            sigma2[t] = (omega
                         + alpha * r2[t - 1]
                         + gamma * r2[t - 1] * indicator
                         + beta * sigma2[t - 1]
                         + delta * on_r2[t - 1])
        return np.maximum(sigma2, 1e-12)

    def forecast(self, steps: int = 1) -> ForecastResult:
        params = self._params
        omega, alpha, gamma, beta, delta = (
            params[0], params[1], params[2], params[3], params[4],
        )
        sigma2 = self._conditional_variance(params, self._returns)
        r2 = self._returns ** 2
        on_r2 = self._overnight_r2 if self._overnight_r2 is not None else np.zeros(len(self._returns))

        indicator = 1.0 if self._returns[-1] < 0 else 0.0
        next_sigma2 = (omega
                       + alpha * r2[-1]
                       + gamma * r2[-1] * indicator
                       + beta * sigma2[-1]
                       + delta * on_r2[-1])

        return ForecastResult(
            date=datetime.now(),
            point_forecast=max(next_sigma2, 1e-12) ** 0.5,
            variance_forecast=max(next_sigma2, 1e-12),
            distribution_params=dict(zip(self._param_names(), params)),
            model_name=self.get_name(),
            fit_info={
                "converged": self._fit_result.success if self._fit_result else False,
                "loglik": -self._fit_result.fun if self._fit_result else None,
                "delta": delta,
            },
        )
