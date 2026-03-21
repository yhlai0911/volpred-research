"""GARCH-MIDAS model (Engle, Ghysels & Sohn, 2013).

Decomposes volatility into:
  - Short-run component g_t (daily GARCH with GJR asymmetry, mean-reverting to 1)
  - Long-run component tau_t (slowly varying, driven by low-frequency macro variable)

Model:
  sigma2_t = tau_t * g_t

  g_t = (1 - alpha - beta - gamma/2)
        + (alpha + gamma * I_{t-1<0}) * (r²_{t-1} / tau_{t-1})
        + beta * g_{t-1}

  tau_t = m + theta * sum_{k=1}^{K} phi_k(w1, w2) * X_{t-k}

  phi_k(w1, w2) = k^{w1-1} * (K-k)^{w2-1} / sum_j j^{w1-1} * (K-j)^{w2-1}
      (Beta polynomial MIDAS weighting)

Parameters:
  MIDAS:  m (intercept), theta (slope), w1, w2 (Beta weights)
  GARCH:  alpha (ARCH), beta (GARCH persistence), gamma (GJR leverage)

Reference:
  Engle, R.F., Ghysels, E., & Sohn, B. (2013). Stock market volatility and
  macroeconomic fundamentals. Review of Economics and Statistics, 95(3), 776-797.

Usage:
    model = GarchMidas(K=12)
    result = model.fit(returns, macro_data)
    forecast = model.forecast()
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from volpred.core.interfaces import BaseVolatilityModel
from volpred.core.types import DataRequirement, ForecastResult, ModelState
from volpred.models.registry import ModelRegistry


def beta_weights(K: int, w1: float, w2: float) -> np.ndarray:
    """Compute Beta polynomial MIDAS weights.

    phi_k = k^{w1-1} * (K-k)^{w2-1} / sum_j j^{w1-1} * (K-j)^{w2-1}

    Parameters
    ----------
    K : int
        Number of lags.
    w1, w2 : float
        Shape parameters (must be > 0). w1=w2=1 gives uniform weights.
        w1=1, w2>1 gives decaying weights (recent lags get more weight).

    Returns
    -------
    np.ndarray of shape (K,)
        Weights summing to 1, indexed as phi_1 ... phi_K.
    """
    k = np.arange(1, K + 1, dtype=np.float64)
    # Numerically safe computation in log-space
    log_num = (w1 - 1) * np.log(k) + (w2 - 1) * np.log(np.maximum(K - k, 1e-10))
    log_num -= log_num.max()  # shift for numerical stability
    raw = np.exp(log_num)
    total = raw.sum()
    if total < 1e-300:
        return np.ones(K) / K  # fallback to uniform
    return raw / total


def _compute_tau(
    macro_aligned: np.ndarray,
    m: float,
    theta: float,
    w1: float,
    w2: float,
    K: int,
) -> np.ndarray:
    """Compute the long-run component tau_t for each daily observation.

    macro_aligned[t, k] contains the macro variable value at lag k for day t.
    Shape: (T, K)

    tau_t = m + theta * sum_{k=1}^{K} phi_k(w1, w2) * X_{t-k}
    """
    weights = beta_weights(K, w1, w2)  # (K,)
    weighted_x = macro_aligned @ weights  # (T,)
    tau = m + theta * weighted_x
    return np.maximum(tau, 1e-12)  # ensure positivity


def _compute_g(
    returns: np.ndarray,
    tau: np.ndarray,
    alpha: float,
    beta: float,
    gamma: float,
) -> np.ndarray:
    """Compute the short-run GARCH component g_t.

    g_t is the daily GARCH component that mean-reverts to 1.

    g_t = (1 - alpha - beta - gamma/2)
          + (alpha + gamma * I_{r_{t-1}<0}) * (r²_{t-1} / tau_{t-1})
          + beta * g_{t-1}
    """
    T = len(returns)
    g = np.ones(T)  # g_0 = 1 (unconditional mean)
    intercept = 1.0 - alpha - beta - gamma / 2.0

    for t in range(1, T):
        indicator = 1.0 if returns[t - 1] < 0 else 0.0
        r2_scaled = returns[t - 1] ** 2 / max(tau[t - 1], 1e-12)
        g[t] = intercept + (alpha + gamma * indicator) * r2_scaled + beta * g[t - 1]
        g[t] = max(g[t], 1e-6)  # numerical floor

    return g


class GarchMidas(BaseVolatilityModel):
    """GARCH-MIDAS model with Beta polynomial weighting.

    Parameters
    ----------
    K : int
        Number of MIDAS lags (in units of macro_freq). Default 12.
    macro_freq : str
        Frequency of macro variable: 'monthly' (22 trading days per period)
        or 'daily' (1 trading day per period). Default 'monthly'.
    n_starts : int
        Number of random starting points for optimization. Default 3.
    dist : str
        Distribution assumption: 'normal' or 'studentt'. Default 'normal'.
    """

    def __init__(
        self,
        K: int = 12,
        macro_freq: str = "monthly",
        n_starts: int = 3,
        dist: str = "normal",
    ):
        self.K = K
        self.macro_freq = macro_freq
        self.n_starts = n_starts
        self._dist = dist

        # Fitted state
        self._params: Optional[np.ndarray] = None
        self._returns: Optional[np.ndarray] = None
        self._macro_aligned: Optional[np.ndarray] = None
        self._tau: Optional[np.ndarray] = None
        self._g: Optional[np.ndarray] = None
        self._fit_result = None
        self._loglik: Optional[float] = None

    def get_name(self) -> str:
        return f"GARCH-MIDAS(K={self.K})_{self.macro_freq}_{self._dist}"

    def get_data_requirement(self) -> DataRequirement:
        return DataRequirement(
            fields=["returns"],
            frequency="daily",
            min_periods=500,
            external_sources=["macro_variable"],
        )

    # ------------------------------------------------------------------
    # Parameter layout
    # ------------------------------------------------------------------

    @staticmethod
    def _param_names() -> list[str]:
        """Parameter order: [m, theta, w1, w2, alpha, beta, gamma]."""
        return ["m", "theta", "w1", "w2", "alpha", "beta", "gamma"]

    @staticmethod
    def _param_names_studentt() -> list[str]:
        return ["m", "theta", "w1", "w2", "alpha", "beta", "gamma", "nu"]

    def _all_param_names(self) -> list[str]:
        if self._dist == "studentt":
            return self._param_names_studentt()
        return self._param_names()

    # ------------------------------------------------------------------
    # Macro data alignment
    # ------------------------------------------------------------------

    @staticmethod
    def align_macro_to_daily(
        returns_index: pd.DatetimeIndex,
        macro_series: pd.Series,
        K: int,
        macro_freq: str = "monthly",
    ) -> np.ndarray:
        """Create a (T, K) matrix where row t contains K lagged macro values.

        For monthly macro: each daily observation within month M gets the same
        macro value for lag k = number of months back.

        For daily macro (e.g., realized variance): lag k = k trading days back.

        Parameters
        ----------
        returns_index : pd.DatetimeIndex
            Daily dates aligned with returns.
        macro_series : pd.Series
            Macro variable indexed by date.
        K : int
            Number of lags.
        macro_freq : str
            'monthly' or 'daily'.

        Returns
        -------
        np.ndarray of shape (T, K)
        """
        T = len(returns_index)
        macro_aligned = np.zeros((T, K))

        if macro_freq == "monthly":
            # Resample macro to monthly if not already
            macro_monthly = macro_series.copy()
            if not isinstance(macro_monthly.index, pd.DatetimeIndex):
                macro_monthly.index = pd.to_datetime(macro_monthly.index)

            # For each daily date, determine its month and look back K months
            for t_idx, date in enumerate(returns_index):
                year, month = date.year, date.month
                for k in range(K):
                    # Go back k+1 months
                    lag_month = month - (k + 1)
                    lag_year = year
                    while lag_month <= 0:
                        lag_month += 12
                        lag_year -= 1

                    # Find the macro value for this year-month
                    target_period = pd.Period(f"{lag_year}-{lag_month:02d}", freq="M")
                    # Search for matching date
                    mask = (
                        (macro_monthly.index.year == lag_year)
                        & (macro_monthly.index.month == lag_month)
                    )
                    matching = macro_monthly[mask]
                    if len(matching) > 0:
                        macro_aligned[t_idx, k] = matching.iloc[-1]
                    else:
                        # Use nearest available value
                        target_date = pd.Timestamp(f"{lag_year}-{lag_month:02d}-15")
                        diffs = np.abs(
                            (macro_monthly.index - target_date).total_seconds()
                        )
                        nearest_idx = np.argmin(diffs)
                        macro_aligned[t_idx, k] = macro_monthly.iloc[nearest_idx]
        else:
            # Daily frequency: simple lag
            macro_values = macro_series.reindex(returns_index, method="ffill").values
            for t_idx in range(T):
                for k in range(K):
                    lag_idx = t_idx - (k + 1)
                    if lag_idx >= 0:
                        macro_aligned[t_idx, k] = macro_values[lag_idx]
                    else:
                        # Use earliest available
                        macro_aligned[t_idx, k] = macro_values[0]

        return macro_aligned

    # ------------------------------------------------------------------
    # Log-likelihood
    # ------------------------------------------------------------------

    def _neg_log_likelihood(
        self,
        params: np.ndarray,
        returns: np.ndarray,
        macro_aligned: np.ndarray,
    ) -> float:
        """Negative log-likelihood for optimization.

        Parameters
        ----------
        params : array
            [m, theta, w1, w2, alpha, beta, gamma] or with nu appended.
        returns : array of shape (T,)
        macro_aligned : array of shape (T, K)
        """
        m, theta, w1, w2, alpha, beta, gamma = params[:7]
        K = macro_aligned.shape[1]

        # Stationarity / positivity constraints
        if alpha + beta + gamma / 2.0 >= 1.0:
            return 1e10
        if alpha < 0 or beta < 0 or gamma < 0:
            return 1e10
        if w1 <= 0 or w2 <= 0:
            return 1e10

        # Compute tau (long-run)
        tau = _compute_tau(macro_aligned, m, theta, w1, w2, K)
        if np.any(tau <= 0):
            return 1e10

        # Compute g (short-run)
        g = _compute_g(returns, tau, alpha, beta, gamma)

        # Total variance
        sigma2 = tau * g
        sigma2 = np.maximum(sigma2, 1e-12)

        # Log-likelihood
        if self._dist == "normal":
            ll = -0.5 * (
                np.log(2 * np.pi) + np.log(sigma2) + returns ** 2 / sigma2
            )
        elif self._dist == "studentt":
            from scipy.special import gammaln

            nu = params[7]
            if nu <= 2.0:
                return 1e10
            ll = (
                gammaln((nu + 1) / 2)
                - gammaln(nu / 2)
                - 0.5 * np.log(np.pi * (nu - 2))
                - 0.5 * np.log(sigma2)
                - (nu + 1) / 2 * np.log(1 + returns ** 2 / (sigma2 * (nu - 2)))
            )
        else:
            return 1e10

        total_ll = np.sum(ll)
        if not np.isfinite(total_ll):
            return 1e10

        return -total_ll

    def log_likelihood(self) -> float:
        """Return the log-likelihood of the fitted model."""
        if self._loglik is None:
            raise RuntimeError("Model not fitted yet.")
        return self._loglik

    # ------------------------------------------------------------------
    # Fitting
    # ------------------------------------------------------------------

    def fit(
        self,
        returns: np.ndarray | pd.Series,
        macro_data: pd.Series | np.ndarray | None = None,
        returns_index: pd.DatetimeIndex | None = None,
        macro_aligned: np.ndarray | None = None,
    ) -> dict:
        """Fit the GARCH-MIDAS model.

        Parameters
        ----------
        returns : array-like
            Daily log returns.
        macro_data : pd.Series, optional
            Low-frequency macro variable (with DatetimeIndex).
            Not needed if macro_aligned is provided.
        returns_index : pd.DatetimeIndex, optional
            Dates for returns. Required if macro_data is a Series.
        macro_aligned : np.ndarray, optional
            Pre-computed (T, K) matrix of aligned macro lags.
            If provided, macro_data and returns_index are ignored.

        Returns
        -------
        dict with keys: converged, loglik, params, aic, bic, n_params
        """
        if isinstance(returns, pd.Series):
            if returns_index is None:
                returns_index = returns.index
            returns = returns.values

        self._returns = returns.astype(np.float64)
        T = len(returns)

        # Build macro alignment matrix
        if macro_aligned is not None:
            self._macro_aligned = macro_aligned.astype(np.float64)
        elif macro_data is not None:
            if returns_index is None:
                raise ValueError(
                    "returns_index is required when macro_data is a Series"
                )
            self._macro_aligned = self.align_macro_to_daily(
                returns_index, macro_data, self.K, self.macro_freq
            )
        else:
            raise ValueError("Either macro_data or macro_aligned must be provided")

        # Sanity check
        assert self._macro_aligned.shape == (T, self.K), (
            f"macro_aligned shape {self._macro_aligned.shape} != ({T}, {self.K})"
        )

        # --- Multi-start optimization ---
        sample_var = np.var(returns)
        macro_mean = np.mean(self._macro_aligned)
        macro_std = np.std(self._macro_aligned) + 1e-10

        # Build starting points
        starts = []

        # Start 1: Default reasonable parameters
        init1 = np.array([
            sample_var,          # m: intercept ~ sample variance
            0.0,                 # theta: start neutral
            1.0,                 # w1: Beta weight param
            5.0,                 # w2: decaying weights
            0.05,               # alpha
            0.90,               # beta
            0.05,               # gamma (GJR)
        ])
        starts.append(init1)

        # Start 2: Stronger MIDAS effect
        init2 = np.array([
            sample_var * 0.5,
            sample_var / (macro_mean + 1e-10) * 0.5,
            1.0,
            3.0,
            0.08,
            0.85,
            0.08,
        ])
        starts.append(init2)

        # Start 3: Weaker persistence
        init3 = np.array([
            sample_var * 0.8,
            0.0,
            1.5,
            2.0,
            0.10,
            0.80,
            0.04,
        ])
        starts.append(init3)

        # Add Student-t parameter
        if self._dist == "studentt":
            starts = [np.append(s, 8.0) for s in starts]

        # Add random perturbations
        rng = np.random.RandomState(42)
        n_random = max(0, self.n_starts - 3)
        for _ in range(n_random):
            base = starts[0].copy()
            perturbed = base * (1.0 + 0.3 * rng.randn(len(base)))
            starts.append(perturbed)

        # Bounds
        bounds = [
            (1e-10, None),       # m > 0
            (None, None),        # theta: unrestricted
            (1.01, 50.0),        # w1 > 1 (ensures proper weighting)
            (1.01, 50.0),        # w2 > 1
            (1e-6, 0.499),       # alpha
            (1e-6, 0.999),       # beta
            (0.0, 0.499),        # gamma (GJR, allow 0)
        ]
        if self._dist == "studentt":
            bounds.append((2.01, 100.0))

        # Optimize
        best_result = None
        best_nll = np.inf

        for i, x0 in enumerate(starts):
            # Clip to bounds
            x0_clipped = x0.copy()
            for j, (lo, hi) in enumerate(bounds):
                if lo is not None:
                    x0_clipped[j] = max(x0_clipped[j], lo * 1.01)
                if hi is not None:
                    x0_clipped[j] = min(x0_clipped[j], hi * 0.99)

            try:
                result = minimize(
                    fun=self._neg_log_likelihood,
                    x0=x0_clipped,
                    args=(self._returns, self._macro_aligned),
                    method="L-BFGS-B",
                    bounds=bounds,
                    options={"maxiter": 5000, "ftol": 1e-12, "gtol": 1e-8},
                )
                if result.fun < best_nll:
                    best_nll = result.fun
                    best_result = result
            except Exception:
                continue

        if best_result is None:
            raise RuntimeError(
                "GARCH-MIDAS optimization failed for all starting points."
            )

        self._params = best_result.x
        self._fit_result = best_result
        self._loglik = -best_nll

        # Store decomposition
        m, theta, w1, w2, alpha, beta, gamma = self._params[:7]
        self._tau = _compute_tau(
            self._macro_aligned, m, theta, w1, w2, self.K
        )
        self._g = _compute_g(self._returns, self._tau, alpha, beta, gamma)

        # Model selection criteria
        n_params = len(self._params)
        aic = 2 * n_params - 2 * self._loglik
        bic = n_params * np.log(T) - 2 * self._loglik

        param_dict = dict(zip(self._all_param_names(), self._params))

        return {
            "converged": bool(best_result.success),
            "loglik": self._loglik,
            "params": param_dict,
            "aic": aic,
            "bic": bic,
            "n_params": n_params,
            "n_obs": T,
            "persistence": alpha + beta + gamma / 2.0,
        }

    # ------------------------------------------------------------------
    # Forecasting
    # ------------------------------------------------------------------

    def forecast(self, steps: int = 1) -> ForecastResult:
        """One-step-ahead variance forecast.

        sigma2_{T+1} = tau_{T+1} * g_{T+1}

        For tau_{T+1}: uses the most recent macro alignment (assume constant
        for 1-step ahead, or extrapolated).
        For g_{T+1}: standard GARCH recursion.
        """
        if self._params is None:
            raise RuntimeError("Model not fitted yet.")

        m, theta, w1, w2, alpha, beta, gamma = self._params[:7]

        # tau_{T+1}: use the last available tau (macro data doesn't change daily)
        tau_next = self._tau[-1]

        # g_{T+1}: GARCH recursion
        intercept = 1.0 - alpha - beta - gamma / 2.0
        last_r = self._returns[-1]
        indicator = 1.0 if last_r < 0 else 0.0
        r2_scaled = last_r ** 2 / max(self._tau[-1], 1e-12)
        g_next = intercept + (alpha + gamma * indicator) * r2_scaled + beta * self._g[-1]
        g_next = max(g_next, 1e-6)

        sigma2_next = tau_next * g_next

        return ForecastResult(
            date=datetime.now(),
            point_forecast=sigma2_next ** 0.5,
            variance_forecast=sigma2_next,
            distribution_params=dict(zip(self._all_param_names(), self._params)),
            model_name=self.get_name(),
            fit_info={
                "converged": (
                    self._fit_result.success if self._fit_result else False
                ),
                "loglik": self._loglik,
                "tau_last": float(self._tau[-1]),
                "g_last": float(self._g[-1]),
                "tau_next": float(tau_next),
                "g_next": float(g_next),
            },
        )

    # ------------------------------------------------------------------
    # Accessors for decomposition
    # ------------------------------------------------------------------

    def get_conditional_variance(self) -> np.ndarray:
        """Return the full conditional variance series sigma2_t = tau_t * g_t."""
        if self._tau is None or self._g is None:
            raise RuntimeError("Model not fitted yet.")
        return self._tau * self._g

    def get_tau(self) -> np.ndarray:
        """Return the long-run component tau_t."""
        if self._tau is None:
            raise RuntimeError("Model not fitted yet.")
        return self._tau.copy()

    def get_g(self) -> np.ndarray:
        """Return the short-run component g_t."""
        if self._g is None:
            raise RuntimeError("Model not fitted yet.")
        return self._g.copy()

    def get_midas_weights(self) -> np.ndarray:
        """Return the MIDAS Beta polynomial weights."""
        if self._params is None:
            raise RuntimeError("Model not fitted yet.")
        w1, w2 = self._params[2], self._params[3]
        return beta_weights(self.K, w1, w2)

    def get_tunable_params(self) -> dict:
        return {
            "K": {"type": "int", "range": [6, 36], "current": self.K},
            "macro_freq": {
                "type": "categorical",
                "options": ["monthly", "daily"],
                "current": self.macro_freq,
            },
            "dist": {
                "type": "categorical",
                "options": ["normal", "studentt"],
                "current": self._dist,
            },
        }

    def get_state(self) -> ModelState:
        return ModelState(
            model_name=self.get_name(),
            params={
                "fitted": dict(zip(self._all_param_names(), self._params.tolist()))
                if self._params is not None
                else {}
            },
            config={
                "K": self.K,
                "macro_freq": self.macro_freq,
                "dist": self._dist,
            },
            timestamp=datetime.now(),
        )


# Also register with the model registry for CLI use
@ModelRegistry.register("garch_midas")
class RegisteredGarchMidas(GarchMidas):
    """Registry wrapper so GarchMidas can be invoked via the volpred CLI.

    Note: this model needs macro data, so the standard CLI `fit(data)` path
    will use daily squared returns as a proxy for the macro variable (RV-based).
    """

    def fit(self, data, **kwargs) -> dict:
        """Fit using either provided macro_data or auto-computed monthly RV.

        If `data` is a DataFrame with a 'returns' column and no macro_data
        is passed, this computes monthly realized variance from squared daily
        returns as the MIDAS driving variable.
        """
        if isinstance(data, np.ndarray):
            returns = data
            returns_index = pd.date_range(
                "2000-01-01", periods=len(data), freq="B"
            )
        elif isinstance(data, pd.DataFrame):
            if "returns" in data.columns:
                returns = data["returns"].values
            else:
                returns = data.iloc[:, 0].values
            returns_index = data.index
        elif isinstance(data, pd.Series):
            returns = data.values
            returns_index = data.index
        else:
            raise ValueError(f"Unsupported data type: {type(data)}")

        macro_data = kwargs.get("macro_data")
        macro_aligned = kwargs.get("macro_aligned")

        if macro_data is None and macro_aligned is None:
            # Auto-compute monthly realized variance from squared returns
            ret_series = pd.Series(returns, index=returns_index)
            rv_daily = ret_series ** 2
            rv_monthly = rv_daily.resample("ME").sum()
            rv_monthly = rv_monthly[rv_monthly > 0]
            macro_data = rv_monthly
            self.macro_freq = "monthly"

        return super().fit(
            returns=returns,
            macro_data=macro_data,
            returns_index=returns_index,
            macro_aligned=macro_aligned,
        )
