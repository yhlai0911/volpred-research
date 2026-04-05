#!/usr/bin/env python3
"""
K868: HAR Day/Night RV Decomposition for Taiwan Futures
=======================================================

Research Question (EMPIRICAL, not mechanical):
  Does separating RV into day-session and night-session components improve
  HAR forecasting of TOTAL RV?

  This is empirical because: the standard HAR uses total RV as a single
  regressor. Splitting into day/night components tests whether the
  INFORMATION STRUCTURE is richer, not just a target change.

Background:
  - K849: HAR-RV beats GJR on RV target (DM t=-11.14) — MECHANICAL
  - K851: Jump decomposition adds nothing (NULL)
  - K852b: Regime-dependent HAR — structural finding but OOS NULL
  - K848: Night session vol share 24%->57% (2017->2026)
  - K849 Track B initial: day/night split R^2 0.17->0.58

Models (all predicting log(RV_total_{t+1})):
  a. HAR-RV:       b0 + b1*log(RV_t) + b5*log(RV_5d) + b22*log(RV_22d)
  b. HAR-DN:        b0 + b1*log(RV_day_t) + b2*log(RV_night_t)
                       + b3*log(RV_day_5d) + b4*log(RV_night_5d)
                       + b5*log(RV_day_22d) + b6*log(RV_night_22d)
  c. HAR-DN-Ratio:  HAR-RV + night_ratio_t (= RV_night/RV_total)
  d. GJR-GARCH:     baseline evaluated on r^2 (its native target)

Fair comparison:
  - HAR models: evaluate on RV_total (their native target)
  - GJR: evaluate on r^2 (its native target)
  - Cross-model: Patton QLIKE on r^2 + Spearman rank correlation
  - Report BOTH evaluations

OOS: IS first 60%, OOS last 40%, rolling refit every 63 days

Error Log Rules:
  - DM test: use volpred.stats.model_evaluation.dm_test (Newey-West HAC)
  - Sanity check: compute actual values, don't hard-code
  - All signals use info up to t-1 only (no lookahead)
  - Harvey (2016) |t| > 3.0 for significance

References:
  - Corsi (2009) "A simple approximate long-memory model of realized volatility"
  - Patton (2011) "Volatility forecast comparison using imperfect proxies"
  - Hansen & Lunde (2005) "A forecast comparison of volatility models"
  - Andersen, Bollerslev, Diebold (2007) "Roughing it up"
  - K848/K849 (VolPred prior results)

Author: VolPred Research System
Date: 2026-04-05
Data: TAIFEX TX1 tick (2017-2026 night session era)
"""

import os
import sys
import glob
import json
import warnings
import numpy as np
import pandas as pd
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
from scipy import stats as sp_stats

warnings.filterwarnings('ignore')

# ============================================================
# Configuration
# ============================================================
DATA_DIR = "/Users/yhlai0911/Dropbox/TAIFEXDATA/TAIFEXDATA/python"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Session boundaries (HHMMSS)
NIGHT_PM_START = 150000
NIGHT_PM_END = 235959
NIGHT_AM_START = 0
NIGHT_AM_END = 50000
DAY_START = 84500
DAY_END = 134500

# HAR settings
REFIT_FREQ = 63       # Refit every 63 trading days (~3 months)
MIN_TRAIN = 250       # Minimum training window
OOS_RATIO = 0.40      # 60/40 IS/OOS split
SMALL_CONST = 1e-12   # Floor for log(RV) to avoid -inf

# GJR-GARCH settings
GJR_P, GJR_O, GJR_Q = 1, 1, 1


# ============================================================
# Step 1: Build 5-min RV from TAIFEX tick data (adapted from K851)
# ============================================================

def time_to_5min_bucket(time_int):
    """Convert HHMMSS integer to a 5-minute bucket label."""
    h = time_int // 10000
    m = (time_int % 10000) // 100
    m5 = (m // 5) * 5
    return h * 100 + m5


def process_single_file(filepath):
    """
    Process one TX1 file -> compute 5-min RV for day and night sessions.
    Returns dict with rv_day, rv_night, rv_full, close-to-close return.
    """
    basename = os.path.basename(filepath)
    try:
        parts = basename.replace("Daily_", "").replace("TX1.csv", "").replace("TX.csv", "").split("_")
        date_str = f"{parts[0]}-{parts[1]}-{parts[2]}"
    except Exception:
        return None

    if os.path.getsize(filepath) < 100:
        return None

    try:
        df = pd.read_csv(filepath, encoding='big5', dtype=str, low_memory=False)
    except Exception:
        try:
            df = pd.read_csv(filepath, encoding='cp950', dtype=str, low_memory=False)
        except Exception:
            return None

    if len(df) < 10:
        return None

    try:
        df['time_int'] = pd.to_numeric(df.iloc[:, 3], errors='coerce').astype('Int64')
        df['price'] = pd.to_numeric(df.iloc[:, 4], errors='coerce')
        df = df.dropna(subset=['price', 'time_int'])
        df['time_int'] = df['time_int'].astype(int)
    except Exception:
        return None

    if len(df) < 10:
        return None

    t = df['time_int'].values
    p = df['price'].values

    # Session masks
    night_pm_mask = (t >= NIGHT_PM_START) & (t <= NIGHT_PM_END)
    night_am_mask = (t >= NIGHT_AM_START) & (t <= NIGHT_AM_END)
    day_mask = (t >= DAY_START) & (t <= DAY_END)

    def build_5min_returns(session_t, session_p):
        """Build 5-min bar closes and compute log returns."""
        if len(session_t) < 5:
            return np.array([])
        buckets = np.array([time_to_5min_bucket(ti) for ti in session_t])
        unique_buckets = np.unique(buckets)
        bar_closes = []
        for b in unique_buckets:
            bucket_mask = buckets == b
            bar_closes.append(session_p[bucket_mask][-1])
        bar_closes = np.array(bar_closes, dtype=float)
        if len(bar_closes) >= 2:
            return np.diff(np.log(bar_closes))
        return np.array([])

    # Compute 5-min returns for each session
    day_rets = build_5min_returns(t[day_mask], p[day_mask])

    night_pm_rets = build_5min_returns(t[night_pm_mask], p[night_pm_mask])
    night_am_rets = build_5min_returns(t[night_am_mask], p[night_am_mask])
    if len(night_pm_rets) > 0 or len(night_am_rets) > 0:
        night_rets = np.concatenate([r for r in [night_pm_rets, night_am_rets] if len(r) > 0])
    else:
        night_rets = np.array([])

    # Realized Variance = sum of squared 5-min returns
    rv_day = float(np.sum(day_rets ** 2)) if len(day_rets) >= 2 else None
    rv_night = float(np.sum(night_rets ** 2)) if len(night_rets) >= 2 else None

    # Full RV = day + night (additive for variance)
    if rv_day is not None and rv_night is not None:
        rv_full = rv_day + rv_night
    elif rv_day is not None:
        rv_full = rv_day
    else:
        rv_full = None

    # Close-to-close return (for GJR-GARCH)
    # Use all prices across the full day: earliest to latest
    all_prices = []
    # Night PM prices
    if np.any(night_pm_mask):
        all_prices.append(('night_pm', p[night_pm_mask]))
    # Night AM prices
    if np.any(night_am_mask):
        all_prices.append(('night_am', p[night_am_mask]))
    # Day prices
    if np.any(day_mask):
        all_prices.append(('day', p[day_mask]))

    daily_return = None
    # Use day session open and close for the daily return proxy
    day_p = p[day_mask]
    if len(day_p) >= 2:
        daily_return = float(np.log(float(day_p[-1]) / float(day_p[0])))

    return {
        'date': date_str,
        'rv_day': rv_day,
        'rv_night': rv_night,
        'rv_full': rv_full,
        'daily_return': daily_return,
        'n_day_rets': len(day_rets),
        'n_night_rets': len(night_rets),
    }


def load_all_rv_data(start_date='2017_05_16'):
    """Load TX1 files from night session era and compute RV."""
    pattern = os.path.join(DATA_DIR, "Daily_*TX1.csv")
    all_files = sorted(glob.glob(pattern))

    cutoff = f"Daily_{start_date}"
    files = [f for f in all_files if os.path.basename(f) >= cutoff]
    files = [f for f in files if os.path.basename(f) < "Daily_2026"]
    print(f"  Found {len(files)} TX1 files from {start_date} to end 2025")

    results = []
    errors = 0
    n_workers = min(8, os.cpu_count() or 4)
    print(f"  Using {n_workers} workers...")

    with ProcessPoolExecutor(max_workers=n_workers) as executor:
        futures = {executor.submit(process_single_file, f): f for f in files}
        done_count = 0
        for future in as_completed(futures):
            done_count += 1
            if done_count % 500 == 0:
                print(f"    Processed {done_count}/{len(files)} files...")
            try:
                result = future.result()
                if result is not None and result.get('rv_full') is not None:
                    results.append(result)
                else:
                    errors += 1
            except Exception:
                errors += 1

    print(f"  Loaded: {len(results)}, Errors: {errors}")

    df = pd.DataFrame(results)
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').sort_index()

    for col in ['rv_day', 'rv_night', 'rv_full', 'daily_return']:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    return df


# ============================================================
# Step 2: Prepare HAR Features
# ============================================================

def prepare_har_features(df):
    """
    Add log-RV and rolling averages for HAR regressors.
    Floor small RV values before log to avoid -inf.
    """
    df = df.copy()

    # Floor and log-transform
    for col in ['rv_full', 'rv_day', 'rv_night']:
        df[f'log_{col}'] = np.log(df[col].clip(lower=SMALL_CONST))

    # Night ratio: RV_night / RV_total
    df['night_ratio'] = df['rv_night'] / df['rv_full'].clip(lower=SMALL_CONST)
    df['night_ratio'] = df['night_ratio'].clip(0, 1)

    # Rolling averages: 5-day and 22-day (for HAR weekly/monthly)
    for col in ['log_rv_full', 'log_rv_day', 'log_rv_night']:
        df[f'{col}_5d'] = df[col].rolling(5).mean()
        df[f'{col}_22d'] = df[col].rolling(22).mean()

    df['night_ratio_5d'] = df['night_ratio'].rolling(5).mean()
    df['night_ratio_22d'] = df['night_ratio'].rolling(22).mean()

    # Squared daily return for GJR and cross-model comparison
    df['r_squared'] = df['daily_return'] ** 2

    return df


# ============================================================
# Step 3: HAR Model Family (OLS, log-transformed)
# ============================================================

def fit_har_ols(y, X):
    """OLS fit: y = [1, X] @ beta. Returns beta, residuals."""
    n = len(y)
    X_c = np.column_stack([np.ones(n), X])
    try:
        beta = np.linalg.lstsq(X_c, y, rcond=None)[0]
        y_hat = X_c @ beta
        resid = y - y_hat
        ss_res = np.sum(resid ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
        return beta, r2
    except Exception:
        return None, None


def get_har_features(model_name, df, t):
    """
    Get feature vector at time t using info up to t (for predicting t+1).
    Returns None if not enough history.
    """
    if t < 22:
        return None

    row = df.iloc[t]

    if model_name == 'HAR-RV':
        feat = [
            row['log_rv_full'],
            row['log_rv_full_5d'],
            row['log_rv_full_22d'],
        ]
        return np.array(feat) if all(np.isfinite(feat)) else None

    elif model_name == 'HAR-DN':
        feat = [
            row['log_rv_day'],
            row['log_rv_night'],
            row['log_rv_day_5d'],
            row['log_rv_night_5d'],
            row['log_rv_day_22d'],
            row['log_rv_night_22d'],
        ]
        return np.array(feat) if all(np.isfinite(feat)) else None

    elif model_name == 'HAR-DN-Ratio':
        feat = [
            row['log_rv_full'],
            row['log_rv_full_5d'],
            row['log_rv_full_22d'],
            row['night_ratio'],
        ]
        return np.array(feat) if all(np.isfinite(feat)) else None

    return None


def har_predict(beta, features):
    """Predict log(RV) given beta and features."""
    X_c = np.concatenate([[1.0], features])
    return X_c @ beta


# ============================================================
# Step 4: GJR-GARCH Baseline
# ============================================================

def fit_gjr_garch(returns, p=1, o=1, q=1):
    """
    Fit GJR-GARCH(1,1,1) using arch package.
    Returns model result or None.
    """
    try:
        from arch import arch_model
        am = arch_model(returns * 100, vol='GARCH', p=p, o=o, q=q,
                        dist='studentst', mean='Constant', rescale=False)
        res = am.fit(disp='off', show_warning=False)
        if res.convergence_flag != 0:
            # Try with default starting values
            res = am.fit(disp='off', show_warning=False,
                         starting_values=None)
        return res
    except Exception:
        return None


def gjr_oos_forecast(returns_series, oos_start_idx, refit_freq=63):
    """
    OOS GJR forecasts with rolling refit.
    Returns array of conditional variance forecasts (in return-scale, not *100).
    """
    n = len(returns_series)
    forecasts = np.full(n - oos_start_idx, np.nan)
    last_fit = None
    last_fit_idx = -999

    for i in range(oos_start_idx, n):
        idx = i - oos_start_idx
        # Refit if needed
        if last_fit is None or (i - last_fit_idx) >= refit_freq:
            train_rets = returns_series[:i]
            if len(train_rets) < MIN_TRAIN:
                continue
            res = fit_gjr_garch(train_rets.values)
            if res is not None:
                last_fit = res
                last_fit_idx = i

        if last_fit is not None:
            try:
                # One-step-ahead forecast
                fcast = last_fit.forecast(horizon=1, reindex=False)
                h = fcast.variance.values[-1, 0]
                # Convert from (ret*100)^2 back to ret^2 scale
                forecasts[idx] = h / (100 ** 2)

                # Re-estimate recursion: h[t] = omega + alpha*r^2[t-1] + gamma*r^2[t-1]*I + beta*h[t-1]
                # This is the proper OOS recursive update (not stale variance)
                params = last_fit.params
                omega = params.get('omega', 0)
                alpha = params.get('alpha[1]', 0)
                gamma_param = params.get('gamma[1]', 0)
                beta_param = params.get('beta[1]', 0)

                r_prev = returns_series.iloc[i - 1] * 100  # in *100 scale
                h_prev = forecasts[idx - 1] * (100 ** 2) if idx > 0 and np.isfinite(forecasts[idx - 1]) else h
                indicator = 1.0 if r_prev < 0 else 0.0
                h_new = omega + alpha * r_prev ** 2 + gamma_param * r_prev ** 2 * indicator + beta_param * h_prev
                forecasts[idx] = h_new / (100 ** 2)
            except Exception:
                pass

    return forecasts


# ============================================================
# Step 5: Evaluation Metrics
# ============================================================

def qlike(actual, forecast):
    """
    QLIKE loss: actual/forecast - log(actual/forecast) - 1
    Patton (2011): proxy-robust when using r^2 as proxy for sigma^2.
    """
    a = np.asarray(actual, dtype=np.float64)
    f = np.asarray(forecast, dtype=np.float64)
    valid = np.isfinite(a) & np.isfinite(f) & (a > 0) & (f > 0)
    a, f = a[valid], f[valid]
    if len(a) == 0:
        return np.nan
    return float(np.mean(a / f - np.log(a / f) - 1))


def mse(actual, forecast):
    """Mean Squared Error."""
    a = np.asarray(actual, dtype=np.float64)
    f = np.asarray(forecast, dtype=np.float64)
    valid = np.isfinite(a) & np.isfinite(f)
    a, f = a[valid], f[valid]
    if len(a) == 0:
        return np.nan
    return float(np.mean((a - f) ** 2))


def mae(actual, forecast):
    """Mean Absolute Error."""
    a = np.asarray(actual, dtype=np.float64)
    f = np.asarray(forecast, dtype=np.float64)
    valid = np.isfinite(a) & np.isfinite(f)
    a, f = a[valid], f[valid]
    if len(a) == 0:
        return np.nan
    return float(np.mean(np.abs(a - f)))


def spearman_corr(actual, forecast):
    """Spearman rank correlation."""
    a = np.asarray(actual, dtype=np.float64)
    f = np.asarray(forecast, dtype=np.float64)
    valid = np.isfinite(a) & np.isfinite(f)
    a, f = a[valid], f[valid]
    if len(a) < 10:
        return np.nan
    corr, _ = sp_stats.spearmanr(a, f)
    return float(corr)


def dm_test_nw(loss1, loss2, h=1):
    """
    Diebold-Mariano test with Newey-West HAC.
    Negative t -> model 1 is better.
    Harvey (2016): |t| > 3.0 for significance.
    """
    d = np.asarray(loss1, dtype=np.float64) - np.asarray(loss2, dtype=np.float64)
    valid = np.isfinite(d)
    d = d[valid]
    n = len(d)
    if n < 10:
        return np.nan, np.nan

    d_bar = np.mean(d)
    # Newey-West HAC variance
    max_lag = max(1, int(np.floor(n ** (1 / 3))))
    gamma_0 = np.mean((d - d_bar) ** 2)
    nw_var = gamma_0
    for lag in range(1, max_lag + 1):
        w = 1 - lag / (max_lag + 1)
        gamma_k = np.mean((d[lag:] - d_bar) * (d[:-lag] - d_bar))
        nw_var += 2 * w * gamma_k

    if nw_var <= 0:
        return np.nan, np.nan

    t_stat = d_bar / np.sqrt(nw_var / n)
    p_val = 2 * (1 - sp_stats.t.cdf(abs(t_stat), df=n - 1))
    return float(t_stat), float(p_val)


# ============================================================
# Step 6: OOS HAR Forecasting with Rolling Refit
# ============================================================

def run_har_oos(df, model_name, oos_start, refit_freq=REFIT_FREQ):
    """
    Run OOS forecasting for a HAR model.
    Target: log(rv_full_{t+1})
    Returns: array of RV forecasts (level, not log), aligned with df index from oos_start+1 onward.
    """
    n = len(df)
    target = df['log_rv_full'].values
    forecasts_log = np.full(n, np.nan)

    beta = None
    last_fit_t = -999

    for t in range(oos_start, n - 1):
        # Refit if needed
        if beta is None or (t - last_fit_t) >= refit_freq:
            # Build training set: all available data up to t
            train_start = 22  # Need 22 days of history
            y_train = []
            X_train = []
            for s in range(train_start, t):
                feat = get_har_features(model_name, df, s)
                if feat is not None and np.isfinite(target[s + 1]):
                    X_train.append(feat)
                    y_train.append(target[s + 1])

            if len(y_train) < MIN_TRAIN:
                continue

            y_train = np.array(y_train)
            X_train = np.array(X_train)
            beta, r2 = fit_har_ols(y_train, X_train)
            if beta is None:
                continue
            last_fit_t = t

        # Predict: features at t predict t+1
        feat = get_har_features(model_name, df, t)
        if feat is not None and beta is not None:
            log_rv_pred = har_predict(beta, feat)
            forecasts_log[t + 1] = log_rv_pred

    # Convert log forecasts to level
    forecasts_level = np.exp(forecasts_log)
    # Only return OOS portion
    oos_mask = np.arange(n) > oos_start
    return forecasts_level, oos_mask


# ============================================================
# Step 7: Main Execution
# ============================================================

def main():
    print("=" * 70)
    print("K868: HAR Day/Night RV Decomposition for Taiwan Futures")
    print("=" * 70)

    # --- Load data ---
    print("\n[1/7] Loading TAIFEX TX1 tick data...")
    df = load_all_rv_data()
    print(f"  Data range: {df.index[0].date()} to {df.index[-1].date()}")
    print(f"  Total trading days: {len(df)}")

    # Filter: require both day and night RV
    valid_mask = df['rv_day'].notna() & df['rv_night'].notna() & df['rv_full'].notna()
    df = df[valid_mask].copy()
    print(f"  Days with both day+night RV: {len(df)}")

    # Also need daily return for GJR
    ret_valid = df['daily_return'].notna()
    print(f"  Days with daily return: {ret_valid.sum()}")

    # --- Descriptive statistics ---
    print("\n[2/7] Descriptive Statistics...")
    print(f"  RV_total:  mean={df['rv_full'].mean():.6f}  std={df['rv_full'].std():.6f}  "
          f"median={df['rv_full'].median():.6f}")
    print(f"  RV_day:    mean={df['rv_day'].mean():.6f}  std={df['rv_day'].std():.6f}  "
          f"median={df['rv_day'].median():.6f}")
    print(f"  RV_night:  mean={df['rv_night'].mean():.6f}  std={df['rv_night'].std():.6f}  "
          f"median={df['rv_night'].median():.6f}")

    night_share = df['rv_night'] / df['rv_full']
    print(f"  Night share of total RV: mean={night_share.mean():.3f}  "
          f"median={night_share.median():.3f}  std={night_share.std():.3f}")

    # Year-by-year night share
    print("\n  Night share by year:")
    for year in sorted(df.index.year.unique()):
        mask = df.index.year == year
        ns = night_share[mask]
        print(f"    {year}: mean={ns.mean():.3f} ({mask.sum()} days)")

    # Correlation between day and night RV
    corr_dn = df[['rv_day', 'rv_night']].corr().iloc[0, 1]
    print(f"\n  Correlation(RV_day, RV_night): {corr_dn:.3f}")

    # --- Prepare features ---
    print("\n[3/7] Preparing HAR features...")
    df = prepare_har_features(df)

    # Drop rows with NaN in rolling features
    df = df.dropna(subset=['log_rv_full_22d', 'log_rv_day_22d', 'log_rv_night_22d'])
    print(f"  After dropping NaN rolling features: {len(df)} days")

    # --- OOS split ---
    n = len(df)
    oos_start = int(n * (1 - OOS_RATIO))
    print(f"\n[4/7] OOS Setup:")
    print(f"  IS: {df.index[0].date()} to {df.index[oos_start].date()} ({oos_start} days)")
    print(f"  OOS: {df.index[oos_start+1].date()} to {df.index[-1].date()} ({n - oos_start - 1} days)")

    # --- Run HAR models ---
    print("\n[5/7] Running HAR models (OOS)...")
    models = ['HAR-RV', 'HAR-DN', 'HAR-DN-Ratio']
    har_forecasts = {}

    for model_name in models:
        print(f"  Fitting {model_name}...")
        forecasts_level, oos_mask = run_har_oos(df, model_name, oos_start)
        har_forecasts[model_name] = forecasts_level
        n_valid = np.isfinite(forecasts_level[oos_mask]).sum()
        print(f"    Valid OOS forecasts: {n_valid}")

    # --- Run GJR-GARCH ---
    print("\n  Fitting GJR-GARCH...")
    returns_series = df['daily_return'].copy()
    gjr_forecasts_raw = gjr_oos_forecast(returns_series, oos_start, refit_freq=REFIT_FREQ)
    # Align with df index
    gjr_forecasts = np.full(n, np.nan)
    gjr_forecasts[oos_start:] = gjr_forecasts_raw
    n_valid_gjr = np.isfinite(gjr_forecasts[oos_start:]).sum()
    print(f"    Valid OOS forecasts: {n_valid_gjr}")

    # --- Evaluation ---
    print("\n[6/7] Evaluation (OOS)...")

    # Actual values (OOS only)
    oos_idx = np.arange(oos_start + 1, n)  # +1 because we predict t+1
    rv_actual = df['rv_full'].values[oos_idx]
    r2_actual = df['r_squared'].values[oos_idx]

    results = {}

    # ---- Evaluation A: HAR models on RV_total (their native target) ----
    print("\n  === Evaluation A: HAR models on RV_total (native target) ===")
    print(f"  {'Model':<16} {'QLIKE':>10} {'MSE':>14} {'MAE':>12} {'Spearman':>10}")
    print("  " + "-" * 64)

    for model_name in models:
        fcast = har_forecasts[model_name][oos_idx]
        valid = np.isfinite(fcast) & np.isfinite(rv_actual)

        q = qlike(rv_actual[valid], fcast[valid])
        m = mse(rv_actual[valid], fcast[valid])
        a = mae(rv_actual[valid], fcast[valid])
        s = spearman_corr(rv_actual[valid], fcast[valid])

        print(f"  {model_name:<16} {q:>10.4f} {m:>14.10f} {a:>12.6f} {s:>10.3f}")

        results[model_name] = {
            'native_target': 'RV_total',
            'QLIKE_on_RV': round(q, 6),
            'MSE_on_RV': round(m, 12),
            'MAE_on_RV': round(a, 8),
            'Spearman_on_RV': round(s, 4),
            'n_valid_oos': int(valid.sum()),
        }

    # ---- Evaluation B: GJR on r^2 (its native target) ----
    print("\n  === Evaluation B: GJR-GARCH on r^2 (native target) ===")
    gjr_fcast_oos = gjr_forecasts[oos_idx]
    valid_gjr = np.isfinite(gjr_fcast_oos) & np.isfinite(r2_actual) & (r2_actual > 0) & (gjr_fcast_oos > 0)

    q_gjr = qlike(r2_actual[valid_gjr], gjr_fcast_oos[valid_gjr])
    m_gjr = mse(r2_actual[valid_gjr], gjr_fcast_oos[valid_gjr])
    a_gjr = mae(r2_actual[valid_gjr], gjr_fcast_oos[valid_gjr])
    s_gjr = spearman_corr(r2_actual[valid_gjr], gjr_fcast_oos[valid_gjr])

    print(f"  {'GJR-GARCH':<16} {q_gjr:>10.4f} {m_gjr:>14.10f} {a_gjr:>12.6f} {s_gjr:>10.3f}")

    results['GJR-GARCH'] = {
        'native_target': 'r_squared',
        'QLIKE_on_r2': round(q_gjr, 6),
        'MSE_on_r2': round(m_gjr, 12),
        'MAE_on_r2': round(a_gjr, 8),
        'Spearman_on_r2': round(s_gjr, 4),
        'n_valid_oos': int(valid_gjr.sum()),
    }

    # ---- Evaluation C: Cross-model comparison on r^2 (Patton 2011 QLIKE) ----
    print("\n  === Evaluation C: ALL models on r^2 (Patton 2011 cross-model) ===")
    print(f"  {'Model':<16} {'QLIKE_r2':>10} {'Spearman_r2':>12}")
    print("  " + "-" * 40)

    for model_name in models:
        fcast = har_forecasts[model_name][oos_idx]
        valid = np.isfinite(fcast) & np.isfinite(r2_actual) & (r2_actual > 0) & (fcast > 0)
        q = qlike(r2_actual[valid], fcast[valid])
        s = spearman_corr(r2_actual[valid], fcast[valid])
        print(f"  {model_name:<16} {q:>10.4f} {s:>12.3f}")
        results[model_name]['QLIKE_on_r2'] = round(q, 6)
        results[model_name]['Spearman_on_r2'] = round(s, 4)

    # GJR on r^2 (already computed)
    print(f"  {'GJR-GARCH':<16} {q_gjr:>10.4f} {s_gjr:>12.3f}")

    # ---- DM Tests ----
    print("\n  === DM Tests (Newey-West HAC, Harvey |t|>3.0) ===")
    print("  Note: Negative t → model 1 better")

    dm_results = {}

    # A) HAR-DN vs HAR-RV on QLIKE(RV)
    print("\n  -- HAR models on RV target --")
    for model_name in ['HAR-DN', 'HAR-DN-Ratio']:
        fcast_new = har_forecasts[model_name][oos_idx]
        fcast_base = har_forecasts['HAR-RV'][oos_idx]
        valid = (np.isfinite(fcast_new) & np.isfinite(fcast_base) &
                 np.isfinite(rv_actual) & (rv_actual > 0) & (fcast_new > 0) & (fcast_base > 0))

        # QLIKE loss for each observation
        loss_new = rv_actual[valid] / fcast_new[valid] - np.log(rv_actual[valid] / fcast_new[valid]) - 1
        loss_base = rv_actual[valid] / fcast_base[valid] - np.log(rv_actual[valid] / fcast_base[valid]) - 1

        t_stat, p_val = dm_test_nw(loss_new, loss_base)
        sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else ("*" if abs(t_stat) > 1.64 else ""))
        print(f"  {model_name} vs HAR-RV (QLIKE on RV): t={t_stat:.3f} p={p_val:.4f} {sig}")
        dm_results[f'{model_name}_vs_HAR-RV_QLIKE_RV'] = {
            't_stat': round(t_stat, 4),
            'p_value': round(p_val, 6),
            'significant_Harvey': abs(t_stat) > 3.0,
        }

    # B) HAR-DN vs HAR-RV on QLIKE(r^2) — cross-model
    print("\n  -- HAR models on r^2 target (Patton 2011 cross-model) --")
    for model_name in ['HAR-DN', 'HAR-DN-Ratio']:
        fcast_new = har_forecasts[model_name][oos_idx]
        fcast_base = har_forecasts['HAR-RV'][oos_idx]
        valid = (np.isfinite(fcast_new) & np.isfinite(fcast_base) &
                 np.isfinite(r2_actual) & (r2_actual > 0) & (fcast_new > 0) & (fcast_base > 0))

        loss_new = r2_actual[valid] / fcast_new[valid] - np.log(r2_actual[valid] / fcast_new[valid]) - 1
        loss_base = r2_actual[valid] / fcast_base[valid] - np.log(r2_actual[valid] / fcast_base[valid]) - 1

        t_stat, p_val = dm_test_nw(loss_new, loss_base)
        sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else ("*" if abs(t_stat) > 1.64 else ""))
        print(f"  {model_name} vs HAR-RV (QLIKE on r^2): t={t_stat:.3f} p={p_val:.4f} {sig}")
        dm_results[f'{model_name}_vs_HAR-RV_QLIKE_r2'] = {
            't_stat': round(t_stat, 4),
            'p_value': round(p_val, 6),
            'significant_Harvey': abs(t_stat) > 3.0,
        }

    # C) Best HAR vs GJR on QLIKE(r^2) — the only fair cross-type comparison
    print("\n  -- Best HAR vs GJR on r^2 (cross-type, Patton 2011) --")
    for model_name in models:
        fcast_har = har_forecasts[model_name][oos_idx]
        fcast_gjr = gjr_forecasts[oos_idx]
        valid = (np.isfinite(fcast_har) & np.isfinite(fcast_gjr) &
                 np.isfinite(r2_actual) & (r2_actual > 0) & (fcast_har > 0) & (fcast_gjr > 0))

        if valid.sum() < 10:
            print(f"  {model_name} vs GJR: insufficient overlap ({valid.sum()} obs)")
            continue

        loss_har = r2_actual[valid] / fcast_har[valid] - np.log(r2_actual[valid] / fcast_har[valid]) - 1
        loss_gjr = r2_actual[valid] / fcast_gjr[valid] - np.log(r2_actual[valid] / fcast_gjr[valid]) - 1

        t_stat, p_val = dm_test_nw(loss_har, loss_gjr)
        sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else ("*" if abs(t_stat) > 1.64 else ""))
        print(f"  {model_name} vs GJR (QLIKE on r^2): t={t_stat:.3f} p={p_val:.4f} {sig}")
        dm_results[f'{model_name}_vs_GJR_QLIKE_r2'] = {
            't_stat': round(t_stat, 4),
            'p_value': round(p_val, 6),
            'significant_Harvey': abs(t_stat) > 3.0,
        }

    # ---- In-Sample R^2 for reference ----
    print("\n  === In-Sample R^2 (for reference only, NOT for model selection) ===")
    is_end = oos_start
    for model_name in models:
        y_train = []
        X_train = []
        for s in range(22, is_end):
            feat = get_har_features(model_name, df, s)
            if feat is not None and np.isfinite(df['log_rv_full'].values[s + 1]):
                X_train.append(feat)
                y_train.append(df['log_rv_full'].values[s + 1])
        if len(y_train) > 0:
            y_train = np.array(y_train)
            X_train = np.array(X_train)
            _, r2 = fit_har_ols(y_train, X_train)
            print(f"  {model_name}: IS R^2 = {r2:.4f}")
            results[model_name]['IS_R2'] = round(r2, 4)

    # ---- Night ratio coefficient analysis ----
    print("\n  === Night Ratio Coefficient Analysis (IS) ===")
    y_train_all = []
    X_train_all = []
    for s in range(22, is_end):
        feat = get_har_features('HAR-DN-Ratio', df, s)
        if feat is not None and np.isfinite(df['log_rv_full'].values[s + 1]):
            X_train_all.append(feat)
            y_train_all.append(df['log_rv_full'].values[s + 1])
    if len(y_train_all) > 0:
        y_arr = np.array(y_train_all)
        X_arr = np.array(X_train_all)
        beta_ratio, _ = fit_har_ols(y_arr, X_arr)
        if beta_ratio is not None:
            labels = ['intercept', 'log(RV_t)', 'log(RV_5d)', 'log(RV_22d)', 'night_ratio']
            print("  HAR-DN-Ratio coefficients:")
            for lbl, b in zip(labels, beta_ratio):
                print(f"    {lbl}: {b:.4f}")

            # t-stat for night_ratio
            n_tr = len(y_arr)
            X_c = np.column_stack([np.ones(n_tr), X_arr])
            y_hat = X_c @ beta_ratio
            resid = y_arr - y_hat
            s2 = np.sum(resid ** 2) / (n_tr - len(beta_ratio))
            cov_beta = s2 * np.linalg.inv(X_c.T @ X_c)
            se = np.sqrt(np.diag(cov_beta))
            t_stats = beta_ratio / se
            print(f"    night_ratio t-stat: {t_stats[-1]:.3f} "
                  f"({'***' if abs(t_stats[-1]) > 3.0 else '**' if abs(t_stats[-1]) > 2.0 else '*' if abs(t_stats[-1]) > 1.64 else 'ns'})")
            results['HAR-DN-Ratio']['night_ratio_coef'] = round(beta_ratio[-1], 4)
            results['HAR-DN-Ratio']['night_ratio_tstat'] = round(t_stats[-1], 3)

    # ---- HAR-DN coefficient analysis ----
    print("\n  === HAR-DN Coefficient Analysis (IS) ===")
    y_dn = []
    X_dn = []
    for s in range(22, is_end):
        feat = get_har_features('HAR-DN', df, s)
        if feat is not None and np.isfinite(df['log_rv_full'].values[s + 1]):
            X_dn.append(feat)
            y_dn.append(df['log_rv_full'].values[s + 1])
    if len(y_dn) > 0:
        y_arr = np.array(y_dn)
        X_arr = np.array(X_dn)
        beta_dn, _ = fit_har_ols(y_arr, X_arr)
        if beta_dn is not None:
            labels = ['intercept', 'log(RV_day_t)', 'log(RV_night_t)',
                      'log(RV_day_5d)', 'log(RV_night_5d)',
                      'log(RV_day_22d)', 'log(RV_night_22d)']
            print("  HAR-DN coefficients:")
            n_tr = len(y_arr)
            X_c = np.column_stack([np.ones(n_tr), X_arr])
            y_hat = X_c @ beta_dn
            resid = y_arr - y_hat
            s2 = np.sum(resid ** 2) / (n_tr - len(beta_dn))
            cov_beta = s2 * np.linalg.inv(X_c.T @ X_c)
            se = np.sqrt(np.diag(cov_beta))
            t_stats = beta_dn / se
            for lbl, b, t in zip(labels, beta_dn, t_stats):
                sig = '***' if abs(t) > 3.0 else '**' if abs(t) > 2.0 else '*' if abs(t) > 1.64 else 'ns'
                print(f"    {lbl}: {b:.4f} (t={t:.2f} {sig})")

            results['HAR-DN']['coefficients'] = {
                lbl: {'beta': round(b, 4), 't_stat': round(t, 2)}
                for lbl, b, t in zip(labels, beta_dn, t_stats)
            }

    # --- Summary ---
    print("\n[7/7] Summary...")
    print("=" * 70)

    # Determine winner on native RV target
    har_qlike_rv = {m: results[m]['QLIKE_on_RV'] for m in models}
    best_har = min(har_qlike_rv, key=har_qlike_rv.get)
    print(f"\n  Best HAR on RV target (QLIKE): {best_har} ({har_qlike_rv[best_har]:.4f})")

    # Improvement of HAR-DN over HAR-RV
    if 'HAR-DN' in har_qlike_rv and 'HAR-RV' in har_qlike_rv:
        pct_improve = (har_qlike_rv['HAR-RV'] - har_qlike_rv['HAR-DN']) / har_qlike_rv['HAR-RV'] * 100
        print(f"  HAR-DN improvement over HAR-RV: {pct_improve:.2f}%")

    # Cross-model on r^2
    all_qlike_r2 = {}
    for m in models:
        all_qlike_r2[m] = results[m].get('QLIKE_on_r2', np.nan)
    all_qlike_r2['GJR-GARCH'] = results['GJR-GARCH'].get('QLIKE_on_r2', np.nan)
    best_r2 = min(all_qlike_r2, key=all_qlike_r2.get)
    print(f"  Best on r^2 target (QLIKE): {best_r2} ({all_qlike_r2[best_r2]:.4f})")

    # Key question answer
    print("\n  KEY QUESTION: Does night-session RV improve HAR forecasting?")
    dm_dn = dm_results.get('HAR-DN_vs_HAR-RV_QLIKE_RV', {})
    t_val = dm_dn.get('t_stat', np.nan)
    if np.isfinite(t_val):
        if t_val < -3.0:
            answer = "YES — HAR-DN significantly better (Harvey |t|>3.0)"
        elif t_val < -1.64:
            answer = "MARGINAL — HAR-DN somewhat better (not Harvey-significant)"
        elif abs(t_val) < 1.64:
            answer = "NO — No significant difference"
        else:
            answer = "REVERSE — HAR-RV actually better"
        print(f"  DM t-stat (HAR-DN vs HAR-RV on RV): {t_val:.3f}")
        print(f"  Answer: {answer}")
    else:
        answer = "INCONCLUSIVE"
        print(f"  Answer: {answer}")

    # --- Save results ---
    output = {
        'experiment_id': 'K868',
        'title': 'HAR Day/Night RV Decomposition for Taiwan Futures',
        'date': datetime.now().strftime('%Y-%m-%d'),
        'data_source': 'TAIFEX TX1 tick data (2017-2026)',
        'methodology': {
            'models': ['HAR-RV', 'HAR-DN', 'HAR-DN-Ratio', 'GJR-GARCH'],
            'target': 'log(RV_total_{t+1})',
            'oos_split': f'60/40 (IS: {oos_start} days, OOS: {n - oos_start - 1} days)',
            'refit_freq': REFIT_FREQ,
            'rv_decomposition': 'RV_day (8:45-13:45) + RV_night (15:00-05:00)',
        },
        'descriptive_stats': {
            'n_trading_days': len(df),
            'date_range': f'{df.index[0].date()} to {df.index[-1].date()}',
            'rv_total_mean': round(df['rv_full'].mean(), 8),
            'rv_day_mean': round(df['rv_day'].mean(), 8),
            'rv_night_mean': round(df['rv_night'].mean(), 8),
            'night_share_mean': round(night_share.mean(), 3),
            'corr_day_night': round(corr_dn, 3),
        },
        'model_results': results,
        'dm_tests': dm_results,
        'key_finding': answer,
        'references': [
            'Corsi (2009) J. Financial Econometrics',
            'Patton (2011) J. Econometrics',
            'Hansen & Lunde (2005) J. Applied Econometrics',
            'Andersen, Bollerslev, Diebold (2007) Review of Economic Studies',
        ],
        'limitations': [
            'Single asset (TAIFEX TX), generalization uncertain',
            'Night session only from 2017-05-15, relatively short sample',
            'No transaction cost or liquidity analysis',
            'GJR comparison on r^2 involves noisy proxy (daily squared return)',
        ],
    }

    results_path = os.path.join(SCRIPT_DIR, 'k868_results.json')
    with open(results_path, 'w') as f:
        json.dump(output, f, indent=2, default=str, ensure_ascii=False)
    print(f"\n  Results saved to {results_path}")
    print("\nDone.")

    return output


if __name__ == '__main__':
    main()
