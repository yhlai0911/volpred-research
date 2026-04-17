#!/usr/bin/env python3
"""
K470: HAR Log-Range Based Volatility Targeting Strategy
========================================================

Research question: Can HAR log-range's superior volatility forecasting
(K465/K469: best forecaster 8/10 cross-OOS) translate into better VT
strategy performance vs standard 12/VIX?

Background:
- K465/K469: HAR log-range is robustly the best vol forecaster
- K440: VRP prediction ≠ trading (VRP-VT hurts Sharpe)
- K467: HAR VaR fails (best forecaster ≠ best VaR)
- Lesson: prediction accuracy ≠ application value

Strategies:
1. Buy & Hold SPY
2. Buy & Hold 50/50 SPY+GLD
3. Standard 12/VIX VT (baseline)
4. HAR-based VT: w = target / σ_HAR
5. Hybrid 50/50: σ = 0.5*VIX + 0.5*σ_HAR
6. VIX-HAR blend: σ = VIX × (σ_HAR / σ_HAR_21d_MA)

Evaluation periods:
- IS: 2006-2022
- OOS: 2023-2025
- Long-term: 2008-2025

Literature:
- Corsi (2009) J Financial Econometrics — HAR-RV model
- Alizadeh, Brandt & Diebold (2002) JFE — Range-based vol estimation
- Moreira & Muir (2017) JoF — Volatility-Managed Portfolios
- K440, K465, K467, K469 results

Data: yfinance (SPY, GLD, ^VIX)
Author: [Proposed: User, Executed: Claude]
"""

import json
import warnings
import time
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from scipy import stats
from statsmodels.tsa.stattools import adfuller
from statsmodels.stats.diagnostic import acorr_ljungbox

warnings.filterwarnings('ignore')

print("=" * 70)
print("K470: HAR Log-Range Based Volatility Targeting Strategy")
print("  Q: Can HAR's vol forecasting edge translate to VT improvement?")
print("=" * 70)

t_start = time.time()

# =============================================================================
# 1. DATA COLLECTION
# =============================================================================
print("\n[1/8] Downloading data from yfinance...")
spy = yf.download('SPY', start='2005-01-01', progress=False)
gld = yf.download('GLD', start='2005-01-01', progress=False)
vix = yf.download('^VIX', start='2005-01-01', progress=False)

for df_name, df in [('SPY', spy), ('GLD', gld), ('VIX', vix)]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

# Align dates
common_idx = spy.index.intersection(vix.index).intersection(gld.index)
spy = spy.loc[common_idx]
gld = gld.loc[common_idx]
vix = vix.loc[common_idx]

print(f"  SPY: {spy.index[0].date()} to {spy.index[-1].date()} ({len(spy)} obs)")
print(f"  GLD: {gld.index[0].date()} to {gld.index[-1].date()} ({len(gld)} obs)")
print(f"  VIX: {vix.index[0].date()} to {vix.index[-1].date()} ({len(vix)} obs)")

# =============================================================================
# 2. FEATURE COMPUTATION
# =============================================================================
print("\n[2/8] Computing features...")

# Returns
spy_ret = spy['Close'].pct_change()
gld_ret = gld['Close'].pct_change()
vix_close = vix['Close'].squeeze()

# SPY log-range features (for HAR model)
spy_high = spy['High'].values.astype(float).ravel()
spy_low = spy['Low'].values.astype(float).ravel()
spy_close = spy['Close'].values.astype(float).ravel()

ratio = spy_high / spy_low
ratio = np.maximum(ratio, 1.0001)
spy_log_range = pd.Series(np.log(ratio), index=spy.index, name='log_range')

# Parkinson variance
spy_parkinson_var = spy_log_range**2 / (4 * np.log(2))

# HAR components: 5d and 21d moving averages of log-range
spy_lr_5d = spy_log_range.rolling(5).mean()
spy_lr_21d = spy_log_range.rolling(21).mean()

# Build feature DataFrame
feat = pd.DataFrame({
    'spy_ret': spy_ret,
    'gld_ret': gld_ret,
    'vix_close': vix_close,
    'log_range': spy_log_range,
    'log_range_5d': spy_lr_5d,
    'log_range_21d': spy_lr_21d,
    'parkinson_var': spy_parkinson_var,
}, index=spy.index).dropna()

print(f"  Features: {feat.index[0].date()} to {feat.index[-1].date()} ({len(feat)} obs)")

# =============================================================================
# 3. DIAGNOSTICS (per CLAUDE.md rule 5)
# =============================================================================
print("\n[3/8] Data diagnostics...")

lr = feat['log_range'].values
spy_r = feat['spy_ret'].values

# Descriptive statistics
print(f"  log_range: mean={np.mean(lr):.5f}, std={np.std(lr):.5f}, "
      f"skew={stats.skew(lr):.3f}, kurt={stats.kurtosis(lr):.3f}")
print(f"  spy_ret:   mean={np.mean(spy_r)*100:.4f}%, std={np.std(spy_r)*100:.4f}%")
print(f"  VIX:       mean={feat['vix_close'].mean():.2f}, std={feat['vix_close'].std():.2f}")

# ADF test
adf_stat, adf_p, _, _, _, _ = adfuller(lr, maxlag=21)
print(f"  ADF(log_range): stat={adf_stat:.4f}, p={adf_p:.2e} "
      f"({'stationary' if adf_p < 0.05 else 'NON-STATIONARY'})")

# Ljung-Box
lb = acorr_ljungbox(lr, lags=[10], return_df=True)
print(f"  Ljung-Box(10): p={float(lb['lb_pvalue'].values[0]):.2e} "
      f"({'autocorrelated' if float(lb['lb_pvalue'].values[0]) < 0.05 else 'no AC'})")

# Correlation: VIX vs Parkinson vol
# Convert Parkinson var to annualized vol (%) for comparison
parkinson_ann_vol = np.sqrt(feat['parkinson_var'] * 252) * 100
corr_vix_pk = feat['vix_close'].corr(parkinson_ann_vol)
print(f"  Corr(VIX, Parkinson ann vol): {corr_vix_pk:.4f}")

diagnostics = {
    'n_obs': len(feat),
    'date_range': f"{feat.index[0].date()} to {feat.index[-1].date()}",
    'log_range_mean': float(np.mean(lr)),
    'log_range_std': float(np.std(lr)),
    'spy_ret_mean_pct': float(np.mean(spy_r) * 100),
    'spy_ret_std_pct': float(np.std(spy_r) * 100),
    'vix_mean': float(feat['vix_close'].mean()),
    'vix_std': float(feat['vix_close'].std()),
    'adf_stat': float(adf_stat),
    'adf_p': float(adf_p),
    'is_stationary': bool(adf_p < 0.05),
    'ljung_box_p10': float(lb['lb_pvalue'].values[0]),
    'corr_vix_parkinson_vol': float(corr_vix_pk),
}

# =============================================================================
# 4. HAR MODEL: Rolling OOS Forecast
# =============================================================================
print("\n[4/8] Estimating HAR log-range model (rolling OOS)...")

# HAR model: y_{t+1} = b0 + b1*y_t + b2*y_{5d,t} + b3*y_{21d,t}
# We need rolling forecasts for the entire strategy period
# IS window: 504 days (~2 years) for OLS efficiency
HAR_WINDOW = 504

# Pre-compute HAR forecasts for the full sample
# For each day t, fit HAR on [t-HAR_WINDOW:t], forecast for t+1
har_cols = ['log_range', 'log_range_5d', 'log_range_21d']

n = len(feat)
har_forecast_lr = np.full(n, np.nan)  # forecasted log-range
har_params_history = []

# Vectorized approach: pre-build matrices
lr_vals = feat['log_range'].values
lr_5d_vals = feat['log_range_5d'].values
lr_21d_vals = feat['log_range_21d'].values

print(f"  Rolling HAR estimation: window={HAR_WINDOW}, {n - HAR_WINDOW} forecasts")

for t in range(HAR_WINDOW, n - 1):
    # Training: [t - HAR_WINDOW, t-1] → predict t
    # y = lr[t - HAR_WINDOW + 1 : t+1]  (target: next-day log_range)
    # X = lr[t - HAR_WINDOW : t], lr_5d[t - HAR_WINDOW : t], lr_21d[t - HAR_WINDOW : t]

    train_start = t - HAR_WINDOW
    Y = lr_vals[train_start + 1: t + 1]  # y_{s+1} for s in [train_start, t-1]
    X = np.column_stack([
        np.ones(HAR_WINDOW),
        lr_vals[train_start: t],
        lr_5d_vals[train_start: t],
        lr_21d_vals[train_start: t]
    ])

    try:
        beta = np.linalg.lstsq(X, Y, rcond=None)[0]
        # Forecast for day t+1 using day t features
        x_t = np.array([1.0, lr_vals[t], lr_5d_vals[t], lr_21d_vals[t]])
        har_forecast_lr[t + 1] = beta @ x_t
    except Exception:
        pass

# Convert HAR log-range forecast to annualized vol (%)
# Parkinson: var = lr² / (4*ln2), std = sqrt(var), ann_vol = std * sqrt(252) * 100
har_forecast_var = har_forecast_lr**2 / (4 * np.log(2))  # daily variance (decimal²)
har_forecast_vol = np.sqrt(har_forecast_var * 252) * 100   # annualized vol (%)

feat['har_forecast_lr'] = har_forecast_lr
feat['har_forecast_vol'] = har_forecast_vol

# 21-day MA of HAR vol (for blend strategy)
feat['har_vol_21d_ma'] = feat['har_forecast_vol'].rolling(21).mean()

# Validity check
valid_har = feat['har_forecast_vol'].dropna()
print(f"  HAR forecasts available: {valid_har.index[0].date()} to {valid_har.index[-1].date()}")
print(f"  HAR vol mean={valid_har.mean():.2f}%, std={valid_har.std():.2f}%, "
      f"min={valid_har.min():.2f}%, max={valid_har.max():.2f}%")
print(f"  VIX mean={feat.loc[valid_har.index, 'vix_close'].mean():.2f}%")
corr_har_vix = feat.loc[valid_har.index, 'har_forecast_vol'].corr(
    feat.loc[valid_har.index, 'vix_close'])
print(f"  Corr(HAR_vol, VIX): {corr_har_vix:.4f}")

# =============================================================================
# 5. STRATEGY DEFINITIONS
# =============================================================================
print("\n[5/8] Computing strategy weights...")

TARGET_VOL = 12.0
RF_DAILY = 0.02 / 252  # 2% annual risk-free rate

# Only use days where HAR forecast is available + all features valid
valid_mask = feat['har_forecast_vol'].notna() & feat['har_vol_21d_ma'].notna()
df = feat[valid_mask].copy()
print(f"  Strategy sample: {df.index[0].date()} to {df.index[-1].date()} ({len(df)} obs)")

# --- Strategy 1: Buy & Hold SPY ---
w_bh_spy = pd.Series(1.0, index=df.index)

# --- Strategy 2: Buy & Hold 50/50 SPY+GLD ---
# (implicit: w=1 for the 50/50 blend)
blend_ret = 0.5 * df['spy_ret'] + 0.5 * df['gld_ret']
w_bh_blend = pd.Series(1.0, index=df.index)

# --- Strategy 3: Standard 12/VIX VT ---
w_vix_vt = (TARGET_VOL / df['vix_close']).clip(upper=1.0)

# --- Strategy 4: HAR-based VT ---
# w = target_vol / σ_HAR (annualized %)
w_har_vt = (TARGET_VOL / df['har_forecast_vol']).clip(upper=1.0)

# --- Strategy 5: Hybrid 50/50 VIX + HAR ---
sigma_hybrid = 0.5 * df['vix_close'] + 0.5 * df['har_forecast_vol']
w_hybrid_vt = (TARGET_VOL / sigma_hybrid).clip(upper=1.0)

# --- Strategy 6: VIX-HAR Blend (VIX for level, HAR for timing) ---
# σ_blend = VIX × (σ_HAR / σ_HAR_21d_MA)
# When HAR says vol is rising relative to its own average → increase σ estimate
har_ratio = df['har_forecast_vol'] / df['har_vol_21d_ma']
har_ratio = har_ratio.clip(0.5, 2.0)  # cap extreme ratios
sigma_blend = df['vix_close'] * har_ratio
w_blend_vt = (TARGET_VOL / sigma_blend).clip(upper=1.0)

# Compute strategy returns (shift weights by 1 day — no look-ahead)
strategies = {}
strategy_weights = {}

# SPY-only strategies
for name, w in [('BH_SPY', w_bh_spy), ('VIX_VT', w_vix_vt),
                ('HAR_VT', w_har_vt), ('Hybrid_VT', w_hybrid_vt),
                ('Blend_VT', w_blend_vt)]:
    w_lagged = w.shift(1)
    ret = w_lagged * df['spy_ret'] + (1 - w_lagged) * RF_DAILY
    strategies[name] = ret
    strategy_weights[name] = w

# 50/50 SPY+GLD strategies (apply VT weight to the 50/50 blend)
for name, w in [('BH_Blend', w_bh_blend), ('VIX_VT_Blend', w_vix_vt),
                ('HAR_VT_Blend', w_har_vt), ('Hybrid_VT_Blend', w_hybrid_vt),
                ('Blend_VT_Blend', w_blend_vt)]:
    w_lagged = w.shift(1)
    ret = w_lagged * blend_ret + (1 - w_lagged) * RF_DAILY
    strategies[name] = ret

strat_returns = pd.DataFrame(strategies).dropna()
print(f"  Returns computed: {strat_returns.index[0].date()} to {strat_returns.index[-1].date()}")

# Weight statistics
print("\n  Weight statistics:")
for name, w in strategy_weights.items():
    w_valid = w.loc[strat_returns.index]
    print(f"    {name:12s}: mean={w_valid.mean():.3f}, std={w_valid.std():.3f}, "
          f"min={w_valid.min():.3f}, max={w_valid.max():.3f}")

# =============================================================================
# 6. TURNOVER ANALYSIS
# =============================================================================
print("\n[6/8] Turnover analysis...")

turnover_stats = {}
for name, w in strategy_weights.items():
    if name == 'BH_SPY':
        turnover_stats[name] = {'daily_mean': 0.0, 'annual': 0.0}
        continue
    w_valid = w.loc[strat_returns.index]
    daily_to = w_valid.diff().abs()
    ann_to = daily_to.mean() * 252
    turnover_stats[name] = {
        'daily_mean': float(daily_to.mean()),
        'annual': float(ann_to),
    }
    print(f"  {name:12s}: annual_turnover={ann_to:.2f}")

# =============================================================================
# 7. PERFORMANCE EVALUATION
# =============================================================================
print("\n[7/8] Performance evaluation...")

def evaluate_performance(returns_df, period_name, rf_annual=0.02):
    """Compute strategy performance metrics."""
    results = {}
    for col in returns_df.columns:
        r = returns_df[col].dropna()
        n = len(r)
        if n < 50:
            continue

        ann_ret = r.mean() * 252
        ann_vol = r.std() * np.sqrt(252)
        sharpe = (ann_ret - rf_annual) / ann_vol if ann_vol > 0 else 0

        # Sortino
        downside = r[r < 0]
        downside_vol = downside.std() * np.sqrt(252) if len(downside) > 5 else ann_vol
        sortino = (ann_ret - rf_annual) / downside_vol if downside_vol > 0 else 0

        # Max drawdown
        cum = (1 + r).cumprod()
        peak = cum.cummax()
        dd = (cum - peak) / peak
        max_dd = float(dd.min())

        # Calmar
        calmar = (ann_ret - rf_annual) / abs(max_dd) if max_dd != 0 else 0

        results[col] = {
            'n_obs': n,
            'ann_return_pct': round(float(ann_ret * 100), 2),
            'ann_vol_pct': round(float(ann_vol * 100), 2),
            'sharpe': round(float(sharpe), 4),
            'sortino': round(float(sortino), 4),
            'max_drawdown_pct': round(float(max_dd * 100), 2),
            'calmar': round(float(calmar), 4),
        }

    return results


def compute_net_sharpe(returns_df, weight_series, rf_annual=0.02, tx_bps=3):
    """Sharpe after monthly rebalancing transaction costs."""
    results = {}
    for col in returns_df.columns:
        r = returns_df[col].dropna()
        n = len(r)
        if n < 50:
            continue

        ann_ret = r.mean() * 252
        ann_vol = r.std() * np.sqrt(252)

        # Monthly TX cost: turnover * cost_per_trade
        if col in weight_series:
            w = weight_series[col].loc[r.index]
            monthly_turnover = w.diff().abs().resample('ME').sum()
            avg_monthly_to = monthly_turnover.mean()
            annual_tx_drag = avg_monthly_to * 12 * (tx_bps / 10000)
        elif col.startswith('BH'):
            annual_tx_drag = 0
        else:
            annual_tx_drag = 0.001  # fallback

        net_sharpe = ((ann_ret - rf_annual) - annual_tx_drag) / ann_vol if ann_vol > 0 else 0
        results[col] = {
            'net_sharpe': round(float(net_sharpe), 4),
            'annual_tx_drag_bps': round(float(annual_tx_drag * 10000), 1),
        }
    return results


# --- Period definitions ---
periods = {
    'IS (2006-2022)': ('2006-01-01', '2022-12-31'),
    'OOS (2023-2025)': ('2023-01-01', '2025-12-31'),
    'Full (2008-2025)': ('2008-01-01', '2025-12-31'),
}

all_performance = {}
for period_name, (p_start, p_end) in periods.items():
    mask = (strat_returns.index >= p_start) & (strat_returns.index <= p_end)
    period_ret = strat_returns[mask]
    if len(period_ret) < 50:
        print(f"  {period_name}: SKIP (only {len(period_ret)} obs)")
        continue

    perf = evaluate_performance(period_ret, period_name)
    net = compute_net_sharpe(period_ret, strategy_weights)

    # Merge net sharpe
    for col in perf:
        if col in net:
            perf[col].update(net[col])

    all_performance[period_name] = perf

    print(f"\n  === {period_name} ({len(period_ret)} obs) ===")
    print(f"  {'Strategy':<20s} {'Sharpe':>8s} {'NetShrp':>8s} {'AnnRet%':>8s} {'AnnVol%':>8s} {'MaxDD%':>8s} {'Calmar':>8s}")
    print(f"  {'-'*72}")

    for col in period_ret.columns:
        if col in perf:
            p = perf[col]
            ns = p.get('net_sharpe', '-')
            ns_str = f"{ns:.4f}" if isinstance(ns, float) else ns
            print(f"  {col:<20s} {p['sharpe']:8.4f} {ns_str:>8s} {p['ann_return_pct']:8.2f} "
                  f"{p['ann_vol_pct']:8.2f} {p['max_drawdown_pct']:8.2f} {p['calmar']:8.4f}")

# =============================================================================
# 8. STATISTICAL TESTS
# =============================================================================
print("\n[8/8] Statistical tests (DM test on returns)...")


def dm_test_returns(ret1, ret2, h=1):
    """DM test comparing strategy returns (squared error loss)."""
    # Loss: squared deviation from mean
    d = ret1.values - ret2.values
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 50:
        return np.nan, np.nan

    d_bar = np.mean(d)
    gamma0 = np.var(d, ddof=1)
    hac_var = gamma0
    for k in range(1, max(h + 1, 2)):
        if k >= n:
            break
        gamma_k = np.mean((d[k:] - d_bar) * (d[:-k] - d_bar))
        hac_var += 2 * (1 - k / max(h + 1, 2)) * gamma_k

    se = np.sqrt(max(hac_var, 1e-20) / n)
    if se < 1e-12:
        return np.nan, np.nan

    t_stat = d_bar / se
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return float(t_stat), float(p_val)


def sharpe_test(ret1, ret2, rf_annual=0.02):
    """Memmel (2003) test for Sharpe ratio difference."""
    r1 = ret1.values
    r2 = ret2.values
    valid = np.isfinite(r1) & np.isfinite(r2)
    r1 = r1[valid]
    r2 = r2[valid]
    n = len(r1)
    if n < 50:
        return np.nan, np.nan

    rf = rf_annual / 252
    mu1 = np.mean(r1) - rf
    mu2 = np.mean(r2) - rf
    s1 = np.std(r1, ddof=1)
    s2 = np.std(r2, ddof=1)

    sr1 = mu1 / s1
    sr2 = mu2 / s2

    # Memmel (2003) approximation
    rho = np.corrcoef(r1, r2)[0, 1]
    se = np.sqrt((2 * (1 - rho) + 0.5 * (sr1**2 + sr2**2 - 2 * sr1 * sr2 * rho)) / n)

    if se < 1e-12:
        return np.nan, np.nan

    z = (sr1 - sr2) / se
    p = 2 * (1 - stats.norm.cdf(abs(z)))
    return float(z), float(p)


stat_tests = {}
# For each evaluation period
for period_name, (p_start, p_end) in periods.items():
    mask = (strat_returns.index >= p_start) & (strat_returns.index <= p_end)
    period_ret = strat_returns[mask]
    if len(period_ret) < 50:
        continue

    period_tests = {}

    # HAR_VT vs VIX_VT (key comparison, SPY-only)
    for pair_name, col1, col2 in [
        ('HAR_VT vs VIX_VT', 'HAR_VT', 'VIX_VT'),
        ('Hybrid_VT vs VIX_VT', 'Hybrid_VT', 'VIX_VT'),
        ('Blend_VT vs VIX_VT', 'Blend_VT', 'VIX_VT'),
        ('HAR_VT_Blend vs VIX_VT_Blend', 'HAR_VT_Blend', 'VIX_VT_Blend'),
        ('Hybrid_VT_Blend vs VIX_VT_Blend', 'Hybrid_VT_Blend', 'VIX_VT_Blend'),
        ('Blend_VT_Blend vs VIX_VT_Blend', 'Blend_VT_Blend', 'VIX_VT_Blend'),
    ]:
        if col1 not in period_ret.columns or col2 not in period_ret.columns:
            continue

        r1 = period_ret[col1]
        r2 = period_ret[col2]

        # DM test
        dm_t, dm_p = dm_test_returns(r1, r2)

        # Sharpe test
        z, z_p = sharpe_test(r1, r2)

        period_tests[pair_name] = {
            'dm_t_stat': round(dm_t, 4) if not np.isnan(dm_t) else None,
            'dm_p_value': round(dm_p, 4) if not np.isnan(dm_p) else None,
            'sharpe_z': round(z, 4) if not np.isnan(z) else None,
            'sharpe_p': round(z_p, 4) if not np.isnan(z_p) else None,
            'harvey_t3_pass': bool(abs(z) > 3.0) if not np.isnan(z) else False,
            'significant_5pct': bool(z_p < 0.05) if not np.isnan(z_p) else False,
        }

    stat_tests[period_name] = period_tests

    print(f"\n  === {period_name} ===")
    for pair, res in period_tests.items():
        sig = '***' if res.get('sharpe_p', 1) < 0.001 else '**' if res.get('sharpe_p', 1) < 0.01 else '*' if res.get('sharpe_p', 1) < 0.05 else 'NS'
        h3 = ' HARVEY-PASS' if res.get('harvey_t3_pass', False) else ''
        z_val = res.get('sharpe_z', 'N/A')
        p_val = res.get('sharpe_p', 'N/A')
        print(f"  {pair:40s}: z={z_val}, p={p_val} {sig}{h3}")

# =============================================================================
# 9. CROSS-OOS: 5 Sub-Period Analysis
# =============================================================================
print("\n" + "=" * 70)
print("[BONUS] 5-Period Cross-OOS (robustness across regimes)")
print("=" * 70)

oos_periods = [
    ("2008-2010 (GFC)", "2008-01-01", "2010-12-31"),
    ("2011-2014 (recovery)", "2011-01-01", "2014-12-31"),
    ("2015-2018 (low vol + Volmageddon)", "2015-01-01", "2018-12-31"),
    ("2019-2020 (COVID)", "2019-01-01", "2020-12-31"),
    ("2021-2025 (rate hikes + post-COVID)", "2021-01-01", "2025-12-31"),
]

cross_oos_results = []
har_wins_sharpe = 0
har_better_turnover = 0

for p_name, p_start, p_end in oos_periods:
    mask = (strat_returns.index >= p_start) & (strat_returns.index <= p_end)
    sub_ret = strat_returns[mask]
    if len(sub_ret) < 50:
        cross_oos_results.append({'period': p_name, 'status': 'skipped', 'n_obs': len(sub_ret)})
        continue

    perf = evaluate_performance(sub_ret, p_name)

    # Sharpe comparison
    vix_sharpe = perf.get('VIX_VT', {}).get('sharpe', None)
    har_sharpe = perf.get('HAR_VT', {}).get('sharpe', None)
    hybrid_sharpe = perf.get('Hybrid_VT', {}).get('sharpe', None)
    blend_sharpe = perf.get('Blend_VT', {}).get('sharpe', None)

    if har_sharpe is not None and vix_sharpe is not None:
        if har_sharpe > vix_sharpe:
            har_wins_sharpe += 1

    # Turnover comparison
    if 'VIX_VT' in strategy_weights and 'HAR_VT' in strategy_weights:
        sub_w_vix = strategy_weights['VIX_VT'].loc[sub_ret.index]
        sub_w_har = strategy_weights['HAR_VT'].loc[sub_ret.index]
        to_vix = sub_w_vix.diff().abs().mean() * 252
        to_har = sub_w_har.diff().abs().mean() * 252
        if to_har < to_vix:
            har_better_turnover += 1
    else:
        to_vix, to_har = None, None

    cross_oos_results.append({
        'period': p_name,
        'n_obs': len(sub_ret),
        'vix_vt_sharpe': vix_sharpe,
        'har_vt_sharpe': har_sharpe,
        'hybrid_vt_sharpe': hybrid_sharpe,
        'blend_vt_sharpe': blend_sharpe,
        'har_minus_vix': round(har_sharpe - vix_sharpe, 4) if har_sharpe and vix_sharpe else None,
        'vix_vt_turnover': round(float(to_vix), 2) if to_vix is not None else None,
        'har_vt_turnover': round(float(to_har), 2) if to_har is not None else None,
        'har_better_turnover': bool(to_har < to_vix) if to_har is not None else None,
    })

    print(f"\n  {p_name} (n={len(sub_ret)}):")
    print(f"    VIX_VT Sharpe: {vix_sharpe}")
    print(f"    HAR_VT Sharpe: {har_sharpe} (diff={round(har_sharpe - vix_sharpe, 4) if har_sharpe and vix_sharpe else 'N/A'})")
    print(f"    Hybrid_VT Sharpe: {hybrid_sharpe}")
    print(f"    Blend_VT  Sharpe: {blend_sharpe}")
    if to_vix is not None:
        print(f"    Turnover: VIX={to_vix:.2f}, HAR={to_har:.2f}, HAR {'lower' if to_har < to_vix else 'higher'}")

n_valid_periods = len([r for r in cross_oos_results if r.get('n_obs', 0) >= 50])
print(f"\n  HAR wins Sharpe: {har_wins_sharpe}/{n_valid_periods}")
print(f"  HAR better turnover: {har_better_turnover}/{n_valid_periods}")

# =============================================================================
# 10. JUDGMENT
# =============================================================================
elapsed = time.time() - t_start

print("\n" + "=" * 70)
print("JUDGMENT")
print("=" * 70)

# Get OOS performance for key comparison
oos_perf = all_performance.get('OOS (2023-2025)', {})
vix_oos_sharpe = oos_perf.get('VIX_VT', {}).get('sharpe', None)
har_oos_sharpe = oos_perf.get('HAR_VT', {}).get('sharpe', None)
hybrid_oos_sharpe = oos_perf.get('Hybrid_VT', {}).get('sharpe', None)
blend_oos_sharpe = oos_perf.get('Blend_VT', {}).get('sharpe', None)

# Full period
full_perf = all_performance.get('Full (2008-2025)', {})
vix_full_sharpe = full_perf.get('VIX_VT', {}).get('sharpe', None)
har_full_sharpe = full_perf.get('HAR_VT', {}).get('sharpe', None)

# Statistical significance
oos_stat = stat_tests.get('OOS (2023-2025)', {})
full_stat = stat_tests.get('Full (2008-2025)', {})
har_vs_vix_oos = oos_stat.get('HAR_VT vs VIX_VT', {})
har_vs_vix_full = full_stat.get('HAR_VT vs VIX_VT', {})

# Check if any HAR variant beats VIX significantly
any_significant = False
any_harvey_pass = False
for period_tests in stat_tests.values():
    for test_name, test_res in period_tests.items():
        if test_res.get('significant_5pct', False):
            any_significant = True
        if test_res.get('harvey_t3_pass', False):
            any_harvey_pass = True

# Best strategy identification
best_strat_name = None
best_sharpe = -999
if full_perf:
    for name, metrics in full_perf.items():
        if metrics.get('sharpe', -999) > best_sharpe:
            best_sharpe = metrics['sharpe']
            best_strat_name = name

# Turnover advantage
full_mask = (strat_returns.index >= '2008-01-01') & (strat_returns.index <= '2025-12-31')
full_ret = strat_returns[full_mask]
if 'VIX_VT' in strategy_weights and 'HAR_VT' in strategy_weights:
    full_to_vix = strategy_weights['VIX_VT'].loc[full_ret.index].diff().abs().mean() * 252
    full_to_har = strategy_weights['HAR_VT'].loc[full_ret.index].diff().abs().mean() * 252
    turnover_advantage = full_to_har < full_to_vix
else:
    full_to_vix, full_to_har = None, None
    turnover_advantage = False

# Final judgment
judgment_lines = []
judgment_lines.append(f"VIX_VT Full Sharpe: {vix_full_sharpe}")
judgment_lines.append(f"HAR_VT Full Sharpe: {har_full_sharpe}")
if har_full_sharpe and vix_full_sharpe:
    diff = har_full_sharpe - vix_full_sharpe
    judgment_lines.append(f"Sharpe difference: {diff:+.4f}")
judgment_lines.append(f"Best strategy: {best_strat_name} (Sharpe={best_sharpe:.4f})")
judgment_lines.append(f"Any test significant (p<0.05)? {any_significant}")
judgment_lines.append(f"Any Harvey t>3.0 pass? {any_harvey_pass}")
judgment_lines.append(f"Turnover advantage (HAR < VIX)? {turnover_advantage}")
judgment_lines.append(f"HAR wins Sharpe cross-OOS: {har_wins_sharpe}/{n_valid_periods}")

if any_harvey_pass:
    overall_judgment = "HAR-VT provides statistically significant improvement over VIX-VT (Harvey t>3.0)"
elif any_significant:
    overall_judgment = "HAR-VT shows significant improvement at 5% level but does NOT pass Harvey t>3.0 threshold"
elif har_full_sharpe and vix_full_sharpe and har_full_sharpe > vix_full_sharpe:
    if turnover_advantage:
        overall_judgment = "HAR-VT has small Sharpe edge + lower turnover, but NOT statistically significant. Turnover advantage is the main practical benefit"
    else:
        overall_judgment = "HAR-VT has small Sharpe edge but NOT significant. Consistent with K440/K467: prediction ≠ application"
else:
    overall_judgment = "HAR-VT does NOT improve VIX-VT. Prediction accuracy ≠ strategy value. VIX remains the best practical VT signal"

judgment_lines.append(f"\nOVERALL: {overall_judgment}")

for line in judgment_lines:
    print(f"  {line}")

# =============================================================================
# SAVE RESULTS
# =============================================================================
output = {
    "experiment_id": "K470",
    "title": "HAR Log-Range Based Volatility Targeting Strategy",
    "research_question": "Can HAR log-range's superior vol forecasting translate to better VT strategy vs 12/VIX?",
    "background": {
        "K465_K469": "HAR log-range is robustly the best vol forecaster (8/10 cross-OOS with r²)",
        "K440": "VRP prediction ≠ trading (VRP-VT hurts Sharpe)",
        "K467": "HAR VaR fails (best forecaster ≠ best VaR)",
        "lesson": "prediction accuracy ≠ application value",
    },
    "references": [
        "Corsi (2009) J Financial Econometrics — HAR-RV model",
        "Alizadeh, Brandt & Diebold (2002) JFE — Range-based vol estimation",
        "Moreira & Muir (2017) JoF 72(4) — Volatility-Managed Portfolios",
        "K440 — VRP-VT null result",
        "K465/K469 — HAR log-range cross-OOS validation",
        "K467 — HAR VaR null result",
    ],
    "method": {
        "strategies": [
            "BH_SPY: Buy & Hold SPY",
            "BH_Blend: Buy & Hold 50/50 SPY+GLD",
            "VIX_VT: w = 12/VIX (baseline, cap 100%)",
            "HAR_VT: w = 12/σ_HAR (cap 100%)",
            "Hybrid_VT: w = 12/(0.5*VIX + 0.5*σ_HAR)",
            "Blend_VT: w = 12/(VIX × σ_HAR/σ_HAR_21d_MA)",
        ],
        "har_model": "HAR log-range: y_{t+1} = b0 + b1*y_t + b2*y_{5d,t} + b3*y_{21d,t}",
        "har_window": HAR_WINDOW,
        "target_vol": TARGET_VOL,
        "weight_cap": 1.0,
        "rf_rate": 0.02,
    },
    "data_source": "yfinance (SPY, GLD, ^VIX)",
    "diagnostics": diagnostics,
    "har_diagnostics": {
        "corr_har_vix": float(corr_har_vix),
        "har_vol_mean": float(valid_har.mean()),
        "har_vol_std": float(valid_har.std()),
        "har_vol_min": float(valid_har.min()),
        "har_vol_max": float(valid_har.max()),
    },
    "performance": all_performance,
    "statistical_tests": stat_tests,
    "turnover": turnover_stats,
    "cross_oos": {
        "periods": cross_oos_results,
        "har_wins_sharpe": har_wins_sharpe,
        "n_valid_periods": n_valid_periods,
        "har_better_turnover": har_better_turnover,
    },
    "judgment": overall_judgment,
    "judgment_details": judgment_lines,
    "runtime_seconds": round(elapsed, 1),
    "timestamp": datetime.now(timezone.utc).isoformat(),
}

output_path = "experiments/k470_har_vt_strategy_results.json"
with open(output_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)
print(f"\n  Results saved to {output_path}")

print(f"\n  Runtime: {elapsed:.1f}s")
print("\n" + "=" * 70)
print("K470 COMPLETE")
print("=" * 70)
