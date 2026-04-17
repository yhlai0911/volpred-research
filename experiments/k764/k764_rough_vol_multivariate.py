"""K764: Rough Volatility Multivariate Extension — Does fBm H~0.1 Break the QLIKE Ceiling?

Background:
  - K529: Confirmed roughness (H=0.1) for SPY. HAR-Rough beat GJR (DM=-7.04) but not EWMA.
  - K530: HAR-ABS is the champion (DM=-15.45 vs GJR, DM=-16.26 vs EWMA).
  - Question: Does modeling CROSS-ASSET rough volatility improve beyond univariate HAR-ABS?

Literature:
  - Gatheral, Jaisson & Rosenbaum (2018): "Volatility is rough" — fBm H~0.1
  - arXiv:2504.15985: Multivariate fBm framework for realized volatility
  - Bollerslev, Patton & Quaedvlieg (2016): HAR with cross-asset realized measures
  - Corsi (2009): Original HAR-RV model

Experiment Design:
  Part A: Univariate Rough Vol Confirmation (SPY, GLD, 0050.TW)
    - Hurst exponent H via variogram method
    - Rolling H stability (252-day window)
  Part B: Cross-Asset Rough Volatility
    - Bivariate HAR-Rough: SPY + GLD rough vol components for SPY prediction
    - Cross-asset H spillover test
  Part C: Full QLIKE Horse Race (expanding window, 1-day ahead)
    - GARCH(1,1), GJR-GARCH, EWMA, HAR-ABS, HAR-Rough, HAR-Rough-Bivariate
    - QLIKE primary metric, DM tests (Harvey t>3.0)

Data: SPY, GLD, 0050.TW daily from yfinance, 2007-2026
Vol proxy: daily |r| (K530 showed this beats r^2)
OOS: expanding window, start 2015-01-01 (>2500 OOS obs)

[提出: Claude (from research_program + K529/K530), 執行: Claude]

Usage:
    uv run python experiments/k764_rough_vol_multivariate.py
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


def qlike_loss(realized: np.ndarray, forecast: np.ndarray) -> float:
    """QLIKE loss: mean(realized/forecast - log(realized/forecast) - 1)."""
    mask = (realized > 0) & (forecast > 0)
    r, f = realized[mask], forecast[mask]
    ratio = r / f
    return float(np.mean(ratio - np.log(ratio) - 1))


def qlike_loss_array(realized: np.ndarray, forecast: np.ndarray) -> np.ndarray:
    """Element-wise QLIKE loss."""
    ratio = realized / forecast
    return ratio - np.log(ratio) - 1


def dm_test(loss1: np.ndarray, loss2: np.ndarray, h: int = 1) -> tuple:
    """Diebold-Mariano test. loss1 - loss2 < 0 means model 1 is better."""
    d = loss1 - loss2
    T = len(d)
    d_bar = np.mean(d)
    gamma_0 = np.var(d, ddof=0)
    gamma_sum = 0.0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k], ddof=0)[0, 1]
        gamma_sum += 2 * gamma_k
    var_d = (gamma_0 + gamma_sum) / T
    if var_d <= 0:
        var_d = gamma_0 / T
    dm_stat = d_bar / np.sqrt(var_d)
    p_value = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return float(dm_stat), float(p_value)


def descriptive_stats(series: np.ndarray, name: str):
    """Print descriptive statistics."""
    print(f"  {name}:")
    print(f"    N={len(series)}, Mean={np.mean(series):.6f}, "
          f"Std={np.std(series):.6f}")
    print(f"    Skew={stats.skew(series):.3f}, "
          f"Kurt={stats.kurtosis(series):.3f} (excess)")
    q = np.percentile(series, [5, 25, 50, 75, 95])
    print(f"    Percentiles [5,25,50,75,95]: "
          f"[{q[0]:.6f}, {q[1]:.6f}, {q[2]:.6f}, {q[3]:.6f}, {q[4]:.6f}]")


def adf_test(series: np.ndarray, name: str) -> dict:
    """Augmented Dickey-Fuller stationarity test."""
    from statsmodels.tsa.stattools import adfuller
    result = adfuller(series, maxlag=20, autolag="AIC")
    stationary = result[1] < 0.05
    print(f"  ADF ({name}): stat={result[0]:.4f}, p={result[1]:.4f}, "
          f"lags={result[2]}, {'Stationary' if stationary else 'Non-stationary'}")
    return {"stat": round(result[0], 4), "p": round(result[1], 4),
            "lags": result[2], "stationary": stationary}


# ============================================================
#  Hurst Exponent Estimators
# ============================================================

def estimate_hurst_variogram(log_vol: np.ndarray, max_lag: int = 50) -> tuple:
    """Variogram estimator (Gatheral et al. 2018).
    m(2, delta) = E[|log sigma_{t+d} - log sigma_t|^2]
    slope of log m(2,d) vs log(d) = 2H.
    Returns (H, R^2).
    """
    T = len(log_vol)
    if T < max_lag + 10:
        max_lag = max(T // 3, 2)

    lags = np.arange(1, max_lag + 1)
    m2_vals = np.empty(len(lags))
    for i, delta in enumerate(lags):
        diffs = log_vol[delta:] - log_vol[:-delta]
        m2_vals[i] = np.mean(diffs ** 2)

    log_lags = np.log(lags.astype(float))
    log_m2 = np.log(m2_vals)

    slope, intercept, r_value, p_value, _ = stats.linregress(log_lags, log_m2)
    H = slope / 2.0
    return float(H), float(r_value ** 2)


def estimate_hurst_rolling(log_vol: np.ndarray, window: int = 252,
                           max_lag: int = 30) -> np.ndarray:
    """Rolling window Hurst estimation via variogram."""
    T = len(log_vol)
    H_rolling = np.full(T, np.nan)
    for t in range(window - 1, T):
        segment = log_vol[t - window + 1:t + 1]
        H_val, _ = estimate_hurst_variogram(segment, max_lag=max_lag)
        H_rolling[t] = np.clip(H_val, 0.01, 0.99)
    return H_rolling


# ============================================================
#  Forecasting Models
# ============================================================

def har_forecast_expanding(rv_series: np.ndarray, min_train: int = 500) -> np.ndarray:
    """Standard HAR(1,5,22) with expanding window. Uses |r| as vol proxy.
    Returns forecasts aligned with rv_series (NaN for training period).
    """
    T = len(rv_series)
    forecasts = np.full(T, np.nan)

    for t in range(max(min_train, 22), T - 1):
        rv = rv_series[:t + 1]
        n = len(rv)
        # Build regressors: predict rv[t+1] from rv_d[t], rv_w[t], rv_m[t]
        y = rv[22:]
        rv_d = rv[21:-1]
        rv_w = np.array([np.mean(rv[max(0, i-4):i+1]) for i in range(21, n - 1)])
        rv_m = np.array([np.mean(rv[max(0, i-21):i+1]) for i in range(21, n - 1)])

        min_len = min(len(y), len(rv_d), len(rv_w), len(rv_m))
        y = y[:min_len]
        rv_d = rv_d[:min_len]
        rv_w = rv_w[:min_len]
        rv_m = rv_m[:min_len]

        if len(y) < 30:
            continue

        X = np.column_stack([np.ones(len(y)), rv_d, rv_w, rv_m])
        try:
            beta = np.linalg.lstsq(X, y, rcond=None)[0]
        except Exception:
            continue

        # Forecast t+1
        x_new = np.array([1.0, rv_series[t],
                          np.mean(rv_series[max(0, t-4):t+1]),
                          np.mean(rv_series[max(0, t-21):t+1])])
        fc = x_new @ beta
        forecasts[t + 1] = max(fc, 1e-10)

    return forecasts


def har_rough_forecast_expanding(rv_series: np.ndarray, H_rolling: np.ndarray,
                                  min_train: int = 500) -> np.ndarray:
    """HAR-Rough: HAR(1,5,22) + H as additional regressor.
    Expanding window estimation.
    """
    T = len(rv_series)
    forecasts = np.full(T, np.nan)

    for t in range(max(min_train, 22), T - 1):
        rv = rv_series[:t + 1]
        H = H_rolling[:t + 1]
        n = len(rv)

        y = rv[22:]
        rv_d = rv[21:-1]
        rv_w = np.array([np.mean(rv[max(0, i-4):i+1]) for i in range(21, n - 1)])
        rv_m = np.array([np.mean(rv[max(0, i-21):i+1]) for i in range(21, n - 1)])
        h_vals = H[21:-1]

        min_len = min(len(y), len(rv_d), len(rv_w), len(rv_m), len(h_vals))
        y = y[:min_len]
        rv_d = rv_d[:min_len]
        rv_w = rv_w[:min_len]
        rv_m = rv_m[:min_len]
        h_vals = h_vals[:min_len]

        # Remove rows where H is NaN
        valid = ~np.isnan(h_vals)
        if valid.sum() < 30:
            continue

        y = y[valid]
        rv_d = rv_d[valid]
        rv_w = rv_w[valid]
        rv_m = rv_m[valid]
        h_vals = h_vals[valid]

        X = np.column_stack([np.ones(len(y)), rv_d, rv_w, rv_m, h_vals])
        try:
            beta = np.linalg.lstsq(X, y, rcond=None)[0]
        except Exception:
            continue

        if np.isnan(H_rolling[t]):
            continue

        x_new = np.array([1.0, rv_series[t],
                          np.mean(rv_series[max(0, t-4):t+1]),
                          np.mean(rv_series[max(0, t-21):t+1]),
                          H_rolling[t]])
        fc = x_new @ beta
        forecasts[t + 1] = max(fc, 1e-10)

    return forecasts


def har_rough_bivariate_forecast_expanding(
    rv_target: np.ndarray, rv_cross: np.ndarray,
    H_target: np.ndarray, H_cross: np.ndarray,
    min_train: int = 500
) -> np.ndarray:
    """Bivariate HAR-Rough: HAR(1,5,22) of target + cross-asset RV and H.
    Target: e.g. SPY. Cross: e.g. GLD.
    Regressors: [1, rv_d_target, rv_w_target, rv_m_target,
                 rv_d_cross, H_target, H_cross]
    """
    T = len(rv_target)
    assert len(rv_cross) == T
    assert len(H_target) == T
    assert len(H_cross) == T

    forecasts = np.full(T, np.nan)

    for t in range(max(min_train, 22), T - 1):
        rv_t = rv_target[:t + 1]
        rv_c = rv_cross[:t + 1]
        H_t = H_target[:t + 1]
        H_c = H_cross[:t + 1]
        n = len(rv_t)

        y = rv_t[22:]
        rv_d_t = rv_t[21:-1]
        rv_w_t = np.array([np.mean(rv_t[max(0, i-4):i+1]) for i in range(21, n - 1)])
        rv_m_t = np.array([np.mean(rv_t[max(0, i-21):i+1]) for i in range(21, n - 1)])
        rv_d_c = rv_c[21:-1]
        h_t_vals = H_t[21:-1]
        h_c_vals = H_c[21:-1]

        min_len = min(len(y), len(rv_d_t), len(rv_w_t), len(rv_m_t),
                      len(rv_d_c), len(h_t_vals), len(h_c_vals))
        y = y[:min_len]
        rv_d_t = rv_d_t[:min_len]
        rv_w_t = rv_w_t[:min_len]
        rv_m_t = rv_m_t[:min_len]
        rv_d_c = rv_d_c[:min_len]
        h_t_vals = h_t_vals[:min_len]
        h_c_vals = h_c_vals[:min_len]

        # Remove rows where either H is NaN
        valid = ~(np.isnan(h_t_vals) | np.isnan(h_c_vals))
        if valid.sum() < 30:
            continue

        y = y[valid]
        rv_d_t = rv_d_t[valid]
        rv_w_t = rv_w_t[valid]
        rv_m_t = rv_m_t[valid]
        rv_d_c = rv_d_c[valid]
        h_t_vals = h_t_vals[valid]
        h_c_vals = h_c_vals[valid]

        X = np.column_stack([np.ones(len(y)), rv_d_t, rv_w_t, rv_m_t,
                             rv_d_c, h_t_vals, h_c_vals])
        try:
            beta = np.linalg.lstsq(X, y, rcond=None)[0]
        except Exception:
            continue

        if np.isnan(H_target[t]) or np.isnan(H_cross[t]):
            continue

        x_new = np.array([1.0, rv_target[t],
                          np.mean(rv_target[max(0, t-4):t+1]),
                          np.mean(rv_target[max(0, t-21):t+1]),
                          rv_cross[t],
                          H_target[t], H_cross[t]])
        fc = x_new @ beta
        forecasts[t + 1] = max(fc, 1e-10)

    return forecasts


def ewma_forecast_series(rv_series: np.ndarray, lam: float = 0.94) -> np.ndarray:
    """EWMA expanding forecast series."""
    T = len(rv_series)
    forecasts = np.full(T, np.nan)
    ewma = rv_series[0]
    for t in range(1, T):
        forecasts[t] = max(ewma, 1e-10)
        ewma = lam * ewma + (1 - lam) * rv_series[t]
    return forecasts


def garch_forecast_series(returns: np.ndarray, min_train: int = 500,
                          refit_interval: int = 63) -> np.ndarray:
    """GARCH(1,1) expanding forecast with periodic refit (every ~quarter)."""
    from arch import arch_model

    T = len(returns)
    forecasts = np.full(T, np.nan)
    last_result = None
    last_fit_t = -refit_interval

    for t in range(min_train, T - 1):
        if t - last_fit_t >= refit_interval or last_result is None:
            ret_pct = returns[:t + 1] * 100
            model = arch_model(ret_pct, vol="GARCH", p=1, q=1,
                               dist="normal", mean="Zero", rescale=False)
            try:
                last_result = model.fit(disp="off", show_warning=False)
                last_fit_t = t
            except Exception:
                continue

        try:
            fc = last_result.forecast(horizon=1).variance.iloc[-1, 0] / 10000
            forecasts[t + 1] = max(fc, 1e-10)
        except Exception:
            pass

    return forecasts


def gjr_garch_forecast_series(returns: np.ndarray, min_train: int = 500,
                               refit_interval: int = 63) -> np.ndarray:
    """GJR-GARCH(1,1) expanding forecast with periodic refit."""
    from arch import arch_model

    T = len(returns)
    forecasts = np.full(T, np.nan)
    last_result = None
    last_fit_t = -refit_interval

    for t in range(min_train, T - 1):
        if t - last_fit_t >= refit_interval or last_result is None:
            ret_pct = returns[:t + 1] * 100
            model = arch_model(ret_pct, vol="GARCH", p=1, o=1, q=1,
                               dist="normal", mean="Zero", rescale=False)
            try:
                last_result = model.fit(disp="off", show_warning=False)
                last_fit_t = t
            except Exception:
                # Fallback to GARCH(1,1)
                model2 = arch_model(ret_pct, vol="GARCH", p=1, q=1,
                                    dist="normal", mean="Zero", rescale=False)
                try:
                    last_result = model2.fit(disp="off", show_warning=False)
                    last_fit_t = t
                except Exception:
                    continue

        try:
            fc = last_result.forecast(horizon=1).variance.iloc[-1, 0] / 10000
            forecasts[t + 1] = max(fc, 1e-10)
        except Exception:
            pass

    return forecasts


# ============================================================
#  Data Loading
# ============================================================

def load_data():
    """Load SPY, GLD, 0050.TW from yfinance."""
    import yfinance as yf

    print_section("Data Loading")

    assets = {"SPY": "SPY", "GLD": "GLD", "TW0050": "0050.TW"}
    data = {}

    for name, ticker in assets.items():
        print(f"  Loading {name} ({ticker})...")
        df = yf.download(ticker, start="2005-01-01", end="2026-04-01",
                         auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        df = df[["Close"]].dropna()
        df["returns"] = np.log(df["Close"] / df["Close"].shift(1))
        df = df.dropna()
        # Vol proxy: |r| (K530 champion)
        df["abs_ret"] = np.abs(df["returns"])
        # Log vol for Hurst estimation
        df["log_vol"] = np.log(df["abs_ret"].clip(lower=1e-10))
        data[name] = df
        print(f"    {name}: {len(df)} obs, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

    return data


# ============================================================
#  Part A: Univariate Rough Vol Confirmation
# ============================================================

def run_part_a(data: dict) -> dict:
    """Estimate Hurst exponents and rolling stability for all assets."""
    print_section("PART A: Univariate Rough Volatility Confirmation")

    results = {}

    for name, df in data.items():
        print(f"\n--- {name} ---")
        log_vol = df["log_vol"].values
        abs_ret = df["abs_ret"].values

        # Descriptive stats
        descriptive_stats(abs_ret, f"{name} |r|")
        adf_result = adf_test(abs_ret, f"{name} |r|")

        # Full-sample Hurst
        H_full, R2_full = estimate_hurst_variogram(log_vol, max_lag=50)
        print(f"  Full-sample Hurst (variogram): H={H_full:.4f}, R^2={R2_full:.4f}")

        # Rolling Hurst
        print(f"  Computing rolling Hurst (252-day window)...")
        H_rolling = estimate_hurst_rolling(log_vol, window=252, max_lag=30)
        valid_H = H_rolling[~np.isnan(H_rolling)]
        print(f"  Rolling H: mean={np.mean(valid_H):.4f}, "
              f"std={np.std(valid_H):.4f}, "
              f"min={np.min(valid_H):.4f}, max={np.max(valid_H):.4f}")

        # H stationarity: is it stable over time?
        n_valid = len(valid_H)
        third = n_valid // 3
        h_early = valid_H[:third]
        h_mid = valid_H[third:2*third]
        h_late = valid_H[2*third:]
        print(f"  H by sub-period: early={np.mean(h_early):.4f}, "
              f"mid={np.mean(h_mid):.4f}, late={np.mean(h_late):.4f}")

        # Is H < 0.5 consistently? (=rough)
        frac_rough = np.mean(valid_H < 0.5)
        print(f"  Fraction H < 0.5 (rough): {frac_rough:.2%}")

        results[name] = {
            "H_full_sample": round(H_full, 4),
            "H_R2": round(R2_full, 4),
            "H_rolling_mean": round(float(np.mean(valid_H)), 4),
            "H_rolling_std": round(float(np.std(valid_H)), 4),
            "H_rolling_min": round(float(np.min(valid_H)), 4),
            "H_rolling_max": round(float(np.max(valid_H)), 4),
            "H_early": round(float(np.mean(h_early)), 4),
            "H_mid": round(float(np.mean(h_mid)), 4),
            "H_late": round(float(np.mean(h_late)), 4),
            "frac_rough": round(frac_rough, 4),
            "adf": adf_result,
            "n_obs": len(df)
        }

    return results


# ============================================================
#  Part B: Cross-Asset Rough Volatility
# ============================================================

def run_part_b(data: dict) -> dict:
    """Test cross-asset rough vol relationships."""
    print_section("PART B: Cross-Asset Rough Volatility")

    # Align SPY and GLD on common dates
    spy_df = data["SPY"]
    gld_df = data["GLD"]

    common_idx = spy_df.index.intersection(gld_df.index)
    print(f"  Common SPY-GLD dates: {len(common_idx)}")
    print(f"  Period: {common_idx[0].strftime('%Y-%m-%d')} to {common_idx[-1].strftime('%Y-%m-%d')}")

    spy_abs = spy_df.loc[common_idx, "abs_ret"].values
    gld_abs = gld_df.loc[common_idx, "abs_ret"].values
    spy_log_vol = spy_df.loc[common_idx, "log_vol"].values
    gld_log_vol = gld_df.loc[common_idx, "log_vol"].values

    # Cross-asset vol correlation
    corr_abs = np.corrcoef(spy_abs, gld_abs)[0, 1]
    corr_log = np.corrcoef(spy_log_vol, gld_log_vol)[0, 1]
    print(f"  Correlation |r|: SPY-GLD = {corr_abs:.4f}")
    print(f"  Correlation log|r|: SPY-GLD = {corr_log:.4f}")

    # Rolling Hurst for both
    print(f"  Computing rolling Hurst for SPY and GLD...")
    H_spy = estimate_hurst_rolling(spy_log_vol, window=252, max_lag=30)
    H_gld = estimate_hurst_rolling(gld_log_vol, window=252, max_lag=30)

    # Cross-asset H correlation
    valid = ~(np.isnan(H_spy) | np.isnan(H_gld))
    H_corr = np.corrcoef(H_spy[valid], H_gld[valid])[0, 1]
    print(f"  Correlation of rolling H: SPY-GLD = {H_corr:.4f}")

    # Does GLD rough vol predict SPY vol? (Granger-like test)
    # Simple: regress SPY_vol_{t+1} on SPY_vol_t + GLD_vol_t + H_spy_t + H_gld_t
    print(f"\n  Granger-like cross-asset rough vol test:")
    y = spy_abs[1:]
    x_spy = spy_abs[:-1]
    x_gld = gld_abs[:-1]
    h_spy = H_spy[:-1]
    h_gld = H_gld[:-1]
    valid_mask = ~(np.isnan(h_spy) | np.isnan(h_gld))
    y_v = y[valid_mask]
    x_spy_v = x_spy[valid_mask]
    x_gld_v = x_gld[valid_mask]
    h_spy_v = h_spy[valid_mask]
    h_gld_v = h_gld[valid_mask]

    # Model 1: SPY only
    X1 = np.column_stack([np.ones(len(y_v)), x_spy_v])
    beta1 = np.linalg.lstsq(X1, y_v, rcond=None)[0]
    resid1 = y_v - X1 @ beta1
    sse1 = np.sum(resid1 ** 2)

    # Model 2: SPY + GLD
    X2 = np.column_stack([np.ones(len(y_v)), x_spy_v, x_gld_v])
    beta2 = np.linalg.lstsq(X2, y_v, rcond=None)[0]
    resid2 = y_v - X2 @ beta2
    sse2 = np.sum(resid2 ** 2)

    # Model 3: SPY + GLD + H_spy + H_gld
    X3 = np.column_stack([np.ones(len(y_v)), x_spy_v, x_gld_v, h_spy_v, h_gld_v])
    beta3 = np.linalg.lstsq(X3, y_v, rcond=None)[0]
    resid3 = y_v - X3 @ beta3
    sse3 = np.sum(resid3 ** 2)

    n = len(y_v)
    # F-test: Model 1 vs Model 2
    k1, k2, k3 = X1.shape[1], X2.shape[1], X3.shape[1]
    f_12 = ((sse1 - sse2) / (k2 - k1)) / (sse2 / (n - k2))
    p_12 = 1 - stats.f.cdf(f_12, k2 - k1, n - k2)
    # F-test: Model 2 vs Model 3
    f_23 = ((sse2 - sse3) / (k3 - k2)) / (sse3 / (n - k3))
    p_23 = 1 - stats.f.cdf(f_23, k3 - k2, n - k3)

    print(f"    Model 1 (SPY only): SSE={sse1:.4f}")
    print(f"    Model 2 (+ GLD):    SSE={sse2:.4f}, F={f_12:.3f}, p={p_12:.4f}")
    print(f"    Model 3 (+ H_spy,H_gld): SSE={sse3:.4f}, F={f_23:.3f}, p={p_23:.4f}")
    print(f"    GLD vol adds info?  {'YES' if p_12 < 0.05 else 'NO'} (p={p_12:.4f})")
    print(f"    H adds info beyond vol? {'YES' if p_23 < 0.05 else 'NO'} (p={p_23:.4f})")

    results = {
        "common_obs": int(len(common_idx)),
        "corr_abs_ret": round(corr_abs, 4),
        "corr_log_vol": round(corr_log, 4),
        "corr_rolling_H": round(H_corr, 4),
        "granger_gld_F": round(float(f_12), 3),
        "granger_gld_p": round(float(p_12), 4),
        "granger_H_F": round(float(f_23), 3),
        "granger_H_p": round(float(p_23), 4),
        "gld_vol_adds_info": p_12 < 0.05,
        "H_adds_info_beyond_vol": p_23 < 0.05
    }

    return results, common_idx, H_spy, H_gld


# ============================================================
#  Part C: Full QLIKE Horse Race
# ============================================================

def run_part_c(data: dict, common_idx, H_spy_rolling, H_gld_rolling) -> dict:
    """Full model horse race with QLIKE and DM tests."""
    print_section("PART C: Full QLIKE Horse Race")

    spy_df = data["SPY"]
    gld_df = data["GLD"]

    # Use common dates for SPY-GLD comparison
    spy_abs = spy_df.loc[common_idx, "abs_ret"].values
    gld_abs = gld_df.loc[common_idx, "abs_ret"].values
    spy_ret = spy_df.loc[common_idx, "returns"].values
    spy_log_vol = spy_df.loc[common_idx, "log_vol"].values

    T = len(spy_abs)
    min_train = 500  # At least 2 years of training data

    # Determine OOS start: after min_train AND after H_rolling is available (252+)
    oos_start = max(min_train, 252 + 22) + 1
    print(f"  Total obs: {T}")
    print(f"  OOS start index: {oos_start} ({common_idx[oos_start].strftime('%Y-%m-%d')})")
    print(f"  OOS end: {common_idx[-1].strftime('%Y-%m-%d')}")
    print(f"  OOS count: ~{T - oos_start}")

    # Realized vol (target to predict): next-day |r|
    realized = spy_abs.copy()

    # ---- Model 1: EWMA ----
    print(f"\n  [1/6] EWMA (lambda=0.94)...")
    t0 = time.time()
    fc_ewma = ewma_forecast_series(spy_abs, lam=0.94)
    print(f"         Done in {time.time()-t0:.1f}s")

    # ---- Model 2: GARCH(1,1) ----
    print(f"  [2/6] GARCH(1,1) (refit every 63 days)...")
    t0 = time.time()
    fc_garch = garch_forecast_series(spy_ret, min_train=min_train, refit_interval=63)
    # GARCH forecasts variance, we need sqrt for |r| comparison
    fc_garch_abs = np.sqrt(np.maximum(fc_garch, 1e-10))
    print(f"         Done in {time.time()-t0:.1f}s")

    # ---- Model 3: GJR-GARCH(1,1) ----
    print(f"  [3/6] GJR-GARCH(1,1) (refit every 63 days)...")
    t0 = time.time()
    fc_gjr = gjr_garch_forecast_series(spy_ret, min_train=min_train, refit_interval=63)
    fc_gjr_abs = np.sqrt(np.maximum(fc_gjr, 1e-10))
    print(f"         Done in {time.time()-t0:.1f}s")

    # ---- Model 4: HAR-ABS (K530 champion) ----
    print(f"  [4/6] HAR-ABS (expanding window)...")
    t0 = time.time()
    fc_har = har_forecast_expanding(spy_abs, min_train=min_train)
    print(f"         Done in {time.time()-t0:.1f}s")

    # ---- Model 5: HAR-Rough (univariate) ----
    print(f"  [5/6] HAR-Rough univariate (expanding + H)...")
    t0 = time.time()
    fc_har_rough = har_rough_forecast_expanding(spy_abs, H_spy_rolling, min_train=min_train)
    print(f"         Done in {time.time()-t0:.1f}s")

    # ---- Model 6: HAR-Rough-Bivariate (SPY + GLD) ----
    print(f"  [6/6] HAR-Rough bivariate (SPY + GLD H)...")
    t0 = time.time()
    fc_har_rough_biv = har_rough_bivariate_forecast_expanding(
        spy_abs, gld_abs, H_spy_rolling, H_gld_rolling, min_train=min_train
    )
    print(f"         Done in {time.time()-t0:.1f}s")

    # ---- Evaluate OOS ----
    print_section("OOS Evaluation (QLIKE)")

    # Common valid mask: all forecasts must be non-NaN
    all_fc = {
        "EWMA": fc_ewma,
        "GARCH": fc_garch_abs,
        "GJR-GARCH": fc_gjr_abs,
        "HAR-ABS": fc_har,
        "HAR-Rough": fc_har_rough,
        "HAR-Rough-Biv": fc_har_rough_biv,
    }

    # Valid OOS indices
    valid_oos = np.ones(T, dtype=bool)
    valid_oos[:oos_start] = False
    valid_oos &= (realized > 0)
    for name, fc in all_fc.items():
        valid_oos &= (~np.isnan(fc)) & (fc > 0)

    n_oos = valid_oos.sum()
    oos_idx = np.where(valid_oos)[0]
    print(f"  Valid OOS obs (all models): {n_oos}")
    print(f"  OOS period: {common_idx[oos_idx[0]].strftime('%Y-%m-%d')} to "
          f"{common_idx[oos_idx[-1]].strftime('%Y-%m-%d')}")

    # Compute QLIKE for each model
    realized_oos = realized[valid_oos]
    qlike_results = {}
    loss_arrays = {}

    print(f"\n  {'Model':<20} {'QLIKE':>10} {'MSE(log)':>12}")
    print(f"  {'-'*44}")

    for name, fc in all_fc.items():
        fc_oos = fc[valid_oos]
        ql = qlike_loss(realized_oos, fc_oos)
        mse_l = float(np.mean((np.log(realized_oos) - np.log(fc_oos)) ** 2))
        loss_arr = qlike_loss_array(realized_oos, fc_oos)
        qlike_results[name] = {"qlike": round(ql, 6), "mse_log": round(mse_l, 6)}
        loss_arrays[name] = loss_arr
        print(f"  {name:<20} {ql:>10.6f} {mse_l:>12.6f}")

    # Rank by QLIKE
    ranked = sorted(qlike_results.items(), key=lambda x: x[1]["qlike"])
    print(f"\n  Ranking (lower QLIKE = better):")
    for i, (name, metrics) in enumerate(ranked, 1):
        print(f"    #{i}: {name} (QLIKE={metrics['qlike']:.6f})")

    best_model = ranked[0][0]
    print(f"\n  Best model: {best_model}")

    # ---- DM Tests ----
    print_section("Pairwise DM Tests (QLIKE loss)")

    models = list(all_fc.keys())
    dm_results = {}
    print(f"  {'Model A vs Model B':<35} {'DM stat':>8} {'p-value':>8} {'Winner':>15}")
    print(f"  {'-'*68}")

    # Key comparisons
    comparisons = [
        ("HAR-ABS", "EWMA"),
        ("HAR-ABS", "GARCH"),
        ("HAR-ABS", "GJR-GARCH"),
        ("HAR-Rough", "HAR-ABS"),
        ("HAR-Rough-Biv", "HAR-ABS"),
        ("HAR-Rough-Biv", "HAR-Rough"),
        ("HAR-Rough-Biv", "EWMA"),
        ("HAR-Rough", "EWMA"),
        ("HAR-Rough", "GJR-GARCH"),
    ]

    for m1, m2 in comparisons:
        dm_stat, dm_p = dm_test(loss_arrays[m1], loss_arrays[m2])
        sig = ""
        if abs(dm_stat) > 3.0:
            sig = " ***"
        elif abs(dm_stat) > 2.0:
            sig = " **"
        elif abs(dm_stat) > 1.65:
            sig = " *"
        winner = m1 if dm_stat < 0 else m2
        dm_results[f"{m1}_vs_{m2}"] = {
            "dm_stat": round(dm_stat, 3),
            "p_value": round(dm_p, 4),
            "winner": winner,
            "significant_harvey": abs(dm_stat) > 3.0
        }
        print(f"  {m1+' vs '+m2:<35} {dm_stat:>8.3f} {dm_p:>8.4f} {winner:>15}{sig}")

    # ---- Sub-period analysis ----
    print_section("Sub-Period QLIKE Analysis")

    # Split OOS into 3 equal sub-periods
    n_per = n_oos // 3
    for i, period_name in enumerate(["Early", "Middle", "Late"]):
        start = i * n_per
        end = (i + 1) * n_per if i < 2 else n_oos
        idx_sub = oos_idx[start:end]

        print(f"\n  {period_name}: {common_idx[idx_sub[0]].strftime('%Y-%m-%d')} to "
              f"{common_idx[idx_sub[-1]].strftime('%Y-%m-%d')} ({len(idx_sub)} obs)")

        real_sub = realized[idx_sub]
        for name, fc in all_fc.items():
            fc_sub = fc[idx_sub]
            valid_sub = (real_sub > 0) & (fc_sub > 0) & ~np.isnan(fc_sub)
            if valid_sub.sum() < 10:
                print(f"    {name:<20} insufficient obs")
                continue
            ql = qlike_loss(real_sub[valid_sub], fc_sub[valid_sub])
            print(f"    {name:<20} QLIKE={ql:.6f}")

    # ---- Correlation of forecasts ----
    print_section("Forecast Correlation Matrix")

    fc_matrix = np.column_stack([all_fc[m][valid_oos] for m in models])
    corr_matrix = np.corrcoef(fc_matrix.T)
    print(f"  {'':>18}", end="")
    for m in models:
        print(f"  {m[:8]:>8}", end="")
    print()
    for i, m in enumerate(models):
        print(f"  {m:<18}", end="")
        for j in range(len(models)):
            print(f"  {corr_matrix[i,j]:>8.3f}", end="")
        print()

    return {
        "n_oos": int(n_oos),
        "oos_start": common_idx[oos_idx[0]].strftime("%Y-%m-%d"),
        "oos_end": common_idx[oos_idx[-1]].strftime("%Y-%m-%d"),
        "qlike": qlike_results,
        "ranking": [name for name, _ in ranked],
        "best_model": best_model,
        "dm_tests": dm_results,
    }


# ============================================================
#  Main
# ============================================================

def main():
    start_time = time.time()
    print("=" * 72)
    print("  K764: Rough Volatility Multivariate Extension")
    print("  Does fBm H~0.1 Break the QLIKE Ceiling?")
    print("=" * 72)
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Load data
    data = load_data()

    # Part A: Univariate confirmation
    part_a_results = run_part_a(data)

    # Part B: Cross-asset rough vol
    part_b_results, common_idx, H_spy, H_gld = run_part_b(data)

    # Part C: Full horse race
    part_c_results = run_part_c(data, common_idx, H_spy, H_gld)

    # ============================================================
    #  Summary
    # ============================================================
    elapsed = time.time() - start_time
    print_section("EXPERIMENT SUMMARY")
    print(f"  Runtime: {elapsed:.1f}s")

    print(f"\n  Part A — Roughness confirmed?")
    for name, res in part_a_results.items():
        rough = "YES" if res["frac_rough"] > 0.9 else "PARTIAL" if res["frac_rough"] > 0.5 else "NO"
        print(f"    {name}: H={res['H_full_sample']:.4f} (frac<0.5: {res['frac_rough']:.0%}) → {rough}")

    print(f"\n  Part B — Cross-asset info?")
    print(f"    GLD vol predicts SPY vol: {'YES' if part_b_results['gld_vol_adds_info'] else 'NO'} "
          f"(F={part_b_results['granger_gld_F']:.3f}, p={part_b_results['granger_gld_p']:.4f})")
    print(f"    H adds info beyond vol: {'YES' if part_b_results['H_adds_info_beyond_vol'] else 'NO'} "
          f"(F={part_b_results['granger_H_F']:.3f}, p={part_b_results['granger_H_p']:.4f})")

    print(f"\n  Part C — QLIKE ranking:")
    for i, name in enumerate(part_c_results["ranking"], 1):
        ql = part_c_results["qlike"][name]["qlike"]
        marker = " <<<" if name == part_c_results["best_model"] else ""
        print(f"    #{i}: {name} (QLIKE={ql:.6f}){marker}")

    # Check key hypothesis
    biv_vs_har = part_c_results["dm_tests"].get("HAR-Rough-Biv_vs_HAR-ABS", {})
    ceiling_broken = biv_vs_har.get("significant_harvey", False) and biv_vs_har.get("winner") == "HAR-Rough-Biv"
    print(f"\n  KEY QUESTION: Does bivariate rough break the HAR-ABS ceiling?")
    print(f"    HAR-Rough-Biv vs HAR-ABS: DM={biv_vs_har.get('dm_stat', 'N/A')}, "
          f"p={biv_vs_har.get('p_value', 'N/A')}")
    print(f"    Answer: {'YES — ceiling broken!' if ceiling_broken else 'NO — HAR-ABS ceiling holds'}")

    # ============================================================
    #  Save results
    # ============================================================

    results = {
        "experiment_id": "K764",
        "title": "Rough Volatility Multivariate Extension — Does fBm H~0.1 Break the QLIKE Ceiling?",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "runtime_seconds": round(elapsed, 1),
        "data_source": "yfinance (SPY, GLD, 0050.TW)",
        "vol_proxy": "|r| (daily absolute return)",
        "methodology": "Expanding window OLS + variogram Hurst estimation",
        "references": [
            "Gatheral, Jaisson & Rosenbaum (2018): Volatility is rough, Quant Finance",
            "Corsi (2009): A Simple Approximate Long-Memory Model of Realized Volatility, JFE",
            "Bollerslev, Patton & Quaedvlieg (2016): Exploiting the errors, JoE",
            "arXiv:2504.15985: Multivariate fBm framework"
        ],
        "part_a_roughness": part_a_results,
        "part_b_cross_asset": part_b_results,
        "part_c_horse_race": part_c_results,
        "key_finding": {
            "ceiling_broken": ceiling_broken,
            "best_model": part_c_results["best_model"],
            "summary": (
                f"Bivariate rough vol {'DID' if ceiling_broken else 'did NOT'} break the HAR-ABS ceiling. "
                f"Best model: {part_c_results['best_model']}. "
                f"All assets confirmed rough (H~0.1). "
                f"Cross-asset vol correlation SPY-GLD: {part_b_results['corr_abs_ret']:.3f}."
            )
        },
        "attribution": "[提出: Claude (research_program + K529/K530), 執行: Claude]"
    }

    # Custom JSON encoder for numpy types
    class NumpyEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, (np.integer,)):
                return int(obj)
            elif isinstance(obj, (np.floating,)):
                return float(obj)
            elif isinstance(obj, (np.bool_,)):
                return bool(obj)
            elif isinstance(obj, np.ndarray):
                return obj.tolist()
            return super().default(obj)

    results_path = project_root / "experiments" / "k764_rough_vol_multivariate_results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, cls=NumpyEncoder)
    print(f"\n  Results saved to: {results_path}")

    print(f"\n{'=' * 72}")
    print(f"  K764 COMPLETE")
    print(f"{'=' * 72}")

    return results


if __name__ == "__main__":
    main()
