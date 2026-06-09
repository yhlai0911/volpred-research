#!/usr/bin/env python3
"""
K1057: HAR-RV-J — Jump Component and Bipower Variation with 60-Day 5-min Data

Extension of K156 (46-day descriptive RV decomposition) with formal jump testing
and HAR-RV-J / HAR-C model comparison using 60 trading days of SPY 5-min data.

Research Questions:
1. SPY 60-day jump detection rate (Barndorff-Nielsen & Shephard z-test)
2. HAR-RV-J (adding jump term) vs standard HAR-RV
3. HAR-C (continuous-only BPV) vs HAR-RV (denoising effect)
4. Best HAR variant vs A4f-VIX² (from K1054)
5. Overnight return² vs intraday RV ratio and correlation

Data:
- 5-min SPY data: data/intraday/SPY_5min_YYYY-MM-DD.csv (60 files, 2026-01-14 ~ 2026-04-10)
- Daily SPY/VIX: yfinance (2000+ daily observations for GARCH/A4f)

References:
- Barndorff-Nielsen & Shephard (2006). Econometrics of testing for jumps. JFE.
- Corsi (2009). A simple approximate long-memory model of realized volatility. JFEC.
- Andersen, Bollerslev & Diebold (2007). Roughing it up. REStat.
- Patton (2011). Volatility forecast comparison using imperfect volatility proxies. JoE.

Status: PRELIMINARY (OOS << 252 days)
Random seed: 42

Prior: K156 (46 days, descriptive), K1054 (60 days, HAR vs A4f baseline)
"""

import json
import os
import sys
import warnings
from datetime import datetime, timezone
from glob import glob

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings('ignore')
np.random.seed(42)

# ── Paths ──
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.abspath(os.path.join(BASE_DIR, '..', '..'))
MAIN_REPO = '/Users/yhlai0911/Desktop/volpred-research'
DATA_DIR = os.path.join(MAIN_REPO, 'data', 'intraday')
OUTPUT_DIR = BASE_DIR
SAMPLE_START = '2026-01-14'
SAMPLE_END = '2026-04-10'
LOCAL_DAILY_FALLBACK = '/Users/yhlai0911/.gemini/antigravity-cli/scratch/crypto-fear-channel/data/spy_btc_usd_vix_2015-2026.csv'

print("=" * 70)
print("K1057: HAR-RV-J — Jump Component & Bipower Variation (60 days)")
print("=" * 70)


# ═══════════════════════════════════════════════════════════════════════
# 1. LOAD 5-MIN DATA AND COMPUTE RV COMPONENTS
# ═══════════════════════════════════════════════════════════════════════

print("\n[1] Loading 5-min data and computing RV components...")

fivemin_files = sorted(glob(os.path.join(DATA_DIR, 'SPY_5min_*.csv')))
fivemin_files = [
    f for f in fivemin_files
    if SAMPLE_START <= os.path.basename(f).replace('SPY_5min_', '').replace('.csv', '') <= SAMPLE_END
]
print(f"  Found {len(fivemin_files)} 5-min CSV files")

# Helper: compute RV, BPV, J from a single day's 5-min data
def compute_rv_components(filepath):
    """
    Compute Realized Variance, Bipower Variation, and Jump from 5-min data.

    RV = sum(r_i^2)
    BPV = (pi/2) * sum(|r_i| * |r_{i-1}|)  (Barndorff-Nielsen & Shephard 2004)
    J = max(RV - BPV, 0)
    """
    df = pd.read_csv(filepath, header=[0, 1], index_col=0, parse_dates=True)

    # Extract close prices
    close = df[('Close', 'SPY')].dropna()

    if len(close) < 5:
        return None

    # Simple returns (pct_change consistent with collect_5min_data.py)
    returns = close.pct_change().dropna()
    n = len(returns)

    if n < 3:
        return None

    r = returns.values

    # Realized Variance
    rv = np.sum(r ** 2)

    # Bipower Variation: (pi/2) * sum(|r_i| * |r_{i-1}|) for i=1,...,n-1
    # Scaled by n/(n-1) for finite sample correction
    abs_r = np.abs(r)
    bpv = (np.pi / 2.0) * (n / (n - 1.0)) * np.sum(abs_r[1:] * abs_r[:-1])

    # Jump component
    jump = max(rv - bpv, 0.0)

    # Barndorff-Nielsen & Shephard (2006) z-test for significant jumps
    # Tri-power quarticity for variance of RV - BPV
    # TPQ = n * mu_{4/3}^{-3} * sum(|r_i|^{4/3} |r_{i-1}|^{4/3} |r_{i-2}|^{4/3})
    import math as _math
    mu_43 = 2.0 ** (2.0/3.0) * _math.gamma(7.0/6.0) / _math.gamma(0.5)

    if n >= 4:
        tpq_sum = np.sum(abs_r[2:] ** (4.0/3.0) * abs_r[1:-1] ** (4.0/3.0) * abs_r[:-2] ** (4.0/3.0))
        tpq = (n ** 2) / (n - 2.0) * mu_43 ** (-3) * tpq_sum
    else:
        tpq = rv ** 2  # fallback

    # Relative jump: (RV - BPV) / RV
    rel_jump = (rv - bpv) / rv if rv > 0 else 0.0

    # BN-S relative jump statistic:
    # z = sqrt(n) * ((RV - BPV) / RV) / sqrt(theta * max(1, TPQ / BPV^2))
    # This is the canonical relative form typically used in practice.
    theta = np.pi ** 2 / 4.0 + np.pi - 5.0  # ≈ 0.6090
    if bpv > 0:
        iq_ratio = max(1.0, tpq / max(bpv ** 2, 1e-30))
    else:
        iq_ratio = 1.0
    denom = np.sqrt(max(theta * iq_ratio, 1e-30))
    z_stat = np.sqrt(n) * rel_jump / denom if denom > 0 else 0.0

    # One-sided test (jumps are positive)
    p_value = 1.0 - stats.norm.cdf(z_stat)
    sig_jump = p_value < 0.05

    # Open and close for overnight calculation
    open_price = close.iloc[0]  # First bar's close ≈ open
    close_price = close.iloc[-1]

    return {
        'rv': rv,
        'bpv': bpv,
        'jump': jump,
        'jump_significant': sig_jump,
        'z_stat': z_stat,
        'p_value': p_value,
        'rel_jump': rel_jump,
        'n_bars': n,
        'open': open_price,
        'close': close_price,
    }

# Process all files
daily_data = {}
for fpath in fivemin_files:
    date_str = os.path.basename(fpath).replace('SPY_5min_', '').replace('.csv', '')
    result = compute_rv_components(fpath)
    if result is not None:
        daily_data[date_str] = result

print(f"  Successfully processed: {len(daily_data)} days")

# Build DataFrame
dates = sorted(daily_data.keys())
df_rv = pd.DataFrame([daily_data[d] for d in dates], index=pd.to_datetime(dates))
df_rv.index.name = 'Date'

# Compute C (continuous) = BPV (truncated: only significant jumps count)
# Two approaches:
# (a) C = BPV always (standard)
# (b) C = RV when no sig jump, C = BPV when sig jump (Andersen, Bollerslev, Diebold 2007)
df_rv['C_standard'] = df_rv['bpv']
df_rv['C_abd'] = np.where(df_rv['jump_significant'], df_rv['bpv'], df_rv['rv'])
df_rv['J_abd'] = np.where(df_rv['jump_significant'], df_rv['jump'], 0.0)

print(f"  Date range: {df_rv.index[0].date()} to {df_rv.index[-1].date()}")
print(f"  RV mean: {df_rv['rv'].mean():.6e}")
print(f"  BPV mean: {df_rv['bpv'].mean():.6e}")
print(f"  Jump mean: {df_rv['jump'].mean():.6e}")

# Jump statistics
n_sig_jumps = df_rv['jump_significant'].sum()
print(f"\n  Jump detection (BN-S z-test, 5% level):")
print(f"    Significant jumps: {n_sig_jumps} / {len(df_rv)} = {n_sig_jumps/len(df_rv)*100:.1f}%")
print(f"    Mean z-stat: {df_rv['z_stat'].mean():.3f}")
print(f"    Max z-stat: {df_rv['z_stat'].max():.3f}")


# ═══════════════════════════════════════════════════════════════════════
# 2. LOAD DAILY DATA (RETURNS, VIX) FOR GARCH/A4f
# ═══════════════════════════════════════════════════════════════════════

print("\n[2] Loading daily SPY/VIX data...")

try:
    import yfinance as yf
    spy_data = yf.download('SPY', start='2016-01-01', end='2026-04-11', progress=False)
    vix_data = yf.download('^VIX', start='2016-01-01', end='2026-04-11', progress=False)

    if spy_data.empty or vix_data.empty:
        raise ValueError("yfinance returned empty daily data")

    # Handle multi-level columns
    if isinstance(spy_data.columns, pd.MultiIndex):
        spy_close = spy_data[('Close', 'SPY')].squeeze()
        spy_open = spy_data[('Open', 'SPY')].squeeze()
    else:
        spy_close = spy_data['Close'].squeeze()
        spy_open = spy_data['Open'].squeeze()

    if isinstance(vix_data.columns, pd.MultiIndex):
        vix_close = vix_data[('Close', '^VIX')].squeeze()
    else:
        vix_close = vix_data['Close'].squeeze()

    # Daily returns
    daily_ret = spy_close.pct_change(fill_method=None).dropna()
    daily_r2 = daily_ret ** 2

    # Overnight returns: (open_t - close_{t-1}) / close_{t-1}
    overnight_ret = (spy_open - spy_close.shift(1)) / spy_close.shift(1)
    overnight_r2 = overnight_ret ** 2

    print(f"  Daily SPY returns: {len(daily_ret)} observations")
    print(f"  VIX data: {len(vix_close)} observations")

except Exception as e:
    print(f"  yfinance unavailable, using local fallback: {e}")
    fallback = pd.read_csv(LOCAL_DAILY_FALLBACK, parse_dates=['date']).set_index('date').sort_index()
    fallback = fallback.loc['2016-01-01':'2026-04-10']
    fallback = fallback[['spy_close', 'spy_open', 'vix_close']].dropna()

    spy_close = fallback['spy_close'].astype(float)
    spy_open = fallback['spy_open'].astype(float)
    vix_close = fallback['vix_close'].astype(float)

    daily_ret = spy_close.pct_change(fill_method=None).dropna()
    daily_r2 = daily_ret ** 2

    overnight_ret = (spy_open - spy_close.shift(1)) / spy_close.shift(1)
    overnight_r2 = overnight_ret ** 2

    print(f"  Daily SPY returns (fallback): {len(daily_ret)} observations")
    print(f"  VIX data (fallback): {len(vix_close.dropna())} observations")

# Align overnight return² with RV dates
overnight_aligned = overnight_r2.reindex(df_rv.index).dropna()
rv_aligned = df_rv['rv'].reindex(overnight_aligned.index)

# Compute overnight share
overnight_share = overnight_aligned / (overnight_aligned + rv_aligned)
print(f"\n  Overnight return² share of total variance:")
print(f"    Mean: {overnight_share.mean():.1%}")
print(f"    Median: {overnight_share.median():.1%}")
print(f"    Range: [{overnight_share.min():.1%}, {overnight_share.max():.1%}]")
print(f"    Corr(overnight_r2, intraday_RV): {overnight_aligned.corr(rv_aligned):.3f}")


# ═══════════════════════════════════════════════════════════════════════
# 3. DESCRIPTIVE STATISTICS
# ═══════════════════════════════════════════════════════════════════════

print("\n[3] Descriptive statistics...")

desc_stats = {
    'rv': {
        'mean': float(df_rv['rv'].mean()),
        'std': float(df_rv['rv'].std()),
        'min': float(df_rv['rv'].min()),
        'max': float(df_rv['rv'].max()),
        'skew': float(df_rv['rv'].skew()),
        'kurtosis': float(df_rv['rv'].kurtosis()),
    },
    'bpv': {
        'mean': float(df_rv['bpv'].mean()),
        'std': float(df_rv['bpv'].std()),
        'min': float(df_rv['bpv'].min()),
        'max': float(df_rv['bpv'].max()),
        'skew': float(df_rv['bpv'].skew()),
        'kurtosis': float(df_rv['bpv'].kurtosis()),
    },
    'jump': {
        'mean': float(df_rv['jump'].mean()),
        'std': float(df_rv['jump'].std()),
        'min': float(df_rv['jump'].min()),
        'max': float(df_rv['jump'].max()),
        'fraction_of_rv': float(df_rv['jump'].sum() / df_rv['rv'].sum()),
    },
    'jump_significant': {
        'count': int(n_sig_jumps),
        'total_days': int(len(df_rv)),
        'rate': float(n_sig_jumps / len(df_rv)),
        'mean_z': float(df_rv['z_stat'].mean()),
        'max_z': float(df_rv['z_stat'].max()),
    },
    'overnight': {
        'mean_share': float(overnight_share.mean()),
        'median_share': float(overnight_share.median()),
        'min_share': float(overnight_share.min()),
        'max_share': float(overnight_share.max()),
        'corr_overnight_intraday': float(overnight_aligned.corr(rv_aligned)),
    },
}

# ACF (manual computation for small sample)
def acf_k(x, k):
    """Compute autocorrelation at lag k."""
    n = len(x)
    if n <= k:
        return np.nan
    xm = x - x.mean()
    c0 = np.sum(xm ** 2)
    ck = np.sum(xm[k:] * xm[:-k])
    return ck / c0 if c0 > 0 else 0.0

for var_name, series in [('rv', df_rv['rv']), ('bpv', df_rv['bpv']),
                          ('jump', df_rv['jump']), ('C_abd', df_rv['C_abd'])]:
    acf1 = acf_k(series.values, 1)
    acf5 = acf_k(series.values, 5)
    desc_stats[f'{var_name}_acf'] = {'lag1': float(acf1), 'lag5': float(acf5)}
    print(f"  ACF {var_name}: lag1={acf1:.3f}, lag5={acf5:.3f}")


# ═══════════════════════════════════════════════════════════════════════
# 4. HAR MODELS (EXPANDING WINDOW)
# ═══════════════════════════════════════════════════════════════════════

print("\n[4] Fitting HAR models...")

# Prepare HAR features
def make_har_features(series, name='x'):
    """Create daily, weekly (5-day), monthly (22-day) averages for HAR model."""
    df = pd.DataFrame({f'{name}_d': series})
    df[f'{name}_w'] = series.rolling(5, min_periods=1).mean()
    df[f'{name}_m'] = series.rolling(22, min_periods=1).mean()
    return df

# Features for each model variant
har_rv_feat = make_har_features(df_rv['rv'], 'rv')
har_c_feat = make_har_features(df_rv['C_standard'], 'c')  # C = BPV
har_cabd_feat = make_har_features(df_rv['C_abd'], 'cabd')  # C_ABD = truncated

# Target: RV_{t} (next-day RV)
target = df_rv['rv'].copy()

# OOS setup: initial training = 30 days (indices 0..29), predict from index 30
INIT_WINDOW = 30
n_total = len(df_rv)
oos_start_idx = INIT_WINDOW

if oos_start_idx >= n_total:
    print("  ERROR: Not enough data for OOS forecasting!")
    sys.exit(1)

n_oos = n_total - oos_start_idx
print(f"  Training window: expanding from {INIT_WINDOW} days")
print(f"  OOS period: {n_oos} days ({df_rv.index[oos_start_idx].date()} to {df_rv.index[-1].date()})")

def ols_forecast(X_train, y_train, x_test):
    """Simple OLS forecast with intercept."""
    n = X_train.shape[0]
    X = np.column_stack([np.ones(n), X_train])
    try:
        beta = np.linalg.lstsq(X, y_train, rcond=None)[0]
        x_t = np.concatenate([[1.0], x_test])
        return max(float(x_t @ beta), 1e-10)  # Non-negative variance
    except:
        return float(y_train.mean())  # Fallback

# Store forecasts
forecasts = {
    'HAR-RV': np.full(n_oos, np.nan),
    'HAR-C': np.full(n_oos, np.nan),
    'HAR-RV-J': np.full(n_oos, np.nan),
    'HAR-CJ': np.full(n_oos, np.nan),
    'HAR-CJ-ABD': np.full(n_oos, np.nan),
}

rv_values = target.values
jump_values = df_rv['jump'].values
j_abd_values = df_rv['J_abd'].values

for i in range(n_oos):
    t = oos_start_idx + i  # forecast target index (predict RV at t)

    # Training data: use data from 0 to t-1
    train_end = t  # exclusive
    y_train = rv_values[1:train_end]  # RV at indices 1..t-1 (targets)

    # HAR-RV: use RV_{t-1}, RV_w_{t-1}, RV_m_{t-1} to predict RV_t
    X_rv = har_rv_feat[['rv_d', 'rv_w', 'rv_m']].values[:train_end-1]  # features at 0..t-2
    x_rv_test = har_rv_feat[['rv_d', 'rv_w', 'rv_m']].values[t-1]  # features at t-1
    forecasts['HAR-RV'][i] = ols_forecast(X_rv, y_train, x_rv_test)

    # HAR-C: use C_{t-1}, C_w_{t-1}, C_m_{t-1}
    X_c = har_c_feat[['c_d', 'c_w', 'c_m']].values[:train_end-1]
    x_c_test = har_c_feat[['c_d', 'c_w', 'c_m']].values[t-1]
    forecasts['HAR-C'][i] = ols_forecast(X_c, y_train, x_c_test)

    # HAR-RV-J: HAR-RV + J_{t-1}
    X_rvj = np.column_stack([X_rv, jump_values[:train_end-1]])
    x_rvj_test = np.concatenate([x_rv_test, [jump_values[t-1]]])
    forecasts['HAR-RV-J'][i] = ols_forecast(X_rvj, y_train, x_rvj_test)

    # HAR-CJ: C_{t-1}, C_w, C_m + J_{t-1}
    X_cj = np.column_stack([X_c, jump_values[:train_end-1]])
    x_cj_test = np.concatenate([x_c_test, [jump_values[t-1]]])
    forecasts['HAR-CJ'][i] = ols_forecast(X_cj, y_train, x_cj_test)

    # HAR-CJ-ABD: C_ABD (truncated continuous) + J_ABD (significant jumps only)
    X_cabd = har_cabd_feat[['cabd_d', 'cabd_w', 'cabd_m']].values[:train_end-1]
    x_cabd_test = har_cabd_feat[['cabd_d', 'cabd_w', 'cabd_m']].values[t-1]
    X_cjabd = np.column_stack([X_cabd, j_abd_values[:train_end-1]])
    x_cjabd_test = np.concatenate([x_cabd_test, [j_abd_values[t-1]]])
    forecasts['HAR-CJ-ABD'][i] = ols_forecast(X_cjabd, y_train, x_cjabd_test)

print("  HAR models fitted successfully")
for name, fc in forecasts.items():
    print(f"    {name}: mean forecast = {np.nanmean(fc):.6e}")


# ═══════════════════════════════════════════════════════════════════════
# 5. GARCH AND A4f BENCHMARKS (from K1054 approach)
# ═══════════════════════════════════════════════════════════════════════

print("\n[5] Fitting GJR-GARCH and A4f-VIX² benchmarks...")

oos_dates = df_rv.index[oos_start_idx:]
oos_r2 = daily_r2.reindex(oos_dates).dropna()
oos_rv = df_rv['rv'].iloc[oos_start_idx:]

# GJR-GARCH: rolling w=2000
from arch import arch_model

garch_forecasts = {}
for d in oos_dates:
    # Get training window ending at d-1
    d_loc = daily_ret.index.get_loc(d)
    if d_loc < 2000:
        continue
    train_ret = daily_ret.iloc[d_loc-2000:d_loc] * 100  # Scale to percentage

    try:
        model = arch_model(train_ret, vol='GARCH', p=1, o=1, q=1, dist='normal')
        res = model.fit(disp='off', show_warning=False)
        fc = res.forecast(horizon=1)
        # Convert back from percentage: sigma2_pct / 10000
        sigma2 = float(fc.variance.values[-1, 0]) / 10000.0
        garch_forecasts[d] = max(sigma2, 1e-10)
    except:
        pass

print(f"  GJR-GARCH: {len(garch_forecasts)} OOS forecasts")

# A4f-VIX²: VIX²/252 rescaled with bias correction
a4f_forecasts = {}
for d in oos_dates:
    d_loc_vix = vix_close.index.get_loc(d) if d in vix_close.index else None
    if d_loc_vix is None or d_loc_vix < 1:
        continue
    # Use previous day's VIX (avoid lookahead)
    vix_prev = float(vix_close.iloc[d_loc_vix - 1])
    # A4f: VIX²/252 as variance forecast
    a4f_forecasts[d] = (vix_prev / 100.0) ** 2 / 252.0

print(f"  A4f-VIX²: {len(a4f_forecasts)} OOS forecasts")


# ═══════════════════════════════════════════════════════════════════════
# 6. EVALUATION: QLIKE ON RV AND r² PROXIES
# ═══════════════════════════════════════════════════════════════════════

print("\n[6] Evaluating models...")

def qlike(actual, predicted):
    """Canonical QLIKE loss: sigma2/h - log(sigma2/h) - 1."""
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    actual = np.maximum(actual, 1e-12)
    predicted = np.maximum(predicted, 1e-10)
    ratio = actual / predicted
    loss = ratio - np.log(ratio) - 1.0
    return float(np.nanmean(loss))

def dm_test(loss1, loss2):
    """Diebold-Mariano test. Negative t-stat means model 1 is better."""
    d = np.asarray(loss1) - np.asarray(loss2)
    d = d[~np.isnan(d)]
    n = len(d)
    if n < 5:
        return float('nan'), float('nan')
    d_mean = np.mean(d)

    # Newey-West HAC variance with lag = int(n^(1/3))
    max_lag = max(1, int(n ** (1.0/3.0)))
    gamma0 = np.var(d, ddof=1)
    gamma_sum = 0.0
    for k in range(1, max_lag + 1):
        w = 1.0 - k / (max_lag + 1.0)
        gamma_k = np.mean((d[k:] - d_mean) * (d[:-k] - d_mean))
        gamma_sum += 2.0 * w * gamma_k
    var_d = gamma0 + gamma_sum

    if var_d <= 0:
        return float('nan'), float('nan')

    t_stat = d_mean / np.sqrt(var_d / n)
    p_val = 2.0 * (1.0 - stats.t.cdf(abs(t_stat), df=n-1))
    return float(t_stat), float(p_val)

# Common OOS dates for HAR models
har_oos_dates = df_rv.index[oos_start_idx:]
har_oos_rv = df_rv['rv'].iloc[oos_start_idx:].values
har_oos_r2_vals = daily_r2.reindex(har_oos_dates).values

# All-model common dates (intersection)
common_dates = sorted(set(har_oos_dates) & set(garch_forecasts.keys()) & set(a4f_forecasts.keys()))
print(f"  Common OOS dates (all models): {len(common_dates)}")

if len(common_dates) < 5:
    print("  WARNING: Very few common dates, results unreliable")

# Build aligned arrays
rv_common = np.array([float(df_rv.loc[d, 'rv']) for d in common_dates])
r2_common = np.array([float(daily_r2.loc[d]) for d in common_dates])
garch_common = np.array([garch_forecasts[d] for d in common_dates])
a4f_common = np.array([a4f_forecasts[d] for d in common_dates])

# HAR forecasts on common dates
har_idx_map = {d: i for i, d in enumerate(har_oos_dates)}
har_rv_common = np.array([forecasts['HAR-RV'][har_idx_map[d]] for d in common_dates])
har_c_common = np.array([forecasts['HAR-C'][har_idx_map[d]] for d in common_dates])
har_rvj_common = np.array([forecasts['HAR-RV-J'][har_idx_map[d]] for d in common_dates])
har_cj_common = np.array([forecasts['HAR-CJ'][har_idx_map[d]] for d in common_dates])
har_cjabd_common = np.array([forecasts['HAR-CJ-ABD'][har_idx_map[d]] for d in common_dates])

# QLIKE on RV proxy (HAR's native target)
print("\n  === QLIKE on RV proxy (HAR native) ===")
qlike_rv = {}
all_fc = {
    'HAR-RV': har_rv_common,
    'HAR-C': har_c_common,
    'HAR-RV-J': har_rvj_common,
    'HAR-CJ': har_cj_common,
    'HAR-CJ-ABD': har_cjabd_common,
    'GJR-GARCH': garch_common,
    'A4f-VIX²': a4f_common,
}

for name, fc in all_fc.items():
    q = qlike(rv_common, fc)
    qlike_rv[name] = q
    print(f"    {name:15s}: QLIKE(RV) = {q:.4f}")

# QLIKE on r² proxy (cross-model fair comparison, Patton 2011)
print("\n  === QLIKE on r² proxy (Patton 2011 fair) ===")
qlike_r2 = {}
for name, fc in all_fc.items():
    q = qlike(r2_common, fc)
    qlike_r2[name] = q
    print(f"    {name:15s}: QLIKE(r²) = {q:.4f}")

# Spearman rank correlation
print("\n  === Spearman Rank Correlation ===")
spearman_rv = {}
spearman_r2 = {}
for name, fc in all_fc.items():
    sr_rv, _ = stats.spearmanr(rv_common, fc)
    sr_r2, _ = stats.spearmanr(r2_common, fc)
    spearman_rv[name] = float(sr_rv)
    spearman_r2[name] = float(sr_r2)
    print(f"    {name:15s}: ρ(RV)={sr_rv:.3f}, ρ(r²)={sr_r2:.3f}")


# ═══════════════════════════════════════════════════════════════════════
# 7. DM TESTS (pairwise)
# ═══════════════════════════════════════════════════════════════════════

print("\n[7] Diebold-Mariano tests...")

# Compute QLIKE losses per observation for DM test
def qlike_losses(actual, predicted):
    """Per-observation canonical QLIKE losses."""
    actual = np.asarray(actual, dtype=float)
    actual = np.maximum(actual, 1e-12)
    predicted = np.maximum(np.asarray(predicted, dtype=float), 1e-10)
    ratio = actual / predicted
    return ratio - np.log(ratio) - 1.0

# DM test pairs: each HAR variant vs HAR-RV, and best HAR vs A4f
dm_results = {}

# On RV proxy
losses_rv = {name: qlike_losses(rv_common, fc) for name, fc in all_fc.items()}

dm_pairs = [
    ('HAR-C', 'HAR-RV'),
    ('HAR-RV-J', 'HAR-RV'),
    ('HAR-CJ', 'HAR-RV'),
    ('HAR-CJ-ABD', 'HAR-RV'),
    ('HAR-RV', 'A4f-VIX²'),
    ('HAR-C', 'A4f-VIX²'),
    ('HAR-CJ', 'A4f-VIX²'),
    ('HAR-RV', 'GJR-GARCH'),
    ('A4f-VIX²', 'GJR-GARCH'),
]

print("\n  === DM Test on RV proxy (negative t = first model better) ===")
for m1, m2 in dm_pairs:
    t_stat, p_val = dm_test(losses_rv[m1], losses_rv[m2])
    dm_results[f'{m1}_vs_{m2}_rv'] = {'t_stat': t_stat, 'p_val': p_val}
    sig = '***' if abs(t_stat) > 3.0 else ('**' if abs(t_stat) > 2.0 else ('*' if abs(t_stat) > 1.65 else ''))
    print(f"    {m1:15s} vs {m2:15s}: t={t_stat:+.3f} {sig}")

# On r² proxy
losses_r2 = {name: qlike_losses(r2_common, fc) for name, fc in all_fc.items()}

print("\n  === DM Test on r² proxy (negative t = first model better) ===")
for m1, m2 in dm_pairs:
    t_stat, p_val = dm_test(losses_r2[m1], losses_r2[m2])
    dm_results[f'{m1}_vs_{m2}_r2'] = {'t_stat': t_stat, 'p_val': p_val}
    sig = '***' if abs(t_stat) > 3.0 else ('**' if abs(t_stat) > 2.0 else ('*' if abs(t_stat) > 1.65 else ''))
    print(f"    {m1:15s} vs {m2:15s}: t={t_stat:+.3f} {sig}")


# ═══════════════════════════════════════════════════════════════════════
# 8. RESULTS COMPILATION
# ═══════════════════════════════════════════════════════════════════════

print("\n[8] Compiling results...")

# Rank models by QLIKE (lower is better)
rank_rv = sorted(qlike_rv.items(), key=lambda x: x[1])
rank_r2 = sorted(qlike_r2.items(), key=lambda x: x[1])

print("\n  === Model Ranking by QLIKE ===")
print("  RV proxy ranking:")
for i, (name, q) in enumerate(rank_rv):
    print(f"    {i+1}. {name:15s}: {q:.4f}")
print("  r² proxy ranking:")
for i, (name, q) in enumerate(rank_r2):
    print(f"    {i+1}. {name:15s}: {q:.4f}")

# Check ranking consistency (Patton 2011 robustness)
rv_rank_names = [x[0] for x in rank_rv]
r2_rank_names = [x[0] for x in rank_r2]
ranking_consistent = rv_rank_names == r2_rank_names
print(f"\n  Ranking consistent across proxies: {ranking_consistent}")
if not ranking_consistent:
    print(f"    RV ranking: {rv_rank_names}")
    print(f"    r² ranking: {r2_rank_names}")

# Jump dates detail
jump_days = df_rv[df_rv['jump_significant']].copy()
jump_detail = []
for d in jump_days.index:
    jump_detail.append({
        'date': str(d.date()),
        'rv': float(df_rv.loc[d, 'rv']),
        'bpv': float(df_rv.loc[d, 'bpv']),
        'jump': float(df_rv.loc[d, 'jump']),
        'z_stat': float(df_rv.loc[d, 'z_stat']),
        'p_value': float(df_rv.loc[d, 'p_value']),
        'rel_jump': float(df_rv.loc[d, 'rel_jump']),
    })


# ═══════════════════════════════════════════════════════════════════════
# 9. SAVE RESULTS JSON
# ═══════════════════════════════════════════════════════════════════════

print("\n[9] Saving results...")

results = {
    'experiment_id': 'K1057',
    'title': 'HAR-RV-J — Jump Component & Bipower Variation (60-Day 5-min SPY)',
    'status': 'PRELIMINARY',
    'note': 'OOS only ~30 days, well below 252-day minimum. Results indicative only.',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'extends': ['K156', 'K1054'],
    'data': {
        'asset': 'SPY',
        'source': 'yfinance (daily) + data/intraday/ (5-min)',
        'rv_days': int(len(df_rv)),
        'rv_period': f"{df_rv.index[0].date()} to {df_rv.index[-1].date()}",
        'oos_days': int(n_oos),
        'oos_period': f"{df_rv.index[oos_start_idx].date()} to {df_rv.index[-1].date()}",
        'common_oos_days': int(len(common_dates)),
        'garch_window': 2000,
        'har_initial_window': INIT_WINDOW,
    },
    'descriptive_stats': desc_stats,
    'significant_jumps': jump_detail,
    'models': {
        'HAR-RV': {
            'specification': 'RV_t = b0 + b_d*RV_{t-1} + b_w*RV_w_{t-1} + b_m*RV_m_{t-1}',
            'estimation': f'Expanding window OLS, initial={INIT_WINDOW} days',
        },
        'HAR-C': {
            'specification': 'RV_t = b0 + b_d*C_{t-1} + b_w*C_w_{t-1} + b_m*C_m_{t-1} (C=BPV)',
            'estimation': f'Expanding window OLS, initial={INIT_WINDOW} days',
        },
        'HAR-RV-J': {
            'specification': 'RV_t = b0 + b_d*RV_{t-1} + b_w*RV_w_{t-1} + b_m*RV_m_{t-1} + g*J_{t-1}',
            'estimation': f'Expanding window OLS, initial={INIT_WINDOW} days',
        },
        'HAR-CJ': {
            'specification': 'RV_t = b0 + b_d*C_{t-1} + b_w*C_w_{t-1} + b_m*C_m_{t-1} + g*J_{t-1}',
            'estimation': f'Expanding window OLS, initial={INIT_WINDOW} days',
        },
        'HAR-CJ-ABD': {
            'specification': 'RV_t = HAR-C(ABD) + g*J_ABD (Andersen-Bollerslev-Diebold truncated)',
            'estimation': f'Expanding window OLS, initial={INIT_WINDOW} days',
        },
        'GJR-GARCH': {
            'specification': 'GJR(1,1) normal innovations',
            'estimation': 'Rolling window=2000 daily',
        },
        'A4f-VIX²': {
            'specification': 'h_t = (VIX_{t-1}/100)²/252',
            'estimation': 'Analytic (no estimation)',
        },
    },
    'evaluation': {
        'qlike_rv_proxy': {k: round(v, 6) for k, v in qlike_rv.items()},
        'qlike_r2_proxy': {k: round(v, 6) for k, v in qlike_r2.items()},
        'spearman_rv': {k: round(v, 4) for k, v in spearman_rv.items()},
        'spearman_r2': {k: round(v, 4) for k, v in spearman_r2.items()},
        'ranking_rv': [{'rank': i+1, 'model': n, 'qlike': round(q, 6)} for i, (n, q) in enumerate(rank_rv)],
        'ranking_r2': [{'rank': i+1, 'model': n, 'qlike': round(q, 6)} for i, (n, q) in enumerate(rank_r2)],
        'ranking_consistent_across_proxies': ranking_consistent,
    },
    'dm_tests': dm_results,
    'interpretation': {
        'q1_jump_rate': f"{n_sig_jumps}/{len(df_rv)} significant jumps ({n_sig_jumps/len(df_rv)*100:.1f}%) by BN-S test at 5%",
        'q2_har_rvj_vs_har_rv': f"QLIKE(RV): HAR-RV-J={qlike_rv.get('HAR-RV-J', 'N/A'):.6f} vs HAR-RV={qlike_rv.get('HAR-RV', 'N/A'):.6f}",
        'q3_har_c_vs_har_rv': f"QLIKE(RV): HAR-C={qlike_rv.get('HAR-C', 'N/A'):.6f} vs HAR-RV={qlike_rv.get('HAR-RV', 'N/A'):.6f}",
        'q4_best_har_vs_a4f': f"Best HAR variant on r²: {rank_r2[0][0]} ({rank_r2[0][1]:.6f}); A4f: {qlike_r2.get('A4f-VIX²', 'N/A'):.6f}",
        'q5_overnight_share': f"Mean overnight share: {overnight_share.mean():.1%}",
    },
    'references': [
        'Barndorff-Nielsen & Shephard (2006). Econometrics of testing for jumps in financial economics using bipower variation. JFE.',
        'Corsi (2009). A simple approximate long-memory model of realized volatility. JFEC.',
        'Andersen, Bollerslev & Diebold (2007). Roughing it up: Including jump components in the measurement, modeling, and forecasting of return volatility. REStat.',
        'Patton (2011). Volatility forecast comparison using imperfect volatility proxies. JoE.',
        'Hansen & Lunde (2005). A forecast comparison of volatility models: Does anything beat a GARCH(1,1)? JFEC.',
    ],
}

results_path = os.path.join(OUTPUT_DIR, 'k1057_results.json')
with open(results_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"  Saved: {results_path}")


# ═══════════════════════════════════════════════════════════════════════
# 10. PLOTS
# ═══════════════════════════════════════════════════════════════════════

print("\n[10] Creating plots...")

x_dates = df_rv.index.to_pydatetime()
sig_dates = df_rv[df_rv['jump_significant']].index
sig_x = sig_dates.to_pydatetime()
overnight_x = overnight_share.index.to_pydatetime()

# ── Plot 1: RV Decomposition time series ──
fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)

# Panel A: RV vs BPV
ax = axes[0]
ax.plot(x_dates, df_rv['rv'].values * 1e4, label='RV', color='#2196F3', linewidth=1.5)
ax.plot(x_dates, df_rv['bpv'].values * 1e4, label='BPV (Continuous)', color='#4CAF50', linewidth=1.5, alpha=0.8)
ax.fill_between(x_dates, df_rv['bpv'].values * 1e4, df_rv['rv'].values * 1e4,
                where=df_rv['rv'] > df_rv['bpv'], alpha=0.3, color='#FF5722', label='Jump (RV-BPV)')
# Mark significant jumps
if len(sig_dates) > 0:
    ax.scatter(sig_x, df_rv.loc[sig_dates, 'rv'].values * 1e4,
               marker='v', color='red', s=80, zorder=5, label=f'Significant Jump ({len(sig_dates)})')
ax.set_ylabel('Variance (×10⁴)')
ax.set_title('(A) Realized Variance vs Bipower Variation (Continuous)')
ax.legend(loc='upper right', fontsize=9)
ax.grid(True, alpha=0.3)

# Panel B: Jump component
ax = axes[1]
ax.bar(x_dates, df_rv['jump'].values * 1e4, color='#FF5722', alpha=0.7, label='Jump = max(RV-BPV, 0)')
if len(sig_dates) > 0:
    ax.bar(sig_x, df_rv.loc[sig_dates, 'jump'].values * 1e4, color='red', alpha=0.9, label='Significant (BN-S p<0.05)')
ax.set_ylabel('Jump (×10⁴)')
ax.set_title(f'(B) Jump Component — {n_sig_jumps}/{len(df_rv)} Significant')
ax.legend(loc='upper right', fontsize=9)
ax.grid(True, alpha=0.3)

# Panel C: BN-S z-statistic
ax = axes[2]
ax.plot(x_dates, df_rv['z_stat'].values, color='#9C27B0', linewidth=1.2)
ax.axhline(y=1.645, color='red', linestyle='--', alpha=0.7, label='z=1.645 (5%)')
ax.axhline(y=0, color='gray', linestyle='-', alpha=0.5)
ax.set_ylabel('BN-S z-statistic')
ax.set_title('(C) Jump Test z-statistic')
ax.legend(loc='upper right', fontsize=9)
ax.grid(True, alpha=0.3)

plt.tight_layout()
fig.savefig(os.path.join(OUTPUT_DIR, 'k1057_rv_decomposition.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved: k1057_rv_decomposition.png")

# ── Plot 2: Model Comparison (QLIKE bar chart) ──
fig, axes = plt.subplots(1, 2, figsize=(14, 6))

# Sort by QLIKE on RV
models_sorted_rv = [x[0] for x in rank_rv]
qlike_sorted_rv = [x[1] for x in rank_rv]

# Sort by QLIKE on r²
models_sorted_r2 = [x[0] for x in rank_r2]
qlike_sorted_r2 = [x[1] for x in rank_r2]

# Color coding
colors_map = {
    'HAR-RV': '#2196F3',
    'HAR-C': '#4CAF50',
    'HAR-RV-J': '#FF9800',
    'HAR-CJ': '#FF5722',
    'HAR-CJ-ABD': '#E91E63',
    'GJR-GARCH': '#607D8B',
    'A4f-VIX²': '#9C27B0',
}

# Panel A: QLIKE on RV
ax = axes[0]
bars = ax.barh(range(len(models_sorted_rv)), qlike_sorted_rv,
               color=[colors_map.get(m, '#999') for m in models_sorted_rv])
ax.set_yticks(range(len(models_sorted_rv)))
ax.set_yticklabels(models_sorted_rv)
ax.set_xlabel('QLIKE (lower = better)')
ax.set_title(f'QLIKE on RV Proxy (n={len(common_dates)} OOS days)')
ax.invert_yaxis()
for i, v in enumerate(qlike_sorted_rv):
    ax.text(v + 0.01, i, f'{v:.4f}', va='center', fontsize=9)
ax.grid(True, alpha=0.3, axis='x')

# Panel B: QLIKE on r²
ax = axes[1]
bars = ax.barh(range(len(models_sorted_r2)), qlike_sorted_r2,
               color=[colors_map.get(m, '#999') for m in models_sorted_r2])
ax.set_yticks(range(len(models_sorted_r2)))
ax.set_yticklabels(models_sorted_r2)
ax.set_xlabel('QLIKE (lower = better)')
ax.set_title(f'QLIKE on r² Proxy (Patton 2011 fair)')
ax.invert_yaxis()
for i, v in enumerate(qlike_sorted_r2):
    ax.text(v + 0.01, i, f'{v:.4f}', va='center', fontsize=9)
ax.grid(True, alpha=0.3, axis='x')

plt.suptitle('K1057: HAR-RV-J Model Comparison (PRELIMINARY, OOS<<252)', fontsize=13, y=1.02)
plt.tight_layout()
fig.savefig(os.path.join(OUTPUT_DIR, 'k1057_model_comparison.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved: k1057_model_comparison.png")

# ── Plot 3: Overnight share ──
fig, axes = plt.subplots(2, 1, figsize=(14, 7))

# Panel A: Overnight share time series
ax = axes[0]
ax.plot(overnight_x, overnight_share.values * 100, color='#FF5722', linewidth=1.5)
ax.axhline(y=overnight_share.mean() * 100, color='red', linestyle='--', alpha=0.7,
           label=f'Mean: {overnight_share.mean():.1%}')
ax.fill_between(overnight_x, 0, overnight_share.values * 100, alpha=0.2, color='#FF5722')
ax.set_ylabel('Overnight Share (%)')
ax.set_title('(A) Overnight Return² as Share of Total Variance')
ax.legend(fontsize=10)
ax.grid(True, alpha=0.3)

# Panel B: Scatter: overnight vs intraday
ax = axes[1]
ax.scatter(overnight_aligned.values * 1e4, rv_aligned.values * 1e4,
           alpha=0.6, color='#2196F3', s=50, edgecolors='white', linewidth=0.5)
r_corr = float(overnight_aligned.corr(rv_aligned))
ax.set_xlabel('Overnight Return² (×10⁴)')
ax.set_ylabel('Intraday RV (×10⁴)')
ax.set_title(f'(B) Overnight vs Intraday — Correlation: {r_corr:.3f}')
ax.grid(True, alpha=0.3)

plt.tight_layout()
fig.savefig(os.path.join(OUTPUT_DIR, 'k1057_overnight_share.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved: k1057_overnight_share.png")


# ═══════════════════════════════════════════════════════════════════════
# 11. SUMMARY
# ═══════════════════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("K1057 SUMMARY")
print("=" * 70)
print(f"\nData: {len(df_rv)} days 5-min SPY, OOS={n_oos} days (PRELIMINARY)")
print(f"\nQ1: Jump Detection Rate = {n_sig_jumps}/{len(df_rv)} ({n_sig_jumps/len(df_rv)*100:.1f}%)")
print(f"    Mean jump fraction of RV: {df_rv['jump'].sum()/df_rv['rv'].sum()*100:.1f}%")
print(f"\nQ2: HAR-RV-J vs HAR-RV (QLIKE on RV): {qlike_rv.get('HAR-RV-J', 'N/A'):.6f} vs {qlike_rv.get('HAR-RV', 'N/A'):.6f}")
print(f"\nQ3: HAR-C vs HAR-RV (QLIKE on RV): {qlike_rv.get('HAR-C', 'N/A'):.6f} vs {qlike_rv.get('HAR-RV', 'N/A'):.6f}")
print(f"\nQ4: Rankings:")
print(f"    On RV: {' > '.join([f'{n}({q:.4f})' for n, q in rank_rv[:3]])}")
print(f"    On r²: {' > '.join([f'{n}({q:.4f})' for n, q in rank_r2[:3]])}")
print(f"    Consistent: {ranking_consistent}")
print(f"\nQ5: Overnight share: mean={overnight_share.mean():.1%}, corr={r_corr:.3f}")
print(f"\n⚠️ PRELIMINARY: {n_oos} OOS days << 252 minimum. Do not overclaim.")
print("=" * 70)
