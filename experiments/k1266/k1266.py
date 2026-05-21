"""K1266: Multivariate Rough Volatility (rough Bergomi) on SPY/QQQ/IWM.

Test whether multivariate rough volatility framework (arXiv:2412.14353)
beats (i) univariate rough Bergomi and (ii) DCC-GARCH benchmarks on a
3-asset US equity ETF panel (SPY, QQQ, IWM).

Literature basis
----------------
- arXiv:2412.14353 (2024-12) "Multivariate rough volatility" — extends
  univariate Rough Bergomi (Bayer-Friz-Gatheral 2016) to multi-asset
  setting via correlated rough innovations.
- Bayer, Friz, Gatheral (2016) "Pricing under rough volatility", QF.
- Gatheral, Jaisson, Rosenbaum (2018) "Volatility is rough", QF.
- Engle (2002) DCC-GARCH, JBES.

Prior (this repo, 7+ ML/rough-vol ceiling failures)
----------------------------------------------------
- K785, K816, K816v2, K784, K787, K806, K1129, K1263:
  every "frontier" method (NN, transformer, multivariate fBm, rough HAR)
  failed to beat GJR/EWMA on QLIKE for daily vol.
- K806 (multivariate fBm) NULL across SPY/QQQ/GLD/0050.TW/BTC.
- K973: SPY daily R/S Hurst centered on 0.5 → rough vol largely
  unmeasurable at daily close-to-close horizon.

Differentiation vs K806
-----------------------
K806 used multivariate fractional Brownian motion (mfBm) with
H estimated per-asset and cross-asset H(t) regressors.
K1266 uses rough Bergomi (RFSV) spec — log-vol driven by
fractional Ornstein-Uhlenbeck-like process — and tests forecast
covariance matrix Σ_forecast against realized Σ on a 3-ETF panel.
Different spec, different evaluation (joint Σ, not per-asset r²).

Hypothesis
----------
H_alt: multivariate rough vol gives lower multivariate QLIKE than
       DCC-GARCH by >2% with DM-HLN p < 0.10, sustained in ≥2/3
       sub-periods (2020 / 2022 / others).
H_null (prior-favored, ~95%): no improvement; method joins the
       7+ ceiling failures.

Lookahead controls
------------------
- All forecasts use t-1 history; evaluated at t.
- Code uses .shift(1) on signal series; no contemporaneous regressor.
- DCC and rough-vol params fit on IS only (2010-2018); OOS expanding
  not refit (frozen-IS evaluation, standard for benchmark comparison).

Seeds
-----
All MC sampling and bootstrap fixed at seed=42.

Author: Claude (background worktree agent), 2026-05-03
"""
from __future__ import annotations

import json
import sys
import warnings
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy import optimize, stats

warnings.filterwarnings("ignore")

SEED = 42
np.random.seed(SEED)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
EXP_DIR = Path(__file__).resolve().parent
DATA_DIR = EXP_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

ASSETS = ["SPY", "QQQ", "IWM"]
START = "2010-01-01"
END = "2026-04-30"
IS_END = "2018-12-31"
OOS_START = "2019-01-01"


# -----------------------------------------------------------------------------
# Data
# -----------------------------------------------------------------------------
def load_returns() -> pd.DataFrame:
    """Load daily log returns for SPY/QQQ/IWM. Cache to data/."""
    cache = DATA_DIR / "etf_returns.csv"
    if cache.exists():
        df = pd.read_csv(cache, index_col=0, parse_dates=True)
        if all(a in df.columns for a in ASSETS) and len(df) > 3000:
            return df[ASSETS].dropna()

    import yfinance as yf

    print(f"Fetching {ASSETS} from yfinance {START}..{END} (auto_adjust=False)")
    raw = yf.download(
        ASSETS, start=START, end=END, auto_adjust=False, progress=False
    )
    # yfinance returns multi-index when multiple tickers; pick "Close" (raw)
    if isinstance(raw.columns, pd.MultiIndex):
        prices = raw["Close"][ASSETS]
    else:
        prices = raw[["Close"]].rename(columns={"Close": ASSETS[0]})

    prices = prices.dropna()
    rets = np.log(prices / prices.shift(1)).dropna()
    rets.to_csv(cache)
    print(f"  cached {len(rets)} rows {rets.index[0].date()}..{rets.index[-1].date()}")
    return rets


# -----------------------------------------------------------------------------
# Realized variance proxy (squared returns)
# -----------------------------------------------------------------------------
def realized_var(rets: pd.DataFrame) -> pd.DataFrame:
    """Daily RV proxy = r^2 (Patton-robust under MSE/QLIKE)."""
    return rets.pow(2)


# -----------------------------------------------------------------------------
# Hurst estimation (variogram method, robust for rough vol)
# -----------------------------------------------------------------------------
def estimate_hurst(log_rv: np.ndarray, max_lag: int = 30) -> float:
    """Variogram-based Hurst from log-RV path. Gatheral et al. (2018)."""
    log_rv = log_rv[np.isfinite(log_rv)]
    if len(log_rv) < 100:
        return np.nan
    lags = np.arange(1, max_lag + 1)
    m = []
    for lag in lags:
        diff = log_rv[lag:] - log_rv[:-lag]
        m.append(np.mean(diff ** 2))
    m = np.array(m)
    valid = m > 0
    if valid.sum() < 5:
        return np.nan
    slope, _, _, _, _ = stats.linregress(np.log(lags[valid]), np.log(m[valid]))
    return float(slope / 2)


# -----------------------------------------------------------------------------
# Univariate Rough Bergomi (simplified RFSV) forecast
# -----------------------------------------------------------------------------
class RoughBergomi:
    """Simplified rough Bergomi: log v_t = xi_0 + eta * X_t,
    where X_t is a fractional process with Hurst H.

    Forecast (1-day-ahead variance):
      v_{t+1} = exp(mu + 0.5 * eta^2 * dt^{2H})
    using rolling-window estimate of unconditional log-vol mean (mu)
    and eta from log-RV variance.
    """

    def __init__(self, H: float = 0.1, window: int = 252):
        self.H = H
        self.window = window
        self.eta = None

    def fit(self, log_rv: np.ndarray) -> "RoughBergomi":
        log_rv = log_rv[np.isfinite(log_rv)]
        # eta calibrated from log-RV stationary std
        self.eta = float(np.std(log_rv))
        return self

    def forecast(self, log_rv_history: np.ndarray) -> float:
        """1-day-ahead variance forecast given history (using last `window` obs)."""
        h = log_rv_history[~np.isnan(log_rv_history)]
        if len(h) < 30:
            return np.exp(np.nanmean(log_rv_history)) if len(h) > 0 else np.nan
        recent = h[-self.window :]
        # Rough Bergomi conditional mean (Bayer-Friz-Gatheral 2016 approx):
        # E[log v_{t+1} | F_t] ≈ alpha * recent_mean + (1-alpha) * long_mean
        # with alpha tied to H. For H<0.5, recent obs weight more.
        alpha = 0.5 + (0.5 - self.H)  # H=0.1 → alpha=0.9 (recent-heavy)
        alpha = float(np.clip(alpha, 0.5, 0.95))
        mean_recent = float(np.mean(recent[-22:]))
        mean_long = float(np.mean(recent))
        mu = alpha * mean_recent + (1 - alpha) * mean_long
        # Convexity adjustment for log-normal
        return float(np.exp(mu + 0.5 * (self.eta ** 2) * (1.0 / 252) ** (2 * self.H)))


# -----------------------------------------------------------------------------
# Multivariate Rough Vol (arXiv:2412.14353 simplified)
# -----------------------------------------------------------------------------
class MultivariateRoughVol:
    """Multivariate rough Bergomi:
    Each asset has its own rough log-vol process with Hurst H_i.
    Innovations across assets correlated via fixed correlation matrix R
    estimated on IS log-RV residuals.

    Forecast:
      sigma_i(t+1)^2 = univariate rough Bergomi forecast for asset i
      Sigma(t+1) = D(t+1) R D(t+1)
    where D = diag(sigma_i) and R is the IS-fitted log-vol-residual
    correlation matrix (constant — simplified spec).

    Note: full arXiv:2412.14353 spec uses time-varying R via DCC-style
    update on rough-vol residuals; we simplify to constant R for tractability,
    which is the canonical baseline test.
    """

    def __init__(self, hursts: Dict[str, float], window: int = 252):
        self.hursts = hursts
        self.window = window
        self.univariates: Dict[str, RoughBergomi] = {}
        self.R = None  # log-vol residual correlation
        self.assets: List[str] = []

    def fit(self, log_rv_df: pd.DataFrame) -> "MultivariateRoughVol":
        self.assets = list(log_rv_df.columns)
        # Univariate fits
        for a in self.assets:
            arr = log_rv_df[a].values
            self.univariates[a] = RoughBergomi(
                H=self.hursts[a], window=self.window
            ).fit(arr)
        # Log-RV residual correlation (subtract rolling 252d mean)
        resid = log_rv_df - log_rv_df.rolling(252, min_periods=60).mean()
        self.R = resid.corr().values
        return self

    def forecast(self, log_rv_history: pd.DataFrame) -> np.ndarray:
        """Return forecast covariance matrix Sigma_{t+1}."""
        sigmas = []
        for a in self.assets:
            v = self.univariates[a].forecast(log_rv_history[a].values)
            sigmas.append(np.sqrt(max(v, 1e-12)))
        D = np.diag(sigmas)
        return D @ self.R @ D


# -----------------------------------------------------------------------------
# DCC-GARCH(1,1) — Engle (2002) multivariate baseline
# -----------------------------------------------------------------------------
def fit_univariate_garch(returns: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Fit GARCH(1,1) via arch package; return conditional std + std resids."""
    from arch import arch_model

    am = arch_model(returns * 100, mean="zero", vol="GARCH", p=1, q=1, dist="normal")
    res = am.fit(disp="off", show_warning=False)
    cv = res.conditional_volatility
    if hasattr(cv, "values"):
        cv = cv.values
    cond_std = np.asarray(cv) / 100.0
    std_resid = returns / cond_std
    return cond_std, std_resid, res


class DCCGarch:
    """DCC-GARCH(1,1) on log returns. Engle (2002).

    Step 1: fit univariate GARCH(1,1) per asset → conditional std D_t
    Step 2: fit dynamic correlation Q_t = (1-a-b)*Q_bar + a*z z' + b*Q_{t-1}
             with a, b > 0, a+b < 1, MLE on standardized residuals
    Step 3: R_t = diag(Q)^{-1/2} Q diag(Q)^{-1/2}, Sigma_t = D R D
    """

    def __init__(self):
        self.uni_models = {}
        self.uni_std_in_sample = None
        self.std_resid = None
        self.Q_bar = None
        self.a = None
        self.b = None
        self.assets: List[str] = []
        # store for OOS
        self.uni_omega = {}
        self.uni_alpha = {}
        self.uni_beta = {}
        self.last_var = {}
        self.last_resid = {}

    def fit(self, returns: pd.DataFrame) -> "DCCGarch":
        self.assets = list(returns.columns)
        T, k = returns.shape
        cond_std = np.zeros((T, k))
        std_resid = np.zeros((T, k))
        for j, a in enumerate(self.assets):
            cs, sr, res = fit_univariate_garch(returns[a].values)
            cond_std[:, j] = cs
            std_resid[:, j] = sr
            # Save params for OOS recursion
            params = res.params
            self.uni_omega[a] = float(params["omega"]) / (100 * 100)  # rescale
            self.uni_alpha[a] = float(params["alpha[1]"])
            self.uni_beta[a] = float(params["beta[1]"])
            self.last_var[a] = float(cs[-1] ** 2)
            self.last_resid[a] = float(returns[a].values[-1])
        self.uni_std_in_sample = cond_std
        self.std_resid = std_resid

        # Q_bar = unconditional correlation of standardized residuals
        Q_bar = np.corrcoef(std_resid.T)
        self.Q_bar = Q_bar

        # MLE for (a, b) on DCC log-likelihood
        def neg_ll(params):
            a, b = params
            if a <= 0 or b <= 0 or a + b >= 0.999:
                return 1e10
            Q_prev = Q_bar.copy()
            ll = 0.0
            for t in range(T):
                z = std_resid[t : t + 1, :].T  # k x 1
                Q_t = (1 - a - b) * Q_bar + a * (z @ z.T) + b * Q_prev
                d_inv_sqrt = 1.0 / np.sqrt(np.diag(Q_t))
                R_t = Q_t * np.outer(d_inv_sqrt, d_inv_sqrt)
                # log-lik contribution (DCC second-stage)
                try:
                    sign, logdet = np.linalg.slogdet(R_t)
                    if sign <= 0:
                        return 1e10
                    R_inv = np.linalg.inv(R_t)
                    quad = float(z.T @ R_inv @ z)
                    ll += -0.5 * (logdet + quad - z.T @ z)
                except np.linalg.LinAlgError:
                    return 1e10
                Q_prev = Q_t
            return -ll

        # multistart for robustness
        best = (0.02, 0.95, np.inf)
        for a0, b0 in [(0.02, 0.95), (0.05, 0.90), (0.01, 0.97), (0.10, 0.80)]:
            try:
                res = optimize.minimize(
                    neg_ll, [a0, b0], method="Nelder-Mead",
                    options={"xatol": 1e-4, "fatol": 1e-3, "maxiter": 200},
                )
                if res.fun < best[2]:
                    best = (res.x[0], res.x[1], res.fun)
            except Exception:
                continue
        self.a = float(best[0])
        self.b = float(best[1])

        # Final Q recursion in-sample to get last Q_T for OOS
        Q_prev = Q_bar.copy()
        for t in range(T):
            z = std_resid[t : t + 1, :].T
            Q_t = (1 - self.a - self.b) * Q_bar + self.a * (z @ z.T) + self.b * Q_prev
            Q_prev = Q_t
        self.Q_last = Q_prev

        return self

    def forecast_one_step(self, last_returns: pd.Series) -> np.ndarray:
        """Forecast Sigma_{t+1} given last observed returns vector.

        Updates univariate GARCH variances and DCC correlation by one step.
        """
        # 1. Update univariate GARCH variance for each asset (recursive)
        sigmas = []
        std_resids = []
        for a in self.assets:
            r_prev = self.last_resid[a]
            v_prev = self.last_var[a]
            v_new = (
                self.uni_omega[a]
                + self.uni_alpha[a] * (r_prev ** 2)
                + self.uni_beta[a] * v_prev
            )
            v_new = max(v_new, 1e-12)
            self.last_var[a] = v_new
            self.last_resid[a] = float(last_returns[a])
            sigmas.append(np.sqrt(v_new))
            std_resids.append(float(last_returns[a]) / np.sqrt(v_new))
        sigmas = np.array(sigmas)
        z = np.array(std_resids).reshape(-1, 1)

        # 2. Update DCC correlation
        Q_new = (
            (1 - self.a - self.b) * self.Q_bar
            + self.a * (z @ z.T)
            + self.b * self.Q_last
        )
        self.Q_last = Q_new
        d_inv = 1.0 / np.sqrt(np.diag(Q_new))
        R_new = Q_new * np.outer(d_inv, d_inv)

        # 3. Sigma = D R D
        D = np.diag(sigmas)
        return D @ R_new @ D


# -----------------------------------------------------------------------------
# Evaluation: QLIKE (per-asset and multivariate) + Frobenius
# -----------------------------------------------------------------------------
def qlike_univariate(forecast: float, realized: float) -> float:
    """Patton (2011) QLIKE on variance proxy. Lower is better."""
    forecast = max(forecast, 1e-12)
    realized = max(realized, 1e-12)
    return realized / forecast - np.log(realized / forecast) - 1


def qlike_multivariate(Sigma_f: np.ndarray, r: np.ndarray) -> float:
    """Multivariate QLIKE (Patton 2011 generalization):
    L = trace(Sigma_f^{-1} R) + log|Sigma_f|
    where R = r r' (rank-1 realized cov proxy from daily returns).
    Lower is better.
    """
    R = np.outer(r, r)
    try:
        S_inv = np.linalg.inv(Sigma_f)
        sign, logdet = np.linalg.slogdet(Sigma_f)
        if sign <= 0:
            return np.inf
        return float(np.trace(S_inv @ R) + logdet)
    except np.linalg.LinAlgError:
        return np.inf


def frobenius(Sigma_f: np.ndarray, R: np.ndarray) -> float:
    return float(np.linalg.norm(Sigma_f - R, ord="fro"))


# -----------------------------------------------------------------------------
# Diebold-Mariano (Harvey-Leybourne-Newbold small-sample correction)
# -----------------------------------------------------------------------------
def dm_hln(losses_a: np.ndarray, losses_b: np.ndarray, h: int = 1) -> Tuple[float, float]:
    """DM test with HLN small-sample correction.

    Returns (t_stat, two-sided p_value).
    Positive t means model A has higher loss (B better).
    """
    d = losses_a - losses_b
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 10:
        return np.nan, np.nan
    mean_d = np.mean(d)
    # Newey-West with lag h-1 (h=1 → no autocov)
    var_d = np.var(d, ddof=1) / n
    if var_d <= 0:
        return np.nan, np.nan
    dm_stat = mean_d / np.sqrt(var_d)
    # HLN correction
    correction = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    t_hln = dm_stat * correction
    # t-distribution with n-1 df
    p = 2 * (1 - stats.t.cdf(abs(t_hln), df=n - 1))
    return float(t_hln), float(p)


# -----------------------------------------------------------------------------
# OOS evaluation loop (frozen IS params, expanding history for forecasts)
# -----------------------------------------------------------------------------
def run_oos(
    rets: pd.DataFrame, log_rv: pd.DataFrame, oos_idx: pd.DatetimeIndex
) -> Dict:
    """Frozen-IS evaluation:
    - Fit DCC, univariate rough Bergomi, multivariate rough vol on IS only.
    - For each OOS day t, produce 1-step-ahead forecast using
      data up to t-1, evaluate against r_t.
    """
    # IS / OOS split
    is_mask = rets.index <= IS_END
    rets_is = rets[is_mask]
    log_rv_is = log_rv[is_mask].replace([np.inf, -np.inf], np.nan).dropna()

    print(f"\nIS: {rets_is.index[0].date()} → {rets_is.index[-1].date()} (n={len(rets_is)})")
    print(f"OOS: {oos_idx[0].date()} → {oos_idx[-1].date()} (n={len(oos_idx)})")

    # ---- Fit Hursts (per asset, IS only) ----
    hursts = {}
    for a in ASSETS:
        h = estimate_hurst(log_rv_is[a].values)
        hursts[a] = h if (h is not None and not np.isnan(h) and 0.01 < h < 0.5) else 0.10
    print(f"\nHurst estimates (IS, variogram): {hursts}")

    # ---- Fit Rough Bergomi (univariate + multivariate) ----
    print("\nFitting univariate Rough Bergomi per asset...")
    uni_rough = {a: RoughBergomi(H=hursts[a]).fit(log_rv_is[a].values) for a in ASSETS}

    print("Fitting multivariate Rough Vol (constant-R simplification)...")
    mv_rough = MultivariateRoughVol(hursts=hursts).fit(log_rv_is)

    # ---- Fit DCC-GARCH ----
    print("Fitting DCC-GARCH(1,1)...")
    dcc = DCCGarch().fit(rets_is)
    print(f"  DCC params: a={dcc.a:.4f}, b={dcc.b:.4f}, a+b={dcc.a+dcc.b:.4f}")

    # ---- OOS loop ----
    n_oos = len(oos_idx)
    # Per-asset losses: shape (n_oos, 3 models, 3 assets)
    qlike_per = {m: {a: np.full(n_oos, np.nan) for a in ASSETS}
                 for m in ["dcc", "uni_rough", "mv_rough"]}
    qlike_mv = {m: np.full(n_oos, np.nan) for m in ["dcc", "uni_rough", "mv_rough"]}
    frob = {m: np.full(n_oos, np.nan) for m in ["dcc", "uni_rough", "mv_rough"]}

    # State for univariate rough (need history up to t-1)
    # We use full-history log_rv up to but not including t (lag-1 correctness).
    log_rv_full = log_rv.copy()

    for i, dt in enumerate(oos_idx):
        # History strictly before dt (lookahead-safe)
        prior_idx = rets.index < dt
        rets_prior = rets.loc[prior_idx]
        log_rv_prior = log_rv_full.loc[prior_idx]
        if len(rets_prior) < 30:
            continue
        last_returns = rets_prior.iloc[-1]
        r_t = rets.loc[dt].values  # realized at t

        # ---- DCC forecast ----
        try:
            Sigma_dcc = dcc.forecast_one_step(last_returns)
        except Exception:
            Sigma_dcc = None

        # ---- Univariate rough Bergomi: per-asset forecast → diagonal Sigma ----
        sigmas_uni = []
        for a in ASSETS:
            v = uni_rough[a].forecast(log_rv_prior[a].values)
            sigmas_uni.append(np.sqrt(max(v, 1e-12)))
        # Univariate model: assume zero correlation (diagonal Sigma)
        Sigma_uni = np.diag(np.array(sigmas_uni) ** 2)

        # ---- Multivariate rough vol forecast ----
        Sigma_mv = mv_rough.forecast(log_rv_prior)

        # ---- Realized rank-1 cov proxy ----
        R_real = np.outer(r_t, r_t)

        # ---- Compute losses ----
        for m_name, Sigma in [
            ("dcc", Sigma_dcc),
            ("uni_rough", Sigma_uni),
            ("mv_rough", Sigma_mv),
        ]:
            if Sigma is None:
                continue
            # Per-asset QLIKE on r^2
            for j, a in enumerate(ASSETS):
                v_f = float(Sigma[j, j])
                v_r = float(r_t[j] ** 2)
                qlike_per[m_name][a][i] = qlike_univariate(v_f, v_r)
            # Multivariate QLIKE
            qlike_mv[m_name][i] = qlike_multivariate(Sigma, r_t)
            # Frobenius
            frob[m_name][i] = frobenius(Sigma, R_real)

        if (i + 1) % 250 == 0:
            print(f"  OOS day {i+1}/{n_oos} done")

    return {
        "hursts": hursts,
        "dcc_params": {"a": dcc.a, "b": dcc.b},
        "qlike_per_asset": qlike_per,
        "qlike_multivariate": qlike_mv,
        "frobenius": frob,
        "oos_dates": [d.strftime("%Y-%m-%d") for d in oos_idx],
    }


# -----------------------------------------------------------------------------
# Sub-period analysis
# -----------------------------------------------------------------------------
def subperiod_table(
    losses: Dict[str, np.ndarray], dates: pd.DatetimeIndex
) -> Dict:
    """Split OOS losses by year buckets: 2020 / 2022 / others."""
    out = {}
    masks = {
        "2020": dates.year == 2020,
        "2022": dates.year == 2022,
        "others": ~((dates.year == 2020) | (dates.year == 2022)),
        "all": np.ones(len(dates), dtype=bool),
    }
    for period, mask in masks.items():
        out[period] = {
            m: float(np.nanmean(losses[m][mask])) for m in losses
        }
    return out


# -----------------------------------------------------------------------------
# Plotting
# -----------------------------------------------------------------------------
def plot_qlike_comparison(results: Dict, oos_dates: pd.DatetimeIndex, out_path: Path):
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(13, 4.5), sharey=False)
    models = ["dcc", "uni_rough", "mv_rough"]
    labels = ["DCC-GARCH", "Univariate\nRough Bergomi", "Multivariate\nRough Vol"]
    colors = ["#1f77b4", "#ff7f0e", "#2ca02c"]

    for ax, asset in zip(axes, ASSETS):
        means = [
            np.nanmean(results["qlike_per_asset"][m][asset]) for m in models
        ]
        stds = [
            np.nanstd(results["qlike_per_asset"][m][asset]) /
            np.sqrt(np.sum(~np.isnan(results["qlike_per_asset"][m][asset])))
            for m in models
        ]
        ax.bar(labels, means, yerr=stds, color=colors, capsize=4, alpha=0.85)
        ax.set_title(f"{asset} per-asset QLIKE")
        ax.set_ylabel("Mean QLIKE (lower better)")
        ax.tick_params(axis="x", labelsize=8)

    plt.tight_layout()
    plt.savefig(out_path, dpi=120)
    plt.close()
    print(f"Saved {out_path.name}")


def plot_dm_heatmap(dm_table: Dict, out_path: Path):
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 5))
    rows = ["mv_rough vs dcc", "uni_rough vs dcc", "mv_rough vs uni_rough"]
    cols = ["mv_QLIKE", "Frobenius"] + [f"QLIKE_{a}" for a in ASSETS]
    grid = np.full((len(rows), len(cols)), np.nan)
    for i, key in enumerate(rows):
        for j, c in enumerate(cols):
            grid[i, j] = dm_table.get(key, {}).get(c, {}).get("t", np.nan)
    im = ax.imshow(grid, cmap="RdBu_r", vmin=-4, vmax=4, aspect="auto")
    ax.set_xticks(range(len(cols)))
    ax.set_xticklabels(cols, rotation=20, ha="right")
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels(rows)
    for i in range(len(rows)):
        for j in range(len(cols)):
            v = grid[i, j]
            if np.isfinite(v):
                ax.text(j, i, f"{v:+.2f}", ha="center", va="center",
                        color="white" if abs(v) > 2 else "black", fontsize=9)
    plt.colorbar(im, ax=ax, label="DM-HLN t-stat (positive = first model worse)")
    ax.set_title("Diebold-Mariano (HLN-corrected) t-statistics")
    plt.tight_layout()
    plt.savefig(out_path, dpi=120)
    plt.close()
    print(f"Saved {out_path.name}")


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main():
    t0 = datetime.utcnow()
    print(f"K1266 Multivariate Rough Vol - start {t0.isoformat()}")

    rets = load_returns()
    rets = rets.loc[(rets.index >= START) & (rets.index <= END)]
    print(f"\nLoaded returns: {rets.shape}, "
          f"{rets.index[0].date()}..{rets.index[-1].date()}")

    # Realized variance (squared returns)
    rv = realized_var(rets)
    log_rv = np.log(rv.replace(0, np.nan))

    # OOS index
    oos_idx = rets.index[(rets.index >= OOS_START)]
    if len(oos_idx) == 0:
        print("No OOS data — abort.")
        return 1

    # Run OOS
    results = run_oos(rets, log_rv, oos_idx)

    # ---- Subperiod summary ----
    oos_dt = pd.DatetimeIndex(results["oos_dates"])
    subperiods_qlike_mv = subperiod_table(results["qlike_multivariate"], oos_dt)
    subperiods_frob = subperiod_table(results["frobenius"], oos_dt)
    subperiods_per = {
        a: subperiod_table({m: results["qlike_per_asset"][m][a]
                            for m in results["qlike_per_asset"]}, oos_dt)
        for a in ASSETS
    }

    # ---- DM tests ----
    dm_table = {}
    pairs = [
        ("mv_rough vs dcc", "mv_rough", "dcc"),
        ("uni_rough vs dcc", "uni_rough", "dcc"),
        ("mv_rough vs uni_rough", "mv_rough", "uni_rough"),
    ]
    for name, model_a, model_b in pairs:
        entry = {}
        # Multivariate QLIKE
        t, p = dm_hln(results["qlike_multivariate"][model_a],
                      results["qlike_multivariate"][model_b])
        entry["mv_QLIKE"] = {"t": t, "p": p}
        # Frobenius
        t, p = dm_hln(results["frobenius"][model_a], results["frobenius"][model_b])
        entry["Frobenius"] = {"t": t, "p": p}
        # Per-asset
        for a in ASSETS:
            t, p = dm_hln(results["qlike_per_asset"][model_a][a],
                          results["qlike_per_asset"][model_b][a])
            entry[f"QLIKE_{a}"] = {"t": t, "p": p}
        dm_table[name] = entry

    # ---- Verdict ----
    # Gate: mv_rough beats DCC by >2% on multivariate QLIKE with DM p<0.10
    mv_qlike_mv = float(np.nanmean(results["qlike_multivariate"]["mv_rough"]))
    dcc_qlike_mv = float(np.nanmean(results["qlike_multivariate"]["dcc"]))
    rel_improve = (dcc_qlike_mv - mv_qlike_mv) / abs(dcc_qlike_mv) * 100
    dm_p = dm_table["mv_rough vs dcc"]["mv_QLIKE"]["p"]
    dm_t = dm_table["mv_rough vs dcc"]["mv_QLIKE"]["t"]

    # Subperiod consistency: mv_rough beats DCC in ≥2/3 of {2020, 2022, others}
    sub_wins = 0
    for period in ["2020", "2022", "others"]:
        if (subperiods_qlike_mv[period]["mv_rough"] <
                subperiods_qlike_mv[period]["dcc"]):
            sub_wins += 1

    if rel_improve > 2 and dm_p < 0.10 and sub_wins >= 2:
        verdict = "PASS"
    elif rel_improve > 0 and dm_p < 0.20:
        verdict = "MARGINAL"
    else:
        verdict = "NULL"

    print(f"\n{'='*60}")
    print(f"VERDICT: {verdict}")
    print(f"  Multivariate QLIKE: mv_rough={mv_qlike_mv:.4f} vs dcc={dcc_qlike_mv:.4f}")
    print(f"  Relative improvement: {rel_improve:+.2f}%")
    print(f"  DM-HLN: t={dm_t:+.3f}, p={dm_p:.4f}")
    print(f"  Subperiod wins (mv_rough vs dcc): {sub_wins}/3")
    print(f"{'='*60}")

    # ---- Per-asset table ----
    per_asset_summary = {}
    print("\nPer-asset OOS QLIKE (mean):")
    print(f"  {'Asset':<6} {'DCC':>10} {'UniRough':>10} {'MvRough':>10}")
    for a in ASSETS:
        d = float(np.nanmean(results["qlike_per_asset"]["dcc"][a]))
        u = float(np.nanmean(results["qlike_per_asset"]["uni_rough"][a]))
        m = float(np.nanmean(results["qlike_per_asset"]["mv_rough"][a]))
        per_asset_summary[a] = {"dcc": d, "uni_rough": u, "mv_rough": m}
        print(f"  {a:<6} {d:>10.5f} {u:>10.5f} {m:>10.5f}")

    # ---- DM table print ----
    print("\nDM-HLN t-stats (positive = first model has higher loss = second wins):")
    for name, entry in dm_table.items():
        print(f"  {name}:")
        for k, v in entry.items():
            print(f"    {k}: t={v['t']:+.3f} p={v['p']:.4f}")

    # ---- Save results ----
    out = {
        "experiment_id": "k1266",
        "title": "Multivariate Rough Volatility (rough Bergomi) on SPY/QQQ/IWM",
        "literature": [
            "arXiv:2412.14353 (2024-12) Multivariate rough volatility",
            "Bayer-Friz-Gatheral (2016) Pricing under rough volatility",
            "Engle (2002) Dynamic Conditional Correlation",
        ],
        "differentiation_from_K806": (
            "K806 used multivariate fBm + cross-asset H regressors on r^2 target; "
            "K1266 uses rough Bergomi spec + DCC-GARCH baseline + joint Sigma "
            "evaluation on 3 US ETFs (different assets, different spec, "
            "different evaluation target)."
        ),
        "assets": ASSETS,
        "period": {"start": str(rets.index[0].date()),
                   "end": str(rets.index[-1].date()),
                   "is_end": IS_END,
                   "oos_start": OOS_START,
                   "n_is": int((rets.index <= IS_END).sum()),
                   "n_oos": int(len(oos_idx))},
        "seed": SEED,
        "hursts": {a: float(results["hursts"][a]) for a in ASSETS},
        "dcc_params": results["dcc_params"],
        "verdict": verdict,
        "headline": {
            "mv_qlike_dcc": dcc_qlike_mv,
            "mv_qlike_uni_rough": float(np.nanmean(results["qlike_multivariate"]["uni_rough"])),
            "mv_qlike_mv_rough": mv_qlike_mv,
            "rel_improve_mv_vs_dcc_pct": rel_improve,
            "dm_t_mv_vs_dcc": dm_t,
            "dm_p_mv_vs_dcc": dm_p,
            "subperiod_wins_mv_vs_dcc": sub_wins,
        },
        "per_asset_qlike": per_asset_summary,
        "dm_table": dm_table,
        "subperiod_qlike_mv": subperiods_qlike_mv,
        "subperiod_frobenius": subperiods_frob,
        "subperiod_per_asset_qlike": subperiods_per,
        "completed_at": datetime.utcnow().isoformat(),
        "runtime_seconds": (datetime.utcnow() - t0).total_seconds(),
    }
    out_path = EXP_DIR / "k1266_results.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nSaved {out_path.name}")

    # Plots
    plot_qlike_comparison(results, oos_dt, EXP_DIR / "k1266_qlike_comparison.png")
    plot_dm_heatmap(dm_table, EXP_DIR / "k1266_dm_heatmap.png")

    print(f"\nTotal runtime: {(datetime.utcnow() - t0).total_seconds():.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
