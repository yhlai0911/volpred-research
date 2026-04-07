"""
K975: VIX Term Structure Slope — Predictive Power and Strategy Analysis

Research question: Does the VIX/VIX3M slope provide incremental predictive
power for SPY returns and volatility beyond VIX level alone?

Data source: yfinance (^VIX, ^VIX3M, SPY), 2010-01-01 to 2026-04-07
References:
  - Simon & Campasano (2014) "The VIX Futures Basis" JFM
  - Johnson (2017) "VIX Term Structure" SSRN
  - Mixon (2007) "The Implied Volatility Term Structure" JD

Fixed seed: np.random.seed(42)
"""

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import json
import warnings
from datetime import datetime
from scipy import stats
from pathlib import Path

np.random.seed(42)
warnings.filterwarnings('ignore')

OUT_DIR = Path(__file__).parent
print(f"Output directory: {OUT_DIR}")

# ============================================================
# 1. DATA LOADING
# ============================================================
print("\n" + "="*60)
print("1. DATA LOADING")
print("="*60)

import yfinance as yf

vix_raw = yf.download('^VIX', start='2010-01-01', end='2026-04-07', progress=False)
spy_raw = yf.download('SPY', start='2010-01-01', end='2026-04-07', progress=False)

# Try VIX3M first, fall back to VIX9D
try:
    vix3m_raw = yf.download('^VIX3M', start='2010-01-01', end='2026-04-07', progress=False)
    if len(vix3m_raw) < 100:
        raise ValueError("VIX3M data too short")
    slope_label = "VIX/VIX3M"
    print(f"VIX3M data loaded: {len(vix3m_raw)} rows")
except Exception as e:
    print(f"VIX3M not available ({e}), trying VIX9D...")
    vix3m_raw = yf.download('^VIX9D', start='2010-01-01', end='2026-04-07', progress=False)
    if len(vix3m_raw) < 100:
        # Use VVIX as last resort proxy
        print("VIX9D also not available, constructing synthetic slope from VIX percentile")
        vix3m_raw = None
        slope_label = "VIX_percentile_proxy"
    else:
        slope_label = "VIX9D/VIX"
        print(f"VIX9D data loaded: {len(vix3m_raw)} rows")

# Handle multi-level columns from yfinance
def get_close(df):
    if isinstance(df.columns, pd.MultiIndex):
        # Try 'Close' level
        if 'Close' in df.columns.get_level_values(0):
            return df['Close'].iloc[:, 0] if df['Close'].ndim > 1 else df['Close']
        return df.iloc[:, 0]
    if 'Close' in df.columns:
        return df['Close']
    return df.iloc[:, 0]

vix_close = get_close(vix_raw).rename('VIX')
spy_close = get_close(spy_raw).rename('SPY')

if vix3m_raw is not None:
    vix3m_close = get_close(vix3m_raw).rename('VIX3M')
else:
    vix3m_close = None

print(f"VIX: {len(vix_close)} rows, {vix_close.index[0].date()} to {vix_close.index[-1].date()}")
print(f"SPY: {len(spy_close)} rows, {spy_close.index[0].date()} to {spy_close.index[-1].date()}")

# Build unified DataFrame
df = pd.DataFrame({'VIX': vix_close, 'SPY': spy_close})
if vix3m_close is not None:
    df['VIX3M'] = vix3m_close
df = df.dropna()

# SPY returns
df['ret_1d'] = df['SPY'].pct_change()
df['ret_5d'] = df['SPY'].pct_change(5)
df['ret_22d'] = df['SPY'].pct_change(22)

# Realized volatility (forward-looking, for prediction analysis only)
df['rvol_5d'] = df['ret_1d'].rolling(5).std() * np.sqrt(252)
df['rvol_22d'] = df['ret_1d'].rolling(22).std() * np.sqrt(252)

# Forward returns and vol (what we want to predict)
df['fwd_ret_1d'] = df['ret_1d'].shift(-1)
df['fwd_ret_5d'] = df['ret_5d'].shift(-5)
df['fwd_ret_22d'] = df['ret_22d'].shift(-22)
df['fwd_rvol_5d'] = df['rvol_5d'].shift(-5)
df['fwd_rvol_22d'] = df['rvol_22d'].shift(-22)

# Compute slope
if 'VIX3M' in df.columns:
    df['slope'] = df['VIX'] / df['VIX3M']
    print(f"\nSlope = VIX / VIX3M")
else:
    # Synthetic: use VIX percentile rank as proxy
    df['slope'] = df['VIX'].rolling(252).apply(lambda x: stats.percentileofscore(x, x.iloc[-1]) / 100)
    print(f"\nSlope = VIX percentile rank (synthetic proxy)")

df = df.dropna(subset=['slope', 'ret_1d'])
print(f"Combined dataset: {len(df)} rows, {df.index[0].date()} to {df.index[-1].date()}")

# ============================================================
# 2. DESCRIPTIVE STATISTICS
# ============================================================
print("\n" + "="*60)
print("2. DESCRIPTIVE STATISTICS")
print("="*60)

slope = df['slope'].dropna()
desc = {
    'mean': float(slope.mean()),
    'std': float(slope.std()),
    'min': float(slope.min()),
    'max': float(slope.max()),
    'p5': float(slope.quantile(0.05)),
    'p25': float(slope.quantile(0.25)),
    'p50': float(slope.quantile(0.50)),
    'p75': float(slope.quantile(0.75)),
    'p95': float(slope.quantile(0.95)),
    'skewness': float(slope.skew()),
    'kurtosis': float(slope.kurtosis()),
}

# Backwardation frequency
backwardation_pct = float((slope > 1.0).mean() * 100)
desc['backwardation_pct'] = backwardation_pct

# Autocorrelation
acf_1 = float(slope.autocorr(1))
acf_5 = float(slope.autocorr(5))
acf_22 = float(slope.autocorr(22))
desc['acf_1'] = acf_1
desc['acf_5'] = acf_5
desc['acf_22'] = acf_22

print(f"Slope descriptive statistics:")
for k, v in desc.items():
    print(f"  {k}: {v:.4f}")

# ============================================================
# 3. PLOT: SLOPE DISTRIBUTION AND TIME SERIES
# ============================================================
print("\n" + "="*60)
print("3. SLOPE DISTRIBUTION AND TIME SERIES")
print("="*60)

fig, axes = plt.subplots(2, 2, figsize=(14, 10))

# Time series
ax = axes[0, 0]
ax.plot(df.index, df['slope'], linewidth=0.5, alpha=0.8)
ax.axhline(1.0, color='red', linestyle='--', linewidth=1, label='Contango/Backwardation')
ax.set_title(f'{slope_label} Slope (Time Series)')
ax.set_ylabel('Slope')
ax.legend()
ax.grid(True, alpha=0.3)

# Distribution
ax = axes[0, 1]
ax.hist(df['slope'].dropna(), bins=100, density=True, alpha=0.7, color='steelblue')
ax.axvline(1.0, color='red', linestyle='--', linewidth=1)
ax.set_title(f'{slope_label} Slope Distribution')
ax.set_xlabel('Slope')
ax.set_ylabel('Density')
ax.grid(True, alpha=0.3)

# VIX vs Slope scatter
ax = axes[1, 0]
ax.scatter(df['VIX'], df['slope'], alpha=0.1, s=3, c='steelblue')
ax.axhline(1.0, color='red', linestyle='--', linewidth=1)
ax.set_title('VIX Level vs Slope')
ax.set_xlabel('VIX')
ax.set_ylabel('Slope')
ax.grid(True, alpha=0.3)

# Rolling 60-day slope
ax = axes[1, 1]
rolling_slope = df['slope'].rolling(60).mean()
ax.plot(df.index, rolling_slope, linewidth=1, color='steelblue')
ax.axhline(1.0, color='red', linestyle='--', linewidth=1)
ax.set_title('60-Day Rolling Average Slope')
ax.set_ylabel('Slope')
ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(OUT_DIR / 'k975_slope_distribution.png', dpi=150, bbox_inches='tight')
plt.close()
print("Saved k975_slope_distribution.png")

# ============================================================
# 4. PREDICTIVE REGRESSIONS
# ============================================================
print("\n" + "="*60)
print("4. PREDICTIVE REGRESSIONS")
print("="*60)

from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score

# IS/OOS split
is_mask = df.index < '2019-01-01'
oos_mask = df.index >= '2019-01-01'

regression_results = {}

targets = {
    'fwd_ret_1d': 'Forward 1d Return',
    'fwd_ret_5d': 'Forward 5d Return',
    'fwd_ret_22d': 'Forward 22d Return',
    'fwd_rvol_5d': 'Forward 5d RVol',
    'fwd_rvol_22d': 'Forward 22d RVol',
}

for target_col, target_name in targets.items():
    valid = df[['slope', 'VIX', target_col]].dropna()
    if len(valid) < 100:
        print(f"  Skipping {target_name}: insufficient data ({len(valid)} rows)")
        continue

    is_data = valid[valid.index < '2019-01-01']
    oos_data = valid[valid.index >= '2019-01-01']

    if len(is_data) < 50 or len(oos_data) < 50:
        continue

    result = {}

    # Model 1: slope only
    X_slope_is = is_data[['slope']].values
    X_slope_oos = oos_data[['slope']].values
    y_is = is_data[target_col].values
    y_oos = oos_data[target_col].values

    reg1 = LinearRegression().fit(X_slope_is, y_is)
    pred_is_1 = reg1.predict(X_slope_is)
    pred_oos_1 = reg1.predict(X_slope_oos)
    r2_is_1 = r2_score(y_is, pred_is_1)
    r2_oos_1 = r2_score(y_oos, pred_oos_1)

    result['slope_only'] = {
        'coef': float(reg1.coef_[0]),
        'intercept': float(reg1.intercept_),
        'r2_is': float(r2_is_1),
        'r2_oos': float(r2_oos_1),
        'n_is': len(is_data),
        'n_oos': len(oos_data),
    }

    # T-stat for slope coefficient
    residuals = y_is - pred_is_1
    se = np.sqrt(np.sum(residuals**2) / (len(y_is) - 2) / np.sum((X_slope_is[:, 0] - X_slope_is[:, 0].mean())**2))
    t_stat = reg1.coef_[0] / se
    result['slope_only']['t_stat'] = float(t_stat)

    # Model 2: VIX only
    X_vix_is = is_data[['VIX']].values
    X_vix_oos = oos_data[['VIX']].values

    reg2 = LinearRegression().fit(X_vix_is, y_is)
    pred_is_2 = reg2.predict(X_vix_is)
    pred_oos_2 = reg2.predict(X_vix_oos)
    r2_is_2 = r2_score(y_is, pred_is_2)
    r2_oos_2 = r2_score(y_oos, pred_oos_2)

    result['vix_only'] = {
        'coef': float(reg2.coef_[0]),
        'r2_is': float(r2_is_2),
        'r2_oos': float(r2_oos_2),
    }

    # Model 3: slope + VIX
    X_both_is = is_data[['slope', 'VIX']].values
    X_both_oos = oos_data[['slope', 'VIX']].values

    reg3 = LinearRegression().fit(X_both_is, y_is)
    pred_is_3 = reg3.predict(X_both_is)
    pred_oos_3 = reg3.predict(X_both_oos)
    r2_is_3 = r2_score(y_is, pred_is_3)
    r2_oos_3 = r2_score(y_oos, pred_oos_3)

    result['slope_plus_vix'] = {
        'coef_slope': float(reg3.coef_[0]),
        'coef_vix': float(reg3.coef_[1]),
        'r2_is': float(r2_is_3),
        'r2_oos': float(r2_oos_3),
        'incremental_r2_is': float(r2_is_3 - r2_is_2),
        'incremental_r2_oos': float(r2_oos_3 - r2_oos_2),
    }

    # DM test: compare slope+VIX vs VIX-only forecasts (OOS)
    e1 = (y_oos - pred_oos_2)**2  # VIX only errors
    e2 = (y_oos - pred_oos_3)**2  # Slope+VIX errors
    d = e1 - e2
    dm_stat = d.mean() / (d.std() / np.sqrt(len(d)))
    dm_pval = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    result['dm_test_vs_vix'] = {
        'dm_stat': float(dm_stat),
        'p_value': float(dm_pval),
        'significant_5pct': bool(dm_pval < 0.05),
    }

    regression_results[target_col] = result

    print(f"\n  {target_name}:")
    print(f"    Slope only  — IS R²={r2_is_1:.6f}, OOS R²={r2_oos_1:.6f}, t={t_stat:.3f}")
    print(f"    VIX only    — IS R²={r2_is_2:.6f}, OOS R²={r2_oos_2:.6f}")
    print(f"    Slope+VIX   — IS R²={r2_is_3:.6f}, OOS R²={r2_oos_3:.6f}")
    print(f"    Incremental — IS ΔR²={r2_is_3 - r2_is_2:.6f}, OOS ΔR²={r2_oos_3 - r2_oos_2:.6f}")
    print(f"    DM test     — stat={dm_stat:.3f}, p={dm_pval:.4f}")

# ============================================================
# 5. CONDITIONAL RETURN ANALYSIS
# ============================================================
print("\n" + "="*60)
print("5. CONDITIONAL RETURN ANALYSIS")
print("="*60)

# Define regimes based on slope
df['regime'] = pd.cut(df['slope'],
                       bins=[-np.inf, 0.85, 0.95, 1.0, 1.05, 1.15, np.inf],
                       labels=['Deep_Contango', 'Contango', 'Normal',
                               'Mild_BW', 'Moderate_BW', 'Strong_BW'])

conditional_results = {}
for regime in df['regime'].dropna().unique():
    mask = df['regime'] == regime
    n = mask.sum()
    if n < 10:
        continue

    regime_ret = df.loc[mask, 'fwd_ret_1d'].dropna()
    regime_ret_5d = df.loc[mask, 'fwd_ret_5d'].dropna()
    regime_ret_22d = df.loc[mask, 'fwd_ret_22d'].dropna()

    conditional_results[str(regime)] = {
        'n': int(n),
        'pct': float(n / len(df) * 100),
        'mean_ret_1d': float(regime_ret.mean()) if len(regime_ret) > 0 else None,
        'std_ret_1d': float(regime_ret.std()) if len(regime_ret) > 0 else None,
        'mean_ret_5d': float(regime_ret_5d.mean()) if len(regime_ret_5d) > 0 else None,
        'mean_ret_22d': float(regime_ret_22d.mean()) if len(regime_ret_22d) > 0 else None,
        'sharpe_1d': float(regime_ret.mean() / regime_ret.std() * np.sqrt(252)) if len(regime_ret) > 1 else None,
    }

    print(f"  {regime}: n={n} ({n/len(df)*100:.1f}%)")
    if len(regime_ret) > 0:
        print(f"    1d mean={regime_ret.mean()*10000:.2f}bp, 5d mean={regime_ret_5d.mean()*10000:.2f}bp")

# Welch t-test: backwardation vs contango returns
bw_mask = df['slope'] > 1.0
ct_mask = df['slope'] <= 0.95
bw_ret = df.loc[bw_mask, 'fwd_ret_1d'].dropna()
ct_ret = df.loc[ct_mask, 'fwd_ret_1d'].dropna()

if len(bw_ret) > 10 and len(ct_ret) > 10:
    t_stat_welch, p_welch = stats.ttest_ind(bw_ret, ct_ret, equal_var=False)
    welch_result = {
        'backwardation_mean': float(bw_ret.mean()),
        'contango_mean': float(ct_ret.mean()),
        'diff_bp': float((bw_ret.mean() - ct_ret.mean()) * 10000),
        't_stat': float(t_stat_welch),
        'p_value': float(p_welch),
        'n_bw': int(len(bw_ret)),
        'n_ct': int(len(ct_ret)),
    }
    print(f"\n  Welch t-test (BW vs Contango 1d returns):")
    print(f"    BW mean: {bw_ret.mean()*10000:.2f}bp, Contango mean: {ct_ret.mean()*10000:.2f}bp")
    print(f"    diff: {(bw_ret.mean() - ct_ret.mean())*10000:.2f}bp, t={t_stat_welch:.3f}, p={p_welch:.4f}")
else:
    welch_result = None

# ============================================================
# 6. PLOT: CONDITIONAL RETURNS
# ============================================================
fig, axes = plt.subplots(1, 3, figsize=(16, 5))

# Box plot of 1d returns by regime
regime_data = []
regime_labels = []
for regime in ['Deep_Contango', 'Contango', 'Normal', 'Mild_BW', 'Moderate_BW', 'Strong_BW']:
    mask = df['regime'] == regime
    rd = df.loc[mask, 'fwd_ret_1d'].dropna()
    if len(rd) > 5:
        regime_data.append(rd.values * 100)
        regime_labels.append(regime.replace('_', '\n'))

ax = axes[0]
bp = ax.boxplot(regime_data, labels=regime_labels, showfliers=False, patch_artist=True)
colors = ['#2ecc71', '#27ae60', '#95a5a6', '#e67e22', '#e74c3c', '#c0392b']
for patch, c in zip(bp['boxes'], colors[:len(bp['boxes'])]):
    patch.set_facecolor(c)
    patch.set_alpha(0.5)
ax.axhline(0, color='black', linestyle='-', linewidth=0.5)
ax.set_title('1-Day Forward Return by Slope Regime')
ax.set_ylabel('Return (%)')
ax.tick_params(axis='x', rotation=45)
ax.grid(True, alpha=0.3)

# Mean returns by regime and horizon
ax = axes[1]
horizons = ['1d', '5d', '22d']
regime_means = {}
for regime in ['Deep_Contango', 'Contango', 'Normal', 'Mild_BW', 'Moderate_BW', 'Strong_BW']:
    if regime in [str(r) for r in conditional_results.keys()]:
        cr = conditional_results[regime]
        regime_means[regime] = [
            cr.get('mean_ret_1d', 0) or 0,
            cr.get('mean_ret_5d', 0) or 0,
            cr.get('mean_ret_22d', 0) or 0,
        ]

x = np.arange(len(horizons))
width = 0.12
for i, (regime, means) in enumerate(regime_means.items()):
    ax.bar(x + i * width, [m * 10000 for m in means], width,
           label=regime.replace('_', ' '), alpha=0.7)

ax.set_xticks(x + width * len(regime_means) / 2)
ax.set_xticklabels(horizons)
ax.set_title('Mean Forward Returns by Regime (bp)')
ax.set_ylabel('Return (bp)')
ax.legend(fontsize=7, ncol=2)
ax.axhline(0, color='black', linewidth=0.5)
ax.grid(True, alpha=0.3)

# Backwardation event study: cumulative returns after backwardation starts
ax = axes[2]
# Find backwardation onset events (slope crosses above 1.0)
bw_start = (df['slope'] > 1.0) & (df['slope'].shift(1) <= 1.0)
bw_events = df.index[bw_start]
print(f"\n  Backwardation onset events: {len(bw_events)}")

cum_rets = []
for event_date in bw_events:
    loc = df.index.get_loc(event_date)
    if loc + 22 < len(df):
        fwd = df['ret_1d'].iloc[loc+1:loc+23].values
        cum_rets.append(np.cumprod(1 + fwd) - 1)

if cum_rets:
    cum_rets_arr = np.array(cum_rets)
    mean_cum = cum_rets_arr.mean(axis=0)
    p25_cum = np.percentile(cum_rets_arr, 25, axis=0)
    p75_cum = np.percentile(cum_rets_arr, 75, axis=0)

    days = np.arange(1, 23)
    ax.plot(days, mean_cum * 100, 'b-', linewidth=2, label='Mean')
    ax.fill_between(days, p25_cum * 100, p75_cum * 100, alpha=0.2, color='blue', label='25-75 pctile')
    ax.axhline(0, color='black', linewidth=0.5)
    ax.set_title(f'SPY Return After Backwardation Onset (n={len(cum_rets)})')
    ax.set_xlabel('Trading Days After Event')
    ax.set_ylabel('Cumulative Return (%)')
    ax.legend()
    ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(OUT_DIR / 'k975_conditional_returns.png', dpi=150, bbox_inches='tight')
plt.close()
print("Saved k975_conditional_returns.png")

# ============================================================
# 7. STRATEGY BACKTESTS
# ============================================================
print("\n" + "="*60)
print("7. STRATEGY BACKTESTS")
print("="*60)

# Strategy 1: Slope-based VT
df['slope_signal'] = df['slope'].shift(1)  # LAG! Use yesterday's slope

def slope_weight(s):
    if pd.isna(s):
        return 1.0
    if s < 0.9:
        return 1.2
    elif s <= 1.0:
        return 1.0
    elif s <= 1.1:
        return 0.7
    else:
        return 0.3

df['w_slope'] = df['slope_signal'].apply(slope_weight)

# Strategy 2: 12/VIX (baseline)
df['vix_signal'] = df['VIX'].shift(1)  # LAG!
df['w_12vix'] = (12.0 / df['vix_signal']).clip(0.0, 1.5)

# Strategy 3: Slope-adjusted 12/VIX
def slope_adj(s):
    if pd.isna(s):
        return 1.0
    if s < 0.9:
        return 1.05
    elif s <= 1.0:
        return 1.0
    elif s <= 1.1:
        return 0.85
    else:
        return 0.65

df['w_slope_12vix'] = df['w_12vix'] * df['slope_signal'].apply(slope_adj)
df['w_slope_12vix'] = df['w_slope_12vix'].clip(0.0, 1.5)

# Strategy 4: Buy & Hold
df['w_bh'] = 1.0

# Calculate returns
strategies = {
    'Buy_Hold': 'w_bh',
    '12/VIX': 'w_12vix',
    'Slope_VT': 'w_slope',
    'Slope_12VIX': 'w_slope_12vix',
}

strategy_results = {}
for name, wcol in strategies.items():
    strat_ret = df[wcol] * df['ret_1d']
    strat_ret = strat_ret.dropna()

    cumret = (1 + strat_ret).cumprod()
    total_ret = float(cumret.iloc[-1] - 1)
    ann_ret = float((1 + total_ret) ** (252 / len(strat_ret)) - 1)
    ann_vol = float(strat_ret.std() * np.sqrt(252))
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # Sortino
    downside = strat_ret[strat_ret < 0]
    sortino_denom = float(downside.std() * np.sqrt(252)) if len(downside) > 0 else ann_vol
    sortino = ann_ret / sortino_denom if sortino_denom > 0 else 0

    # MDD
    peak = cumret.expanding().max()
    drawdown = (cumret / peak) - 1
    mdd = float(drawdown.min())

    # Calmar
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    strategy_results[name] = {
        'ann_return': float(ann_ret),
        'ann_vol': float(ann_vol),
        'sharpe': float(sharpe),
        'sortino': float(sortino),
        'mdd': float(mdd),
        'calmar': float(calmar),
        'total_return': float(total_ret),
        'n_days': int(len(strat_ret)),
    }

    print(f"  {name:15s}: Sharpe={sharpe:.4f}, Sortino={sortino:.4f}, MDD={mdd:.4f}, Ann.Ret={ann_ret:.4f}")

# OOS only (2019+)
print("\n  --- OOS (2019+) ---")
oos_strategy_results = {}
for name, wcol in strategies.items():
    strat_ret = (df[wcol] * df['ret_1d']).loc[oos_mask].dropna()
    if len(strat_ret) < 50:
        continue

    cumret = (1 + strat_ret).cumprod()
    total_ret = float(cumret.iloc[-1] - 1)
    ann_ret = float((1 + total_ret) ** (252 / len(strat_ret)) - 1)
    ann_vol = float(strat_ret.std() * np.sqrt(252))
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    peak = cumret.expanding().max()
    drawdown = (cumret / peak) - 1
    mdd = float(drawdown.min())

    oos_strategy_results[name] = {
        'ann_return': float(ann_ret),
        'ann_vol': float(ann_vol),
        'sharpe': float(sharpe),
        'mdd': float(mdd),
    }

    print(f"  {name:15s}: Sharpe={sharpe:.4f}, MDD={mdd:.4f}, Ann.Ret={ann_ret:.4f}")

# DM test: Slope_VT vs 12/VIX
strat_12vix_ret = (df['w_12vix'] * df['ret_1d']).dropna()
strat_slope_ret = (df['w_slope'] * df['ret_1d']).dropna()
strat_slope12_ret = (df['w_slope_12vix'] * df['ret_1d']).dropna()

# Align
common_idx = strat_12vix_ret.index.intersection(strat_slope_ret.index)
e1 = (strat_12vix_ret.loc[common_idx] - strat_12vix_ret.loc[common_idx].mean())**2
e2 = (strat_slope_ret.loc[common_idx] - strat_slope_ret.loc[common_idx].mean())**2
d = e1 - e2
if d.std() > 0:
    dm_strat = float(d.mean() / (d.std() / np.sqrt(len(d))))
    dm_strat_p = float(2 * (1 - stats.norm.cdf(abs(dm_strat))))
else:
    dm_strat = 0
    dm_strat_p = 1.0

print(f"\n  DM test (Slope_VT vs 12/VIX): stat={dm_strat:.3f}, p={dm_strat_p:.4f}")

# ============================================================
# 8. PLOT: STRATEGY COMPARISON
# ============================================================
fig, axes = plt.subplots(2, 2, figsize=(14, 10))

# Cumulative returns
ax = axes[0, 0]
for name, wcol in strategies.items():
    strat_ret = df[wcol] * df['ret_1d']
    cumret = (1 + strat_ret.dropna()).cumprod()
    ax.plot(cumret.index, cumret.values, label=name, linewidth=1)
ax.set_title('Cumulative Returns (Full Sample)')
ax.set_ylabel('Growth of $1')
ax.legend()
ax.grid(True, alpha=0.3)
ax.set_yscale('log')

# OOS cumulative returns
ax = axes[0, 1]
for name, wcol in strategies.items():
    strat_ret = (df[wcol] * df['ret_1d']).loc[oos_mask].dropna()
    if len(strat_ret) > 0:
        cumret = (1 + strat_ret).cumprod()
        ax.plot(cumret.index, cumret.values, label=name, linewidth=1)
ax.set_title('Cumulative Returns (OOS: 2019+)')
ax.set_ylabel('Growth of $1')
ax.legend()
ax.grid(True, alpha=0.3)

# Rolling Sharpe
ax = axes[1, 0]
window = 252
for name, wcol in strategies.items():
    strat_ret = df[wcol] * df['ret_1d']
    rolling_sharpe = (strat_ret.rolling(window).mean() / strat_ret.rolling(window).std()) * np.sqrt(252)
    ax.plot(rolling_sharpe.dropna().index, rolling_sharpe.dropna().values, label=name, linewidth=0.8)
ax.axhline(0, color='black', linewidth=0.5)
ax.set_title('Rolling 252-Day Sharpe Ratio')
ax.set_ylabel('Sharpe')
ax.legend()
ax.grid(True, alpha=0.3)

# Weight time series
ax = axes[1, 1]
ax.plot(df.index, df['w_slope'], label='Slope VT', alpha=0.7, linewidth=0.5)
ax.plot(df.index, df['w_12vix'], label='12/VIX', alpha=0.7, linewidth=0.5)
ax.plot(df.index, df['w_slope_12vix'], label='Slope×12/VIX', alpha=0.7, linewidth=0.5)
ax.set_title('Strategy Weights Over Time')
ax.set_ylabel('Weight')
ax.legend()
ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(OUT_DIR / 'k975_strategy_comparison.png', dpi=150, bbox_inches='tight')
plt.close()
print("Saved k975_strategy_comparison.png")

# ============================================================
# 9. COVID & 2022 BEAR MARKET ANALYSIS
# ============================================================
print("\n" + "="*60)
print("9. EVENT ANALYSIS")
print("="*60)

events = {
    'COVID_2020': ('2020-02-01', '2020-06-01'),
    'Bear_2022': ('2022-01-01', '2022-10-31'),
    'VIX_spike_Aug2024': ('2024-07-15', '2024-09-15'),
}

event_analysis = {}
for event_name, (start, end) in events.items():
    mask = (df.index >= start) & (df.index <= end)
    event_df = df.loc[mask]
    if len(event_df) < 5:
        continue

    event_analysis[event_name] = {
        'n_days': int(len(event_df)),
        'slope_mean': float(event_df['slope'].mean()),
        'slope_max': float(event_df['slope'].max()),
        'slope_min': float(event_df['slope'].min()),
        'vix_mean': float(event_df['VIX'].mean()),
        'vix_max': float(event_df['VIX'].max()),
        'backwardation_pct': float((event_df['slope'] > 1.0).mean() * 100),
        'spy_return': float(event_df['ret_1d'].sum()),
    }

    ea = event_analysis[event_name]
    print(f"  {event_name}:")
    print(f"    Slope: mean={ea['slope_mean']:.4f}, max={ea['slope_max']:.4f}")
    print(f"    VIX: mean={ea['vix_mean']:.1f}, max={ea['vix_max']:.1f}")
    print(f"    Backwardation: {ea['backwardation_pct']:.1f}% of days")

# ============================================================
# 10. BACKWARDATION MEAN REVERSION TEST
# ============================================================
print("\n" + "="*60)
print("10. BACKWARDATION MEAN REVERSION TEST")
print("="*60)

# When backwardation > 1.1, what happens to VIX in next 5/22 days?
bw_strong = df['slope'] > 1.1
bw_dates = df.index[bw_strong]

vix_change_5d = []
vix_change_22d = []
for d in bw_dates:
    loc = df.index.get_loc(d)
    if loc + 22 < len(df):
        vix_now = df['VIX'].iloc[loc]
        vix_5 = df['VIX'].iloc[loc + 5]
        vix_22 = df['VIX'].iloc[loc + 22]
        vix_change_5d.append((vix_5 - vix_now) / vix_now)
        vix_change_22d.append((vix_22 - vix_now) / vix_now)

if vix_change_5d:
    vc5 = np.array(vix_change_5d)
    vc22 = np.array(vix_change_22d)

    mr_result = {
        'n_events': len(vc5),
        'vix_change_5d_mean': float(vc5.mean()),
        'vix_change_5d_median': float(np.median(vc5)),
        'vix_change_5d_pct_decline': float((vc5 < 0).mean() * 100),
        'vix_change_22d_mean': float(vc22.mean()),
        'vix_change_22d_median': float(np.median(vc22)),
        'vix_change_22d_pct_decline': float((vc22 < 0).mean() * 100),
    }

    # t-test: is mean VIX change significantly < 0?
    t5, p5 = stats.ttest_1samp(vc5, 0)
    t22, p22 = stats.ttest_1samp(vc22, 0)
    mr_result['t_stat_5d'] = float(t5)
    mr_result['p_value_5d'] = float(p5)
    mr_result['t_stat_22d'] = float(t22)
    mr_result['p_value_22d'] = float(p22)

    print(f"  Strong backwardation (slope > 1.1): {len(vc5)} events")
    print(f"    5-day VIX change: mean={vc5.mean()*100:.2f}%, median={np.median(vc5)*100:.2f}%, "
          f"{(vc5 < 0).mean()*100:.0f}% decline, t={t5:.2f}, p={p5:.4f}")
    print(f"    22-day VIX change: mean={vc22.mean()*100:.2f}%, median={np.median(vc22)*100:.2f}%, "
          f"{(vc22 < 0).mean()*100:.0f}% decline, t={t22:.2f}, p={p22:.4f}")
else:
    mr_result = None
    print("  No strong backwardation events found")

# ============================================================
# 11. COMPILE RESULTS
# ============================================================
print("\n" + "="*60)
print("11. COMPILING RESULTS")
print("="*60)

results = {
    'experiment_id': 'K975',
    'title': 'VIX Term Structure Slope — Predictive Power and Strategy Analysis',
    'timestamp': datetime.now().isoformat(),
    'data_source': 'yfinance',
    'data_period': f"{df.index[0].date()} to {df.index[-1].date()}",
    'n_observations': int(len(df)),
    'slope_type': slope_label,
    'seed': 42,

    'descriptive_statistics': desc,
    'regression_results': regression_results,
    'conditional_returns': conditional_results,
    'welch_test_bw_vs_contango': welch_result,
    'strategy_performance_full': strategy_results,
    'strategy_performance_oos': oos_strategy_results,
    'dm_test_slope_vs_12vix': {
        'dm_stat': dm_strat,
        'p_value': dm_strat_p,
    },
    'event_analysis': event_analysis,
    'mean_reversion_test': mr_result,

    'conclusions': {},
}

# Fill conclusions
c = results['conclusions']

# 1. Incremental predictive power?
if 'fwd_rvol_22d' in regression_results:
    rr = regression_results['fwd_rvol_22d']
    inc_r2 = rr['slope_plus_vix']['incremental_r2_oos']
    c['incremental_vol_prediction'] = {
        'finding': f"Slope provides {'meaningful' if inc_r2 > 0.005 else 'minimal'} incremental R² over VIX for 22d vol prediction",
        'oos_incremental_r2': inc_r2,
        'significant': bool(rr.get('dm_test_vs_vix', {}).get('significant_5pct', False)),
    }

# 2. Slope-based strategy vs 12/VIX
slope_sharpe = strategy_results.get('Slope_VT', {}).get('sharpe', 0)
vix_sharpe = strategy_results.get('12/VIX', {}).get('sharpe', 0)
combo_sharpe = strategy_results.get('Slope_12VIX', {}).get('sharpe', 0)
c['strategy_comparison'] = {
    'slope_vt_sharpe': slope_sharpe,
    'vix_12_sharpe': vix_sharpe,
    'slope_12vix_sharpe': combo_sharpe,
    'slope_beats_12vix': slope_sharpe > vix_sharpe,
    'combo_beats_12vix': combo_sharpe > vix_sharpe,
    'finding': (
        f"Slope VT Sharpe={slope_sharpe:.4f} vs 12/VIX Sharpe={vix_sharpe:.4f}. "
        f"Combination Sharpe={combo_sharpe:.4f}. "
        f"{'Slope adds value' if combo_sharpe > vix_sharpe else 'Slope does not improve'} over 12/VIX."
    ),
}

# 3. Mean reversion
if mr_result:
    c['mean_reversion'] = {
        'finding': (
            f"After strong backwardation, VIX declines in {mr_result['vix_change_22d_pct_decline']:.0f}% "
            f"of cases over 22 days (mean change: {mr_result['vix_change_22d_mean']*100:.1f}%). "
            f"{'Statistically significant' if mr_result['p_value_22d'] < 0.05 else 'Not statistically significant'} "
            f"(p={mr_result['p_value_22d']:.4f})."
        ),
    }

# Save results
results_path = OUT_DIR / 'k975_vix_slope_results.json'
with open(results_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\nSaved results to {results_path}")

# ============================================================
# SUMMARY
# ============================================================
print("\n" + "="*60)
print("SUMMARY")
print("="*60)
print(f"Slope type: {slope_label}")
print(f"Data: {df.index[0].date()} to {df.index[-1].date()} ({len(df)} obs)")
print(f"Backwardation frequency: {backwardation_pct:.1f}%")
print(f"\nStrategy Sharpes (full sample):")
for name, sr in strategy_results.items():
    print(f"  {name:15s}: {sr['sharpe']:.4f}")
print(f"\nConclusions:")
for key, val in c.items():
    if 'finding' in val:
        print(f"  {key}: {val['finding']}")

print("\nDone!")
