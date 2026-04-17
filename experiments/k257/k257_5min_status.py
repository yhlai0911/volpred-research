"""
K257: 5-Minute Data Accumulation Status and HAR-RV Readiness Check
===================================================================
[提出: User, 執行: Claude]

Background:
- K188 proved the ceiling is in DATA, not MODEL
- K196 showed 5-min RV has AC(1)=0.414 vs c2c AC(1)=-0.118
- We have been accumulating 5-min data via daily cron
- This experiment checks: how much data do we have? Is it enough for HAR-RV?

Data source: yfinance 5-min bars, collected daily by scripts/collect_5min_data.py
             and scripts/collect_tw_data.py (0050.TW)
Storage: data/intraday/{ticker}_5min_YYYY-MM-DD.csv

Methodology:
1. Inventory all 5-min data files (tickers, days, gaps, quality)
2. Compute daily RV, BPV, Jump Variation from SPY 5-min returns
3. Autocorrelation structure of RV vs c2c squared returns
4. If >= 60 days: fit HAR-RV and compare with GARCH
5. If >= 90 days: rolling OOS test
6. Report readiness status and projected dates
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
from scipy import stats

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
_main_repo = Path("/Users/yhlai0911/Desktop/volpred-research")
DATA_DIR = _main_repo / "data" / "intraday"
_repo_root = Path(__file__).resolve().parent.parent
STORAGE_DIR = _repo_root / "storage" / "experiments"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)


# ===========================================================================
# PART 1: DATA INVENTORY
# ===========================================================================

def inventory_5min_data():
    """Scan all 5-min CSV files, report per-ticker statistics."""
    files = sorted(DATA_DIR.glob("*_5min_*.csv"))

    ticker_files = defaultdict(list)
    for f in files:
        # Parse filename: {TICKER}_5min_YYYY-MM-DD.csv
        parts = f.stem.split("_5min_")
        if len(parts) != 2:
            continue
        ticker_raw = parts[0]
        date_str = parts[1]
        try:
            date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        ticker_files[ticker_raw].append((date, f))

    print("=" * 70)
    print("PART 1: 5-MINUTE DATA INVENTORY")
    print("=" * 70)

    inventory = {}
    for ticker, date_files in sorted(ticker_files.items()):
        dates = sorted([d for d, _ in date_files])

        # Detect gaps (weekdays without data)
        gaps = []
        for i in range(len(dates) - 1):
            curr = dates[i]
            nxt = dates[i + 1]
            delta = (nxt - curr).days
            # Count weekdays between curr and nxt
            weekday_gap = sum(1 for d in range(1, delta)
                           if (curr + timedelta(days=d)).weekday() < 5)
            if weekday_gap > 0:
                gaps.append({
                    'from': str(curr),
                    'to': str(nxt),
                    'missing_weekdays': weekday_gap
                })

        # Count bars per day (quality check)
        bar_counts = []
        zero_vol_days = 0
        for d, f in sorted(date_files, key=lambda x: x[0]):
            try:
                df = pd.read_csv(f, skiprows=2)
                df.columns = ["Datetime", "Close", "High", "Low", "Open", "Volume"]
                bar_counts.append(len(df))
                vol = pd.to_numeric(df["Volume"], errors="coerce")
                if (vol == 0).all():
                    zero_vol_days += 1
            except Exception:
                bar_counts.append(0)

        total_missing_weekdays = sum(g['missing_weekdays'] for g in gaps)

        info = {
            'ticker': ticker,
            'n_days': len(dates),
            'start': str(dates[0]),
            'end': str(dates[-1]),
            'calendar_span': (dates[-1] - dates[0]).days,
            'n_gaps': len(gaps),
            'total_missing_weekdays': total_missing_weekdays,
            'gap_details': gaps if len(gaps) <= 5 else gaps[:3] + [{'...': f'{len(gaps)-3} more gaps'}],
            'bars_per_day': {
                'mean': np.mean(bar_counts),
                'min': int(np.min(bar_counts)),
                'max': int(np.max(bar_counts)),
                'std': np.std(bar_counts),
            },
            'zero_volume_days': zero_vol_days,
        }
        inventory[ticker] = info

        print(f"\n--- {ticker} ---")
        print(f"  Trading days:     {info['n_days']}")
        print(f"  Date range:       {info['start']} to {info['end']}")
        print(f"  Calendar span:    {info['calendar_span']} days")
        print(f"  Gaps:             {info['n_gaps']} gaps ({total_missing_weekdays} missing weekdays)")
        if gaps:
            for g in gaps[:5]:
                if '...' not in g:
                    print(f"    Gap: {g['from']} -> {g['to']} ({g['missing_weekdays']} weekday(s))")
        print(f"  Bars/day:         mean={info['bars_per_day']['mean']:.1f}, "
              f"min={info['bars_per_day']['min']}, max={info['bars_per_day']['max']}")
        print(f"  Zero-volume days: {zero_vol_days}")

    return inventory


# ===========================================================================
# PART 2: COMPUTE RV / BPV / JUMP FROM 5-MIN DATA
# ===========================================================================

def load_all_5min(ticker="SPY"):
    """Load all 5-min data for a ticker, return combined DataFrame."""
    safe_ticker = ticker.replace(".", "_")
    files = sorted(DATA_DIR.glob(f"{safe_ticker}_5min_*.csv"))

    all_data = []
    for f in files:
        try:
            df = pd.read_csv(f, skiprows=2)
            df.columns = ["Datetime", "Close", "High", "Low", "Open", "Volume"]
            df["Datetime"] = pd.to_datetime(df["Datetime"])
            df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
            df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce")
            df = df.dropna(subset=["Close"])
            all_data.append(df)
        except Exception as e:
            print(f"  Warning: failed to read {f.name}: {e}")

    if not all_data:
        return pd.DataFrame()

    combined = pd.concat(all_data, ignore_index=True)
    combined = combined.sort_values("Datetime").reset_index(drop=True)
    return combined


def compute_daily_rv_bpv(df_5min):
    """Compute daily Realized Variance, Bipower Variation, Jump Variation.

    RV_t = sum(r_{i,t}^2)  where r are 5-min log returns
    BPV_t = (pi/2) * sum(|r_{i,t}| * |r_{i-1,t}|)   (Barndorff-Nielsen & Shephard 2004)
    JV_t = max(RV_t - BPV_t, 0)  (jump component)
    """
    df = df_5min.copy()
    df['date'] = df['Datetime'].dt.date
    df['log_ret'] = np.log(df['Close'] / df['Close'].shift(1))

    results = []
    for date, group in df.groupby('date'):
        rets = group['log_ret'].dropna().values
        n = len(rets)
        if n < 5:  # Need minimum bars
            continue

        # Realized Variance
        rv = np.sum(rets ** 2)

        # Bipower Variation (BPV)
        # BPV = (pi/2) * sum(|r_i| * |r_{i-1}|) for i = 2, ..., n
        abs_rets = np.abs(rets)
        bpv = (np.pi / 2) * np.sum(abs_rets[1:] * abs_rets[:-1])

        # Jump Variation
        jv = max(rv - bpv, 0)

        # Jump test statistic (Huang & Tauchen 2005)
        # z = (RV - BPV) / RV * sqrt(n / (2.62 * max_rv_contribution))
        # Simplified: relative jump
        jump_ratio = jv / rv if rv > 0 else 0

        results.append({
            'date': date,
            'rv': rv,
            'bpv': bpv,
            'jv': jv,
            'jump_ratio': jump_ratio,
            'n_bars': n,
            'rv_ann': rv * 252,          # Annualized
            'vol_ann': np.sqrt(rv * 252),  # Annualized vol
        })

    return pd.DataFrame(results).set_index('date').sort_index()


# ===========================================================================
# PART 3: AUTOCORRELATION AND COMPARISON WITH C2C
# ===========================================================================

def compute_c2c_data(ticker="SPY"):
    """Get daily close-to-close returns from yfinance cache or download."""
    import yfinance as yf

    # Download enough daily data to cover our 5-min period
    data = yf.download(ticker, period="1y", progress=False)
    if hasattr(data.columns, 'levels'):  # MultiIndex
        data.columns = data.columns.get_level_values(0)

    data['ret'] = data['Close'].pct_change()
    data['r2'] = data['ret'] ** 2  # Close-to-close squared return
    data['log_ret'] = np.log(data['Close'] / data['Close'].shift(1))
    data['log_r2'] = data['log_ret'] ** 2

    return data


def autocorrelation_analysis(rv_df, c2c_data, max_lag=10):
    """Compare autocorrelation structure of RV vs c2c r^2."""
    print("\n" + "=" * 70)
    print("PART 3: AUTOCORRELATION STRUCTURE")
    print("=" * 70)

    rv_series = rv_df['rv'].dropna()

    # Align c2c data with RV dates
    rv_dates = rv_df.index
    c2c_r2 = c2c_data['log_r2'].dropna()
    c2c_r2.index = c2c_r2.index.date if hasattr(c2c_r2.index, 'date') else c2c_r2.index

    # Only keep overlapping dates
    common_dates = sorted(set(rv_dates) & set(c2c_r2.index))
    if len(common_dates) < 20:
        print(f"  WARNING: Only {len(common_dates)} overlapping dates. Results may be unreliable.")

    rv_aligned = rv_series.loc[common_dates]
    c2c_aligned = c2c_r2.loc[common_dates]

    print(f"\n  Overlapping trading days: {len(common_dates)}")
    print(f"  Period: {common_dates[0]} to {common_dates[-1]}")

    # Autocorrelations
    print(f"\n  {'Lag':>5} | {'RV AC':>10} | {'c2c r^2 AC':>12} | {'BPV AC':>10}")
    print(f"  {'-'*5} | {'-'*10} | {'-'*12} | {'-'*10}")

    ac_rv = []
    ac_c2c = []
    ac_bpv = []
    bpv_series = rv_df['bpv'].loc[common_dates] if 'bpv' in rv_df.columns else None

    for lag in range(1, min(max_lag + 1, len(common_dates) // 3)):
        ac_r = rv_aligned.autocorr(lag=lag) if len(rv_aligned) > lag + 1 else np.nan
        ac_c = c2c_aligned.autocorr(lag=lag) if len(c2c_aligned) > lag + 1 else np.nan
        ac_b = bpv_series.autocorr(lag=lag) if bpv_series is not None and len(bpv_series) > lag + 1 else np.nan

        ac_rv.append(ac_r)
        ac_c2c.append(ac_c)
        ac_bpv.append(ac_b)

        print(f"  {lag:5d} | {ac_r:10.4f} | {ac_c:12.4f} | {ac_b:10.4f}")

    # Correlation between RV and c2c r^2
    corr = np.corrcoef(rv_aligned.values, c2c_aligned.values)[0, 1]
    r2_stat = corr ** 2

    print(f"\n  Correlation(RV, c2c_r2):  {corr:.4f}")
    print(f"  R^2(RV, c2c_r2):          {r2_stat:.4f}")

    # Summary stats
    print(f"\n  --- Summary Statistics ---")
    print(f"  {'':>20} | {'5-min RV':>12} | {'c2c r^2':>12} | {'BPV':>12}")
    print(f"  {'Mean':>20} | {rv_aligned.mean():12.6f} | {c2c_aligned.mean():12.6f} | {rv_df['bpv'].loc[common_dates].mean():12.6f}")
    print(f"  {'Std':>20} | {rv_aligned.std():12.6f} | {c2c_aligned.std():12.6f} | {rv_df['bpv'].loc[common_dates].std():12.6f}")
    print(f"  {'Skewness':>20} | {rv_aligned.skew():12.4f} | {c2c_aligned.skew():12.4f} | {rv_df['bpv'].loc[common_dates].skew():12.4f}")
    print(f"  {'Kurtosis':>20} | {rv_aligned.kurtosis():12.4f} | {c2c_aligned.kurtosis():12.4f} | {rv_df['bpv'].loc[common_dates].kurtosis():12.4f}")

    # Annualized vol comparison
    mean_rv_vol = np.sqrt(rv_aligned.mean() * 252) * 100
    mean_c2c_vol = np.sqrt(c2c_aligned.mean() * 252) * 100
    print(f"\n  Annualized vol (from mean):")
    print(f"    5-min RV:  {mean_rv_vol:.2f}%")
    print(f"    c2c r^2:   {mean_c2c_vol:.2f}%")

    return {
        'ac_rv': ac_rv,
        'ac_c2c': ac_c2c,
        'ac_bpv': ac_bpv,
        'corr_rv_c2c': float(corr),
        'r2_rv_c2c': float(r2_stat),
        'n_common_days': len(common_dates),
    }


# ===========================================================================
# PART 4: HAR-RV MODEL (if >= 60 days)
# ===========================================================================

def fit_har_rv(rv_df, min_days=60):
    """Fit HAR-RV model and evaluate OOS performance.

    HAR-RV(1,5,22):
        RV_{t+1} = beta_0 + beta_1 * RV_t + beta_5 * RV_weekly + beta_22 * RV_monthly + eps

    where RV_weekly = mean(RV_{t-4:t}), RV_monthly = mean(RV_{t-21:t})
    """
    print("\n" + "=" * 70)
    print("PART 4: HAR-RV MODEL")
    print("=" * 70)

    rv = rv_df['rv'].values
    bpv = rv_df['bpv'].values
    n = len(rv)

    if n < min_days:
        print(f"\n  INSUFFICIENT DATA: {n} days < {min_days} minimum")
        print(f"  Need {min_days - n} more days for HAR-RV estimation")
        return None

    # Construct HAR regressors
    # Need at least 22 days for monthly component
    rv_daily = rv[21:]       # RV_{t}
    rv_target = rv[22:]      # RV_{t+1}

    # Weekly average: mean of past 5 days
    rv_weekly = np.array([np.mean(rv[i:i+5]) for i in range(17, n-5)])
    # Monthly average: mean of past 22 days
    rv_monthly = np.array([np.mean(rv[i:i+22]) for i in range(0, n-22)])

    # Align: all should have same length
    T = min(len(rv_target), len(rv_daily), len(rv_weekly), len(rv_monthly))
    rv_target = rv_target[:T]
    rv_d = rv_daily[:T]
    rv_w = rv_weekly[:T]
    rv_m = rv_monthly[:T]

    # Also do BPV version: HAR-BPV
    bpv_daily = bpv[21:][:T]
    bpv_weekly = np.array([np.mean(bpv[i:i+5]) for i in range(17, n-5)])[:T]
    bpv_monthly = np.array([np.mean(bpv[i:i+22]) for i in range(0, n-22)])[:T]

    print(f"\n  Total observations: {n} days")
    print(f"  Usable for HAR(1,5,22): {T} days (after 22-day lookback)")

    # --- Full-sample estimation ---
    X_har = np.column_stack([np.ones(T), rv_d, rv_w, rv_m])
    X_har_bpv = np.column_stack([np.ones(T), bpv_daily, bpv_weekly, bpv_monthly])

    # OLS for HAR-RV
    beta_rv = np.linalg.lstsq(X_har, rv_target, rcond=None)[0]
    resid_rv = rv_target - X_har @ beta_rv

    # OLS for HAR-BPV
    beta_bpv = np.linalg.lstsq(X_har_bpv, rv_target, rcond=None)[0]
    resid_bpv = rv_target - X_har_bpv @ beta_bpv

    print(f"\n  --- HAR-RV Full-Sample Coefficients ---")
    print(f"  beta_0 (const):    {beta_rv[0]:.8f}")
    print(f"  beta_1 (daily):    {beta_rv[1]:.4f}")
    print(f"  beta_5 (weekly):   {beta_rv[2]:.4f}")
    print(f"  beta_22 (monthly): {beta_rv[3]:.4f}")

    r2_is = 1 - np.sum(resid_rv**2) / np.sum((rv_target - np.mean(rv_target))**2)
    print(f"  In-sample R^2:     {r2_is:.4f}")

    print(f"\n  --- HAR-BPV Full-Sample Coefficients ---")
    print(f"  beta_0 (const):    {beta_bpv[0]:.8f}")
    print(f"  beta_1 (daily):    {beta_bpv[1]:.4f}")
    print(f"  beta_5 (weekly):   {beta_bpv[2]:.4f}")
    print(f"  beta_22 (monthly): {beta_bpv[3]:.4f}")

    r2_bpv_is = 1 - np.sum(resid_bpv**2) / np.sum((rv_target - np.mean(rv_target))**2)
    print(f"  In-sample R^2:     {r2_bpv_is:.4f}")

    # --- Out-of-sample (expanding window) ---
    # Use at least 10 days for training, but no more than T//2
    oos_start = min(max(10, T // 2), T - 5)  # Ensure at least 5 OOS days

    if T - oos_start < 5:
        print(f"\n  WARNING: Only {T - oos_start} OOS days — too few for reliable evaluation")
        print(f"  Proceeding with indicative results only")

    oos_preds_har = []
    oos_preds_bpv = []
    oos_actual = []
    oos_naive = []  # RV(t) as forecast of RV(t+1)

    for t in range(oos_start, T):
        # Expanding window
        X_train = X_har[:t]
        y_train = rv_target[:t]

        beta_t = np.linalg.lstsq(X_train, y_train, rcond=None)[0]
        pred = X_har[t] @ beta_t
        oos_preds_har.append(max(pred, 1e-10))  # Floor at small positive

        # BPV version
        X_train_b = X_har_bpv[:t]
        beta_t_b = np.linalg.lstsq(X_train_b, y_train, rcond=None)[0]
        pred_b = X_har_bpv[t] @ beta_t_b
        oos_preds_bpv.append(max(pred_b, 1e-10))

        oos_actual.append(rv_target[t])
        oos_naive.append(rv_d[t])  # Yesterday's RV

    oos_preds_har = np.array(oos_preds_har)
    oos_preds_bpv = np.array(oos_preds_bpv)
    oos_actual = np.array(oos_actual)
    oos_naive = np.array(oos_naive)

    n_oos = len(oos_actual)

    # Loss functions
    def mse(pred, actual):
        return np.mean((pred - actual) ** 2)

    def qlike(pred, actual):
        """QLIKE loss: mean(actual/pred + log(pred))"""
        pred_safe = np.maximum(pred, 1e-12)
        return np.mean(actual / pred_safe + np.log(pred_safe))

    def mae(pred, actual):
        return np.mean(np.abs(pred - actual))

    mse_har = mse(oos_preds_har, oos_actual)
    mse_bpv = mse(oos_preds_bpv, oos_actual)
    mse_naive = mse(oos_naive, oos_actual)

    qlike_har = qlike(oos_preds_har, oos_actual)
    qlike_bpv = qlike(oos_preds_bpv, oos_actual)
    qlike_naive = qlike(oos_naive, oos_actual)

    mae_har = mae(oos_preds_har, oos_actual)
    mae_bpv = mae(oos_preds_bpv, oos_actual)
    mae_naive = mae(oos_naive, oos_actual)

    r2_oos_har = 1 - np.sum((oos_preds_har - oos_actual)**2) / np.sum((oos_actual - np.mean(oos_actual))**2)
    r2_oos_bpv = 1 - np.sum((oos_preds_bpv - oos_actual)**2) / np.sum((oos_actual - np.mean(oos_actual))**2)
    r2_oos_naive = 1 - np.sum((oos_naive - oos_actual)**2) / np.sum((oos_actual - np.mean(oos_actual))**2)

    print(f"\n  --- OOS Performance ({n_oos} days, expanding window) ---")
    print(f"  {'Model':>12} | {'MSE':>14} | {'QLIKE':>10} | {'MAE':>14} | {'OOS R^2':>10}")
    print(f"  {'-'*12} | {'-'*14} | {'-'*10} | {'-'*14} | {'-'*10}")
    print(f"  {'HAR-RV':>12} | {mse_har:14.2e} | {qlike_har:10.4f} | {mae_har:14.2e} | {r2_oos_har:10.4f}")
    print(f"  {'HAR-BPV':>12} | {mse_bpv:14.2e} | {qlike_bpv:10.4f} | {mae_bpv:14.2e} | {r2_oos_bpv:10.4f}")
    print(f"  {'Naive(RV_t)':>12} | {mse_naive:14.2e} | {qlike_naive:10.4f} | {mae_naive:14.2e} | {r2_oos_naive:10.4f}")

    # Diebold-Mariano test: HAR-RV vs Naive
    e_har = (oos_preds_har - oos_actual) ** 2
    e_naive = (oos_naive - oos_actual) ** 2
    d = e_naive - e_har  # positive = HAR better

    if n_oos > 5:
        dm_stat = np.mean(d) / (np.std(d, ddof=1) / np.sqrt(n_oos))
        dm_pval = 2 * (1 - stats.t.cdf(abs(dm_stat), df=n_oos-1))
    else:
        dm_stat = np.nan
        dm_pval = np.nan

    print(f"\n  DM test (HAR-RV vs Naive):")
    print(f"    t-stat:  {dm_stat:.4f}")
    print(f"    p-value: {dm_pval:.4f}")
    print(f"    HAR-RV {'better' if dm_stat > 0 else 'worse'} than naive (need t > 3.0 for Harvey threshold)")

    return {
        'n_total': int(n),
        'n_usable': int(T),
        'n_oos': int(n_oos),
        'oos_start_idx': int(oos_start),
        'har_rv': {
            'betas': beta_rv.tolist(),
            'r2_is': float(r2_is),
            'mse_oos': float(mse_har),
            'qlike_oos': float(qlike_har),
            'mae_oos': float(mae_har),
            'r2_oos': float(r2_oos_har),
        },
        'har_bpv': {
            'betas': beta_bpv.tolist(),
            'r2_is': float(r2_bpv_is),
            'mse_oos': float(mse_bpv),
            'qlike_oos': float(qlike_bpv),
            'mae_oos': float(mae_bpv),
            'r2_oos': float(r2_oos_bpv),
        },
        'naive': {
            'mse_oos': float(mse_naive),
            'qlike_oos': float(qlike_naive),
            'mae_oos': float(mae_naive),
            'r2_oos': float(r2_oos_naive),
        },
        'dm_test': {
            't_stat': float(dm_stat) if not np.isnan(dm_stat) else None,
            'p_value': float(dm_pval) if not np.isnan(dm_pval) else None,
        }
    }


# ===========================================================================
# PART 5: GJR-GARCH COMPARISON (using c2c returns, target = RV)
# ===========================================================================

def fit_garch_compare(rv_df, c2c_data):
    """Fit GJR-GARCH on c2c returns, evaluate against RV target."""
    print("\n" + "=" * 70)
    print("PART 5: GJR-GARCH vs HAR-RV (with RV as target)")
    print("=" * 70)

    try:
        from arch import arch_model
    except ImportError:
        print("  arch package not available — skipping GARCH comparison")
        return None

    # Align dates
    rv_dates = list(rv_df.index)
    c2c = c2c_data[['log_ret']].dropna().copy()
    c2c.index = c2c.index.date if hasattr(c2c.index, 'date') else c2c.index

    common = sorted(set(rv_dates) & set(c2c.index))
    if len(common) < 40:
        print(f"  Only {len(common)} overlapping dates — not enough for GARCH")
        return None

    c2c_aligned = c2c.loc[common, 'log_ret'].values * 100  # Scale for GARCH
    rv_aligned = rv_df.loc[common, 'rv'].values

    n = len(common)
    oos_start = max(30, n // 2)

    # Expanding window OOS for GARCH
    oos_garch = []
    oos_actual = []

    for t in range(oos_start, n - 1):
        try:
            am = arch_model(c2c_aligned[:t+1], vol='GARCH', p=1, o=1, q=1,
                          mean='Zero', dist='normal')
            res = am.fit(disp='off', show_warning=False)
            fc = res.forecast(horizon=1)
            h = fc.variance.values[-1, 0] / 10000  # Unscale
            oos_garch.append(max(h, 1e-12))
            oos_actual.append(rv_aligned[t + 1])
        except Exception:
            continue

    if len(oos_garch) < 5:
        print("  Too few successful GARCH forecasts")
        return None

    oos_garch = np.array(oos_garch)
    oos_actual_g = np.array(oos_actual)
    n_oos = len(oos_garch)

    def qlike(pred, actual):
        pred_safe = np.maximum(pred, 1e-12)
        return np.mean(actual / pred_safe + np.log(pred_safe))

    mse_g = np.mean((oos_garch - oos_actual_g) ** 2)
    qlike_g = qlike(oos_garch, oos_actual_g)
    mae_g = np.mean(np.abs(oos_garch - oos_actual_g))
    r2_g = 1 - np.sum((oos_garch - oos_actual_g)**2) / np.sum((oos_actual_g - np.mean(oos_actual_g))**2)

    print(f"\n  GJR-GARCH OOS ({n_oos} days, expanding window, target = RV):")
    print(f"    MSE:     {mse_g:.2e}")
    print(f"    QLIKE:   {qlike_g:.4f}")
    print(f"    MAE:     {mae_g:.2e}")
    print(f"    OOS R^2: {r2_g:.4f}")

    return {
        'n_oos': int(n_oos),
        'mse_oos': float(mse_g),
        'qlike_oos': float(qlike_g),
        'mae_oos': float(mae_g),
        'r2_oos': float(r2_g),
    }


# ===========================================================================
# PART 6: JUMP ANALYSIS
# ===========================================================================

def jump_analysis(rv_df):
    """Analyze jump component from BPV decomposition."""
    print("\n" + "=" * 70)
    print("PART 6: JUMP DECOMPOSITION (RV = BPV + JV)")
    print("=" * 70)

    n = len(rv_df)
    mean_rv = rv_df['rv'].mean()
    mean_bpv = rv_df['bpv'].mean()
    mean_jv = rv_df['jv'].mean()

    pct_jump = mean_jv / mean_rv * 100 if mean_rv > 0 else 0

    # Days with significant jumps (JV > 20% of RV)
    sig_jump_days = (rv_df['jump_ratio'] > 0.20).sum()

    print(f"\n  Total days: {n}")
    print(f"\n  Variance decomposition (mean daily):")
    print(f"    RV (total):       {mean_rv:.6f}  (={np.sqrt(mean_rv*252)*100:.2f}% ann)")
    print(f"    BPV (continuous): {mean_bpv:.6f}  ({mean_bpv/mean_rv*100:.1f}% of RV)")
    print(f"    JV (jump):        {mean_jv:.6f}  ({pct_jump:.1f}% of RV)")
    print(f"\n  Days with jump_ratio > 20%: {sig_jump_days}/{n} ({sig_jump_days/n*100:.1f}%)")

    # Top 5 jump days
    top_jumps = rv_df.nlargest(5, 'jv')
    print(f"\n  Top 5 jump days:")
    print(f"    {'Date':>12} | {'RV':>10} | {'JV':>10} | {'Jump%':>8} | {'Vol(ann)':>10}")
    for idx, row in top_jumps.iterrows():
        print(f"    {str(idx):>12} | {row['rv']:10.6f} | {row['jv']:10.6f} | "
              f"{row['jump_ratio']*100:7.1f}% | {row['vol_ann']*100:9.2f}%")

    return {
        'mean_rv': float(mean_rv),
        'mean_bpv': float(mean_bpv),
        'mean_jv': float(mean_jv),
        'jump_pct_of_rv': float(pct_jump),
        'sig_jump_days': int(sig_jump_days),
        'n_days': int(n),
    }


# ===========================================================================
# PART 7: READINESS ASSESSMENT
# ===========================================================================

def readiness_assessment(inventory, rv_df):
    """Assess readiness for various HAR-RV analyses."""
    print("\n" + "=" * 70)
    print("PART 7: HAR-RV READINESS ASSESSMENT")
    print("=" * 70)

    spy_info = inventory.get('SPY', {})
    n_spy = spy_info.get('n_days', 0)
    tw_info = inventory.get('0050_TW', {})
    n_tw = tw_info.get('n_days', 0)

    today = datetime.now().date()

    # Milestones
    milestones = [
        (60,  "HAR-RV basic estimation",           "beta estimates, in-sample R^2"),
        (90,  "Rolling OOS (30-day window)",        "Preliminary OOS comparison"),
        (120, "Rolling OOS (60-day window)",        "More stable OOS estimates"),
        (180, "HAR-RV with jump decomposition",     "Separate continuous/jump components"),
        (252, "Full 1-year sample",                 "Publication-quality HAR-RV vs GARCH"),
        (504, "2-year sample",                      "Multi-regime analysis"),
    ]

    # Estimate trading days per calendar week: ~5/7
    trading_days_per_week = 5 / 7

    print(f"\n  Current status:")
    print(f"    SPY:     {n_spy} days ({spy_info.get('start', '?')} to {spy_info.get('end', '?')})")
    print(f"    0050.TW: {n_tw} days ({tw_info.get('start', '?')} to {tw_info.get('end', '?')})")

    if rv_df is not None:
        n_rv = len(rv_df)
        print(f"    SPY RV computed: {n_rv} days")
    else:
        n_rv = n_spy

    print(f"\n  {'Milestone':>40} | {'Days needed':>12} | {'Status':>10} | {'ETA':>12}")
    print(f"  {'-'*40} | {'-'*12} | {'-'*10} | {'-'*12}")

    collection_start = datetime.strptime(spy_info.get('start', '2026-01-14'), '%Y-%m-%d').date()
    daily_rate = n_spy / max((today - collection_start).days, 1)

    assessment = {}
    for target, label, description in milestones:
        remaining = target - n_spy
        if remaining <= 0:
            status = "READY"
            eta = "now"
        else:
            cal_days_needed = remaining / trading_days_per_week * (7 / 5)
            eta_date = today + timedelta(days=int(cal_days_needed))
            status = "waiting"
            eta = str(eta_date)

        print(f"  {label:>40} | {target:>12} | {status:>10} | {eta:>12}")
        assessment[f'target_{target}'] = {
            'label': label,
            'description': description,
            'target_days': target,
            'current': n_spy,
            'remaining': max(0, remaining),
            'status': status,
            'eta': eta,
        }

    # Data collection rate
    print(f"\n  Collection rate: ~{daily_rate:.2f} trading days/calendar day")
    print(f"  yfinance 5-min limit: ~59 days backfill")
    print(f"  Accumulation started: {spy_info.get('start', '?')}")

    # Current capability
    print(f"\n  Current capabilities:")
    if n_spy >= 252:
        print(f"    [x] Full 1-year HAR-RV estimation + proper OOS")
    elif n_spy >= 90:
        print(f"    [x] Rolling OOS with 30-day training window")
        print(f"    [ ] Full 1-year analysis (need {252 - n_spy} more days)")
    elif n_spy >= 60:
        print(f"    [x] HAR-RV basic estimation (expanding window OOS)")
        print(f"    [ ] Proper rolling OOS (need {90 - n_spy} more days)")
    else:
        print(f"    [ ] HAR-RV estimation (need {60 - n_spy} more days)")

    return assessment


# ===========================================================================
# MAIN
# ===========================================================================

def main():
    print("K257: 5-Minute Data Accumulation Status and HAR-RV Readiness Check")
    print("Data source: yfinance 5-min bars (collected daily by cron)")
    print(f"Run date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print()

    results = {
        'experiment': 'K257',
        'title': '5-Minute Data Accumulation Status and HAR-RV Readiness Check',
        'run_date': datetime.now().isoformat(),
        'data_source': 'yfinance 5-min bars via scripts/collect_5min_data.py',
    }

    # Part 1: Inventory
    inventory = inventory_5min_data()
    results['inventory'] = {}
    for k, v in inventory.items():
        results['inventory'][k] = {kk: vv for kk, vv in v.items() if kk != 'gap_details'}
        results['inventory'][k]['gap_count'] = v['n_gaps']

    # Part 2: Compute RV/BPV from raw 5-min data for SPY
    print("\n" + "=" * 70)
    print("PART 2: COMPUTING DAILY RV / BPV / JUMP FROM 5-MIN DATA")
    print("=" * 70)

    df_5min = load_all_5min("SPY")
    if len(df_5min) > 0:
        rv_df = compute_daily_rv_bpv(df_5min)
        print(f"\n  Computed RV for {len(rv_df)} trading days")
        print(f"  Date range: {rv_df.index[0]} to {rv_df.index[-1]}")

        # Compare with pre-computed RV file
        rv_file = DATA_DIR / "SPY_daily_rv.csv"
        if rv_file.exists():
            rv_precomputed = pd.read_csv(rv_file, index_col=0, parse_dates=True)
            print(f"  Pre-computed RV file: {len(rv_precomputed)} days")

        # Summary table
        print(f"\n  {'Date':>12} | {'RV':>12} | {'BPV':>12} | {'JV':>12} | {'Jump%':>8} | {'#Bars':>6}")
        print(f"  {'-'*12} | {'-'*12} | {'-'*12} | {'-'*12} | {'-'*8} | {'-'*6}")
        # Show first 5 and last 5
        display_idx = list(range(min(5, len(rv_df)))) + list(range(max(5, len(rv_df)-5), len(rv_df)))
        display_idx = sorted(set(display_idx))
        prev_i = -1
        for i in display_idx:
            if prev_i >= 0 and i - prev_i > 1:
                print(f"  {'... ':>12} | {'...':>12} | {'...':>12} | {'...':>12} | {'...':>8} | {'...':>6}")
            row = rv_df.iloc[i]
            print(f"  {str(rv_df.index[i]):>12} | {row['rv']:12.6f} | {row['bpv']:12.6f} | "
                  f"{row['jv']:12.6f} | {row['jump_ratio']*100:7.1f}% | {int(row['n_bars']):6d}")
            prev_i = i

        results['rv_stats'] = {
            'n_days': int(len(rv_df)),
            'start': str(rv_df.index[0]),
            'end': str(rv_df.index[-1]),
            'mean_rv': float(rv_df['rv'].mean()),
            'mean_bpv': float(rv_df['bpv'].mean()),
            'mean_jv': float(rv_df['jv'].mean()),
            'annualized_vol': float(np.sqrt(rv_df['rv'].mean() * 252) * 100),
        }
    else:
        rv_df = None
        print("  No 5-min data found for SPY")

    # Part 3: Autocorrelation comparison
    if rv_df is not None and len(rv_df) >= 10:
        c2c_data = compute_c2c_data("SPY")
        ac_results = autocorrelation_analysis(rv_df, c2c_data)
        results['autocorrelation'] = ac_results

    # Part 4: HAR-RV model
    if rv_df is not None:
        har_results = fit_har_rv(rv_df, min_days=25)  # Lower threshold for preliminary
        if har_results:
            results['har_rv'] = har_results

    # Part 5: GARCH comparison
    if rv_df is not None and len(rv_df) >= 40:
        garch_results = fit_garch_compare(rv_df, c2c_data)
        if garch_results:
            results['garch_comparison'] = garch_results

    # Part 6: Jump analysis
    if rv_df is not None:
        jump_results = jump_analysis(rv_df)
        results['jump_analysis'] = jump_results

    # Part 7: Readiness
    assessment = readiness_assessment(inventory, rv_df)
    results['readiness'] = assessment

    # Print 0050.TW stats if available
    if '0050_TW' in inventory:
        print("\n" + "=" * 70)
        print("BONUS: 0050.TW (Taiwan) 5-MIN RV")
        print("=" * 70)
        df_tw = load_all_5min("0050_TW")
        if len(df_tw) > 0:
            rv_tw = compute_daily_rv_bpv(df_tw)
            print(f"  Days: {len(rv_tw)}")
            print(f"  Range: {rv_tw.index[0]} to {rv_tw.index[-1]}")
            print(f"  Mean RV:  {rv_tw['rv'].mean():.6f}  (={np.sqrt(rv_tw['rv'].mean()*252)*100:.2f}% ann)")
            print(f"  Mean BPV: {rv_tw['bpv'].mean():.6f}")
            print(f"  Jump%:    {rv_tw['jv'].mean()/rv_tw['rv'].mean()*100:.1f}%")
            results['tw_0050'] = {
                'n_days': int(len(rv_tw)),
                'start': str(rv_tw.index[0]),
                'end': str(rv_tw.index[-1]),
                'mean_rv': float(rv_tw['rv'].mean()),
                'annualized_vol': float(np.sqrt(rv_tw['rv'].mean() * 252) * 100),
                'jump_pct': float(rv_tw['jv'].mean() / rv_tw['rv'].mean() * 100),
            }

    # Final summary
    print("\n" + "=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)

    n_spy = inventory.get('SPY', {}).get('n_days', 0)

    print(f"\n  DATA STATUS:")
    print(f"    SPY 5-min data: {n_spy} trading days accumulated")
    print(f"    0050.TW 5-min:  {inventory.get('0050_TW', {}).get('n_days', 0)} trading days")

    if n_spy >= 60:
        print(f"\n  HAR-RV STATUS: READY for preliminary testing")
        if 'har_rv' in results and results['har_rv']:
            h = results['har_rv']
            print(f"    HAR-RV OOS R^2:  {h['har_rv']['r2_oos']:.4f}")
            print(f"    HAR-BPV OOS R^2: {h['har_bpv']['r2_oos']:.4f}")
            print(f"    Naive OOS R^2:   {h['naive']['r2_oos']:.4f}")
            if h['dm_test']['t_stat'] is not None:
                print(f"    DM t-stat (HAR vs Naive): {h['dm_test']['t_stat']:.4f}")
    elif n_spy >= 30:
        print(f"\n  HAR-RV STATUS: MARGINAL — can fit but OOS too short")
        print(f"    Need {60 - n_spy} more days for reliable HAR-RV")
    else:
        print(f"\n  HAR-RV STATUS: NOT READY")
        print(f"    Need {60 - n_spy} more days for basic HAR-RV")

    if n_spy >= 90:
        print(f"\n  ROLLING OOS: READY (30-day training window)")
    else:
        print(f"\n  ROLLING OOS: Need {90 - n_spy} more days")

    print(f"\n  KEY FINDING from K196: RV AC(1) >> c2c AC(1)")
    print(f"    -> RV is fundamentally more forecastable")
    print(f"    -> This experiment confirms/updates with current data")

    # Limitation
    print(f"\n  LIMITATIONS:")
    print(f"    - yfinance free tier: max ~59 days backfill")
    print(f"    - Must accumulate daily; cannot retrieve old 5-min data")
    print(f"    - Current sample too short for definitive HAR-RV vs GARCH conclusion")
    print(f"    - No overnight return component in RV (RTH only)")

    # Save results
    out_file = STORAGE_DIR / "k257_5min_status.json"
    with open(out_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved: {out_file}")

    return results


if __name__ == '__main__':
    results = main()
