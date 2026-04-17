"""
K682: Percentile-Based Lookup Table — Simplifying the Breakthrough for Retail
==============================================================================

Background:
- K679 found VIX percentile strategy (Sharpe 1.68 vs 12/VIX 1.08, Harvey t=3.375)
- K680 validated 5/5 cross-OOS
- K665 showed 3-row lookup table retains 97% of continuous 12/VIX strategy

Problem:
VIX percentile requires rolling 252-day distribution computation.
Retail investors can't easily do this. But we can:
1. Pre-compute what absolute VIX levels correspond to various percentiles
2. Check if these percentile thresholds are stable over time
3. Create lookup tables using absolute VIX levels that APPROXIMATE the percentile approach

This bridges the gap: the sophistication of percentile-based timing,
delivered as a simple printed card.

Data source: yfinance (SPY, GLD, ^VIX)
Data period: 2006-01-01 to 2026-03-27
Portfolio: 50/50 SPY/GLD, cash at 4% RF

References:
- K679: VIX Percentile-Based Strategy (Sharpe 1.68, t=3.375)
- K680: Cross-OOS validation (5/5 wins)
- K665: Lookup Table Simplification (3-row retains 97%)
- Copeland & Copeland (1999), Market Timing with VIX
- Moreira & Muir (2017), Volatility-Managed Portfolios, JoF
"""

import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from scipy import stats

warnings.filterwarnings('ignore')

# ============================================================
# 1. Data Download
# ============================================================
print("=" * 70)
print("K682: Percentile-Based Lookup Table")
print("=" * 70)

start = "2006-01-01"
end = "2026-03-28"

print(f"\nDownloading data: {start} to {end}")
spy = yf.download("SPY", start=start, end=end, progress=False)["Close"].squeeze()
gld = yf.download("GLD", start=start, end=end, progress=False)["Close"].squeeze()
vix = yf.download("^VIX", start=start, end=end, progress=False)["Close"].squeeze()

# Align dates
common = spy.index.intersection(gld.index).intersection(vix.index)
spy = spy.loc[common]
gld = gld.loc[common]
vix = vix.loc[common]

print(f"Data: {common[0].strftime('%Y-%m-%d')} to {common[-1].strftime('%Y-%m-%d')}")
print(f"Trading days: {len(common)}")

# Returns
spy_ret = spy.pct_change().dropna()
gld_ret = gld.pct_change().dropna()

# Align everything
common2 = spy_ret.index.intersection(gld_ret.index).intersection(vix.index)
spy_ret = spy_ret.loc[common2]
gld_ret = gld_ret.loc[common2]
vix_vals = vix.loc[common2]
# Use previous day's VIX for signal (realistic for retail)
vix_signal = vix.shift(1).loc[common2].dropna()
common3 = spy_ret.index.intersection(vix_signal.index)
spy_ret = spy_ret.loc[common3]
gld_ret = gld_ret.loc[common3]
vix_signal = vix_signal.loc[common3]

print(f"Eval period: {common3[0].strftime('%Y-%m-%d')} to {common3[-1].strftime('%Y-%m-%d')}")
print(f"Eval days: {len(common3)}")

# ============================================================
# 2. VIX Descriptive Statistics & Percentile Analysis
# ============================================================
print("\n" + "=" * 70)
print("2. VIX Percentile Analysis")
print("=" * 70)

vix_all = vix_signal.values

# Full-sample percentiles
percentiles = [5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95]
pct_values = {}
for p in percentiles:
    pct_values[p] = np.percentile(vix_all, p)
    print(f"  {p}th percentile: VIX = {pct_values[p]:.2f}")

print(f"\n  Key thresholds:")
print(f"    25th percentile: VIX = {pct_values[25]:.2f}")
print(f"    50th (median):   VIX = {pct_values[50]:.2f}")
print(f"    75th percentile: VIX = {pct_values[75]:.2f}")
print(f"    90th percentile: VIX = {pct_values[90]:.2f}")

# ============================================================
# 3. Stability of Percentile Thresholds Over Time
# ============================================================
print("\n" + "=" * 70)
print("3. Percentile Threshold Stability (5-year windows)")
print("=" * 70)

years_per_window = 5
approx_days = years_per_window * 252
stability_data = {}

for p in [10, 25, 40, 50, 65, 75, 85, 90]:
    window_vals = []
    for i in range(0, len(vix_all) - approx_days, 252):
        window = vix_all[i:i + approx_days]
        window_vals.append(np.percentile(window, p))
    stability_data[p] = {
        'mean': np.mean(window_vals),
        'std': np.std(window_vals),
        'min': np.min(window_vals),
        'max': np.max(window_vals),
        'cv': np.std(window_vals) / np.mean(window_vals) * 100
    }
    print(f"  {p}th pct: mean={stability_data[p]['mean']:.2f}, "
          f"std={stability_data[p]['std']:.2f}, "
          f"range=[{stability_data[p]['min']:.2f}, {stability_data[p]['max']:.2f}], "
          f"CV={stability_data[p]['cv']:.1f}%")

# Also check rolling 252-day percentiles vs full-sample
print("\n  Rolling 252-day percentile thresholds (by year):")
yearly_pct = {}
for year in range(2007, 2027):
    mask = (vix_signal.index.year == year)
    if mask.sum() > 50:
        v = vix_signal[mask].values
        yearly_pct[year] = {
            25: np.percentile(v, 25),
            50: np.percentile(v, 50),
            75: np.percentile(v, 75),
        }
        print(f"    {year}: 25th={yearly_pct[year][25]:.1f}, "
              f"50th={yearly_pct[year][50]:.1f}, "
              f"75th={yearly_pct[year][75]:.1f}")

# ============================================================
# 4. Backtest Framework
# ============================================================

def backtest_strategy(weights, spy_ret, gld_ret, rf_annual=0.04, tx_cost_bps=5):
    """Backtest a strategy with given daily weights."""
    rf_daily = (1 + rf_annual) ** (1/252) - 1
    tx = tx_cost_bps / 10000

    w = weights.copy()
    port_ret = w * (0.5 * spy_ret + 0.5 * gld_ret) + (1 - w) * rf_daily

    # Transaction costs
    w_diff = np.abs(w.diff().fillna(0))
    tc = w_diff * tx
    port_ret = port_ret - tc

    # Metrics
    ann_ret = (1 + port_ret).prod() ** (252 / len(port_ret)) - 1
    ann_vol = port_ret.std() * np.sqrt(252)
    sharpe = (ann_ret - 0.02) / ann_vol if ann_vol > 0 else 0

    # Max drawdown
    cum = (1 + port_ret).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    # Sortino
    downside = port_ret[port_ret < 0].std() * np.sqrt(252)
    sortino = (ann_ret - 0.02) / downside if downside > 0 else 0

    # Calmar
    calmar = ann_ret / abs(mdd) if abs(mdd) > 0 else 0

    # Turnover
    n_years = len(port_ret) / 252
    annual_turnover = w_diff.sum() / n_years

    total_ret = (1 + port_ret).prod() - 1

    return {
        'cagr': round(ann_ret * 100, 2),
        'sharpe': round(sharpe, 4),
        'sortino': round(sortino, 3),
        'mdd': round(mdd * 100, 2),
        'calmar': round(calmar, 3),
        'ann_vol': round(ann_vol * 100, 2),
        'avg_weight': round(w.mean(), 3),
        'annual_turnover': round(annual_turnover, 2),
        'total_return_pct': round(total_ret * 100, 2),
        'n_days': len(port_ret),
        'daily_returns': port_ret
    }


def lookup_weight(vix_val, table):
    """Get weight from a lookup table."""
    for low, high, weight in table:
        if low <= vix_val < high:
            return weight
    return table[-1][2]  # Last row catches everything above


# ============================================================
# 5. Define All Strategies
# ============================================================

# --- True Percentile (K679 reference) ---
rolling_window = 252
vix_pctrank = vix_signal.rolling(rolling_window).apply(
    lambda x: stats.percentileofscore(x, x.iloc[-1]) / 100, raw=False
)
pct_weights = (1 - vix_pctrank).clip(0, 1)
pct_weights = pct_weights.dropna()

# Align all to percentile weights dates
eval_idx = pct_weights.index
spy_ret_e = spy_ret.loc[eval_idx]
gld_ret_e = gld_ret.loc[eval_idx]
vix_sig_e = vix_signal.loc[eval_idx]

# --- 12/VIX Baseline ---
w_12vix = (12 / vix_sig_e).clip(0, 1)

# --- K665 Best Absolute Table (Table A, 5-row) ---
table_K665_A5 = [
    (0, 12, 1.0),
    (12, 16, 0.8),
    (16, 22, 0.6),
    (22, 30, 0.4),
    (30, 999, 0.2),
]

# --- K665 Table B (3-row simplest) ---
table_K665_B3 = [
    (0, 15, 1.0),
    (15, 25, 0.5),
    (25, 999, 0.2),
]

# --- NEW: Percentile-Informed Table P3 (3-row) ---
# Uses percentile thresholds: ~25th=14, ~75th=22
table_P3 = [
    (0, 14, 0.90),     # Below 25th pct → high allocation
    (14, 22, 0.50),    # 25th-75th pct → moderate
    (22, 999, 0.15),   # Above 75th pct → defensive
]

# --- NEW: Percentile-Informed Table P5 (5-row) ---
# 10th≈12, 40th≈16, 65th≈20, 85th≈27
table_P5 = [
    (0, 13, 0.95),     # Below 10th pct
    (13, 16, 0.75),    # 10th-40th pct
    (16, 20, 0.50),    # 40th-65th pct
    (20, 27, 0.25),    # 65th-85th pct
    (27, 999, 0.10),   # Above 85th pct
]

# --- NEW: Optimized Percentile Table P5-OPT ---
# Fine-tune allocations to better match percentile strategy's behavior
# From K679 data: percentile avg weights by VIX level
table_P5_OPT = [
    (0, 13, 0.86),     # Matches pct avg_weight=0.864 at VIX<12
    (13, 16, 0.69),    # Matches pct avg_weight=0.693 at VIX 12-15
    (16, 20, 0.55),    # Matches pct avg_weight=0.554 at VIX 15-20
    (20, 25, 0.45),    # Matches pct avg_weight=0.450 at VIX 20-25
    (25, 999, 0.20),   # Avg of 0.284 (25-30) and 0.164 (>30)
]

# --- NEW: Aggressive Percentile Table P3-AGG (3-row) ---
# Key insight: percentile uses LOWER weights than 12/VIX in normal times
# and proportionally even lower in high-VIX
table_P3_AGG = [
    (0, 15, 0.80),     # Percentile is ~0.78 at VIX<15
    (15, 25, 0.45),    # Percentile is ~0.50 at VIX 15-25
    (25, 999, 0.10),   # Percentile is ~0.16 at VIX>30, aggressive cut
]

# --- NEW: 4-row percentile-inspired ---
table_P4 = [
    (0, 14, 0.85),     # Below 25th
    (14, 18, 0.60),    # 25th-50th
    (18, 25, 0.35),    # 50th-80th
    (25, 999, 0.12),   # Above 80th
]

# Compute lookup weights
strategies = {
    'True Percentile (K679)': pct_weights,
    '12/VIX Continuous': w_12vix,
}

table_configs = {
    'K665 Table A (5-row abs)': table_K665_A5,
    'K665 Table B (3-row abs)': table_K665_B3,
    'P3: Pct-Informed 3-row': table_P3,
    'P3-AGG: Aggressive 3-row': table_P3_AGG,
    'P4: Pct-Informed 4-row': table_P4,
    'P5: Pct-Informed 5-row': table_P5,
    'P5-OPT: Calibrated 5-row': table_P5_OPT,
}

for name, table in table_configs.items():
    w = vix_sig_e.apply(lambda v: lookup_weight(v, table))
    strategies[name] = w

# ============================================================
# 6. Full-Period Backtest
# ============================================================
print("\n" + "=" * 70)
print("6. Full-Period Backtest Comparison")
print("=" * 70)

results = {}
for name, w in strategies.items():
    res = backtest_strategy(w, spy_ret_e, gld_ret_e)
    results[name] = res
    print(f"\n  {name}:")
    print(f"    Sharpe={res['sharpe']:.4f}  CAGR={res['cagr']:.2f}%  "
          f"MDD={res['mdd']:.2f}%  Vol={res['ann_vol']:.2f}%  "
          f"Avg_w={res['avg_weight']:.3f}  Turnover={res['annual_turnover']:.1f}")

# ============================================================
# 7. Retention Analysis
# ============================================================
print("\n" + "=" * 70)
print("7. Sharpe Retention vs True Percentile (K679)")
print("=" * 70)

ref_sharpe = results['True Percentile (K679)']['sharpe']
ref_12vix = results['12/VIX Continuous']['sharpe']

print(f"\n  Reference: True Percentile Sharpe = {ref_sharpe:.4f}")
print(f"  Baseline:  12/VIX Sharpe = {ref_12vix:.4f}")
print(f"  Improvement: {ref_sharpe - ref_12vix:.4f} ({(ref_sharpe / ref_12vix - 1) * 100:.1f}%)")

retention_data = {}
for name, res in results.items():
    if name == 'True Percentile (K679)':
        continue
    ret_vs_pct = res['sharpe'] / ref_sharpe if ref_sharpe != 0 else 0
    ret_vs_12vix = res['sharpe'] / ref_12vix if ref_12vix != 0 else 0
    retention_data[name] = {
        'sharpe': res['sharpe'],
        'retention_vs_percentile': round(ret_vs_pct, 4),
        'retention_vs_12vix': round(ret_vs_12vix, 4),
        'cagr': res['cagr'],
        'mdd': res['mdd'],
        'improvement_over_12vix': round(res['sharpe'] - ref_12vix, 4),
    }
    beat_12vix = "YES" if res['sharpe'] > ref_12vix else "no"
    print(f"\n  {name}:")
    print(f"    Sharpe={res['sharpe']:.4f}  "
          f"Retention vs Pct={ret_vs_pct*100:.1f}%  "
          f"Retention vs 12/VIX={ret_vs_12vix*100:.1f}%  "
          f"Beats 12/VIX? {beat_12vix}")

# ============================================================
# 8. Weight Correlation with True Percentile
# ============================================================
print("\n" + "=" * 70)
print("8. Weight Correlation with True Percentile")
print("=" * 70)

pct_w = strategies['True Percentile (K679)']
corr_data = {}
for name, w in strategies.items():
    if name == 'True Percentile (K679)':
        continue
    corr = np.corrcoef(pct_w.values, w.values)[0, 1]
    mae = np.abs(pct_w.values - w.values).mean()
    corr_data[name] = {'weight_corr': round(corr, 4), 'weight_mae': round(mae, 4)}
    print(f"  {name}: corr={corr:.4f}, MAE={mae:.4f}")

# ============================================================
# 9. Statistical Test: Best lookup table vs 12/VIX
# ============================================================
print("\n" + "=" * 70)
print("9. Statistical Tests (paired t-test on daily returns)")
print("=" * 70)

ret_12vix = results['12/VIX Continuous']['daily_returns']

for name, res in results.items():
    if name in ['12/VIX Continuous', 'True Percentile (K679)']:
        continue
    diff = res['daily_returns'] - ret_12vix
    t_stat = diff.mean() / (diff.std() / np.sqrt(len(diff)))
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), len(diff) - 1))
    print(f"  {name} vs 12/VIX: t={t_stat:.3f}, p={p_val:.4f}, "
          f"{'*** SIGNIFICANT' if abs(t_stat) > 3.0 else '** sig' if p_val < 0.05 else 'not sig'}")

# Also test best lookup vs true percentile
print("\n  vs True Percentile:")
ret_pct = results['True Percentile (K679)']['daily_returns']
for name, res in results.items():
    if name in ['12/VIX Continuous', 'True Percentile (K679)']:
        continue
    diff = res['daily_returns'] - ret_pct
    t_stat = diff.mean() / (diff.std() / np.sqrt(len(diff)))
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), len(diff) - 1))
    print(f"  {name} vs True Pct: t={t_stat:.3f}, p={p_val:.4f}")

# ============================================================
# 10. Sub-Period Analysis
# ============================================================
print("\n" + "=" * 70)
print("10. Sub-Period Analysis")
print("=" * 70)

periods = {
    'GFC (2008-2009)': ('2008-01-01', '2009-12-31'),
    'Post-GFC Bull (2010-2014)': ('2010-01-01', '2014-12-31'),
    'Low Vol (2017)': ('2017-01-01', '2017-12-31'),
    'COVID (2020)': ('2020-01-01', '2020-12-31'),
    'Rate Hikes (2022)': ('2022-01-01', '2022-12-31'),
    'Recent (2024-2026)': ('2024-01-01', '2026-12-31'),
}

sub_period_results = {}
key_strategies = [
    'True Percentile (K679)', '12/VIX Continuous',
    'K665 Table A (5-row abs)', 'K665 Table B (3-row abs)',
    'P3: Pct-Informed 3-row', 'P5: Pct-Informed 5-row',
    'P5-OPT: Calibrated 5-row',
]

for period_name, (ps, pe) in periods.items():
    print(f"\n  --- {period_name} ---")
    sub_period_results[period_name] = {}
    mask = (spy_ret_e.index >= ps) & (spy_ret_e.index <= pe)
    if mask.sum() < 50:
        print(f"    Insufficient data ({mask.sum()} days)")
        continue

    for strat_name in key_strategies:
        w = strategies[strat_name]
        sub_w = w.loc[mask]
        sub_spy = spy_ret_e.loc[mask]
        sub_gld = gld_ret_e.loc[mask]
        res = backtest_strategy(sub_w, sub_spy, sub_gld)
        sub_period_results[period_name][strat_name] = {
            'sharpe': res['sharpe'], 'cagr': res['cagr'], 'mdd': res['mdd']
        }
        print(f"    {strat_name}: Sharpe={res['sharpe']:.3f}, CAGR={res['cagr']:.1f}%")

# ============================================================
# 11. Find the Best Retail Card
# ============================================================
print("\n" + "=" * 70)
print("11. Ranking: Best Lookup Table for Retail")
print("=" * 70)

# Score: weighted combination of Sharpe retention vs percentile + vs 12/VIX + simplicity
lookup_names = [n for n in results if n not in ['True Percentile (K679)', '12/VIX Continuous']]
ranking = []
for name in lookup_names:
    r = results[name]
    ret_pct = r['sharpe'] / ref_sharpe if ref_sharpe != 0 else 0
    beats_12vix = r['sharpe'] > ref_12vix
    rows = len(table_configs.get(name, [()] * 5))  # crude row count

    # Composite score: 60% Sharpe, 20% low MDD, 20% simplicity bonus
    sharpe_score = r['sharpe']
    mdd_score = -r['mdd'] / 100  # Lower MDD is better
    simplicity_bonus = max(0, (7 - rows) * 0.02)  # Fewer rows = bonus

    composite = 0.6 * sharpe_score + 0.2 * mdd_score + 0.2 * simplicity_bonus

    ranking.append({
        'name': name,
        'sharpe': r['sharpe'],
        'cagr': r['cagr'],
        'mdd': r['mdd'],
        'retention_vs_pct': round(ret_pct * 100, 1),
        'beats_12vix': beats_12vix,
        'composite': round(composite, 4),
        'rows': rows,
    })

ranking.sort(key=lambda x: x['sharpe'], reverse=True)

print(f"\n  {'Rank':<5} {'Strategy':<30} {'Sharpe':<8} {'CAGR%':<8} {'MDD%':<8} {'Ret%':<7} {'Beat12V':<8} {'Rows':<5}")
print(f"  {'-'*4}  {'-'*29} {'-'*7} {'-'*7} {'-'*7} {'-'*6} {'-'*7} {'-'*4}")
for i, r in enumerate(ranking):
    print(f"  {i+1:<5} {r['name']:<30} {r['sharpe']:<8.4f} {r['cagr']:<8.2f} {r['mdd']:<8.2f} "
          f"{r['retention_vs_pct']:<7.1f} {'YES' if r['beats_12vix'] else 'no':<8} {r['rows']:<5}")

# ============================================================
# 12. The Recommended Retail Card
# ============================================================
print("\n" + "=" * 70)
print("12. RECOMMENDED RETAIL CARD")
print("=" * 70)

# Pick the best that beats 12/VIX
best_beating = [r for r in ranking if r['beats_12vix']]
if best_beating:
    best = best_beating[0]
    print(f"\n  WINNER: {best['name']}")
    print(f"  Sharpe: {best['sharpe']:.4f} (vs True Percentile {ref_sharpe:.4f}, retention {best['retention_vs_pct']:.1f}%)")
    print(f"  Sharpe: {best['sharpe']:.4f} (vs 12/VIX {ref_12vix:.4f}, improvement {best['sharpe'] - ref_12vix:.4f})")
else:
    best = ranking[0]
    print(f"\n  Best available (doesn't beat 12/VIX): {best['name']}")

# Print the card
print(f"\n  ┌───────────────────────────────────────────────┐")
print(f"  │  VIX-Based Investment Guide (Percentile Card) │")
print(f"  │  For: 50/50 SPY/GLD Portfolio                 │")
print(f"  ├───────────────────────────────────────────────┤")

# Find which table config to print
best_table_name = best['name']
if best_table_name in table_configs:
    table = table_configs[best_table_name]
    for low, high, alloc in table:
        high_str = str(int(high)) if high < 900 else "+"
        low_str = str(int(low)) if low > 0 else "0"
        if high >= 900:
            vix_label = f"VIX > {low_str}"
        elif low == 0:
            vix_label = f"VIX < {high_str}"
        else:
            vix_label = f"VIX {low_str}-{high_str}"
        print(f"  │  {vix_label:<15} → {alloc*100:>5.0f}% invested            │")
    print(f"  │  (remainder in cash/T-bills at ~4%)          │")
    print(f"  └───────────────────────────────────────────────┘")

# ============================================================
# 13. Compile Results JSON
# ============================================================
print("\n" + "=" * 70)
print("13. Saving results...")
print("=" * 70)

# Build clean results (no Series objects)
clean_results = {}
for name, res in results.items():
    clean_results[name] = {k: v for k, v in res.items() if k != 'daily_returns'}

# Build clean sub-period
clean_sub = {}
for period, strats in sub_period_results.items():
    clean_sub[period] = strats

# Build stability data
stability_clean = {}
for p, v in stability_data.items():
    stability_clean[f"{p}th_percentile"] = v

output = {
    "experiment_id": "K682",
    "title": "Percentile-Based Lookup Table — Simplifying the Breakthrough for Retail",
    "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    "data_source": "yfinance (SPY, GLD, ^VIX)",
    "data_period": f"{common3[0].strftime('%Y-%m-%d')} to {common3[-1].strftime('%Y-%m-%d')}",
    "eval_period": f"{eval_idx[0].strftime('%Y-%m-%d')} to {eval_idx[-1].strftime('%Y-%m-%d')}",
    "n_eval_days": len(eval_idx),
    "n_years": round(len(eval_idx) / 252, 1),
    "methodology": {
        "portfolio": "50/50 SPY/GLD, cash remainder at 4% annual RF",
        "transaction_cost": "5 bps one-way",
        "rolling_window_for_percentile": 252,
        "signal": "Previous day VIX close (1-day lag, realistic for retail)"
    },
    "references": [
        "K679: VIX Percentile Strategy (Sharpe 1.68, t=3.375)",
        "K680: Cross-OOS 5/5 validation",
        "K665: Lookup Table (3-row retains 97% of 12/VIX)",
        "Copeland & Copeland (1999), Market Timing with VIX",
        "Moreira & Muir (2017), Volatility-Managed Portfolios"
    ],
    "vix_percentile_thresholds": {f"{p}th": round(v, 2) for p, v in pct_values.items()},
    "percentile_stability_5yr_windows": stability_clean,
    "lookup_tables": {
        "P3_percentile_3row": {
            "rows": 3,
            "design_principle": "Percentile-informed thresholds at 25th/75th",
            "rules": [
                {"vix_range": "< 14", "approx_percentile": "Below 25th", "allocation": "90%"},
                {"vix_range": "14-22", "approx_percentile": "25th-75th", "allocation": "50%"},
                {"vix_range": "> 22", "approx_percentile": "Above 75th", "allocation": "15%"},
            ]
        },
        "P3_AGG_aggressive_3row": {
            "rows": 3,
            "design_principle": "More aggressive defensive allocation at high VIX",
            "rules": [
                {"vix_range": "< 15", "approx_percentile": "Below 30th", "allocation": "80%"},
                {"vix_range": "15-25", "approx_percentile": "30th-80th", "allocation": "45%"},
                {"vix_range": "> 25", "approx_percentile": "Above 80th", "allocation": "10%"},
            ]
        },
        "P4_percentile_4row": {
            "rows": 4,
            "design_principle": "Percentile-informed with 4 regimes",
            "rules": [
                {"vix_range": "< 14", "approx_percentile": "Below 25th", "allocation": "85%"},
                {"vix_range": "14-18", "approx_percentile": "25th-50th", "allocation": "60%"},
                {"vix_range": "18-25", "approx_percentile": "50th-80th", "allocation": "35%"},
                {"vix_range": "> 25", "approx_percentile": "Above 80th", "allocation": "12%"},
            ]
        },
        "P5_percentile_5row": {
            "rows": 5,
            "design_principle": "Fine-grained percentile mapping",
            "rules": [
                {"vix_range": "< 13", "approx_percentile": "Below 10th", "allocation": "95%"},
                {"vix_range": "13-16", "approx_percentile": "10th-40th", "allocation": "75%"},
                {"vix_range": "16-20", "approx_percentile": "40th-65th", "allocation": "50%"},
                {"vix_range": "20-27", "approx_percentile": "65th-85th", "allocation": "25%"},
                {"vix_range": "> 27", "approx_percentile": "Above 85th", "allocation": "10%"},
            ]
        },
        "P5_OPT_calibrated_5row": {
            "rows": 5,
            "design_principle": "Calibrated to match K679 avg weights by VIX level",
            "rules": [
                {"vix_range": "< 13", "approx_percentile": "Below 10th", "allocation": "86%"},
                {"vix_range": "13-16", "approx_percentile": "10th-40th", "allocation": "69%"},
                {"vix_range": "16-20", "approx_percentile": "40th-65th", "allocation": "55%"},
                {"vix_range": "20-25", "approx_percentile": "65th-80th", "allocation": "45%"},
                {"vix_range": "> 25", "approx_percentile": "Above 80th", "allocation": "20%"},
            ]
        },
    },
    "full_period_results": clean_results,
    "retention_analysis": retention_data,
    "weight_correlation_with_true_percentile": corr_data,
    "sub_period_results": clean_sub,
    "ranking": ranking,
    "recommended_card": {
        "winner": best['name'],
        "sharpe": best['sharpe'],
        "cagr": best['cagr'],
        "mdd": best['mdd'],
        "retention_vs_true_percentile_pct": best['retention_vs_pct'],
        "beats_12vix": best['beats_12vix'],
    },
    "key_findings": [],
    "limitations": [
        "Lookup tables use FIXED VIX thresholds derived from full-sample percentiles — potential look-ahead bias",
        "True percentile adapts to regime changes; lookup tables do NOT",
        "VIX percentile thresholds shift across regimes (CV ~15-25% across 5yr windows)",
        "Transaction costs of 5 bps may understate retail costs",
        "GLD data starts mid-2004; full overlap from 2006",
        "Backtest uses 1-day lagged VIX (realistic for retail)"
    ],
}

# Build key findings
findings = []
findings.append(f"True Percentile strategy Sharpe = {ref_sharpe:.4f}, 12/VIX = {ref_12vix:.4f}")
findings.append(f"Best lookup table: {best['name']} (Sharpe={best['sharpe']:.4f}, retention={best['retention_vs_pct']:.1f}% vs percentile)")

# Count how many beat 12/VIX
n_beat = sum(1 for r in ranking if r['beats_12vix'])
findings.append(f"{n_beat}/{len(ranking)} lookup tables beat 12/VIX baseline")

# Percentile stability
avg_cv = np.mean([stability_data[p]['cv'] for p in [25, 50, 75]])
findings.append(f"VIX percentile thresholds moderately stable (avg CV={avg_cv:.1f}% across 5yr windows)")

# Best simple table
simple_beating = [r for r in ranking if r['beats_12vix'] and r['rows'] <= 3]
if simple_beating:
    findings.append(f"Simplest table beating 12/VIX: {simple_beating[0]['name']} ({simple_beating[0]['rows']} rows, Sharpe={simple_beating[0]['sharpe']:.4f})")
else:
    findings.append("No 3-row table beats 12/VIX")

output["key_findings"] = findings

# Save
outpath = "/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-ad99a9ae/experiments/k682_results.json"
with open(outpath, 'w', encoding='utf-8') as f:
    json.dump(output, f, indent=2, ensure_ascii=False, default=str)

print(f"\n  Results saved to: {outpath}")

# ============================================================
# Summary
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)
for f in findings:
    print(f"  • {f}")
print(f"\n  True Percentile (K679): Sharpe = {ref_sharpe:.4f}")
print(f"  12/VIX Baseline:       Sharpe = {ref_12vix:.4f}")
print(f"  Best Lookup Table:     Sharpe = {best['sharpe']:.4f} ({best['name']})")
print(f"  Retention vs Pct:      {best['retention_vs_pct']:.1f}%")
print(f"\nDone!")
