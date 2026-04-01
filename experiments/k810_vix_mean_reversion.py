"""
K810: VIX Mean-Reversion Trading Strategy
==========================================
[提出: 用戶, 執行: Claude]

Hypothesis:
- VIX exhibits strong mean-reversion (AR(1) ρ=0.969, half-life ~22 days)
- After VIX spikes, markets tend to recover — can we systematically exploit this?

Literature:
- Whaley (2009): VIX as investor fear gauge, mean-reverting process
- Simon & Campasano (2014): VIX futures term structure and mean-reversion
- Bollen & Whaley (2004): VIX smile dynamics imply mean-reversion in vol
- Bollerslev, Tauchen & Zhou (2009): VRP predicts equity returns

Prior work:
- K430/K491: VIX has strong mean-reversion properties (half-life ~22d)
- K503: 4 VIX MR strategies all WORSE than 12/VIX. "12/VIX IS the MR trade"
  → K503 used full-sample statistics (lookahead). K810 uses expanding window.
  → K503 used crude binary signals. K810 adds continuous signal variants.
  → K503 had no cross-OOS. K810 does 5×2-year cross-OOS.
- N182: Excess Fear Signal (VIX/GARCH z-score) passed Harvey t>3.0 for 5d returns
- K734: VRP strategies all null vs 12/VIX

Differentiation from K503:
1. Expanding window for ALL statistics (no lookahead in z-scores/percentiles)
2. VIX spike event analysis (duration, amplitude, SPY recovery)
3. Continuous signal variants (not just binary)
4. Cross-OOS 5×2-year validation
5. DM test with Harvey t>3.0 threshold
6. TX costs 5bps per weight change

Data: yfinance (SPY, GLD, ^VIX), 2006-2026
OOS: 2023-01-01 ~ 2024-12-31
"""

import numpy as np
import pandas as pd
import yfinance as yf
import json
import warnings
from datetime import datetime
from scipy import stats
from collections import OrderedDict

warnings.filterwarnings('ignore')

# ========================================
# CONFIGURATION
# ========================================
TX_COST_BPS = 5  # basis points per one-way
TX_COST = TX_COST_BPS / 10000
MIN_EXPANDING_WINDOW = 252  # 1 year before generating signals
OOS_START = '2023-01-01'
OOS_END = '2024-12-31'
CROSS_OOS_PERIODS = [
    ('2008-01-01', '2009-12-31'),  # GFC
    ('2012-01-01', '2013-12-31'),  # Recovery
    ('2016-01-01', '2017-12-31'),  # Low vol
    ('2020-01-01', '2021-12-31'),  # COVID
    ('2023-01-01', '2024-12-31'),  # Recent
]

# ========================================
# DATA COLLECTION
# ========================================
print("=" * 70)
print("K810: VIX Mean-Reversion Trading Strategy")
print("=" * 70)

tickers = {'SPY': 'SPY', 'GLD': 'GLD', 'VIX': '^VIX'}
data = {}
for name, ticker in tickers.items():
    df = yf.download(ticker, start='2005-01-01', end='2026-04-01', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    data[name] = df['Close'].rename(name)

prices = pd.DataFrame(data).dropna()
print(f"\nData period: {prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}")
print(f"Total observations: {len(prices)}")

# Returns
spy_ret = prices['SPY'].pct_change()
gld_ret = prices['GLD'].pct_change()
vix = prices['VIX']

# ========================================
# PART A: VIX MEAN-REVERSION CHARACTERISTICS
# ========================================
print("\n" + "=" * 70)
print("PART A: VIX MEAN-REVERSION CHARACTERISTICS")
print("=" * 70)

# A1: AR(1) estimation
print("\n--- A1: AR(1) Estimation ---")
vix_clean = vix.dropna()
vix_lag = vix_clean.shift(1).dropna()
vix_curr = vix_clean.reindex(vix_lag.index)
slope, intercept, r, p, se = stats.linregress(vix_lag, vix_curr)
half_life = np.log(2) / (-np.log(abs(slope)))
long_run_mean = intercept / (1 - slope)
print(f"  AR(1) coefficient: {slope:.4f}")
print(f"  Intercept: {intercept:.4f}")
print(f"  Long-run mean: {long_run_mean:.2f}")
print(f"  Half-life: {half_life:.1f} trading days ({half_life/21:.1f} months)")
print(f"  R²: {r**2:.4f}")

# A2: VIX spike events (expanding window)
print("\n--- A2: VIX Spike Event Analysis (expanding window) ---")

# Calculate expanding mean, std, z-score
vix_expanding_mean = vix.expanding(min_periods=MIN_EXPANDING_WINDOW).mean()
vix_expanding_std = vix.expanding(min_periods=MIN_EXPANDING_WINDOW).std()
vix_zscore = (vix - vix_expanding_mean) / vix_expanding_std

# VIX 1-day change
vix_daily_change = vix.diff()
vix_daily_pct_change = vix.pct_change()

# Expanding std of daily VIX changes
vix_change_expanding_std = vix_daily_change.expanding(min_periods=MIN_EXPANDING_WINDOW).std()

# Spike = 1-day VIX increase > 2σ of expanding change std
spike_threshold = 2.0
is_spike = vix_daily_change > (spike_threshold * vix_change_expanding_std)
is_spike = is_spike.fillna(False)

# Analyze each spike event
spike_dates = vix.index[is_spike]
print(f"  Total spike events (VIX 1d change > {spike_threshold}σ): {len(spike_dates)}")

spike_events = []
for spike_date in spike_dates:
    spike_idx = vix.index.get_loc(spike_date)
    spike_vix = vix.iloc[spike_idx]
    pre_spike_vix = vix.iloc[spike_idx - 1] if spike_idx > 0 else np.nan
    spike_change = spike_vix - pre_spike_vix
    spike_pct = spike_change / pre_spike_vix * 100 if pre_spike_vix > 0 else np.nan

    # How long until VIX returns to pre-spike level?
    recovery_days = np.nan
    for j in range(1, min(126, len(vix) - spike_idx)):  # look up to 6 months
        if vix.iloc[spike_idx + j] <= pre_spike_vix:
            recovery_days = j
            break

    # SPY return over recovery period
    spy_ret_recovery = np.nan
    if not np.isnan(recovery_days):
        spy_price_at_spike = prices['SPY'].iloc[spike_idx]
        spy_price_at_recovery = prices['SPY'].iloc[spike_idx + int(recovery_days)]
        spy_ret_recovery = (spy_price_at_recovery / spy_price_at_spike - 1) * 100

    # SPY returns at fixed horizons post-spike
    spy_rets_post = {}
    for h in [1, 5, 10, 22, 44]:
        if spike_idx + h < len(prices):
            val = (prices['SPY'].iloc[spike_idx + h] / prices['SPY'].iloc[spike_idx] - 1) * 100
            spy_rets_post[f'{h}d'] = float(val) if not np.isnan(val) else None
        else:
            spy_rets_post[f'{h}d'] = None

    spike_events.append({
        'date': spike_date.strftime('%Y-%m-%d'),
        'spike_vix': float(spike_vix),
        'pre_spike_vix': float(pre_spike_vix),
        'spike_change': float(spike_change),
        'spike_pct': float(spike_pct) if not np.isnan(spike_pct) else None,
        'recovery_days': int(recovery_days) if not np.isnan(recovery_days) else None,
        'spy_ret_recovery_pct': float(spy_ret_recovery) if not np.isnan(spy_ret_recovery) else None,
        'spy_rets_post': spy_rets_post,
    })

# Summary statistics of spike events
valid_recovery = [e for e in spike_events if e['recovery_days'] is not None]
if valid_recovery:
    rec_days = [e['recovery_days'] for e in valid_recovery]
    spy_rec = [e['spy_ret_recovery_pct'] for e in valid_recovery if e['spy_ret_recovery_pct'] is not None]
    print(f"\n  Spike events with recovery: {len(valid_recovery)}/{len(spike_events)}")
    print(f"  Recovery days: median={np.median(rec_days):.0f}, mean={np.mean(rec_days):.1f}, "
          f"25th={np.percentile(rec_days, 25):.0f}, 75th={np.percentile(rec_days, 75):.0f}")
    if spy_rec:
        print(f"  SPY return during recovery: median={np.median(spy_rec):.2f}%, mean={np.mean(spy_rec):.2f}%")

# Post-spike returns at fixed horizons
print("\n  Average SPY return after spike:")
for h in ['1d', '5d', '10d', '22d', '44d']:
    vals = [e['spy_rets_post'].get(h) for e in spike_events if e['spy_rets_post'].get(h) is not None]
    if vals:
        mean_r = np.mean(vals)
        t_stat_r = np.mean(vals) / (np.std(vals, ddof=1) / np.sqrt(len(vals))) if np.std(vals, ddof=1) > 0 else 0
        print(f"    {h}: mean={mean_r:+.3f}%, t={t_stat_r:.2f}, n={len(vals)}")

# ========================================
# PART B: STRATEGY CONSTRUCTION
# ========================================
print("\n" + "=" * 70)
print("PART B: STRATEGY CONSTRUCTION")
print("=" * 70)

# Common index with valid data
valid_idx = prices.index[MIN_EXPANDING_WINDOW:]
spy_ret_valid = spy_ret.reindex(valid_idx)
gld_ret_valid = gld_ret.reindex(valid_idx)

# --- S0: Buy & Hold 50/50 SPY/GLD (Baseline) ---
print("\n--- S0: Buy & Hold 50/50 SPY/GLD ---")
s0_weights_spy = pd.Series(0.5, index=valid_idx)
s0_weights_gld = pd.Series(0.5, index=valid_idx)

# --- S1: VIX Spike Recovery Strategy ---
print("\n--- S1: VIX Spike Recovery Strategy ---")
# After a VIX spike, wait 1 day then go 80/20 SPY/GLD
# Return to 50/50 when VIX z-score drops below 0 (back to mean)
# Uses expanding window z-score

s1_weights_spy = pd.Series(0.5, index=valid_idx, dtype=float)
vix_zscore_valid = vix_zscore.reindex(valid_idx)
is_spike_valid = is_spike.reindex(valid_idx).fillna(False)

in_recovery = False
for i in range(len(valid_idx)):
    date = valid_idx[i]
    z = vix_zscore_valid.iloc[i]

    if i > 0 and is_spike_valid.iloc[i - 1]:  # Spike yesterday -> shift(1) for lag
        in_recovery = True

    if in_recovery and z <= 0:  # VIX back to mean
        in_recovery = False

    if in_recovery:
        s1_weights_spy.iloc[i] = 0.80  # Overweight SPY during recovery
    else:
        s1_weights_spy.iloc[i] = 0.50

# Apply shift(1) to ALL signals (critical: prevent lookahead)
s1_weights_spy = s1_weights_spy.shift(1).fillna(0.5)
s1_weights_gld = 1.0 - s1_weights_spy

# --- S2: VIX Percentile Strategy ---
print("\n--- S2: VIX Percentile Strategy ---")
# VIX > 80th expanding percentile → reduce SPY (20/80) — fear is high
# VIX < 20th expanding percentile → increase SPY (80/20) — complacency, ride trend
# Between → 50/50

# Expanding percentile rank
vix_expanding_rank = vix.expanding(min_periods=MIN_EXPANDING_WINDOW).apply(
    lambda x: stats.percentileofscore(x, x.iloc[-1], kind='rank') / 100,
    raw=False
)
vix_pctile_valid = vix_expanding_rank.reindex(valid_idx)

s2_weights_spy_raw = pd.Series(0.5, index=valid_idx, dtype=float)
for i in range(len(valid_idx)):
    pctile = vix_pctile_valid.iloc[i]
    if pd.isna(pctile):
        s2_weights_spy_raw.iloc[i] = 0.5
    elif pctile > 0.80:
        s2_weights_spy_raw.iloc[i] = 0.20  # High VIX → reduce equity
    elif pctile < 0.20:
        s2_weights_spy_raw.iloc[i] = 0.80  # Low VIX → increase equity
    else:
        s2_weights_spy_raw.iloc[i] = 0.50

# shift(1) to prevent lookahead
s2_weights_spy = s2_weights_spy_raw.shift(1).fillna(0.5)
s2_weights_gld = 1.0 - s2_weights_spy

# --- S3: Contrarian Mean-Reversion Strategy ---
print("\n--- S3: Contrarian Mean-Reversion (VIX z-score) ---")
# VIX z-score > 2 → BUY SPY (contrarian: extreme fear → expect reversal)
# VIX z-score < -1 → REDUCE SPY (complacency → expect vol increase)
# Uses expanding window z-score

s3_weights_spy_raw = pd.Series(0.5, index=valid_idx, dtype=float)
for i in range(len(valid_idx)):
    z = vix_zscore_valid.iloc[i]
    if pd.isna(z):
        s3_weights_spy_raw.iloc[i] = 0.5
    elif z > 2.0:
        s3_weights_spy_raw.iloc[i] = 0.80  # Extreme fear → contrarian buy
    elif z > 1.0:
        s3_weights_spy_raw.iloc[i] = 0.65  # Elevated fear → moderate buy
    elif z < -1.0:
        s3_weights_spy_raw.iloc[i] = 0.30  # Complacency → reduce
    else:
        s3_weights_spy_raw.iloc[i] = 0.50

# shift(1) to prevent lookahead
s3_weights_spy = s3_weights_spy_raw.shift(1).fillna(0.5)
s3_weights_gld = 1.0 - s3_weights_spy

# --- S4: 12/VIX Strategy (Baseline VT) ---
print("\n--- S4: 12/VIX Strategy ---")
vix_valid = vix.reindex(valid_idx)
s4_weights_spy_raw = (12.0 / vix_valid).clip(0.0, 1.0)
# shift(1) to prevent lookahead
s4_weights_spy = s4_weights_spy_raw.shift(1).fillna(0.5)
s4_weights_gld = 1.0 - s4_weights_spy

# --- S5: Continuous Contrarian (smooth signal) ---
print("\n--- S5: Continuous Contrarian (smooth) ---")
# Map z-score linearly to weight: z=+3 → w_spy=1.0, z=-3 → w_spy=0.0, z=0 → w_spy=0.5
# INVERTED from naive: higher fear → more equity (contrarian)
s5_weights_spy_raw = (0.5 + vix_zscore_valid / 6.0).clip(0.0, 1.0)
s5_weights_spy = s5_weights_spy_raw.shift(1).fillna(0.5)
s5_weights_gld = 1.0 - s5_weights_spy

# ========================================
# PART C: STRATEGY EVALUATION
# ========================================
print("\n" + "=" * 70)
print("PART C: STRATEGY EVALUATION")
print("=" * 70)


def compute_portfolio_return(w_spy, w_gld, r_spy, r_gld, tx_cost=TX_COST):
    """Compute portfolio returns with transaction costs."""
    weight_change = w_spy.diff().abs().fillna(0)
    tx = weight_change * tx_cost * 2  # Both legs
    port_ret = w_spy * r_spy + w_gld * r_gld - tx
    return port_ret


def compute_metrics(returns, label=""):
    """Compute standard performance metrics."""
    clean = returns.dropna()
    if len(clean) < 50:
        return None

    ann_ret = clean.mean() * 252
    ann_vol = clean.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cum = (1 + clean).cumprod()
    mdd = ((cum / cum.cummax()) - 1).min()

    # CAGR
    years = len(clean) / 252
    total_ret = cum.iloc[-1] if len(cum) > 0 else 1
    cagr = total_ret ** (1 / years) - 1 if years > 0 and total_ret > 0 else 0

    return {
        'label': label,
        'sharpe': float(sharpe),
        'cagr': float(cagr),
        'ann_ret': float(ann_ret),
        'ann_vol': float(ann_vol),
        'mdd': float(mdd),
        'n_obs': int(len(clean)),
        'years': float(years),
        'total_return': float(total_ret - 1),
    }


# All strategies
strategies = OrderedDict()
strategies['S0_BH_5050'] = (s0_weights_spy, s0_weights_gld)
strategies['S1_Spike_Recovery'] = (s1_weights_spy, s1_weights_gld)
strategies['S2_VIX_Percentile'] = (s2_weights_spy, s2_weights_gld)
strategies['S3_Contrarian_MR'] = (s3_weights_spy, s3_weights_gld)
strategies['S4_12_VIX'] = (s4_weights_spy, s4_weights_gld)
strategies['S5_Continuous_Contrarian'] = (s5_weights_spy, s5_weights_gld)

# Compute returns for each strategy
strat_returns = {}
for name, (w_spy, w_gld) in strategies.items():
    strat_returns[name] = compute_portfolio_return(
        w_spy.reindex(valid_idx),
        w_gld.reindex(valid_idx),
        spy_ret_valid,
        gld_ret_valid,
    )

# --- C1: Full Sample Performance ---
print("\n--- C1: Full Sample Performance ---")
full_metrics = {}
print(f"\n{'Strategy':<30} {'Sharpe':>8} {'CAGR':>8} {'MDD':>8} {'AnnVol':>8}")
print("-" * 70)
for name, ret in strat_returns.items():
    m = compute_metrics(ret, name)
    if m:
        full_metrics[name] = m
        print(f"  {name:<28} {m['sharpe']:>8.3f} {m['cagr']:>7.1%} {m['mdd']:>7.1%} {m['ann_vol']:>7.1%}")

# --- C2: OOS Performance ---
print(f"\n--- C2: OOS Performance ({OOS_START} to {OOS_END}) ---")
oos_metrics = {}
print(f"\n{'Strategy':<30} {'Sharpe':>8} {'CAGR':>8} {'MDD':>8} {'AnnVol':>8}")
print("-" * 70)
for name, ret in strat_returns.items():
    oos_ret = ret[(ret.index >= OOS_START) & (ret.index <= OOS_END)]
    m = compute_metrics(oos_ret, name + '_OOS')
    if m:
        oos_metrics[name] = m
        print(f"  {name:<28} {m['sharpe']:>8.3f} {m['cagr']:>7.1%} {m['mdd']:>7.1%} {m['ann_vol']:>7.1%}")

# --- C3: DM Tests (Harvey t>3.0) ---
print("\n--- C3: DM Tests vs S0 (baseline) ---")
# Import strategy_dm_test
try:
    from volpred.stats.model_evaluation import strategy_dm_test
    has_dm = True
except ImportError:
    has_dm = False
    print("  WARNING: strategy_dm_test not available, using manual DM test")

dm_results = {}
baseline_ret = strat_returns['S0_BH_5050'].dropna()

for name, ret in strat_returns.items():
    if name == 'S0_BH_5050':
        continue

    # Align returns
    common = baseline_ret.index.intersection(ret.dropna().index)
    r1 = ret.reindex(common).values
    r0 = baseline_ret.reindex(common).values

    if has_dm:
        t_stat, p_val = strategy_dm_test(r1, r0, h=1, loss_fn='negative_return')
    else:
        # Manual DM test
        d = r1 - r0  # loss differential
        d_bar = np.mean(d)
        # HAC variance (Newey-West with h-1 lags)
        n = len(d)
        gamma0 = np.var(d, ddof=1)
        var_d = gamma0 / n
        if var_d > 0:
            t_stat = d_bar / np.sqrt(var_d)
            p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
        else:
            t_stat, p_val = 0.0, 1.0

    sig = '***' if abs(t_stat) > 3.0 else ('**' if abs(t_stat) > 2.0 else ('*' if abs(t_stat) > 1.65 else ''))
    direction = 'BETTER' if t_stat < 0 else 'WORSE'  # Negative t → strategy 1 is better
    dm_results[name] = {
        't_stat': float(t_stat),
        'p_value': float(p_val),
        'direction': direction,
        'significant_harvey': bool(abs(t_stat) > 3.0),
    }
    print(f"  {name:<28} t={t_stat:>7.3f} p={p_val:.4f} {direction} {sig}")

# DM tests vs S4 (12/VIX)
print("\n--- C4: DM Tests vs S4 (12/VIX) ---")
dm_vs_12vix = {}
s4_ret = strat_returns['S4_12_VIX'].dropna()

for name, ret in strat_returns.items():
    if name in ('S0_BH_5050', 'S4_12_VIX'):
        continue

    common = s4_ret.index.intersection(ret.dropna().index)
    r1 = ret.reindex(common).values
    r4 = s4_ret.reindex(common).values

    if has_dm:
        t_stat, p_val = strategy_dm_test(r1, r4, h=1, loss_fn='negative_return')
    else:
        d = r1 - r4
        d_bar = np.mean(d)
        n = len(d)
        gamma0 = np.var(d, ddof=1)
        var_d = gamma0 / n
        t_stat = d_bar / np.sqrt(var_d) if var_d > 0 else 0.0
        p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1)) if var_d > 0 else 1.0

    sig = '***' if abs(t_stat) > 3.0 else ('**' if abs(t_stat) > 2.0 else ('*' if abs(t_stat) > 1.65 else ''))
    direction = 'BETTER' if t_stat < 0 else 'WORSE'
    dm_vs_12vix[name] = {
        't_stat': float(t_stat),
        'p_value': float(p_val),
        'direction': direction,
        'significant_harvey': bool(abs(t_stat) > 3.0),
    }
    print(f"  {name:<28} t={t_stat:>7.3f} p={p_val:.4f} {direction} {sig}")

# ========================================
# PART D: CROSS-OOS VALIDATION (5 × 2-year)
# ========================================
print("\n" + "=" * 70)
print("PART D: CROSS-OOS VALIDATION (5 × 2-year)")
print("=" * 70)

cross_oos_results = {}
for name, ret in strat_returns.items():
    cross_oos_results[name] = {}

for period_name, (start, end) in zip(
    ['GFC', 'Recovery', 'Low_Vol', 'COVID', 'Recent'],
    CROSS_OOS_PERIODS
):
    print(f"\n--- Period: {period_name} ({start} to {end}) ---")
    print(f"  {'Strategy':<28} {'Sharpe':>8} {'CAGR':>8} {'MDD':>8}")
    print("  " + "-" * 56)

    for name, ret in strat_returns.items():
        period_ret = ret[(ret.index >= start) & (ret.index <= end)]
        m = compute_metrics(period_ret, f"{name}_{period_name}")
        if m:
            cross_oos_results[name][period_name] = m
            print(f"  {name:<28} {m['sharpe']:>8.3f} {m['cagr']:>7.1%} {m['mdd']:>7.1%}")

# Summary: how many periods does each strategy beat BH 50/50?
print("\n--- Cross-OOS Summary: Sharpe vs BH 50/50 ---")
cross_oos_wins = {}
for name in strat_returns.keys():
    if name == 'S0_BH_5050':
        continue
    wins = 0
    total = 0
    for period_name in ['GFC', 'Recovery', 'Low_Vol', 'COVID', 'Recent']:
        if period_name in cross_oos_results.get(name, {}) and period_name in cross_oos_results.get('S0_BH_5050', {}):
            total += 1
            if cross_oos_results[name][period_name]['sharpe'] > cross_oos_results['S0_BH_5050'][period_name]['sharpe']:
                wins += 1
    cross_oos_wins[name] = {'wins': wins, 'total': total, 'win_rate': wins / total if total > 0 else 0}
    print(f"  {name:<28} Wins: {wins}/{total} ({wins/total*100:.0f}%)")

# ========================================
# PART E: WEIGHT CHANGE ANALYSIS
# ========================================
print("\n" + "=" * 70)
print("PART E: WEIGHT CHANGE ANALYSIS (TURNOVER)")
print("=" * 70)

turnover_results = {}
for name, (w_spy, w_gld) in strategies.items():
    w = w_spy.reindex(valid_idx)
    changes = w.diff().abs().dropna()
    total_changes = changes.sum()
    avg_daily_change = changes.mean()
    days_with_change = (changes > 0.001).sum()  # non-trivial changes
    annual_turnover = total_changes / (len(changes) / 252) * 2  # two-way

    turnover_results[name] = {
        'total_weight_changes': float(total_changes),
        'avg_daily_change': float(avg_daily_change),
        'days_with_change': int(days_with_change),
        'pct_days_with_change': float(days_with_change / len(changes) * 100),
        'annual_turnover_2way': float(annual_turnover),
    }
    print(f"  {name:<28} Turnover={annual_turnover:.1f}x/yr, "
          f"Active days={days_with_change}/{len(changes)} ({days_with_change/len(changes)*100:.1f}%)")

# ========================================
# PART F: VIX RECOVERY PATTERN DEEP DIVE
# ========================================
print("\n" + "=" * 70)
print("PART F: VIX RECOVERY PATTERN DEEP DIVE")
print("=" * 70)

# Categorize spikes by severity
severity_bins = {
    'Small (5-15%)': (5, 15),
    'Medium (15-30%)': (15, 30),
    'Large (30-50%)': (30, 50),
    'Extreme (>50%)': (50, 999),
}

severity_analysis = {}
for sev_name, (lo, hi) in severity_bins.items():
    sev_events = [e for e in spike_events
                  if e['spike_pct'] is not None and lo <= abs(e['spike_pct']) < hi]

    if len(sev_events) < 3:
        continue

    rec_days_sev = [e['recovery_days'] for e in sev_events if e['recovery_days'] is not None]
    spy_5d = [e['spy_rets_post'].get('5d') for e in sev_events if e['spy_rets_post'].get('5d') is not None]
    spy_22d = [e['spy_rets_post'].get('22d') for e in sev_events if e['spy_rets_post'].get('22d') is not None]

    severity_analysis[sev_name] = {
        'n_events': len(sev_events),
        'median_recovery_days': float(np.median(rec_days_sev)) if rec_days_sev else None,
        'mean_spy_5d_return': float(np.mean(spy_5d)) if spy_5d else None,
        'mean_spy_22d_return': float(np.mean(spy_22d)) if spy_22d else None,
    }

    print(f"\n  {sev_name}: {len(sev_events)} events")
    if rec_days_sev:
        print(f"    Recovery days: median={np.median(rec_days_sev):.0f}, mean={np.mean(rec_days_sev):.1f}")
    if spy_5d:
        print(f"    SPY 5d return: mean={np.mean(spy_5d):+.3f}%")
    if spy_22d:
        print(f"    SPY 22d return: mean={np.mean(spy_22d):+.3f}%")

# ========================================
# PART G: KEY INSIGHT ANALYSIS
# ========================================
print("\n" + "=" * 70)
print("PART G: KEY INSIGHTS")
print("=" * 70)

# G1: Why 12/VIX is already the MR trade
# When VIX spikes from 15 to 30, 12/VIX goes from 0.8 to 0.4 (automatic de-risk)
# When VIX reverts back to 15, weight automatically goes back to 0.8 (re-risk)
vix_examples = [12, 15, 18, 20, 25, 30, 40, 50]
print("\n--- G1: 12/VIX as Implicit Mean-Reversion ---")
print(f"  {'VIX':>5} | {'12/VIX wt':>10} | {'Implied'}")
print("  " + "-" * 40)
for v in vix_examples:
    w = min(12.0 / v, 1.0)
    implied = 'Full equity' if w >= 0.95 else ('Overweight' if w > 0.6 else ('Neutral' if w > 0.4 else ('Underweight' if w > 0.2 else 'Minimal')))
    print(f"  {v:>5} | {w:>10.2f} | {implied}")

# G2: Correlation between strategies
print("\n--- G2: Strategy Return Correlation ---")
ret_df = pd.DataFrame(strat_returns)
corr = ret_df.corr()
print(corr.round(3).to_string())

# ========================================
# SAVE RESULTS
# ========================================
print("\n" + "=" * 70)
print("SAVING RESULTS")
print("=" * 70)

results = {
    'experiment_id': 'K810',
    'title': 'K810: VIX Mean-Reversion Trading Strategy',
    'proposer': '用戶',
    'executor': 'Claude',
    'timestamp': datetime.now().isoformat(),
    'data_source': 'yfinance (SPY, GLD, ^VIX)',
    'data_period': f"{prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}",
    'n_observations': int(len(prices)),
    'oos_period': f"{OOS_START} to {OOS_END}",

    'vix_characteristics': {
        'ar1_coefficient': float(slope),
        'half_life_days': float(half_life),
        'long_run_mean': float(long_run_mean),
        'total_spike_events': len(spike_events),
        'spike_events_with_recovery': len(valid_recovery),
        'median_recovery_days': float(np.median(rec_days)) if valid_recovery else None,
        'mean_recovery_days': float(np.mean(rec_days)) if valid_recovery else None,
    },

    'spike_severity_analysis': severity_analysis,

    'full_sample_metrics': full_metrics,
    'oos_metrics': oos_metrics,

    'dm_tests_vs_baseline': dm_results,
    'dm_tests_vs_12vix': dm_vs_12vix,

    'cross_oos_results': {},
    'cross_oos_wins': cross_oos_wins,

    'turnover': turnover_results,

    'spike_events_sample': spike_events[:20],  # First 20 events for reference

    'conclusion': '',
    'codex_reviewed': False,
}

# Flatten cross-OOS results for JSON
for name in strat_returns.keys():
    results['cross_oos_results'][name] = {}
    for period_name in ['GFC', 'Recovery', 'Low_Vol', 'COVID', 'Recent']:
        if period_name in cross_oos_results.get(name, {}):
            results['cross_oos_results'][name][period_name] = cross_oos_results[name][period_name]

# Determine conclusion
best_strat = max(full_metrics.items(), key=lambda x: x[1]['sharpe'])
best_oos = max(oos_metrics.items(), key=lambda x: x[1]['sharpe'])

any_beats_12vix_harvey = any(
    v['direction'] == 'BETTER' and v['significant_harvey']
    for v in dm_vs_12vix.values()
)

s4_sharpe = full_metrics.get('S4_12_VIX', {}).get('sharpe', 0)
s4_oos_sharpe = oos_metrics.get('S4_12_VIX', {}).get('sharpe', 0)

conclusion_parts = [
    f"Best full-sample: {best_strat[0]} (Sharpe {best_strat[1]['sharpe']:.3f})",
    f"Best OOS: {best_oos[0]} (Sharpe {best_oos[1]['sharpe']:.3f})",
    f"12/VIX: full Sharpe {s4_sharpe:.3f}, OOS Sharpe {s4_oos_sharpe:.3f}",
    f"Any strategy beats 12/VIX at Harvey t>3.0: {'YES' if any_beats_12vix_harvey else 'NO'}",
    f"VIX half-life: {half_life:.1f} days, {len(spike_events)} spike events detected",
]

# Check if explicit MR strategies beat 12/VIX
for name in ['S1_Spike_Recovery', 'S2_VIX_Percentile', 'S3_Contrarian_MR', 'S5_Continuous_Contrarian']:
    if name in dm_vs_12vix:
        d = dm_vs_12vix[name]
        conclusion_parts.append(
            f"{name} vs 12/VIX: t={d['t_stat']:.3f}, {d['direction']}, Harvey={'PASS' if d['significant_harvey'] else 'FAIL'}"
        )

conclusion = '. '.join(conclusion_parts) + '.'

# K503 comparison
conclusion += (
    f" K503 redux with expanding windows and cross-OOS: "
    f"confirms that 12/VIX IS already the optimal continuous mean-reversion trade "
    f"if no explicit MR strategy beats it at Harvey threshold."
    if not any_beats_12vix_harvey
    else f" NEW FINDING: An explicit MR strategy beats 12/VIX at Harvey threshold!"
)

results['conclusion'] = conclusion

print(f"\nCONCLUSION: {conclusion}")

# Save
output_path = '/Users/yhlai0911/Desktop/volpred-research/experiments/k810_vix_mean_reversion_results.json'
def sanitize_for_json(obj):
    """Replace NaN/Inf with None for JSON serialization."""
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_json(v) for v in obj]
    elif isinstance(obj, float) and (np.isnan(obj) or np.isinf(obj)):
        return None
    return obj

results = sanitize_for_json(results)

with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)

print(f"\nResults saved to: {output_path}")
print("\n" + "=" * 70)
print("K810 COMPLETE")
print("=" * 70)
