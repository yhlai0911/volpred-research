#!/usr/bin/env python3
"""
K849: HAR-RV on TAIFEX 5-min RV — HAR Model Comparison
=======================================================

Purpose:
  Compare HAR-RV models against GJR-GARCH/EWMA using TAIFEX TX 5-min RV as
  the gold-standard target (Hansen & Lunde 2005). Two tracks to satisfy
  "long sample" requirement:
    Track A: Day-only RV, 2012-2025 (14 years)
    Track B: Full RV (day+night), 2017/05-2025 (8 years)

Models:
  1. HAR-RV:   RV_t = b0 + b1*RV_{t-1} + b2*RV_{t-1:5} + b3*RV_{t-1:22} + e
  2. HAR-RV-J: HAR-RV + b4*Jump_{t-1}  (Jump = max(RV-BPV, 0))
  3. GJR-GARCH(1,1): Student-t on 0050.TW daily log returns (OOS recursive)
  4. EWMA: lambda=0.94 on daily r-squared

Target = 5-min RV (both tracks)
Metrics: QLIKE, MSE, MAE, Spearman
DM test (Harvey t>3.0), Cross-OOS stability (5 folds)

Track A IS: 2012-2019, OOS: 2020-2025
Track B IS: 2017/05-2021, OOS: 2022-2025

Error log rules:
  - 0050.TW: must use clean_tw50_data
  - DM test: Newey-West HAC
  - GARCH OOS: recursive h[t]=f(h[t-1], r_sq[t-1])
  - Student-t: scale term sqrt((df-2)/df)

References:
  - Corsi (2009): HAR-RV model
  - Andersen, Bollerslev, Diebold (2007): Roughing it up - HAR-RV-J
  - Hansen & Lunde (2005): 5-min RV as gold standard
  - Patton (2011): QLIKE proxy-robust
  - Barndorff-Nielsen & Shephard (2004): Bipower variation

Author: VolPred Research System
Date: 2026-04-03
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


# ============================================================
# Step 1: Build 5-min RV from tick data (reused from K848)
# ============================================================

def time_to_5min_bucket(time_int):
    """Convert HHMMSS integer to a 5-minute bucket label."""
    h = time_int // 10000
    m = (time_int % 10000) // 100
    m5 = (m // 5) * 5
    return h * 100 + m5


def compute_rv_bpv(returns):
    """Compute RV and BPV from an array of 5-min log returns."""
    if len(returns) < 1:
        return np.nan, np.nan
    rv = np.sum(returns ** 2)
    if len(returns) >= 2:
        bpv = (np.pi / 2) * np.sum(np.abs(returns[1:]) * np.abs(returns[:-1]))
    else:
        bpv = np.nan
    return float(rv), float(bpv)


def process_single_file(filepath):
    """Process one TX file -> compute 5-min RV for day and night sessions."""
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
        df['volume'] = pd.to_numeric(df.iloc[:, 5], errors='coerce').fillna(0)
        df = df.dropna(subset=['price', 'time_int'])
        df['time_int'] = df['time_int'].astype(int)
    except Exception:
        return None

    if len(df) < 10:
        return None

    # Filter to near-month (most volume) for TX files (not TX1)
    if 'TX1' not in basename and 'TX2' not in basename:
        df['delivery'] = df.iloc[:, 2].astype(str).str.strip()
        vol_by_delivery = df.groupby('delivery')['volume'].sum()
        if len(vol_by_delivery) > 0:
            near_month = vol_by_delivery.idxmax()
            df = df[df['delivery'] == near_month]

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

    day_rets = build_5min_returns(t[day_mask], p[day_mask])
    night_pm_rets = build_5min_returns(t[night_pm_mask], p[night_pm_mask])
    night_am_rets = build_5min_returns(t[night_am_mask], p[night_am_mask])

    if len(night_pm_rets) > 0 or len(night_am_rets) > 0:
        night_rets = np.concatenate([night_pm_rets, night_am_rets])
    else:
        night_rets = np.array([])

    rv_day, bpv_day = compute_rv_bpv(day_rets)
    rv_night, bpv_night = compute_rv_bpv(night_rets)

    # RV total
    if not np.isnan(rv_day) and not np.isnan(rv_night):
        rv_total = rv_day + rv_night
        bpv_total = (bpv_day if not np.isnan(bpv_day) else 0) + (bpv_night if not np.isnan(bpv_night) else 0)
    elif not np.isnan(rv_day):
        rv_total = rv_day
        bpv_total = bpv_day if not np.isnan(bpv_day) else np.nan
    else:
        rv_total = np.nan
        bpv_total = np.nan

    jump_total = max(rv_total - bpv_total, 0) if (not np.isnan(rv_total) and not np.isnan(bpv_total)) else np.nan
    jump_day = max(rv_day - bpv_day, 0) if (not np.isnan(rv_day) and not np.isnan(bpv_day)) else np.nan

    # Day session return for r-squared
    day_p_sorted = p[day_mask]
    if len(day_p_sorted) >= 2:
        day_return = np.log(float(day_p_sorted[-1]) / float(day_p_sorted[0]))
    else:
        day_return = np.nan

    return {
        'date': date_str,
        'rv_day': rv_day if not np.isnan(rv_day) else None,
        'rv_night': rv_night if not np.isnan(rv_night) else None,
        'rv_total': rv_total if not np.isnan(rv_total) else None,
        'bpv_day': bpv_day if not np.isnan(bpv_day) else None,
        'bpv_total': bpv_total if not np.isnan(bpv_total) else None,
        'jump_day': jump_day if not np.isnan(jump_day) else None,
        'jump_total': jump_total if not np.isnan(jump_total) else None,
        'day_return': day_return if not np.isnan(day_return) else None,
    }


def load_all_rv_data(start_date=None):
    """Load TX1 files and compute 5-min RV using parallel processing."""
    pattern = os.path.join(DATA_DIR, "Daily_*TX1.csv")
    all_files = sorted(glob.glob(pattern))

    if start_date:
        cutoff = f"Daily_{start_date.replace('-', '_')}"
        files = [f for f in all_files if os.path.basename(f) >= cutoff]
    else:
        files = all_files

    # Cap at end of 2025 for clean sample
    files = [f for f in files if os.path.basename(f) < "Daily_2026"]
    print(f"  Found {len(files)} TX1 files from {start_date or 'all'} to end 2025")

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
                if result is not None and result.get('rv_day') is not None:
                    results.append(result)
                else:
                    errors += 1
            except Exception:
                errors += 1

    print(f"  Loaded: {len(results)}, Errors: {errors}")

    df = pd.DataFrame(results)
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').sort_index()
    return df


# ============================================================
# Step 2: HAR-RV Models
# ============================================================

def fit_har_ols(y, X):
    """OLS fit: y = X @ beta + e. Returns beta, y_hat, R-squared."""
    n = len(y)
    X_c = np.column_stack([np.ones(n), X])
    try:
        beta = np.linalg.lstsq(X_c, y, rcond=None)[0]
        y_hat = X_c @ beta
        resid = y - y_hat
        ss_res = np.sum(resid ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
        return beta, y_hat, r2
    except Exception:
        return None, None, None


def har_oos_forecast(rv_series, jump_series, oos_start, model_type='HAR-RV',
                     refit_freq=63, min_train=250):
    """
    Rolling OOS forecast for HAR models.
    model_type: 'HAR-RV' or 'HAR-RV-J'
    """
    rv = rv_series.values.copy()
    dates = rv_series.index
    n = len(rv)

    oos_idx = np.searchsorted(dates, pd.Timestamp(oos_start))
    if oos_idx < min_train:
        oos_idx = min_train

    forecasts = np.full(n, np.nan)
    last_beta = None
    last_fit_idx = -refit_freq  # Force first fit

    for t in range(oos_idx, n):
        # Refit periodically
        if t - last_fit_idx >= refit_freq or last_beta is None:
            train_rv = rv[:t]
            if len(train_rv) < min_train:
                continue

            # Build features for training
            rv_d = np.full(t, np.nan)
            rv_w = np.full(t, np.nan)
            rv_m = np.full(t, np.nan)
            for i in range(1, t):
                rv_d[i] = train_rv[i - 1]
            for i in range(5, t):
                rv_w[i] = np.mean(train_rv[i - 5:i])
            for i in range(22, t):
                rv_m[i] = np.mean(train_rv[i - 22:i])

            if model_type == 'HAR-RV-J' and jump_series is not None:
                j = jump_series.values[:t]
                j_lag = np.full(t, np.nan)
                for i in range(1, t):
                    j_lag[i] = j[i - 1]
                feat = np.column_stack([rv_d, rv_w, rv_m, j_lag])
            else:
                feat = np.column_stack([rv_d, rv_w, rv_m])

            valid_mask = ~np.any(np.isnan(feat), axis=1) & ~np.isnan(train_rv)
            if np.sum(valid_mask) < 50:
                continue

            y_train = train_rv[valid_mask]
            X_train = feat[valid_mask]

            beta, _, _ = fit_har_ols(y_train, X_train)
            if beta is not None:
                last_beta = beta
                last_fit_idx = t

        if last_beta is None:
            continue

        # Build features for time t (using info up to t-1)
        rv_d_t = rv[t - 1]
        rv_w_t = np.mean(rv[max(0, t - 5):t]) if t >= 5 else np.nan
        rv_m_t = np.mean(rv[max(0, t - 22):t]) if t >= 22 else np.nan

        if np.isnan(rv_d_t) or np.isnan(rv_w_t) or np.isnan(rv_m_t):
            continue

        if model_type == 'HAR-RV-J' and jump_series is not None:
            j_t = jump_series.values[t - 1] if t > 0 else 0
            x_t = np.array([1, rv_d_t, rv_w_t, rv_m_t, j_t])
        else:
            x_t = np.array([1, rv_d_t, rv_w_t, rv_m_t])

        forecast = x_t @ last_beta
        forecasts[t] = max(forecast, 1e-10)  # Floor at small positive

    return pd.Series(forecasts, index=dates, name=model_type)


# ============================================================
# Step 3: GJR-GARCH on 0050.TW
# ============================================================

def fit_gjr_garch_oos(rv_df, oos_start, refit_freq=63, init_window=500):
    """
    Fit GJR-GARCH(1,1) on 0050.TW daily log returns.
    OOS: recursive h[t] = omega + (alpha + gamma*I_{t-1}) * r_sq[t-1] + beta * h[t-1]
    """
    import arch

    # Mandatory: use clean_tw50_data (returns Series, not DataFrame)
    sys.path.insert(0, os.path.join(SCRIPT_DIR, '..', 'src'))
    from volpred.utils import clean_tw50_data

    import yfinance as yf

    # Download 0050.TW data
    start_yr = rv_df.index.min().year - 1
    raw = yf.download('0050.TW', start=f'{start_yr}-01-01', end='2026-01-01', progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    # clean_tw50_data expects a Series (prices), returns (clean_prices, clean_returns)
    close_series = raw['Close'].squeeze()
    clean_prices, clean_returns = clean_tw50_data(close_series)
    etf = pd.DataFrame({'Close': clean_prices, 'Return': clean_returns})
    etf['log_ret'] = np.log(etf['Close'] / etf['Close'].shift(1))
    etf = etf.dropna(subset=['log_ret'])
    etf.index = pd.to_datetime(etf.index).tz_localize(None)

    # Align dates with RV data
    common_dates = rv_df.index.intersection(etf.index)
    print(f"  GJR-GARCH: {len(common_dates)} common dates with RV data")

    returns_pct = etf.loc[common_dates, 'log_ret'] * 100  # arch needs %
    returns_raw = etf.loc[common_dates, 'log_ret']

    oos_idx = np.searchsorted(common_dates, pd.Timestamp(oos_start))
    if oos_idx < init_window:
        oos_idx = init_window

    forecasts = pd.Series(np.nan, index=common_dates, name='GJR-GARCH')
    r_squared = pd.Series(returns_raw.values ** 2, index=common_dates, name='r_squared')

    last_params = None
    last_fit_idx = -refit_freq
    last_h = None

    for t in range(oos_idx, len(common_dates)):
        if t - last_fit_idx >= refit_freq or last_params is None:
            train = returns_pct.iloc[:t]
            if len(train) < init_window:
                continue
            try:
                model = arch.arch_model(train, vol='GARCH', p=1, o=1, q=1, dist='t')
                res = model.fit(disp='off', show_warning=False)
                if res.convergence_flag == 0:
                    last_params = {
                        'omega': res.params['omega'],
                        'alpha': res.params['alpha[1]'],
                        'gamma': res.params['gamma[1]'],
                        'beta': res.params['beta[1]'],
                        'nu': res.params['nu'],
                    }
                    # Initialize h at last conditional variance
                    last_h = res.conditional_volatility.iloc[-1] ** 2
                    last_fit_idx = t
            except Exception:
                pass

        if last_params is None or last_h is None:
            continue

        # Recursive: h[t] = omega + (alpha + gamma*I) * r_sq[t-1] + beta * h[t-1]
        r_prev = returns_pct.iloc[t - 1]  # in %
        I_neg = 1.0 if r_prev < 0 else 0.0
        r2_prev = r_prev ** 2

        h_t = (last_params['omega'] +
               (last_params['alpha'] + last_params['gamma'] * I_neg) * r2_prev +
               last_params['beta'] * last_h)
        last_h = h_t

        # Convert from pct-squared to decimal-squared: divide by 10000
        forecasts.iloc[t] = h_t / 10000.0

    return forecasts, r_squared


# ============================================================
# Step 4: EWMA baseline
# ============================================================

def ewma_forecast(r_squared_series, lam=0.94):
    """EWMA: h[t] = lambda * h[t-1] + (1-lambda) * r_sq[t-1]"""
    r2 = r_squared_series.values.copy()
    n = len(r2)
    h = np.full(n, np.nan)
    h[0] = r2[0] if not np.isnan(r2[0]) else np.nanmean(r2[:20])

    for t in range(1, n):
        if np.isnan(r2[t - 1]):
            h[t] = h[t - 1] if not np.isnan(h[t - 1]) else h[0]
        else:
            h_prev = h[t - 1] if not np.isnan(h[t - 1]) else r2[t - 1]
            h[t] = lam * h_prev + (1 - lam) * r2[t - 1]

    return pd.Series(h, index=r_squared_series.index, name='EWMA')


# ============================================================
# Step 5: Metrics and statistical tests
# ============================================================

def qlike(target, forecast):
    """QLIKE = mean(target/forecast - log(target/forecast) - 1)"""
    t = np.asarray(target, dtype=float)
    f = np.asarray(forecast, dtype=float)
    valid = np.isfinite(t) & np.isfinite(f) & (t > 0) & (f > 0)
    t, f = t[valid], f[valid]
    if len(t) < 10:
        return np.nan
    ratio = t / f
    return float(np.mean(ratio - np.log(ratio) - 1))


def mse_metric(target, forecast):
    t = np.asarray(target, dtype=float)
    f = np.asarray(forecast, dtype=float)
    valid = np.isfinite(t) & np.isfinite(f)
    return float(np.mean((t[valid] - f[valid]) ** 2)) if np.sum(valid) > 10 else np.nan


def mae_metric(target, forecast):
    t = np.asarray(target, dtype=float)
    f = np.asarray(forecast, dtype=float)
    valid = np.isfinite(t) & np.isfinite(f)
    return float(np.mean(np.abs(t[valid] - f[valid]))) if np.sum(valid) > 10 else np.nan


def spearman_corr(target, forecast):
    t = np.asarray(target, dtype=float)
    f = np.asarray(forecast, dtype=float)
    valid = np.isfinite(t) & np.isfinite(f)
    if np.sum(valid) < 10:
        return np.nan, np.nan
    rho, pval = sp_stats.spearmanr(t[valid], f[valid])
    return float(rho), float(pval)


def qlike_loss_series(target, forecast):
    """Per-observation QLIKE loss for DM test."""
    t = np.asarray(target, dtype=float)
    f = np.asarray(forecast, dtype=float)
    ratio = t / f
    loss = ratio - np.log(ratio) - 1
    loss[~np.isfinite(loss)] = np.nan
    loss[(t <= 0) | (f <= 0)] = np.nan
    return loss


def dm_test(loss1, loss2, h=1):
    """DM test with Newey-West HAC. Negative t -> model 1 better."""
    d = np.asarray(loss1, dtype=np.float64) - np.asarray(loss2, dtype=np.float64)
    valid = np.isfinite(d)
    d = d[valid]
    n = len(d)
    if n < 10:
        return 0.0, 1.0

    d_mean = np.mean(d)
    max_lag = max(1, min(int(np.ceil(h ** (1/3) * n ** (1/3))), n // 4))
    gamma0 = np.mean((d - d_mean) ** 2)
    var_d = gamma0
    for lag in range(1, max_lag + 1):
        weight = 1 - lag / (max_lag + 1)
        gamma_l = np.mean((d[lag:] - d_mean) * (d[:-lag] - d_mean))
        var_d += 2 * weight * gamma_l

    if var_d <= 0:
        return 0.0, 1.0
    se = np.sqrt(var_d / n)
    if se < 1e-15:
        return 0.0, 1.0

    t_stat = d_mean / se
    p_val = 2 * (1 - sp_stats.t.cdf(abs(t_stat), df=n - 1))
    return float(t_stat), float(p_val)


# ============================================================
# Step 6: In-sample HAR diagnostics
# ============================================================

def har_insample_diagnostics(rv_series, jump_series, model_type='HAR-RV'):
    """Fit HAR on full in-sample and report coefficients + R-squared."""
    rv = rv_series.values
    n = len(rv)

    # Build features
    rv_d = np.full(n, np.nan)
    rv_w = np.full(n, np.nan)
    rv_m = np.full(n, np.nan)
    for i in range(1, n):
        rv_d[i] = rv[i - 1]
    for i in range(5, n):
        rv_w[i] = np.mean(rv[i - 5:i])
    for i in range(22, n):
        rv_m[i] = np.mean(rv[i - 22:i])

    if model_type == 'HAR-RV-J' and jump_series is not None:
        j = jump_series.values
        j_lag = np.full(n, np.nan)
        for i in range(1, n):
            j_lag[i] = j[i - 1]
        feat = np.column_stack([rv_d, rv_w, rv_m, j_lag])
        names = ['const', 'rv_d', 'rv_w', 'rv_m', 'jump']
    else:
        feat = np.column_stack([rv_d, rv_w, rv_m])
        names = ['const', 'rv_d', 'rv_w', 'rv_m']

    valid_mask = ~np.any(np.isnan(feat), axis=1) & ~np.isnan(rv)
    if np.sum(valid_mask) < 50:
        return None

    y = rv[valid_mask]
    X = feat[valid_mask]
    n_valid = len(y)

    beta, y_hat, r2 = fit_har_ols(y, X)
    if beta is None:
        return None

    # Newey-West t-stats
    X_c = np.column_stack([np.ones(n_valid), X])
    resid = y - y_hat
    max_lag = int(np.ceil(n_valid ** (1/3)))

    # HAC covariance
    S = np.zeros((X_c.shape[1], X_c.shape[1]))
    for lag in range(max_lag + 1):
        weight = 1.0 if lag == 0 else (1 - lag / (max_lag + 1))
        if lag == 0:
            Gamma = (X_c * resid[:, None]).T @ (X_c * resid[:, None]) / n_valid
        else:
            Gamma = (X_c[lag:] * resid[lag:, None]).T @ (X_c[:-lag] * resid[:-lag, None]) / n_valid
            S += weight * (Gamma + Gamma.T)
            continue
        S += weight * Gamma

    try:
        XtX_inv = np.linalg.inv(X_c.T @ X_c / n_valid)
        V = XtX_inv @ S @ XtX_inv / n_valid
        se = np.sqrt(np.diag(V))
        t_stats = beta / se
    except Exception:
        se = np.full_like(beta, np.nan)
        t_stats = np.full_like(beta, np.nan)

    coeffs = {}
    for i, name in enumerate(names):
        coeffs[name] = {
            'estimate': round(float(beta[i]), 8),
            'se': round(float(se[i]), 8),
            't_stat': round(float(t_stats[i]), 4),
        }

    return {
        'model': model_type,
        'n': n_valid,
        'R2': round(float(r2), 6),
        'coefficients': coeffs,
    }


# ============================================================
# Step 7: Cross-OOS stability
# ============================================================

def cross_oos_stability(rv_series, model_forecasts, n_folds=5):
    """
    Split OOS period into n_folds and compute QLIKE + Spearman per fold.
    """
    # Find common valid dates across all models
    model_names = list(model_forecasts.keys())
    common_oos = rv_series.dropna().index
    for mn in model_names:
        fc = model_forecasts[mn]
        valid = fc.dropna().index
        common_oos = common_oos.intersection(valid)
    common_oos = common_oos.sort_values()

    if len(common_oos) < 50:
        return None

    fold_size = len(common_oos) // n_folds
    folds = []

    for f in range(n_folds):
        start_idx = f * fold_size
        end_idx = (f + 1) * fold_size if f < n_folds - 1 else len(common_oos)
        fold_dates = common_oos[start_idx:end_idx]
        target = rv_series.loc[fold_dates].values

        fold_result = {
            'fold': f + 1,
            'n': len(fold_dates),
            'start': str(fold_dates[0].date()),
            'end': str(fold_dates[-1].date()),
        }

        for mn in model_names:
            fc = model_forecasts[mn].loc[fold_dates].values
            fold_result[f'{mn}_QLIKE'] = round(qlike(target, fc), 6) if not np.isnan(qlike(target, fc)) else None
            rho, _ = spearman_corr(target, fc)
            fold_result[f'{mn}_Spearman'] = round(rho, 4) if not np.isnan(rho) else None

        folds.append(fold_result)

    return folds


# ============================================================
# Main execution
# ============================================================

def run_track(track_name, rv_df, rv_col, jump_col, oos_start,
              is_start, is_end, oos_end):
    """Run a full analysis track."""
    print(f"\n{'='*60}")
    print(f"  TRACK {track_name}: {rv_col}")
    print(f"  IS {is_start} to {is_end}, OOS {oos_start} to {oos_end}")
    print(f"{'='*60}")

    rv = rv_df[rv_col].dropna()
    jump = rv_df[jump_col].dropna() if jump_col else None

    print(f"  RV series: {len(rv)} obs, {rv.index[0].date()} to {rv.index[-1].date()}")

    # In-sample period
    is_rv = rv.loc[:is_end]
    is_jump = rv_df[jump_col].loc[:is_end] if jump_col else None
    print(f"  IS: {len(is_rv)} obs")

    # ---- In-sample diagnostics ----
    print("  Fitting HAR-RV in-sample...")
    is_diag_har = har_insample_diagnostics(is_rv, is_jump, 'HAR-RV')
    is_diag_harj = har_insample_diagnostics(is_rv, is_jump, 'HAR-RV-J')

    if is_diag_har:
        print(f"    HAR-RV  IS R2 = {is_diag_har['R2']:.4f}")
    if is_diag_harj:
        print(f"    HAR-RV-J IS R2 = {is_diag_harj['R2']:.4f}")

    # ---- OOS forecasts ----
    print("  Computing HAR-RV OOS forecasts...")
    fc_har = har_oos_forecast(rv, jump, oos_start, 'HAR-RV', refit_freq=63, min_train=250)
    print(f"    HAR-RV: {fc_har.dropna().shape[0]} OOS forecasts")

    print("  Computing HAR-RV-J OOS forecasts...")
    fc_harj = har_oos_forecast(rv, jump, oos_start, 'HAR-RV-J', refit_freq=63, min_train=250)
    print(f"    HAR-RV-J: {fc_harj.dropna().shape[0]} OOS forecasts")

    # ---- GJR-GARCH ----
    print("  Fitting GJR-GARCH on 0050.TW...")
    fc_garch, r_squared = fit_gjr_garch_oos(rv_df, oos_start, refit_freq=63)
    print(f"    GJR-GARCH: {fc_garch.dropna().shape[0]} OOS forecasts")

    # ---- EWMA ----
    day_ret = rv_df['day_return'].dropna()
    r2_series = day_ret ** 2
    r2_series.name = 'r_squared'
    fc_ewma = ewma_forecast(r2_series, lam=0.94)
    print(f"    EWMA: {fc_ewma.dropna().shape[0]} total forecasts")

    # ---- Align all to common OOS dates ----
    oos_start_ts = pd.Timestamp(oos_start)
    oos_end_ts = pd.Timestamp(oos_end)

    all_dates = rv.index[(rv.index >= oos_start_ts) & (rv.index <= oos_end_ts)]

    model_forecasts = {
        'HAR-RV': fc_har,
        'HAR-RV-J': fc_harj,
        'GJR-GARCH': fc_garch,
        'EWMA': fc_ewma,
    }

    # Find common valid dates
    common = all_dates
    for mn, fc in model_forecasts.items():
        valid = fc.dropna().index
        common = common.intersection(valid)
    common = common.intersection(rv.dropna().index)
    common = common.sort_values()

    print(f"\n  Common OOS dates: {len(common)}")
    if len(common) < 30:
        print("  WARNING: Too few common dates!")
        return None

    target = rv.loc[common].values
    print(f"  Target RV: mean={np.mean(target):.2e}, std={np.std(target):.2e}")

    # ---- Compute metrics ----
    results = {}
    loss_series = {}

    for mn, fc in model_forecasts.items():
        fc_vals = fc.loc[common].values
        q = qlike(target, fc_vals)
        m = mse_metric(target, fc_vals)
        ma = mae_metric(target, fc_vals)
        rho, p = spearman_corr(target, fc_vals)

        results[mn] = {
            'QLIKE': round(q, 6) if not np.isnan(q) else None,
            'MSE': float(f"{m:.4e}") if not np.isnan(m) else None,
            'MAE': float(f"{ma:.4e}") if not np.isnan(ma) else None,
            'Spearman': round(rho, 4) if not np.isnan(rho) else None,
            'Spearman_p': round(p, 6) if not np.isnan(p) else None,
            'n_oos': len(common),
        }
        loss_series[mn] = qlike_loss_series(target, fc_vals)

        print(f"    {mn:12s}: QLIKE={q:.6f}  MSE={m:.2e}  Spearman={rho:.4f}")

    # ---- DM tests ----
    print("\n  DM tests (QLIKE loss, Harvey t>3.0):")
    dm_results = {}
    model_names = list(model_forecasts.keys())
    for i in range(len(model_names)):
        for j in range(i + 1, len(model_names)):
            m1, m2 = model_names[i], model_names[j]
            t_stat, p_val = dm_test(loss_series[m1], loss_series[m2])
            key = f"{m1} vs {m2}"
            sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else "")
            winner = m1 if t_stat < 0 else m2
            dm_results[key] = {
                't_stat': round(t_stat, 4),
                'p_value': round(p_val, 6),
                'winner': winner,
                'significant_harvey': abs(t_stat) > 3.0,
            }
            print(f"    {key}: t={t_stat:.3f} p={p_val:.4f} -> {winner} {sig}")

    # ---- Cross-OOS ----
    print("\n  Cross-OOS stability (5 folds):")
    # Restrict forecasts to OOS period
    oos_forecasts = {}
    for mn, fc in model_forecasts.items():
        oos_forecasts[mn] = fc.reindex(common)

    cross_oos = cross_oos_stability(rv.reindex(common), oos_forecasts, n_folds=5)

    fold_wins = {mn: 0 for mn in model_names}
    if cross_oos:
        for fold in cross_oos:
            line = f"    Fold {fold['fold']} ({fold['start']}~{fold['end']}, n={fold['n']}): "
            qlikes = {}
            for mn in model_names:
                q_val = fold.get(f'{mn}_QLIKE', None)
                if q_val is not None:
                    line += f"{mn}={q_val:.4f} "
                    qlikes[mn] = q_val
            print(line)
            if qlikes:
                best_mn = min(qlikes, key=qlikes.get)
                fold_wins[best_mn] += 1
        print(f"    Fold wins: {fold_wins}")

    # ---- Also assess on r-squared target for reference ----
    print("\n  [Reference] On r-squared target:")
    r2_ref = {}
    r2_vals = r2_series.reindex(common).values
    valid_r2 = np.isfinite(r2_vals) & (r2_vals > 0)
    if np.sum(valid_r2) > 30:
        for mn, fc in model_forecasts.items():
            fc_vals = fc.loc[common].values
            mask = valid_r2 & np.isfinite(fc_vals) & (fc_vals > 0)
            if np.sum(mask) > 30:
                q = qlike(r2_vals[mask], fc_vals[mask])
                rho, _ = spearman_corr(r2_vals[mask], fc_vals[mask])
                r2_ref[mn] = {
                    'QLIKE_on_r2': round(q, 6) if not np.isnan(q) else None,
                    'Spearman_on_r2': round(rho, 4) if not np.isnan(rho) else None,
                }
                print(f"    {mn:12s}: QLIKE(r2)={q:.6f}  Spearman(r2)={rho:.4f}")

    return {
        'track': track_name,
        'rv_col': rv_col,
        'is_period': f"{is_start} to {is_end}",
        'oos_period': f"{oos_start} to {oos_end}",
        'n_oos': len(common),
        'n_total': len(rv),
        'is_diagnostics': {
            'HAR-RV': is_diag_har,
            'HAR-RV-J': is_diag_harj,
        },
        'oos_metrics': results,
        'dm_tests': dm_results,
        'cross_oos': cross_oos,
        'fold_wins': fold_wins,
        'r2_reference': r2_ref,
    }


def main():
    t0 = datetime.now()
    print("=" * 70)
    print("K849: HAR-RV on TAIFEX 5-min RV -- HAR Model Comparison")
    print("=" * 70)

    # ================================================================
    # Load data for Track A (2012+, day-only)
    # ================================================================
    print("\n[1/4] Loading TX1 tick data (2012+)...")
    rv_all = load_all_rv_data(start_date='2012-01-01')
    print(f"  Total days: {len(rv_all)}, range: {rv_all.index[0].date()} to {rv_all.index[-1].date()}")

    # Descriptive stats
    desc = {}
    for col in ['rv_day', 'rv_total', 'jump_day', 'jump_total']:
        s = rv_all[col].dropna()
        if len(s) < 10:
            continue
        desc[col] = {
            'n': len(s),
            'mean': float(s.mean()),
            'std': float(s.std()),
            'median': float(s.median()),
            'skew': round(float(s.skew()), 4),
            'kurtosis': round(float(s.kurtosis()), 4),
            'ann_vol_mean_pct': round(float(np.sqrt(s.mean() * 252) * 100), 2),
        }

    print(f"\n  Descriptive stats:")
    for col, st in desc.items():
        print(f"    {col}: n={st['n']}, mean={st['mean']:.2e}, ann_vol={st['ann_vol_mean_pct']:.1f}%")

    # ================================================================
    # Track A: Day-only RV, 2012-2025
    # ================================================================
    print("\n[2/4] Running Track A (Day-only, 2012-2025)...")
    track_a = run_track(
        track_name='A (Day-only, 14yr)',
        rv_df=rv_all,
        rv_col='rv_day',
        jump_col='jump_day',
        oos_start='2020-01-01',
        is_start='2012-01-01',
        is_end='2019-12-31',
        oos_end='2025-12-31',
    )

    # ================================================================
    # Track B: Full RV (day+night), 2017/05-2025
    # ================================================================
    print("\n[3/4] Running Track B (Full RV, 2017/05-2025)...")
    rv_night_era = rv_all.loc['2017-05-16':]
    track_b = run_track(
        track_name='B (Full RV, 8yr)',
        rv_df=rv_night_era,
        rv_col='rv_total',
        jump_col='jump_total',
        oos_start='2022-01-01',
        is_start='2017-05-16',
        is_end='2021-12-31',
        oos_end='2025-12-31',
    )

    # ================================================================
    # Summary
    # ================================================================
    print("\n[4/4] Summary...")
    t1 = datetime.now()
    elapsed = (t1 - t0).total_seconds()
    print(f"  Total time: {elapsed:.1f}s")

    summary = {
        'question': 'Does HAR-RV beat GJR-GARCH when measured against 5-min RV target?',
        'tracks': {},
    }

    for track_result, label in [(track_a, 'A'), (track_b, 'B')]:
        if track_result is None:
            continue
        metrics = track_result['oos_metrics']
        ranked = sorted(metrics.items(), key=lambda x: x[1]['QLIKE'] if x[1]['QLIKE'] is not None else float('inf'))
        summary['tracks'][label] = {
            'best_model': ranked[0][0],
            'best_QLIKE': ranked[0][1]['QLIKE'],
            'rankings': {r[0]: {'QLIKE': r[1]['QLIKE'], 'rank': i+1} for i, r in enumerate(ranked)},
            'n_oos': track_result['n_oos'],
            'oos_period': track_result['oos_period'],
        }

    # Key findings
    findings = []
    for label in ['A', 'B']:
        if label in summary['tracks']:
            s = summary['tracks'][label]
            findings.append(f"Track {label}: Best={s['best_model']} (QLIKE={s['best_QLIKE']}), n={s['n_oos']}")

    if 'A' in summary['tracks'] and 'B' in summary['tracks']:
        a_best = summary['tracks']['A']['best_model']
        b_best = summary['tracks']['B']['best_model']
        consistent = a_best == b_best
        findings.append(f"Consistent across tracks: {'Yes' if consistent else 'No'} (A={a_best}, B={b_best})")

    # HAR vs GJR comparison
    for label in ['A', 'B']:
        if label in summary['tracks']:
            ranks = summary['tracks'][label]['rankings']
            har_q = ranks.get('HAR-RV', {}).get('QLIKE')
            gjr_q = ranks.get('GJR-GARCH', {}).get('QLIKE')
            if har_q is not None and gjr_q is not None:
                pct = ((gjr_q - har_q) / gjr_q) * 100
                findings.append(f"Track {label}: HAR-RV QLIKE {har_q:.6f} vs GJR {gjr_q:.6f} ({pct:+.1f}%)")

    summary['key_findings'] = findings

    print("\n" + "=" * 70)
    print("  KEY FINDINGS")
    print("=" * 70)
    for f in findings:
        print(f"  -> {f}")

    # ================================================================
    # Save results
    # ================================================================
    results_json = {
        'experiment_id': 'K849',
        'title': 'HAR-RV on TAIFEX 5-min RV -- HAR Model Comparison (14-year Track A + 8-year Track B)',
        'date': '2026-04-03',
        'data_source': 'TAIFEX TX1 tick data + 0050.TW (yfinance, clean_tw50_data applied)',
        'data_period': {
            'track_a': '2012-01 to 2025-12 (day-only RV)',
            'track_b': '2017-05 to 2025-12 (full day+night RV)',
        },
        'methodology': {
            'HAR-RV': 'Corsi (2009): RV_t = b0 + b1*RV_{t-1} + b2*RV_w + b3*RV_m',
            'HAR-RV-J': 'Andersen et al (2007): HAR-RV + Jump component (BPV-based)',
            'GJR-GARCH': 'GJR-GARCH(1,1) Student-t on 0050.TW daily returns, recursive OOS',
            'EWMA': 'lambda=0.94 on daily r-squared',
            'target': '5-min Realized Volatility (Hansen & Lunde 2005 gold standard)',
            'metrics': 'QLIKE (Patton 2011), MSE, MAE, Spearman',
            'dm_test': 'Newey-West HAC, Harvey (2016) threshold |t|>3.0',
            'refit_freq': '63 trading days',
            'oos_method': 'Rolling with periodic refit, recursive h propagation for GARCH',
        },
        'references': [
            'Corsi (2009) - A simple approximate long-memory model of realized volatility, J. Financial Econometrics',
            'Andersen, Bollerslev, Diebold (2007) - Roughing it up, RES',
            'Hansen & Lunde (2005) - A forecast comparison of volatility models, J. Applied Econometrics',
            'Patton (2011) - Volatility forecast comparison using imperfect proxies, J. Econometrics',
            'Barndorff-Nielsen & Shephard (2004) - Power/bipower variation, J. Financial Econometrics',
            'Harvey, Leybourne, Newbold (2016) - Testing the equality of prediction MSEs',
        ],
        'descriptive_stats': desc,
        'track_A': track_a,
        'track_B': track_b,
        'summary': summary,
        'elapsed_seconds': round(elapsed, 1),
    }

    out_path = os.path.join(SCRIPT_DIR, 'k849_har_rv_taifex_results.json')
    with open(out_path, 'w') as f:
        json.dump(results_json, f, indent=2, default=str)
    print(f"\n  Results saved to {out_path}")


if __name__ == '__main__':
    main()
