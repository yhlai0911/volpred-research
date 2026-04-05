#!/usr/bin/env python3
"""
K848: TAIFEX TX 5-Min Realized Volatility vs GJR-GARCH Daily Forecast
======================================================================

Purpose:
  Build 5-minute Realized Volatility (RV) from TAIFEX TX tick data as a
  high-frequency proxy for true volatility, then compare GJR-GARCH daily
  forecasts evaluated against (a) r² (noisy proxy) vs (b) 5-min RV (precise).

Methodology:
  1. From TX tick data → 5-min bars (last-tick close per 5-min interval)
  2. RV_day = Σ(5min_return²)  for day session (08:45-13:45)
  3. RV_night = Σ(5min_return²) for night session (15:00-05:00)
  4. RV_total = RV_day + RV_night
  5. Bipower Variation (BPV) = (π/2) × Σ|r_i| × |r_{i-1}| (jump-robust)
  6. GJR-GARCH on 0050.TW daily → σ² forecast
  7. QLIKE = mean(σ²/target + log(target) - 1 - log(σ²))
     evaluated on target ∈ {r², RV_day, RV_total}

Time boundaries:
  - Night PM: 150000 <= time <= 235959
  - Night AM: 0 <= time <= 50000
  - Day: 84500 <= time <= 134500
  - Night session started 2017-05-15 (first file with night ticks: 2017-05-16)

Error log rules applied:
  - 0050.TW: must use clean_tw50_data
  - DM test: use volpred.stats.model_evaluation.strategy_dm_test (or scipy for simple)
  - GARCH OOS: recursive h[t]=f(h[t-1], r²[t-1])
  - Student-t scale: sqrt((df-2)/df)

References:
  - Hansen & Lunde (2005): 5-min RV as gold standard for evaluating vol forecasts
  - Patton (2011): QLIKE is proxy-robust for σ² ranking
  - Andersen & Bollerslev (1998): Answering the Skeptics - RV as realized measure
  - Barndorff-Nielsen & Shephard (2004): Bipower variation for jump detection

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

warnings.filterwarnings('ignore')

# ============================================================
# Configuration
# ============================================================
DATA_DIR = "/Users/yhlai0911/Dropbox/TAIFEXDATA/TAIFEXDATA/python"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BAR_INTERVAL_MIN = 5  # 5-minute bars

# Night session: PM (15:00-23:59) + AM (00:00-05:00)
# Day session: 08:45-13:45
NIGHT_PM_START = 150000
NIGHT_PM_END = 235959
NIGHT_AM_START = 0
NIGHT_AM_END = 50000
DAY_START = 84500
DAY_END = 134500


# ============================================================
# Step 1: Build 5-min bars from tick data
# ============================================================

def time_to_5min_bucket(time_int, session):
    """
    Convert HHMMSS integer to a 5-minute bucket label.
    For night session, we need chronological ordering:
      PM: 150000, 150500, ..., 235500
      AM: 000000, 000500, ..., 045500
    For day session:
      084500, 085000, ..., 134000
    """
    h = time_int // 10000
    m = (time_int % 10000) // 100
    # Round down to 5-min boundary
    m5 = (m // 5) * 5
    bucket = h * 100 + m5
    return bucket


def process_single_file(filepath):
    """
    Process one TX file → compute 5-min RV for day and night sessions.
    Returns dict with date, RV_day, RV_night, RV_total, BPV_day, BPV_night, n_bars, etc.
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

    # Parse columns
    try:
        df['time_int'] = pd.to_numeric(df.iloc[:, 3], errors='coerce').astype('Int64')
        df['price'] = pd.to_numeric(df.iloc[:, 4], errors='coerce')
        df = df.dropna(subset=['price', 'time_int'])
        df['time_int'] = df['time_int'].astype(int)
    except Exception:
        return None

    if len(df) < 10:
        return None

    # If this is a TX file (all contracts), filter to near-month (most volume)
    if 'TX1' not in basename and 'TX2' not in basename:
        # Use delivery month column (column 2)
        df['delivery'] = df.iloc[:, 2].astype(str).str.strip()
        vol_by_delivery = df.groupby('delivery')['price'].count()
        if len(vol_by_delivery) > 0:
            near_month = vol_by_delivery.idxmax()
            df = df[df['delivery'] == near_month]

    # Classify sessions
    t = df['time_int'].values
    p = df['price'].values

    night_pm_mask = (t >= NIGHT_PM_START) & (t <= NIGHT_PM_END)
    night_am_mask = (t >= NIGHT_AM_START) & (t <= NIGHT_AM_END)
    day_mask = (t >= DAY_START) & (t <= DAY_END)

    result = {'date': date_str}

    # Process each session
    for session_name, mask in [('day', day_mask), ('night_pm', night_pm_mask), ('night_am', night_am_mask)]:
        session_t = t[mask]
        session_p = p[mask]
        if len(session_t) < 5:
            result[f'n_ticks_{session_name}'] = len(session_t)
            continue

        # Build 5-min bars: for each 5-min bucket, take the last price
        buckets = np.array([time_to_5min_bucket(ti, session_name) for ti in session_t])
        unique_buckets = np.unique(buckets)

        bar_closes = []
        for b in unique_buckets:
            bucket_mask = buckets == b
            # Last price in this 5-min window
            bar_closes.append(session_p[bucket_mask][-1])

        bar_closes = np.array(bar_closes, dtype=float)
        result[f'n_bars_{session_name}'] = len(bar_closes)
        result[f'n_ticks_{session_name}'] = len(session_t)

        if len(bar_closes) >= 2:
            # 5-min log returns
            log_returns = np.diff(np.log(bar_closes))
            result[f'returns_{session_name}'] = log_returns
        else:
            result[f'returns_{session_name}'] = np.array([])

    # Combine night PM + AM returns chronologically
    night_pm_rets = result.get('returns_night_pm', np.array([]))
    night_am_rets = result.get('returns_night_am', np.array([]))

    if len(night_pm_rets) > 0 or len(night_am_rets) > 0:
        # Night session: PM first, then AM
        night_rets = np.concatenate([night_pm_rets, night_am_rets])
        n_night_bars = result.get('n_bars_night_pm', 0) + result.get('n_bars_night_am', 0)
    else:
        night_rets = np.array([])
        n_night_bars = 0

    day_rets = result.get('returns_day', np.array([]))
    n_day_bars = result.get('n_bars_day', 0)

    # Compute RV = Σ(r²)
    rv_day = np.sum(day_rets ** 2) if len(day_rets) > 0 else np.nan
    rv_night = np.sum(night_rets ** 2) if len(night_rets) > 0 else np.nan

    # Compute Bipower Variation = (π/2) × Σ|r_i| × |r_{i-1}|
    if len(day_rets) >= 2:
        bpv_day = (np.pi / 2) * np.sum(np.abs(day_rets[1:]) * np.abs(day_rets[:-1]))
    else:
        bpv_day = np.nan

    if len(night_rets) >= 2:
        bpv_night = (np.pi / 2) * np.sum(np.abs(night_rets[1:]) * np.abs(night_rets[:-1]))
    else:
        bpv_night = np.nan

    # RV total
    if not np.isnan(rv_day) and not np.isnan(rv_night):
        rv_total = rv_day + rv_night
        bpv_total = (bpv_day if not np.isnan(bpv_day) else 0) + (bpv_night if not np.isnan(bpv_night) else 0)
    elif not np.isnan(rv_day):
        rv_total = rv_day
        bpv_total = bpv_day
    elif not np.isnan(rv_night):
        rv_total = rv_night
        bpv_total = bpv_night
    else:
        rv_total = np.nan
        bpv_total = np.nan

    # Jump component: J = RV - BPV (positive = jump detected)
    if not np.isnan(rv_total) and not np.isnan(bpv_total):
        jump = max(rv_total - bpv_total, 0)
    else:
        jump = np.nan

    # Day session open/close for daily return calculation
    day_t_sorted = t[day_mask]
    day_p_sorted = p[day_mask]
    if len(day_p_sorted) >= 2:
        day_open = float(day_p_sorted[0])
        day_close = float(day_p_sorted[-1])
        day_return = np.log(day_close / day_open)
    else:
        day_open = np.nan
        day_close = np.nan
        day_return = np.nan

    return {
        'date': date_str,
        'rv_day': float(rv_day) if not np.isnan(rv_day) else None,
        'rv_night': float(rv_night) if not np.isnan(rv_night) else None,
        'rv_total': float(rv_total) if not np.isnan(rv_total) else None,
        'bpv_day': float(bpv_day) if not np.isnan(bpv_day) else None,
        'bpv_night': float(bpv_night) if not np.isnan(bpv_night) else None,
        'bpv_total': float(bpv_total) if not np.isnan(bpv_total) else None,
        'jump': float(jump) if not np.isnan(jump) else None,
        'n_day_bars': n_day_bars,
        'n_night_bars': n_night_bars,
        'n_day_ticks': result.get('n_ticks_day', 0),
        'n_night_ticks': (result.get('n_ticks_night_pm', 0) + result.get('n_ticks_night_am', 0)),
        'day_open': float(day_open) if not np.isnan(day_open) else None,
        'day_close': float(day_close) if not np.isnan(day_close) else None,
        'day_return': float(day_return) if not np.isnan(day_return) else None,
    }


def load_all_rv_data():
    """Load all TX files (2017-05-16+) and compute 5-min RV using parallel processing."""
    # Use TX (all contracts) for maximum tick density
    # TX1 is near-month only which is fine too - let's use TX1 for cleanliness
    pattern = os.path.join(DATA_DIR, "Daily_*TX1.csv")
    all_files = sorted(glob.glob(pattern))

    # Filter to 2017-05-16+ (night session era)
    files = [f for f in all_files if os.path.basename(f) >= "Daily_2017_05_16"]
    print(f"  Found {len(files)} TX1 files from 2017-05-16")

    results = []
    errors = 0

    # Use ProcessPoolExecutor for parallel processing
    n_workers = min(8, os.cpu_count() or 4)
    print(f"  Using {n_workers} workers for parallel processing...")

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
# Step 2: Descriptive Statistics
# ============================================================

def rv_descriptive_stats(rv_df):
    """Compute descriptive statistics for RV measures."""
    stats = {}
    for col in ['rv_day', 'rv_night', 'rv_total', 'bpv_total', 'jump']:
        s = rv_df[col].dropna()
        if len(s) < 10:
            continue
        # Annualize: RV is already in return² units, annualize by × 252
        ann_factor = 252
        stats[col] = {
            'mean': float(s.mean()),
            'std': float(s.std()),
            'median': float(s.median()),
            'skew': float(s.skew()),
            'kurtosis': float(s.kurtosis()),
            'min': float(s.min()),
            'max': float(s.max()),
            'q25': float(s.quantile(0.25)),
            'q75': float(s.quantile(0.75)),
            'n': len(s),
            # Annualized vol = sqrt(RV * 252) as percentage
            'ann_vol_mean_pct': float(np.sqrt(s.mean() * ann_factor) * 100),
            'ann_vol_median_pct': float(np.sqrt(s.median() * ann_factor) * 100),
        }
    return stats


# ============================================================
# Step 3: Night vs Day RV analysis
# ============================================================

def night_vs_day_analysis(rv_df):
    """Analyze the proportion of volatility in night vs day session."""
    valid = rv_df.dropna(subset=['rv_day', 'rv_night', 'rv_total'])
    valid = valid[valid['rv_total'] > 0]

    night_share = valid['rv_night'] / valid['rv_total']
    day_share = valid['rv_day'] / valid['rv_total']

    result = {
        'n_days': len(valid),
        'night_share_mean': float(night_share.mean()),
        'night_share_median': float(night_share.median()),
        'night_share_std': float(night_share.std()),
        'day_share_mean': float(day_share.mean()),
        'day_share_median': float(day_share.median()),
        'rv_day_mean': float(valid['rv_day'].mean()),
        'rv_night_mean': float(valid['rv_night'].mean()),
        'rv_total_mean': float(valid['rv_total'].mean()),
        # Annualized
        'ann_vol_day_pct': float(np.sqrt(valid['rv_day'].mean() * 252) * 100),
        'ann_vol_night_pct': float(np.sqrt(valid['rv_night'].mean() * 252) * 100),
        'ann_vol_total_pct': float(np.sqrt(valid['rv_total'].mean() * 252) * 100),
    }

    # Yearly breakdown
    yearly = {}
    for year, group in valid.groupby(valid.index.year):
        if len(group) < 20:
            continue
        ns = group['rv_night'] / group['rv_total']
        yearly[str(year)] = {
            'night_share_mean': round(float(ns.mean()), 4),
            'n_days': len(group),
            'ann_vol_total_pct': round(float(np.sqrt(group['rv_total'].mean() * 252) * 100), 2),
        }
    result['yearly'] = yearly

    return result


# ============================================================
# Step 4: Compare with daily r² proxy
# ============================================================

def compare_rv_vs_r2(rv_df):
    """Compare 5-min RV with daily r² as volatility proxies."""
    from scipy import stats as sp_stats

    valid = rv_df.dropna(subset=['rv_day', 'rv_total', 'day_return'])
    valid = valid[valid['rv_total'] > 0]

    # r² = (log return)²
    r_squared = valid['day_return'] ** 2

    result = {}

    # Correlation between RV and r²
    for rv_col, label in [('rv_day', 'RV_day'), ('rv_total', 'RV_total')]:
        rv = valid[rv_col]
        corr_pearson = float(rv.corr(r_squared))
        corr_spearman, sp_p = sp_stats.spearmanr(rv, r_squared)
        ratio = r_squared / rv
        ratio_clean = ratio.replace([np.inf, -np.inf], np.nan).dropna()

        result[label] = {
            'corr_pearson_vs_r2': round(corr_pearson, 4),
            'corr_spearman_vs_r2': round(float(corr_spearman), 4),
            'spearman_p': float(sp_p),
            'ratio_r2_over_rv_mean': round(float(ratio_clean.mean()), 4),
            'ratio_r2_over_rv_median': round(float(ratio_clean.median()), 4),
            'ratio_r2_over_rv_std': round(float(ratio_clean.std()), 4),
        }

    # Key insight: r² is a noisy estimate of σ²
    # If RV_total ≈ true σ², then r²/RV_total tells us how noisy r² is
    result['noise_ratio'] = {
        'description': 'r²/RV_total distribution: if r² were perfect, ratio≈1',
        'mean': result['RV_total']['ratio_r2_over_rv_mean'],
        'median': result['RV_total']['ratio_r2_over_rv_median'],
    }

    return result


# ============================================================
# Step 5: GJR-GARCH comparison with different targets
# ============================================================

def gjr_garch_comparison(rv_df):
    """
    Fit GJR-GARCH on 0050.TW daily returns, then evaluate QLIKE
    against different targets: r², RV_day, RV_total.
    """
    import yfinance as yf
    from arch import arch_model

    # Add volpred to path for clean_tw50_data
    sys.path.insert(0, os.path.join(os.path.dirname(SCRIPT_DIR), 'src'))
    from volpred.utils import clean_tw50_data

    print("  Downloading 0050.TW data...")
    tw50 = yf.download('0050.TW', start='2016-01-01', end='2026-04-03', progress=False)
    if isinstance(tw50.columns, pd.MultiIndex):
        tw50.columns = tw50.columns.get_level_values(0)

    prices = tw50['Close'].dropna()
    prices, _ = clean_tw50_data(prices)

    # Log returns in percentage (for arch package)
    log_returns = np.log(prices / prices.shift(1)).dropna() * 100

    # Align dates with TX RV data
    # TX dates are Taiwan market dates, 0050.TW dates are also Taiwan
    common_dates = rv_df.index.intersection(log_returns.index)
    print(f"  Common dates: {len(common_dates)} ({common_dates.min()} to {common_dates.max()})")

    if len(common_dates) < 200:
        print("  WARNING: Too few common dates for meaningful analysis")
        return None

    # Filter to common dates
    rv_common = rv_df.loc[common_dates].copy()
    ret_common = log_returns.loc[common_dates].copy()

    # --- Full-sample GJR-GARCH fit ---
    print("  Fitting GJR-GARCH(1,1) on full sample...")
    model = arch_model(ret_common, vol='GARCH', p=1, o=1, q=1, dist='t')
    try:
        res = model.fit(disp='off')
    except Exception as e:
        print(f"  GJR-GARCH fit failed: {e}")
        return None

    print(f"  Parameters: omega={res.params.get('omega', 0):.6f}, "
          f"alpha={res.params.get('alpha[1]', 0):.6f}, "
          f"gamma={res.params.get('gamma[1]', 0):.6f}, "
          f"beta={res.params.get('beta[1]', 0):.6f}")
    persistence = res.params.get('alpha[1]', 0) + 0.5 * res.params.get('gamma[1]', 0) + res.params.get('beta[1]', 0)
    print(f"  Persistence: {persistence:.4f}")

    # Conditional variance (in %² units, so divide by 10000 for decimal²)
    cond_var_pct2 = res.conditional_volatility ** 2  # in %² units
    sigma2 = cond_var_pct2 / 10000  # convert to decimal² for comparison with RV

    # --- Prepare targets ---
    # r² in decimal² units
    r_squared = (ret_common / 100) ** 2  # convert % return back to decimal, then square

    targets = {
        'r_squared': r_squared,
        'rv_day': rv_common['rv_day'],
        'rv_total': rv_common['rv_total'],
    }

    # --- QLIKE computation ---
    # QLIKE = mean(target/σ² - log(target/σ²) - 1)
    # Or equivalently: mean(target/σ² + log(σ²) - log(target) - 1)
    # Lower is better
    qlike_results = {}
    for target_name, target in targets.items():
        valid_mask = target.notna() & (target > 0) & sigma2.notna() & (sigma2 > 0)
        valid_idx = target.index[valid_mask]

        if len(valid_idx) < 100:
            print(f"    {target_name}: Too few valid observations ({len(valid_idx)})")
            continue

        t_vals = target.loc[valid_idx].values
        s_vals = sigma2.loc[valid_idx].values

        # QLIKE
        qlike = np.mean(t_vals / s_vals - np.log(t_vals / s_vals) - 1)

        # MSE (for reference)
        mse = np.mean((t_vals - s_vals) ** 2)

        # MAE
        mae = np.mean(np.abs(t_vals - s_vals))

        # Correlation
        corr = float(np.corrcoef(t_vals, s_vals)[0, 1])

        # Spearman
        from scipy import stats as sp_stats
        spearman_r, spearman_p = sp_stats.spearmanr(t_vals, s_vals)

        # R² (coefficient of determination)
        ss_res = np.sum((t_vals - s_vals) ** 2)
        ss_tot = np.sum((t_vals - np.mean(t_vals)) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan

        # Mean ratio
        mean_ratio = np.mean(s_vals) / np.mean(t_vals)

        qlike_results[target_name] = {
            'qlike': round(float(qlike), 6),
            'mse': float(mse),
            'mae': float(mae),
            'corr_pearson': round(corr, 4),
            'corr_spearman': round(float(spearman_r), 4),
            'spearman_p': float(spearman_p),
            'r_squared': round(float(r2), 4) if not np.isnan(r2) else None,
            'mean_ratio_sigma2_over_target': round(float(mean_ratio), 4),
            'n_obs': len(valid_idx),
            'mean_target': float(np.mean(t_vals)),
            'mean_sigma2': float(np.mean(s_vals)),
        }

        print(f"    {target_name}: QLIKE={qlike:.6f}, corr={corr:.4f}, "
              f"Spearman={spearman_r:.4f}, n={len(valid_idx)}")

    # --- Rolling OOS evaluation ---
    print("\n  Running rolling OOS GJR-GARCH (500-day window)...")
    window = 500
    oos_start_idx = window
    if len(ret_common) <= oos_start_idx + 50:
        print("  Not enough data for OOS")
        return {'in_sample': qlike_results, 'model_params': {
            'omega': float(res.params.get('omega', 0)),
            'alpha': float(res.params.get('alpha[1]', 0)),
            'gamma': float(res.params.get('gamma[1]', 0)),
            'beta': float(res.params.get('beta[1]', 0)),
            'persistence': float(persistence),
            'nu': float(res.params.get('nu', 0)),
        }}

    # Refit every 63 days (quarterly), but propagate variance daily
    refit_interval = 63
    oos_sigma2 = pd.Series(index=ret_common.index[oos_start_idx:], dtype=float)

    last_fit = None
    last_omega = None
    last_alpha = None
    last_gamma = None
    last_beta = None
    last_h = None

    for i in range(oos_start_idx, len(ret_common)):
        # Refit?
        if last_fit is None or (i - last_fit) >= refit_interval:
            train_data = ret_common.iloc[max(0, i - window):i]
            try:
                m = arch_model(train_data, vol='GARCH', p=1, o=1, q=1, dist='t')
                r = m.fit(disp='off')
                last_omega = r.params.get('omega', last_omega)
                last_alpha = r.params.get('alpha[1]', last_alpha)
                last_gamma = r.params.get('gamma[1]', last_gamma)
                last_beta = r.params.get('beta[1]', last_beta)
                # Get last conditional variance from fit
                last_h = r.conditional_volatility.iloc[-1] ** 2  # in %²
                last_fit = i
            except Exception:
                pass  # Keep using previous params

        if last_omega is None:
            continue

        # Propagate: h[t] = omega + alpha*r²[t-1] + gamma*r²[t-1]*I(r<0) + beta*h[t-1]
        r_prev = float(ret_common.iloc[i - 1])  # in % units
        r_prev_sq = r_prev ** 2
        indicator = 1.0 if r_prev < 0 else 0.0

        h_t = last_omega + last_alpha * r_prev_sq + last_gamma * r_prev_sq * indicator + last_beta * last_h
        last_h = h_t

        # Convert to decimal² (from %²)
        oos_sigma2.iloc[i - oos_start_idx] = h_t / 10000

    oos_sigma2 = oos_sigma2.dropna()
    print(f"  OOS predictions: {len(oos_sigma2)} days")

    # Evaluate OOS
    oos_qlike = {}
    for target_name, target in targets.items():
        common = oos_sigma2.index.intersection(target.dropna().index)
        common = common[target.loc[common] > 0]
        if len(common) < 50:
            continue

        t_vals = target.loc[common].values
        s_vals = oos_sigma2.loc[common].values
        valid = (t_vals > 0) & (s_vals > 0) & np.isfinite(t_vals) & np.isfinite(s_vals)
        t_vals = t_vals[valid]
        s_vals = s_vals[valid]

        if len(t_vals) < 50:
            continue

        qlike = np.mean(t_vals / s_vals - np.log(t_vals / s_vals) - 1)
        corr = float(np.corrcoef(t_vals, s_vals)[0, 1])
        spearman_r, _ = sp_stats.spearmanr(t_vals, s_vals)

        oos_qlike[target_name] = {
            'qlike': round(float(qlike), 6),
            'corr_pearson': round(corr, 4),
            'corr_spearman': round(float(spearman_r), 4),
            'n_obs': len(t_vals),
            'mean_target': float(np.mean(t_vals)),
            'mean_sigma2': float(np.mean(s_vals)),
        }

        print(f"    OOS {target_name}: QLIKE={qlike:.6f}, corr={corr:.4f}, "
              f"Spearman={spearman_r:.4f}, n={len(t_vals)}")

    return {
        'in_sample': qlike_results,
        'out_of_sample': oos_qlike,
        'model_params': {
            'omega': float(res.params.get('omega', 0)),
            'alpha': float(res.params.get('alpha[1]', 0)),
            'gamma': float(res.params.get('gamma[1]', 0)),
            'beta': float(res.params.get('beta[1]', 0)),
            'persistence': float(persistence),
            'nu': float(res.params.get('nu', 0)),
        },
        'oos_window': window,
        'oos_refit_interval': refit_interval,
    }


# ============================================================
# Step 6: Jump detection analysis
# ============================================================

def jump_analysis(rv_df):
    """Analyze jump component (RV - BPV) and its properties."""
    valid = rv_df.dropna(subset=['rv_total', 'bpv_total', 'jump'])
    valid = valid[valid['rv_total'] > 0]

    jump_share = valid['jump'] / valid['rv_total']

    # Jump days: RV - BPV > 0 (already floored at 0 in process_single_file)
    jump_days = valid[valid['jump'] > 0]
    no_jump_days = valid[valid['jump'] == 0]

    result = {
        'n_total': len(valid),
        'n_jump_days': len(jump_days),
        'jump_frequency': round(len(jump_days) / len(valid), 4),
        'jump_share_mean': round(float(jump_share.mean()), 4),
        'jump_share_median': round(float(jump_share.median()), 4),
        'jump_rv_mean': float(jump_days['jump'].mean()) if len(jump_days) > 0 else None,
        'continuous_rv_mean': float(valid['bpv_total'].mean()),
        'ann_continuous_vol_pct': round(float(np.sqrt(valid['bpv_total'].mean() * 252) * 100), 2),
        'ann_jump_vol_pct': round(float(np.sqrt(valid['jump'].mean() * 252) * 100), 2),
    }

    return result


# ============================================================
# Main
# ============================================================

def main():
    print("=" * 70)
    print("K848: TAIFEX TX 5-Min Realized Volatility vs GJR-GARCH")
    print("=" * 70)

    # Step 1: Build 5-min RV from tick data
    print("\n[Step 1] Building 5-min RV from TX1 tick data...")
    t0 = datetime.now()
    rv_df = load_all_rv_data()
    t1 = datetime.now()
    elapsed = (t1 - t0).total_seconds()
    print(f"  Completed in {elapsed:.1f}s, shape: {rv_df.shape}")
    print(f"  Date range: {rv_df.index.min()} to {rv_df.index.max()}")

    # Quality check
    print(f"\n  Data quality:")
    for col in ['rv_day', 'rv_night', 'rv_total', 'n_day_bars', 'n_night_bars']:
        s = rv_df[col].dropna()
        print(f"    {col}: n={len(s)}, mean={s.mean():.6f}" +
              (f", median={s.median():.6f}" if col.startswith('rv') else f", median={s.median():.0f}"))

    # Step 2: Descriptive statistics
    print("\n[Step 2] Descriptive Statistics:")
    desc_stats = rv_descriptive_stats(rv_df)
    for col, stats in desc_stats.items():
        print(f"\n  {col}:")
        print(f"    Mean:     {stats['mean']:.8f}")
        print(f"    Median:   {stats['median']:.8f}")
        print(f"    Std:      {stats['std']:.8f}")
        print(f"    Skew:     {stats['skew']:.4f}")
        print(f"    Kurtosis: {stats['kurtosis']:.4f}")
        print(f"    Ann Vol (mean):   {stats['ann_vol_mean_pct']:.2f}%")
        print(f"    Ann Vol (median): {stats['ann_vol_median_pct']:.2f}%")
        print(f"    N:        {stats['n']}")

    # Step 3: Night vs Day RV
    print("\n[Step 3] Night vs Day Session Volatility:")
    night_day = night_vs_day_analysis(rv_df)
    print(f"  Night share of total RV: {night_day['night_share_mean']*100:.1f}% (mean), "
          f"{night_day['night_share_median']*100:.1f}% (median)")
    print(f"  Day share of total RV:   {night_day['day_share_mean']*100:.1f}% (mean)")
    print(f"  Annualized vol (day):    {night_day['ann_vol_day_pct']:.2f}%")
    print(f"  Annualized vol (night):  {night_day['ann_vol_night_pct']:.2f}%")
    print(f"  Annualized vol (total):  {night_day['ann_vol_total_pct']:.2f}%")
    print(f"\n  Yearly breakdown:")
    for year, ystats in sorted(night_day.get('yearly', {}).items()):
        print(f"    {year}: night_share={ystats['night_share_mean']*100:.1f}%, "
              f"ann_vol={ystats['ann_vol_total_pct']:.1f}%, n={ystats['n_days']}")

    # Step 4: Compare RV vs r²
    print("\n[Step 4] RV vs r² Comparison:")
    rv_vs_r2 = compare_rv_vs_r2(rv_df)
    for label, stats in rv_vs_r2.items():
        if label == 'noise_ratio':
            print(f"  Noise ratio (r²/RV_total): mean={stats['mean']:.4f}, median={stats['median']:.4f}")
        else:
            print(f"  {label} vs r²: Pearson={stats['corr_pearson_vs_r2']:.4f}, "
                  f"Spearman={stats['corr_spearman_vs_r2']:.4f}")

    # Step 5: GJR-GARCH comparison
    print("\n[Step 5] GJR-GARCH(1,1) vs Different Targets:")
    garch_results = gjr_garch_comparison(rv_df)

    # Step 6: Jump analysis
    print("\n[Step 6] Jump Detection (RV - BPV):")
    jumps = jump_analysis(rv_df)
    print(f"  Jump frequency: {jumps['jump_frequency']*100:.1f}% of days")
    print(f"  Jump share of total RV: {jumps['jump_share_mean']*100:.1f}% (mean), "
          f"{jumps['jump_share_median']*100:.1f}% (median)")
    print(f"  Continuous vol (BPV):    {jumps['ann_continuous_vol_pct']:.2f}% ann.")
    print(f"  Jump vol:                {jumps['ann_jump_vol_pct']:.2f}% ann.")

    # ============================================================
    # Compile results
    # ============================================================
    final_results = {
        "experiment_id": "K848",
        "title": "TAIFEX TX 5-Min Realized Volatility vs GJR-GARCH Daily Forecast",
        "date": "2026-04-03",
        "data_source": "TAIFEX TX tick data (TX1 near-month) + 0050.TW (yfinance, clean_tw50_data applied)",
        "data_period": f"{rv_df.index.min().strftime('%Y-%m-%d')} to {rv_df.index.max().strftime('%Y-%m-%d')}",
        "n_trading_days": int(len(rv_df)),
        "methodology": {
            "5min_bars": "Last-tick close per 5-min interval",
            "rv": "RV = Σ(5min_log_return²)",
            "bpv": "BPV = (π/2) × Σ|r_i|×|r_{i-1}| (Barndorff-Nielsen & Shephard 2004)",
            "jump": "J = max(RV - BPV, 0)",
            "garch": "GJR-GARCH(1,1) with Student-t innovations on 0050.TW daily log returns",
            "qlike": "QLIKE = mean(target/σ² - log(target/σ²) - 1) (Patton 2011)",
            "oos": "Rolling 500-day window, refit every 63 days, daily h[t] propagation",
        },
        "descriptive_stats": {k: {kk: round(vv, 8) if isinstance(vv, float) else vv
                                   for kk, vv in v.items()}
                              for k, v in desc_stats.items()},
        "night_vs_day": night_day,
        "rv_vs_r2": rv_vs_r2,
        "garch_comparison": garch_results,
        "jump_analysis": jumps,
        "bar_stats": {
            'mean_day_bars': round(float(rv_df['n_day_bars'].mean()), 1),
            'mean_night_bars': round(float(rv_df['n_night_bars'].mean()), 1),
            'mean_day_ticks': round(float(rv_df['n_day_ticks'].mean()), 0),
            'mean_night_ticks': round(float(rv_df['n_night_ticks'].mean()), 0),
        },
        "references": [
            "Hansen & Lunde (2005): A forecast comparison of volatility models: Does anything beat a GARCH(1,1)?",
            "Patton (2011): Volatility forecast comparison using imperfect volatility proxies. JoE 160(1)",
            "Andersen & Bollerslev (1998): Answering the Skeptics: Yes, Standard Volatility Models Do Provide Accurate Forecasts. IER 39(4)",
            "Barndorff-Nielsen & Shephard (2004): Power and bipower variation with stochastic volatility and jumps. JFE 2(1)",
        ],
        "limitations": [
            "TX futures != 0050.TW ETF (basis risk, leverage, different tick sizes)",
            "Night session ticks can be thin (01:00-04:00), affecting bar quality",
            "Microstructure noise not corrected (kernel-based RV would be more robust)",
            "BPV assumes no consecutive jumps",
            "TX1 rollover not modeled (near-month switches monthly)",
            "Only 8.8 years of night session data (since 2017-05-16)",
        ],
        "conclusion": "",  # filled below
    }

    # Build conclusion
    conclusion_parts = []

    # Night share
    ns = night_day['night_share_mean']
    conclusion_parts.append(f"Night session accounts for {ns*100:.1f}% of total RV (consistent with K844 return finding)")

    # RV vs r² noise
    if 'RV_total' in rv_vs_r2:
        nr = rv_vs_r2['noise_ratio']
        conclusion_parts.append(f"r² is very noisy proxy: r²/RV_total ratio mean={nr['mean']:.2f} (should be ~1 if perfect)")

    # QLIKE comparison
    if garch_results and 'in_sample' in garch_results:
        is_qlike = garch_results['in_sample']
        if 'r_squared' in is_qlike and 'rv_total' in is_qlike:
            q_r2 = is_qlike['r_squared']['qlike']
            q_rv = is_qlike['rv_total']['qlike']
            conclusion_parts.append(
                f"In-sample QLIKE: on r²={q_r2:.4f}, on RV_total={q_rv:.4f} "
                f"({'RV better' if q_rv < q_r2 else 'r² better'})"
            )

    if garch_results and 'out_of_sample' in garch_results:
        oos = garch_results['out_of_sample']
        if 'r_squared' in oos and 'rv_total' in oos:
            q_r2 = oos['r_squared']['qlike']
            q_rv = oos['rv_total']['qlike']
            conclusion_parts.append(
                f"OOS QLIKE: on r²={q_r2:.4f}, on RV_total={q_rv:.4f} "
                f"({'RV better' if q_rv < q_r2 else 'r² better'})"
            )

    # Jump analysis
    conclusion_parts.append(f"Jump component: {jumps['jump_share_mean']*100:.1f}% of total RV, "
                          f"frequency={jumps['jump_frequency']*100:.1f}%")

    final_results['conclusion'] = " | ".join(conclusion_parts)

    # Save results
    results_path = os.path.join(SCRIPT_DIR, "k848_taifex_5min_rv_results.json")
    with open(results_path, 'w', encoding='utf-8') as f:
        json.dump(final_results, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n{'='*70}")
    print(f"CONCLUSION:")
    for part in conclusion_parts:
        print(f"  • {part}")
    print(f"{'='*70}")
    print(f"\nResults saved to: {results_path}")

    return final_results


if __name__ == "__main__":
    results = main()
