#!/usr/bin/env python3
"""
K853: Proxy Ceiling Ablation — Isolate Proxy Choice Effect on HAR vs GJR Ranking
=================================================================================

Purpose:
  Codex adversarial review (H1) of K849: K849 simultaneously changed target
  (r² → RV), window (rolling 2000 → expanding 500), and sample (2006+ → 2017+).
  Cannot attribute HAR's win to any single factor.

  This ablation fixes ALL conditions identical to K849 Track A, and ONLY varies
  the evaluation target across three conditions:
    Condition A: QLIKE on r² (daily squared return) — noisy proxy
    Condition B: QLIKE on RV_day (5-min day-session RV) — precise proxy
    Condition C: QLIKE on RV_total (day + night 5-min RV) — most complete proxy

  If HAR wins in Condition A (r² target) → proxy is NOT the cause, HAR is genuinely better
  If HAR only wins in B/C → proxy ceiling CONFIRMED (r² noise masks true differences)

Fixed conditions (identical to K849 Track A):
  - Asset: 0050.TW daily returns (GJR) + TAIFEX TX 5-min RV (HAR + evaluation)
  - IS: 2012-2019, OOS: 2020-2024
  - Window: expanding (500-day minimum)
  - Refit: every 63 trading days
  - Models: HAR-RV and GJR-GARCH(1,1) Student-t (same estimation, only eval target changes)

Error log rules applied:
  - 0050.TW: must use clean_tw50_data
  - DM test: Newey-West HAC
  - GARCH OOS: recursive h[t]=f(h[t-1], r²[t-1])
  - Student-t: scale term sqrt((df-2)/df)

References:
  - Corsi (2009) - HAR-RV model, J. Financial Econometrics
  - Hansen & Lunde (2005) - Forecast comparison with 5-min RV, J. Applied Econometrics
  - Patton (2011) - QLIKE proxy-robust, J. Econometrics
  - Barndorff-Nielsen & Shephard (2004) - Bipower variation
  - Harvey, Leybourne, Newbold (2016) - DM test, t>3.0 threshold

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
# Configuration — FIXED for ablation (same as K849 Track A)
# ============================================================
DATA_DIR = "/Users/yhlai0911/Dropbox/TAIFEXDATA/TAIFEXDATA/python"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

IS_START = '2012-01-01'
IS_END = '2019-12-31'
OOS_START = '2020-01-01'
OOS_END = '2025-12-31'
MIN_TRAIN = 500       # expanding window minimum
REFIT_FREQ = 63       # refit every 63 trading days

# Session boundaries (HHMMSS)
NIGHT_PM_START = 150000
NIGHT_PM_END = 235959
NIGHT_AM_START = 0
NIGHT_AM_END = 50000
DAY_START = 84500
DAY_END = 134500


# ============================================================
# Step 1: Build 5-min RV from tick data (reused from K849)
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
    elif not np.isnan(rv_day):
        rv_total = rv_day
    else:
        rv_total = np.nan

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
        'day_return': day_return if not np.isnan(day_return) else None,
    }


def load_all_rv_data():
    """Load TX1 files and compute 5-min RV using parallel processing."""
    pattern = os.path.join(DATA_DIR, "Daily_*TX1.csv")
    all_files = sorted(glob.glob(pattern))

    cutoff = f"Daily_{IS_START.replace('-', '_')}"
    files = [f for f in all_files if os.path.basename(f) >= cutoff]
    files = [f for f in files if os.path.basename(f) < "Daily_2026"]
    print(f"  Found {len(files)} TX1 files from {IS_START} to end 2025")

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
# Step 2: HAR-RV OOS forecast (expanding window)
# ============================================================

def fit_har_ols(y, X):
    """OLS fit: y = X @ beta + e. Returns beta."""
    n = len(y)
    X_c = np.column_stack([np.ones(n), X])
    try:
        beta = np.linalg.lstsq(X_c, y, rcond=None)[0]
        return beta
    except Exception:
        return None


def har_oos_forecast(rv_series, oos_start):
    """
    Expanding-window OOS forecast for HAR-RV.
    Uses RV_day as the predictor (HAR on day-session RV).
    Refit every REFIT_FREQ days, minimum MIN_TRAIN observations.
    """
    rv = rv_series.values.copy()
    dates = rv_series.index
    n = len(rv)

    oos_idx = np.searchsorted(dates, pd.Timestamp(oos_start))
    if oos_idx < MIN_TRAIN:
        oos_idx = MIN_TRAIN

    forecasts = np.full(n, np.nan)
    last_beta = None
    last_fit_idx = -REFIT_FREQ

    for t in range(oos_idx, n):
        # Refit periodically (expanding window)
        if t - last_fit_idx >= REFIT_FREQ or last_beta is None:
            train_rv = rv[:t]
            if len(train_rv) < MIN_TRAIN:
                continue

            # Build HAR features: RV_{t-1}, RV_{t-5:t}, RV_{t-22:t}
            rv_d = np.full(t, np.nan)
            rv_w = np.full(t, np.nan)
            rv_m = np.full(t, np.nan)
            for i in range(1, t):
                rv_d[i] = train_rv[i - 1]
            for i in range(5, t):
                rv_w[i] = np.mean(train_rv[i - 5:i])
            for i in range(22, t):
                rv_m[i] = np.mean(train_rv[i - 22:i])

            feat = np.column_stack([rv_d, rv_w, rv_m])
            valid_mask = ~np.any(np.isnan(feat), axis=1) & ~np.isnan(train_rv)
            if np.sum(valid_mask) < 50:
                continue

            y_train = train_rv[valid_mask]
            X_train = feat[valid_mask]

            beta = fit_har_ols(y_train, X_train)
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

        x_t = np.array([1, rv_d_t, rv_w_t, rv_m_t])
        forecast = x_t @ last_beta
        forecasts[t] = max(forecast, 1e-10)  # Floor at small positive

    return pd.Series(forecasts, index=dates, name='HAR-RV')


# ============================================================
# Step 3: GJR-GARCH on 0050.TW (expanding window)
# ============================================================

def fit_gjr_garch_oos(rv_df, oos_start):
    """
    Fit GJR-GARCH(1,1) Student-t on 0050.TW daily log returns.
    OOS: recursive h[t] = omega + (alpha + gamma*I_{t-1}) * r²[t-1] + beta * h[t-1]
    Returns forecasts (in decimal variance) and r-squared series.
    """
    import arch

    sys.path.insert(0, os.path.join(SCRIPT_DIR, '..', 'src'))
    from volpred.utils import clean_tw50_data
    import yfinance as yf

    start_yr = rv_df.index.min().year - 1
    raw = yf.download('0050.TW', start=f'{start_yr}-01-01', end='2026-01-01', progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

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
    if oos_idx < MIN_TRAIN:
        oos_idx = MIN_TRAIN

    forecasts = pd.Series(np.nan, index=common_dates, name='GJR-GARCH')
    r_squared = pd.Series(returns_raw.values ** 2, index=common_dates, name='r_squared')

    last_params = None
    last_fit_idx = -REFIT_FREQ
    last_h = None

    for t in range(oos_idx, len(common_dates)):
        if t - last_fit_idx >= REFIT_FREQ or last_params is None:
            train = returns_pct.iloc[:t]  # expanding window
            if len(train) < MIN_TRAIN:
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
                    last_h = res.conditional_volatility.iloc[-1] ** 2
                    last_fit_idx = t
            except Exception:
                pass

        if last_params is None or last_h is None:
            continue

        # Recursive: h[t] = omega + (alpha + gamma*I) * r²[t-1] + beta * h[t-1]
        r_prev = returns_pct.iloc[t - 1]
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
    """EWMA: h[t] = lambda * h[t-1] + (1-lambda) * r²[t-1]"""
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


def qlike_loss_series(target, forecast):
    """Per-observation QLIKE loss for DM test."""
    t = np.asarray(target, dtype=float)
    f = np.asarray(forecast, dtype=float)
    ratio = t / f
    loss = ratio - np.log(ratio) - 1
    loss[~np.isfinite(loss)] = np.nan
    loss[(t <= 0) | (f <= 0)] = np.nan
    return loss


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
# Step 6: Evaluate one condition
# ============================================================

def evaluate_condition(condition_name, target_series, model_forecasts, common_dates):
    """
    Evaluate all models against a given target on common OOS dates.
    Returns metrics dict and loss series for DM tests.
    """
    # Further restrict to dates where target is valid
    valid_target = target_series.reindex(common_dates).dropna()
    valid_target = valid_target[valid_target > 0]
    eval_dates = valid_target.index

    # Further restrict to dates where all forecasts are valid
    for mn, fc in model_forecasts.items():
        fc_valid = fc.reindex(eval_dates).dropna()
        fc_valid = fc_valid[fc_valid > 0]
        eval_dates = eval_dates.intersection(fc_valid.index)

    eval_dates = eval_dates.sort_values()
    n_eval = len(eval_dates)

    print(f"\n  Condition {condition_name}: {n_eval} evaluation dates")

    if n_eval < 30:
        print(f"  WARNING: Too few dates for {condition_name}!")
        return None

    target = target_series.loc[eval_dates].values
    print(f"  Target: mean={np.mean(target):.2e}, std={np.std(target):.2e}")

    metrics = {}
    loss_dict = {}

    for mn, fc in model_forecasts.items():
        fc_vals = fc.loc[eval_dates].values
        q = qlike(target, fc_vals)
        m = mse_metric(target, fc_vals)
        ma = mae_metric(target, fc_vals)
        rho, p = spearman_corr(target, fc_vals)

        metrics[mn] = {
            'QLIKE': round(q, 6) if not np.isnan(q) else None,
            'MSE': float(f"{m:.4e}") if not np.isnan(m) else None,
            'MAE': float(f"{ma:.4e}") if not np.isnan(ma) else None,
            'Spearman': round(rho, 4) if not np.isnan(rho) else None,
            'Spearman_p': round(p, 6) if not np.isnan(p) else None,
            'n_eval': n_eval,
        }
        loss_dict[mn] = qlike_loss_series(target, fc_vals)

        print(f"    {mn:12s}: QLIKE={q:.6f}  MSE={m:.2e}  Spearman={rho:.4f}")

    # DM tests: HAR-RV vs GJR-GARCH (primary), HAR-RV vs EWMA, GJR-GARCH vs EWMA
    dm_results = {}
    model_names = list(model_forecasts.keys())
    for i in range(len(model_names)):
        for j in range(i + 1, len(model_names)):
            m1, m2 = model_names[i], model_names[j]
            t_stat, p_val = dm_test(loss_dict[m1], loss_dict[m2])
            key = f"{m1} vs {m2}"
            sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else "")
            winner = m1 if t_stat < 0 else m2
            dm_results[key] = {
                't_stat': round(t_stat, 4),
                'p_value': round(p_val, 6),
                'winner': winner,
                'significant_harvey': abs(t_stat) > 3.0,
            }
            print(f"    DM {key}: t={t_stat:.3f} p={p_val:.4f} -> {winner} {sig}")

    # QLIKE ranking
    ranked = sorted(metrics.items(), key=lambda x: x[1]['QLIKE'] if x[1]['QLIKE'] is not None else float('inf'))
    ranking = {r[0]: i+1 for i, r in enumerate(ranked)}
    print(f"    Ranking: {ranking}")

    return {
        'condition': condition_name,
        'n_eval': n_eval,
        'metrics': metrics,
        'dm_tests': dm_results,
        'ranking': ranking,
    }


# ============================================================
# Main execution
# ============================================================

def main():
    t0 = datetime.now()
    print("=" * 70)
    print("K853: Proxy Ceiling Ablation")
    print("  Fixed: IS 2012-2019, OOS 2020-2024+, expanding 500, refit 63")
    print("  Variable: evaluation target only")
    print("=" * 70)

    # ================================================================
    # 1. Load 5-min RV data
    # ================================================================
    print("\n[1/4] Loading TX1 tick data (2012+)...")
    rv_df = load_all_rv_data()
    print(f"  Total days: {len(rv_df)}, range: {rv_df.index[0].date()} to {rv_df.index[-1].date()}")

    # Descriptive stats
    desc = {}
    for col in ['rv_day', 'rv_total', 'day_return']:
        s = rv_df[col].dropna()
        if len(s) < 10:
            continue
        desc[col] = {
            'n': int(len(s)),
            'mean': float(s.mean()),
            'std': float(s.std()),
            'median': float(s.median()),
        }
        if col == 'day_return':
            desc[col]['r2_mean'] = float((s**2).mean())
            desc[col]['r2_std'] = float((s**2).std())

    # r-squared series from TX day return (to be used as evaluation target)
    r2_tx = (rv_df['day_return'] ** 2).dropna()
    r2_tx = r2_tx[r2_tx > 0]
    r2_tx.name = 'r_squared_tx'

    # ================================================================
    # 2. Fit models (ONCE — same for all conditions)
    # ================================================================
    print("\n[2/4] Fitting models (fixed for all conditions)...")

    # HAR-RV on rv_day
    rv_day = rv_df['rv_day'].dropna()
    print("  HAR-RV on rv_day...")
    fc_har = har_oos_forecast(rv_day, OOS_START)
    n_har = fc_har.dropna().shape[0]
    print(f"    HAR-RV: {n_har} OOS forecasts")

    # GJR-GARCH on 0050.TW
    print("  GJR-GARCH on 0050.TW...")
    fc_garch, r_squared_etf = fit_gjr_garch_oos(rv_df, OOS_START)
    n_garch = fc_garch.dropna().shape[0]
    print(f"    GJR-GARCH: {n_garch} OOS forecasts")

    # EWMA on ETF r-squared
    print("  EWMA on ETF r-squared...")
    fc_ewma = ewma_forecast(r_squared_etf, lam=0.94)
    n_ewma = fc_ewma.dropna().shape[0]
    print(f"    EWMA: {n_ewma} OOS forecasts")

    model_forecasts = {
        'HAR-RV': fc_har,
        'GJR-GARCH': fc_garch,
        'EWMA': fc_ewma,
    }

    # ================================================================
    # 3. Find common OOS dates (across ALL models)
    # ================================================================
    oos_start_ts = pd.Timestamp(OOS_START)
    oos_end_ts = pd.Timestamp(OOS_END)

    # Common dates where ALL models have valid forecasts
    common_dates = rv_day.index[(rv_day.index >= oos_start_ts) & (rv_day.index <= oos_end_ts)]
    for mn, fc in model_forecasts.items():
        valid = fc.dropna().index
        common_dates = common_dates.intersection(valid)
    common_dates = common_dates.sort_values()
    print(f"\n  Common OOS dates (all models valid): {len(common_dates)}")

    if len(common_dates) < 50:
        print("  FATAL: Too few common dates!")
        return

    # ================================================================
    # 4. Evaluate three conditions (ONLY thing that changes)
    # ================================================================
    print("\n[3/4] Evaluating three conditions (only evaluation target varies)...")

    # Build target series aligned to common dates
    # Condition A: r² from TX day return (same-market squared return)
    target_r2 = r2_tx.reindex(common_dates)

    # Condition B: RV_day (5-min day-session RV)
    target_rv_day = rv_df['rv_day'].reindex(common_dates)

    # Condition C: RV_total (day + night 5-min RV) — only available post 2017-05
    target_rv_total = rv_df['rv_total'].reindex(common_dates)

    cond_a = evaluate_condition(
        'A: r² (squared return)',
        target_r2,
        model_forecasts,
        common_dates,
    )

    cond_b = evaluate_condition(
        'B: RV_day (5-min day RV)',
        target_rv_day,
        model_forecasts,
        common_dates,
    )

    cond_c = evaluate_condition(
        'C: RV_total (5-min day+night RV)',
        target_rv_total,
        model_forecasts,
        common_dates,
    )

    # ================================================================
    # 5. Causal analysis: does proxy choice flip the ranking?
    # ================================================================
    print("\n[4/4] Causal analysis...")
    print("=" * 70)

    conditions = {'A': cond_a, 'B': cond_b, 'C': cond_c}

    # Check: does HAR-RV beat GJR-GARCH in ALL conditions?
    har_beats_gjr = {}
    for cname, cond in conditions.items():
        if cond is None:
            har_beats_gjr[cname] = None
            continue
        har_rank = cond['ranking'].get('HAR-RV', 99)
        gjr_rank = cond['ranking'].get('GJR-GARCH', 99)
        har_q = cond['metrics']['HAR-RV']['QLIKE']
        gjr_q = cond['metrics']['GJR-GARCH']['QLIKE']

        # Also check DM test significance
        dm_key = 'HAR-RV vs GJR-GARCH'
        dm = cond['dm_tests'].get(dm_key, {})
        dm_sig = dm.get('significant_harvey', False)
        dm_winner = dm.get('winner', '')

        har_beats_gjr[cname] = {
            'har_rank': har_rank,
            'gjr_rank': gjr_rank,
            'har_qlike': har_q,
            'gjr_qlike': gjr_q,
            'delta_pct': round(((gjr_q - har_q) / gjr_q) * 100, 2) if (har_q and gjr_q) else None,
            'dm_t': dm.get('t_stat'),
            'dm_p': dm.get('p_value'),
            'dm_significant': dm_sig,
            'dm_winner': dm_winner,
            'har_wins': har_rank < gjr_rank,
        }

    # Determine causal conclusion
    a_result = har_beats_gjr.get('A', {})
    b_result = har_beats_gjr.get('B', {})
    c_result = har_beats_gjr.get('C', {})

    if a_result and a_result.get('har_wins'):
        conclusion = "PROXY NOT THE CAUSE: HAR beats GJR even on r² target. Model is genuinely better."
        proxy_ceiling = False
    elif (not a_result or not a_result.get('har_wins')) and b_result and b_result.get('har_wins'):
        conclusion = "PROXY CEILING CONFIRMED: HAR only beats GJR on RV targets, not on r². Noise in r² masks true differences."
        proxy_ceiling = True
    else:
        conclusion = "INCONCLUSIVE: Need further investigation."
        proxy_ceiling = None

    # Check if the margin changes significantly across conditions
    margins = {}
    for cname, result in har_beats_gjr.items():
        if result and result.get('delta_pct') is not None:
            margins[cname] = result['delta_pct']

    print(f"\n  HAR-RV vs GJR-GARCH across conditions:")
    for cname, result in har_beats_gjr.items():
        if result:
            print(f"    Condition {cname}: HAR QLIKE={result['har_qlike']:.6f}, GJR QLIKE={result['gjr_qlike']:.6f}, "
                  f"delta={result['delta_pct']:+.1f}%, DM t={result['dm_t']:.3f} {'***' if result['dm_significant'] else ''}")
        else:
            print(f"    Condition {cname}: N/A")

    print(f"\n  CONCLUSION: {conclusion}")

    # ================================================================
    # Save results
    # ================================================================
    t1 = datetime.now()
    elapsed = (t1 - t0).total_seconds()

    results_json = {
        'experiment_id': 'K853',
        'title': 'Proxy Ceiling Ablation: Isolate proxy choice effect on HAR vs GJR ranking',
        'date': '2026-04-03',
        'data_source': 'TAIFEX TX1 tick data (5-min RV) + 0050.TW (yfinance, clean_tw50_data applied)',
        'data_period': f'{IS_START} to {OOS_END}',
        'methodology': {
            'design': 'Ablation: fix all conditions, only vary evaluation target',
            'fixed_conditions': {
                'IS': f'{IS_START} to {IS_END}',
                'OOS': f'{OOS_START} to {OOS_END}',
                'window': f'expanding (min {MIN_TRAIN} days)',
                'refit': f'every {REFIT_FREQ} trading days',
                'models': 'HAR-RV (Corsi 2009) on RV_day, GJR-GARCH(1,1) Student-t on 0050.TW, EWMA lambda=0.94',
            },
            'variable': 'Evaluation target: r² (Condition A), RV_day (B), RV_total (C)',
            'causal_question': 'Does proxy choice (r² vs RV) flip the HAR vs GJR ranking?',
            'metrics': 'QLIKE (Patton 2011), MSE, MAE, Spearman',
            'dm_test': 'Newey-West HAC, Harvey (2016) |t|>3.0',
        },
        'references': [
            'Corsi (2009) - HAR-RV model, J. Financial Econometrics',
            'Hansen & Lunde (2005) - Forecast comparison with 5-min RV, J. Applied Econometrics',
            'Patton (2011) - QLIKE proxy-robust, J. Econometrics',
            'Harvey, Leybourne, Newbold (2016) - DM test threshold',
        ],
        'descriptive_stats': desc,
        'n_common_oos': len(common_dates),
        'oos_date_range': f'{common_dates[0].date()} to {common_dates[-1].date()}',
        'conditions': {
            'A_r_squared': cond_a,
            'B_rv_day': cond_b,
            'C_rv_total': cond_c,
        },
        'causal_analysis': {
            'har_vs_gjr_by_condition': har_beats_gjr,
            'margins_pct': margins,
            'proxy_ceiling_confirmed': proxy_ceiling,
            'conclusion': conclusion,
        },
        'runtime_seconds': round(elapsed, 1),
    }

    out_path = os.path.join(SCRIPT_DIR, 'k853_proxy_ablation_results.json')
    with open(out_path, 'w') as f:
        json.dump(results_json, f, indent=2, default=str)
    print(f"\n  Results saved to {out_path}")
    print(f"  Total time: {elapsed:.1f}s")


if __name__ == '__main__':
    main()
