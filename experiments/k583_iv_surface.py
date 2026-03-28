"""K583: Options Implied Volatility Surface Analysis
====================================================
[提出: User, 執行: Claude]

Research Question:
Does the SHAPE of the IV surface (beyond VIX level) — specifically curvature,
term structure slope, and CHANGES in surface shape — provide incremental
information for daily volatility prediction beyond HAR-ABS and HAR-VIX?

Motivation:
VIX is a single number from SPX options. The full IV surface (across strikes
and maturities) contains richer information:
- Slope across maturities = term structure (K542: null)
- Level (VIX) = K429, K530: VIX adds marginally to HAR
- CURVATURE (butterfly: VIX9D - 2*VIX + VIX3M) = UNTESTED in HAR framework
- CHANGES in surface shape (delta-slope, delta-curvature) = UNTESTED

Key difference from K429:
- K429 used Ridge regression on raw levels → null result
- K583 uses HAR-ABS rolling-window OLS framework (proven in K530)
- Focus on DYNAMICS (changes/momentum) not just levels
- Proper rolling-window OOS (w=500), not fixed IS/OOS split

Data: yfinance ^VIX, ^VIX3M, ^VIX9D, SPY
IS window: 500 days rolling
OOS: 2023-2024
Evaluation: QLIKE + DM test pairwise

References:
- Corsi (2009, JFE): HAR-RV model
- K530: HAR-ABS framework (baseline, DM=-7.04 vs GJR)
- K429: VIX term structure slope (null with Ridge)
- K535: VIX skew (null)
- K542: VIX term structure (null)

Usage:
    uv run python experiments/k583_iv_surface.py
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))


# ============================================================
#  Utility functions
# ============================================================

def print_section(title: str, char: str = "=", width: int = 72):
    print(f"\n{char * width}")
    print(f"  {title}")
    print(f"{char * width}")


def qlike_loss(realized: np.ndarray, forecast: np.ndarray) -> float:
    """QLIKE loss: mean(realized/forecast - log(realized/forecast) - 1).
    Both inputs should be VARIANCE proxies (positive).
    Clip forecast to [1e-8, 1e3*median(realized)] to avoid blow-up."""
    mask = (realized > 1e-15) & (forecast > 1e-15)
    r, f = realized[mask], forecast[mask]
    # Robust clipping: forecast within [0.01*median, 100*median] of realized
    med_r = np.median(r)
    f = np.clip(f, med_r * 0.01, med_r * 100)
    ratio = r / f
    return float(np.mean(ratio - np.log(ratio) - 1))


def qlike_loss_array(realized: np.ndarray, forecast: np.ndarray) -> np.ndarray:
    """Element-wise QLIKE loss with robust clipping."""
    med_r = np.median(realized[realized > 1e-15])
    f_clipped = np.clip(forecast, med_r * 0.01, med_r * 100)
    ratio = realized / f_clipped
    out = ratio - np.log(ratio) - 1
    out[~np.isfinite(out)] = np.nan
    return out


def dm_test(loss1: np.ndarray, loss2: np.ndarray, h: int = 1) -> tuple:
    """Diebold-Mariano test (two-sided).
    loss1 - loss2 < 0 means model 1 is better.
    Returns (DM statistic, p-value).
    """
    d = loss1 - loss2
    mask = np.isfinite(d)
    d = d[mask]
    T = len(d)
    if T < 30:
        return (np.nan, np.nan)
    d_bar = np.mean(d)
    gamma_0 = np.var(d, ddof=0)
    gamma_sum = 0.0
    for k in range(1, h):
        if k < T:
            gamma_k = np.cov(d[k:], d[:-k], ddof=0)[0, 1]
            gamma_sum += 2 * gamma_k
    var_d = (gamma_0 + gamma_sum) / T
    if var_d <= 0:
        return (0.0, 1.0)
    dm_stat = d_bar / np.sqrt(var_d)
    p_value = 2 * (1 - stats.t.cdf(abs(dm_stat), df=T - 1))
    return (float(dm_stat), float(p_value))


def ols_fit(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    """OLS with intercept. Returns coefficients [intercept, beta1, ...]."""
    n = len(y)
    X_aug = np.column_stack([np.ones(n), X])
    try:
        beta = np.linalg.lstsq(X_aug, y, rcond=None)[0]
    except np.linalg.LinAlgError:
        beta = np.zeros(X_aug.shape[1])
    return beta


def ols_predict(x_new: np.ndarray, beta: np.ndarray) -> float:
    """Predict with OLS coefficients."""
    x_aug = np.concatenate([[1.0], x_new])
    pred = np.dot(x_aug, beta)
    return max(pred, 1e-10)  # floor to positive


# ============================================================
#  1. Data Download
# ============================================================
print_section("K583: Options IV Surface Analysis")
t0 = time.time()

tickers = {
    'SPY': 'SPY',
    'VIX': '^VIX',
    'VIX3M': '^VIX3M',
    'VIX9D': '^VIX9D',
}

raw_data = {}
for name, ticker in tickers.items():
    try:
        df_dl = yf.download(ticker, start='2010-01-01', end='2026-01-01', progress=False)
        if isinstance(df_dl.columns, pd.MultiIndex):
            df_dl.columns = df_dl.columns.get_level_values(0)
        raw_data[name] = df_dl['Close'].dropna()
        print(f"  {name}: {len(raw_data[name])} obs, "
              f"{raw_data[name].index[0].date()} ~ {raw_data[name].index[-1].date()}")
    except Exception as e:
        print(f"  {name}: FAILED - {e}")

has_vix9d = 'VIX9D' in raw_data and len(raw_data['VIX9D']) > 500
print(f"\nVIX9D available: {has_vix9d}")

# Merge
df = pd.DataFrame({
    'spy_close': raw_data['SPY'],
    'vix': raw_data['VIX'],
    'vix3m': raw_data['VIX3M'],
})
if has_vix9d:
    df['vix9d'] = raw_data['VIX9D']

df = df.dropna()
print(f"Merged data: {len(df)} obs, {df.index[0].date()} ~ {df.index[-1].date()}")


# ============================================================
#  2. Feature Engineering
# ============================================================
print_section("Feature Engineering")

# Returns
df['log_return'] = np.log(df['spy_close'] / df['spy_close'].shift(1))
df['abs_ret'] = df['log_return'].abs()
df['sq_ret'] = df['log_return'] ** 2

# HAR-ABS features (Corsi 2009)
df['rv1_abs'] = df['abs_ret']
df['rv5_abs'] = df['abs_ret'].rolling(5).mean()
df['rv22_abs'] = df['abs_ret'].rolling(22).mean()

# Target: next-day squared return (variance proxy)
df['target_sq'] = df['sq_ret'].shift(-1)

# VIX daily scale for HAR-VIX
df['vix_daily'] = df['vix'] / 100.0 / np.sqrt(252)

# ----- IV Surface Features -----

# (A) Term structure LEVEL (slope)
df['ts_slope'] = df['vix3m'] - df['vix']  # positive = contango
df['ts_ratio'] = df['vix'] / df['vix3m']  # >1 = backwardation

# (B) Term structure CURVATURE (butterfly)
if has_vix9d:
    df['ts_curvature'] = df['vix9d'] - 2 * df['vix'] + df['vix3m']
    df['ts_curvature_norm'] = df['ts_curvature'] / df['vix']
else:
    # Proxy: use 5-day realized vol as short-end proxy
    df['rv5_ann'] = df['log_return'].rolling(5).std() * np.sqrt(252) * 100
    df['ts_curvature'] = df['rv5_ann'] - 2 * df['vix'] + df['vix3m']
    df['ts_curvature_norm'] = df['ts_curvature'] / df['vix']
    print("  Note: VIX9D not available, using 5d realized vol proxy for curvature")

# (C) CHANGES in surface shape (dynamics/momentum) — KEY DIFFERENTIATOR from K429
df['d_vix'] = df['vix'].diff()                    # 1-day VIX change
df['d_vix3m'] = df['vix3m'].diff()                # 1-day VIX3M change
df['d_slope'] = df['ts_slope'].diff()             # 1-day slope change
df['d_slope_5d'] = df['ts_slope'].diff(5)         # 5-day slope change
df['d_curvature'] = df['ts_curvature'].diff()     # 1-day curvature change
df['d_curvature_5d'] = df['ts_curvature'].diff(5) # 5-day curvature change

# (D) Surface momentum ratios
# How much does VIX move relative to VIX3M? (short-end amplification)
df['vix_vix3m_chg_ratio'] = df['d_vix'] / (df['d_vix3m'].replace(0, np.nan))
df['vix_vix3m_chg_ratio'] = df['vix_vix3m_chg_ratio'].clip(-10, 10)

# Normalized slope for HAR integration
df['ts_slope_norm'] = df['ts_slope'] / df['vix']

# Slope z-score (mean-reversion signal)
df['slope_zscore'] = ((df['ts_slope'] - df['ts_slope'].rolling(63).mean())
                      / df['ts_slope'].rolling(63).std())

# Convert IV surface features to daily variance scale for HAR models
df['ts_slope_daily'] = df['ts_slope'] / 100.0 / np.sqrt(252)
df['ts_curvature_daily'] = df['ts_curvature'] / 100.0 / np.sqrt(252)
df['d_slope_daily'] = df['d_slope'] / 100.0 / np.sqrt(252)
df['d_slope_5d_daily'] = df['d_slope_5d'] / 100.0 / np.sqrt(252)
df['d_curvature_daily'] = df['d_curvature'] / 100.0 / np.sqrt(252)

# Drop initial NaN
df = df.dropna(subset=['rv22_abs', 'target_sq', 'ts_curvature', 'd_slope_5d',
                         'd_curvature_5d', 'slope_zscore'])
print(f"Clean data: {len(df)} obs, {df.index[0].date()} ~ {df.index[-1].date()}")

# ============================================================
#  3. Descriptive Statistics
# ============================================================
print_section("Descriptive Statistics (Full Sample)")

desc_features = ['vix', 'vix3m', 'ts_slope', 'ts_ratio', 'ts_curvature',
                  'd_slope', 'd_slope_5d', 'd_curvature', 'slope_zscore']
if has_vix9d:
    desc_features.insert(2, 'vix9d')

desc_stats = {}
for col in desc_features:
    s = df[col].dropna()
    desc_stats[col] = {
        'mean': float(s.mean()), 'std': float(s.std()),
        'skew': float(s.skew()), 'kurt': float(s.kurtosis()),
        'min': float(s.min()), 'q25': float(s.quantile(0.25)),
        'median': float(s.median()), 'q75': float(s.quantile(0.75)),
        'max': float(s.max()),
    }
    print(f"  {col:20s}: mean={s.mean():8.4f}  std={s.std():8.4f}  "
          f"skew={s.skew():6.2f}  kurt={s.kurtosis():6.2f}")

# Correlations with next-day abs return
print("\n  Correlation with next-day |return|:")
corr_target = {}
next_abs = df['abs_ret'].shift(-1)
for col in desc_features + ['rv1_abs', 'rv5_abs', 'rv22_abs']:
    valid = df[col].notna() & next_abs.notna()
    r, p = stats.pearsonr(df.loc[valid, col].values, next_abs[valid].values)
    corr_target[col] = {'r': float(r), 'p': float(p)}
    sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else ""
    print(f"    {col:20s}: r={r:+.4f} (p={p:.4f}) {sig}")


# ============================================================
#  4. Define HAR Models
# ============================================================
print_section("Model Definitions")

# Each model returns feature names and a function to extract features
MODEL_DEFS = {
    'HAR-ABS': {
        'desc': 'Baseline: rv1, rv5, rv22',
        'cols': ['rv1_abs', 'rv5_abs', 'rv22_abs'],
    },
    'HAR-VIX': {
        'desc': 'HAR-ABS + VIX (standard augmentation)',
        'cols': ['rv1_abs', 'rv5_abs', 'rv22_abs', 'vix_daily'],
    },
    'HAR-Slope': {
        'desc': 'HAR-ABS + term structure slope',
        'cols': ['rv1_abs', 'rv5_abs', 'rv22_abs', 'ts_slope_daily'],
    },
    'HAR-Curvature': {
        'desc': 'HAR-ABS + term structure curvature (butterfly)',
        'cols': ['rv1_abs', 'rv5_abs', 'rv22_abs', 'ts_curvature_daily'],
    },
    'HAR-dSlope': {
        'desc': 'HAR-ABS + change in slope (1d)',
        'cols': ['rv1_abs', 'rv5_abs', 'rv22_abs', 'd_slope_daily'],
    },
    'HAR-dSlope5d': {
        'desc': 'HAR-ABS + change in slope (5d)',
        'cols': ['rv1_abs', 'rv5_abs', 'rv22_abs', 'd_slope_5d_daily'],
    },
    'HAR-dCurvature': {
        'desc': 'HAR-ABS + change in curvature (1d)',
        'cols': ['rv1_abs', 'rv5_abs', 'rv22_abs', 'd_curvature_daily'],
    },
    'HAR-Surface': {
        'desc': 'HAR-ABS + slope + curvature + VIX (full surface info)',
        'cols': ['rv1_abs', 'rv5_abs', 'rv22_abs', 'vix_daily',
                 'ts_slope_daily', 'ts_curvature_daily'],
    },
    'HAR-SurfDyn': {
        'desc': 'HAR-ABS + surface dynamics (changes in slope + curvature)',
        'cols': ['rv1_abs', 'rv5_abs', 'rv22_abs',
                 'd_slope_daily', 'd_curvature_daily'],
    },
    'HAR-Full': {
        'desc': 'Kitchen sink: HAR-ABS + VIX + all surface features',
        'cols': ['rv1_abs', 'rv5_abs', 'rv22_abs', 'vix_daily',
                 'ts_slope_daily', 'ts_curvature_daily',
                 'd_slope_daily', 'd_slope_5d_daily', 'd_curvature_daily'],
    },
}

for name, mdef in MODEL_DEFS.items():
    print(f"  {name:20s}: {mdef['desc']}")
print(f"\n  Total models: {len(MODEL_DEFS)}")


# ============================================================
#  5. Rolling-Window OOS Evaluation
# ============================================================
print_section("Rolling-Window OOS Evaluation")

WINDOW = 500
OOS_START = '2023-01-01'
OOS_END = '2024-12-31'

oos_mask = (df.index >= OOS_START) & (df.index <= OOS_END)
oos_indices = df.index[oos_mask]
n_oos = len(oos_indices)
print(f"OOS period: {OOS_START} to {OOS_END}")
print(f"OOS observations: {n_oos}")
print(f"Rolling window: {WINDOW} days")

# Preallocate forecast arrays
forecasts = {name: np.full(n_oos, np.nan) for name in MODEL_DEFS}
realized = np.full(n_oos, np.nan)

# Get integer positions for speed
all_idx = df.index.tolist()
oos_positions = [all_idx.index(idx) for idx in oos_indices]

t_start = time.time()
for i, (oos_idx, oos_pos) in enumerate(zip(oos_indices, oos_positions)):
    # Training window: [oos_pos - WINDOW, oos_pos - 1]
    train_start = oos_pos - WINDOW
    if train_start < 0:
        continue

    # Realized variance (next-day squared return)
    realized[i] = df.iloc[oos_pos]['target_sq']

    for model_name, mdef in MODEL_DEFS.items():
        cols = mdef['cols']

        # Training data
        X_train = df.iloc[train_start:oos_pos][cols].values
        y_train = df.iloc[train_start:oos_pos]['target_sq'].values

        # Check for NaN
        valid = np.all(np.isfinite(X_train), axis=1) & np.isfinite(y_train)
        if valid.sum() < 50:
            continue

        X_tr = X_train[valid]
        y_tr = y_train[valid]

        # Fit OLS
        beta = ols_fit(X_tr, y_tr)

        # Predict at oos_pos
        x_new = df.iloc[oos_pos][cols].values
        if np.all(np.isfinite(x_new)):
            forecasts[model_name][i] = ols_predict(x_new, beta)

    if (i + 1) % 100 == 0:
        elapsed = time.time() - t_start
        print(f"  {i+1}/{n_oos} done ({elapsed:.1f}s)")

elapsed = time.time() - t_start
print(f"  Rolling evaluation complete: {elapsed:.1f}s")

# Diagnostic: forecast distribution
print("\n  Forecast diagnostics (median, %negative, %clipped):")
for name in MODEL_DEFS:
    f_arr = forecasts[name]
    valid = np.isfinite(f_arr)
    if valid.sum() == 0:
        continue
    f_v = f_arr[valid]
    pct_neg = (f_v < 0).mean() * 100
    med_f = np.median(f_v)
    med_r = np.median(realized[np.isfinite(realized) & (realized > 0)])
    print(f"    {name:20s}: median_f={med_f:.8f}, median_r={med_r:.8f}, "
          f"neg={pct_neg:.1f}%, ratio={med_f/med_r:.3f}")


# ============================================================
#  6. Compute Metrics
# ============================================================
print_section("Results: QLIKE + DM Tests")

# Compute QLIKE for each model
model_metrics = {}
model_losses = {}

for name in MODEL_DEFS:
    f_arr = forecasts[name]
    valid = np.isfinite(f_arr) & np.isfinite(realized) & (f_arr > 1e-15) & (realized > 1e-15)
    n_valid = valid.sum()

    if n_valid < 50:
        print(f"  {name:20s}: insufficient valid forecasts ({n_valid})")
        continue

    r_v = realized[valid]
    f_v = f_arr[valid]

    ql = qlike_loss(r_v, f_v)
    mse = float(np.mean((r_v - f_v) ** 2))
    corr = float(np.corrcoef(r_v, f_v)[0, 1])
    r2 = 1 - np.sum((r_v - f_v)**2) / np.sum((r_v - np.mean(r_v))**2)

    model_metrics[name] = {
        'qlike': ql,
        'mse': mse,
        'correlation': corr,
        'r2_oos': float(r2),
        'n_valid': int(n_valid),
    }

    # Store loss arrays for DM test
    model_losses[name] = qlike_loss_array(r_v, f_v)

    print(f"  {name:20s}: QLIKE={ql:.6f}  MSE={mse:.10f}  Corr={corr:.4f}  R2={r2:.4f}  n={n_valid}")


# DM tests
print("\n  DM Tests (negative t = row model better):")
baselines = ['HAR-ABS', 'HAR-VIX']

dm_results = {}
for base in baselines:
    if base not in model_losses:
        continue
    print(f"\n  --- vs {base} ---")
    for name in MODEL_DEFS:
        if name == base or name not in model_losses:
            continue

        # Align losses (same valid set)
        f1 = forecasts[name]
        f2 = forecasts[base]
        valid = (np.isfinite(f1) & np.isfinite(f2) &
                 np.isfinite(realized) & (f1 > 1e-15) & (f2 > 1e-15) & (realized > 1e-15))

        if valid.sum() < 50:
            continue

        l1 = qlike_loss_array(realized[valid], f1[valid])
        l2 = qlike_loss_array(realized[valid], f2[valid])

        t_stat, p_val = dm_test(l1, l2, h=1)
        sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.10 else ""
        print(f"    {name:20s}: DM t={t_stat:+.3f}, p={p_val:.4f} {sig}")

        key = f"{name}_vs_{base}"
        dm_results[key] = {'t': float(t_stat), 'p': float(p_val)}


# ============================================================
#  7. Coefficient Analysis (Full-sample OLS for interpretation)
# ============================================================
print_section("Coefficient Analysis (Full IS fit for interpretation)")

coef_analysis = {}
is_mask_coef = df.index < OOS_START

for name, mdef in MODEL_DEFS.items():
    cols = mdef['cols']
    X_is = df.loc[is_mask_coef, cols].values
    y_is = df.loc[is_mask_coef, 'target_sq'].values
    valid = np.all(np.isfinite(X_is), axis=1) & np.isfinite(y_is)

    if valid.sum() < 100:
        continue

    beta = ols_fit(X_is[valid], y_is[valid])

    # t-statistics (OLS standard errors)
    n_fit = valid.sum()
    X_aug = np.column_stack([np.ones(n_fit), X_is[valid]])
    y_fit = y_is[valid]
    resid = y_fit - X_aug @ beta
    sigma2 = np.sum(resid**2) / (n_fit - len(beta))
    try:
        cov_beta = sigma2 * np.linalg.inv(X_aug.T @ X_aug)
        se_beta = np.sqrt(np.diag(cov_beta))
        t_stats = beta / se_beta
    except np.linalg.LinAlgError:
        t_stats = np.full_like(beta, np.nan)

    col_names = ['intercept'] + cols
    coefs = {}
    for j, cname in enumerate(col_names):
        coefs[cname] = {
            'coef': float(beta[j]),
            't_stat': float(t_stats[j]) if np.isfinite(t_stats[j]) else None,
            'significant': bool(abs(t_stats[j]) > 1.96) if np.isfinite(t_stats[j]) else False,
        }

    coef_analysis[name] = coefs

    # Print augmentation variables only (skip HAR base)
    aug_vars = [c for c in cols if c not in ['rv1_abs', 'rv5_abs', 'rv22_abs']]
    if aug_vars:
        aug_str = "  ".join([f"{c}: β={coefs[c]['coef']:.6f} (t={coefs[c]['t_stat']:.2f})"
                              for c in aug_vars if c in coefs])
        print(f"  {name:20s}: {aug_str}")


# ============================================================
#  8. Regime-Conditional Analysis
# ============================================================
print_section("Regime-Conditional QLIKE (OOS)")

oos_vix = df.loc[oos_mask, 'vix'].values[:n_oos]
oos_slope = df.loc[oos_mask, 'ts_slope'].values[:n_oos]

regimes = {
    'Low VIX (<15)':    oos_vix < 15,
    'Mid VIX (15-20)':  (oos_vix >= 15) & (oos_vix < 20),
    'High VIX (20+)':   oos_vix >= 20,
    'Contango (slope>2)': oos_slope > 2,
    'Flat (|slope|<2)':   np.abs(oos_slope) <= 2,
    'Backwardation (slope<-2)': oos_slope < -2,
}

regime_results = {}
for regime_name, rmask in regimes.items():
    n_reg = int(rmask.sum())
    if n_reg < 20:
        print(f"  {regime_name:30s}: {n_reg} obs (too few)")
        continue

    reg_metrics = {}
    for name in ['HAR-ABS', 'HAR-VIX', 'HAR-Slope', 'HAR-Curvature',
                  'HAR-dSlope', 'HAR-SurfDyn', 'HAR-Full']:
        f_arr = forecasts.get(name)
        if f_arr is None:
            continue
        valid = rmask & np.isfinite(f_arr) & np.isfinite(realized) & (f_arr > 1e-15) & (realized > 1e-15)
        if valid.sum() < 10:
            continue
        ql = qlike_loss(realized[valid], f_arr[valid])
        reg_metrics[name] = float(ql)

    regime_results[regime_name] = {'n': n_reg, 'qlike': reg_metrics}

    metrics_str = "  ".join([f"{k}={v:.5f}" for k, v in reg_metrics.items()])
    print(f"  {regime_name:30s}: n={n_reg:4d} | {metrics_str}")


# ============================================================
#  9. Annual Stability
# ============================================================
print_section("Annual OOS Stability")

annual_results = {}
for year in [2023, 2024]:
    year_mask = (df.index >= f'{year}-01-01') & (df.index <= f'{year}-12-31')
    # Map to OOS array indices
    year_oos_mask = np.array([(idx.year == year) for idx in oos_indices])

    n_yr = int(year_oos_mask.sum())
    if n_yr < 50:
        continue

    yr_metrics = {}
    for name in MODEL_DEFS:
        f_arr = forecasts[name]
        valid = year_oos_mask & np.isfinite(f_arr) & np.isfinite(realized) & (f_arr > 1e-15) & (realized > 1e-15)
        if valid.sum() < 30:
            continue
        ql = qlike_loss(realized[valid], f_arr[valid])
        yr_metrics[name] = float(ql)

    annual_results[str(year)] = {'n': n_yr, 'qlike': yr_metrics}

    metrics_str = "  ".join([f"{k}={v:.5f}" for k, v in yr_metrics.items()])
    print(f"  {year}: n={n_yr} | {metrics_str}")


# ============================================================
#  10. VT Strategy Signal Test
# ============================================================
print_section("VT Strategy Signal Test")

# Test: does curvature or slope change improve a simple VT strategy?
# Strategy: 12/VIX baseline, then test overlay with surface signals

spy_ret = df.loc[oos_mask, 'log_return'].values[:n_oos]
oos_vix_arr = df.loc[oos_mask, 'vix'].values[:n_oos]
oos_d_slope = df.loc[oos_mask, 'd_slope'].values[:n_oos]
oos_d_curv = df.loc[oos_mask, 'd_curvature'].values[:n_oos]
oos_slope_z = df.loc[oos_mask, 'slope_zscore'].values[:n_oos]

# Baseline: 12/VIX
w_base = np.clip(12.0 / oos_vix_arr, 0, 1.5)

# Strategy 1: Reduce exposure when slope is rapidly changing (surface instability)
# When |d_slope_5d| is high, the surface is moving → more uncertainty
oos_d_slope_5d = df.loc[oos_mask, 'd_slope_5d'].values[:n_oos]
d_slope_75 = np.nanpercentile(np.abs(oos_d_slope_5d), 75)
w_surf_stab = w_base.copy()
surface_unstable = np.abs(oos_d_slope_5d) > d_slope_75
w_surf_stab[surface_unstable] *= 0.7  # reduce by 30% when surface unstable

# Strategy 2: Curvature signal
# High curvature → unusual surface shape → uncertainty
oos_curv = df.loc[oos_mask, 'ts_curvature'].values[:n_oos]
curv_90 = np.nanpercentile(np.abs(oos_curv), 90)
w_curv = w_base.copy()
extreme_curv = np.abs(oos_curv) > curv_90
w_curv[extreme_curv] *= 0.5  # reduce by 50% when extreme curvature

# Strategy 3: Slope z-score mean-reversion
# When slope is very high (contango extreme), VIX might spike
slope_z_low = oos_slope_z < -1.5
slope_z_high = oos_slope_z > 1.5
w_slope_z = w_base.copy()
w_slope_z[slope_z_low] *= 0.7   # reduce when slope unusually low (stress likely)
w_slope_z[slope_z_high] *= 1.1  # slightly boost when contango extreme (complacency?)

def compute_vt_stats(weights, returns):
    """Compute VT strategy stats."""
    valid = np.isfinite(weights) & np.isfinite(returns)
    w = weights[valid]
    r = returns[valid]
    strat_ret = w * r
    ann_ret = np.mean(strat_ret) * 252
    ann_vol = np.std(strat_ret) * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cum = np.cumsum(strat_ret)
    mdd = float(np.max(np.maximum.accumulate(cum) - cum))
    return {
        'ann_return': float(ann_ret),
        'ann_vol': float(ann_vol),
        'sharpe': float(sharpe),
        'max_dd': mdd,
        'avg_weight': float(np.mean(w)),
        'n': int(valid.sum()),
    }

vt_results = {}
strategies = {
    '12/VIX (baseline)': w_base,
    'Surface Stability': w_surf_stab,
    'Curvature Filter': w_curv,
    'Slope Z-Score': w_slope_z,
}

for sname, weights in strategies.items():
    stats_dict = compute_vt_stats(weights, spy_ret)
    vt_results[sname] = stats_dict
    print(f"  {sname:25s}: Sharpe={stats_dict['sharpe']:.3f}  "
          f"Ret={stats_dict['ann_return']*100:.1f}%  Vol={stats_dict['ann_vol']*100:.1f}%  "
          f"MDD={stats_dict['max_dd']*100:.1f}%  AvgW={stats_dict['avg_weight']:.3f}")

# DM test for VT strategies (squared return difference)
print("\n  VT DM tests vs baseline:")
base_strat_ret = w_base * spy_ret
for sname, weights in strategies.items():
    if sname == '12/VIX (baseline)':
        continue
    strat_ret_alt = weights * spy_ret
    valid = np.isfinite(base_strat_ret) & np.isfinite(strat_ret_alt)
    # Use negative squared return as "loss" (we want high returns)
    l_base = -base_strat_ret[valid]**2
    l_alt = -strat_ret_alt[valid]**2
    # Actually, compare utility: higher is better
    # Simple: compare cumulative return difference
    diff = strat_ret_alt[valid] - base_strat_ret[valid]
    t_stat_vt = float(np.mean(diff) / (np.std(diff) / np.sqrt(len(diff)))) if np.std(diff) > 0 else 0
    p_val_vt = float(2 * (1 - stats.t.cdf(abs(t_stat_vt), df=len(diff)-1)))
    sig = "***" if p_val_vt < 0.01 else "**" if p_val_vt < 0.05 else "*" if p_val_vt < 0.10 else ""
    print(f"    {sname:25s}: t={t_stat_vt:+.3f}, p={p_val_vt:.4f} {sig}")
    vt_results[sname]['dm_vs_baseline_t'] = t_stat_vt
    vt_results[sname]['dm_vs_baseline_p'] = p_val_vt


# ============================================================
#  11. Summary & Conclusions
# ============================================================
print_section("SUMMARY & CONCLUSIONS")

# Determine main finding
har_abs_ql = model_metrics.get('HAR-ABS', {}).get('qlike', float('inf'))
har_abs_mse = model_metrics.get('HAR-ABS', {}).get('mse', float('inf'))
har_vix_ql = model_metrics.get('HAR-VIX', {}).get('qlike', float('inf'))
har_vix_mse = model_metrics.get('HAR-VIX', {}).get('mse', float('inf'))

# Check if any surface model SIGNIFICANTLY beats HAR-ABS
surface_models = ['HAR-Slope', 'HAR-Curvature', 'HAR-dSlope', 'HAR-dSlope5d',
                   'HAR-dCurvature', 'HAR-Surface', 'HAR-SurfDyn', 'HAR-Full']
best_surface = None
best_surface_ql = float('inf')
best_surface_mse = float('inf')
for name in surface_models:
    ql = model_metrics.get(name, {}).get('qlike', float('inf'))
    ms = model_metrics.get(name, {}).get('mse', float('inf'))
    if ql < best_surface_ql:
        best_surface_ql = ql
        best_surface = name
        best_surface_mse = ms

# Check DM significance vs HAR-ABS specifically (the fair baseline)
any_sig_vs_abs = False
for name in surface_models:
    key = f"{name}_vs_HAR-ABS"
    if key in dm_results and dm_results[key]['p'] < 0.05 and dm_results[key]['t'] < 0:
        any_sig_vs_abs = True
        break

# Check best MSE model
all_mse = {name: model_metrics[name]['mse'] for name in model_metrics}
best_mse_model = min(all_mse, key=all_mse.get)

# Conclusions
conclusions = {
    'har_abs_qlike': har_abs_ql,
    'har_abs_mse': har_abs_mse,
    'har_vix_qlike': har_vix_ql,
    'har_vix_mse': har_vix_mse,
    'best_surface_model_qlike': best_surface,
    'best_surface_qlike': best_surface_ql,
    'best_surface_mse': best_surface_mse,
    'best_mse_model': best_mse_model,
    'best_mse': all_mse[best_mse_model],
    'any_surface_significant_vs_har_abs': any_sig_vs_abs,
    'best_vt_strategy': max(vt_results.items(), key=lambda x: x[1]['sharpe'])[0],
    'best_vt_sharpe': max(vt_results.items(), key=lambda x: x[1]['sharpe'])[1]['sharpe'],
    'baseline_vt_sharpe': vt_results.get('12/VIX (baseline)', {}).get('sharpe', None),
}

# DM test for best surface vs HAR-ABS
dm_key = f"{best_surface}_vs_HAR-ABS"
dm_p = dm_results.get(dm_key, {}).get('p', 1.0)
dm_t = dm_results.get(dm_key, {}).get('t', 0)

if any_sig_vs_abs:
    verdict = (f"IV surface features SIGNIFICANTLY improve vol prediction: {best_surface} "
               f"(QLIKE={best_surface_ql:.4f}) beats HAR-ABS ({har_abs_ql:.4f}), "
               f"DM t={dm_t:.3f}, p={dm_p:.4f}")
elif best_surface_ql < har_abs_ql:
    verdict = (f"NULL RESULT. IV surface features show marginal QLIKE improvement but NOT significant: "
               f"best={best_surface} QLIKE={best_surface_ql:.4f} vs HAR-ABS {har_abs_ql:.4f}, "
               f"DM t={dm_t:.3f}, p={dm_p:.4f}. "
               f"No surface model significantly beats HAR-ABS. "
               f"Best MSE model: {best_mse_model} ({all_mse[best_mse_model]:.10f}). "
               f"Consistent with VIX sufficiency (K129, K429).")
else:
    verdict = (f"NULL RESULT. IV surface features provide NO incremental value. "
               f"HAR-ABS QLIKE={har_abs_ql:.4f}, best surface={best_surface_ql:.4f}. "
               f"Consistent with VIX sufficiency (K129, K429, 25+ confirmations).")

conclusions['verdict'] = verdict
print(f"\n{verdict}\n")

# VT verdict
base_sharpe = vt_results.get('12/VIX (baseline)', {}).get('sharpe', 0)
best_overlay = max([(k, v) for k, v in vt_results.items() if k != '12/VIX (baseline)'],
                    key=lambda x: x[1]['sharpe'])
sharpe_diff = best_overlay[1]['sharpe'] - base_sharpe
vt_verdict = (f"VT strategy: best overlay = {best_overlay[0]} "
              f"(Sharpe {best_overlay[1]['sharpe']:.3f} vs baseline {base_sharpe:.3f}, "
              f"delta={sharpe_diff:+.3f})")
conclusions['vt_verdict'] = vt_verdict
print(vt_verdict)


# ============================================================
#  12. Save Results
# ============================================================
print_section("Saving Results")

final_results = {
    'experiment_id': 'K583',
    'title': 'IV Surface Analysis: Curvature, Dynamics, and HAR Integration',
    'hypothesis': ('IV surface shape (curvature, slope changes, surface dynamics) '
                   'provides incremental information beyond VIX level for daily vol prediction'),
    'proposer': 'User',
    'executor': 'Claude',
    'data_source': 'yfinance (^VIX, ^VIX3M, ^VIX9D, SPY)',
    'data_period': f"{df.index[0].date()} ~ {df.index[-1].date()}",
    'oos_period': f"{OOS_START} ~ {OOS_END}",
    'rolling_window': WINDOW,
    'n_total': int(len(df)),
    'n_oos': n_oos,
    'vix9d_available': has_vix9d,
    'method': 'HAR-type OLS with rolling window (Corsi 2009 framework)',
    'references': [
        'Corsi (2009, JFE): HAR-RV model',
        'K429: VIX term structure slope (null, Ridge framework)',
        'K530: HAR-ABS multi-scale framework',
        'K535: VIX skew (null)',
        'K542: VIX term structure (null)',
        'K129: VIX sufficient statistic boundary map',
    ],
    'descriptive_statistics': desc_stats,
    'correlations_with_target': corr_target,
    'model_metrics': model_metrics,
    'dm_tests': dm_results,
    'coefficient_analysis': coef_analysis,
    'regime_conditional': regime_results,
    'annual_stability': annual_results,
    'vt_strategy_results': vt_results,
    'conclusions': conclusions,
    'runtime_seconds': round(time.time() - t0, 1),
    'timestamp': datetime.now(timezone.utc).isoformat(),
}

output_path = Path(__file__).parent / 'k583_iv_surface_results.json'
with open(output_path, 'w') as f:
    json.dump(final_results, f, indent=2, default=str)

print(f"Results saved to {output_path}")
print(f"Total runtime: {time.time() - t0:.1f}s")
print("\nDone.")
