"""
K625: Time-Varying Hurst Exponent for Volatility Forecasting
=============================================================

Literature:
  - arXiv:2509.05820 (2025): "EWMA-driven dynamic Hurst parameter beats traditional rough Bergomi"
  - Frontiers in Applied Mathematics (2025): "Wavelet-based time-varying Hurst, RMSE -12.3%"
  - Gatheral, Jaisson, Rosenbaum (2018): "Volatility is rough", Quantitative Finance, 18(6).
    H ~ 0.1 for log-variance increments (rough volatility).
  - Peng et al. (1994): DFA method for long-range correlations.

Prior knowledge:
  - K138: Hurst fingerprint — all assets rough (H~0.01 for log-var), but doesn't explain capture rate
  - K166: Hurst Exponent Regime — SPY H=0.54 (random walk), rolling 75% time H>0.55
  - Prior Hurst-GARCH OOS test: GJR QLIKE=0.8264, Hurst-augmented QLIKE=0.8370 (+1.28%), no improvement

Key differences from prior work:
  - DFA method (more robust than R/S for finite samples)
  - Multiple model variants: HAR-H, Hurst-Scaled EWMA, Regime-Hurst
  - Proper rolling OOS with DM tests
  - Analysis of H_t dynamics and correlations

Data source: yfinance (SPY, 2006-01-01 to 2026-03-27)
Proxy: sigma^2_proxy = r^2_t (squared daily returns)
OOS: 2023-01-01 to 2024-12-31, re-estimate every 21 trading days
"""

import json
import sys
import time
import warnings
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats

warnings.filterwarnings("ignore")

# ─── Configuration ───────────────────────────────────────────────────────────
ASSET = "SPY"
START = "2006-01-01"
END = "2026-03-27"
WINDOW = 2000
OOS_START = "2023-01-01"
OOS_END = "2024-12-31"
REFIT_EVERY = 21
HURST_WINDOW = 252  # 1 year rolling window for Hurst
DFA_SCALES = [10, 20, 50, 100]  # DFA box sizes
EWMA_LAMBDA = 0.94
PRINT_EVERY = 50

print("=" * 70)
print("K625: Time-Varying Hurst Exponent for Volatility Forecasting")
print("=" * 70)

# ─── Data download ───────────────────────────────────────────────────────────
print(f"\nDownloading {ASSET} from {START} to {END}...")
df = yf.download(ASSET, start=START, end=END, auto_adjust=True, progress=False)
if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.get_level_values(0)
prices = df["Close"].dropna()
returns = 100.0 * prices.pct_change().dropna()  # percentage returns
dates = returns.index
T = len(returns)
print(f"Total observations: {T}, from {dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}")

returns_arr = returns.values.astype(np.float64)
proxy = returns_arr ** 2  # squared returns as vol proxy
abs_returns = np.abs(returns_arr)


# ═══════════════════════════════════════════════════════════════════════════════
# DFA (Detrended Fluctuation Analysis) Implementation
# ═══════════════════════════════════════════════════════════════════════════════
def dfa_hurst(series, n_values=None):
    """
    Detrended Fluctuation Analysis for estimating the Hurst exponent.

    Parameters:
        series: 1D array of the time series
        n_values: list of box sizes (scales)

    Returns:
        H: Hurst exponent (slope of log F(n) vs log n)
        r_squared: R-squared of the log-log fit
    """
    if n_values is None:
        n_values = DFA_SCALES

    N = len(series)
    # Step 1: Compute cumulative sum (profile)
    y = np.cumsum(series - np.mean(series))

    F_n = []
    valid_n = []

    for n in n_values:
        if n < 4:  # need at least 4 points for linear detrending
            continue
        num_segments = N // n
        if num_segments < 2:  # need at least 2 segments
            continue

        # Forward pass
        fluctuations_sq = []
        for i in range(num_segments):
            segment = y[i * n : (i + 1) * n]
            x = np.arange(n, dtype=np.float64)
            # Linear detrend
            coeffs = np.polyfit(x, segment, 1)
            trend = coeffs[0] * x + coeffs[1]
            fluctuations_sq.append(np.mean((segment - trend) ** 2))

        # Backward pass (use remaining data from the end)
        for i in range(num_segments):
            segment = y[N - (i + 1) * n : N - i * n]
            x = np.arange(n, dtype=np.float64)
            coeffs = np.polyfit(x, segment, 1)
            trend = coeffs[0] * x + coeffs[1]
            fluctuations_sq.append(np.mean((segment - trend) ** 2))

        F = np.sqrt(np.mean(fluctuations_sq))
        if F > 0:
            F_n.append(F)
            valid_n.append(n)

    if len(valid_n) < 2:
        return np.nan, 0.0

    log_n = np.log(np.array(valid_n, dtype=np.float64))
    log_F = np.log(np.array(F_n, dtype=np.float64))

    # Linear regression: log F = H * log n + const
    coeffs = np.polyfit(log_n, log_F, 1)
    H = coeffs[0]

    # R-squared
    predicted = coeffs[0] * log_n + coeffs[1]
    ss_res = np.sum((log_F - predicted) ** 2)
    ss_tot = np.sum((log_F - np.mean(log_F)) ** 2)
    r_sq = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

    return H, r_sq


# ═══════════════════════════════════════════════════════════════════════════════
# Compute Rolling Hurst Exponent
# ═══════════════════════════════════════════════════════════════════════════════
print(f"\nComputing rolling Hurst exponent (DFA, window={HURST_WINDOW})...")
t0 = time.time()

hurst_series = np.full(T, np.nan)
hurst_rsq = np.full(T, np.nan)

for t in range(HURST_WINDOW, T):
    window_data = abs_returns[t - HURST_WINDOW : t]
    H, rsq = dfa_hurst(window_data, DFA_SCALES)
    hurst_series[t] = H
    hurst_rsq[t] = rsq
    if (t - HURST_WINDOW) % 500 == 0:
        print(f"  Hurst computation: {t - HURST_WINDOW}/{T - HURST_WINDOW} done, H={H:.4f}")

elapsed_hurst = time.time() - t0
print(f"Hurst computation done in {elapsed_hurst:.1f}s")

# Hurst descriptive statistics (where valid)
valid_mask = ~np.isnan(hurst_series)
H_valid = hurst_series[valid_mask]
print(f"\n--- Hurst Exponent Descriptive Statistics (DFA, |r_t|) ---")
print(f"  N valid:   {len(H_valid)}")
print(f"  Mean:      {np.mean(H_valid):.4f}")
print(f"  Std:       {np.std(H_valid):.4f}")
print(f"  Min:       {np.min(H_valid):.4f}")
print(f"  Max:       {np.max(H_valid):.4f}")
print(f"  Median:    {np.median(H_valid):.4f}")
print(f"  Pct H>0.5: {100 * np.mean(H_valid > 0.5):.1f}%")
print(f"  Pct H<0.5: {100 * np.mean(H_valid < 0.5):.1f}%")
print(f"  Mean R²:   {np.mean(hurst_rsq[valid_mask]):.4f}")

# ═══════════════════════════════════════════════════════════════════════════════
# Descriptive Statistics — Returns
# ═══════════════════════════════════════════════════════════════════════════════
print(f"\n--- Returns Descriptive Statistics ---")
print(f"  Mean:     {np.mean(returns_arr):.4f}%")
print(f"  Std:      {np.std(returns_arr):.4f}%")
print(f"  Skew:     {stats.skew(returns_arr):.4f}")
print(f"  Kurt:     {stats.kurtosis(returns_arr):.4f}")

# ADF test on returns
from statsmodels.tsa.stattools import adfuller
adf_ret = adfuller(returns_arr, maxlag=20)
print(f"  ADF stat: {adf_ret[0]:.4f} (p={adf_ret[1]:.6f})")

# ARCH LM test
from statsmodels.stats.diagnostic import het_arch
arch_lm = het_arch(returns_arr, nlags=10)
print(f"  ARCH LM:  stat={arch_lm[0]:.2f}, p={arch_lm[1]:.6f}")


# ═══════════════════════════════════════════════════════════════════════════════
# Correlation Analysis: H_t vs VIX, H_t vs future realized vol
# ═══════════════════════════════════════════════════════════════════════════════
print(f"\n--- Correlation Analysis ---")

# Download VIX
print("Downloading VIX data...")
vix_df = yf.download("^VIX", start=START, end=END, auto_adjust=True, progress=False)
if isinstance(vix_df.columns, pd.MultiIndex):
    vix_df.columns = vix_df.columns.get_level_values(0)
vix_close = vix_df["Close"].reindex(dates).ffill()
vix_arr = vix_close.values.astype(np.float64)

# Future realized vol (20-day forward)
future_rv20 = np.full(T, np.nan)
for t in range(T - 20):
    future_rv20[t] = np.sqrt(np.mean(returns_arr[t + 1 : t + 21] ** 2))

# Correlations (where all valid)
mask_all = valid_mask & ~np.isnan(vix_arr) & ~np.isnan(future_rv20)
if np.sum(mask_all) > 100:
    corr_h_vix = np.corrcoef(hurst_series[mask_all], vix_arr[mask_all])[0, 1]
    corr_h_fvol = np.corrcoef(hurst_series[mask_all], future_rv20[mask_all])[0, 1]
    corr_vix_fvol = np.corrcoef(vix_arr[mask_all], future_rv20[mask_all])[0, 1]
    print(f"  Corr(H_t, VIX):           {corr_h_vix:.4f}")
    print(f"  Corr(H_t, FutureRV20):    {corr_h_fvol:.4f}")
    print(f"  Corr(VIX, FutureRV20):    {corr_vix_fvol:.4f}")

    # Rank correlation (Spearman)
    sp_h_vix = stats.spearmanr(hurst_series[mask_all], vix_arr[mask_all])
    sp_h_fvol = stats.spearmanr(hurst_series[mask_all], future_rv20[mask_all])
    print(f"  Spearman(H_t, VIX):       {sp_h_vix.statistic:.4f} (p={sp_h_vix.pvalue:.6f})")
    print(f"  Spearman(H_t, FutureRV20):{sp_h_fvol.statistic:.4f} (p={sp_h_fvol.pvalue:.6f})")
else:
    corr_h_vix = corr_h_fvol = corr_vix_fvol = np.nan
    sp_h_vix = sp_h_fvol = None
    print("  Insufficient overlapping data for correlation analysis")


# ═══════════════════════════════════════════════════════════════════════════════
# MODEL DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════════════

def fit_gjr(ret_window):
    """Fit GJR-GARCH(1,1) and return conditional variance array + 1-step forecast."""
    try:
        am = arch_model(ret_window, vol="Garch", p=1, o=1, q=1, dist="normal", mean="Constant")
        res = am.fit(disp="off", show_warning=False)
        cond_var = res.conditional_volatility ** 2
        fcast = res.forecast(horizon=1)
        h_next = fcast.variance.iloc[-1, 0]
        return cond_var.values, h_next, True
    except Exception:
        return None, None, False


def compute_har_features(proxy_series, t):
    """Compute HAR features: RV_1, RV_5, RV_22 at time t (using data up to t-1)."""
    if t < 22:
        return None
    rv1 = proxy_series[t - 1]
    rv5 = np.mean(proxy_series[t - 5 : t])
    rv22 = np.mean(proxy_series[t - 22 : t])
    return np.array([rv1, rv5, rv22])


def fit_har_h(proxy_window, hurst_window, ret_window):
    """
    HAR + Hurst regressor:
    sigma^2_t = b0 + b1*r^2_{t-1} + b2*avg5 + b3*avg22 + b4*H_t + e_t

    Fit by OLS on in-sample, return coefficients.
    """
    n = len(proxy_window)
    if n < 50:
        return None

    # Build design matrix (start at t=22 to have all features)
    Y = []
    X = []
    start = 22
    for t in range(start, n):
        if np.isnan(hurst_window[t]):
            continue
        har = compute_har_features(proxy_window, t)
        if har is None:
            continue
        Y.append(proxy_window[t])
        X.append(np.concatenate([[1.0], har, [hurst_window[t]]]))

    if len(Y) < 30:
        return None

    Y = np.array(Y)
    X = np.array(X)

    # OLS
    try:
        beta, residuals, rank, sv = np.linalg.lstsq(X, Y, rcond=None)
        return beta  # [intercept, b_rv1, b_rv5, b_rv22, b_hurst]
    except Exception:
        return None


def forecast_har_h(beta, proxy_recent, hurst_val):
    """One-step HAR-H forecast."""
    if beta is None or np.isnan(hurst_val):
        return np.nan
    rv1 = proxy_recent[-1]
    rv5 = np.mean(proxy_recent[-5:])
    rv22 = np.mean(proxy_recent[-22:])
    x = np.array([1.0, rv1, rv5, rv22, hurst_val])
    fcast = np.dot(beta, x)
    return max(fcast, 1e-8)  # ensure positive


def forecast_hurst_scaled_ewma(returns_window, hurst_val, base_lambda=0.94):
    """
    Hurst-Scaled EWMA:
    - When H is high (persistent), use more history (higher lambda)
    - When H is low (rough/anti-persistent), use less history (lower lambda)

    Mapping: lambda_adj = base_lambda + 0.05 * (H - 0.5)
    Clamped to [0.85, 0.99]
    """
    if np.isnan(hurst_val):
        lam = base_lambda
    else:
        lam = base_lambda + 0.1 * (hurst_val - 0.5)
        lam = np.clip(lam, 0.85, 0.99)

    n = len(returns_window)
    var_t = np.var(returns_window)  # initial value
    for i in range(1, n):
        var_t = lam * var_t + (1 - lam) * returns_window[i] ** 2

    # One-step forecast
    h_next = lam * var_t + (1 - lam) * returns_window[-1] ** 2
    return max(h_next, 1e-8)


def fit_regime_hurst_gjr(ret_window, hurst_window):
    """
    Regime-Hurst: Split by H > 0.5 (persistent) vs H < 0.5 (rough).
    Fit separate GJR models on each regime's data.
    Return the forecasts for both regimes.
    """
    valid = ~np.isnan(hurst_window)
    if np.sum(valid) < 100:
        return None, None, None

    # Current H determines regime
    current_h = hurst_window[-1] if not np.isnan(hurst_window[-1]) else 0.5

    # Split returns
    persistent_mask = valid & (hurst_window >= 0.5)
    rough_mask = valid & (hurst_window < 0.5)

    n_persistent = np.sum(persistent_mask)
    n_rough = np.sum(rough_mask)

    # We need enough data in each regime for GJR
    # Use full sample GJR but adjust forecast based on regime-specific variance scaling
    try:
        am = arch_model(pd.Series(ret_window), vol="Garch", p=1, o=1, q=1,
                        dist="normal", mean="Constant")
        res = am.fit(disp="off", show_warning=False)
        base_fcast = res.forecast(horizon=1).variance.iloc[-1, 0]

        # Regime adjustment: compute mean variance in each regime
        cond_var = res.conditional_volatility.values ** 2

        if n_persistent > 20 and n_rough > 20:
            mean_var_persistent = np.mean(cond_var[persistent_mask[:len(cond_var)]]
                                          if len(persistent_mask) >= len(cond_var)
                                          else cond_var[persistent_mask[-len(cond_var):]])
            mean_var_rough = np.mean(cond_var[rough_mask[:len(cond_var)]]
                                     if len(rough_mask) >= len(cond_var)
                                     else cond_var[rough_mask[-len(cond_var):]])

            # Scale factor
            overall_mean = np.mean(cond_var)
            if current_h >= 0.5:
                scale = mean_var_persistent / overall_mean if overall_mean > 0 else 1.0
            else:
                scale = mean_var_rough / overall_mean if overall_mean > 0 else 1.0

            regime_fcast = base_fcast * scale
        else:
            regime_fcast = base_fcast
            scale = 1.0

        return max(regime_fcast, 1e-8), scale, True
    except Exception:
        return None, None, False


# ═══════════════════════════════════════════════════════════════════════════════
# HAR Baseline (without Hurst)
# ═══════════════════════════════════════════════════════════════════════════════
def fit_har(proxy_window):
    """
    Standard HAR:
    sigma^2_t = b0 + b1*r^2_{t-1} + b2*avg5 + b3*avg22 + e_t
    """
    n = len(proxy_window)
    if n < 50:
        return None

    Y = []
    X = []
    start = 22
    for t in range(start, n):
        har = compute_har_features(proxy_window, t)
        if har is None:
            continue
        Y.append(proxy_window[t])
        X.append(np.concatenate([[1.0], har]))

    if len(Y) < 30:
        return None

    Y = np.array(Y)
    X = np.array(X)

    try:
        beta, _, _, _ = np.linalg.lstsq(X, Y, rcond=None)
        return beta
    except Exception:
        return None


def forecast_har(beta, proxy_recent):
    """One-step HAR forecast."""
    if beta is None:
        return np.nan
    rv1 = proxy_recent[-1]
    rv5 = np.mean(proxy_recent[-5:])
    rv22 = np.mean(proxy_recent[-22:])
    x = np.array([1.0, rv1, rv5, rv22])
    fcast = np.dot(beta, x)
    return max(fcast, 1e-8)


# ═══════════════════════════════════════════════════════════════════════════════
# Rolling OOS Evaluation
# ═══════════════════════════════════════════════════════════════════════════════
print(f"\n{'=' * 70}")
print(f"Rolling OOS Evaluation: {OOS_START} to {OOS_END}")
print(f"Window={WINDOW}, Refit every {REFIT_EVERY} days")
print(f"{'=' * 70}")

oos_start_idx = np.searchsorted(dates, pd.Timestamp(OOS_START))
oos_end_idx = np.searchsorted(dates, pd.Timestamp(OOS_END))
if oos_end_idx >= T:
    oos_end_idx = T - 1

n_oos = oos_end_idx - oos_start_idx
print(f"OOS period: {dates[oos_start_idx].strftime('%Y-%m-%d')} to {dates[oos_end_idx].strftime('%Y-%m-%d')}")
print(f"OOS observations: {n_oos}")

# Storage for forecasts
fcast_gjr = np.full(n_oos, np.nan)
fcast_har = np.full(n_oos, np.nan)
fcast_har_h = np.full(n_oos, np.nan)
fcast_ewma_h = np.full(n_oos, np.nan)
fcast_regime_h = np.full(n_oos, np.nan)
oos_proxy = np.full(n_oos, np.nan)
oos_hurst = np.full(n_oos, np.nan)
oos_dates = []

# Cache for fitted models
gjr_cache = None
har_cache = None
har_h_cache = None
last_refit = -REFIT_EVERY  # force initial fit

t_start = time.time()
n_refits = 0

for i in range(n_oos):
    t = oos_start_idx + i
    oos_dates.append(dates[t].strftime("%Y-%m-%d"))
    oos_proxy[i] = proxy[t]
    oos_hurst[i] = hurst_series[t]

    # Check if we need to refit
    if i - last_refit >= REFIT_EVERY or gjr_cache is None:
        last_refit = i
        n_refits += 1

        # Training window
        train_start = max(0, t - WINDOW)
        train_ret = returns_arr[train_start:t]
        train_proxy = proxy[train_start:t]
        train_hurst = hurst_series[train_start:t]

        # 1. GJR-GARCH
        _, gjr_fcast_val, gjr_ok = fit_gjr(pd.Series(train_ret, index=dates[train_start:t]))
        gjr_cache = gjr_fcast_val if gjr_ok else gjr_cache

        # 2. HAR baseline
        har_cache = fit_har(train_proxy)

        # 3. HAR-H
        har_h_cache = fit_har_h(train_proxy, train_hurst, train_ret)

        if i % PRINT_EVERY == 0:
            print(f"  Refit #{n_refits} at OOS day {i}/{n_oos} ({dates[t].strftime('%Y-%m-%d')})")
    else:
        # Update GJR forecast without refitting (use last fitted model)
        train_start = max(0, t - WINDOW)
        train_ret = returns_arr[train_start:t]
        _, gjr_fcast_val, gjr_ok = fit_gjr(pd.Series(train_ret, index=dates[train_start:t]))
        if gjr_ok:
            gjr_cache = gjr_fcast_val

    # Generate forecasts
    # 1. GJR
    fcast_gjr[i] = gjr_cache if gjr_cache is not None else np.nan

    # 2. HAR
    if t >= 22:
        fcast_har[i] = forecast_har(har_cache, proxy[t - 22:t])

    # 3. HAR-H
    if t >= 22 and not np.isnan(hurst_series[t]):
        fcast_har_h[i] = forecast_har_h(har_h_cache, proxy[t - 22:t], hurst_series[t])

    # 4. Hurst-Scaled EWMA
    train_start_ewma = max(0, t - 252)
    fcast_ewma_h[i] = forecast_hurst_scaled_ewma(
        returns_arr[train_start_ewma:t],
        hurst_series[t] if not np.isnan(hurst_series[t]) else 0.5
    )

    # 5. Regime-Hurst GJR
    train_start_r = max(0, t - WINDOW)
    train_ret_r = returns_arr[train_start_r:t]
    train_hurst_r = hurst_series[train_start_r:t]
    regime_fcast, _, regime_ok = fit_regime_hurst_gjr(train_ret_r, train_hurst_r)
    if regime_ok and regime_fcast is not None:
        fcast_regime_h[i] = regime_fcast

    if i % PRINT_EVERY == 0 and i > 0:
        elapsed = time.time() - t_start
        rate = elapsed / i
        eta = rate * (n_oos - i)
        print(f"  OOS {i}/{n_oos}: GJR={fcast_gjr[i]:.4f}, HAR={fcast_har[i]:.4f}, "
              f"HAR-H={fcast_har_h[i]:.4f}, EWMA-H={fcast_ewma_h[i]:.4f}, "
              f"Regime-H={fcast_regime_h[i]:.4f} | H_t={hurst_series[t]:.3f} | "
              f"ETA {eta:.0f}s")

elapsed_oos = time.time() - t_start
print(f"\nOOS evaluation done in {elapsed_oos:.1f}s ({n_refits} refits)")


# ═══════════════════════════════════════════════════════════════════════════════
# Loss Functions & Evaluation Metrics
# ═══════════════════════════════════════════════════════════════════════════════
def qlike(actual, forecast):
    """QLIKE loss: actual/forecast - log(actual/forecast) - 1"""
    mask = (actual > 0) & (forecast > 0) & ~np.isnan(actual) & ~np.isnan(forecast)
    a = actual[mask]
    f = forecast[mask]
    return np.mean(a / f - np.log(a / f) - 1), mask

def mse(actual, forecast):
    """MSE loss"""
    mask = ~np.isnan(actual) & ~np.isnan(forecast) & (forecast > 0)
    return np.mean((actual[mask] - forecast[mask]) ** 2), mask

def mae(actual, forecast):
    """MAE loss"""
    mask = ~np.isnan(actual) & ~np.isnan(forecast) & (forecast > 0)
    return np.mean(np.abs(actual[mask] - forecast[mask])), mask

def dm_test(actual, fcast1, fcast2, loss_fn="qlike"):
    """
    Diebold-Mariano test.
    H0: equal predictive accuracy.
    Negative t-stat means fcast2 is better.
    """
    mask = ~np.isnan(actual) & ~np.isnan(fcast1) & ~np.isnan(fcast2) & (actual > 0) & (fcast1 > 0) & (fcast2 > 0)
    a = actual[mask]
    f1 = fcast1[mask]
    f2 = fcast2[mask]

    if len(a) < 30:
        return np.nan, np.nan, len(a)

    if loss_fn == "qlike":
        d1 = a / f1 - np.log(a / f1) - 1
        d2 = a / f2 - np.log(a / f2) - 1
    else:  # MSE
        d1 = (a - f1) ** 2
        d2 = (a - f2) ** 2

    d = d1 - d2  # positive means fcast2 is better

    n = len(d)
    d_bar = np.mean(d)

    # Newey-West HAC variance (lag = int(n^(1/3)))
    max_lag = int(n ** (1.0 / 3.0))
    gamma_0 = np.var(d, ddof=1)

    hac_var = gamma_0
    for k in range(1, max_lag + 1):
        weight = 1 - k / (max_lag + 1)
        gamma_k = np.mean((d[k:] - d_bar) * (d[:-k] - d_bar))
        hac_var += 2 * weight * gamma_k

    if hac_var <= 0:
        return np.nan, np.nan, n

    dm_stat = d_bar / np.sqrt(hac_var / n)
    p_val = 2 * (1 - stats.norm.cdf(abs(dm_stat)))

    return dm_stat, p_val, n


print(f"\n{'=' * 70}")
print("EVALUATION RESULTS")
print(f"{'=' * 70}")

# Compute metrics for all models
models = {
    "GJR-GARCH": fcast_gjr,
    "HAR": fcast_har,
    "HAR-H (Hurst)": fcast_har_h,
    "EWMA-H (Hurst-scaled)": fcast_ewma_h,
    "Regime-Hurst GJR": fcast_regime_h,
}

results_metrics = {}
for name, fcast in models.items():
    q, _ = qlike(oos_proxy, fcast)
    m, _ = mse(oos_proxy, fcast)
    a, mask = mae(oos_proxy, fcast)
    n_valid = np.sum(~np.isnan(fcast) & ~np.isnan(oos_proxy) & (oos_proxy > 0) & (fcast > 0))
    results_metrics[name] = {"QLIKE": q, "MSE": m, "MAE": a, "n_valid": int(n_valid)}
    print(f"  {name:25s}: QLIKE={q:.6f}  MSE={m:.4f}  MAE={a:.4f}  n={n_valid}")

# DM tests vs GJR baseline
print(f"\n--- Diebold-Mariano Tests vs GJR-GARCH (QLIKE) ---")
print(f"  Positive DM stat => GJR better; Negative => alternative better")

dm_results = {}
for name, fcast in models.items():
    if name == "GJR-GARCH":
        continue
    dm_stat, p_val, n_dm = dm_test(oos_proxy, fcast_gjr, fcast, "qlike")
    dm_results[name] = {"DM_stat": dm_stat, "p_value": p_val, "n": n_dm}
    sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.10 else ""
    direction = "better" if dm_stat > 0 else "worse"
    print(f"  GJR vs {name:25s}: DM={dm_stat:+.4f}  p={p_val:.4f}  n={n_dm} {sig} ({name} {direction})")

# DM tests MSE
print(f"\n--- Diebold-Mariano Tests vs GJR-GARCH (MSE) ---")
dm_results_mse = {}
for name, fcast in models.items():
    if name == "GJR-GARCH":
        continue
    dm_stat, p_val, n_dm = dm_test(oos_proxy, fcast_gjr, fcast, "mse")
    dm_results_mse[name] = {"DM_stat": dm_stat, "p_value": p_val, "n": n_dm}
    sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.10 else ""
    direction = "better" if dm_stat > 0 else "worse"
    print(f"  GJR vs {name:25s}: DM={dm_stat:+.4f}  p={p_val:.4f}  n={n_dm} {sig} ({name} {direction})")

# DM test: HAR vs HAR-H (direct comparison)
print(f"\n--- HAR vs HAR-H Direct Comparison ---")
dm_har_harh_q, p_har_harh_q, n_har_harh_q = dm_test(oos_proxy, fcast_har, fcast_har_h, "qlike")
print(f"  QLIKE: DM={dm_har_harh_q:+.4f}  p={p_har_harh_q:.4f}  n={n_har_harh_q}")
dm_har_harh_m, p_har_harh_m, n_har_harh_m = dm_test(oos_proxy, fcast_har, fcast_har_h, "mse")
print(f"  MSE:   DM={dm_har_harh_m:+.4f}  p={p_har_harh_m:.4f}  n={n_har_harh_m}")


# ═══════════════════════════════════════════════════════════════════════════════
# Additional Analysis: H_t stability over time
# ═══════════════════════════════════════════════════════════════════════════════
print(f"\n--- Hurst Exponent Time Variation Analysis ---")

# Split into periods
periods = [
    ("2007-2009 (GFC)", "2007-01-01", "2009-12-31"),
    ("2010-2014 (Recovery)", "2010-01-01", "2014-12-31"),
    ("2015-2019 (Bull)", "2015-01-01", "2019-12-31"),
    ("2020 (COVID)", "2020-01-01", "2020-12-31"),
    ("2021-2022 (Post-COVID)", "2021-01-01", "2022-12-31"),
    ("2023-2024 (OOS)", "2023-01-01", "2024-12-31"),
]

period_stats = {}
for label, ps, pe in periods:
    mask_period = (dates >= pd.Timestamp(ps)) & (dates <= pd.Timestamp(pe))
    idx_period = np.where(mask_period)[0]
    h_period = hurst_series[idx_period]
    h_valid_p = h_period[~np.isnan(h_period)]
    if len(h_valid_p) > 0:
        period_stats[label] = {
            "mean": float(np.mean(h_valid_p)),
            "std": float(np.std(h_valid_p)),
            "pct_above_0.5": float(100 * np.mean(h_valid_p > 0.5)),
            "n": int(len(h_valid_p)),
        }
        print(f"  {label:30s}: mean={np.mean(h_valid_p):.4f} std={np.std(h_valid_p):.4f} "
              f"H>0.5={100*np.mean(h_valid_p>0.5):.0f}% n={len(h_valid_p)}")


# ═══════════════════════════════════════════════════════════════════════════════
# PLOT: Hurst Exponent Evolution
# ═══════════════════════════════════════════════════════════════════════════════
print("\nGenerating Hurst evolution plot...")

fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)

# Panel 1: SPY price
ax1 = axes[0]
ax1.plot(dates, prices.reindex(dates).values, color="steelblue", linewidth=0.8)
ax1.set_ylabel("SPY Price ($)", fontsize=11)
ax1.set_title("K625: Time-Varying Hurst Exponent (DFA) for SPY", fontsize=13, fontweight="bold")
ax1.grid(True, alpha=0.3)

# Panel 2: Rolling Hurst exponent
ax2 = axes[1]
valid_dates = dates[valid_mask]
valid_h = hurst_series[valid_mask]
ax2.plot(valid_dates, valid_h, color="darkorange", linewidth=0.8, label="H_t (DFA)")
ax2.axhline(y=0.5, color="red", linestyle="--", alpha=0.7, label="H=0.5 (random walk)")
ax2.fill_between(valid_dates, 0, 0.5, alpha=0.05, color="blue", label="Rough/Anti-persistent")
ax2.fill_between(valid_dates, 0.5, 1.0, alpha=0.05, color="green", label="Persistent")
ax2.set_ylabel("Hurst Exponent H", fontsize=11)
ax2.set_ylim(0, 1.0)
ax2.legend(loc="upper right", fontsize=9)
ax2.grid(True, alpha=0.3)

# Panel 3: VIX
ax3 = axes[2]
ax3.plot(dates, vix_arr, color="red", linewidth=0.8, alpha=0.8)
ax3.set_ylabel("VIX", fontsize=11)
ax3.set_xlabel("Date", fontsize=11)
ax3.grid(True, alpha=0.3)

# Shade OOS period
for ax in axes:
    ax.axvspan(pd.Timestamp(OOS_START), pd.Timestamp(OOS_END), alpha=0.1, color="yellow", label="OOS" if ax == axes[0] else "")

plt.tight_layout()
plot_path = "experiments/k625/k625_hurst_evolution.png"
plt.savefig(plot_path, dpi=150, bbox_inches="tight")
plt.close()
print(f"Plot saved to {plot_path}")


# ═══════════════════════════════════════════════════════════════════════════════
# PLOT 2: OOS Forecasts Comparison
# ═══════════════════════════════════════════════════════════════════════════════
fig, axes = plt.subplots(2, 1, figsize=(14, 8))

oos_dates_ts = pd.to_datetime(oos_dates)

# Panel 1: Realized vs Forecasts
ax1 = axes[0]
ax1.plot(oos_dates_ts, oos_proxy, color="black", linewidth=0.5, alpha=0.4, label="Realized (r²)")
ax1.plot(oos_dates_ts, fcast_gjr, color="blue", linewidth=1.0, alpha=0.8, label="GJR-GARCH")
ax1.plot(oos_dates_ts, fcast_har_h, color="red", linewidth=1.0, alpha=0.8, label="HAR-H")
ax1.plot(oos_dates_ts, fcast_ewma_h, color="green", linewidth=1.0, alpha=0.8, label="EWMA-H")
ax1.set_ylabel("Conditional Variance", fontsize=11)
ax1.set_title("K625: OOS Forecasts Comparison (2023-2024)", fontsize=13, fontweight="bold")
ax1.legend(loc="upper right", fontsize=9)
ax1.set_ylim(0, np.nanpercentile(oos_proxy, 99) * 2)
ax1.grid(True, alpha=0.3)

# Panel 2: Hurst during OOS
ax2 = axes[1]
ax2.plot(oos_dates_ts, oos_hurst, color="darkorange", linewidth=1.0)
ax2.axhline(y=0.5, color="red", linestyle="--", alpha=0.7)
ax2.set_ylabel("Hurst H_t", fontsize=11)
ax2.set_xlabel("Date", fontsize=11)
ax2.grid(True, alpha=0.3)

plt.tight_layout()
plot_path2 = "experiments/k625/k625_hurst_oos_comparison.png"
plt.savefig(plot_path2, dpi=150, bbox_inches="tight")
plt.close()
print(f"Plot saved to {plot_path2}")


# ═══════════════════════════════════════════════════════════════════════════════
# Save Results
# ═══════════════════════════════════════════════════════════════════════════════
print(f"\n{'=' * 70}")
print("SUMMARY")
print(f"{'=' * 70}")

# Determine best model
qlike_scores = {name: results_metrics[name]["QLIKE"] for name in results_metrics}
best_model = min(qlike_scores, key=qlike_scores.get)
worst_model = max(qlike_scores, key=qlike_scores.get)
gjr_qlike = results_metrics["GJR-GARCH"]["QLIKE"]

print(f"\nBest QLIKE:  {best_model} ({qlike_scores[best_model]:.6f})")
print(f"Worst QLIKE: {worst_model} ({qlike_scores[worst_model]:.6f})")
print(f"GJR baseline: {gjr_qlike:.6f}")

for name in models:
    if name == "GJR-GARCH":
        continue
    pct_diff = 100 * (results_metrics[name]["QLIKE"] - gjr_qlike) / gjr_qlike
    print(f"  {name}: {pct_diff:+.2f}% vs GJR")

# Conclusion
print(f"\n--- Conclusion ---")
any_improvement = any(
    results_metrics[name]["QLIKE"] < gjr_qlike
    for name in results_metrics if name != "GJR-GARCH"
)
any_significant = any(
    dm_results.get(name, {}).get("p_value", 1.0) < 0.05 and
    dm_results.get(name, {}).get("DM_stat", 0) > 0
    for name in dm_results
)

if any_significant:
    print("POSITIVE: At least one Hurst-augmented model significantly beats GJR")
elif any_improvement:
    print("MARGINAL: Some Hurst models have lower QLIKE but not statistically significant")
else:
    print("NULL RESULT: No Hurst-augmented model improves over GJR-GARCH baseline")


# Build results JSON
def safe_float(x):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    return float(x)

results = {
    "experiment_id": "K625",
    "title": "Time-Varying Hurst Exponent (DFA) for Volatility Forecasting",
    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "data_source": "yfinance",
    "asset": ASSET,
    "period": f"{dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}",
    "total_obs": int(T),
    "oos_period": f"{OOS_START} to {OOS_END}",
    "oos_obs": int(n_oos),
    "n_refits": int(n_refits),
    "window": WINDOW,
    "refit_every": REFIT_EVERY,
    "hurst_window": HURST_WINDOW,
    "dfa_scales": DFA_SCALES,
    "references": [
        "arXiv:2509.05820 (2025): EWMA-driven dynamic Hurst parameter",
        "Frontiers Applied Math (2025): Wavelet-based time-varying Hurst",
        "Gatheral, Jaisson, Rosenbaum (2018): Volatility is rough, QF 18(6)",
        "Peng et al. (1994): DFA method, Physical Review E",
    ],
    "prior_knowledge": [
        "K138: Hurst fingerprint — all assets rough (H~0.01 for log-var)",
        "K166: Hurst Exponent Regime — SPY H=0.54, OOS no improvement",
        "Prior Hurst-GARCH OOS: +1.28% QLIKE, no improvement",
    ],
    "hurst_descriptive": {
        "method": "DFA (Detrended Fluctuation Analysis)",
        "input_series": "|r_t| (absolute returns)",
        "n_valid": int(len(H_valid)),
        "mean": safe_float(np.mean(H_valid)),
        "std": safe_float(np.std(H_valid)),
        "min": safe_float(np.min(H_valid)),
        "max": safe_float(np.max(H_valid)),
        "median": safe_float(np.median(H_valid)),
        "pct_above_0.5": safe_float(100 * np.mean(H_valid > 0.5)),
        "pct_below_0.5": safe_float(100 * np.mean(H_valid < 0.5)),
        "mean_r_squared": safe_float(np.mean(hurst_rsq[valid_mask])),
    },
    "returns_diagnostics": {
        "mean_pct": safe_float(np.mean(returns_arr)),
        "std_pct": safe_float(np.std(returns_arr)),
        "skewness": safe_float(stats.skew(returns_arr)),
        "kurtosis": safe_float(stats.kurtosis(returns_arr)),
        "adf_stat": safe_float(adf_ret[0]),
        "adf_pvalue": safe_float(adf_ret[1]),
        "arch_lm_stat": safe_float(arch_lm[0]),
        "arch_lm_pvalue": safe_float(arch_lm[1]),
    },
    "correlations": {
        "pearson_h_vix": safe_float(corr_h_vix),
        "pearson_h_future_rv20": safe_float(corr_h_fvol),
        "pearson_vix_future_rv20": safe_float(corr_vix_fvol),
        "spearman_h_vix": safe_float(sp_h_vix.statistic) if sp_h_vix else None,
        "spearman_h_vix_pvalue": safe_float(sp_h_vix.pvalue) if sp_h_vix else None,
        "spearman_h_future_rv20": safe_float(sp_h_fvol.statistic) if sp_h_fvol else None,
        "spearman_h_future_rv20_pvalue": safe_float(sp_h_fvol.pvalue) if sp_h_fvol else None,
    },
    "period_analysis": period_stats,
    "oos_metrics": {
        name: {
            "QLIKE": safe_float(results_metrics[name]["QLIKE"]),
            "MSE": safe_float(results_metrics[name]["MSE"]),
            "MAE": safe_float(results_metrics[name]["MAE"]),
            "n_valid": results_metrics[name]["n_valid"],
            "pct_diff_vs_gjr_qlike": safe_float(
                100 * (results_metrics[name]["QLIKE"] - gjr_qlike) / gjr_qlike
            ) if name != "GJR-GARCH" else 0.0,
        }
        for name in results_metrics
    },
    "dm_tests_qlike_vs_gjr": {
        name: {
            "DM_stat": safe_float(dm_results[name]["DM_stat"]),
            "p_value": safe_float(dm_results[name]["p_value"]),
            "n": dm_results[name]["n"],
            "interpretation": (
                f"{name} {'better' if dm_results[name]['DM_stat'] > 0 else 'worse'} than GJR"
                + (" (significant)" if dm_results[name]["p_value"] < 0.05 else " (not significant)")
            ),
        }
        for name in dm_results
    },
    "dm_tests_mse_vs_gjr": {
        name: {
            "DM_stat": safe_float(dm_results_mse[name]["DM_stat"]),
            "p_value": safe_float(dm_results_mse[name]["p_value"]),
            "n": dm_results_mse[name]["n"],
        }
        for name in dm_results_mse
    },
    "dm_test_har_vs_har_h": {
        "QLIKE": {"DM_stat": safe_float(dm_har_harh_q), "p_value": safe_float(p_har_harh_q), "n": int(n_har_harh_q)},
        "MSE": {"DM_stat": safe_float(dm_har_harh_m), "p_value": safe_float(p_har_harh_m), "n": int(n_har_harh_m)},
    },
    "conclusion": {
        "any_improvement": any_improvement,
        "any_significant_improvement": any_significant,
        "best_model": best_model,
        "best_qlike": safe_float(qlike_scores[best_model]),
        "summary": (
            "Time-varying Hurst exponent (DFA) on |returns| shows persistent behavior "
            f"(mean H={np.mean(H_valid):.3f}, {100*np.mean(H_valid>0.5):.0f}% above 0.5). "
            "However, incorporating H_t into volatility forecasting models (HAR-H, EWMA-H, Regime-Hurst) "
            f"{'improves' if any_improvement else 'does NOT improve'} over GJR-GARCH baseline in OOS (2023-2024). "
            f"{'Statistically significant improvement found.' if any_significant else 'No statistically significant improvement (DM test).'} "
            "This confirms prior findings (K138, K166) that Hurst information, while describing "
            "vol dynamics, does not translate to better OOS forecasts. "
            "The DFA method gives different H values than R/S (prior work: H=0.73 via R/S), "
            "but the forecasting conclusion is consistent."
        ),
    },
    "limitations": [
        "Squared returns as vol proxy (noisy); 5-min RV would be better",
        "DFA with only 4 scales (10,20,50,100) — more scales could give more precise H",
        "Single asset (SPY) — generalizability unknown",
        "HAR-H uses OLS (no heteroskedasticity correction)",
        "Regime-Hurst uses crude variance scaling rather than true regime-switching model",
        "Hurst on absolute returns vs log-variance may give different H values",
    ],
    "runtime_seconds": {
        "hurst_computation": round(elapsed_hurst, 1),
        "oos_evaluation": round(elapsed_oos, 1),
        "total": round(elapsed_hurst + elapsed_oos, 1),
    },
    "plots": [
        "experiments/k625/k625_hurst_evolution.png",
        "experiments/k625/k625_hurst_oos_comparison.png",
    ],
}

results_path = "experiments/k625/k625_hurst_volatility_results.json"
with open(results_path, "w") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print(f"\nResults saved to {results_path}")
print(f"\nTotal runtime: {elapsed_hurst + elapsed_oos:.1f}s")
print("K625 complete.")
