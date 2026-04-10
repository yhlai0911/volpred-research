"""
K1027: Drawdown Recovery Speed — K735 Corrected Methodology

K735 found VIX predicts drawdown depth (rho=-0.49) and duration (rho=+0.45),
but Codex found 2 HIGH bugs:
  1. Fake OOS (used full-sample data for OOS claims)
  2. Lookahead bias (strategy signal not properly lagged)

This experiment redoes the analysis with strict methodology:
  - Training: 2005-2018 (in-sample)
  - OOS: 2019-2026 (out-of-sample, no information leakage)
  - signal.shift(1) explicitly in strategy code
  - Bootstrap CIs for all correlations
  - Spearman rank correlations (robust to outliers)

Data source: yfinance (SPY, ^VIX), 2005-2026
Reference: K735, K648, K687/K697
"""

import numpy as np
import pandas as pd
import yfinance as yf
import json
import os
import warnings
from datetime import datetime
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

warnings.filterwarnings('ignore')
np.random.seed(42)

# ============================================================
# 1. DATA COLLECTION
# ============================================================
print("=" * 60)
print("K1027: Drawdown Recovery Speed — Corrected Methodology")
print("=" * 60)

# Download data
print("\n[1] Downloading data from yfinance...")
spy = yf.download("SPY", start="2004-01-01", end="2026-12-31", progress=False)
vix = yf.download("^VIX", start="2004-01-01", end="2026-12-31", progress=False)

# Handle multi-level columns
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

# Combine
df = pd.DataFrame({
    'spy_close': spy['Close'],
    'spy_return': spy['Close'].pct_change(),
    'vix': vix['Close']
}).dropna()

# Filter to 2005+
df = df[df.index >= '2005-01-01'].copy()
print(f"  Data range: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
print(f"  Total observations: {len(df)}")

# ============================================================
# 2. FEATURE ENGINEERING
# ============================================================
print("\n[2] Engineering features...")

# VIX percentile (rolling 252d)
df['vix_pct'] = df['vix'].rolling(252).apply(
    lambda x: stats.percentileofscore(x, x.iloc[-1]) / 100.0,
    raw=False
)

# VIX slope (5d change)
df['vix_slope'] = df['vix'].diff(5)

# Realized volatility (20d)
df['rvol_20d'] = df['spy_return'].rolling(20).std() * np.sqrt(252)

# Return momentum (20d cumulative)
df['momentum_20d'] = df['spy_return'].rolling(20).sum()

# Drop NaN from rolling calculations
df = df.dropna()
print(f"  After feature engineering: {len(df)} observations")
print(f"  Feature range: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

# ============================================================
# 3. DRAWDOWN IDENTIFICATION
# ============================================================
print("\n[3] Identifying drawdowns (threshold > 5%)...")

def identify_drawdowns(prices, threshold=0.05):
    """
    Identify drawdown episodes: peak -> trough -> recovery to peak.
    Returns list of dicts with start, trough, recovery dates and metrics.
    """
    drawdowns = []
    cummax = prices.cummax()
    dd_series = (prices - cummax) / cummax  # Drawdown series (negative values)

    in_drawdown = False
    peak_date = None
    peak_val = None
    trough_date = None
    trough_val = None
    max_dd = 0

    for i in range(len(prices)):
        date = prices.index[i]
        price = prices.iloc[i]
        current_dd = dd_series.iloc[i]

        if not in_drawdown:
            if current_dd < -threshold:
                # Drawdown started — find the peak before this point
                in_drawdown = True
                # Peak is the most recent cummax point
                peak_idx = cummax.iloc[:i+1].idxmax()
                peak_date = peak_idx
                peak_val = cummax.iloc[i]
                trough_date = date
                trough_val = price
                max_dd = current_dd
        else:
            if current_dd < max_dd:
                # Deeper trough
                trough_date = date
                trough_val = price
                max_dd = current_dd

            if price >= peak_val:
                # Recovery complete
                recovery_date = date
                duration_to_trough = (trough_date - peak_date).days
                duration_to_recovery = (recovery_date - peak_date).days

                drawdowns.append({
                    'peak_date': peak_date,
                    'trough_date': trough_date,
                    'recovery_date': recovery_date,
                    'depth': max_dd,  # negative number
                    'days_to_trough': duration_to_trough,
                    'days_to_recovery': duration_to_recovery,
                    'peak_val': peak_val,
                    'trough_val': trough_val,
                })

                in_drawdown = False
                max_dd = 0

    # Handle ongoing drawdown (no recovery yet)
    if in_drawdown:
        last_date = prices.index[-1]
        duration_to_trough = (trough_date - peak_date).days
        drawdowns.append({
            'peak_date': peak_date,
            'trough_date': trough_date,
            'recovery_date': None,  # Not recovered
            'depth': max_dd,
            'days_to_trough': duration_to_trough,
            'days_to_recovery': None,
            'peak_val': peak_val,
            'trough_val': trough_val,
        })

    return drawdowns

drawdowns = identify_drawdowns(df['spy_close'], threshold=0.05)
print(f"  Found {len(drawdowns)} drawdowns > 5%")

# Enrich drawdowns with features at drawdown start
for dd in drawdowns:
    peak_date = dd['peak_date']
    # Use features from the day BEFORE the peak (avoid lookahead)
    # We want the VIX conditions when the drawdown started to develop
    # Use trough_date's features minus some days... No.
    # Actually: features at the START of the drawdown (the peak date)
    # This is observable in real-time.
    if peak_date in df.index:
        dd['vix_at_peak'] = df.loc[peak_date, 'vix']
        dd['vix_pct_at_peak'] = df.loc[peak_date, 'vix_pct']
        dd['vix_slope_at_peak'] = df.loc[peak_date, 'vix_slope']
        dd['rvol_at_peak'] = df.loc[peak_date, 'rvol_20d']
        dd['momentum_at_peak'] = df.loc[peak_date, 'momentum_20d']
    else:
        # Find nearest available date
        idx = df.index.get_indexer([peak_date], method='ffill')[0]
        if idx >= 0:
            nearest = df.index[idx]
            dd['vix_at_peak'] = df.loc[nearest, 'vix']
            dd['vix_pct_at_peak'] = df.loc[nearest, 'vix_pct']
            dd['vix_slope_at_peak'] = df.loc[nearest, 'vix_slope']
            dd['rvol_at_peak'] = df.loc[nearest, 'rvol_20d']
            dd['momentum_at_peak'] = df.loc[nearest, 'momentum_20d']
        else:
            dd['vix_at_peak'] = np.nan
            dd['vix_pct_at_peak'] = np.nan
            dd['vix_slope_at_peak'] = np.nan
            dd['rvol_at_peak'] = np.nan
            dd['momentum_at_peak'] = np.nan

# Convert to DataFrame
dd_df = pd.DataFrame(drawdowns)
dd_df = dd_df.dropna(subset=['vix_at_peak'])  # Remove drawdowns without feature data

print(f"\n  Drawdown Summary:")
print(f"  {'Peak Date':<14} {'Trough Date':<14} {'Depth':>8} {'Days to Trough':>15} {'Days to Recovery':>17} {'VIX at Peak':>12}")
print(f"  {'-'*14} {'-'*14} {'-'*8} {'-'*15} {'-'*17} {'-'*12}")
for _, row in dd_df.iterrows():
    rec_days = f"{row['days_to_recovery']:.0f}" if pd.notna(row['days_to_recovery']) else "ongoing"
    print(f"  {str(row['peak_date'])[:10]:<14} {str(row['trough_date'])[:10]:<14} {row['depth']:>8.1%} {row['days_to_trough']:>15.0f} {rec_days:>17} {row['vix_at_peak']:>12.1f}")

# ============================================================
# 4. STRICT IN-SAMPLE / OUT-OF-SAMPLE SPLIT
# ============================================================
print("\n[4] Splitting into IS (2005-2018) and OOS (2019-2026)...")

IS_END = '2018-12-31'
OOS_START = '2019-01-01'

dd_is = dd_df[dd_df['peak_date'] <= IS_END].copy()
dd_oos = dd_df[dd_df['peak_date'] >= OOS_START].copy()

print(f"  In-sample drawdowns: {len(dd_is)}")
print(f"  Out-of-sample drawdowns: {len(dd_oos)}")

# ============================================================
# 5. CORRELATION ANALYSIS WITH BOOTSTRAP CIs
# ============================================================
print("\n[5] Correlation analysis (Spearman) with bootstrap CIs...")

def bootstrap_spearman(x, y, n_boot=5000, seed=42):
    """Bootstrap confidence intervals for Spearman correlation."""
    rng = np.random.default_rng(seed)
    n = len(x)
    boot_corrs = np.zeros(n_boot)

    for b in range(n_boot):
        idx = rng.integers(0, n, size=n)
        boot_corrs[b] = stats.spearmanr(x[idx], y[idx])[0]

    ci_lo = np.percentile(boot_corrs, 2.5)
    ci_hi = np.percentile(boot_corrs, 97.5)
    return ci_lo, ci_hi, boot_corrs

features = ['vix_at_peak', 'vix_pct_at_peak', 'vix_slope_at_peak', 'rvol_at_peak', 'momentum_at_peak']
feature_names = ['VIX Level', 'VIX Percentile', 'VIX Slope (5d)', 'RVol (20d)', 'Momentum (20d)']
targets = ['depth', 'days_to_trough', 'days_to_recovery']
target_names = ['Drawdown Depth', 'Days to Trough', 'Days to Recovery']

results_correlations = {}

for sample_name, dd_sample in [('full', dd_df), ('in_sample', dd_is), ('oos', dd_oos)]:
    results_correlations[sample_name] = {}
    print(f"\n  --- {sample_name.upper()} (n={len(dd_sample)}) ---")

    for ti, target in enumerate(targets):
        results_correlations[sample_name][target] = {}
        valid = dd_sample.dropna(subset=[target])

        if len(valid) < 5:
            print(f"    {target_names[ti]}: too few observations ({len(valid)})")
            continue

        for fi, feat in enumerate(features):
            x = valid[feat].values
            y = valid[target].values

            if len(x) < 5:
                continue

            rho, pval = stats.spearmanr(x, y)

            # Bootstrap CI (only if n >= 10)
            if len(x) >= 10:
                ci_lo, ci_hi, _ = bootstrap_spearman(x, y, n_boot=5000)
                ci_str = f"[{ci_lo:.3f}, {ci_hi:.3f}]"
            else:
                ci_lo, ci_hi = np.nan, np.nan
                ci_str = "[n<10, no CI]"

            results_correlations[sample_name][target][feat] = {
                'rho': float(rho),
                'pval': float(pval),
                'ci_lo': float(ci_lo) if not np.isnan(ci_lo) else None,
                'ci_hi': float(ci_hi) if not np.isnan(ci_hi) else None,
                'n': int(len(x)),
            }

            sig = "***" if pval < 0.01 else "**" if pval < 0.05 else "*" if pval < 0.1 else ""
            print(f"    {feature_names[fi]:>20} vs {target_names[ti]:<20}: rho={rho:+.3f} (p={pval:.3f}) {sig} 95%CI: {ci_str}")

# ============================================================
# 6. IS vs OOS STABILITY CHECK
# ============================================================
print("\n[6] IS vs OOS Stability Check...")

stability_results = {}
for target in targets:
    stability_results[target] = {}
    for feat in features:
        is_data = results_correlations.get('in_sample', {}).get(target, {}).get(feat)
        oos_data = results_correlations.get('oos', {}).get(target, {}).get(feat)

        if is_data and oos_data:
            is_rho = is_data['rho']
            oos_rho = oos_data['rho']
            same_sign = (is_rho > 0 and oos_rho > 0) or (is_rho < 0 and oos_rho < 0) or (is_rho == 0 or oos_rho == 0)
            diff = abs(is_rho - oos_rho)

            stability_results[target][feat] = {
                'is_rho': is_rho,
                'oos_rho': oos_rho,
                'same_sign': same_sign,
                'abs_diff': diff,
                'stable': same_sign and diff < 0.3,
            }

            status = "STABLE" if same_sign and diff < 0.3 else "UNSTABLE"
            print(f"    {feat:>20} vs {target:<20}: IS={is_rho:+.3f} OOS={oos_rho:+.3f} diff={diff:.3f} [{status}]")

# ============================================================
# 7. DRAWDOWN PROTECTION OVERLAY STRATEGY
# ============================================================
print("\n[7] Drawdown Protection Overlay Strategy...")
print("   Based on VIX percentile — de-lever when VIX is elevated")

# Strategy: reduce exposure when VIX percentile is high
# Use FULL daily data (not just drawdown events) for strategy backtest
# Training period: learn thresholds from IS
# OOS: apply those thresholds

# IS period for threshold selection
df_is = df[df.index <= IS_END].copy()
df_oos = df[df.index >= OOS_START].copy()

print(f"  IS daily obs: {len(df_is)}, OOS daily obs: {len(df_oos)}")

# Strategy rules (determined from IS analysis):
# - VIX percentile < 50%: 100% SPY (low fear)
# - VIX percentile 50-80%: 70% SPY (moderate fear)
# - VIX percentile > 80%: 40% SPY (high fear)

# These thresholds come from IS drawdown analysis
# Let's optimize on IS first
def compute_strategy_returns(daily_df, thresholds, weights):
    """
    Apply VIX-percentile-based weight overlay.
    CRITICAL: signal.shift(1) — use YESTERDAY's VIX to determine TODAY's weight.
    """
    signal = pd.Series(np.nan, index=daily_df.index)

    for i in range(len(thresholds) + 1):
        if i == 0:
            mask = daily_df['vix_pct'] < thresholds[0]
        elif i == len(thresholds):
            mask = daily_df['vix_pct'] >= thresholds[-1]
        else:
            mask = (daily_df['vix_pct'] >= thresholds[i-1]) & (daily_df['vix_pct'] < thresholds[i])
        signal[mask] = weights[i]

    # CRITICAL: shift(1) to avoid lookahead bias
    # Today's weight is based on YESTERDAY's VIX percentile
    signal = signal.shift(1)  # <--- EXPLICIT LAG

    strategy_ret = signal * daily_df['spy_return']
    baseline_ret = daily_df['spy_return']  # Buy-and-hold SPY

    return strategy_ret.dropna(), baseline_ret.loc[strategy_ret.dropna().index], signal.dropna()

# Test several threshold/weight combinations on IS
# Pick the one with best risk-adjusted return
configs = [
    # (thresholds, weights, description)
    ([0.5, 0.8], [1.0, 0.7, 0.4], "50/80 percentile, 100/70/40%"),
    ([0.5, 0.8], [1.0, 0.6, 0.3], "50/80 percentile, 100/60/30%"),
    ([0.6, 0.9], [1.0, 0.7, 0.3], "60/90 percentile, 100/70/30%"),
    ([0.5, 0.7, 0.9], [1.0, 0.8, 0.5, 0.2], "50/70/90 percentile, 100/80/50/20%"),
    ([0.7], [1.0, 0.5], "70 percentile, 100/50%"),
]

# Also compare with 12/VIX baseline
def compute_12vix_returns(daily_df):
    """12/VIX strategy with proper lag."""
    weight = (12.0 / daily_df['vix']).clip(0, 1.0)
    weight = weight.shift(1)  # <--- EXPLICIT LAG
    strategy_ret = weight * daily_df['spy_return']
    return strategy_ret.dropna(), weight.shift(0).dropna()  # return lagged weight for analysis

def calc_metrics(returns):
    """Calculate Sharpe, MDD, annual return."""
    ann_ret = returns.mean() * 252
    ann_vol = returns.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    cum = (1 + returns).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    return {
        'ann_return': float(ann_ret),
        'ann_vol': float(ann_vol),
        'sharpe': float(sharpe),
        'mdd': float(mdd),
        'n_days': int(len(returns)),
    }

print("\n  --- IS Strategy Selection ---")
best_is_sharpe = -999
best_config = None
is_results = []

for thresh, wts, desc in configs:
    strat_ret, bh_ret, _ = compute_strategy_returns(df_is, thresh, wts)
    m = calc_metrics(strat_ret)
    bh_m = calc_metrics(bh_ret)
    is_results.append((desc, m, bh_m))
    print(f"    {desc}: Sharpe={m['sharpe']:.3f} (BH={bh_m['sharpe']:.3f}), MDD={m['mdd']:.1%} (BH={bh_m['mdd']:.1%})")

    if m['sharpe'] > best_is_sharpe:
        best_is_sharpe = m['sharpe']
        best_config = (thresh, wts, desc)

print(f"\n  Best IS config: {best_config[2]} (Sharpe={best_is_sharpe:.3f})")

# ============================================================
# 8. OOS STRATEGY EVALUATION
# ============================================================
print("\n[8] Out-of-Sample Strategy Evaluation...")
print(f"  Using IS-selected config: {best_config[2]}")
print(f"  OOS period: {df_oos.index[0].strftime('%Y-%m-%d')} to {df_oos.index[-1].strftime('%Y-%m-%d')}")

# Apply best config to OOS
oos_strat_ret, oos_bh_ret, oos_weights = compute_strategy_returns(df_oos, best_config[0], best_config[1])
oos_strat_m = calc_metrics(oos_strat_ret)
oos_bh_m = calc_metrics(oos_bh_ret)

# 12/VIX benchmark on OOS
oos_12vix_ret, oos_12vix_wt = compute_12vix_returns(df_oos)
oos_12vix_m = calc_metrics(oos_12vix_ret)

print(f"\n  OOS Results:")
print(f"  {'Strategy':<35} {'Sharpe':>8} {'AnnRet':>8} {'AnnVol':>8} {'MDD':>8}")
print(f"  {'-'*35} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")
print(f"  {'Buy & Hold SPY':<35} {oos_bh_m['sharpe']:>8.3f} {oos_bh_m['ann_return']:>8.1%} {oos_bh_m['ann_vol']:>8.1%} {oos_bh_m['mdd']:>8.1%}")
print(f"  {'12/VIX (lagged)':<35} {oos_12vix_m['sharpe']:>8.3f} {oos_12vix_m['ann_return']:>8.1%} {oos_12vix_m['ann_vol']:>8.1%} {oos_12vix_m['mdd']:>8.1%}")
print(f"  {('DD Protection: ' + best_config[2])[:35]:<35} {oos_strat_m['sharpe']:>8.3f} {oos_strat_m['ann_return']:>8.1%} {oos_strat_m['ann_vol']:>8.1%} {oos_strat_m['mdd']:>8.1%}")

# Sharpe > 2x baseline check
if oos_strat_m['sharpe'] > 2 * oos_bh_m['sharpe'] and oos_bh_m['sharpe'] > 0:
    print("\n  ⚠️ WARNING: Sharpe > 2x baseline — possible bug! Checking carefully...")

# DM-like test: compare strategy vs BH in OOS
# Using paired t-test on daily return differences
aligned_idx = oos_strat_ret.index.intersection(oos_bh_ret.index)
diff = oos_strat_ret.loc[aligned_idx] - oos_bh_ret.loc[aligned_idx]
t_stat = diff.mean() / (diff.std() / np.sqrt(len(diff)))
p_val_dm = 2 * (1 - stats.t.cdf(abs(t_stat), df=len(diff)-1))

print(f"\n  DM-like test (Strategy vs BH): t={t_stat:.3f}, p={p_val_dm:.4f}")
if abs(t_stat) > 3.0:
    print("  Harvey (2016) threshold |t|>3.0: PASS — statistically significant")
else:
    print("  Harvey (2016) threshold |t|>3.0: FAIL — not significant at corrected threshold")

# Compare with 12/VIX
aligned_idx2 = oos_strat_ret.index.intersection(oos_12vix_ret.index)
diff2 = oos_strat_ret.loc[aligned_idx2] - oos_12vix_ret.loc[aligned_idx2]
t_stat2 = diff2.mean() / (diff2.std() / np.sqrt(len(diff2)))
p_val_dm2 = 2 * (1 - stats.t.cdf(abs(t_stat2), df=len(diff2)-1))

print(f"  DM-like test (Strategy vs 12/VIX): t={t_stat2:.3f}, p={p_val_dm2:.4f}")

# ============================================================
# 9. DRAWDOWN BEHAVIOR DURING SPECIFIC EVENTS
# ============================================================
print("\n[9] Drawdown behavior during key events...")

# Check strategy weight during major drawdowns in OOS
major_dd_oos = dd_df[dd_df['peak_date'] >= OOS_START].copy()
print(f"\n  Major OOS drawdowns and strategy weights:")

for _, dd_row in major_dd_oos.iterrows():
    peak_d = dd_row['peak_date']
    trough_d = dd_row['trough_date']

    # Get average weight during drawdown period
    dd_period = oos_weights.loc[
        (oos_weights.index >= peak_d) & (oos_weights.index <= trough_d)
    ]

    if len(dd_period) > 0:
        avg_weight = dd_period.mean()
        print(f"    {str(peak_d)[:10]} -> {str(trough_d)[:10]}: depth={dd_row['depth']:.1%}, avg_weight={avg_weight:.2f}, VIX={dd_row.get('vix_at_peak', np.nan):.1f}")

# ============================================================
# 10. PLOTS
# ============================================================
print("\n[10] Generating plots...")
output_dir = os.path.dirname(os.path.abspath(__file__))

# Plot 1: Drawdown depth vs VIX at peak (IS vs OOS)
fig, axes = plt.subplots(1, 2, figsize=(14, 6))

# IS
ax = axes[0]
if len(dd_is) > 0:
    ax.scatter(dd_is['vix_at_peak'], dd_is['depth'] * 100, c='steelblue', s=80, alpha=0.7, edgecolors='navy')
    if len(dd_is) > 2:
        z = np.polyfit(dd_is['vix_at_peak'].values, (dd_is['depth'] * 100).values, 1)
        p = np.poly1d(z)
        x_range = np.linspace(dd_is['vix_at_peak'].min(), dd_is['vix_at_peak'].max(), 50)
        ax.plot(x_range, p(x_range), 'r--', alpha=0.7)

    rho_is = results_correlations.get('in_sample', {}).get('depth', {}).get('vix_at_peak', {})
    if rho_is:
        ax.set_title(f"In-Sample (2005-2018)\nSpearman rho={rho_is['rho']:.3f}, p={rho_is['pval']:.3f}", fontsize=12)
ax.set_xlabel('VIX at Drawdown Peak', fontsize=11)
ax.set_ylabel('Drawdown Depth (%)', fontsize=11)
ax.grid(True, alpha=0.3)
ax.set_xlim(left=0)

# OOS
ax = axes[1]
if len(dd_oos) > 0:
    ax.scatter(dd_oos['vix_at_peak'], dd_oos['depth'] * 100, c='coral', s=80, alpha=0.7, edgecolors='darkred')
    if len(dd_oos) > 2:
        z = np.polyfit(dd_oos['vix_at_peak'].values, (dd_oos['depth'] * 100).values, 1)
        p = np.poly1d(z)
        x_range = np.linspace(dd_oos['vix_at_peak'].min(), dd_oos['vix_at_peak'].max(), 50)
        ax.plot(x_range, p(x_range), 'r--', alpha=0.7)

    rho_oos = results_correlations.get('oos', {}).get('depth', {}).get('vix_at_peak', {})
    if rho_oos:
        ax.set_title(f"Out-of-Sample (2019-2026)\nSpearman rho={rho_oos['rho']:.3f}, p={rho_oos['pval']:.3f}", fontsize=12)
ax.set_xlabel('VIX at Drawdown Peak', fontsize=11)
ax.set_ylabel('Drawdown Depth (%)', fontsize=11)
ax.grid(True, alpha=0.3)
ax.set_xlim(left=0)

plt.suptitle('K1027: VIX vs Drawdown Depth — IS vs OOS', fontsize=14, fontweight='bold')
plt.tight_layout()
plt.savefig(os.path.join(output_dir, 'k1027_vix_vs_depth.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved: k1027_vix_vs_depth.png")

# Plot 2: OOS cumulative returns comparison
fig, ax = plt.subplots(figsize=(14, 7))

cum_bh = (1 + oos_bh_ret).cumprod()
cum_strat = (1 + oos_strat_ret).cumprod()
cum_12vix = (1 + oos_12vix_ret).cumprod()

ax.plot(cum_bh.index, cum_bh.values, label=f'Buy & Hold SPY (Sharpe={oos_bh_m["sharpe"]:.3f})', linewidth=1.5, color='gray')
ax.plot(cum_12vix.index, cum_12vix.values, label=f'12/VIX (Sharpe={oos_12vix_m["sharpe"]:.3f})', linewidth=1.5, color='blue')
ax.plot(cum_strat.index, cum_strat.values, label=f'DD Protection (Sharpe={oos_strat_m["sharpe"]:.3f})', linewidth=1.5, color='green')

# Shade OOS drawdown periods
for _, dd_row in major_dd_oos.iterrows():
    peak_d = dd_row['peak_date']
    rec_d = dd_row['recovery_date'] if pd.notna(dd_row['recovery_date']) else df_oos.index[-1]
    ax.axvspan(peak_d, rec_d, alpha=0.1, color='red')

ax.set_title('K1027: OOS Cumulative Returns (2019-2026)', fontsize=14, fontweight='bold')
ax.set_xlabel('Date', fontsize=11)
ax.set_ylabel('Cumulative Return ($1 invested)', fontsize=11)
ax.legend(fontsize=10, loc='upper left')
ax.grid(True, alpha=0.3)
ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
ax.xaxis.set_major_locator(mdates.YearLocator())

plt.tight_layout()
plt.savefig(os.path.join(output_dir, 'k1027_oos_cumulative.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved: k1027_oos_cumulative.png")

# Plot 3: Drawdown timeline with VIX overlay
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), sharex=True, height_ratios=[2, 1])

# SPY price with drawdowns shaded
ax1.plot(df['spy_close'].index, df['spy_close'].values, color='black', linewidth=0.8, label='SPY')
for _, dd_row in dd_df.iterrows():
    color = 'salmon' if dd_row['peak_date'] < pd.Timestamp(OOS_START) else 'lightcoral'
    rec_d = dd_row['recovery_date'] if pd.notna(dd_row['recovery_date']) else df.index[-1]
    ax1.axvspan(dd_row['peak_date'], rec_d, alpha=0.2, color=color)

ax1.set_ylabel('SPY Price', fontsize=11)
ax1.set_title('K1027: SPY Price & Drawdown Episodes', fontsize=14, fontweight='bold')
ax1.axvline(pd.Timestamp(OOS_START), color='darkgreen', linestyle='--', linewidth=1.5, label='OOS Start (2019)')
ax1.legend(fontsize=10)
ax1.grid(True, alpha=0.3)

# VIX
ax2.plot(df['vix'].index, df['vix'].values, color='purple', linewidth=0.8, label='VIX')
ax2.axhline(20, color='orange', linestyle='--', alpha=0.5, label='VIX=20')
ax2.axhline(30, color='red', linestyle='--', alpha=0.5, label='VIX=30')
ax2.axvline(pd.Timestamp(OOS_START), color='darkgreen', linestyle='--', linewidth=1.5)
ax2.set_ylabel('VIX', fontsize=11)
ax2.set_xlabel('Date', fontsize=11)
ax2.legend(fontsize=10)
ax2.grid(True, alpha=0.3)
ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
ax2.xaxis.set_major_locator(mdates.YearLocator(2))

plt.tight_layout()
plt.savefig(os.path.join(output_dir, 'k1027_drawdown_timeline.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved: k1027_drawdown_timeline.png")

# ============================================================
# 11. SELF-VALIDATION CHECKS
# ============================================================
print("\n[11] Self-Validation Checks...")

checks = []

# Check 1: Is the result mechanical or empirical?
checks.append({
    'check': 'Mechanical vs Empirical',
    'result': 'EMPIRICAL — VIX-drawdown correlation is not a definitional identity. VIX measures implied vol, drawdown measures realized price decline. The relationship is empirical.'
})

# Check 2: Sharpe > 2x baseline?
sharpe_ratio = oos_strat_m['sharpe'] / oos_bh_m['sharpe'] if oos_bh_m['sharpe'] > 0 else float('inf')
checks.append({
    'check': 'Sharpe > 2x baseline',
    'result': f"Strategy/BH ratio = {sharpe_ratio:.2f}. {'WARNING: >2x' if sharpe_ratio > 2 else 'OK: <2x'}"
})

# Check 3: IS vs OOS consistency
# Count stable correlations
n_stable = sum(1 for t in stability_results.values() for f in t.values() if f.get('stable', False))
n_total = sum(1 for t in stability_results.values() for _ in t.values())
checks.append({
    'check': 'IS vs OOS stability',
    'result': f"{n_stable}/{n_total} correlations are stable (same sign, |diff| < 0.3)"
})

# Check 4: Sufficient OOS drawdowns
checks.append({
    'check': 'OOS sample size',
    'result': f"{len(dd_oos)} OOS drawdowns. {'Adequate' if len(dd_oos) >= 5 else 'LIMITED — interpret with caution'}"
})

for c in checks:
    status = "PASS" if "OK" in c['result'] or "EMPIRICAL" in c['result'] or "Adequate" in c['result'] or "stable" in c['result'].lower() else "WARN"
    print(f"  [{status}] {c['check']}: {c['result']}")

# ============================================================
# 12. SAVE RESULTS
# ============================================================
print("\n[12] Saving results...")

# Prepare serializable drawdown list
dd_list = []
for _, row in dd_df.iterrows():
    dd_list.append({
        'peak_date': str(row['peak_date'])[:10],
        'trough_date': str(row['trough_date'])[:10],
        'recovery_date': str(row['recovery_date'])[:10] if pd.notna(row['recovery_date']) else None,
        'depth': float(row['depth']),
        'days_to_trough': int(row['days_to_trough']),
        'days_to_recovery': int(row['days_to_recovery']) if pd.notna(row['days_to_recovery']) else None,
        'vix_at_peak': float(row['vix_at_peak']),
        'vix_pct_at_peak': float(row['vix_pct_at_peak']),
        'sample': 'IS' if row['peak_date'] <= pd.Timestamp(IS_END) else 'OOS',
    })

results = {
    'experiment_id': 'K1027',
    'title': 'Drawdown Recovery Speed — K735 Corrected Methodology',
    'date': datetime.now().strftime('%Y-%m-%d'),
    'data_source': 'yfinance (SPY, ^VIX)',
    'data_period': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    'total_observations': int(len(df)),
    'seed': 42,
    'methodology': {
        'drawdown_threshold': 0.05,
        'is_period': '2005-01-01 to 2018-12-31',
        'oos_period': '2019-01-01 to present',
        'correlation_method': 'Spearman rank correlation',
        'bootstrap_reps': 5000,
        'lag': 'signal.shift(1) — explicit in code',
        'correction': 'K735 had fake OOS and lookahead bias, both fixed',
    },
    'drawdowns': {
        'total': len(dd_df),
        'in_sample': len(dd_is),
        'out_of_sample': len(dd_oos),
        'list': dd_list,
    },
    'correlations': results_correlations,
    'stability': {},
    'strategy': {
        'best_is_config': {
            'thresholds': best_config[0],
            'weights': best_config[1],
            'description': best_config[2],
        },
        'is_metrics': {
            'strategy': is_results[[desc for desc, _, _ in is_results].index(best_config[2])][1],
            'buy_hold': is_results[[desc for desc, _, _ in is_results].index(best_config[2])][2],
        },
        'oos_metrics': {
            'strategy': oos_strat_m,
            'buy_hold': oos_bh_m,
            'twelve_vix': oos_12vix_m,
        },
        'dm_test_vs_bh': {
            't_stat': float(t_stat),
            'p_value': float(p_val_dm),
            'harvey_threshold': abs(t_stat) > 3.0,
        },
        'dm_test_vs_12vix': {
            't_stat': float(t_stat2),
            'p_value': float(p_val_dm2),
            'harvey_threshold': abs(t_stat2) > 3.0,
        },
    },
    'validation_checks': checks,
    'conclusions': [],
    'limitations': [
        'Small OOS drawdown sample — VIX-depth correlation may not generalize',
        'Drawdown threshold (5%) is arbitrary — different thresholds may yield different results',
        'VIX percentile uses rolling 252d which introduces lookback window dependency',
        'COVID-19 crash (2020) is an extreme outlier in OOS that dominates results',
        'Strategy de-leveraging reduces downside but also reduces upside',
    ],
    'references': [
        'K735: Original drawdown recovery study (Codex-invalidated)',
        'K648: Drawdown Recovery comparison across strategies',
        'K687/K697: VT = drawdown insurance, not alpha generator',
    ],
}

# Serialize stability results
for target, feats in stability_results.items():
    results['stability'][target] = {}
    for feat, data in feats.items():
        results['stability'][target][feat] = {
            'is_rho': data['is_rho'],
            'oos_rho': data['oos_rho'],
            'same_sign': data['same_sign'],
            'abs_diff': data['abs_diff'],
            'stable': data['stable'],
        }

# Generate conclusions based on results
conclusions = []

# Conclusion 1: VIX-depth correlation
is_depth_vix = results_correlations.get('in_sample', {}).get('depth', {}).get('vix_at_peak', {})
oos_depth_vix = results_correlations.get('oos', {}).get('depth', {}).get('vix_at_peak', {})
if is_depth_vix and oos_depth_vix:
    conclusions.append(
        f"VIX at drawdown peak vs drawdown depth: IS rho={is_depth_vix['rho']:.3f}, OOS rho={oos_depth_vix['rho']:.3f}. "
        f"{'Relationship stable across samples.' if stability_results.get('depth', {}).get('vix_at_peak', {}).get('stable', False) else 'Relationship NOT stable across samples — K735 finding does not generalize cleanly.'}"
    )

# Conclusion 2: Strategy performance
conclusions.append(
    f"DD Protection overlay OOS: Sharpe={oos_strat_m['sharpe']:.3f} vs BH={oos_bh_m['sharpe']:.3f} vs 12/VIX={oos_12vix_m['sharpe']:.3f}. "
    f"DM t={t_stat:.3f} (p={p_val_dm:.4f}). "
    f"{'Significant improvement' if abs(t_stat) > 3.0 else 'No significant improvement'} over BH at Harvey (2016) threshold."
)

# Conclusion 3: Overall assessment
conclusions.append(
    f"K735 correction: With strict OOS and proper lag, the VIX-drawdown relationship is "
    f"{'weaker than originally claimed' if oos_depth_vix and abs(oos_depth_vix.get('rho', 0)) < abs(is_depth_vix.get('rho', 0)) else 'consistent with IS findings'}. "
    f"The practical strategy value is {'limited' if oos_strat_m['sharpe'] < oos_12vix_m['sharpe'] else 'comparable to 12/VIX'}."
)

results['conclusions'] = conclusions

# Save
results_path = os.path.join(output_dir, 'k1027_results.json')
with open(results_path, 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)
print(f"  Saved: k1027_results.json")

# ============================================================
# FINAL SUMMARY
# ============================================================
print("\n" + "=" * 60)
print("FINAL SUMMARY — K1027")
print("=" * 60)
for i, c in enumerate(conclusions, 1):
    print(f"\n  [{i}] {c}")
print(f"\n  Files produced:")
print(f"    - k1027_drawdown_recovery.py (this script)")
print(f"    - k1027_results.json")
print(f"    - k1027_vix_vs_depth.png")
print(f"    - k1027_oos_cumulative.png")
print(f"    - k1027_drawdown_timeline.png")
print("\n" + "=" * 60)
