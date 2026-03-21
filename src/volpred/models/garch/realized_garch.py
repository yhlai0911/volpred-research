"""Realized GARCH model (Hansen, Huang & Shek, 2012, JAE).

Log-linear specification:

    Return equation:      r_t = sqrt(h_t) * z_t
    GARCH equation:       log(h_t) = omega + beta * log(h_{t-1}) + gamma * log(x_{t-1})
    Measurement equation: log(x_t) = xi + phi * log(h_t) + tau1 * z_t + tau2 * (z_t^2 - 1) + u_t

Where:
    r_t  = daily log return
    h_t  = conditional variance (latent)
    x_t  = realized variance from intraday data
    z_t  = r_t / sqrt(h_t) = standardized residual
    u_t  ~ iid N(0, sigma_u^2) = measurement noise
    tau(z) = tau1*z + tau2*(z^2-1) is the leverage function

Parameters: omega, beta, gamma, xi, phi, tau1, tau2, sigma_u^2
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import numpy as np
from scipy.optimize import minimize

from volpred.core.interfaces import BaseVolatilityModel
from volpred.core.types import DataRequirement, ForecastResult, ModelState
from volpred.models.registry import ModelRegistry


@ModelRegistry.register("realized_garch")
class RealizedGARCH(BaseVolatilityModel):
    """Realized GARCH (Hansen, Huang & Shek, 2012).

    Jointly models daily returns and realized variance using a log-linear
    specification.  Estimation is by Quasi-Maximum Likelihood (Gaussian).

    Parameters
    ----------
    n_starts : int
        Number of random starting points for multi-start optimization.
    """

    PARAM_NAMES = ["omega", "beta", "gamma", "xi", "phi", "tau1", "tau2", "sigma_u2"]

    def __init__(self, n_starts: int = 5):
        self.n_starts = n_starts
        # Fitted state
        self._params: Optional[np.ndarray] = None
        self._returns: Optional[np.ndarray] = None
        self._realized_var: Optional[np.ndarray] = None
        self._log_h: Optional[np.ndarray] = None
        self._fit_result = None
        self._loglik_value: Optional[float] = None

    # ------------------------------------------------------------------
    # BaseVolatilityModel interface
    # ------------------------------------------------------------------

    def get_name(self) -> str:
        return "RealizedGARCH(1,1)_HHS2012"

    def get_data_requirement(self) -> DataRequirement:
        return DataRequirement(
            fields=["returns", "realized_var"],
            frequency="daily",
            min_periods=30,
            external_sources=["intraday_5min"],
        )

    def fit(self, returns: np.ndarray, realized_var: np.ndarray) -> dict:
        """Fit the Realized GARCH model by joint QML.

        Parameters
        ----------
        returns : array-like, shape (T,)
            Daily log returns (decimal, NOT percentage).
        realized_var : array-like, shape (T,)
            Daily realized variance computed from intraday data.

        Returns
        -------
        dict
            Fit summary with keys: converged, loglik, params, n_iter.
        """
        returns = np.asarray(returns, dtype=np.float64)
        realized_var = np.asarray(realized_var, dtype=np.float64)

        if len(returns) != len(realized_var):
            raise ValueError(
                f"returns ({len(returns)}) and realized_var ({len(realized_var)}) "
                "must have the same length."
            )

        # Store for later use
        self._returns = returns
        self._realized_var = realized_var
        T = len(returns)

        # Log-transform realized variance (with floor for safety)
        log_x = np.log(np.maximum(realized_var, 1e-20))

        # ---- Bounds ----
        # omega: unrestricted (log-linear), but keep reasonable
        # beta:  (0, 0.999)   persistence
        # gamma: (0, 0.999)   realized var effect
        # xi:    unrestricted  measurement intercept
        # phi:   (0, 2.0)     measurement loading
        # tau1:  (-1, 1)      leverage linear
        # tau2:  (-1, 1)      leverage quadratic
        # sigma_u2: (1e-10, 10) measurement noise variance
        bounds = [
            (-20.0, 5.0),     # omega
            (0.001, 0.999),   # beta
            (0.001, 0.999),   # gamma
            (-20.0, 5.0),     # xi
            (0.01, 2.0),      # phi
            (-1.0, 1.0),      # tau1
            (-1.0, 1.0),      # tau2
            (1e-10, 10.0),    # sigma_u2
        ]

        # ---- Initial parameter guesses ----
        sample_var = np.var(returns)
        log_sample_var = np.log(max(sample_var, 1e-20))
        mean_log_x = np.mean(log_x)

        def make_init():
            """Construct a reasonable starting point."""
            beta0 = 0.6
            gamma0 = 0.3
            omega0 = mean_log_x * (1 - beta0 - gamma0)
            xi0 = mean_log_x * (1 - 1.0)  # phi=1 baseline
            phi0 = 1.0
            tau1_0 = -0.05  # slight leverage
            tau2_0 = 0.05
            resid_log_x = log_x - xi0 - phi0 * mean_log_x
            sigma_u2_0 = float(np.var(resid_log_x)) if T > 1 else 0.1
            sigma_u2_0 = max(sigma_u2_0, 1e-6)
            return np.array([omega0, beta0, gamma0, xi0, phi0, tau1_0, tau2_0, sigma_u2_0])

        init = make_init()

        # ---- Objective (negative joint log-likelihood) ----
        def neg_loglik(params):
            return -self._joint_loglikelihood(params, returns, log_x, T)

        # ---- Multi-start optimization ----
        best_result = None
        rng = np.random.RandomState(42)

        starts = [init]
        for _ in range(self.n_starts - 1):
            perturbed = init.copy()
            perturbed[0] += rng.randn() * 1.0       # omega
            perturbed[1] = np.clip(init[1] + rng.randn() * 0.15, 0.05, 0.95)  # beta
            perturbed[2] = np.clip(init[2] + rng.randn() * 0.15, 0.05, 0.95)  # gamma
            perturbed[3] += rng.randn() * 1.0       # xi
            perturbed[4] = np.clip(init[4] + rng.randn() * 0.3, 0.1, 1.9)     # phi
            perturbed[5] = np.clip(rng.randn() * 0.1, -0.5, 0.5)              # tau1
            perturbed[6] = np.clip(rng.randn() * 0.1, -0.5, 0.5)              # tau2
            perturbed[7] = np.clip(init[7] * (1 + rng.randn() * 0.5), 1e-6, 5.0)  # sigma_u2
            starts.append(perturbed)

        for x0 in starts:
            for method in ["L-BFGS-B", "Nelder-Mead"]:
                try:
                    if method == "L-BFGS-B":
                        result = minimize(
                            neg_loglik, x0, method="L-BFGS-B",
                            bounds=bounds,
                            options={"maxiter": 5000, "ftol": 1e-12, "gtol": 1e-8},
                        )
                    else:
                        # Nelder-Mead doesn't support bounds directly;
                        # clip inside objective instead
                        def neg_loglik_clipped(params):
                            clipped = np.array([
                                np.clip(params[i], bounds[i][0], bounds[i][1])
                                for i in range(len(params))
                            ])
                            penalty = 1e6 * np.sum((params - clipped) ** 2)
                            return -self._joint_loglikelihood(clipped, returns, log_x, T) + penalty

                        result = minimize(
                            neg_loglik_clipped, x0, method="Nelder-Mead",
                            options={"maxiter": 10000, "xatol": 1e-10, "fatol": 1e-10},
                        )
                        # Clip final params
                        result.x = np.array([
                            np.clip(result.x[i], bounds[i][0], bounds[i][1])
                            for i in range(len(result.x))
                        ])

                    if np.isfinite(result.fun):
                        if best_result is None or result.fun < best_result.fun:
                            best_result = result
                except Exception:
                    continue

        if best_result is None:
            raise RuntimeError("All optimization attempts failed.")

        self._params = best_result.x
        self._fit_result = best_result
        self._loglik_value = -best_result.fun

        # Compute and store the conditional variance path
        self._log_h = self._compute_log_h(self._params, returns, log_x, T)

        param_dict = dict(zip(self.PARAM_NAMES, self._params))
        return {
            "converged": bool(getattr(best_result, "success", True)),
            "loglik": self._loglik_value,
            "params": param_dict,
            "n_iter": int(getattr(best_result, "nit", 0)),
        }

    def forecast(self, horizon: int = 1) -> ForecastResult:
        """One-step-ahead forecast of conditional variance.

        Uses the last fitted log(h_t) and log(x_t) to project forward.
        """
        if self._params is None:
            raise RuntimeError("Model has not been fitted yet.")

        omega, beta, gamma = self._params[0], self._params[1], self._params[2]
        log_x = np.log(np.maximum(self._realized_var, 1e-20))

        # One-step: log(h_{T+1}) = omega + beta * log(h_T) + gamma * log(x_T)
        log_h_next = omega + beta * self._log_h[-1] + gamma * log_x[-1]
        h_next = np.exp(log_h_next)

        # Multi-step (if needed): iterate using E[log(x_{t+s})] = xi + phi * log(h_{t+s})
        if horizon > 1:
            xi, phi = self._params[3], self._params[4]
            log_h_s = log_h_next
            for _ in range(horizon - 1):
                E_log_x = xi + phi * log_h_s  # E[log(x)] (tau terms average to 0)
                log_h_s = omega + beta * log_h_s + gamma * E_log_x
            h_next = np.exp(log_h_s)

        return ForecastResult(
            date=datetime.now(),
            point_forecast=float(h_next ** 0.5),
            variance_forecast=float(h_next),
            distribution_params=dict(zip(self.PARAM_NAMES, self._params)),
            model_name=self.get_name(),
            fit_info={
                "converged": bool(getattr(self._fit_result, "success", True)),
                "loglik": self._loglik_value,
            },
        )

    def log_likelihood(self) -> float:
        """Return the fitted joint log-likelihood value."""
        if self._loglik_value is None:
            raise RuntimeError("Model has not been fitted yet.")
        return self._loglik_value

    def get_conditional_variance(self) -> np.ndarray:
        """Return the in-sample conditional variance series h_t."""
        if self._log_h is None:
            raise RuntimeError("Model has not been fitted yet.")
        return np.exp(self._log_h)

    def get_fitted_log_h(self) -> np.ndarray:
        """Return log(h_t) series (useful for diagnostics)."""
        if self._log_h is None:
            raise RuntimeError("Model has not been fitted yet.")
        return self._log_h.copy()

    def get_measurement_residuals(self) -> np.ndarray:
        """Return u_t = log(x_t) - xi - phi*log(h_t) - tau(z_t).

        Useful for checking the iid assumption of the measurement equation.
        """
        if self._params is None:
            raise RuntimeError("Model has not been fitted yet.")

        xi, phi, tau1, tau2 = (
            self._params[3], self._params[4], self._params[5], self._params[6]
        )
        log_x = np.log(np.maximum(self._realized_var, 1e-20))
        z = self._returns / np.sqrt(np.maximum(np.exp(self._log_h), 1e-20))

        tau_z = tau1 * z + tau2 * (z ** 2 - 1)
        u = log_x - xi - phi * self._log_h - tau_z
        return u

    # ------------------------------------------------------------------
    # State serialization
    # ------------------------------------------------------------------

    def get_state(self) -> ModelState:
        return ModelState(
            model_name=self.get_name(),
            params={
                "fitted": dict(zip(self.PARAM_NAMES, self._params.tolist()))
                if self._params is not None
                else {}
            },
            config={"n_starts": self.n_starts},
            timestamp=datetime.now(),
        )

    def load_state(self, state: ModelState) -> None:
        if state.params.get("fitted"):
            self._params = np.array(
                [state.params["fitted"][n] for n in self.PARAM_NAMES]
            )

    def get_tunable_params(self) -> dict:
        return {
            "n_starts": {
                "type": "int",
                "range": [1, 20],
                "current": self.n_starts,
            },
        }

    # ------------------------------------------------------------------
    # Internal: log-likelihood computation
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_log_h(
        params: np.ndarray,
        returns: np.ndarray,
        log_x: np.ndarray,
        T: int,
    ) -> np.ndarray:
        """Compute the log conditional variance path log(h_t).

        Parameters
        ----------
        params : (8,) array
            [omega, beta, gamma, xi, phi, tau1, tau2, sigma_u2]
        returns : (T,) array
            Daily log returns.
        log_x : (T,) array
            Log realized variance.
        T : int
            Number of observations.

        Returns
        -------
        log_h : (T,) array
        """
        omega, beta, gamma = params[0], params[1], params[2]

        log_h = np.empty(T)
        # Initialize: use sample variance of returns
        sample_var = np.var(returns) if T > 1 else np.exp(log_x[0])
        log_h[0] = np.log(max(sample_var, 1e-20))

        for t in range(1, T):
            log_h[t] = omega + beta * log_h[t - 1] + gamma * log_x[t - 1]

        return log_h

    @staticmethod
    def _joint_loglikelihood(
        params: np.ndarray,
        returns: np.ndarray,
        log_x: np.ndarray,
        T: int,
    ) -> float:
        """Compute the joint Gaussian quasi-log-likelihood.

        Joint LL = sum_t [ ll_return(t) + ll_measurement(t) ]

        ll_return(t)      = -0.5 * (log(h_t) + r_t^2 / h_t)
        ll_measurement(t) = -0.5 * (log(sigma_u^2) + u_t^2 / sigma_u^2)

        where u_t = log(x_t) - xi - phi*log(h_t) - tau1*z_t - tau2*(z_t^2 - 1)
        """
        omega, beta, gamma, xi, phi, tau1, tau2, sigma_u2 = params

        # Safety checks
        if sigma_u2 <= 0 or beta <= 0 or gamma <= 0:
            return -1e20

        # Compute log(h_t) path
        log_h = np.empty(T)
        sample_var = np.var(returns) if T > 1 else np.exp(log_x[0])
        log_h[0] = np.log(max(sample_var, 1e-20))

        for t in range(1, T):
            log_h[t] = omega + beta * log_h[t - 1] + gamma * log_x[t - 1]

        h = np.exp(log_h)
        # Floor h to avoid division by zero
        h = np.maximum(h, 1e-20)

        # Standardized residuals
        z = returns / np.sqrt(h)

        # Return equation log-likelihood (Gaussian, dropping constant)
        ll_return = -0.5 * (log_h + returns ** 2 / h)

        # Measurement equation
        tau_z = tau1 * z + tau2 * (z ** 2 - 1)
        u = log_x - xi - phi * log_h - tau_z

        ll_meas = -0.5 * (np.log(sigma_u2) + u ** 2 / sigma_u2)

        total_ll = np.sum(ll_return) + np.sum(ll_meas)

        if not np.isfinite(total_ll):
            return -1e20

        return total_ll


# ======================================================================
# Standalone pilot test
# ======================================================================

if __name__ == "__main__":
    import pandas as pd
    from pathlib import Path

    print("=" * 70)
    print("Realized GARCH Pilot Test")
    print("Hansen, Huang & Shek (2012, JAE) - Log-Linear Specification")
    print("=" * 70)

    # ---- Load realized variance from pre-computed daily RV file ----
    base = Path(__file__).resolve().parents[4]  # project root
    rv_path = base / "data" / "intraday" / "SPY_daily_rv.csv"

    if not rv_path.exists():
        print(f"ERROR: {rv_path} not found.")
        raise SystemExit(1)

    rv_df = pd.read_csv(rv_path, index_col=0, parse_dates=True)
    rv_df.columns = ["rv"]
    print(f"\nLoaded {len(rv_df)} days of realized variance")
    print(f"Date range: {rv_df.index[0].date()} to {rv_df.index[-1].date()}")
    print(f"Mean RV: {rv_df['rv'].mean():.6e}")
    print(f"Mean realized vol (annualized): {(rv_df['rv'].mean() * 252)**0.5:.4f}")

    # ---- Get daily returns from yfinance ----
    try:
        import yfinance as yf
    except ImportError:
        print("ERROR: yfinance not installed. Run: pip install yfinance")
        raise SystemExit(1)

    start_date = rv_df.index[0] - pd.Timedelta(days=5)
    end_date = rv_df.index[-1] + pd.Timedelta(days=5)

    print(f"\nDownloading SPY daily data from yfinance...")
    spy = yf.download("SPY", start=start_date, end=end_date, progress=False)
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    spy.index = spy.index.tz_localize(None)

    # Compute daily log returns
    spy["log_return"] = np.log(spy["Close"] / spy["Close"].shift(1))
    spy = spy.dropna(subset=["log_return"])

    # Align dates
    common_dates = rv_df.index.intersection(spy.index)
    print(f"Common dates: {len(common_dates)}")

    if len(common_dates) < 20:
        print(f"WARNING: Only {len(common_dates)} common dates. Need at least 20.")
        raise SystemExit(1)

    returns = spy.loc[common_dates, "log_return"].values
    realized_var = rv_df.loc[common_dates, "rv"].values

    print(f"\nData summary:")
    print(f"  Returns:  mean={returns.mean():.6f}, std={returns.std():.6f}")
    print(f"  RV:       mean={realized_var.mean():.6e}, min={realized_var.min():.6e}, max={realized_var.max():.6e}")

    # ---- Fit Realized GARCH ----
    print("\n" + "-" * 70)
    print("Fitting Realized GARCH...")
    print("-" * 70)

    model = RealizedGARCH(n_starts=5)
    result = model.fit(returns, realized_var)

    print(f"\nConverged: {result['converged']}")
    print(f"Log-likelihood: {result['loglik']:.4f}")
    print(f"Iterations: {result['n_iter']}")
    print(f"\nEstimated parameters:")
    for name, val in result["params"].items():
        print(f"  {name:10s} = {val:12.6f}")

    # Persistence
    beta_hat = result["params"]["beta"]
    gamma_hat = result["params"]["gamma"]
    phi_hat = result["params"]["phi"]
    persistence = beta_hat + gamma_hat * phi_hat
    print(f"\n  Persistence (beta + gamma*phi) = {persistence:.4f}")

    # ---- Compare h_t vs x_t ----
    h_t = model.get_conditional_variance()
    print(f"\n" + "-" * 70)
    print("Comparison: model h_t vs realized x_t")
    print("-" * 70)
    print(f"  Corr(h_t, x_t):       {np.corrcoef(h_t, realized_var)[0,1]:.4f}")
    print(f"  Corr(log h_t, log x): {np.corrcoef(np.log(h_t), np.log(realized_var))[0,1]:.4f}")
    print(f"  Mean(h_t):             {h_t.mean():.6e}")
    print(f"  Mean(x_t):             {realized_var.mean():.6e}")
    print(f"  Ratio mean(h/x):       {(h_t / realized_var).mean():.4f}")

    # QLIKE
    qlike = np.mean(realized_var / h_t - np.log(realized_var / h_t) - 1)
    print(f"  QLIKE(x_t | h_t):     {qlike:.6f}")

    # ---- Measurement equation diagnostics ----
    u_t = model.get_measurement_residuals()
    print(f"\nMeasurement residuals u_t:")
    print(f"  Mean:  {u_t.mean():.6f}")
    print(f"  Std:   {u_t.std():.6f}")
    print(f"  sigma_u (estimated): {result['params']['sigma_u2']**0.5:.6f}")

    # ---- One-step forecast ----
    fc = model.forecast(horizon=1)
    print(f"\nOne-step-ahead forecast:")
    print(f"  h_{{T+1}}:    {fc.variance_forecast:.6e}")
    print(f"  vol_{{T+1}}:  {fc.point_forecast:.6f}")
    print(f"  annualized: {fc.point_forecast * 252**0.5:.4f}")

    # ---- Compare with GJR-GARCH ----
    print(f"\n" + "-" * 70)
    print("Comparison with GJR-GARCH (arch package)")
    print("-" * 70)
    try:
        from arch import arch_model

        ret_pct = returns * 100
        gjr = arch_model(ret_pct, vol="GARCH", p=1, o=1, q=1, dist="normal", mean="Zero", rescale=False)
        gjr_res = gjr.fit(disp="off", show_warning=False)

        gjr_var = gjr_res.conditional_volatility ** 2 / 10000  # back to decimal
        gjr_forecast_var = gjr_res.forecast(horizon=1).variance.iloc[-1, 0] / 10000

        print(f"  GJR-GARCH log-likelihood: {gjr_res.loglikelihood:.4f}")
        print(f"  GJR-GARCH params: {dict(gjr_res.params)}")
        print(f"\n  Corr(h_RG, h_GJR): {np.corrcoef(h_t, gjr_var)[0,1]:.4f}")
        print(f"  QLIKE(x|h_RG):     {qlike:.6f}")
        qlike_gjr = np.mean(realized_var / gjr_var - np.log(realized_var / gjr_var) - 1)
        print(f"  QLIKE(x|h_GJR):    {qlike_gjr:.6f}")

        if qlike < qlike_gjr:
            print(f"\n  >>> Realized GARCH wins by QLIKE ({qlike:.6f} < {qlike_gjr:.6f})")
        else:
            print(f"\n  >>> GJR-GARCH wins by QLIKE ({qlike_gjr:.6f} < {qlike:.6f})")

        print(f"\n  Forecast comparison:")
        print(f"    Realized GARCH h_{{T+1}}: {fc.variance_forecast:.6e}  (vol: {fc.point_forecast:.6f})")
        print(f"    GJR-GARCH h_{{T+1}}:      {gjr_forecast_var:.6e}  (vol: {gjr_forecast_var**0.5:.6f})")

    except ImportError:
        print("  arch package not installed, skipping GJR comparison.")
    except Exception as e:
        print(f"  GJR comparison failed: {e}")

    print(f"\n{'=' * 70}")
    print("Pilot test complete.")
    print(f"NOTE: Only {len(common_dates)} days available.")
    print("Realized GARCH typically needs 252+ days for reliable estimation.")
    print(f"{'=' * 70}")
