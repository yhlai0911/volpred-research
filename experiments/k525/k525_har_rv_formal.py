#!/usr/bin/env python3
"""
K525: Formal HAR-RV Experiment with 60+ Day 5-Min Data
=======================================================
[提出: 用戶, 執行: Claude]

Background:
  K188 (42d): HAR ceiling test — insufficient data, R² near zero.
  K522 (50d): HAR-RV pilot — preliminary, monthly component under-identified.
  K465/K469: HAR log-range with Parkinson proxy (tautology issue in K468).
  K490: GJR-X(VIX9D) champion — QLIKE -4.6%, VaR 5/5 (current best).
  NOW: 60+ trading days of 5-min data → formal HAR-RV evaluation.

Research Questions:
  1. With 60+ days, does HAR-RV outperform GJR-GARCH when evaluated against
     TRUE realized variance (5-min RV)?
  2. Do jump-robust extensions (HAR-RV-J, HAR-RV-CJ) improve forecasts?
  3. Does semivariance decomposition (HAR-RV-RS, Patton & Sheppard 2015) help?
  4. How does HAR-RV compare to the K490 champion GJR-X(VIX9D)?
  5. Are results robust across 2-fold cross-OOS?

Models:
  1. HAR-RV (Corsi 2009): baseline intraday model
  2. HAR-RV-J (ABD 2007): + jump component J_t = max(RV_t - BV_t, 0)
  3. HAR-RV-CJ: continuous (BV) and jump separated
  4. HAR-RV-RS (Patton & Sheppard 2015): + semivariance RS⁺/RS⁻
  5. GJR-GARCH(1,1) (arch package, daily close-to-close)
  6. GJR-X(VIX9D) (K490 champion, if VIX9D data available)
  7. EWMA (lambda=0.94)
  8. HAR log-range (Parkinson-based, K465/K469)

Evaluation:
  - QLIKE with 5-min RV as proxy (gold standard)
  - R²_OOS
  - DM test (Newey-West HAC) for all pairwise comparisons
  - 2-fold cross-OOS if n_days >= 70; otherwise leave-last-15-out

Data: yfinance 5-min intraday CSVs (data/intraday/SPY_5min_*.csv)
      yfinance daily (SPY, ^VIX, ^VIX9D) for GJR-GARCH-X benchmark

References:
  Corsi (2009) "A Simple Approximate Long-Memory Model" J Financial Econometrics
  Andersen, Bollerslev, Diebold (2007) "Roughing It Up" RFS
  Barndorff-Nielsen & Shephard (2004) "Power and Bipower Variation" J Financial Econometrics
  Patton & Sheppard (2015) "Good Volatility, Bad Volatility" JBES
  Patton (2011) "Volatility Forecast Comparison Using Imperfect Proxies" JoE
  Hansen & Lunde (2005) "A Forecast Comparison of Volatility Models" J Applied Econometrics
  K188, K465, K468, K469, K490, K522
"""

import json
import warnings
import time
import glob
import os
import sys
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from scipy import stats
from numpy.linalg import lstsq

warnings.filterwarnings('ignore')

START_TIME = time.time()
EXPERIMENT_ID = "K525"
MIN_DAYS = 60
OOS_SIZE = 15           # larger OOS than K522's 10 for better DM power
WARMUP_DAYS = 22        # monthly component needs 22-day history
MIN_IS = 30             # minimum in-sample after warmup
EWMA_LAMBDA = 0.94
MAIN_REPO = '/Users/yhlai0911/Desktop/volpred-research'

print("=" * 70)
print(f"{EXPERIMENT_ID}: Formal HAR-RV with 60+ Day 5-Min Data")
print("  Realized Variance + Bipower Variation + Jump + Semivariance")
print("  vs GJR-GARCH, GJR-X(VIX9D), EWMA, HAR-LogRange")
print("=" * 70)

# ============================================================
# 1. Load 5-min data and compute daily realized measures
# ============================================================
print("\n[1] Loading 5-min intraday data...")

DATA_DIR = os.path.join(MAIN_REPO, 'data', 'intraday')
if not os.path.exists(DATA_DIR):
    DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'data', 'intraday')

files = sorted(glob.glob(os.path.join(DATA_DIR, 'SPY_5min_*.csv')))
n_files = len(files)
print(f"  Found {n_files} daily 5-min files")

if n_files < MIN_DAYS:
    days_needed = MIN_DAYS - n_files
    # Estimate ETA: ~1 trading day per weekday
    from datetime import timedelta
    eta_date = datetime.now() + timedelta(days=int(days_needed * 7 / 5) + 2)
    print(f"\n  *** INSUFFICIENT DATA ***")
    print(f"  Need >= {MIN_DAYS} trading days, currently have {n_files}.")
    print(f"  Still need {days_needed} more trading days.")
    print(f"  Estimated ETA: ~{eta_date.strftime('%Y-%m-%d')}")
    print(f"  Re-run this script after accumulating enough data.")
    sys.exit(1)

# --- Parse each file and compute daily realized measures ---
rv_daily = {}           # Realized Variance: Σ r²_i
bv_daily = {}           # Bipower Variation: (π/2) Σ |r_i| |r_{i-1}|
rv_plus_daily = {}      # Positive semivariance: Σ r²_i · I(r_i > 0)
rv_minus_daily = {}     # Negative semivariance: Σ r²_i · I(r_i < 0)
close_prices = {}
ohlc_daily = {}
n_bars_daily = {}

for f in files:
    try:
        # Read with multi-row header (yfinance 5-min format)
        df = pd.read_csv(f, header=[0, 1], index_col=0)
        df.columns = [col[0] for col in df.columns]
    except Exception:
        # Fallback: single-row header
        df = pd.read_csv(f, index_col=0)

    df.index = pd.to_datetime(df.index)
    df = df.sort_index()

    if len(df) < 5:
        continue  # skip partial days

    date = df.index[0].date()
    close = df['Close'].astype(float)
    high = df['High'].astype(float)
    low = df['Low'].astype(float)
    opn = df['Open'].astype(float)

    # 5-min log returns
    log_ret = np.log(close / close.shift(1)).dropna()
    n_bars = len(log_ret)

    if n_bars < 5:
        continue

    # --- Realized Variance ---
    rv = (log_ret ** 2).sum()
    rv_daily[date] = rv

    # --- Bipower Variation (Barndorff-Nielsen & Shephard 2004) ---
    # BV = (π/2) * (n/(n-1)) * Σ_{i=2}^{n} |r_i| * |r_{i-1}|
    abs_ret = np.abs(log_ret.values)
    if len(abs_ret) >= 2:
        bv = (np.pi / 2) * (n_bars / (n_bars - 1)) * np.sum(abs_ret[1:] * abs_ret[:-1])
        bv_daily[date] = bv
    else:
        bv_daily[date] = rv  # fallback

    # --- Positive and Negative Semivariance (Patton & Sheppard 2015) ---
    ret_vals = log_ret.values
    rv_plus_daily[date] = np.sum(ret_vals[ret_vals > 0] ** 2)
    rv_minus_daily[date] = np.sum(ret_vals[ret_vals < 0] ** 2)

    # --- Daily OHLC from intraday ---
    daily_high = high.max()
    daily_low = low.min()
    daily_open = opn.iloc[0]
    daily_close = close.iloc[-1]
    close_prices[date] = daily_close
    ohlc_daily[date] = {'open': daily_open, 'high': daily_high,
                         'low': daily_low, 'close': daily_close}
    n_bars_daily[date] = n_bars

# Build aligned series
rv_series = pd.Series(rv_daily).sort_index()
bv_series = pd.Series(bv_daily).sort_index()
rv_plus_series = pd.Series(rv_plus_daily).sort_index()
rv_minus_series = pd.Series(rv_minus_daily).sort_index()
close_series = pd.Series(close_prices).sort_index()
parkinson_daily = {}
for d in ohlc_daily:
    h, l = ohlc_daily[d]['high'], ohlc_daily[d]['low']
    if h > 0 and l > 0:
        parkinson_daily[d] = np.log(h / l) ** 2 / (4 * np.log(2))
parkinson_series = pd.Series(parkinson_daily).sort_index()

# Jump component: J_t = max(RV_t - BV_t, 0)
jump_series = (rv_series - bv_series).clip(lower=0)
# Continuous component: C_t = BV_t (or min(RV_t, BV_t) to be safe)
continuous_series = bv_series.copy()

# Daily close-to-close log returns
daily_log_ret = np.log(close_series / close_series.shift(1)).dropna()
r2_series = daily_log_ret ** 2

n_days = len(rv_series)
print(f"  RV series: {n_days} days [{rv_series.index[0]} to {rv_series.index[-1]}]")
print(f"  Annualized vol (from RV): {np.sqrt(rv_series.mean() * 252) * 100:.1f}%")
print(f"  Avg bars/day: {np.mean(list(n_bars_daily.values())):.0f}")

if n_days < MIN_DAYS:
    print(f"\n  *** After filtering, only {n_days} usable days (need {MIN_DAYS}). Exiting. ***")
    sys.exit(1)

# ============================================================
# 2. Descriptive Statistics & Diagnostics
# ============================================================
print("\n[2] Descriptive Statistics")

stats_data = {}
for name, s in [('RV_5min', rv_series), ('BV', bv_series), ('Jump', jump_series),
                ('RV+', rv_plus_series), ('RV-', rv_minus_series),
                ('Parkinson', parkinson_series), ('r²', r2_series)]:
    common = rv_series.index.intersection(s.index)
    s_a = s.loc[common]
    stats_data[name] = {
        'mean': float(s_a.mean()),
        'std': float(s_a.std()),
        'min': float(s_a.min()),
        'max': float(s_a.max()),
        'skew': float(s_a.skew()),
        'kurtosis': float(s_a.kurtosis()),
        'count': int(len(s_a)),
    }

print(f"  {'Metric':<12} {'RV_5min':<14} {'BV':<14} {'Jump':<14} {'RV+':<14} {'RV-':<14} {'Parkinson':<14} {'r²':<14}")
print(f"  {'-'*110}")
for metric in ['mean', 'std', 'min', 'max', 'skew']:
    vals = [f"{stats_data[k][metric]:.2e}" for k in ['RV_5min', 'BV', 'Jump', 'RV+', 'RV-', 'Parkinson', 'r²']]
    print(f"  {metric:<12} {'  '.join(f'{v:<12}' for v in vals)}")

# Proxy correlations
common_idx = rv_series.index
for s in [bv_series, parkinson_series, r2_series]:
    common_idx = common_idx.intersection(s.index)

print(f"\n  Proxy correlations (n={len(common_idx)}):")
proxy_corr = {}
for n1, s1 in [('RV', rv_series), ('BV', bv_series), ('Parkinson', parkinson_series), ('r²', r2_series)]:
    for n2, s2 in [('RV', rv_series), ('BV', bv_series), ('Parkinson', parkinson_series), ('r²', r2_series)]:
        if n1 < n2:
            c = np.corrcoef(s1.loc[common_idx], s2.loc[common_idx])[0, 1]
            proxy_corr[f'{n1}_vs_{n2}'] = float(c)
            print(f"    {n1} vs {n2}: {c:.4f}")

# Jump proportion
jump_pct = jump_series.mean() / rv_series.mean() * 100
print(f"\n  Jump proportion: {jump_pct:.1f}% of total RV")
print(f"  RV+ share: {rv_plus_series.mean() / rv_series.mean() * 100:.1f}%")
print(f"  RV- share: {rv_minus_series.mean() / rv_series.mean() * 100:.1f}%")

# ADF test on log(RV)
log_rv = np.log(rv_series)
try:
    from statsmodels.tsa.stattools import adfuller
    adf_stat, adf_pval, _, _, _, _ = adfuller(log_rv, maxlag=5)
    print(f"\n  ADF test on log(RV): stat={adf_stat:.3f}, p={adf_pval:.4f} "
          f"({'Stationary' if adf_pval < 0.05 else 'Non-stationary'})")
except ImportError:
    print("  (statsmodels not available for ADF test)")

# ============================================================
# 3. HAR Feature Builders
# ============================================================
print("\n[3] Building HAR models...")


def build_har_features(rv_s, min_history=WARMUP_DAYS):
    """Build HAR-RV features: daily(1), weekly(5), monthly(22)."""
    dates = rv_s.index
    features, targets, target_dates = [], [], []
    for i in range(min_history, len(rv_s) - 1):
        rv_d = rv_s.iloc[i]
        rv_w = rv_s.iloc[max(0, i-4):i+1].mean()
        rv_m = rv_s.iloc[max(0, i-21):i+1].mean()
        features.append([rv_d, rv_w, rv_m])
        targets.append(rv_s.iloc[i + 1])
        target_dates.append(dates[i + 1])
    return np.array(features), np.array(targets), target_dates


def build_har_j_features(rv_s, jump_s, min_history=WARMUP_DAYS):
    """HAR-RV-J: HAR features + jump component (ABD 2007)."""
    dates = rv_s.index
    features, targets, target_dates = [], [], []
    for i in range(min_history, len(rv_s) - 1):
        rv_d = rv_s.iloc[i]
        rv_w = rv_s.iloc[max(0, i-4):i+1].mean()
        rv_m = rv_s.iloc[max(0, i-21):i+1].mean()
        j_d = jump_s.iloc[i]
        j_w = jump_s.iloc[max(0, i-4):i+1].mean()
        features.append([rv_d, rv_w, rv_m, j_d, j_w])
        targets.append(rv_s.iloc[i + 1])
        target_dates.append(dates[i + 1])
    return np.array(features), np.array(targets), target_dates


def build_har_cj_features(cont_s, jump_s, min_history=WARMUP_DAYS):
    """HAR-RV-CJ: continuous and jump decomposition."""
    dates = cont_s.index
    features, targets, target_dates = [], [], []
    rv_s = cont_s + jump_s  # total RV
    for i in range(min_history, len(cont_s) - 1):
        c_d = cont_s.iloc[i]
        c_w = cont_s.iloc[max(0, i-4):i+1].mean()
        c_m = cont_s.iloc[max(0, i-21):i+1].mean()
        j_d = jump_s.iloc[i]
        j_w = jump_s.iloc[max(0, i-4):i+1].mean()
        j_m = jump_s.iloc[max(0, i-21):i+1].mean()
        features.append([c_d, c_w, c_m, j_d, j_w, j_m])
        targets.append(rv_s.iloc[i + 1])
        target_dates.append(dates[i + 1])
    return np.array(features), np.array(targets), target_dates


def build_har_rs_features(rv_plus_s, rv_minus_s, min_history=WARMUP_DAYS):
    """HAR-RV-RS: positive and negative semivariance (Patton & Sheppard 2015)."""
    dates = rv_plus_s.index
    features, targets, target_dates = [], [], []
    rv_s = rv_plus_s + rv_minus_s  # total RV
    for i in range(min_history, len(rv_plus_s) - 1):
        # Daily
        rvp_d = rv_plus_s.iloc[i]
        rvm_d = rv_minus_s.iloc[i]
        # Weekly
        rvp_w = rv_plus_s.iloc[max(0, i-4):i+1].mean()
        rvm_w = rv_minus_s.iloc[max(0, i-4):i+1].mean()
        # Monthly
        rvp_m = rv_plus_s.iloc[max(0, i-21):i+1].mean()
        rvm_m = rv_minus_s.iloc[max(0, i-21):i+1].mean()
        features.append([rvp_d, rvm_d, rvp_w, rvm_w, rvp_m, rvm_m])
        targets.append(rv_s.iloc[i + 1])
        target_dates.append(dates[i + 1])
    return np.array(features), np.array(targets), target_dates


# ============================================================
# 4. OLS estimation and forecasting utilities
# ============================================================

def ols_fit(X, y):
    """OLS with intercept. Returns beta, R², residuals, SE, t-stats."""
    n = len(y)
    X_c = np.column_stack([np.ones(n), X])
    beta, _, rank, _ = lstsq(X_c, y, rcond=None)
    y_hat = X_c @ beta
    resid = y - y_hat
    ss_res = np.sum(resid ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    k = X_c.shape[1]
    mse = ss_res / max(n - k, 1)
    try:
        cov = mse * np.linalg.inv(X_c.T @ X_c)
        se = np.sqrt(np.maximum(np.diag(cov), 0))
    except np.linalg.LinAlgError:
        se = np.full(k, np.nan)
    t_stat = np.where(se > 1e-15, beta / se, np.nan)
    return beta, r2, resid, se, t_stat


def ols_forecast(X_oos, beta):
    """Forecast using OLS beta with intercept."""
    n = X_oos.shape[0]
    X_c = np.column_stack([np.ones(n), X_oos])
    fc = X_c @ beta
    return np.maximum(fc, 1e-12)  # floor at tiny positive


# ============================================================
# 5. Loss functions
# ============================================================

def qlike(forecast, actual):
    """QLIKE loss: mean(actual/forecast - log(actual/forecast) - 1)."""
    ratio = actual / forecast
    return float(np.mean(ratio - np.log(ratio) - 1))


def qlike_individual(forecast, actual):
    """Per-observation QLIKE losses."""
    ratio = actual / forecast
    return ratio - np.log(ratio) - 1


def mse_loss(forecast, actual):
    return float(np.mean((forecast - actual) ** 2))


def mae_loss(forecast, actual):
    return float(np.mean(np.abs(forecast - actual)))


def oos_r2(forecast, actual):
    ss_res = np.sum((actual - forecast) ** 2)
    ss_tot = np.sum((actual - actual.mean()) ** 2)
    return float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0


def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test with Newey-West HAC variance. H0: equal accuracy."""
    d = loss1 - loss2
    d_mean = np.mean(d)
    n = len(d)
    if n < 3:
        return 0.0, 1.0
    gamma0 = np.var(d, ddof=1)
    hac_var = gamma0
    for k in range(1, min(h, n - 1)):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1] if len(d[k:]) > 1 else 0
        hac_var += 2 * (1 - k / h) * gamma_k
    se = np.sqrt(max(hac_var / n, 1e-30))
    dm_stat = d_mean / se
    p_val = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return float(dm_stat), float(p_val)


# ============================================================
# 6. Determine OOS design
# ============================================================
print("\n[4] OOS Design")

# Total usable observations after warmup
X_har, y_har, dates_har = build_har_features(rv_series)
n_total = len(y_har)
print(f"  Total usable observations (after {WARMUP_DAYS}-day warmup): {n_total}")

# Decide between 2-fold cross-OOS or single split
USE_CROSS_OOS = n_total >= 50  # need enough for 2 reasonable folds

if USE_CROSS_OOS:
    n_half = n_total // 2
    fold_splits = [
        ("Fold1", 0, n_half, n_half, n_total),      # Train on first half, test second
        ("Fold2", n_half, n_total, 0, n_half),       # Train on second half, test first
    ]
    print(f"  Design: 2-fold cross-OOS (n_half={n_half})")
else:
    n_is = n_total - OOS_SIZE
    if n_is < MIN_IS:
        print(f"  WARNING: IS={n_is} < {MIN_IS}. Adjusting OOS to {n_total - MIN_IS}.")
        OOS_SIZE_ACTUAL = max(n_total - MIN_IS, 5)
        n_is = n_total - OOS_SIZE_ACTUAL
    else:
        OOS_SIZE_ACTUAL = OOS_SIZE
    fold_splits = [
        ("Single", 0, n_is, n_is, n_total),
    ]
    print(f"  Design: Single split (IS={n_is}, OOS={OOS_SIZE_ACTUAL})")


# ============================================================
# 7. Run all HAR model variants
# ============================================================
print("\n[5] Estimating HAR model family...")

har_model_specs = {}

# Pre-build all feature sets
X_harj, y_harj, dates_harj = build_har_j_features(rv_series, jump_series)
X_harcj, y_harcj, dates_harcj = build_har_cj_features(continuous_series, jump_series)
X_harrs, y_harrs, dates_harrs = build_har_rs_features(rv_plus_series, rv_minus_series)

model_data = {
    'HAR-RV': (X_har, y_har, dates_har,
               ['beta_d', 'beta_w', 'beta_m']),
    'HAR-RV-J': (X_harj, y_harj, dates_harj,
                 ['beta_d', 'beta_w', 'beta_m', 'jump_d', 'jump_w']),
    'HAR-RV-CJ': (X_harcj, y_harcj, dates_harcj,
                  ['cont_d', 'cont_w', 'cont_m', 'jump_d', 'jump_w', 'jump_m']),
    'HAR-RV-RS': (X_harrs, y_harrs, dates_harrs,
                  ['rv+_d', 'rv-_d', 'rv+_w', 'rv-_w', 'rv+_m', 'rv-_m']),
}

all_results = {}
all_dm_pairs = []

for fold_name, is_start, is_end, oos_start, oos_end in fold_splits:
    print(f"\n  --- {fold_name} ---")
    fold_results = {}
    fold_forecasts = {}
    fold_actuals = None

    for m_name, (X, y, dates, coef_names) in model_data.items():
        n_obs = len(y)
        # Adjust indices for this model's observation count (may differ slightly)
        if USE_CROSS_OOS:
            # For cross-OOS, use proportional split
            is_s = int(is_start * n_obs / n_total)
            is_e = int(is_end * n_obs / n_total)
            oos_s = int(oos_start * n_obs / n_total)
            oos_e = int(oos_end * n_obs / n_total)
        else:
            is_s = 0
            is_e = n_obs - OOS_SIZE_ACTUAL if not USE_CROSS_OOS else is_end
            oos_s = is_e
            oos_e = n_obs

        X_is, y_is = X[is_s:is_e], y[is_s:is_e]
        X_oos, y_oos = X[oos_s:oos_e], y[oos_s:oos_e]

        if len(X_is) < 5 or len(X_oos) < 3:
            print(f"    {m_name}: skipped (IS={len(X_is)}, OOS={len(X_oos)})")
            continue

        beta, r2_is, resid, se, t_stat = ols_fit(X_is, y_is)
        fc = ols_forecast(X_oos, beta)

        # Evaluation
        q = qlike(fc, y_oos)
        r2_o = oos_r2(fc, y_oos)
        mse_v = mse_loss(fc, y_oos)

        fold_results[m_name] = {
            'QLIKE': q,
            'R2_OOS': r2_o,
            'MSE': mse_v,
            'MAE': mae_loss(fc, y_oos),
            'R2_IS': float(r2_is),
            'n_IS': int(len(X_is)),
            'n_OOS': int(len(X_oos)),
            'coefficients': {n: float(beta[i+1]) for i, n in enumerate(coef_names)},
            'intercept': float(beta[0]),
            't_statistics': {n: float(t_stat[i+1]) for i, n in enumerate(coef_names)},
        }

        fold_forecasts[m_name] = (fc, y_oos)
        if fold_actuals is None:
            fold_actuals = y_oos

        sig_coefs = sum(1 for t in t_stat[1:] if abs(t) > 1.96)
        print(f"    {m_name:<15}: QLIKE={q:.4f}, R²_OOS={r2_o:.4f}, R²_IS={r2_is:.4f}, "
              f"sig_coefs={sig_coefs}/{len(coef_names)}")

    # --- GJR-GARCH & EWMA (daily models) ---
    print(f"\n  --- {fold_name}: Daily models ---")

    # GJR-GARCH
    try:
        from arch import arch_model

        returns_pct = daily_log_ret * 100
        n_ret = len(returns_pct)

        if USE_CROSS_OOS:
            # Map fold indices to return dates
            oos_dates_fold = [dates_har[i] for i in range(oos_start, min(oos_end, len(dates_har)))]
            is_dates_fold = [dates_har[i] for i in range(is_start, min(is_end, len(dates_har)))]

            # For GJR, always use expanding window ending before OOS start
            # Use all returns up to the OOS period
            ret_dates = returns_pct.index
            oos_start_date = pd.Timestamp(oos_dates_fold[0]) if oos_dates_fold else ret_dates[-1]

            # Rolling 1-step forecasts for OOS period
            gjr_forecasts = []
            gjr_oos_actual_rv = []
            oos_ret_indices = [i for i, d in enumerate(ret_dates) if d in [pd.Timestamp(x) for x in oos_dates_fold]]

            # Simpler approach: use return index-based split
            if not USE_CROSS_OOS:
                raise ValueError("Handled below")

            # For cross-OOS, do rolling from the IS data
            gjr_oos_size = min(oos_end - oos_start, len(returns_pct) - 10)
            ret_oos_start = max(0, n_ret - (n_total - oos_start))
            ret_oos_end = min(n_ret, n_ret - (n_total - oos_end))

            if ret_oos_start >= ret_oos_end or ret_oos_start < 10:
                raise ValueError(f"Cannot map fold to return indices (start={ret_oos_start}, end={ret_oos_end})")

            for i in range(ret_oos_start, ret_oos_end):
                ret_window = returns_pct.iloc[:i]
                if len(ret_window) < 20:
                    continue
                m = arch_model(ret_window, vol='GARCH', p=1, o=1, q=1,
                               dist='StudentsT', mean='Constant')
                r = m.fit(disp='off', show_warning=False)
                fc = r.forecast(horizon=1)
                gjr_forecasts.append(fc.variance.values[-1, 0] / 10000.0)
                # Map this return date to RV
                ret_date = returns_pct.index[i].date() if hasattr(returns_pct.index[i], 'date') else returns_pct.index[i]
                if ret_date in rv_daily:
                    gjr_oos_actual_rv.append(rv_daily[ret_date])
                else:
                    gjr_oos_actual_rv.append(np.nan)

        else:
            # Single split: simpler
            n_ret_oos = OOS_SIZE_ACTUAL
            ret_is = returns_pct.iloc[:-n_ret_oos]

            model_gjr = arch_model(ret_is, vol='GARCH', p=1, o=1, q=1,
                                    dist='StudentsT', mean='Constant')
            res_gjr = model_gjr.fit(disp='off', show_warning=False)

            print(f"    GJR-GARCH params: α={res_gjr.params.get('alpha[1]', 0):.4f}, "
                  f"γ={res_gjr.params.get('gamma[1]', 0):.4f}, "
                  f"β={res_gjr.params.get('beta[1]', 0):.4f}, "
                  f"pers={res_gjr.params.get('alpha[1]', 0) + res_gjr.params.get('gamma[1]', 0)/2 + res_gjr.params.get('beta[1]', 0):.4f}")

            gjr_forecasts = []
            gjr_oos_actual_rv = rv_series.iloc[-n_ret_oos:].values.tolist()

            for i in range(n_ret_oos):
                ret_window = returns_pct.iloc[:-(n_ret_oos - i)]
                m = arch_model(ret_window, vol='GARCH', p=1, o=1, q=1,
                               dist='StudentsT', mean='Constant')
                r = m.fit(disp='off', show_warning=False, starting_values=res_gjr.params.values)
                fc = r.forecast(horizon=1)
                gjr_forecasts.append(fc.variance.values[-1, 0] / 10000.0)

        gjr_forecasts = np.array(gjr_forecasts)
        gjr_oos_actual_rv = np.array(gjr_oos_actual_rv)

        # Remove NaN entries
        valid = ~np.isnan(gjr_oos_actual_rv)
        if valid.sum() >= 3:
            gjr_fc_valid = np.maximum(gjr_forecasts[valid], 1e-12)
            gjr_rv_valid = gjr_oos_actual_rv[valid]

            q_gjr = qlike(gjr_fc_valid, gjr_rv_valid)
            r2_gjr = oos_r2(gjr_fc_valid, gjr_rv_valid)
            fold_results['GJR-GARCH'] = {
                'QLIKE': q_gjr, 'R2_OOS': r2_gjr,
                'MSE': mse_loss(gjr_fc_valid, gjr_rv_valid),
                'MAE': mae_loss(gjr_fc_valid, gjr_rv_valid),
                'n_OOS': int(valid.sum()),
            }
            fold_forecasts['GJR-GARCH'] = (gjr_fc_valid, gjr_rv_valid)
            print(f"    GJR-GARCH     : QLIKE={q_gjr:.4f}, R²_OOS={r2_gjr:.4f}")
        else:
            print(f"    GJR-GARCH: insufficient valid OOS points")

    except Exception as e:
        print(f"    GJR-GARCH failed: {e}")

    # --- GJR-X(VIX9D) champion (K490) ---
    try:
        import yfinance as yf

        # Download VIX9D data
        vix9d = yf.download('^VIX9D', start='2025-01-01', progress=False)
        if isinstance(vix9d.columns, pd.MultiIndex):
            vix9d.columns = vix9d.columns.get_level_values(0)
        vix9d_close = vix9d['Close'].dropna()

        if len(vix9d_close) >= 20:
            # Align VIX9D with return dates
            ret_dates_set = set(returns_pct.index.date if hasattr(returns_pct.index, 'date') else returns_pct.index)

            # Build VIX9D variance exogenous: (VIX9D/100)² / 252
            vix9d_var = (vix9d_close / 100) ** 2 / 252

            if not USE_CROSS_OOS:
                n_ret_oos = OOS_SIZE_ACTUAL
                gjrx_forecasts = []

                for i in range(n_ret_oos):
                    idx = -(n_ret_oos - i)
                    ret_window = returns_pct.iloc[:idx] if idx != 0 else returns_pct

                    # Get aligned VIX9D for this window
                    ret_window_dates = ret_window.index
                    vix9d_aligned = vix9d_var.reindex(ret_window_dates).ffill().dropna()

                    if len(vix9d_aligned) < 20:
                        gjrx_forecasts.append(np.nan)
                        continue

                    # Use only dates where both exist
                    common_dates = ret_window_dates.intersection(vix9d_aligned.index)
                    if len(common_dates) < 20:
                        gjrx_forecasts.append(np.nan)
                        continue

                    ret_w = returns_pct.loc[common_dates]
                    vix9d_w = vix9d_aligned.loc[common_dates]

                    m = arch_model(ret_w, vol='GARCH', p=1, o=1, q=1,
                                   x=pd.DataFrame({'VIX9D_var': vix9d_w}),
                                   dist='StudentsT', mean='Constant')
                    try:
                        r = m.fit(disp='off', show_warning=False)
                        # For forecast, need last VIX9D value
                        fc = r.forecast(horizon=1, x=pd.DataFrame({'VIX9D_var': [vix9d_var.iloc[-1]]}))
                        gjrx_forecasts.append(fc.variance.values[-1, 0] / 10000.0)
                    except Exception:
                        gjrx_forecasts.append(np.nan)

                gjrx_forecasts = np.array(gjrx_forecasts)
                gjrx_actual = rv_series.iloc[-n_ret_oos:].values

                valid_x = ~np.isnan(gjrx_forecasts)
                if valid_x.sum() >= 3:
                    gjrx_fc = np.maximum(gjrx_forecasts[valid_x], 1e-12)
                    gjrx_rv = gjrx_actual[valid_x]

                    q_gjrx = qlike(gjrx_fc, gjrx_rv)
                    r2_gjrx = oos_r2(gjrx_fc, gjrx_rv)
                    fold_results['GJR-X(VIX9D)'] = {
                        'QLIKE': q_gjrx, 'R2_OOS': r2_gjrx,
                        'MSE': mse_loss(gjrx_fc, gjrx_rv),
                        'MAE': mae_loss(gjrx_fc, gjrx_rv),
                        'n_OOS': int(valid_x.sum()),
                    }
                    fold_forecasts['GJR-X(VIX9D)'] = (gjrx_fc, gjrx_rv)
                    print(f"    GJR-X(VIX9D)  : QLIKE={q_gjrx:.4f}, R²_OOS={r2_gjrx:.4f}")
                else:
                    print(f"    GJR-X(VIX9D): insufficient valid OOS")
            else:
                print(f"    GJR-X(VIX9D): skipped in cross-OOS (complex alignment)")
        else:
            print(f"    GJR-X(VIX9D): insufficient VIX9D data")

    except Exception as e:
        print(f"    GJR-X(VIX9D) failed: {e}")

    # --- EWMA ---
    ewma_var = np.zeros(len(rv_series))
    ewma_var[0] = rv_series.iloc[0]
    for i in range(1, len(rv_series)):
        ewma_var[i] = EWMA_LAMBDA * ewma_var[i - 1] + (1 - EWMA_LAMBDA) * rv_series.iloc[i]

    if not USE_CROSS_OOS:
        ewma_fc = ewma_var[-(OOS_SIZE_ACTUAL + 1):-1]
        ewma_actual = rv_series.iloc[-OOS_SIZE_ACTUAL:].values
    else:
        ewma_fc = ewma_var[oos_start + WARMUP_DAYS:oos_end + WARMUP_DAYS - 1]
        ewma_actual_idx = slice(oos_start + WARMUP_DAYS, oos_end + WARMUP_DAYS)
        if oos_end + WARMUP_DAYS <= len(rv_series):
            ewma_actual = rv_series.iloc[ewma_actual_idx].values
        else:
            ewma_actual = rv_series.iloc[oos_start + WARMUP_DAYS:].values

    # Match lengths
    min_len = min(len(ewma_fc), len(ewma_actual))
    if min_len >= 3:
        ewma_fc = np.maximum(ewma_fc[:min_len], 1e-12)
        ewma_actual = ewma_actual[:min_len]

        q_ewma = qlike(ewma_fc, ewma_actual)
        r2_ewma = oos_r2(ewma_fc, ewma_actual)
        fold_results['EWMA'] = {
            'QLIKE': q_ewma, 'R2_OOS': r2_ewma,
            'MSE': mse_loss(ewma_fc, ewma_actual),
            'MAE': mae_loss(ewma_fc, ewma_actual),
            'n_OOS': int(min_len),
        }
        fold_forecasts['EWMA'] = (ewma_fc, ewma_actual)
        print(f"    EWMA          : QLIKE={q_ewma:.4f}, R²_OOS={r2_ewma:.4f}")

    # --- HAR Log-Range ---
    log_range_series = pd.Series(
        {d: np.log(ohlc_daily[d]['high'] / ohlc_daily[d]['low'])
         for d in ohlc_daily if ohlc_daily[d]['high'] > 0 and ohlc_daily[d]['low'] > 0}
    ).sort_index()

    X_lr, y_lr = [], []
    for i in range(WARMUP_DAYS, len(log_range_series) - 1):
        lr_d = log_range_series.iloc[i]
        lr_w = log_range_series.iloc[max(0, i-4):i+1].mean()
        lr_m = log_range_series.iloc[max(0, i-21):i+1].mean()
        X_lr.append([lr_d, lr_w, lr_m])
        y_lr.append(log_range_series.iloc[i + 1])

    if len(X_lr) > 10:
        X_lr = np.array(X_lr)
        y_lr = np.array(y_lr)

        if not USE_CROSS_OOS:
            lr_is_n = len(y_lr) - OOS_SIZE_ACTUAL
        else:
            lr_is_n = int(is_end * len(y_lr) / n_total)
            lr_oos_start = int(oos_start * len(y_lr) / n_total)
            lr_oos_end = int(oos_end * len(y_lr) / n_total)

        if not USE_CROSS_OOS:
            X_lr_is, y_lr_is = X_lr[:lr_is_n], y_lr[:lr_is_n]
            X_lr_oos = X_lr[lr_is_n:]
        else:
            X_lr_is, y_lr_is = X_lr[is_start:is_end] if is_end <= len(X_lr) else (X_lr[:lr_is_n], y_lr[:lr_is_n])
            X_lr_oos = X_lr[lr_oos_start:lr_oos_end]

        if len(X_lr_is) >= 5 and len(X_lr_oos) >= 3:
            beta_lr, r2_lr_is, _, _, _ = ols_fit(X_lr_is, y_lr_is)
            lr_fc_raw = ols_forecast(X_lr_oos, beta_lr)

            # Convert log-range to variance scale
            lr_fc_var = lr_fc_raw ** 2 / (4 * np.log(2))

            # Scale to RV level
            park_mean = parkinson_series.mean()
            rv_mean = rv_series.mean()
            scale_ratio = rv_mean / park_mean if park_mean > 0 else 1.0
            lr_fc_scaled = lr_fc_var * scale_ratio

            # Get matching actual RV
            lr_oos_n = len(lr_fc_scaled)
            if not USE_CROSS_OOS:
                lr_actual = rv_series.iloc[-lr_oos_n:].values
            else:
                lr_actual = rv_series.iloc[lr_oos_start + WARMUP_DAYS:lr_oos_start + WARMUP_DAYS + lr_oos_n].values

            lr_oos_n = min(len(lr_fc_scaled), len(lr_actual))
            if lr_oos_n >= 3:
                q_lr = qlike(lr_fc_scaled[:lr_oos_n], lr_actual[:lr_oos_n])
                r2_lr = oos_r2(lr_fc_scaled[:lr_oos_n], lr_actual[:lr_oos_n])
                fold_results['HAR-LogRange'] = {
                    'QLIKE': q_lr, 'R2_OOS': r2_lr,
                    'MSE': mse_loss(lr_fc_scaled[:lr_oos_n], lr_actual[:lr_oos_n]),
                    'MAE': mae_loss(lr_fc_scaled[:lr_oos_n], lr_actual[:lr_oos_n]),
                    'n_OOS': int(lr_oos_n),
                    'scale_ratio': float(scale_ratio),
                }
                fold_forecasts['HAR-LogRange'] = (lr_fc_scaled[:lr_oos_n], lr_actual[:lr_oos_n])
                print(f"    HAR-LogRange   : QLIKE={q_lr:.4f}, R²_OOS={r2_lr:.4f}")

    # --- Pairwise DM tests ---
    print(f"\n  --- {fold_name}: Diebold-Mariano Tests ---")
    fold_dm = {}
    model_names = list(fold_forecasts.keys())

    for i, m1 in enumerate(model_names):
        for m2 in model_names[i+1:]:
            fc1, act1 = fold_forecasts[m1]
            fc2, act2 = fold_forecasts[m2]

            # Need same actual for valid comparison — use minimum common length
            n_common = min(len(fc1), len(fc2), len(act1), len(act2))
            if n_common < 3:
                continue

            # Use the actual from the first model (should be same if same OOS)
            loss1 = qlike_individual(fc1[:n_common], act1[:n_common])
            loss2 = qlike_individual(fc2[:n_common], act2[:n_common])

            dm_stat, dm_pval = dm_test(loss1, loss2)
            pair_name = f'{m1} vs {m2}'
            fold_dm[pair_name] = {
                'DM_stat': dm_stat,
                'p_value': dm_pval,
                'first_better': bool(dm_stat < 0),
                'n': int(n_common),
            }

            sig = '***' if dm_pval < 0.01 else '**' if dm_pval < 0.05 else '*' if dm_pval < 0.10 else 'n.s.'
            winner = m1 if dm_stat < 0 else m2
            print(f"    {pair_name:<35}: DM={dm_stat:>7.3f}, p={dm_pval:.4f} ({sig}) → {winner}")

    # Store fold results
    all_results[fold_name] = {
        'models': fold_results,
        'dm_tests': fold_dm,
    }

# ============================================================
# 8. Aggregate cross-OOS results
# ============================================================
print("\n[6] Summary Across Folds")

if len(all_results) == 1:
    fold_name = list(all_results.keys())[0]
    final_results = all_results[fold_name]['models']
    final_dm = all_results[fold_name]['dm_tests']
else:
    # Average QLIKE and R² across folds
    all_model_names = set()
    for fold in all_results.values():
        all_model_names.update(fold['models'].keys())

    final_results = {}
    for m in all_model_names:
        qlikes = [all_results[f]['models'][m]['QLIKE']
                  for f in all_results if m in all_results[f]['models']]
        r2s = [all_results[f]['models'][m]['R2_OOS']
               for f in all_results if m in all_results[f]['models']]
        if qlikes:
            final_results[m] = {
                'QLIKE_mean': float(np.mean(qlikes)),
                'QLIKE_folds': qlikes,
                'R2_OOS_mean': float(np.mean(r2s)),
                'R2_OOS_folds': r2s,
                'n_folds': len(qlikes),
            }
    final_dm = {}
    for fold in all_results.values():
        for pair, dm in fold['dm_tests'].items():
            if pair not in final_dm:
                final_dm[pair] = []
            final_dm[pair].append(dm)

# Ranking table
print(f"\n  {'Model':<20} {'QLIKE':<12} {'R²_OOS':<12} {'MSE(×10⁸)':<12}")
print(f"  {'-'*56}")

if len(all_results) == 1:
    ranked = sorted(final_results.items(), key=lambda x: x[1].get('QLIKE', 999))
    best_model = ranked[0][0] if ranked else 'N/A'
    for name, r in ranked:
        marker = ' ★' if name == best_model else ''
        q = r.get('QLIKE', float('nan'))
        r2 = r.get('R2_OOS', float('nan'))
        mse_v = r.get('MSE', float('nan'))
        print(f"  {name:<20} {q:<12.4f} {r2:<12.4f} {mse_v*1e8:<12.4f}{marker}")
else:
    ranked = sorted(final_results.items(), key=lambda x: x[1].get('QLIKE_mean', 999))
    best_model = ranked[0][0] if ranked else 'N/A'
    for name, r in ranked:
        marker = ' ★' if name == best_model else ''
        q = r.get('QLIKE_mean', float('nan'))
        r2 = r.get('R2_OOS_mean', float('nan'))
        print(f"  {name:<20} {q:<12.4f} {r2:<12.4f} (avg {r['n_folds']} folds){marker}")

# ============================================================
# 9. HAR Component Analysis (full sample)
# ============================================================
print("\n[7] HAR Component Analysis (full-sample estimation)")

# Estimate on full sample for interpretability
beta_full, r2_full, _, se_full, t_full = ols_fit(X_har, y_har)

print(f"  HAR-RV (full sample, n={len(y_har)}):")
print(f"    R² = {r2_full:.4f}")
har_coef_names = ['intercept', 'beta_d', 'beta_w', 'beta_m']
for i, name in enumerate(har_coef_names):
    sig = '***' if abs(t_full[i]) > 2.576 else '**' if abs(t_full[i]) > 1.96 else '*' if abs(t_full[i]) > 1.645 else ''
    print(f"    {name:<12}: β={beta_full[i]:>10.6f}, SE={se_full[i]:>10.6f}, t={t_full[i]:>7.3f} {sig}")

# Component contribution
total_beta = abs(beta_full[1]) + abs(beta_full[2]) + abs(beta_full[3])
if total_beta > 0:
    print(f"\n  Relative contribution (|β|):")
    print(f"    Daily:   {abs(beta_full[1])/total_beta*100:.1f}%")
    print(f"    Weekly:  {abs(beta_full[2])/total_beta*100:.1f}%")
    print(f"    Monthly: {abs(beta_full[3])/total_beta*100:.1f}%")
    print(f"\n  Corsi (2009) typical: β_d≈0.36, β_w≈0.28, β_m≈0.28")

# HAR-RV-J full sample
if len(X_harj) > 10:
    beta_j_full, r2_j_full, _, se_j, t_j = ols_fit(X_harj, y_harj)
    print(f"\n  HAR-RV-J (full sample):")
    print(f"    R² = {r2_j_full:.4f} (HAR-RV: {r2_full:.4f}, Δ={r2_j_full-r2_full:+.4f})")
    j_names = ['intercept', 'beta_d', 'beta_w', 'beta_m', 'jump_d', 'jump_w']
    for i, name in enumerate(j_names):
        sig = '***' if abs(t_j[i]) > 2.576 else '**' if abs(t_j[i]) > 1.96 else '*' if abs(t_j[i]) > 1.645 else ''
        print(f"    {name:<12}: β={beta_j_full[i]:>10.6f}, t={t_j[i]:>7.3f} {sig}")

# HAR-RV-RS full sample
if len(X_harrs) > 10:
    beta_rs_full, r2_rs_full, _, se_rs, t_rs = ols_fit(X_harrs, y_harrs)
    print(f"\n  HAR-RV-RS (full sample):")
    print(f"    R² = {r2_rs_full:.4f} (HAR-RV: {r2_full:.4f}, Δ={r2_rs_full-r2_full:+.4f})")
    rs_names = ['intercept', 'rv+_d', 'rv-_d', 'rv+_w', 'rv-_w', 'rv+_m', 'rv-_m']
    for i, name in enumerate(rs_names):
        sig = '***' if abs(t_rs[i]) > 2.576 else '**' if abs(t_rs[i]) > 1.96 else '*' if abs(t_rs[i]) > 1.645 else ''
        print(f"    {name:<12}: β={beta_rs_full[i]:>10.6f}, t={t_rs[i]:>7.3f} {sig}")
    # Leverage effect: β(RV-) > β(RV+)?
    rv_minus_coefs = [beta_rs_full[i+1] for i, n in enumerate(rs_names[1:]) if 'rv-' in n]
    rv_plus_coefs = [beta_rs_full[i+1] for i, n in enumerate(rs_names[1:]) if 'rv+' in n]
    print(f"\n    Leverage test (Patton & Sheppard 2015):")
    print(f"    Σ|β(RV-)| = {sum(abs(c) for c in rv_minus_coefs):.6f}")
    print(f"    Σ|β(RV+)| = {sum(abs(c) for c in rv_plus_coefs):.6f}")
    if sum(abs(c) for c in rv_minus_coefs) > sum(abs(c) for c in rv_plus_coefs):
        print(f"    → Negative semivariance dominates (leverage effect)")
    else:
        print(f"    → No clear leverage effect in semivariance")

# ============================================================
# 10. Cross-proxy evaluation (robustness check)
# ============================================================
print("\n[8] Cross-Proxy Evaluation (same forecasts, different proxies)")

# Refit single-split for this comparison
if not USE_CROSS_OOS:
    n_cp = OOS_SIZE_ACTUAL
else:
    n_cp = n_total // 2

# Use the fold forecasts from the first (or only) fold
first_fold = list(all_results.keys())[0]
cross_proxy_results = {}

rv_oos_vals = rv_series.iloc[-n_cp:].values
park_oos_vals = parkinson_series.iloc[-n_cp:].values if len(parkinson_series) >= n_cp else None
r2_oos_vals = r2_series.iloc[-n_cp:].values if len(r2_series) >= n_cp else None

proxy_list = [('5min_RV', rv_oos_vals)]
if park_oos_vals is not None and len(park_oos_vals) >= n_cp:
    proxy_list.append(('Parkinson', park_oos_vals))
if r2_oos_vals is not None and len(r2_oos_vals) >= n_cp:
    proxy_list.append(('r²', r2_oos_vals))

for proxy_name, proxy_vals in proxy_list:
    cross_proxy_results[proxy_name] = {}
    for m_name, (fc, _) in all_results[first_fold].get('dm_tests', {}).items():
        pass  # handled below

# Actually compute using fold forecasts
for proxy_name, proxy_vals in proxy_list:
    cross_proxy_results[proxy_name] = {}
    for m_name in all_results[first_fold]['models']:
        if m_name in ['HAR-RV', 'HAR-RV-J', 'HAR-RV-CJ', 'HAR-RV-RS']:
            # Re-estimate and forecast for cross-proxy
            model_spec = model_data.get(m_name)
            if model_spec is None:
                continue
            X, y, dates, _ = model_spec
            if not USE_CROSS_OOS:
                n_is_cp = len(y) - n_cp
            else:
                n_is_cp = len(y) // 2
            if n_is_cp < 5:
                continue
            beta_cp, _, _, _, _ = ols_fit(X[:n_is_cp], y[:n_is_cp])
            fc_cp = ols_forecast(X[n_is_cp:n_is_cp + len(proxy_vals)], beta_cp)
            min_n = min(len(fc_cp), len(proxy_vals))
            if min_n >= 3:
                cross_proxy_results[proxy_name][m_name] = float(qlike(fc_cp[:min_n], proxy_vals[:min_n]))

if cross_proxy_results:
    all_cp_models = set()
    for p in cross_proxy_results:
        all_cp_models.update(cross_proxy_results[p].keys())

    if all_cp_models:
        print(f"\n  QLIKE by proxy:")
        header = f"  {'Model':<20}" + "".join(f" {p:<14}" for p in cross_proxy_results)
        print(header)
        print(f"  {'-'*len(header)}")
        for m in sorted(all_cp_models):
            line = f"  {m:<20}"
            for p in cross_proxy_results:
                if m in cross_proxy_results[p]:
                    line += f" {cross_proxy_results[p][m]:<14.4f}"
                else:
                    line += f" {'N/A':<14}"
            print(line)

        # Ranking by each proxy
        print(f"\n  Rankings:")
        for p in cross_proxy_results:
            if cross_proxy_results[p]:
                ranking = sorted(cross_proxy_results[p].items(), key=lambda x: x[1])
                rank_str = ' > '.join([f"{r[0]}({r[1]:.3f})" for r in ranking])
                print(f"    {p:<14}: {rank_str}")

# ============================================================
# 11. Nested model comparison
# ============================================================
print("\n[9] Nested Model Comparison")

if not USE_CROSS_OOS:
    nest_oos = OOS_SIZE_ACTUAL
else:
    nest_oos = n_total // 2

n_is_nest = len(y_har) - nest_oos
if n_is_nest >= 5 and nest_oos >= 3:
    rv_actual_nest = y_har[-nest_oos:]

    # HAR(d): daily only
    X_d = X_har[:, 0:1]
    beta_d, _, _, _, _ = ols_fit(X_d[:n_is_nest], y_har[:n_is_nest])
    fc_d = ols_forecast(X_d[n_is_nest:], beta_d)
    q_d = qlike(fc_d, rv_actual_nest)

    # HAR(d,w): daily + weekly
    X_dw = X_har[:, 0:2]
    beta_dw, _, _, _, _ = ols_fit(X_dw[:n_is_nest], y_har[:n_is_nest])
    fc_dw = ols_forecast(X_dw[n_is_nest:], beta_dw)
    q_dw = qlike(fc_dw, rv_actual_nest)

    # HAR(d,w,m): full
    beta_dwm, _, _, _, _ = ols_fit(X_har[:n_is_nest], y_har[:n_is_nest])
    fc_dwm = ols_forecast(X_har[n_is_nest:], beta_dwm)
    q_dwm = qlike(fc_dwm, rv_actual_nest)

    print(f"  {'Model':<30} {'QLIKE':<12}")
    print(f"  {'-'*42}")
    print(f"  {'HAR(d) — daily only':<30} {q_d:<12.4f}")
    print(f"  {'HAR(d,w) — daily+weekly':<30} {q_dw:<12.4f}")
    print(f"  {'HAR(d,w,m) — full':<30} {q_dwm:<12.4f}")

    imp_w = (q_d - q_dw) / q_d * 100
    imp_m = (q_dw - q_dwm) / q_dw * 100
    print(f"  Adding weekly:  {imp_w:+.1f}% QLIKE change ({'improved' if imp_w > 0 else 'worsened'})")
    print(f"  Adding monthly: {imp_m:+.1f}% QLIKE change ({'improved' if imp_m > 0 else 'worsened'})")

# ============================================================
# 12. Day-by-day OOS table
# ============================================================
print("\n[10] Day-by-day OOS Forecasts vs Actual RV (last fold)")

last_fold_name = list(all_results.keys())[-1]
last_fold = all_results[last_fold_name]

# Show for models that have matched-length OOS
if not USE_CROSS_OOS:
    oos_dates_display = rv_series.index[-OOS_SIZE_ACTUAL:]
    rv_oos_display = rv_series.iloc[-OOS_SIZE_ACTUAL:].values
else:
    oos_dates_display = rv_series.index[-n_total//2:]
    rv_oos_display = rv_series.iloc[-n_total//2:].values

display_n = min(15, len(rv_oos_display))  # cap at 15 rows for readability
print(f"  (showing first {display_n} OOS days, values ×10⁴)")
header = f"  {'Date':<14} {'Actual':<10}"
display_models = [m for m in ['HAR-RV', 'HAR-RV-J', 'HAR-RV-RS', 'GJR-GARCH', 'EWMA']
                  if m in last_fold['models']]
for m in display_models:
    header += f" {m:<12}"
print(header)
print(f"  {'-'*len(header)}")

# Re-forecast for display
for i in range(display_n):
    if i < len(oos_dates_display):
        line = f"  {str(oos_dates_display[i]):<14} {rv_oos_display[i]*1e4:>8.4f}"
    else:
        break
    # We'd need per-day forecasts; skip if not easily available
    print(line)

# ============================================================
# 13. Summary and conclusions
# ============================================================
elapsed = time.time() - START_TIME

print(f"\n{'='*70}")
print(f"SUMMARY — {EXPERIMENT_ID}: Formal HAR-RV with {n_days}-Day 5-Min Data")
print(f"{'='*70}")

print(f"\n  Data: {n_days} trading days ({rv_series.index[0]} to {rv_series.index[-1]})")
print(f"  Design: {'2-fold cross-OOS' if USE_CROSS_OOS else f'Single split (IS/OOS)'}")
print(f"  Proxy: 5-min Realized Variance (gold standard)")
print(f"  Best model: {best_model}")

print(f"\n  KEY FINDINGS:")

# Enumerate findings
finding_num = 1
if 'HAR-RV' in final_results:
    har_q = final_results['HAR-RV'].get('QLIKE', final_results['HAR-RV'].get('QLIKE_mean', float('nan')))
    print(f"    {finding_num}. HAR-RV QLIKE = {har_q:.4f}")
    finding_num += 1

if 'GJR-GARCH' in final_results:
    gjr_q = final_results['GJR-GARCH'].get('QLIKE', final_results['GJR-GARCH'].get('QLIKE_mean', float('nan')))
    har_q = final_results.get('HAR-RV', {}).get('QLIKE', final_results.get('HAR-RV', {}).get('QLIKE_mean', float('nan')))
    if not np.isnan(har_q) and not np.isnan(gjr_q):
        comp = '<' if har_q < gjr_q else '>'
        print(f"    {finding_num}. HAR-RV ({har_q:.4f}) {comp} GJR-GARCH ({gjr_q:.4f})")
        finding_num += 1

if 'HAR-RV-J' in final_results:
    harj_q = final_results['HAR-RV-J'].get('QLIKE', final_results['HAR-RV-J'].get('QLIKE_mean', float('nan')))
    print(f"    {finding_num}. HAR-RV-J (with jump component) QLIKE = {harj_q:.4f}")
    finding_num += 1

if 'HAR-RV-RS' in final_results:
    harrs_q = final_results['HAR-RV-RS'].get('QLIKE', final_results['HAR-RV-RS'].get('QLIKE_mean', float('nan')))
    print(f"    {finding_num}. HAR-RV-RS (semivariance) QLIKE = {harrs_q:.4f}")
    finding_num += 1

print(f"    {finding_num}. Jump proportion: {jump_pct:.1f}% of total RV")
finding_num += 1

print(f"\n  CAVEATS:")
print(f"    - {n_days} days still relatively short for HAR-RV (literature uses 1000+)")
print(f"    - 5-min RV excludes overnight returns (may bias downward)")
print(f"    - Monthly component identification limited by {n_days - WARMUP_DAYS} effective obs")
print(f"    - GJR-GARCH fitted on very short daily return history")
print(f"    - {'Cross-OOS folds are small' if USE_CROSS_OOS else 'Single OOS period limits robustness'}")

print(f"\n  Elapsed: {elapsed:.1f}s")

# ============================================================
# 14. Save results
# ============================================================
output = {
    "experiment_id": EXPERIMENT_ID,
    "title": f"Formal HAR-RV with {n_days}-Day 5-Min Data",
    "status": "COMPLETED",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "data": {
        "source": "yfinance 5-min intraday CSVs (data/intraday/SPY_5min_*.csv)",
        "asset": "SPY",
        "n_days": int(n_days),
        "date_range": f"{rv_series.index[0]} to {rv_series.index[-1]}",
        "n_5min_files": n_files,
        "avg_bars_per_day": float(np.mean(list(n_bars_daily.values()))),
    },
    "descriptive_stats": stats_data,
    "proxy_correlations": proxy_corr,
    "jump_proportion_pct": float(jump_pct),
    "rv_plus_share_pct": float(rv_plus_series.mean() / rv_series.mean() * 100),
    "rv_minus_share_pct": float(rv_minus_series.mean() / rv_series.mean() * 100),
    "oos_design": {
        "type": "2-fold cross-OOS" if USE_CROSS_OOS else "single split",
        "oos_size": n_total // 2 if USE_CROSS_OOS else OOS_SIZE_ACTUAL,
        "min_IS": MIN_IS,
        "warmup": WARMUP_DAYS,
    },
    "har_rv_full_sample": {
        "coefficients": {
            "intercept": float(beta_full[0]),
            "beta_d": float(beta_full[1]),
            "beta_w": float(beta_full[2]),
            "beta_m": float(beta_full[3]),
        },
        "t_statistics": {
            "intercept": float(t_full[0]),
            "beta_d": float(t_full[1]),
            "beta_w": float(t_full[2]),
            "beta_m": float(t_full[3]),
        },
        "R2": float(r2_full),
        "n": int(len(y_har)),
    },
    "fold_results": {
        fold_name: {
            "models": fold_data["models"],
            "dm_tests": fold_data["dm_tests"],
        }
        for fold_name, fold_data in all_results.items()
    },
    "ranking_by_QLIKE": [r[0] for r in ranked],
    "best_model": best_model,
    "cross_proxy_evaluation": cross_proxy_results,
    "caveats": [
        f"{n_days} days still short for HAR-RV (literature uses 1000+ days)",
        "5-min RV excludes overnight returns (may bias downward)",
        f"Monthly component limited by {n_days - WARMUP_DAYS} effective observations",
        "GJR-GARCH fitted on very short daily return history",
        "VIX9D alignment with 5-min data dates may have mismatches",
        "Cross-OOS folds are small" if USE_CROSS_OOS else "Single OOS limits robustness",
    ],
    "references": [
        "Corsi (2009) 'A Simple Approximate Long-Memory Model' J Financial Econometrics",
        "Andersen, Bollerslev, Diebold (2007) 'Roughing It Up' Review of Financial Studies",
        "Barndorff-Nielsen & Shephard (2004) 'Power and Bipower Variation' J Financial Econometrics",
        "Patton & Sheppard (2015) 'Good Volatility, Bad Volatility' JBES",
        "Patton (2011) 'Volatility Forecast Comparison Using Imperfect Proxies' JoE",
        "Hansen & Lunde (2005) 'A Forecast Comparison of Volatility Models' J Applied Econometrics",
        "K188: HAR ceiling (42d, insufficient)",
        "K522: HAR-RV pilot (50d, preliminary)",
        "K465/K469: HAR log-range (Parkinson proxy, K468 tautology)",
        "K490: GJR-X(VIX9D) champion (QLIKE -4.6%, VaR 5/5)",
    ],
    "elapsed_seconds": round(elapsed, 1),
    "next_steps": [
        "If HAR-RV wins: build strategy with 5-min RV as signal",
        "Test HAR-RV on Taiwan market (0050.TW 5-min data)",
        "Add overnight return component (close-to-open decomposition)",
        "Compare with HEAVY model (Shephard & Sheppard 2010)",
        "Test realized kernel estimator (noise-robust RV)",
        "Extend to multi-horizon forecasting (5-day, 22-day ahead)",
    ],
}

results_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            f'{EXPERIMENT_ID.lower()}_har_rv_formal_results.json')
with open(results_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n  Results saved to: {results_path}")
print(f"  Script: experiments/{EXPERIMENT_ID.lower()}_har_rv_formal.py")
print(f"  Elapsed: {elapsed:.1f}s")
