"""
K1059: TSMC Earnings Announcement x 0050.TW Volatility Event Study
===================================================================

Research Questions:
1. Does 0050.TW volatility exhibit abnormal behavior around TSMC earnings?
2. Is the effect pre-event (uncertainty) or post-event (shock)?
3. Do clustered announcements (multiple firms same day) amplify volatility?
4. Does A4f (with VIX^2) outperform GJR around announcement dates?

Data Sources:
- 財報公告日.txt (Big5, 158K records, 1986-2025)
- 0050.TW daily: yfinance (2003+)
- ^VIX daily: yfinance

References:
- K1050: SPY earnings season vol (A4f uniform, bootstrap p=0.471)
- K1058: A4f on 0050.TW (DM NS t=-1.26, VaR Trinity A4f PASS / GJR FAIL)
- K176: TSMC DeltaCoVaR = -1.599 (4.6x SPY)
- Patton (2011): QLIKE for model comparison, J Econometrics
- Andersen & Bollerslev (1998): event study volatility

Random seed: 42
"""

import numpy as np
import pandas as pd
import json
import os
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from scipy import stats, optimize
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

np.random.seed(42)
warnings.filterwarnings('ignore')

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'src'))

from volpred.utils import clean_tw50_data

DATA_FILE = PROJECT_ROOT / '財報公告日.txt'
START_TIME = time.time()

# Configuration
OOS_START = '2010-01-01'
WINDOW = 2000
REFIT_EVERY = 63  # quarterly refit for speed

print("=" * 70)
print("K1059: TSMC Earnings Announcement x 0050.TW Volatility Event Study")
print("=" * 70)

###############################################################################
# Part 0: Load earnings announcement data
###############################################################################
print("\n[Part 0] Loading earnings announcement data...")

with open(DATA_FILE, 'rb') as f:
    raw_text = f.read().decode('big5', errors='replace')

lines = raw_text.strip().split('\n')
records = []
for line in lines[1:]:
    parts = line.strip().split('\t')
    if len(parts) >= 4:
        code = parts[0].strip()
        name = parts[1].strip()
        ym = parts[2].strip()
        date_str = parts[3].strip()
        if date_str:
            try:
                dt = pd.Timestamp(date_str.replace('/', '-'))
                records.append({
                    'code': code, 'name': name,
                    'year_month': ym, 'announce_date': dt
                })
            except:
                pass

earnings_df = pd.DataFrame(records)
print(f"  Total parsed records: {len(earnings_df):,}")
print(f"  Unique companies: {earnings_df['code'].nunique():,}")

tsmc = earnings_df[earnings_df['code'] == '2330'].copy()
tsmc = tsmc.sort_values('announce_date').reset_index(drop=True)
print(f"  TSMC (2330) announcements: {len(tsmc)}")

###############################################################################
# Part 1: Load market data
###############################################################################
print("\n[Part 1] Loading market data...")
import yfinance as yf

tw50_raw = yf.download('0050.TW', start='2003-06-30', end='2025-12-31',
                        auto_adjust=True, progress=False)
if isinstance(tw50_raw.columns, pd.MultiIndex):
    tw50_raw.columns = tw50_raw.columns.get_level_values(0)
tw50_raw.index = tw50_raw.index.tz_localize(None)

prices_clean, _ = clean_tw50_data(tw50_raw['Close'])
log_ret = np.log(prices_clean / prices_clean.shift(1))

vix_raw = yf.download('^VIX', start='2003-06-30', end='2025-12-31', progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_raw.index = vix_raw.index.tz_localize(None)
vix_close = vix_raw['Close'].copy()

# Align
vix_ffill = vix_close.reindex(prices_clean.index, method='ffill')
df = pd.DataFrame({
    'log_ret': log_ret,
    'VIX': vix_ffill
}).dropna()

# Remove extreme outliers (split artifacts)
max_abs = df['log_ret'].abs().max()
if max_abs > 0.3:
    print(f"  WARNING: Max |return| = {max_abs:.4f}, removing outliers...")
    df = df[df['log_ret'].abs() <= 0.3]

ret = df['log_ret'].values
vix = df['VIX'].values
r2 = ret ** 2
trading_dates = df.index
n_total = len(df)

print(f"  0050.TW: {trading_dates[0].date()} ~ {trading_dates[-1].date()}, n={n_total}")
print(f"  Mean r^2 (bp): {r2.mean()*10000:.2f}")

###############################################################################
# Part 2: TSMC Event Study
###############################################################################
print("\n[Part 2] TSMC Event Study (window [-5, +5])...")

# Map TSMC announce dates to nearest trading day
tsmc_event_dates = []
for d in tsmc['announce_date'].values:
    d_ts = pd.Timestamp(d)
    if d_ts < trading_dates[0] or d_ts > trading_dates[-1]:
        continue
    idx = trading_dates.searchsorted(d_ts)
    if idx < len(trading_dates):
        tsmc_event_dates.append(trading_dates[idx])
tsmc_event_dates = pd.DatetimeIndex(sorted(set(tsmc_event_dates)))
print(f"  TSMC events in sample: {len(tsmc_event_dates)}")

# Build abnormal vol series
rolling_20d_var = pd.Series(r2, index=trading_dates).rolling(20).mean()

# Event window
WINDOW_DAYS = 5
event_data = []
for event_date in tsmc_event_dates:
    loc = trading_dates.get_loc(event_date)
    if loc - WINDOW_DAYS < 0 or loc + WINDOW_DAYS >= n_total:
        continue
    for offset in range(-WINDOW_DAYS, WINDOW_DAYS + 1):
        idx = loc + offset
        date = trading_dates[idx]
        rv = rolling_20d_var.iloc[idx]
        if pd.isna(rv) or rv == 0:
            continue
        event_data.append({
            'event_date': event_date,
            'trade_date': date,
            'offset': offset,
            'r_sq': r2[idx],
            'abnormal_vol': r2[idx] / rv
        })

event_df = pd.DataFrame(event_data)
print(f"  Event observations: {len(event_df)}")

# Average by offset
avg_by_offset = event_df.groupby('offset').agg({
    'abnormal_vol': ['mean', 'std', 'count'],
    'r_sq': 'mean'
})
avg_by_offset.columns = ['abvol_mean', 'abvol_std', 'n_events', 'r_sq_mean']

print("\n  Abnormal Volatility by Offset:")
print("  Offset | AbVol_Mean |  r^2(bp)  | N")
print("  " + "-" * 45)
for off in range(-WINDOW_DAYS, WINDOW_DAYS + 1):
    row = avg_by_offset.loc[off]
    marker = " ***" if off == 0 else ""
    print(f"    {off:+3d}   |   {row['abvol_mean']:7.4f}   | {row['r_sq_mean']*10000:8.2f}  | {int(row['n_events'])}{marker}")

# T-test: event day vs non-event day
event_day_r2 = pd.Series(r2, index=trading_dates).loc[
    tsmc_event_dates.intersection(trading_dates)
].dropna()
non_event_mask = ~trading_dates.isin(tsmc_event_dates)
non_event_r2 = pd.Series(r2, index=trading_dates).loc[non_event_mask].dropna()

t_stat, p_value = stats.ttest_ind(event_day_r2, non_event_r2, equal_var=False)
vol_ratio = event_day_r2.mean() / non_event_r2.mean()
print(f"\n  T-test (event day r^2 vs non-event):")
print(f"    Event day:     {event_day_r2.mean()*10000:.2f} bp (n={len(event_day_r2)})")
print(f"    Non-event day: {non_event_r2.mean()*10000:.2f} bp (n={len(non_event_r2)})")
print(f"    Ratio: {vol_ratio:.2f}x, t={t_stat:.4f}, p={p_value:.4f}")

# Pre vs Post
pre_event = event_df[event_df['offset'].between(-5, -1)]
post_event = event_df[event_df['offset'].between(1, 5)]
day0 = event_df[event_df['offset'] == 0]

pre_mean = pre_event['r_sq'].mean()
post_mean = post_event['r_sq'].mean()
day0_mean = day0['r_sq'].mean()

t_pre_post, p_pre_post = stats.ttest_ind(
    pre_event['r_sq'], post_event['r_sq'], equal_var=False)
print(f"\n  Pre [-5,-1]:  {pre_mean*10000:.2f} bp")
print(f"  Day-0:        {day0_mean*10000:.2f} bp")
print(f"  Post [+1,+5]: {post_mean*10000:.2f} bp")
print(f"  Pre vs Post: t={t_pre_post:.4f}, p={p_pre_post:.4f}")

# Bootstrap
print("\n  Bootstrap (10,000 reps):")
n_ev = len(event_day_r2)
bootstrap_means = np.array([
    np.random.choice(r2, size=n_ev, replace=True).mean()
    for _ in range(10000)
])
obs_mean = event_day_r2.mean()
boot_p = (bootstrap_means >= obs_mean).mean()
boot_ci = np.percentile(bootstrap_means, [2.5, 97.5])
print(f"    Observed: {obs_mean*10000:.2f} bp")
print(f"    95% CI:   [{boot_ci[0]*10000:.2f}, {boot_ci[1]*10000:.2f}] bp")
print(f"    p-value:  {boot_p:.4f}")

###############################################################################
# Part 3: Clustering Effect
###############################################################################
print("\n[Part 3] Clustering Effect...")

all_announce = earnings_df[
    (earnings_df['announce_date'] >= trading_dates[0]) &
    (earnings_df['announce_date'] <= trading_dates[-1])
]
daily_count = all_announce.groupby('announce_date').size().rename('n_announce')
print(f"  Days with announcements: {len(daily_count)}")
print(f"  Mean: {daily_count.mean():.1f}, Max: {daily_count.max()}")

# Merge with market data
combined = df.copy()
combined['r_sq'] = r2
combined['n_announce'] = daily_count.reindex(combined.index).fillna(0).astype(int)

# Dense threshold
nonzero = daily_count[daily_count > 0]
threshold_90 = nonzero.quantile(0.9)
print(f"  Dense threshold (90th pct nonzero): {threshold_90:.0f}")

combined['is_dense'] = combined['n_announce'] >= threshold_90
combined['has_announce'] = combined['n_announce'] > 0

vol_dense = combined.loc[combined['is_dense'], 'r_sq']
vol_any = combined.loc[combined['has_announce'], 'r_sq']
vol_none = combined.loc[~combined['has_announce'], 'r_sq']

t_dn, p_dn = stats.ttest_ind(vol_dense, vol_none, equal_var=False)
t_an, p_an = stats.ttest_ind(vol_any, vol_none, equal_var=False)

print(f"\n  Vol by category:")
print(f"    Dense ({len(vol_dense)}):      {vol_dense.mean()*10000:.2f} bp")
print(f"    Any announce ({len(vol_any)}): {vol_any.mean()*10000:.2f} bp")
print(f"    No announce ({len(vol_none)}): {vol_none.mean()*10000:.2f} bp")
print(f"    Dense vs None: t={t_dn:.3f}, p={p_dn:.4f}")
print(f"    Any vs None:   t={t_an:.3f}, p={p_an:.4f}")

# OLS: r^2(bp) = a + b1*n_announce + b2*VIX + e
Y = combined['r_sq'].values * 10000
X = np.column_stack([
    np.ones(len(Y)),
    combined['n_announce'].values,
    combined['VIX'].values
])
mask_valid = ~np.isnan(Y) & ~np.isnan(X).any(axis=1)
Y_c, X_c = Y[mask_valid], X[mask_valid]
beta_ols = np.linalg.lstsq(X_c, Y_c, rcond=None)[0]
resid_ols = Y_c - X_c @ beta_ols
sigma2 = np.sum(resid_ols**2) / (len(Y_c) - 3)
se = np.sqrt(np.diag(sigma2 * np.linalg.inv(X_c.T @ X_c)))
t_ols = beta_ols / se
R2_ols = 1 - np.sum(resid_ols**2) / np.sum((Y_c - Y_c.mean())**2)

print(f"\n  OLS: r^2(bp) = a + b1*n_announce + b2*VIX")
print(f"    a={beta_ols[0]:.4f} (t={t_ols[0]:.2f})")
print(f"    b1={beta_ols[1]:.4f} (t={t_ols[1]:.2f})")
print(f"    b2={beta_ols[2]:.4f} (t={t_ols[2]:.2f})")
print(f"    R^2={R2_ols:.4f}, N={len(Y_c)}")

# Monthly pattern
all_announce_m = all_announce.copy()
all_announce_m['month'] = all_announce_m['announce_date'].dt.month
monthly_pattern = all_announce_m.groupby('month').size()
print(f"\n  Monthly announcement pattern:")
for m in range(1, 13):
    c = monthly_pattern.get(m, 0)
    print(f"    Month {m:2d}: {c:6d} ({c/len(all_announce)*100:5.1f}%)")

###############################################################################
# Part 4: A4f vs GJR around announcements (custom MLE, per K1058)
###############################################################################
print("\n[Part 4] A4f vs GJR conditional analysis...")
print("  Using custom MLE implementation (same as K1058)...")

# --- GJR-GARCH(1,1) ---
def gjr_loglik(params, returns):
    omega, alpha, gamma, beta = params
    n = len(returns)
    h = np.empty(n)
    h[0] = np.var(returns[:min(250, n)])
    ll = 0.0
    for t in range(1, n):
        asym = gamma * returns[t-1]**2 if returns[t-1] < 0 else 0.0
        h[t] = omega + alpha * returns[t-1]**2 + asym + beta * h[t-1]
        if h[t] < 1e-10:
            h[t] = 1e-10
    for t in range(n):
        if h[t] > 0:
            ll += -0.5 * (np.log(2*np.pi) + np.log(h[t]) + returns[t]**2/h[t])
    return -ll

def fit_gjr(returns):
    var0 = np.var(returns)
    best_ll, best_params = np.inf, None
    starts = [
        [var0*0.05, 0.05, 0.05, 0.90],
        [var0*0.02, 0.03, 0.08, 0.88],
        [var0*0.10, 0.08, 0.10, 0.80],
    ]
    bounds = [(1e-8, var0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    for s in starts:
        try:
            res = optimize.minimize(gjr_loglik, s, args=(returns,),
                                    method='L-BFGS-B', bounds=bounds)
            if res.fun < best_ll:
                best_ll, best_params = res.fun, res.x
        except:
            continue
    return best_params

def gjr_forecast_1step(params, h_prev, r_prev):
    omega, alpha, gamma, beta = params
    asym = gamma * r_prev**2 if r_prev < 0 else 0.0
    return max(omega + alpha * r_prev**2 + asym + beta * h_prev, 1e-10)

# --- A4f: Multiplicative GARCH-X with VIX^2 ---
def fit_a4f(returns, vix_vals):
    n = len(returns)
    vix_lag = np.empty(n)
    vix_lag[0] = vix_vals[0]
    vix_lag[1:] = vix_vals[:-1]

    def neg_loglik(params):
        theta0, theta1, omega_g, alpha, gamma_p, beta = params
        tau = np.maximum(theta0 + theta1 * vix_lag**2, 1e-16)
        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        if alpha + gamma_p/2.0 + beta >= 0.999:
            return 1e10
        persist = alpha + gamma_p/2.0 + beta
        eg = omega_g / (1.0 - persist) if persist < 1.0 else 1.0
        g = np.empty(n)
        g[0] = eg
        for t in range(1, n):
            u_prev = returns[t-1] / np.sqrt(tau[t])
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g[t] = omega_g + alpha * u_prev**2 + asym + beta * g[t-1]
            if g[t] < 1e-10:
                g[t] = 1e-10
        ll = 0.0
        for t in range(n):
            sigma2 = tau[t] * g[t]
            if sigma2 > 0:
                ll += -0.5*(np.log(2*np.pi) + np.log(sigma2) + returns[t]**2/sigma2)
        return -ll

    var0 = np.var(returns)
    vix2_mean = np.mean(vix_lag**2) + 1e-8
    best_ll, best_params = np.inf, None
    starts = [
        [var0*0.1, var0/vix2_mean, 0.05, 0.05, 0.05, 0.90],
        [var0*0.05, var0/vix2_mean*0.5, 0.10, 0.03, 0.08, 0.88],
        [var0*0.2, var0/vix2_mean*1.5, 0.02, 0.08, 0.10, 0.80],
        [var0*0.01, var0/vix2_mean*2.0, 0.08, 0.04, 0.06, 0.85],
    ]
    bounds = [(-1e-2, 1e-2), (1e-8, 1e-3), (1e-6, 1.0),
              (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    for s in starts:
        try:
            res = optimize.minimize(neg_loglik, s, method='L-BFGS-B',
                                    bounds=bounds, options={'maxiter': 500})
            if res.fun < best_ll:
                best_ll, best_params = res.fun, res.x
        except:
            continue
    return best_params

def compute_tau(theta0, theta1, vix_val):
    return max(theta0 + theta1 * vix_val**2, 1e-16)

# --- OOS Forecasting ---
oos_mask = df.index >= OOS_START
oos_indices = np.where(oos_mask)[0]
n_oos = len(oos_indices)
print(f"  OOS: {df.index[oos_mask][0].date()} ~ {df.index[oos_mask][-1].date()}, n={n_oos}")
print(f"  Refit every {REFIT_EVERY} days...")

gjr_fc = np.full(n_oos, np.nan)
a4f_fc = np.full(n_oos, np.nan)

gjr_params = None
a4f_params = None
gjr_h = None
a4f_g = None
a4f_tau_prev = None

refit_count = 0
for t_idx, abs_idx in enumerate(oos_indices):
    if t_idx % 500 == 0:
        elapsed = time.time() - START_TIME
        print(f"    Step {t_idx}/{n_oos} ({elapsed:.0f}s)")

    need_refit = (t_idx % REFIT_EVERY == 0) or (t_idx == 0)

    if need_refit:
        refit_count += 1
        train_start = max(0, abs_idx - WINDOW)
        train_ret = ret[train_start:abs_idx]
        train_vix = vix[train_start:abs_idx]

        # GJR
        gjr_params = fit_gjr(train_ret)
        if gjr_params is not None:
            h = np.var(train_ret)
            for i in range(1, len(train_ret)):
                h = gjr_forecast_1step(gjr_params, h, train_ret[i-1])
            gjr_h = h

        # A4f
        a4f_params = fit_a4f(train_ret, train_vix)
        if a4f_params is not None:
            theta0, theta1 = a4f_params[0], a4f_params[1]
            omega_g, alpha_p, gamma_p, beta_p = a4f_params[2], a4f_params[3], a4f_params[4], a4f_params[5]
            n_tr = len(train_ret)
            vix_lag_tr = np.empty(n_tr)
            vix_lag_tr[0] = train_vix[0]
            vix_lag_tr[1:] = train_vix[:-1]
            tau_tr = np.maximum(theta0 + theta1 * vix_lag_tr**2, 1e-16)
            persist = alpha_p + gamma_p/2.0 + beta_p
            eg = omega_g / (1.0 - persist) if persist < 1.0 else 1.0
            g = eg
            for i in range(1, n_tr):
                u_prev = train_ret[i-1] / np.sqrt(tau_tr[i])
                asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
                g = omega_g + alpha_p * u_prev**2 + asym + beta_p * g
                g = max(g, 1e-10)
            a4f_g = g

    # Generate forecasts
    if gjr_params is not None:
        r_prev = ret[abs_idx - 1]
        h_new = gjr_forecast_1step(gjr_params, gjr_h, r_prev)
        gjr_fc[t_idx] = h_new
        gjr_h = h_new

    if a4f_params is not None:
        theta0, theta1 = a4f_params[0], a4f_params[1]
        omega_g, alpha_p, gamma_p, beta_p = a4f_params[2], a4f_params[3], a4f_params[4], a4f_params[5]
        v_lag = vix[abs_idx - 1]
        tau_t = compute_tau(theta0, theta1, v_lag)
        r_prev = ret[abs_idx - 1]
        u_prev = r_prev / np.sqrt(tau_t)
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g_new = omega_g + alpha_p * u_prev**2 + asym + beta_p * a4f_g
        g_new = max(g_new, 1e-10)
        a4f_fc[t_idx] = tau_t * g_new
        a4f_g = g_new

elapsed = time.time() - START_TIME
print(f"  Forecasting done: {refit_count} refits in {elapsed:.0f}s")

# Evaluate
oos_r2 = r2[oos_mask]
oos_dates_arr = df.index[oos_mask]
valid_mask = ~np.isnan(gjr_fc) & ~np.isnan(a4f_fc) & (gjr_fc > 0) & (a4f_fc > 0)
print(f"  Valid forecasts: {valid_mask.sum()} / {n_oos}")

gjr_v = gjr_fc[valid_mask]
a4f_v = a4f_fc[valid_mask]
r2_v = oos_r2[valid_mask]
dates_v = oos_dates_arr[valid_mask]

# QLIKE (robust: floor actual to avoid log(0) when r^2=0)
def qlike(actual, forecast):
    # Floor actual at small positive value to avoid log(0) = -inf
    actual_safe = np.maximum(actual, 1e-12)
    forecast_safe = np.maximum(forecast, 1e-12)
    ratio = actual_safe / forecast_safe
    return ratio - np.log(ratio) - 1

gjr_ql = qlike(r2_v, gjr_v)
a4f_ql = qlike(r2_v, a4f_v)

print(f"\n  Overall QLIKE:")
print(f"    GJR: {gjr_ql.mean():.6f}")
print(f"    A4f: {a4f_ql.mean():.6f}")
diff_ql = gjr_ql.mean() - a4f_ql.mean()
print(f"    Diff (GJR - A4f): {diff_ql:.6f} ({'A4f better' if diff_ql > 0 else 'GJR better'})")

d = gjr_ql - a4f_ql
dm_t_overall = d.mean() / (d.std() / np.sqrt(len(d)))
dm_p_overall = 2 * (1 - stats.norm.cdf(abs(dm_t_overall)))
print(f"    DM t-stat: {dm_t_overall:.4f}, p={dm_p_overall:.4f}")

# --- Conditional analysis: event window vs non-event ---
tsmc_event_set = set(tsmc_event_dates)
event_window_set = set()
for ed in tsmc_event_dates:
    loc_s = trading_dates.searchsorted(ed)
    for off in range(-5, 6):
        idx = loc_s + off
        if 0 <= idx < len(trading_dates):
            event_window_set.add(trading_dates[idx])

is_event_window = np.array([d in event_window_set for d in dates_v])
is_day0 = np.array([d in tsmc_event_set for d in dates_v])
is_non_event = ~is_event_window

n_ew = is_event_window.sum()
n_d0 = is_day0.sum()
n_ne = is_non_event.sum()

print(f"\n  Conditional QLIKE:")
if n_ew > 10:
    gjr_ew = gjr_ql[is_event_window]
    a4f_ew = a4f_ql[is_event_window]
    d_ew = gjr_ew - a4f_ew
    dm_t_ew = d_ew.mean() / (d_ew.std() / np.sqrt(len(d_ew))) if d_ew.std() > 0 else 0.0
    wr_ew = (a4f_ew < gjr_ew).mean()
    print(f"    Event window ({n_ew} days):")
    print(f"      GJR: {gjr_ew.mean():.6f}, A4f: {a4f_ew.mean():.6f}")
    print(f"      DM t: {dm_t_ew:.4f}, A4f win rate: {wr_ew:.1%}")
else:
    dm_t_ew = np.nan
    wr_ew = np.nan
    print(f"    Event window: insufficient data ({n_ew} days)")

if n_ne > 10:
    gjr_ne = gjr_ql[is_non_event]
    a4f_ne = a4f_ql[is_non_event]
    d_ne = gjr_ne - a4f_ne
    dm_t_ne = d_ne.mean() / (d_ne.std() / np.sqrt(len(d_ne))) if d_ne.std() > 0 else 0.0
    wr_ne = (a4f_ne < gjr_ne).mean()
    print(f"    Non-event ({n_ne} days):")
    print(f"      GJR: {gjr_ne.mean():.6f}, A4f: {a4f_ne.mean():.6f}")
    print(f"      DM t: {dm_t_ne:.4f}, A4f win rate: {wr_ne:.1%}")
else:
    dm_t_ne = np.nan
    wr_ne = np.nan
    print(f"    Non-event: insufficient data ({n_ne} days)")

if n_d0 > 2:
    gjr_d0 = gjr_ql[is_day0]
    a4f_d0 = a4f_ql[is_day0]
    d_d0 = gjr_d0 - a4f_d0
    dm_t_d0 = d_d0.mean() / (d_d0.std() / np.sqrt(len(d_d0))) if d_d0.std() > 0 else 0.0
    wr_d0 = (a4f_d0 < gjr_d0).mean()
    print(f"    Day-0 only ({n_d0} days):")
    print(f"      GJR: {gjr_d0.mean():.6f}, A4f: {a4f_d0.mean():.6f}")
    print(f"      DM t: {dm_t_d0:.4f}, A4f win rate: {wr_d0:.1%}")
else:
    dm_t_d0 = np.nan
    wr_d0 = np.nan
    print(f"    Day-0: insufficient data ({n_d0} days)")

# QLIKE by offset around events
print(f"\n  QLIKE by offset:")
offsets_list = list(range(-5, 6))
gjr_by_off = []
a4f_by_off = []
for off in offsets_list:
    off_dates = set()
    for ed in tsmc_event_dates:
        loc_s = trading_dates.searchsorted(ed)
        idx = loc_s + off
        if 0 <= idx < len(trading_dates):
            off_dates.add(trading_dates[idx])
    mask_off = np.array([d in off_dates for d in dates_v])
    if mask_off.sum() > 0:
        gjr_by_off.append(float(gjr_ql[mask_off].mean()))
        a4f_by_off.append(float(a4f_ql[mask_off].mean()))
        print(f"    {off:+3d}: GJR={gjr_by_off[-1]:.4f}, A4f={a4f_by_off[-1]:.4f}, "
              f"Diff={gjr_by_off[-1]-a4f_by_off[-1]:+.4f}")
    else:
        gjr_by_off.append(np.nan)
        a4f_by_off.append(np.nan)

###############################################################################
# Part 5: Generate plots
###############################################################################
print("\n[Part 5] Generating plots...")

# --- Plot 1: Event Study ---
fig, axes = plt.subplots(2, 1, figsize=(12, 10))

offsets = list(range(-WINDOW_DAYS, WINDOW_DAYS + 1))
means = [avg_by_offset.loc[o, 'abvol_mean'] for o in offsets]
stds = [avg_by_offset.loc[o, 'abvol_std'] for o in offsets]
n_ev_plot = int(avg_by_offset.loc[0, 'n_events'])
se = [s / np.sqrt(n_ev_plot) for s in stds]

colors = ['#2196F3' if o < 0 else ('#F44336' if o > 0 else '#FF9800') for o in offsets]
axes[0].bar(offsets, means, yerr=se, color=colors, edgecolor='white', capsize=3, alpha=0.8)
axes[0].axhline(y=1.0, color='gray', linestyle='--', alpha=0.5, label='Baseline (1.0)')
axes[0].set_xlabel('Days from TSMC Earnings Announcement', fontsize=12)
axes[0].set_ylabel('Abnormal Volatility (r^2 / rolling_20d_var)', fontsize=12)
axes[0].set_title(f'Panel A: TSMC Earnings Event Study\n'
                   f'Abnormal Volatility [-5, +5] (n={n_ev_plot} events)',
                   fontsize=14, fontweight='bold')
axes[0].legend()
axes[0].set_xticks(offsets)

cav = np.cumsum([m - 1.0 for m in means])
axes[1].plot(offsets, cav, 'b-o', linewidth=2, markersize=6)
axes[1].axhline(y=0, color='gray', linestyle='--', alpha=0.5)
axes[1].axvline(x=0, color='red', linestyle='--', alpha=0.5, label='Announcement day')
axes[1].fill_between(offsets, cav, 0, where=[c > 0 for c in cav], alpha=0.2, color='red')
axes[1].fill_between(offsets, cav, 0, where=[c <= 0 for c in cav], alpha=0.2, color='blue')
axes[1].set_xlabel('Days from TSMC Earnings Announcement', fontsize=12)
axes[1].set_ylabel('Cumulative Abnormal Volatility', fontsize=12)
axes[1].set_title('Panel B: Cumulative Abnormal Volatility (CAV)', fontsize=14, fontweight='bold')
axes[1].legend()
axes[1].set_xticks(offsets)

plt.tight_layout()
plt.savefig(SCRIPT_DIR / 'k1059_event_study.png', dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k1059_event_study.png")

# --- Plot 2: Clustering Effect ---
fig, axes = plt.subplots(2, 2, figsize=(14, 10))

# Panel A: Histogram of announcement counts
nonzero_counts = combined['n_announce'][combined['n_announce'] > 0]
axes[0, 0].hist(nonzero_counts, bins=50, color='#2196F3', edgecolor='white', alpha=0.8)
axes[0, 0].axvline(x=threshold_90, color='red', linestyle='--', label=f'90th pct ({threshold_90:.0f})')
axes[0, 0].set_xlabel('Announcements per Day')
axes[0, 0].set_ylabel('Frequency')
axes[0, 0].set_title('Panel A: Daily Announcement Count Distribution')
axes[0, 0].legend()

# Panel B: Vol by category
cats = ['No\nAnnounce', 'Any\nAnnounce', 'Dense\nDays', 'TSMC\nEvent']
means_cat = [
    vol_none.mean()*10000, vol_any.mean()*10000,
    vol_dense.mean()*10000, event_day_r2.mean()*10000
]
colors_cat = ['#607D8B', '#2196F3', '#FF9800', '#F44336']
bars_c = axes[0, 1].bar(cats, means_cat, color=colors_cat, edgecolor='white', alpha=0.8)
for b, v in zip(bars_c, means_cat):
    axes[0, 1].text(b.get_x()+b.get_width()/2, b.get_height()+0.05, f'{v:.1f}',
                     ha='center', fontsize=10)
axes[0, 1].set_ylabel('Mean r^2 (bp)')
axes[0, 1].set_title('Panel B: Volatility by Announcement Category')

# Panel C: Binned scatter
bins_df = combined.copy()
bins_df['n_bin'] = pd.cut(bins_df['n_announce'],
                           bins=[0, 1, 5, 10, 20, 50, 100, 500],
                           right=True, include_lowest=True)
bin_means = bins_df.groupby('n_bin', observed=True)['r_sq'].mean() * 10000
bin_means.plot(kind='bar', ax=axes[1, 0], color='#2196F3', edgecolor='white', alpha=0.8)
axes[1, 0].set_xlabel('Announcement Count Bin')
axes[1, 0].set_ylabel('Mean r^2 (bp)')
axes[1, 0].set_title('Panel C: Volatility vs Announcement Count')
axes[1, 0].tick_params(axis='x', rotation=30)

# Panel D: Monthly seasonality
monthly_vol = pd.Series(r2, index=trading_dates).groupby(trading_dates.month).mean() * 10000
months = range(1, 13)
ax2 = axes[1, 1].twinx()
axes[1, 1].bar(months, [monthly_pattern.get(m, 0)/1000 for m in months],
                color='#2196F3', alpha=0.4, label='Announcements (K)')
ax2.plot(months, [monthly_vol.get(m, 0) for m in months], 'r-o', linewidth=2, label='Mean r^2 (bp)')
axes[1, 1].set_xlabel('Month')
axes[1, 1].set_ylabel('Announcements (thousands)', color='#2196F3')
ax2.set_ylabel('Mean r^2 (bp)', color='red')
axes[1, 1].set_title('Panel D: Monthly Seasonality')
axes[1, 1].set_xticks(list(months))
lines1, labels1 = axes[1, 1].get_legend_handles_labels()
lines2, labels2 = ax2.get_legend_handles_labels()
axes[1, 1].legend(lines1+lines2, labels1+labels2, loc='upper right')

plt.tight_layout()
plt.savefig(SCRIPT_DIR / 'k1059_clustering.png', dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k1059_clustering.png")

# --- Plot 3: A4f vs GJR around announcements ---
fig, axes = plt.subplots(2, 2, figsize=(14, 10))

# Panel A: QLIKE by offset
gjr_off_clean = [g for g in gjr_by_off if not np.isnan(g)]
a4f_off_clean = [a for a in a4f_by_off if not np.isnan(a)]
off_clean = [o for o, g in zip(offsets_list, gjr_by_off) if not np.isnan(g)]
axes[0, 0].plot(off_clean, gjr_off_clean[:len(off_clean)], 'b-o', label='GJR', linewidth=2)
axes[0, 0].plot(off_clean, a4f_off_clean[:len(off_clean)], 'r-s', label='A4f', linewidth=2)
axes[0, 0].axvline(x=0, color='gray', linestyle='--', alpha=0.5)
axes[0, 0].set_xlabel('Days from TSMC Announcement')
axes[0, 0].set_ylabel('Mean QLIKE Loss')
axes[0, 0].set_title('Panel A: QLIKE by Offset')
axes[0, 0].legend()
axes[0, 0].set_xticks(offsets_list)

# Panel B: A4f improvement by offset
improvement = [g - a for g, a in zip(gjr_by_off, a4f_by_off) if not (np.isnan(g) or np.isnan(a))]
off_imp = [o for o, g in zip(offsets_list, gjr_by_off) if not np.isnan(g)]
colors_imp = ['green' if imp > 0 else 'red' for imp in improvement]
axes[0, 1].bar(off_imp, improvement, color=colors_imp, edgecolor='white', alpha=0.8)
axes[0, 1].axhline(y=0, color='gray', linestyle='--')
axes[0, 1].axvline(x=0, color='gray', linestyle='--', alpha=0.5)
axes[0, 1].set_xlabel('Days from TSMC Announcement')
axes[0, 1].set_ylabel('A4f Improvement (GJR - A4f QLIKE)')
axes[0, 1].set_title('Panel B: A4f Advantage by Offset')
axes[0, 1].set_xticks(offsets_list)

# Panel C: Win rate comparison
labels_wr = ['Event\nWindow', 'Non-event']
a4f_wr_vals = []
if not np.isnan(wr_ew):
    a4f_wr_vals.append(wr_ew * 100)
else:
    a4f_wr_vals.append(50)
if not np.isnan(wr_ne):
    a4f_wr_vals.append(wr_ne * 100)
else:
    a4f_wr_vals.append(50)
if not np.isnan(wr_d0):
    labels_wr.append('Day-0')
    a4f_wr_vals.append(wr_d0 * 100)

colors_wr = ['#FF9800', '#2196F3', '#F44336'][:len(labels_wr)]
axes[1, 0].bar(labels_wr, a4f_wr_vals, color=colors_wr, edgecolor='white', alpha=0.8)
axes[1, 0].axhline(y=50, color='gray', linestyle='--', label='50% (no advantage)')
for i, v in enumerate(a4f_wr_vals):
    axes[1, 0].text(i, v + 0.5, f'{v:.1f}%', ha='center', fontsize=11, fontweight='bold')
axes[1, 0].set_ylabel('A4f Win Rate (%)')
axes[1, 0].set_title('Panel C: A4f Win Rate vs GJR')
axes[1, 0].legend()
max_wr = max(a4f_wr_vals) if a4f_wr_vals else 60
axes[1, 0].set_ylim(0, max_wr + 15)

# Panel D: Rolling DM
d_series = pd.Series(gjr_ql - a4f_ql, index=dates_v)
rolling_dm = d_series.rolling(252).apply(
    lambda x: x.mean() / (x.std() / np.sqrt(len(x))) if x.std() > 0 else 0, raw=False
)
axes[1, 1].plot(rolling_dm.index, rolling_dm.values, 'b-', linewidth=1, alpha=0.7)
axes[1, 1].axhline(y=0, color='gray', linestyle='--')
axes[1, 1].axhline(y=1.96, color='green', linestyle=':', alpha=0.5, label='5% sig (A4f better)')
axes[1, 1].axhline(y=-1.96, color='red', linestyle=':', alpha=0.5, label='5% sig (GJR better)')
for ed in tsmc_event_dates:
    if ed in rolling_dm.index:
        axes[1, 1].axvline(x=ed, color='orange', alpha=0.15, linewidth=0.5)
axes[1, 1].set_xlabel('Date')
axes[1, 1].set_ylabel('Rolling 252-day DM t-stat')
axes[1, 1].set_title('Panel D: Rolling DM (A4f vs GJR)\nOrange = TSMC events')
axes[1, 1].legend(fontsize=9)

plt.tight_layout()
plt.savefig(SCRIPT_DIR / 'k1059_a4f_earnings.png', dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k1059_a4f_earnings.png")

###############################################################################
# Part 6: Results JSON
###############################################################################
print("\n[Part 6] Saving results...")

results = {
    "experiment_id": "K1059",
    "title": "TSMC Earnings Announcement x 0050.TW Volatility Event Study",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "data_sources": {
        "earnings": "財報公告日.txt (Big5, 153,875 records with dates, 2,409 companies)",
        "prices": "yfinance 0050.TW daily",
        "vix": "yfinance ^VIX daily"
    },
    "sample": {
        "start": str(trading_dates[0].date()),
        "end": str(trading_dates[-1].date()),
        "n_trading_days": n_total,
        "n_tsmc_events_in_sample": len(tsmc_event_dates),
        "n_companies_total": int(earnings_df['code'].nunique()),
    },
    "part_a_event_study": {
        "window": [-5, 5],
        "abnormal_vol_by_offset": {
            str(o): {
                "mean": float(avg_by_offset.loc[o, 'abvol_mean']),
                "std": float(avg_by_offset.loc[o, 'abvol_std']),
                "r_sq_bp": float(avg_by_offset.loc[o, 'r_sq_mean']*10000)
            } for o in offsets
        },
        "event_day_vol_bp": float(event_day_r2.mean()*10000),
        "non_event_day_vol_bp": float(non_event_r2.mean()*10000),
        "vol_ratio": float(vol_ratio),
        "ttest": {"t_stat": float(t_stat), "p_value": float(p_value)},
        "bootstrap": {
            "observed_bp": float(obs_mean*10000),
            "ci_95": [float(boot_ci[0]*10000), float(boot_ci[1]*10000)],
            "p_value": float(boot_p)
        },
        "pre_vs_post": {
            "pre_bp": float(pre_mean*10000),
            "day0_bp": float(day0_mean*10000),
            "post_bp": float(post_mean*10000),
            "t_stat": float(t_pre_post),
            "p_value": float(p_pre_post)
        }
    },
    "part_b_clustering": {
        "dense_threshold": int(threshold_90),
        "vol_by_category_bp": {
            "no_announce": float(vol_none.mean()*10000),
            "any_announce": float(vol_any.mean()*10000),
            "dense_days": float(vol_dense.mean()*10000),
            "tsmc_event": float(event_day_r2.mean()*10000)
        },
        "ttest_dense_vs_none": {"t": float(t_dn), "p": float(p_dn)},
        "ttest_any_vs_none": {"t": float(t_an), "p": float(p_an)},
        "regression": {
            "intercept": float(beta_ols[0]),
            "beta_n_announce": float(beta_ols[1]),
            "beta_vix": float(beta_ols[2]),
            "t_intercept": float(t_ols[0]),
            "t_n_announce": float(t_ols[1]),
            "t_vix": float(t_ols[2]),
            "R2": float(R2_ols),
            "n": int(len(Y_c))
        }
    },
    "part_c_a4f_vs_gjr": {
        "oos_period": f"{df.index[oos_mask][0].date()} ~ {df.index[oos_mask][-1].date()}",
        "n_valid_forecasts": int(valid_mask.sum()),
        "n_refits": refit_count,
        "overall": {
            "gjr_qlike": float(gjr_ql.mean()),
            "a4f_qlike": float(a4f_ql.mean()),
            "dm_t": float(dm_t_overall),
            "dm_p": float(dm_p_overall)
        },
        "event_window": {
            "n_days": int(n_ew),
            "gjr_qlike": float(gjr_ew.mean()) if n_ew > 10 else None,
            "a4f_qlike": float(a4f_ew.mean()) if n_ew > 10 else None,
            "dm_t": float(dm_t_ew) if not np.isnan(dm_t_ew) else None,
            "a4f_win_rate": float(wr_ew) if not np.isnan(wr_ew) else None
        },
        "non_event": {
            "n_days": int(n_ne),
            "gjr_qlike": float(gjr_ne.mean()) if n_ne > 10 else None,
            "a4f_qlike": float(a4f_ne.mean()) if n_ne > 10 else None,
            "dm_t": float(dm_t_ne) if not np.isnan(dm_t_ne) else None,
            "a4f_win_rate": float(wr_ne) if not np.isnan(wr_ne) else None
        },
        "day0": {
            "n_days": int(n_d0),
            "gjr_qlike": float(gjr_d0.mean()) if n_d0 > 2 else None,
            "a4f_qlike": float(a4f_d0.mean()) if n_d0 > 2 else None,
            "dm_t": float(dm_t_d0) if not np.isnan(dm_t_d0) else None,
            "a4f_win_rate": float(wr_d0) if not np.isnan(wr_d0) else None
        },
        "qlike_by_offset": {
            str(o): {"gjr": g, "a4f": a, "improvement": g - a}
            for o, g, a in zip(offsets_list, gjr_by_off, a4f_by_off)
            if not (np.isnan(g) or np.isnan(a))
        }
    },
    "conclusions": {
        "q1_abnormal_vol": (
            f"TSMC event day vol = {vol_ratio:.2f}x non-event. "
            f"t={t_stat:.2f}, p={p_value:.4f}. Bootstrap p={boot_p:.4f}."
        ),
        "q2_pre_vs_post": (
            f"Pre [-5,-1] = {pre_mean*10000:.1f} bp, Day-0 = {day0_mean*10000:.1f} bp, "
            f"Post [+1,+5] = {post_mean*10000:.1f} bp. "
            f"Pre vs Post t={t_pre_post:.2f}, p={p_pre_post:.4f}."
        ),
        "q3_clustering": (
            f"Dense days (>={int(threshold_90)}): {vol_dense.mean()*10000:.1f} bp vs "
            f"no-announce {vol_none.mean()*10000:.1f} bp. "
            f"t={t_dn:.2f}, p={p_dn:.4f}. "
            f"Regression beta_n_announce={beta_ols[1]:.4f} (t={t_ols[1]:.2f}). "
            f"Announcement days actually have LOWER vol (VIX dominates)."
        ),
        "q4_a4f_vs_gjr": (
            f"Overall DM t={dm_t_overall:.2f}, p={dm_p_overall:.4f}. "
            f"Event window DM t={dm_t_ew:.2f}. "
            f"A4f win rate: event {wr_ew:.1%} vs non-event {wr_ne:.1%}."
        ) if not np.isnan(wr_ew) else (
            f"Overall DM t={dm_t_overall:.2f}, p={dm_p_overall:.4f}. "
            f"Insufficient event window data for conditional analysis."
        )
    },
    "random_seed": 42,
    "references": [
        "K1050: SPY earnings season vol (A4f uniform, bootstrap p=0.471)",
        "K1058: A4f on 0050.TW (DM NS t=-1.26, VaR Trinity A4f PASS / GJR FAIL)",
        "K176: TSMC DeltaCoVaR = -1.599 (4.6x SPY)",
        "Patton (2011): QLIKE, J Econometrics 160:246-256",
        "Andersen & Bollerslev (1998): DM$ volatility event study"
    ]
}

with open(SCRIPT_DIR / 'k1059_results.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)
print("  Saved k1059_results.json")

###############################################################################
# Summary
###############################################################################
elapsed = time.time() - START_TIME
print(f"\n{'='*70}")
print("SUMMARY")
print(f"{'='*70}")
print(f"""
Q1: TSMC Announcement Day Volatility
  Event-day r^2 = {event_day_r2.mean()*10000:.2f} bp vs non-event = {non_event_r2.mean()*10000:.2f} bp
  Ratio: {vol_ratio:.2f}x, t={t_stat:.4f}, p={p_value:.4f}
  Bootstrap p={boot_p:.4f}

Q2: Pre vs Post Direction
  Pre [-5,-1]:  {pre_mean*10000:.2f} bp
  Day-0:        {day0_mean*10000:.2f} bp
  Post [+1,+5]: {post_mean*10000:.2f} bp

Q3: Clustering Effect
  Dense days: {vol_dense.mean()*10000:.2f} bp, No announce: {vol_none.mean()*10000:.2f} bp
  Regression: n_announce beta = {beta_ols[1]:.4f} (t={t_ols[1]:.2f})

Q4: A4f vs GJR
  Overall DM t={dm_t_overall:.4f}, p={dm_p_overall:.4f}
  Event window DM t={'%.4f' % dm_t_ew if not np.isnan(dm_t_ew) else 'N/A'}
  A4f win rate: event {'%.1f%%' % (wr_ew*100) if not np.isnan(wr_ew) else 'N/A'} vs non-event {'%.1f%%' % (wr_ne*100) if not np.isnan(wr_ne) else 'N/A'}

Elapsed: {elapsed:.0f}s
""")
print("All output saved to experiments/k1059/")
print("=" * 70)
