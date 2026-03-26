#!/usr/bin/env python3
"""
K473: Investor Attention (Google Trends) as Vol Signal — Revisit with Proper Methodology

Literature:
  - Da, Engelberg, Gao (2011) "In Search of Attention" JoF
    - Google SVI predicts stock returns and vol; single search term more stable
  - Vlastakis & Markellos (2012) "Information demand and stock market volatility" JBES
    - Google Trends predicts vol, but effect decays over time

Prior results (K192/J3/G14):
  - K192: IS composite r=0.576 but OOS completely failed (-1.5% to -97.7%)
  - J3: "recession" partial r=0.634, "stock market crash" partial r=0.600
    but VT overlay all NS (DM p=0.47-0.80)
  - G14: "stock market crash" spike → next-week SPY -0.70% (t=-3.15),
    but controlling VIX+momentum, it's crash momentum (R²=4.8%)

Improvements over K192:
  1. Only 1-2 search terms (not composite index)
  2. Strict lag: only t-1 search volume
  3. No IS optimization — fixed z-score
  4. Weekly frequency (K457: weekly noise lower)
  5. VIX-based attention proxy as secondary approach

Models:
  1. Lagged RV (baseline)
  2. VIX only (12/VIX benchmark)
  3. Attention proxy only (VIX spike indicator)
  4. VIX + Attention interaction
  5. Weekly aggregated attention
  6. Google Trends direct (if pytrends works)

Asset: SPY
OOS: 2023-01-01 to 2025-12-31
Evaluation: QLIKE, MSE, DM test

Refs: Da, Engelberg, Gao (2011) JoF; Vlastakis & Markellos (2012) JBES
      K192, J3, G14 (prior null results)
"""

import json
import warnings
import time
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings('ignore')

# ============================================================
# Configuration
# ============================================================
OOS_START = '2023-01-01'
DATA_START = '2005-01-01'
ASSET = 'SPY'

# ============================================================
# Helper functions
# ============================================================

def qlike(realized, forecast):
    """QLIKE loss: RV/forecast - log(RV/forecast) - 1"""
    ratio = realized / forecast
    valid = (realized > 0) & (forecast > 0) & np.isfinite(ratio)
    r = ratio[valid]
    return np.mean(r - np.log(r) - 1)

def mse(realized, forecast):
    """Mean Squared Error"""
    valid = np.isfinite(realized) & np.isfinite(forecast)
    return np.mean((realized[valid] - forecast[valid])**2)

def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test (two-sided)
    H0: equal predictive accuracy
    loss1 = losses from model 1, loss2 = losses from model 2
    Negative t-stat means model 2 is better (lower loss)
    """
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 10:
        return np.nan, np.nan
    d_mean = np.mean(d)
    # HAC variance (Newey-West with h-1 lags)
    gamma0 = np.var(d, ddof=1)
    hac_var = gamma0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        hac_var += 2 * (1 - k / h) * gamma_k
    hac_var = max(hac_var, 1e-20)
    dm_stat = d_mean / np.sqrt(hac_var / n)
    p_value = 2 * (1 - stats.t.cdf(abs(dm_stat), df=n - 1))
    return dm_stat, p_value

def rolling_forecast_ols(X_is, y_is, X_oos, expanding=True, min_window=252):
    """Expanding window OLS forecast"""
    n_is = len(X_is)
    n_oos = len(X_oos)
    forecasts = np.full(n_oos, np.nan)

    X_all = np.vstack([X_is, X_oos])
    y_all = np.concatenate([y_is, np.full(n_oos, np.nan)])  # placeholder

    for i in range(n_oos):
        if expanding:
            train_end = n_is + i
            train_start = 0
        else:
            train_end = n_is + i
            train_start = max(0, train_end - min_window)

        X_train = X_all[train_start:train_end]
        y_train = y_all[train_start:train_end]

        valid = np.isfinite(y_train) & np.all(np.isfinite(X_train), axis=1)
        if valid.sum() < min_window // 2:
            continue

        X_v = X_train[valid]
        y_v = y_train[valid]

        try:
            beta, _, _, _ = np.linalg.lstsq(X_v, y_v, rcond=None)
            forecasts[i] = X_oos[i] @ beta
        except Exception:
            continue

    return forecasts

def expanding_ols_forecast(y_target, X_features, is_mask, oos_mask, min_train=504):
    """
    Expanding window OLS: train on all data up to t-1, predict t.
    y_target: full series of target (RV)
    X_features: full DataFrame of features (lagged, so X[t] uses info up to t-1)
    is_mask, oos_mask: boolean masks for IS and OOS periods
    """
    full_idx = y_target.index
    oos_idx = full_idx[oos_mask]
    forecasts = pd.Series(np.nan, index=oos_idx)

    y_arr = y_target.values
    X_arr = X_features.values

    # Find first IS index
    is_indices = np.where(is_mask)[0]
    if len(is_indices) == 0:
        return forecasts

    for oos_pos in np.where(oos_mask)[0]:
        # Train on all data from start to oos_pos - 1
        train_end = oos_pos
        if train_end < min_train:
            continue

        X_train = X_arr[:train_end]
        y_train = y_arr[:train_end]

        valid = np.isfinite(y_train) & np.all(np.isfinite(X_train), axis=1)
        if valid.sum() < min_train // 2:
            continue

        try:
            beta, _, _, _ = np.linalg.lstsq(X_train[valid], y_train[valid], rcond=None)
            pred = X_arr[oos_pos] @ beta
            if np.isfinite(pred) and pred > 0:
                forecasts.iloc[forecasts.index.get_loc(full_idx[oos_pos])] = pred
        except Exception:
            continue

    return forecasts


# ============================================================
# 1. Download data
# ============================================================
print("=" * 70)
print("K473: Investor Attention (Google Trends) as Vol Signal")
print("=" * 70)

t0 = time.time()

print("\n[1] Downloading SPY and VIX data...")
spy = yf.download(ASSET, start=DATA_START, auto_adjust=False, progress=False)
vix = yf.download('^VIX', start=DATA_START, auto_adjust=False, progress=False)

# Flatten columns if MultiIndex
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

spy.index = pd.to_datetime(spy.index).tz_localize(None)
vix.index = pd.to_datetime(vix.index).tz_localize(None)

# ============================================================
# 2. Compute realized volatility and features
# ============================================================
print("[2] Computing realized volatility and features...")

# Daily log returns
spy['log_ret'] = np.log(spy['Close'] / spy['Close'].shift(1))

# Realized volatility (5-day, annualized)
spy['rv5'] = spy['log_ret'].rolling(5).var() * 252

# Realized volatility (21-day, annualized) for weekly target
spy['rv21'] = spy['log_ret'].rolling(21).var() * 252

# Parkinson range-based vol
spy['log_range'] = np.log(spy['High'] / spy['Low'])
spy['parkinson'] = (spy['log_range']**2 / (4 * np.log(2))) * 252

# VIX aligned
spy['vix'] = vix['Close'].reindex(spy.index, method='ffill')
spy['vix_var'] = (spy['vix'] / 100)**2  # VIX² as variance forecast

# Drop initial NaN
spy = spy.dropna(subset=['rv5', 'vix'])

print(f"  Data: {spy.index[0].date()} to {spy.index[-1].date()}")
print(f"  Observations: {len(spy)}")

# ============================================================
# 3. Construct Attention Proxies
# ============================================================
print("[3] Constructing attention proxies...")

# --- Proxy 1: VIX spike indicator (Da et al. style attention proxy) ---
# VIX z-score relative to 63-day rolling window
spy['vix_z'] = (spy['vix'] - spy['vix'].rolling(63).mean()) / spy['vix'].rolling(63).std()
# Binary attention: extreme VIX (> 2 sigma)
spy['attn_spike'] = (spy['vix_z'] > 2).astype(float)
# Continuous attention: clipped normalized VIX z-score [0,1]
spy['attn_level'] = spy['vix_z'].clip(0, 5) / 5

# --- Proxy 2: VIX rate of change (attention = rapid change) ---
spy['vix_roc_5d'] = spy['vix'].pct_change(5)
spy['attn_roc'] = spy['vix_roc_5d'].clip(0, 2) / 2  # [0,1], only increases

# --- Proxy 3: Volume-based attention (abnormal volume) ---
spy['vol_ratio'] = spy['Volume'] / spy['Volume'].rolling(63).mean()
spy['attn_volume'] = (spy['vol_ratio'] - 1).clip(0, 3) / 3  # [0,1]

# --- Proxy 4: Absolute return as attention trigger ---
spy['abs_ret'] = spy['log_ret'].abs()
spy['abs_ret_z'] = (spy['abs_ret'] - spy['abs_ret'].rolling(63).mean()) / spy['abs_ret'].rolling(63).std()
spy['attn_absret'] = spy['abs_ret_z'].clip(0, 5) / 5

print(f"  Attention spike days: {spy['attn_spike'].sum():.0f} ({spy['attn_spike'].mean()*100:.1f}%)")
print(f"  Mean attn_level: {spy['attn_level'].mean():.3f}")
print(f"  Mean attn_roc: {spy['attn_roc'].mean():.3f}")
print(f"  Mean attn_volume: {spy['attn_volume'].mean():.3f}")

# ============================================================
# 4. Try Google Trends (pytrends)
# ============================================================
print("[4] Attempting Google Trends data retrieval...")
gt_success = False
gt_data = None

try:
    from pytrends.request import TrendReq
    import time as time_mod

    pytrends = TrendReq(hl='en-US', tz=360)

    # Only use 1-2 simple terms per Da et al. (2011)
    search_terms = ['stock market crash', 'VIX']

    gt_frames = {}
    for term in search_terms:
        try:
            pytrends.build_payload([term], timeframe='2005-01-01 2026-03-26', geo='US')
            data = pytrends.interest_over_time()
            if data is not None and len(data) > 100:
                gt_frames[term] = data[term]
                print(f"  Got Google Trends for '{term}': {len(data)} weeks")
            time_mod.sleep(2)  # Rate limit
        except Exception as e:
            print(f"  Failed for '{term}': {e}")

    if gt_frames:
        gt_data = pd.DataFrame(gt_frames)
        gt_data.index = pd.to_datetime(gt_data.index).tz_localize(None)
        gt_success = True
        print(f"  Google Trends data: {gt_data.index[0].date()} to {gt_data.index[-1].date()}")
    else:
        print("  No Google Trends data retrieved, using proxy only")

except ImportError:
    print("  pytrends not installed, using proxy only")
except Exception as e:
    print(f"  Google Trends error: {e}, using proxy only")

# ============================================================
# 5. Prepare weekly data for analysis
# ============================================================
print("[5] Preparing weekly data...")

# Resample to weekly (Friday close)
weekly = spy[['Close', 'log_ret', 'vix', 'Volume']].copy()

# Weekly RV: sum of squared daily returns within week, annualized
weekly['rv_week'] = spy['log_ret']**2
weekly_rv = weekly['rv_week'].resample('W-FRI').sum() * 52  # annualized weekly var

# Weekly close and VIX (last of week)
weekly_close = weekly['Close'].resample('W-FRI').last()
weekly_vix = weekly['vix'].resample('W-FRI').last()
weekly_vol = weekly['Volume'].resample('W-FRI').sum()

# Weekly attention proxies (max of week -- captures spike events)
weekly_attn_spike = spy['attn_spike'].resample('W-FRI').max()
weekly_attn_level = spy['attn_level'].resample('W-FRI').max()
weekly_attn_roc = spy['attn_roc'].resample('W-FRI').max()
weekly_attn_volume = spy['attn_volume'].resample('W-FRI').max()
weekly_attn_absret = spy['attn_absret'].resample('W-FRI').max()

# Combine into weekly DataFrame
w = pd.DataFrame({
    'rv': weekly_rv,
    'vix': weekly_vix,
    'volume': weekly_vol,
    'attn_spike': weekly_attn_spike,
    'attn_level': weekly_attn_level,
    'attn_roc': weekly_attn_roc,
    'attn_volume': weekly_attn_volume,
    'attn_absret': weekly_attn_absret,
}).dropna()

# Add Google Trends if available
if gt_success and gt_data is not None:
    for col in gt_data.columns:
        safe_col = col.replace(' ', '_')
        # Align weekly GT data to our weekly index
        gt_weekly = gt_data[col].reindex(w.index, method='ffill')
        # Z-score (rolling 52-week)
        gt_z = (gt_weekly - gt_weekly.rolling(52).mean()) / gt_weekly.rolling(52).std()
        w[f'gt_{safe_col}'] = gt_z.clip(0, 5) / 5  # normalized [0,1], only high attention
        w[f'gt_{safe_col}_raw'] = gt_weekly

# VIX variance forecast
w['vix_var'] = (w['vix'] / 100)**2

# Lagged features (t-1 for strict causality)
for col in [c for c in w.columns if c != 'rv']:
    w[f'{col}_lag1'] = w[col].shift(1)

w['rv_lag1'] = w['rv'].shift(1)
w['rv_lag2'] = w['rv'].shift(2)
w['rv_lag4'] = w['rv'].shift(4)

w = w.dropna()

print(f"  Weekly observations: {len(w)}")
print(f"  Period: {w.index[0].date()} to {w.index[-1].date()}")

# ============================================================
# 6. IS / OOS split
# ============================================================
oos_start = pd.Timestamp(OOS_START)
is_mask = w.index < oos_start
oos_mask = w.index >= oos_start

n_is = is_mask.sum()
n_oos = oos_mask.sum()
print(f"  IS: {n_is} weeks | OOS: {n_oos} weeks")

# ============================================================
# 7. Descriptive statistics
# ============================================================
print("\n[6] Descriptive Statistics (IS period)...")
w_is = w[is_mask]

desc_cols = ['rv', 'vix', 'attn_spike', 'attn_level', 'attn_roc', 'attn_volume']
if gt_success:
    desc_cols += [c for c in w.columns if c.startswith('gt_') and not c.endswith('_raw') and 'lag' not in c]

print(f"\n{'Variable':<20} {'Mean':>10} {'Std':>10} {'Skew':>10} {'Kurt':>10}")
print("-" * 60)
for col in desc_cols:
    if col in w_is.columns:
        s = w_is[col]
        print(f"{col:<20} {s.mean():>10.4f} {s.std():>10.4f} {stats.skew(s):>10.2f} {stats.kurtosis(s):>10.2f}")

# Correlations with next-week RV (IS only)
print(f"\n{'Feature':<20} {'Corr(rv)':>10} {'p-value':>10}")
print("-" * 40)
target = w_is['rv']
for col in ['rv_lag1', 'vix_var_lag1', 'attn_spike_lag1', 'attn_level_lag1',
            'attn_roc_lag1', 'attn_volume_lag1', 'attn_absret_lag1']:
    if col in w_is.columns:
        r, p = stats.pearsonr(w_is[col].dropna(), target.loc[w_is[col].dropna().index])
        print(f"{col:<20} {r:>10.4f} {p:>10.4f}")

if gt_success:
    for col in [c for c in w_is.columns if c.startswith('gt_') and 'lag1' in c and 'raw' not in c]:
        valid = w_is[[col, 'rv']].dropna()
        if len(valid) > 10:
            r, p = stats.pearsonr(valid[col], valid['rv'])
            print(f"{col:<20} {r:>10.4f} {p:>10.4f}")

# ============================================================
# 8. Forecasting models (expanding window OLS)
# ============================================================
print("\n[7] Running forecasting models (expanding window OLS)...")

target = w['rv']
models = {}

# Model 1: Lagged RV only (HAR-style)
X1 = w[['rv_lag1', 'rv_lag2', 'rv_lag4']].copy()
X1.insert(0, 'const', 1.0)
models['M1_LaggedRV'] = ('Lagged RV (HAR)', X1)

# Model 2: VIX only
X2 = w[['vix_var_lag1']].copy()
X2.insert(0, 'const', 1.0)
models['M2_VIX'] = ('VIX only', X2)

# Model 3: VIX + Lagged RV
X3 = w[['rv_lag1', 'vix_var_lag1']].copy()
X3.insert(0, 'const', 1.0)
models['M3_VIX_RV'] = ('VIX + Lagged RV', X3)

# Model 4: Attention level only
X4 = w[['attn_level_lag1']].copy()
X4.insert(0, 'const', 1.0)
models['M4_AttnLevel'] = ('Attention Level only', X4)

# Model 5: VIX + Attention level
X5 = w[['vix_var_lag1', 'attn_level_lag1']].copy()
X5.insert(0, 'const', 1.0)
models['M5_VIX_Attn'] = ('VIX + Attention', X5)

# Model 6: VIX + Attention spike
X6 = w[['vix_var_lag1', 'attn_spike_lag1']].copy()
X6.insert(0, 'const', 1.0)
models['M6_VIX_Spike'] = ('VIX + Attention Spike', X6)

# Model 7: VIX + Volume attention
X7 = w[['vix_var_lag1', 'attn_volume_lag1']].copy()
X7.insert(0, 'const', 1.0)
models['M7_VIX_VolAttn'] = ('VIX + Volume Attention', X7)

# Model 8: VIX + Abs Return attention
X8 = w[['vix_var_lag1', 'attn_absret_lag1']].copy()
X8.insert(0, 'const', 1.0)
models['M8_VIX_AbsRet'] = ('VIX + AbsRet Attention', X8)

# Model 9: VIX + RoC attention
X9 = w[['vix_var_lag1', 'attn_roc_lag1']].copy()
X9.insert(0, 'const', 1.0)
models['M9_VIX_RoC'] = ('VIX + RoC Attention', X9)

# Model 10: Kitchen sink (VIX + all attention)
X10 = w[['rv_lag1', 'vix_var_lag1', 'attn_level_lag1', 'attn_volume_lag1', 'attn_absret_lag1']].copy()
X10.insert(0, 'const', 1.0)
models['M10_KitchenSink'] = ('Kitchen Sink', X10)

# Add Google Trends models if available
if gt_success:
    gt_lag_cols = [c for c in w.columns if c.startswith('gt_') and 'lag1' in c and 'raw' not in c]
    if gt_lag_cols:
        # Model GT1: Google Trends only
        X_gt1 = w[gt_lag_cols].copy()
        X_gt1.insert(0, 'const', 1.0)
        models['M_GT1_TrendsOnly'] = ('Google Trends only', X_gt1)

        # Model GT2: VIX + Google Trends
        X_gt2 = w[['vix_var_lag1'] + gt_lag_cols].copy()
        X_gt2.insert(0, 'const', 1.0)
        models['M_GT2_VIX_Trends'] = ('VIX + Google Trends', X_gt2)

        # Model GT3: VIX + RV + Google Trends
        X_gt3 = w[['rv_lag1', 'vix_var_lag1'] + gt_lag_cols].copy()
        X_gt3.insert(0, 'const', 1.0)
        models['M_GT3_Full'] = ('RV + VIX + Google Trends', X_gt3)

# Run all models
results = {}
oos_rv = target[oos_mask].values

print(f"\n{'Model':<30} {'QLIKE':>10} {'MSE':>12} {'Corr(f,rv)':>12}")
print("-" * 70)

for key, (name, X) in models.items():
    forecasts = expanding_ols_forecast(target, X, is_mask, oos_mask, min_train=200)
    f_vals = forecasts.values
    # Ensure positive forecasts
    f_vals = np.maximum(f_vals, 1e-8)

    valid = np.isfinite(f_vals) & np.isfinite(oos_rv) & (f_vals > 0)
    if valid.sum() < 10:
        print(f"{name:<30} {'N/A':>10} {'N/A':>12} {'N/A':>12}")
        continue

    rv_v = oos_rv[valid]
    f_v = f_vals[valid]

    q = qlike(rv_v, f_v)
    m = mse(rv_v, f_v)
    r, _ = stats.pearsonr(rv_v, f_v)

    results[key] = {
        'name': name,
        'qlike': q,
        'mse': m,
        'corr': r,
        'n_valid': int(valid.sum()),
        'forecasts': f_vals,
        'valid': valid,
    }

    print(f"{name:<30} {q:>10.4f} {m:>12.6f} {r:>12.4f}")

# ============================================================
# 9. DM tests vs baseline (VIX + RV)
# ============================================================
print("\n[8] DM Tests vs M3 (VIX + Lagged RV) baseline...")

if 'M3_VIX_RV' in results:
    baseline = results['M3_VIX_RV']
    base_f = baseline['forecasts']
    base_valid = baseline['valid']

    # QLIKE losses
    base_qloss = np.full(len(oos_rv), np.nan)
    for i in range(len(oos_rv)):
        if base_valid[i] and oos_rv[i] > 0 and base_f[i] > 0:
            ratio = oos_rv[i] / base_f[i]
            base_qloss[i] = ratio - np.log(ratio) - 1

    print(f"\n{'Model':<30} {'DM_stat':>10} {'p-value':>10} {'Better?':>10}")
    print("-" * 60)

    dm_results = {}
    for key, res in results.items():
        if key == 'M3_VIX_RV':
            continue
        f = res['forecasts']
        v = res['valid']

        model_qloss = np.full(len(oos_rv), np.nan)
        for i in range(len(oos_rv)):
            if v[i] and oos_rv[i] > 0 and f[i] > 0:
                ratio = oos_rv[i] / f[i]
                model_qloss[i] = ratio - np.log(ratio) - 1

        dm_stat, dm_p = dm_test(model_qloss, base_qloss)
        better = "YES" if dm_p < 0.10 and dm_stat < 0 else "no"

        dm_results[key] = {'dm_stat': dm_stat, 'dm_p': dm_p, 'better': better}
        print(f"{res['name']:<30} {dm_stat:>10.3f} {dm_p:>10.4f} {better:>10}")
else:
    print("  Baseline M3 not available")
    dm_results = {}

# ============================================================
# 10. Sub-period analysis (OOS stability)
# ============================================================
print("\n[9] Sub-period analysis...")

oos_dates = w.index[oos_mask]
sub_periods = [
    ('2023H1', '2023-01-01', '2023-07-01'),
    ('2023H2', '2023-07-01', '2024-01-01'),
    ('2024H1', '2024-01-01', '2024-07-01'),
    ('2024H2', '2024-07-01', '2025-01-01'),
    ('2025', '2025-01-01', '2026-01-01'),
]

# Compare M3 (VIX+RV) vs M5 (VIX+Attention) across sub-periods
if 'M3_VIX_RV' in results and 'M5_VIX_Attn' in results:
    print(f"\n{'Period':<10} {'M3_QLIKE':>10} {'M5_QLIKE':>10} {'Improvement':>12}")
    print("-" * 45)

    sub_period_results = {}
    for name, start, end in sub_periods:
        mask = (oos_dates >= start) & (oos_dates < end)
        if mask.sum() < 5:
            continue

        rv_sub = oos_rv[mask]
        f3_sub = results['M3_VIX_RV']['forecasts'][mask]
        f5_sub = results['M5_VIX_Attn']['forecasts'][mask]

        valid = np.isfinite(f3_sub) & np.isfinite(f5_sub) & (rv_sub > 0) & (f3_sub > 0) & (f5_sub > 0)
        if valid.sum() < 5:
            continue

        q3 = qlike(rv_sub[valid], f3_sub[valid])
        q5 = qlike(rv_sub[valid], f5_sub[valid])
        imp = (q3 - q5) / q3 * 100

        sub_period_results[name] = {'m3_qlike': q3, 'm5_qlike': q5, 'improvement_pct': imp}
        print(f"{name:<10} {q3:>10.4f} {q5:>10.4f} {imp:>11.1f}%")

# ============================================================
# 11. Incremental R² analysis (IS)
# ============================================================
print("\n[10] Incremental R² analysis (IS period)...")

y_is = w_is['rv']

# Baseline: VIX only
X_base = w_is[['vix_var_lag1']].copy()
X_base.insert(0, 'const', 1.0)
beta_base, _, _, _ = np.linalg.lstsq(X_base.values, y_is.values, rcond=None)
resid_base = y_is.values - X_base.values @ beta_base
ss_base = np.sum(resid_base**2)
ss_total = np.sum((y_is.values - y_is.mean())**2)
r2_base = 1 - ss_base / ss_total

print(f"\n  Baseline (VIX only) R²: {r2_base:.4f}")

attn_cols = ['attn_level_lag1', 'attn_roc_lag1', 'attn_volume_lag1', 'attn_absret_lag1', 'attn_spike_lag1']
if gt_success:
    attn_cols += [c for c in w_is.columns if c.startswith('gt_') and 'lag1' in c and 'raw' not in c]

incr_r2 = {}
print(f"\n{'Attention var':<25} {'Full R²':>10} {'Incr R²':>10} {'F-stat':>10} {'p-value':>10}")
print("-" * 70)

for col in attn_cols:
    if col not in w_is.columns:
        continue
    X_full = w_is[['vix_var_lag1', col]].copy()
    X_full.insert(0, 'const', 1.0)

    valid = X_full.notna().all(axis=1) & y_is.notna()
    if valid.sum() < 50:
        continue

    beta_full, _, _, _ = np.linalg.lstsq(X_full.values[valid], y_is.values[valid], rcond=None)
    resid_full = y_is.values[valid] - X_full.values[valid] @ beta_full
    ss_full = np.sum(resid_full**2)

    # Recompute baseline on same valid subset
    X_base_sub = w_is[['vix_var_lag1']].copy()
    X_base_sub.insert(0, 'const', 1.0)
    beta_base_sub, _, _, _ = np.linalg.lstsq(X_base_sub.values[valid], y_is.values[valid], rcond=None)
    resid_base_sub = y_is.values[valid] - X_base_sub.values[valid] @ beta_base_sub
    ss_base_sub = np.sum(resid_base_sub**2)
    ss_total_sub = np.sum((y_is.values[valid] - y_is.values[valid].mean())**2)

    r2_full = 1 - ss_full / ss_total_sub
    r2_base_v = 1 - ss_base_sub / ss_total_sub
    incr = r2_full - r2_base_v

    # F-test for incremental variable
    n = valid.sum()
    k_full = X_full.shape[1]
    k_base = X_base_sub.shape[1]
    f_stat = ((ss_base_sub - ss_full) / (k_full - k_base)) / (ss_full / (n - k_full))
    f_p = 1 - stats.f.cdf(f_stat, k_full - k_base, n - k_full)

    incr_r2[col] = {'r2_full': r2_full, 'incr_r2': incr, 'f_stat': f_stat, 'f_p': f_p}
    print(f"{col:<25} {r2_full:>10.4f} {incr:>10.4f} {f_stat:>10.2f} {f_p:>10.4f}")

# ============================================================
# 12. Regime-conditional analysis
# ============================================================
print("\n[11] Regime-conditional attention effect (IS)...")

# High vol regime: VIX > 20
high_vol = w_is['vix'] > 20
low_vol = ~high_vol

for regime, mask_r, label in [(high_vol, high_vol, 'High Vol (VIX>20)'),
                               (low_vol, low_vol, 'Low Vol (VIX<=20)')]:
    if mask_r.sum() < 30:
        continue

    y_r = w_is.loc[mask_r, 'rv']
    attn_r = w_is.loc[mask_r, 'attn_level_lag1']

    valid = y_r.notna() & attn_r.notna()
    if valid.sum() < 20:
        continue

    r_val, p_val = stats.pearsonr(attn_r[valid], y_r[valid])
    print(f"  {label}: corr(attn, rv) = {r_val:.4f} (p={p_val:.4f}), n={valid.sum()}")

# ============================================================
# 13. Granger causality test
# ============================================================
print("\n[12] Pseudo-Granger causality test (attention → vol, IS)...")

# Test: does lagged attention add info beyond lagged RV + lagged VIX?
y_gc = w_is['rv'].values
X_restricted = w_is[['rv_lag1', 'vix_var_lag1']].copy()
X_restricted.insert(0, 'const', 1.0)

valid_gc = np.all(np.isfinite(X_restricted.values), axis=1) & np.isfinite(y_gc)

beta_r, _, _, _ = np.linalg.lstsq(X_restricted.values[valid_gc], y_gc[valid_gc], rcond=None)
resid_r = y_gc[valid_gc] - X_restricted.values[valid_gc] @ beta_r
ss_r = np.sum(resid_r**2)

for attn_col in ['attn_level_lag1', 'attn_volume_lag1', 'attn_absret_lag1']:
    if attn_col not in w_is.columns:
        continue
    X_unrest = w_is[['rv_lag1', 'vix_var_lag1', attn_col]].copy()
    X_unrest.insert(0, 'const', 1.0)

    valid_u = valid_gc & np.isfinite(w_is[attn_col].values)
    if valid_u.sum() < 50:
        continue

    # Re-estimate restricted on same sample
    beta_r2, _, _, _ = np.linalg.lstsq(X_restricted.values[valid_u], y_gc[valid_u], rcond=None)
    resid_r2 = y_gc[valid_u] - X_restricted.values[valid_u] @ beta_r2
    ss_r2 = np.sum(resid_r2**2)

    beta_u, _, _, _ = np.linalg.lstsq(X_unrest.values[valid_u], y_gc[valid_u], rcond=None)
    resid_u = y_gc[valid_u] - X_unrest.values[valid_u] @ beta_u
    ss_u = np.sum(resid_u**2)

    n = valid_u.sum()
    q = 1  # one additional variable
    k = X_unrest.shape[1]
    f_gc = ((ss_r2 - ss_u) / q) / (ss_u / (n - k))
    f_gc_p = 1 - stats.f.cdf(f_gc, q, n - k)

    sig = "***" if f_gc_p < 0.01 else "**" if f_gc_p < 0.05 else "*" if f_gc_p < 0.10 else "NS"
    print(f"  {attn_col}: F={f_gc:.3f}, p={f_gc_p:.4f} {sig}")

# ============================================================
# 14. Summary and Results
# ============================================================
elapsed = time.time() - t0
print(f"\n{'='*70}")
print(f"SUMMARY (elapsed: {elapsed:.1f}s)")
print(f"{'='*70}")

# Determine best model
if results:
    best_key = min(results, key=lambda k: results[k]['qlike'])
    best = results[best_key]
    print(f"\nBest OOS model: {best['name']} (QLIKE={best['qlike']:.4f})")

    # Check if any attention model beats VIX+RV
    baseline_qlike = results.get('M3_VIX_RV', {}).get('qlike', np.inf)
    attention_models = {k: v for k, v in results.items()
                       if 'Attn' in k or 'Spike' in k or 'Vol' in k or 'AbsRet' in k
                       or 'RoC' in k or 'Kitchen' in k or 'GT' in k or 'Trends' in k}

    any_better = False
    for k, v in attention_models.items():
        if v['qlike'] < baseline_qlike:
            imp = (baseline_qlike - v['qlike']) / baseline_qlike * 100
            print(f"  {v['name']}: QLIKE improvement = {imp:.1f}%")
            if k in dm_results and dm_results[k]['dm_p'] < 0.10:
                print(f"    Statistically significant (DM p={dm_results[k]['dm_p']:.4f})")
                any_better = True
            else:
                p_val = dm_results.get(k, {}).get('dm_p', np.nan)
                print(f"    NOT statistically significant (DM p={p_val:.4f})")

    if not any_better:
        print("\n  CONCLUSION: No attention proxy provides statistically significant")
        print("  improvement over VIX + Lagged RV baseline in OOS period.")
        print("  Consistent with K192/J3: VIX is sufficient statistic for fear/attention.")

# ============================================================
# 15. Save results
# ============================================================
print("\n[13] Saving results...")

# Clean results for JSON
json_results = {}
for key, res in results.items():
    json_results[key] = {
        'name': res['name'],
        'qlike': float(res['qlike']),
        'mse': float(res['mse']),
        'corr': float(res['corr']),
        'n_valid': res['n_valid'],
    }

# Prepare output
output = {
    'experiment_id': 'K473',
    'title': 'Investor Attention (Google Trends) as Vol Signal — Revisit',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data': {
        'asset': ASSET,
        'source': 'yfinance (SPY, ^VIX)',
        'google_trends_available': gt_success,
        'frequency': 'weekly',
        'is_period': f'{w.index[is_mask][0].date()} to {w.index[is_mask][-1].date()}' if is_mask.any() else 'N/A',
        'oos_period': f'{w.index[oos_mask][0].date()} to {w.index[oos_mask][-1].date()}' if oos_mask.any() else 'N/A',
        'n_is': int(n_is),
        'n_oos': int(n_oos),
    },
    'descriptive_stats': {
        'is_rv_mean': float(w_is['rv'].mean()),
        'is_rv_std': float(w_is['rv'].std()),
        'is_attn_level_mean': float(w_is['attn_level'].mean()),
        'is_attn_spike_pct': float(w_is['attn_spike'].mean() * 100),
    },
    'oos_results': json_results,
    'dm_tests_vs_M3': {k: {'dm_stat': float(v['dm_stat']), 'dm_p': float(v['dm_p']),
                            'better': v['better']}
                       for k, v in dm_results.items()},
    'incremental_r2': {k: {kk: float(vv) for kk, vv in v.items()}
                       for k, v in incr_r2.items()},
    'regime_analysis': {},
    'granger_causality': {},
    'conclusion': {
        'main_finding': '',
        'attention_adds_value_oos': False,
        'best_model': '',
        'consistent_with_prior': True,
    },
    'references': [
        'Da, Engelberg, Gao (2011) "In Search of Attention" JoF',
        'Vlastakis & Markellos (2012) "Information demand and stock market volatility" JBES',
        'K192: Google Trends composite — IS r=0.576 but OOS failed',
        'J3: Google Trends "recession" partial r=0.634, VT overlay NS',
        'G14: "stock market crash" spike → crash momentum, not tradeable',
    ],
    'elapsed_seconds': round(elapsed, 1),
}

# Fill conclusion
if results:
    best_key = min(results, key=lambda k: results[k]['qlike'])
    baseline_key = 'M3_VIX_RV'

    # Only check attention models (not M1 or M2 which are non-attention baselines)
    attention_keys = {k for k in results if k not in ('M1_LaggedRV', 'M2_VIX', 'M3_VIX_RV')}
    any_sig_better = False
    for k, v in dm_results.items():
        if k in attention_keys and v['dm_p'] < 0.10 and v['dm_stat'] < 0:
            any_sig_better = True
            break

    output['conclusion']['attention_adds_value_oos'] = any_sig_better
    output['conclusion']['best_model'] = results[best_key]['name']

    if any_sig_better:
        output['conclusion']['main_finding'] = (
            f"Attention proxy improves vol forecast OOS. "
            f"Best model: {results[best_key]['name']} (QLIKE={results[best_key]['qlike']:.4f})"
        )
        output['conclusion']['consistent_with_prior'] = False
    else:
        output['conclusion']['main_finding'] = (
            "No attention proxy provides statistically significant OOS improvement "
            "over VIX + Lagged RV baseline. VIX remains sufficient statistic for "
            "attention/fear information. Consistent with K192/J3."
        )

# Save
results_path = 'experiments/k473_attention_vol_results.json'
with open(results_path, 'w') as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f"  Saved to {results_path}")
print(f"\nDone! Total time: {elapsed:.1f}s")
