"""
K786: Convexity-Adjusted VT Insurance Premium — When is VT insurance overpriced?

Core question: VT costs ~4%/yr in expected return drag (K41). Can we TIME when
insurance is cheap vs expensive using Vol-of-Vol (VoV)?

Key insight from K649: VoV adjustment that INCREASES hedging when VoV high → hurts
(Sharpe 0.527 vs 0.680). K786 tries the OPPOSITE: REDUCE hedging when VoV low
(insurance overpriced because calm markets don't need it).

References:
- K41: VT insurance premium ~4%/yr constant
- K649: VoV adjustment hurts (wrong direction — increased hedging on high VoV)
- K687: No VT beats BH 50/50 on Sharpe after proper lag
- K688: VT wins CRRA utility at gamma>=5
- K74: VT underperforms 80% of the time
- Gemini suggestion: VoV clustering for insurance pricing

Data: yfinance SPY/GLD/^VIX, 2006-01-01 to 2025-12-31
OOS: 2023-01-01 to 2024-12-31

Author: [提出: Gemini, 執行: Claude]
"""

import numpy as np
import pandas as pd
import yfinance as yf
import json
import warnings
from datetime import datetime
from scipy import stats

warnings.filterwarnings('ignore')

# ============================================================
# 1. DATA DOWNLOAD
# ============================================================
print("=" * 70)
print("K786: Convexity-Adjusted VT Insurance Premium")
print("=" * 70)

tickers = ['SPY', 'GLD', '^VIX']
data = {}
for t in tickers:
    df = yf.download(t, start='2005-01-01', end='2026-01-01', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    data[t] = df['Close'] if 'Close' in df.columns else df['Adj Close']

prices = pd.DataFrame(data).dropna()
prices.columns = ['SPY', 'GLD', 'VIX']
print(f"Data: {prices.index[0].date()} to {prices.index[-1].date()}, {len(prices)} days")

# Returns
ret_spy = prices['SPY'].pct_change()
ret_gld = prices['GLD'].pct_change()

# ============================================================
# 2. VOL-OF-VOL (VoV) COMPUTATION
# ============================================================
vix = prices['VIX']
vix_change = vix.diff()  # daily VIX change (not pct change — VIX is already a vol measure)

# VoV = rolling 22-day std of VIX daily changes
vov_22 = vix_change.rolling(22).std()

# Also compute expanding percentile of VoV (no lookahead)
vov_expanding_rank = vov_22.expanding(min_periods=252).rank(pct=True)

print(f"\nVoV (22d) stats:")
print(f"  Mean: {vov_22.mean():.3f}")
print(f"  Median: {vov_22.median():.3f}")
print(f"  Std: {vov_22.std():.3f}")
print(f"  25th pctl: {vov_22.quantile(0.25):.3f}")
print(f"  75th pctl: {vov_22.quantile(0.75):.3f}")

# ============================================================
# 3. STRATEGY DEFINITIONS
# ============================================================
# All strategies: SPY weight from VIX, remainder to GLD
# CRITICAL: signal.shift(1) — VIX/VoV from yesterday, return today

def compute_strategy_returns(spy_weight_series, ret_spy, ret_gld, name="strategy"):
    """Compute portfolio returns with proper lag."""
    # SHIFT(1): signal from yesterday, return today
    w = spy_weight_series.shift(1).clip(0.0, 1.0)
    port_ret = w * ret_spy + (1 - w) * ret_gld
    port_ret = port_ret.dropna()
    return port_ret

# --- Strategy 1: Buy & Hold 50/50 ---
bh_weight = pd.Series(0.5, index=prices.index)
ret_bh = compute_strategy_returns(bh_weight, ret_spy, ret_gld, "BH 50/50")

# --- Strategy 2: Static 12/VIX (standard VT) ---
w_12vix = (12.0 / vix).clip(0.0, 1.0)
ret_12vix = compute_strategy_returns(w_12vix, ret_spy, ret_gld, "12/VIX")

# --- Strategy 3: VoV-Adjusted VT ---
# Low VoV (< expanding median): use 18/VIX (higher equity, less insurance)
# High VoV (>= expanding median): use 12/VIX (standard insurance)
vov_median_expanding = vov_22.expanding(min_periods=252).median()
is_low_vov = vov_22 < vov_median_expanding

w_vov_adj = pd.Series(np.nan, index=prices.index)
w_vov_adj[is_low_vov] = (18.0 / vix[is_low_vov]).clip(0.0, 1.0)
w_vov_adj[~is_low_vov] = (12.0 / vix[~is_low_vov]).clip(0.0, 1.0)
w_vov_adj = w_vov_adj.clip(0.0, 1.0)
ret_vov_adj = compute_strategy_returns(w_vov_adj, ret_spy, ret_gld, "VoV-Adj VT")

# --- Strategy 4: VoV-Off VT ---
# Turn off VT entirely when VoV < expanding 25th percentile (go 50/50)
# Otherwise use 12/VIX
vov_p25_expanding = vov_22.expanding(min_periods=252).quantile(0.25)
is_very_low_vov = vov_22 < vov_p25_expanding

w_vov_off = pd.Series(np.nan, index=prices.index)
w_vov_off[is_very_low_vov] = 0.5  # no VT, just 50/50
w_vov_off[~is_very_low_vov] = (12.0 / vix[~is_very_low_vov]).clip(0.0, 1.0)
w_vov_off = w_vov_off.clip(0.0, 1.0)
ret_vov_off = compute_strategy_returns(w_vov_off, ret_spy, ret_gld, "VoV-Off VT")

# --- Strategy 5: Smooth VoV scaling ---
# Scale 12/VIX weight by VoV percentile rank:
# weight_multiplier = 0.5 + 0.5 * vov_rank (range: 0.5x to 1.0x)
# Low VoV → less insurance (0.5x), High VoV → full insurance (1.0x)
# This means: target = (12/VIX) when VoV high, (24/VIX) when VoV low [more equity]
# Actually: w_spy = w_12vix * (1 + (1 - vov_rank))
# Simpler: effective_target = 12 + 12*(1 - vov_rank) = 24 - 12*vov_rank
effective_target = 24 - 12 * vov_expanding_rank.fillna(0.5)
w_smooth_vov = (effective_target / vix).clip(0.0, 1.0)
ret_smooth_vov = compute_strategy_returns(w_smooth_vov, ret_spy, ret_gld, "Smooth VoV VT")

# ============================================================
# 4. COMMON ANALYSIS PERIOD
# ============================================================
# Need at least 252 days for expanding stats to kick in
# Start from 2007 to have full year of VoV data
start_full = '2007-01-01'
start_oos = '2023-01-01'
end_oos = '2024-12-31'

strategies = {
    'BH 50/50': ret_bh,
    '12/VIX (Static VT)': ret_12vix,
    'VoV-Adjusted VT': ret_vov_adj,
    'VoV-Off VT': ret_vov_off,
    'Smooth VoV VT': ret_smooth_vov,
}

# ============================================================
# 5. PERFORMANCE METRICS
# ============================================================
def calc_metrics(returns, period_start, period_end):
    """Calculate standard performance metrics."""
    r = returns.loc[period_start:period_end].dropna()
    if len(r) < 50:
        return None
    ann_ret = r.mean() * 252
    ann_vol = r.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cumret = (1 + r).cumprod()
    mdd = (cumret / cumret.cummax() - 1).min()
    # Sortino
    downside = r[r < 0].std() * np.sqrt(252)
    sortino = ann_ret / downside if downside > 0 else 0
    return {
        'ann_return': round(ann_ret, 4),
        'ann_vol': round(ann_vol, 4),
        'sharpe': round(sharpe, 4),
        'sortino': round(sortino, 4),
        'mdd': round(mdd, 4),
        'n_days': len(r),
    }

def crra_utility(returns, gamma):
    """CRRA utility: E[(1+r)^(1-gamma) / (1-gamma)]"""
    r = returns.dropna()
    wealth = 1 + r
    wealth = wealth[wealth > 0]  # avoid negative wealth
    if gamma == 1:
        return np.mean(np.log(wealth))
    else:
        return np.mean((wealth ** (1 - gamma) - 1) / (1 - gamma))

def dm_test(e1, e2, h=1):
    """Diebold-Mariano test on squared errors (loss = r^2 differences)."""
    d = e1 - e2
    d = d.dropna()
    n = len(d)
    if n < 30:
        return np.nan, np.nan
    d_mean = d.mean()
    # HAC variance (Newey-West with h-1 lags)
    gamma0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * gamma_k
    var_d = (gamma0 + gamma_sum) / n
    if var_d <= 0:
        return np.nan, np.nan
    dm_stat = d_mean / np.sqrt(var_d)
    p_val = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return dm_stat, p_val

print("\n" + "=" * 70)
print("FULL PERIOD PERFORMANCE (2007-2025)")
print("=" * 70)

full_metrics = {}
for name, ret in strategies.items():
    m = calc_metrics(ret, start_full, '2025-12-31')
    if m:
        full_metrics[name] = m
        print(f"\n{name}:")
        print(f"  Ann Return: {m['ann_return']:.4f}  Vol: {m['ann_vol']:.4f}")
        print(f"  Sharpe: {m['sharpe']:.4f}  Sortino: {m['sortino']:.4f}")
        print(f"  MDD: {m['mdd']:.4f}  N: {m['n_days']}")

print("\n" + "=" * 70)
print("OOS PERIOD PERFORMANCE (2023-2025)")
print("=" * 70)

oos_metrics = {}
for name, ret in strategies.items():
    m = calc_metrics(ret, start_oos, end_oos)
    if m:
        oos_metrics[name] = m
        print(f"\n{name}:")
        print(f"  Ann Return: {m['ann_return']:.4f}  Vol: {m['ann_vol']:.4f}")
        print(f"  Sharpe: {m['sharpe']:.4f}  Sortino: {m['sortino']:.4f}")
        print(f"  MDD: {m['mdd']:.4f}  N: {m['n_days']}")

# ============================================================
# 6. CRRA UTILITY COMPARISON (gamma=5, 10)
# ============================================================
print("\n" + "=" * 70)
print("CRRA UTILITY (Full Period)")
print("=" * 70)

utility_results = {}
for gamma in [5, 10]:
    print(f"\n  gamma = {gamma}:")
    for name, ret in strategies.items():
        r = ret.loc[start_full:'2025-12-31'].dropna()
        u = crra_utility(r, gamma)
        key = f"{name}_gamma{gamma}"
        utility_results[key] = round(u, 8)
        print(f"    {name}: {u:.8f}")

# ============================================================
# 7. INSURANCE PREMIUM ANALYSIS
# ============================================================
print("\n" + "=" * 70)
print("INSURANCE PREMIUM BY VoV QUINTILE")
print("=" * 70)

# Insurance premium = 12/VIX return - BH 50/50 return (daily)
ins_premium_daily = ret_12vix - ret_bh
ins_premium_daily = ins_premium_daily.loc[start_full:'2025-12-31'].dropna()

# VoV quintile assignment (expanding, no lookahead)
# Use VoV from yesterday (shifted) to match returns
vov_shifted = vov_22.shift(1)
vov_for_quintile = vov_shifted.loc[ins_premium_daily.index]

# Expanding quintile — assign each day to a quintile based on history up to that day
quintile_labels = pd.Series(np.nan, index=ins_premium_daily.index)
for i in range(252, len(ins_premium_daily)):
    idx = ins_premium_daily.index[i]
    historical_vov = vov_for_quintile.iloc[:i+1].dropna()
    if len(historical_vov) < 100:
        continue
    current_val = vov_for_quintile.iloc[i]
    if pd.isna(current_val):
        continue
    pct_rank = (historical_vov < current_val).sum() / len(historical_vov)
    quintile_labels.iloc[i] = min(int(pct_rank * 5) + 1, 5)

# Vectorized approach for speed (approximate expanding quintile)
# Use expanding rank approach
vov_rank_series = vov_for_quintile.expanding(min_periods=252).rank(pct=True)
quintile_fast = np.ceil(vov_rank_series * 5).clip(1, 5)

print("\nInsurance Premium (12/VIX minus BH) by VoV Quintile:")
print("(Quintile 1 = lowest VoV = calmest markets)")
print("-" * 60)

quintile_analysis = {}
for q in range(1, 6):
    mask = quintile_fast == q
    masked = mask.reindex(ins_premium_daily.index, fill_value=False)
    premium_in_q = ins_premium_daily[masked]
    if len(premium_in_q) < 20:
        continue
    ann_premium = premium_in_q.mean() * 252
    ann_vol = premium_in_q.std() * np.sqrt(252)
    t_stat = premium_in_q.mean() / (premium_in_q.std() / np.sqrt(len(premium_in_q)))
    pct_negative = (premium_in_q < 0).mean()

    quintile_analysis[f"Q{q}"] = {
        'ann_premium': round(ann_premium, 4),
        'ann_vol': round(ann_vol, 4),
        'info_ratio': round(ann_premium / ann_vol if ann_vol > 0 else 0, 4),
        't_stat': round(t_stat, 4),
        'pct_negative_days': round(pct_negative, 4),
        'n_days': int(masked.sum()),
    }
    print(f"  Q{q} (n={int(masked.sum())}): Premium={ann_premium:+.4f}  "
          f"Vol={ann_vol:.4f}  IR={ann_premium/ann_vol if ann_vol > 0 else 0:+.4f}  "
          f"t={t_stat:.2f}  %neg={pct_negative:.1%}")

# ============================================================
# 8. FORWARD INSURANCE VALUE
# ============================================================
print("\n" + "=" * 70)
print("FORWARD INSURANCE VALUE BY VoV QUINTILE")
print("(Next 63 trading days insurance payout)")
print("=" * 70)

# Forward 63-day (quarterly) insurance payout
forward_63 = ins_premium_daily.rolling(63).sum().shift(-63)

forward_analysis = {}
for q in range(1, 6):
    mask = quintile_fast == q
    masked = mask.reindex(forward_63.index, fill_value=False)
    fwd = forward_63[masked].dropna()
    if len(fwd) < 20:
        continue
    mean_fwd = fwd.mean()
    median_fwd = fwd.median()
    pct_positive = (fwd > 0).mean()
    t_stat = fwd.mean() / (fwd.std() / np.sqrt(len(fwd)))

    forward_analysis[f"Q{q}"] = {
        'mean_63d_payout': round(mean_fwd, 4),
        'median_63d_payout': round(median_fwd, 4),
        'pct_positive_payout': round(pct_positive, 4),
        't_stat': round(t_stat, 4),
        'n_obs': len(fwd),
    }
    print(f"  Q{q} (n={len(fwd)}): Mean payout={mean_fwd:+.4f}  "
          f"Median={median_fwd:+.4f}  %pos={pct_positive:.1%}  t={t_stat:.2f}")

# ============================================================
# 9. DM TESTS (strategies vs BH 50/50 and vs 12/VIX)
# ============================================================
print("\n" + "=" * 70)
print("DIEBOLD-MARIANO TESTS (Full Period)")
print("=" * 70)

# Use negative portfolio returns as loss (we want higher returns)
# DM test on utility difference is more appropriate
# Use squared returns as proxy for loss differential
dm_results = {}
baseline_ret = ret_bh.loc[start_full:'2025-12-31'].dropna()

for name, ret in strategies.items():
    if name == 'BH 50/50':
        continue
    r = ret.loc[start_full:'2025-12-31'].dropna()
    common = baseline_ret.index.intersection(r.index)
    if len(common) < 100:
        continue
    # DM on negative returns (loss = -return; lower loss = higher return)
    loss_baseline = -baseline_ret.loc[common]
    loss_strat = -r.loc[common]
    dm_stat, dm_pval = dm_test(loss_baseline ** 2, loss_strat ** 2)
    dm_results[f"{name} vs BH"] = {
        'dm_stat': round(dm_stat, 4) if not np.isnan(dm_stat) else None,
        'p_value': round(dm_pval, 4) if not np.isnan(dm_pval) else None,
        'n': len(common),
    }
    sig = "***" if dm_pval < 0.01 else "**" if dm_pval < 0.05 else "*" if dm_pval < 0.10 else ""
    print(f"  {name} vs BH: DM={dm_stat:.4f}  p={dm_pval:.4f} {sig}")

# Also test VoV strategies vs standard 12/VIX
print("\nvs 12/VIX (Static VT):")
baseline_vt = ret_12vix.loc[start_full:'2025-12-31'].dropna()
for name, ret in strategies.items():
    if name in ['BH 50/50', '12/VIX (Static VT)']:
        continue
    r = ret.loc[start_full:'2025-12-31'].dropna()
    common = baseline_vt.index.intersection(r.index)
    if len(common) < 100:
        continue
    loss_vt = -baseline_vt.loc[common]
    loss_strat = -r.loc[common]
    dm_stat, dm_pval = dm_test(loss_vt ** 2, loss_strat ** 2)
    dm_results[f"{name} vs 12/VIX"] = {
        'dm_stat': round(dm_stat, 4) if not np.isnan(dm_stat) else None,
        'p_value': round(dm_pval, 4) if not np.isnan(dm_pval) else None,
        'n': len(common),
    }
    sig = "***" if dm_pval < 0.01 else "**" if dm_pval < 0.05 else "*" if dm_pval < 0.10 else ""
    print(f"  {name} vs 12/VIX: DM={dm_stat:.4f}  p={dm_pval:.4f} {sig}")

# ============================================================
# 10. INSURANCE PREMIUM OVER TIME
# ============================================================
print("\n" + "=" * 70)
print("ROLLING INSURANCE PREMIUM OVER TIME")
print("=" * 70)

# Rolling 252-day annualized insurance premium
rolling_premium = ins_premium_daily.rolling(252).mean() * 252
rp = rolling_premium.dropna()
print(f"\nRolling 252d Insurance Premium:")
print(f"  Mean: {rp.mean():.4f}")
print(f"  Std: {rp.std():.4f}")
print(f"  Min: {rp.min():.4f} ({rp.idxmin().date()})")
print(f"  Max: {rp.max():.4f} ({rp.idxmax().date()})")
print(f"  % time negative (VT outperforms): {(rp < 0).mean():.1%}")

# ============================================================
# 11. REGIME CONDITIONAL ANALYSIS
# ============================================================
print("\n" + "=" * 70)
print("VIX REGIME x VoV QUINTILE ANALYSIS")
print("=" * 70)

# VIX regimes: <15, 15-20, 20-30, >30
vix_shifted = vix.shift(1)  # yesterday's VIX
vix_regimes = pd.cut(vix_shifted, bins=[0, 15, 20, 30, 100], labels=['<15', '15-20', '20-30', '>30'])

regime_vov_premium = {}
for regime in ['<15', '15-20', '20-30', '>30']:
    regime_mask = (vix_regimes == regime).reindex(ins_premium_daily.index, fill_value=False)
    for q in [1, 3, 5]:  # low, mid, high VoV
        q_mask = (quintile_fast == q).reindex(ins_premium_daily.index, fill_value=False)
        combined = regime_mask & q_mask
        subset = ins_premium_daily[combined]
        if len(subset) < 20:
            continue
        ann_prem = subset.mean() * 252
        key = f"VIX{regime}_VoVQ{q}"
        regime_vov_premium[key] = {
            'ann_premium': round(ann_prem, 4),
            'n_days': len(subset),
        }
        print(f"  VIX {regime} + VoV Q{q}: Premium={ann_prem:+.4f}  (n={len(subset)})")

# ============================================================
# 12. STRATEGY TURNOVER
# ============================================================
print("\n" + "=" * 70)
print("STRATEGY TURNOVER ANALYSIS")
print("=" * 70)

turnover_results = {}
for name, w_series in [('12/VIX', w_12vix), ('VoV-Adj', w_vov_adj),
                         ('VoV-Off', w_vov_off), ('Smooth VoV', w_smooth_vov)]:
    w = w_series.loc[start_full:'2025-12-31'].dropna()
    daily_turnover = w.diff().abs()
    ann_turnover = daily_turnover.mean() * 252
    turnover_results[name] = round(ann_turnover, 4)
    print(f"  {name}: Ann Turnover = {ann_turnover:.4f}")

# ============================================================
# 13. CROSS-OOS VALIDATION (5 non-overlapping 2-year periods)
# ============================================================
print("\n" + "=" * 70)
print("CROSS-OOS VALIDATION (5 x 2-year periods)")
print("=" * 70)

oos_periods = [
    ('2007-01-01', '2008-12-31'),
    ('2009-01-01', '2010-12-31'),
    ('2011-01-01', '2012-12-31'),
    ('2017-01-01', '2018-12-31'),
    ('2023-01-01', '2024-12-31'),
]

cross_oos = {}
for name, ret in strategies.items():
    wins = 0
    sharpes = []
    for start, end in oos_periods:
        m = calc_metrics(ret, start, end)
        bh_m = calc_metrics(ret_bh, start, end)
        if m and bh_m:
            sharpes.append(m['sharpe'])
            if m['sharpe'] > bh_m['sharpe']:
                wins += 1
    cross_oos[name] = {
        'wins_vs_bh': wins,
        'total_periods': len(oos_periods),
        'avg_sharpe': round(np.mean(sharpes), 4) if sharpes else None,
    }
    print(f"  {name}: {wins}/{len(oos_periods)} periods beat BH 50/50  "
          f"(avg Sharpe={np.mean(sharpes):.4f})")

# ============================================================
# 14. CRASH PROTECTION CHECK
# ============================================================
print("\n" + "=" * 70)
print("CRASH PROTECTION CHECK (worst drawdown periods)")
print("=" * 70)

crash_periods = [
    ('GFC', '2008-09-01', '2009-03-31'),
    ('COVID', '2020-02-19', '2020-03-23'),
    ('2022 Bear', '2022-01-03', '2022-10-12'),
]

crash_results = {}
for crash_name, start, end in crash_periods:
    print(f"\n  {crash_name} ({start} to {end}):")
    crash_results[crash_name] = {}
    for name, ret in strategies.items():
        r = ret.loc[start:end].dropna()
        if len(r) > 0:
            cum_ret = (1 + r).prod() - 1
            crash_results[crash_name][name] = round(cum_ret, 4)
            print(f"    {name}: {cum_ret:+.4f}")

# ============================================================
# 15. KEY FINDING: IS VoV TIMING VALUABLE?
# ============================================================
print("\n" + "=" * 70)
print("KEY FINDINGS SUMMARY")
print("=" * 70)

# Compare VoV strategies to static 12/VIX
static_sharpe = full_metrics.get('12/VIX (Static VT)', {}).get('sharpe', 0)
bh_sharpe = full_metrics.get('BH 50/50', {}).get('sharpe', 0)

best_vov_name = None
best_vov_sharpe = -999
for name in ['VoV-Adjusted VT', 'VoV-Off VT', 'Smooth VoV VT']:
    s = full_metrics.get(name, {}).get('sharpe', -999)
    if s > best_vov_sharpe:
        best_vov_sharpe = s
        best_vov_name = name

sharpe_improvement = best_vov_sharpe - static_sharpe
sharpe_se = 1.0 / np.sqrt(full_metrics.get(best_vov_name, {}).get('n_days', 1000))

# Harvey threshold: t > 3.0
t_improvement = sharpe_improvement / sharpe_se if sharpe_se > 0 else 0

print(f"\n1. Static 12/VIX Sharpe: {static_sharpe:.4f}")
print(f"   BH 50/50 Sharpe: {bh_sharpe:.4f}")
print(f"   Best VoV strategy ({best_vov_name}): {best_vov_sharpe:.4f}")
print(f"   Sharpe improvement over static VT: {sharpe_improvement:+.4f}")
print(f"   Harvey t-stat: {t_improvement:.2f} (threshold: 3.0)")

# Check quintile spread
if quintile_analysis:
    q1_prem = quintile_analysis.get('Q1', {}).get('ann_premium', 0)
    q5_prem = quintile_analysis.get('Q5', {}).get('ann_premium', 0)
    print(f"\n2. Insurance Premium Quintile Spread:")
    print(f"   Q1 (low VoV): {q1_prem:+.4f}/yr")
    print(f"   Q5 (high VoV): {q5_prem:+.4f}/yr")
    print(f"   Spread (Q5-Q1): {q5_prem - q1_prem:+.4f}/yr")

# Crash protection assessment
print(f"\n3. Crash Protection:")
for crash_name in crash_results:
    bh_loss = crash_results[crash_name].get('BH 50/50', 0)
    vt_loss = crash_results[crash_name].get('12/VIX (Static VT)', 0)
    best_loss = crash_results[crash_name].get(best_vov_name, 0) if best_vov_name else 0
    print(f"   {crash_name}: BH={bh_loss:+.4f}  Static VT={vt_loss:+.4f}  "
          f"Best VoV={best_loss:+.4f}")

# Verdict
if abs(t_improvement) < 3.0:
    verdict = "NULL — VoV timing does NOT significantly improve VT insurance"
    codex_rating = "0 (null result, consistent with VIX sufficiency)"
else:
    if sharpe_improvement > 0:
        verdict = "POSITIVE — VoV timing significantly improves VT insurance"
        codex_rating = "TBD (needs Codex review)"
    else:
        verdict = "NEGATIVE — VoV timing significantly WORSENS VT insurance"
        codex_rating = "0 (null/negative)"

print(f"\n{'='*70}")
print(f"VERDICT: {verdict}")
print(f"Codex Rating: {codex_rating}")
print(f"{'='*70}")

# ============================================================
# 16. SAVE RESULTS
# ============================================================
results = {
    'experiment_id': 'K786',
    'title': 'Convexity-Adjusted VT Insurance Premium — When is VT insurance overpriced?',
    'proposed_by': 'Gemini',
    'executed_by': 'Claude',
    'date': datetime.now().isoformat(),
    'data_source': 'yfinance SPY/GLD/^VIX',
    'data_period': '2007-01-01 to 2025-12-31',
    'oos_period': '2023-01-01 to 2024-12-31',
    'methodology': {
        'VoV_definition': 'rolling 22-day std of daily VIX changes',
        'insurance_premium': '12/VIX strategy return minus BH 50/50 return',
        'quintile_assignment': 'expanding percentile (no lookahead)',
        'lag': 'signal.shift(1) — VIX/VoV from yesterday, return today',
        'strategies': {
            'BH_5050': 'Buy & Hold 50% SPY + 50% GLD',
            '12_VIX': 'w_spy = 12/VIX, w_gld = 1-w_spy',
            'VoV_Adjusted': 'Low VoV → 18/VIX (less insurance), High VoV → 12/VIX',
            'VoV_Off': 'Very low VoV (<P25) → 50/50 (no insurance), else 12/VIX',
            'Smooth_VoV': 'effective_target = 24 - 12*vov_rank, w = target/VIX',
        },
    },
    'full_period_metrics': full_metrics,
    'oos_metrics': oos_metrics,
    'crra_utility': utility_results,
    'insurance_premium_by_quintile': quintile_analysis,
    'forward_insurance_value': forward_analysis,
    'dm_tests': dm_results,
    'rolling_premium_stats': {
        'mean': round(rp.mean(), 4),
        'std': round(rp.std(), 4),
        'min': round(rp.min(), 4),
        'max': round(rp.max(), 4),
        'pct_time_negative': round((rp < 0).mean(), 4),
    },
    'regime_vov_premium': regime_vov_premium,
    'turnover': turnover_results,
    'cross_oos_validation': cross_oos,
    'crash_protection': crash_results,
    'verdict': verdict,
    'codex_rating': codex_rating,
    'key_findings': {
        'static_vt_sharpe': static_sharpe,
        'bh_sharpe': bh_sharpe,
        'best_vov_strategy': best_vov_name,
        'best_vov_sharpe': best_vov_sharpe,
        'sharpe_improvement': round(sharpe_improvement, 4),
        'harvey_t_stat': round(t_improvement, 2),
        'passes_harvey_threshold': abs(t_improvement) >= 3.0,
    },
    'references': [
        'K41: VT insurance premium ~4%/yr',
        'K649: VoV adjustment hurts Sharpe (0.527 vs 0.680)',
        'K687: No VT beats BH 50/50 on Sharpe',
        'K688: VT wins CRRA utility gamma>=5',
        'K74: VT underperforms 80% of time',
        'Gemini: VoV clustering for insurance pricing',
    ],
}

results_path = 'experiments/k786_vt_insurance_premium_results.json'
with open(results_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to {results_path}")
print("DONE.")
