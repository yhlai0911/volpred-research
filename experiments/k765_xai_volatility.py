"""K765: Explainable AI for Volatility — Which GARCH Parameters Matter Most?

Background:
  - K530: HAR-ABS is the QLIKE champion (DM=-15.45 vs GJR, DM=-16.26 vs EWMA)
  - K764: Multivariate rough vol doesn't improve beyond univariate HAR-ABS
  - But WHY does HAR-ABS work? Which features drive predictions?
  - This experiment uses feature importance analysis to explain vol forecasting

Literature:
  - Corsi (2009): HAR-RV, multi-scale realized volatility
  - Engle & Patton (2001): GARCH parameter interpretation
  - Hansen & Lunde (2005): 330 GARCH variants, (1,1) hard to beat
  - Lundbergh & Teräsvirta (2002): GARCH parameter stability tests
  - Shapley (1953): SHAP-like decomposition for additive models

Experiment Design:
  Part A: GJR-GARCH Parameter Importance
    - Rolling 504-day windows for SPY, track ω, α, β, γ evolution
    - Which parameter has highest variance? Most stable?
    - Does γ (leverage) predict next-period forecast accuracy?

  Part B: HAR Feature Importance
    - HAR-ABS with 3 features: |r|_daily, |r|_weekly, |r|_monthly
    - Track β coefficients over time (expanding window)
    - Which horizon dominates? Does it change by VIX regime?

  Part C: SHAP-like Decomposition (analytical, no ML)
    - For each forecast day: forecast = baseline + daily_contrib + weekly_contrib + monthly_contrib
    - When does weekly/monthly component matter most?
    - Crisis vs calm decomposition

  Part D: Forecast Confidence via Model Agreement
    - When daily/weekly/monthly components agree → high confidence
    - When they disagree → low confidence (uncertain regime)
    - Test: does component agreement predict forecast accuracy?

Data: SPY daily from yfinance, 2007-2026
      ^VIX for regime classification
Vol proxy: daily |r| (per K530 finding)
OOS: expanding window, start 2012-01-01

[提出: Claude (from research_program), 執行: Claude]

Usage:
    uv run python experiments/k765_xai_volatility.py
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import minimize

warnings.filterwarnings("ignore")

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))


# ============================================================
#  Utility functions
# ============================================================

def print_section(title: str, char: str = "=", width: int = 72):
    print(f"\n{char * width}")
    print(f"  {title}")
    print(f"{char * width}")


def qlike(realized: np.ndarray, forecast: np.ndarray) -> float:
    """QLIKE loss: mean(realized/forecast + log(forecast))"""
    mask = (forecast > 0) & (realized > 0) & np.isfinite(realized) & np.isfinite(forecast)
    r, f = realized[mask], forecast[mask]
    return np.mean(r / f + np.log(f))


def dm_test(loss1: np.ndarray, loss2: np.ndarray) -> tuple:
    """Diebold-Mariano test. Negative t → model 1 better."""
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 30:
        return np.nan, np.nan
    d_bar = np.mean(d)
    # HAC variance (Newey-West, 5 lags)
    gamma0 = np.var(d, ddof=1)
    hac_var = gamma0
    for k in range(1, 6):
        w = 1 - k / 6
        gamma_k = np.mean((d[k:] - d_bar) * (d[:-k] - d_bar))
        hac_var += 2 * w * gamma_k
    se = np.sqrt(hac_var / n)
    if se < 1e-12:
        return 0.0, 1.0
    t_stat = d_bar / se
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return t_stat, p_val


# ============================================================
#  GJR-GARCH estimation (MLE)
# ============================================================

def gjr_garch_nll(params, returns):
    """Negative log-likelihood for GJR-GARCH(1,1) with Normal innovations."""
    omega, alpha, beta, gamma = params
    n = len(returns)
    sigma2 = np.empty(n)
    sigma2[0] = np.var(returns)
    for t in range(1, n):
        r2 = returns[t - 1] ** 2
        ind = 1.0 if returns[t - 1] < 0 else 0.0
        sigma2[t] = omega + alpha * r2 + beta * sigma2[t - 1] + gamma * ind * r2
        if sigma2[t] < 1e-10:
            sigma2[t] = 1e-10
    # Log-likelihood (Normal)
    ll = -0.5 * np.sum(np.log(2 * np.pi * sigma2) + returns ** 2 / sigma2)
    return -ll


def fit_gjr_garch(returns, n_restarts=4):
    """Fit GJR-GARCH(1,1) with multi-start optimization."""
    best_result = None
    best_nll = np.inf
    var_r = np.var(returns)

    bounds = [(1e-8, var_r * 0.5), (1e-8, 0.5), (0.5, 0.9999), (1e-8, 0.5)]

    for i in range(n_restarts):
        if i == 0:
            x0 = [var_r * 0.05, 0.05, 0.90, 0.05]
        else:
            rng = np.random.RandomState(42 + i)
            x0 = [
                rng.uniform(1e-6, var_r * 0.1),
                rng.uniform(0.01, 0.15),
                rng.uniform(0.7, 0.95),
                rng.uniform(0.01, 0.15),
            ]

        try:
            result = minimize(
                gjr_garch_nll, x0, args=(returns,),
                method="L-BFGS-B", bounds=bounds,
                options={"maxiter": 500, "ftol": 1e-12}
            )
            if result.fun < best_nll:
                best_nll = result.fun
                best_result = result
        except Exception:
            continue

    if best_result is None:
        return None
    return {
        "omega": best_result.x[0],
        "alpha": best_result.x[1],
        "beta": best_result.x[2],
        "gamma": best_result.x[3],
        "persistence": best_result.x[1] + best_result.x[2] + 0.5 * best_result.x[3],
        "nll": best_result.fun,
        "converged": best_result.success,
    }


def gjr_garch_forecast(params, returns):
    """One-step-ahead forecast from GJR-GARCH parameters."""
    omega, alpha, beta, gamma = params["omega"], params["alpha"], params["beta"], params["gamma"]
    n = len(returns)
    sigma2 = np.empty(n)
    sigma2[0] = np.var(returns)
    for t in range(1, n):
        r2 = returns[t - 1] ** 2
        ind = 1.0 if returns[t - 1] < 0 else 0.0
        sigma2[t] = omega + alpha * r2 + beta * sigma2[t - 1] + gamma * ind * r2
        if sigma2[t] < 1e-10:
            sigma2[t] = 1e-10
    # Forecast for next period
    r2_last = returns[-1] ** 2
    ind_last = 1.0 if returns[-1] < 0 else 0.0
    fcast = omega + alpha * r2_last + beta * sigma2[-1] + gamma * ind_last * r2_last
    return max(fcast, 1e-10), sigma2


# ============================================================
#  HAR-ABS model
# ============================================================

def build_har_features(abs_returns: np.ndarray) -> tuple:
    """Build HAR features: daily, weekly (5d), monthly (22d) averages of |r|."""
    n = len(abs_returns)
    daily = abs_returns.copy()
    weekly = np.full(n, np.nan)
    monthly = np.full(n, np.nan)

    for t in range(4, n):
        weekly[t] = np.mean(abs_returns[t - 4:t + 1])
    for t in range(21, n):
        monthly[t] = np.mean(abs_returns[t - 21:t + 1])

    return daily, weekly, monthly


def fit_har_abs(abs_returns: np.ndarray, min_obs: int = 252):
    """Fit HAR-ABS model using OLS. Returns coefficients and diagnostics."""
    daily, weekly, monthly = build_har_features(abs_returns)
    n = len(abs_returns)

    # Target: next-day |r|, Features: current day's daily/weekly/monthly
    valid = np.arange(22, n - 1)  # Need 22 days history, predict next
    y = abs_returns[valid + 1]
    X = np.column_stack([
        np.ones(len(valid)),
        daily[valid],
        weekly[valid],
        monthly[valid],
    ])

    mask = np.all(np.isfinite(X), axis=1) & np.isfinite(y)
    y, X = y[mask], X[mask]

    if len(y) < min_obs:
        return None

    # OLS
    beta = np.linalg.lstsq(X, y, rcond=None)[0]

    # R-squared
    y_hat = X @ beta
    ss_res = np.sum((y - y_hat) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0

    # Standard errors
    n_obs = len(y)
    k = X.shape[1]
    mse = ss_res / (n_obs - k)
    try:
        cov = mse * np.linalg.inv(X.T @ X)
        se = np.sqrt(np.diag(cov))
        t_stats = beta / se
    except Exception:
        se = np.full(k, np.nan)
        t_stats = np.full(k, np.nan)

    return {
        "intercept": float(beta[0]),
        "beta_daily": float(beta[1]),
        "beta_weekly": float(beta[2]),
        "beta_monthly": float(beta[3]),
        "se_intercept": float(se[0]),
        "se_daily": float(se[1]),
        "se_weekly": float(se[2]),
        "se_monthly": float(se[3]),
        "t_daily": float(t_stats[1]),
        "t_weekly": float(t_stats[2]),
        "t_monthly": float(t_stats[3]),
        "r2": float(r2),
        "n_obs": n_obs,
    }


def har_abs_forecast(abs_returns: np.ndarray, coeffs: dict) -> float:
    """One-step-ahead HAR-ABS forecast."""
    daily = abs_returns[-1]
    weekly = np.mean(abs_returns[-5:]) if len(abs_returns) >= 5 else daily
    monthly = np.mean(abs_returns[-22:]) if len(abs_returns) >= 22 else weekly
    fcast = (coeffs["intercept"] + coeffs["beta_daily"] * daily +
             coeffs["beta_weekly"] * weekly + coeffs["beta_monthly"] * monthly)
    return max(fcast, 1e-6)


# ============================================================
#  Data Loading
# ============================================================

def load_data():
    """Load SPY and VIX data."""
    print_section("Loading Data")
    import yfinance as yf

    spy = yf.download("SPY", start="2006-01-01", end="2026-04-01", progress=False)
    vix = yf.download("^VIX", start="2006-01-01", end="2026-04-01", progress=False)

    # Handle multi-level columns
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)

    spy_ret = np.log(spy["Close"] / spy["Close"].shift(1)).dropna()
    spy_ret.name = "return"

    vix_close = vix["Close"].reindex(spy_ret.index, method="ffill")
    vix_close.name = "VIX"

    df = pd.DataFrame({"return": spy_ret, "VIX": vix_close}).dropna()
    df["abs_return"] = df["return"].abs()
    df["sq_return"] = df["return"] ** 2

    print(f"  SPY: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
    print(f"  Total observations: {len(df)}")
    print(f"  Mean |r|: {df['abs_return'].mean():.5f}")
    print(f"  Mean VIX: {df['VIX'].mean():.2f}")

    return df


# ============================================================
#  Part A: GJR-GARCH Parameter Importance (Rolling)
# ============================================================

def part_a_garch_parameter_importance(df):
    """Track GJR-GARCH parameter evolution over rolling windows."""
    print_section("Part A: GJR-GARCH Parameter Importance (Rolling)")

    returns = df["return"].values
    dates = df.index
    window = 504  # 2 years
    step = 22     # monthly re-estimation for efficiency

    params_history = []
    forecast_errors = []

    oos_start_idx = np.searchsorted(dates, pd.Timestamp("2012-01-01"))
    if oos_start_idx < window:
        oos_start_idx = window

    print(f"  Window: {window} days, Step: {step} days")
    print(f"  OOS start: {dates[oos_start_idx].strftime('%Y-%m-%d')}")

    t_start = time.time()
    n_fits = 0

    for t in range(oos_start_idx, len(returns) - 1, step):
        train_ret = returns[t - window:t]
        result = fit_gjr_garch(train_ret, n_restarts=3)
        if result is None or not result["converged"]:
            continue

        # Forecast next day
        fcast_var, _ = gjr_garch_forecast(result, train_ret)
        # Realized: next-day return squared (variance proxy)
        realized_var = returns[t] ** 2

        params_history.append({
            "date": dates[t].strftime("%Y-%m-%d"),
            "omega": result["omega"],
            "alpha": result["alpha"],
            "beta": result["beta"],
            "gamma": result["gamma"],
            "persistence": result["persistence"],
        })

        forecast_errors.append({
            "date": dates[t].strftime("%Y-%m-%d"),
            "gamma": result["gamma"],
            "forecast_var": float(fcast_var),
            "realized_var": float(realized_var),
            "qlike_loss": float(realized_var / fcast_var + np.log(fcast_var)) if fcast_var > 0 else np.nan,
        })

        n_fits += 1
        if n_fits % 20 == 0:
            elapsed = time.time() - t_start
            print(f"    Fitted {n_fits} windows ({elapsed:.1f}s)...")

    print(f"  Total fits: {n_fits} ({time.time() - t_start:.1f}s)")

    # Analyze parameter evolution
    ph = pd.DataFrame(params_history)
    param_names = ["omega", "alpha", "beta", "gamma"]

    print("\n  Parameter Statistics (across rolling windows):")
    print(f"  {'Param':<10} {'Mean':>10} {'Std':>10} {'CV':>10} {'Min':>10} {'Max':>10}")
    print(f"  {'-' * 60}")

    param_stats = {}
    for p in param_names:
        vals = ph[p].values
        mean_v = np.mean(vals)
        std_v = np.std(vals)
        cv = std_v / mean_v if mean_v > 0 else np.nan
        param_stats[p] = {
            "mean": float(mean_v),
            "std": float(std_v),
            "cv": float(cv),
            "min": float(np.min(vals)),
            "max": float(np.max(vals)),
            "median": float(np.median(vals)),
        }
        print(f"  {p:<10} {mean_v:>10.6f} {std_v:>10.6f} {cv:>10.3f} {np.min(vals):>10.6f} {np.max(vals):>10.6f}")

    # Persistence evolution
    pers = ph["persistence"].values
    print(f"\n  Persistence: mean={np.mean(pers):.4f}, std={np.std(pers):.4f}, "
          f"range=[{np.min(pers):.4f}, {np.max(pers):.4f}]")

    # Does gamma predict next-period forecast accuracy?
    fe = pd.DataFrame(forecast_errors).dropna(subset=["qlike_loss"])
    if len(fe) > 30:
        gamma_vals = fe["gamma"].values
        losses = fe["qlike_loss"].values

        # Split into high-gamma and low-gamma groups
        median_gamma = np.median(gamma_vals)
        high_gamma = losses[gamma_vals >= median_gamma]
        low_gamma = losses[gamma_vals < median_gamma]

        t_stat_gamma, p_val_gamma = stats.ttest_ind(high_gamma, low_gamma)
        corr_gamma_loss, p_corr = stats.pearsonr(gamma_vals, losses)

        print(f"\n  Gamma → Forecast Accuracy:")
        print(f"    High-gamma QLIKE: {np.mean(high_gamma):.4f} (n={len(high_gamma)})")
        print(f"    Low-gamma QLIKE:  {np.mean(low_gamma):.4f} (n={len(low_gamma)})")
        print(f"    t-test: t={t_stat_gamma:.3f}, p={p_val_gamma:.4f}")
        print(f"    Correlation(gamma, QLIKE): r={corr_gamma_loss:.4f}, p={p_corr:.4f}")

        gamma_predicts = {
            "high_gamma_qlike": float(np.mean(high_gamma)),
            "low_gamma_qlike": float(np.mean(low_gamma)),
            "t_stat": float(t_stat_gamma),
            "p_value": float(p_val_gamma),
            "correlation": float(corr_gamma_loss),
            "corr_p_value": float(p_corr),
        }
    else:
        gamma_predicts = {"note": "insufficient data"}

    # Most variable parameter (highest CV)
    most_variable = max(param_stats.items(), key=lambda x: x[1]["cv"])
    most_stable = min(param_stats.items(), key=lambda x: x[1]["cv"])

    print(f"\n  Most variable parameter: {most_variable[0]} (CV={most_variable[1]['cv']:.3f})")
    print(f"  Most stable parameter:   {most_stable[0]} (CV={most_stable[1]['cv']:.3f})")

    return {
        "param_stats": param_stats,
        "gamma_predicts_accuracy": gamma_predicts,
        "most_variable_param": most_variable[0],
        "most_stable_param": most_stable[0],
        "n_windows": n_fits,
        "params_history": params_history,
    }


# ============================================================
#  Part B: HAR Feature Importance (Expanding Window)
# ============================================================

def part_b_har_feature_importance(df):
    """Track HAR-ABS coefficient evolution and regime dependence."""
    print_section("Part B: HAR-ABS Feature Importance (Expanding Window)")

    abs_ret = df["abs_return"].values
    vix = df["VIX"].values
    dates = df.index

    oos_start_idx = np.searchsorted(dates, pd.Timestamp("2012-01-01"))
    min_train = 504
    if oos_start_idx < min_train + 22:
        oos_start_idx = min_train + 22

    step = 22  # monthly re-estimation
    coeff_history = []
    oos_forecasts = []

    print(f"  OOS start: {dates[oos_start_idx].strftime('%Y-%m-%d')}")

    t_start = time.time()

    for t in range(oos_start_idx, len(abs_ret) - 1, step):
        train_abs = abs_ret[:t]
        result = fit_har_abs(train_abs, min_obs=252)
        if result is None:
            continue

        # Forecast next day
        fcast = har_abs_forecast(train_abs, result)
        realized = abs_ret[t]  # next-day |r|

        current_vix = vix[t] if t < len(vix) else np.nan

        coeff_history.append({
            "date": dates[t].strftime("%Y-%m-%d"),
            "beta_daily": result["beta_daily"],
            "beta_weekly": result["beta_weekly"],
            "beta_monthly": result["beta_monthly"],
            "intercept": result["intercept"],
            "r2": result["r2"],
            "n_obs": result["n_obs"],
            "vix": float(current_vix) if np.isfinite(current_vix) else None,
        })

        oos_forecasts.append({
            "date": dates[t].strftime("%Y-%m-%d"),
            "forecast": float(fcast),
            "realized": float(realized),
            "vix": float(current_vix) if np.isfinite(current_vix) else None,
        })

    print(f"  Total estimation windows: {len(coeff_history)} ({time.time() - t_start:.1f}s)")

    ch = pd.DataFrame(coeff_history)

    # Coefficient statistics
    print("\n  HAR-ABS Coefficient Statistics (across expanding windows):")
    beta_names = ["beta_daily", "beta_weekly", "beta_monthly"]
    print(f"  {'Coeff':<15} {'Mean':>10} {'Std':>10} {'CV':>10} {'Min':>10} {'Max':>10}")
    print(f"  {'-' * 65}")

    coeff_stats = {}
    for b in beta_names:
        vals = ch[b].values
        mean_v = np.mean(vals)
        std_v = np.std(vals)
        cv = std_v / abs(mean_v) if abs(mean_v) > 1e-8 else np.nan
        coeff_stats[b] = {
            "mean": float(mean_v),
            "std": float(std_v),
            "cv": float(cv),
            "min": float(np.min(vals)),
            "max": float(np.max(vals)),
        }
        print(f"  {b:<15} {mean_v:>10.5f} {std_v:>10.5f} {cv:>10.3f} {np.min(vals):>10.5f} {np.max(vals):>10.5f}")

    # Relative importance: standardized coefficients
    # Since features have different scales, use standardized betas
    # Rough estimate: daily_std ~= weekly_std / sqrt(5) ~= monthly_std / sqrt(22)
    daily_vals = ch["beta_daily"].values
    weekly_vals = ch["beta_weekly"].values
    monthly_vals = ch["beta_monthly"].values

    # Average relative magnitude
    total = np.abs(daily_vals) + np.abs(weekly_vals) + np.abs(monthly_vals)
    rel_daily = np.mean(np.abs(daily_vals) / total)
    rel_weekly = np.mean(np.abs(weekly_vals) / total)
    rel_monthly = np.mean(np.abs(monthly_vals) / total)

    print(f"\n  Relative Coefficient Magnitude (average across windows):")
    print(f"    Daily:   {rel_daily:.3f} ({rel_daily * 100:.1f}%)")
    print(f"    Weekly:  {rel_weekly:.3f} ({rel_weekly * 100:.1f}%)")
    print(f"    Monthly: {rel_monthly:.3f} ({rel_monthly * 100:.1f}%)")

    dominant = max([("daily", rel_daily), ("weekly", rel_weekly), ("monthly", rel_monthly)],
                   key=lambda x: x[1])
    print(f"    Dominant horizon: {dominant[0]}")

    # VIX Regime Analysis
    vix_vals = ch["vix"].dropna().values
    vix_indices = ch["vix"].dropna().index

    if len(vix_vals) > 20:
        vix_25 = np.percentile(vix_vals, 25)
        vix_75 = np.percentile(vix_vals, 75)

        low_vix_mask = vix_vals <= vix_25
        high_vix_mask = vix_vals >= vix_75

        regime_analysis = {}
        for b in beta_names:
            b_vals = ch.loc[vix_indices, b].values
            low_mean = np.mean(b_vals[low_vix_mask])
            high_mean = np.mean(b_vals[high_vix_mask])
            if np.sum(low_vix_mask) > 5 and np.sum(high_vix_mask) > 5:
                t_reg, p_reg = stats.ttest_ind(b_vals[high_vix_mask], b_vals[low_vix_mask])
            else:
                t_reg, p_reg = np.nan, np.nan
            regime_analysis[b] = {
                "low_vix_mean": float(low_mean),
                "high_vix_mean": float(high_mean),
                "t_stat": float(t_reg),
                "p_value": float(p_reg),
            }

        print(f"\n  VIX Regime Analysis (Low VIX ≤ {vix_25:.1f}, High VIX ≥ {vix_75:.1f}):")
        print(f"  {'Coeff':<15} {'Low VIX':>10} {'High VIX':>10} {'t-stat':>10} {'p-val':>10}")
        print(f"  {'-' * 55}")
        for b in beta_names:
            ra = regime_analysis[b]
            print(f"  {b:<15} {ra['low_vix_mean']:>10.5f} {ra['high_vix_mean']:>10.5f} "
                  f"{ra['t_stat']:>10.3f} {ra['p_value']:>10.4f}")
    else:
        regime_analysis = {"note": "insufficient data for regime analysis"}

    return {
        "coeff_stats": coeff_stats,
        "relative_importance": {
            "daily": float(rel_daily),
            "weekly": float(rel_weekly),
            "monthly": float(rel_monthly),
        },
        "dominant_horizon": dominant[0],
        "regime_analysis": regime_analysis,
        "r2_stats": {
            "mean": float(ch["r2"].mean()),
            "std": float(ch["r2"].std()),
            "min": float(ch["r2"].min()),
            "max": float(ch["r2"].max()),
        },
        "coeff_history": coeff_history,
        "oos_forecasts": oos_forecasts,
    }


# ============================================================
#  Part C: SHAP-like Decomposition
# ============================================================

def part_c_shap_decomposition(df, har_result):
    """Decompose each HAR-ABS forecast into component contributions."""
    print_section("Part C: SHAP-like Forecast Decomposition")

    abs_ret = df["abs_return"].values
    vix = df["VIX"].values
    dates = df.index

    oos_start_idx = np.searchsorted(dates, pd.Timestamp("2012-01-01"))
    min_train = 504
    if oos_start_idx < min_train + 22:
        oos_start_idx = min_train + 22

    step = 1  # Daily decomposition for a subset
    # For efficiency, do daily for last 5 years only
    decomp_start_idx = max(oos_start_idx, np.searchsorted(dates, pd.Timestamp("2020-01-01")))

    decompositions = []
    current_coeffs = None
    refit_step = 66  # re-estimate quarterly

    print(f"  Decomposition period: {dates[decomp_start_idx].strftime('%Y-%m-%d')} to "
          f"{dates[-2].strftime('%Y-%m-%d')}")

    t_start = time.time()

    for t in range(decomp_start_idx, len(abs_ret) - 1):
        # Refit periodically
        if current_coeffs is None or (t - decomp_start_idx) % refit_step == 0:
            train_abs = abs_ret[:t]
            result = fit_har_abs(train_abs, min_obs=252)
            if result is not None:
                current_coeffs = result

        if current_coeffs is None:
            continue

        # Compute features for day t
        daily_feat = abs_ret[t]
        weekly_feat = np.mean(abs_ret[max(0, t - 4):t + 1]) if t >= 4 else daily_feat
        monthly_feat = np.mean(abs_ret[max(0, t - 21):t + 1]) if t >= 21 else weekly_feat

        # Baseline: unconditional mean of |r| up to t
        baseline = np.mean(abs_ret[:t])

        # Component contributions (deviation from baseline forecast)
        forecast = (current_coeffs["intercept"] +
                    current_coeffs["beta_daily"] * daily_feat +
                    current_coeffs["beta_weekly"] * weekly_feat +
                    current_coeffs["beta_monthly"] * monthly_feat)

        # Marginal contributions (Shapley-like for additive model)
        # baseline_forecast = intercept + beta_d * E[daily] + beta_w * E[weekly] + beta_m * E[monthly]
        mean_daily = np.mean(abs_ret[:t])
        mean_weekly = np.mean(abs_ret[:t])  # approximately same for long history
        mean_monthly = np.mean(abs_ret[:t])

        daily_contrib = current_coeffs["beta_daily"] * (daily_feat - mean_daily)
        weekly_contrib = current_coeffs["beta_weekly"] * (weekly_feat - mean_weekly)
        monthly_contrib = current_coeffs["beta_monthly"] * (monthly_feat - mean_monthly)

        realized = abs_ret[t + 1] if t + 1 < len(abs_ret) else np.nan
        current_vix = vix[t] if t < len(vix) else np.nan

        decompositions.append({
            "date": dates[t].strftime("%Y-%m-%d"),
            "forecast": float(forecast),
            "realized": float(realized) if np.isfinite(realized) else None,
            "baseline": float(baseline),
            "daily_contrib": float(daily_contrib),
            "weekly_contrib": float(weekly_contrib),
            "monthly_contrib": float(monthly_contrib),
            "total_deviation": float(daily_contrib + weekly_contrib + monthly_contrib),
            "vix": float(current_vix) if np.isfinite(current_vix) else None,
        })

    print(f"  Total decomposed days: {len(decompositions)} ({time.time() - t_start:.1f}s)")

    dd = pd.DataFrame(decompositions)

    # Analyze contributions
    print("\n  Average Absolute Contribution by Component:")
    contrib_cols = ["daily_contrib", "weekly_contrib", "monthly_contrib"]
    abs_contribs = {}
    for c in contrib_cols:
        vals = dd[c].abs().values
        mean_abs = np.mean(vals)
        abs_contribs[c] = mean_abs
    total_abs = sum(abs_contribs.values())

    for c in contrib_cols:
        pct = abs_contribs[c] / total_abs * 100
        print(f"    {c:<20}: {abs_contribs[c]:.6f} ({pct:.1f}%)")

    # Crisis vs Calm analysis
    vix_vals = dd["vix"].dropna().values
    if len(vix_vals) > 20:
        vix_median = np.median(vix_vals)
        calm_mask = dd["vix"].dropna() <= vix_median
        crisis_mask = dd["vix"].dropna() > vix_median

        print(f"\n  Crisis (VIX > {vix_median:.1f}) vs Calm (VIX ≤ {vix_median:.1f}):")
        crisis_calm_analysis = {}

        for c in contrib_cols:
            valid_dd = dd.dropna(subset=["vix"])
            calm_vals = valid_dd.loc[calm_mask.values, c].abs().values
            crisis_vals = valid_dd.loc[crisis_mask.values, c].abs().values
            calm_mean = np.mean(calm_vals)
            crisis_mean = np.mean(crisis_vals)
            ratio = crisis_mean / calm_mean if calm_mean > 0 else np.nan

            crisis_calm_analysis[c] = {
                "calm_mean": float(calm_mean),
                "crisis_mean": float(crisis_mean),
                "crisis_to_calm_ratio": float(ratio),
            }
            print(f"    {c:<20}: Calm={calm_mean:.6f}, Crisis={crisis_mean:.6f}, Ratio={ratio:.2f}x")

        # Which component increases most during crisis?
        most_crisis_sensitive = max(crisis_calm_analysis.items(),
                                    key=lambda x: x[1]["crisis_to_calm_ratio"])
        print(f"\n    Most crisis-sensitive component: {most_crisis_sensitive[0]} "
              f"({most_crisis_sensitive[1]['crisis_to_calm_ratio']:.2f}x increase)")
    else:
        crisis_calm_analysis = {}
        most_crisis_sensitive = ("unknown", {"crisis_to_calm_ratio": 0})

    return {
        "avg_abs_contribution": {c: float(abs_contribs[c]) for c in contrib_cols},
        "relative_contribution": {c: float(abs_contribs[c] / total_abs) for c in contrib_cols},
        "crisis_vs_calm": crisis_calm_analysis,
        "most_crisis_sensitive": most_crisis_sensitive[0],
        "n_decomposed_days": len(decompositions),
        "decompositions_sample": decompositions[:5] + decompositions[-5:],  # First/last 5
    }


# ============================================================
#  Part D: Forecast Confidence via Model Agreement
# ============================================================

def part_d_forecast_confidence(df, har_result):
    """Test if component agreement predicts forecast accuracy."""
    print_section("Part D: Forecast Confidence via Component Agreement")

    abs_ret = df["abs_return"].values
    vix = df["VIX"].values
    dates = df.index

    oos_start_idx = np.searchsorted(dates, pd.Timestamp("2012-01-01"))
    min_train = 504
    if oos_start_idx < min_train + 22:
        oos_start_idx = min_train + 22

    # Use expanding window with periodic refitting
    current_coeffs = None
    refit_step = 66

    agreement_data = []

    print(f"  OOS period: {dates[oos_start_idx].strftime('%Y-%m-%d')} to "
          f"{dates[-2].strftime('%Y-%m-%d')}")

    t_start = time.time()

    for t in range(oos_start_idx, len(abs_ret) - 1):
        # Refit periodically
        if current_coeffs is None or (t - oos_start_idx) % refit_step == 0:
            train_abs = abs_ret[:t]
            result = fit_har_abs(train_abs, min_obs=252)
            if result is not None:
                current_coeffs = result

        if current_coeffs is None:
            continue

        # Features
        daily_feat = abs_ret[t]
        weekly_feat = np.mean(abs_ret[max(0, t - 4):t + 1]) if t >= 4 else daily_feat
        monthly_feat = np.mean(abs_ret[max(0, t - 21):t + 1]) if t >= 21 else weekly_feat

        # Each component's "signal" about vol level relative to long-run average
        long_run_abs = np.mean(abs_ret[:t])

        daily_signal = daily_feat / long_run_abs - 1  # % above/below average
        weekly_signal = weekly_feat / long_run_abs - 1
        monthly_signal = monthly_feat / long_run_abs - 1

        # Agreement: all three pointing same direction (all above or all below average)
        signs = np.sign([daily_signal, weekly_signal, monthly_signal])
        all_agree = (signs[0] == signs[1] == signs[2])

        # Disagreement magnitude: std of the three signals
        disagreement = np.std([daily_signal, weekly_signal, monthly_signal])

        # Forecast and realized
        forecast = (current_coeffs["intercept"] +
                    current_coeffs["beta_daily"] * daily_feat +
                    current_coeffs["beta_weekly"] * weekly_feat +
                    current_coeffs["beta_monthly"] * monthly_feat)
        forecast = max(forecast, 1e-6)
        realized = abs_ret[t + 1] if t + 1 < len(abs_ret) else np.nan

        if np.isfinite(realized) and realized > 0:
            # Use |r| / forecast ratio as accuracy metric
            # Perfect forecast: ratio = 1
            forecast_error = abs(realized - forecast) / forecast
            qlike_loss = realized ** 2 / forecast ** 2 + 2 * np.log(forecast) if forecast > 0 else np.nan

            agreement_data.append({
                "date": dates[t].strftime("%Y-%m-%d"),
                "all_agree": bool(all_agree),
                "disagreement": float(disagreement),
                "forecast_error": float(forecast_error),
                "daily_signal": float(daily_signal),
                "weekly_signal": float(weekly_signal),
                "monthly_signal": float(monthly_signal),
                "forecast": float(forecast),
                "realized": float(realized),
                "vix": float(vix[t]) if t < len(vix) and np.isfinite(vix[t]) else None,
            })

    print(f"  Total OOS days with agreement data: {len(agreement_data)} ({time.time() - t_start:.1f}s)")

    ad = pd.DataFrame(agreement_data)

    # Agreement vs Disagreement accuracy
    agree_mask = ad["all_agree"]
    agree_errors = ad.loc[agree_mask, "forecast_error"].values
    disagree_errors = ad.loc[~agree_mask, "forecast_error"].values

    print(f"\n  Agreement Analysis:")
    print(f"    Days with full agreement: {agree_mask.sum()} ({agree_mask.mean() * 100:.1f}%)")
    print(f"    Days with disagreement:   {(~agree_mask).sum()} ({(~agree_mask).mean() * 100:.1f}%)")
    print(f"    Mean forecast error (agree):    {np.mean(agree_errors):.4f}")
    print(f"    Mean forecast error (disagree): {np.mean(disagree_errors):.4f}")

    t_agree, p_agree = stats.ttest_ind(agree_errors, disagree_errors)
    print(f"    t-test: t={t_agree:.3f}, p={p_agree:.4f}")

    # Disagreement magnitude vs forecast error
    corr_disagree, p_corr = stats.pearsonr(ad["disagreement"].values, ad["forecast_error"].values)
    print(f"\n  Disagreement Magnitude → Forecast Error:")
    print(f"    Correlation: r={corr_disagree:.4f}, p={p_corr:.6f}")

    # Quintile analysis: sort by disagreement, compare errors
    ad_sorted = ad.sort_values("disagreement")
    n = len(ad_sorted)
    quintile_size = n // 5

    print(f"\n  Disagreement Quintile Analysis:")
    print(f"  {'Quintile':<10} {'Mean Disagr':>12} {'Mean Error':>12} {'N':>6}")
    print(f"  {'-' * 42}")

    quintile_results = []
    for q in range(5):
        start = q * quintile_size
        end = (q + 1) * quintile_size if q < 4 else n
        q_data = ad_sorted.iloc[start:end]
        mean_dis = q_data["disagreement"].mean()
        mean_err = q_data["forecast_error"].mean()
        quintile_results.append({
            "quintile": q + 1,
            "mean_disagreement": float(mean_dis),
            "mean_forecast_error": float(mean_err),
            "n": len(q_data),
        })
        print(f"  Q{q + 1:<9} {mean_dis:>12.4f} {mean_err:>12.4f} {len(q_data):>6}")

    # Monotonicity test: is Q5 error > Q1 error?
    q1_err = quintile_results[0]["mean_forecast_error"]
    q5_err = quintile_results[4]["mean_forecast_error"]
    monotone = q5_err > q1_err
    print(f"\n  Monotonicity: Q5 error ({q5_err:.4f}) {'>' if monotone else '<='} Q1 error ({q1_err:.4f})")
    print(f"  → High disagreement {'DOES' if monotone else 'does NOT'} predict worse forecasts")

    # Practical confidence indicator
    # Define: low disagreement (Q1-Q2) = HIGH confidence, high disagreement (Q4-Q5) = LOW confidence
    high_conf_mask = ad["disagreement"] <= ad["disagreement"].quantile(0.4)
    low_conf_mask = ad["disagreement"] >= ad["disagreement"].quantile(0.6)

    high_conf_err = ad.loc[high_conf_mask, "forecast_error"].mean()
    low_conf_err = ad.loc[low_conf_mask, "forecast_error"].mean()

    print(f"\n  Practical Confidence Indicator:")
    print(f"    HIGH confidence (low disagr) mean error: {high_conf_err:.4f} (n={high_conf_mask.sum()})")
    print(f"    LOW confidence (high disagr) mean error:  {low_conf_err:.4f} (n={low_conf_mask.sum()})")
    improvement = (low_conf_err - high_conf_err) / low_conf_err * 100
    print(f"    Error reduction by using confidence: {improvement:.1f}%")

    return {
        "agreement_rate": float(agree_mask.mean()),
        "agree_mean_error": float(np.mean(agree_errors)),
        "disagree_mean_error": float(np.mean(disagree_errors)),
        "agree_disagree_t_stat": float(t_agree),
        "agree_disagree_p_value": float(p_agree),
        "disagreement_error_correlation": float(corr_disagree),
        "disagreement_error_corr_p": float(p_corr),
        "quintile_results": quintile_results,
        "monotonicity": bool(monotone),
        "confidence_indicator": {
            "high_conf_error": float(high_conf_err),
            "low_conf_error": float(low_conf_err),
            "error_reduction_pct": float(improvement),
        },
        "n_oos_days": len(agreement_data),
    }


# ============================================================
#  Main
# ============================================================

def main():
    print_section("K765: Explainable AI for Volatility", char="*", width=72)
    print("  Which features and parameters drive vol forecasts?")
    print("  GARCH parameter importance + HAR feature importance + SHAP decomposition")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    overall_start = time.time()

    # Load data
    df = load_data()

    # Part A: GARCH Parameter Importance
    part_a_results = part_a_garch_parameter_importance(df)

    # Part B: HAR Feature Importance
    part_b_results = part_b_har_feature_importance(df)

    # Part C: SHAP-like Decomposition
    part_c_results = part_c_shap_decomposition(df, part_b_results)

    # Part D: Forecast Confidence
    part_d_results = part_d_forecast_confidence(df, part_b_results)

    # ============================================================
    #  Summary
    # ============================================================
    print_section("SUMMARY: Explainable AI for Volatility")

    print("\n  Part A — GJR-GARCH Parameter Importance:")
    print(f"    Most variable: {part_a_results['most_variable_param']} "
          f"(CV={part_a_results['param_stats'][part_a_results['most_variable_param']]['cv']:.3f})")
    print(f"    Most stable:   {part_a_results['most_stable_param']} "
          f"(CV={part_a_results['param_stats'][part_a_results['most_stable_param']]['cv']:.3f})")
    gpa = part_a_results["gamma_predicts_accuracy"]
    if "t_stat" in gpa:
        sig = "YES" if abs(gpa["t_stat"]) > 2 else "NO"
        print(f"    Gamma predicts accuracy? {sig} (t={gpa['t_stat']:.3f})")

    print(f"\n  Part B — HAR Feature Importance:")
    ri = part_b_results["relative_importance"]
    print(f"    Daily:   {ri['daily'] * 100:.1f}%")
    print(f"    Weekly:  {ri['weekly'] * 100:.1f}%")
    print(f"    Monthly: {ri['monthly'] * 100:.1f}%")
    print(f"    Dominant: {part_b_results['dominant_horizon']}")
    print(f"    R² mean: {part_b_results['r2_stats']['mean']:.4f}")

    print(f"\n  Part C — SHAP-like Decomposition:")
    rc = part_c_results["relative_contribution"]
    print(f"    Relative contribution: D={rc['daily_contrib'] * 100:.1f}%, "
          f"W={rc['weekly_contrib'] * 100:.1f}%, M={rc['monthly_contrib'] * 100:.1f}%")
    print(f"    Most crisis-sensitive: {part_c_results['most_crisis_sensitive']}")

    print(f"\n  Part D — Forecast Confidence:")
    ci = part_d_results["confidence_indicator"]
    print(f"    Agreement predicts accuracy? "
          f"{'YES' if part_d_results['monotonicity'] else 'NO'} (monotonic quintiles)")
    print(f"    Error reduction from confidence filtering: {ci['error_reduction_pct']:.1f}%")
    print(f"    Disagr-Error correlation: r={part_d_results['disagreement_error_correlation']:.4f} "
          f"(p={part_d_results['disagreement_error_corr_p']:.6f})")

    elapsed = time.time() - overall_start
    print(f"\n  Total runtime: {elapsed:.1f}s")

    # ============================================================
    #  Save results
    # ============================================================
    results = {
        "experiment_id": "K765",
        "title": "Explainable AI for Volatility — Which Features Matter Most?",
        "proposer": "Claude (from research_program)",
        "executor": "Claude",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "data_source": "yfinance (SPY, ^VIX)",
        "data_period": f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
        "n_observations": len(df),
        "methodology": {
            "part_a": "GJR-GARCH rolling 504-day windows, parameter tracking",
            "part_b": "HAR-ABS expanding window, coefficient tracking",
            "part_c": "SHAP-like analytical decomposition for additive HAR model",
            "part_d": "Component agreement as forecast confidence indicator",
        },
        "literature": [
            "Corsi (2009) — HAR-RV model",
            "Hansen & Lunde (2005) — 330 GARCH variants, (1,1) hard to beat",
            "Engle & Patton (2001) — GARCH parameter interpretation",
            "Lundbergh & Terasvirta (2002) — GARCH stability tests",
        ],
        "results": {
            "part_a_garch_params": {
                "param_stats": part_a_results["param_stats"],
                "most_variable": part_a_results["most_variable_param"],
                "most_stable": part_a_results["most_stable_param"],
                "gamma_predicts_accuracy": part_a_results["gamma_predicts_accuracy"],
                "n_windows": part_a_results["n_windows"],
            },
            "part_b_har_features": {
                "coeff_stats": part_b_results["coeff_stats"],
                "relative_importance": part_b_results["relative_importance"],
                "dominant_horizon": part_b_results["dominant_horizon"],
                "regime_analysis": part_b_results["regime_analysis"],
                "r2_stats": part_b_results["r2_stats"],
            },
            "part_c_shap_decomposition": {
                "relative_contribution": part_c_results["relative_contribution"],
                "crisis_vs_calm": part_c_results["crisis_vs_calm"],
                "most_crisis_sensitive": part_c_results["most_crisis_sensitive"],
                "n_decomposed_days": part_c_results["n_decomposed_days"],
                "sample_decompositions": part_c_results["decompositions_sample"],
            },
            "part_d_forecast_confidence": {
                "agreement_rate": part_d_results["agreement_rate"],
                "agree_vs_disagree": {
                    "agree_error": part_d_results["agree_mean_error"],
                    "disagree_error": part_d_results["disagree_mean_error"],
                    "t_stat": part_d_results["agree_disagree_t_stat"],
                    "p_value": part_d_results["agree_disagree_p_value"],
                },
                "disagreement_error_corr": {
                    "r": part_d_results["disagreement_error_correlation"],
                    "p": part_d_results["disagreement_error_corr_p"],
                },
                "quintile_results": part_d_results["quintile_results"],
                "monotonicity": part_d_results["monotonicity"],
                "confidence_indicator": part_d_results["confidence_indicator"],
                "n_oos_days": part_d_results["n_oos_days"],
            },
        },
        "key_findings": [],
        "runtime_seconds": round(elapsed, 1),
    }

    # Populate key findings
    findings = []

    # Finding 1: Most variable GARCH parameter
    mvp = part_a_results["most_variable_param"]
    findings.append(
        f"GJR-GARCH most variable parameter: {mvp} "
        f"(CV={part_a_results['param_stats'][mvp]['cv']:.3f}). "
        f"Most stable: {part_a_results['most_stable_param']} "
        f"(CV={part_a_results['param_stats'][part_a_results['most_stable_param']]['cv']:.3f})"
    )

    # Finding 2: Dominant HAR horizon
    findings.append(
        f"HAR-ABS dominant horizon: {part_b_results['dominant_horizon']} "
        f"(D={ri['daily'] * 100:.1f}%, W={ri['weekly'] * 100:.1f}%, M={ri['monthly'] * 100:.1f}%)"
    )

    # Finding 3: Crisis sensitivity
    findings.append(
        f"Most crisis-sensitive component: {part_c_results['most_crisis_sensitive']} — "
        f"increases most during high-VIX periods"
    )

    # Finding 4: Confidence indicator
    findings.append(
        f"Component agreement as confidence indicator: "
        f"{'WORKS' if part_d_results['monotonicity'] else 'FAILS'}. "
        f"Error reduction: {ci['error_reduction_pct']:.1f}%. "
        f"Corr(disagreement, error): r={part_d_results['disagreement_error_correlation']:.4f}"
    )

    results["key_findings"] = findings

    # Save
    results_path = project_root / "experiments" / "k765_xai_volatility_results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n  Results saved: {results_path}")

    print_section("DONE", char="*", width=72)

    return results


if __name__ == "__main__":
    results = main()
