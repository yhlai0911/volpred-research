"""
K641: VT Strategy Performance by VIX Regime — Regime Decomposition Analysis
=============================================================================
Motivation: K640 Live Audit found pure SPY VT strategies (GARCH VT, 12/VIX)
struggled in 2025 (Sharpe 0.23-0.26) while Piecewise Conservative thrived
(Sharpe 3.98). Hypothesis: VT strategies that go to ZERO exposure during
high VIX protect capital but miss rebounds.

Data Sources:
  - paper_trading.json (actual strategy returns, 2023-01 to 2026-03)
  - yfinance: ^VIX daily close (for regime classification)

References:
  - Fleming, Kirby & Ostdiek (2001, 2003) - VT framework
  - K640 Live Audit results
  - K499 rebalancing frequency analysis
"""

import json
import os
import sys
import warnings
from datetime import datetime, timezone
from collections import defaultdict

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')

# ─── Paths ──────────────────────────────────────────────────────────────
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PT_PATH = os.path.join(REPO, 'storage', 'paper_trading.json')
RESULTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            'k641_results.json')

# ─── 1. Load Paper Trading Data ────────────────────────────────────────
print("=" * 70)
print("K641: VT Strategy Performance by VIX Regime")
print("=" * 70)

with open(PT_PATH) as f:
    pt_data = json.load(f)

# Strategies to analyze (US-market, VIX-relevant)
STRATEGY_KEYS = [
    'slow_vt',             # GARCH VT (SPY) — continuous scaling
    'simple_12vix',        # 12/VIX (SPY) — continuous scaling
    'piecewise_conservative',  # Piecewise — discrete brackets
    'recommended_5050',    # 50/50 SPY/GLD — multi-asset
    'risk_parity',         # Risk Parity — multi-asset
    'vix_cond_leverage',   # VIX conditional leverage
    'fear_dca',            # Fear DCA — always-invested baseline
    'adaptive_tier',       # Adaptive tier — discrete brackets
]

STRATEGY_LABELS = {
    'slow_vt': 'GARCH VT (SPY)',
    'simple_12vix': '12/VIX (SPY)',
    'piecewise_conservative': 'Piecewise Conservative',
    'recommended_5050': '50/50 SPY/GLD',
    'risk_parity': 'Risk Parity (SPY+GLD)',
    'vix_cond_leverage': 'VIX Cond Leverage',
    'fear_dca': 'Fear DCA',
    'adaptive_tier': 'Adaptive Tier',
}

ARCHITECTURE = {
    'slow_vt': 'continuous',
    'simple_12vix': 'continuous',
    'piecewise_conservative': 'piecewise',
    'recommended_5050': 'multi_asset',
    'risk_parity': 'multi_asset',
    'vix_cond_leverage': 'conditional',
    'fear_dca': 'always_invested',
    'adaptive_tier': 'piecewise',
}

# Build DataFrames for each strategy
strategy_dfs = {}
for key in STRATEGY_KEYS:
    if key not in pt_data:
        print(f"  [SKIP] {key} not found in paper_trading.json")
        continue
    raw = pt_data[key]
    entries = raw.get('entries', raw) if isinstance(raw, dict) else raw
    if not isinstance(entries, list) or len(entries) == 0:
        continue

    rows = []
    for e in entries:
        date_str = e.get('data_date') or e.get('trade_date')
        ret = e.get('portfolio_return')
        weights = e.get('weights', {})
        cash = e.get('cash_weight', 0)
        total_weight = sum(weights.values()) if weights else 0
        spy_w = weights.get('SPY', 0)
        gld_w = weights.get('GLD', 0)
        rows.append({
            'date': pd.Timestamp(date_str),
            'return': ret if ret is not None else 0.0,
            'total_weight': total_weight,
            'spy_weight': spy_w,
            'gld_weight': gld_w,
            'cash_weight': cash,
        })

    df = pd.DataFrame(rows).set_index('date').sort_index()
    df = df[~df.index.duplicated(keep='first')]
    strategy_dfs[key] = df
    print(f"  Loaded {key}: {len(df)} days ({df.index[0].date()} to {df.index[-1].date()})")

# ─── 2. Get VIX Data from yfinance ─────────────────────────────────────
print("\nDownloading VIX data from yfinance...")
import yfinance as yf

vix = yf.download('^VIX', start='2022-12-01', end='2026-04-01', progress=False)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)
vix_close = vix['Close'].dropna()
vix_close.index = pd.to_datetime(vix_close.index).tz_localize(None)
print(f"  VIX: {len(vix_close)} days ({vix_close.index[0].date()} to {vix_close.index[-1].date()})")
print(f"  VIX range: {vix_close.min():.1f} – {vix_close.max():.1f}")
print(f"  VIX mean: {vix_close.mean():.1f}, median: {vix_close.median():.1f}")

# Also get SPY for buy-and-hold benchmark
spy = yf.download('SPY', start='2022-12-01', end='2026-04-01', progress=False)
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
spy_ret = spy['Close'].pct_change().dropna()
spy_ret.index = pd.to_datetime(spy_ret.index).tz_localize(None)

# ─── 3. Define Regimes ─────────────────────────────────────────────────
REGIMES = {
    'Calm': (0, 15),
    'Normal': (15, 20),
    'Elevated': (20, 30),
    'Crisis': (30, 200),
}

def classify_regime(vix_val):
    for name, (lo, hi) in REGIMES.items():
        if lo <= vix_val < hi:
            return name
    return 'Crisis'  # fallback

regime_series = vix_close.apply(classify_regime)
regime_series.name = 'regime'

print("\nVIX Regime Distribution:")
regime_counts = regime_series.value_counts()
for r in ['Calm', 'Normal', 'Elevated', 'Crisis']:
    if r in regime_counts:
        pct = regime_counts[r] / len(regime_series) * 100
        print(f"  {r:12s}: {regime_counts[r]:4d} days ({pct:.1f}%)")

# ─── 4. Strategy × Regime Analysis ─────────────────────────────────────
print("\n" + "=" * 70)
print("Strategy × Regime Performance")
print("=" * 70)

results_by_regime = {}

for key, df in strategy_dfs.items():
    # Align with VIX regime
    common_idx = df.index.intersection(regime_series.index)
    df_aligned = df.loc[common_idx]
    regime_aligned = regime_series.loc[common_idx]

    strat_regime_results = {}

    for regime_name in ['Calm', 'Normal', 'Elevated', 'Crisis']:
        mask = regime_aligned == regime_name
        n_days = mask.sum()

        if n_days < 5:
            strat_regime_results[regime_name] = {
                'n_days': int(n_days),
                'mean_daily_return': None,
                'annualized_return': None,
                'annualized_vol': None,
                'sharpe': None,
                'avg_total_weight': None,
            }
            continue

        rets = df_aligned.loc[mask, 'return']
        mean_ret = rets.mean()
        std_ret = rets.std()
        ann_ret = mean_ret * 252
        ann_vol = std_ret * np.sqrt(252)
        sharpe = ann_ret / ann_vol if ann_vol > 1e-8 else 0.0
        avg_weight = df_aligned.loc[mask, 'total_weight'].mean()
        avg_spy_w = df_aligned.loc[mask, 'spy_weight'].mean()
        avg_gld_w = df_aligned.loc[mask, 'gld_weight'].mean()

        strat_regime_results[regime_name] = {
            'n_days': int(n_days),
            'mean_daily_return': round(float(mean_ret), 6),
            'annualized_return': round(float(ann_ret), 4),
            'annualized_vol': round(float(ann_vol), 4),
            'sharpe': round(float(sharpe), 3),
            'avg_total_weight': round(float(avg_weight), 4),
            'avg_spy_weight': round(float(avg_spy_w), 4),
            'avg_gld_weight': round(float(avg_gld_w), 4),
        }

    results_by_regime[key] = strat_regime_results

# Print summary table
print(f"\n{'Strategy':<22s} {'Regime':<10s} {'Days':>5s} {'Ann Ret':>9s} {'Vol':>8s} {'Sharpe':>7s} {'Weight':>7s}")
print("-" * 70)
for key in STRATEGY_KEYS:
    if key not in results_by_regime:
        continue
    for regime in ['Calm', 'Normal', 'Elevated', 'Crisis']:
        r = results_by_regime[key][regime]
        if r['annualized_return'] is None:
            continue
        label = STRATEGY_LABELS[key] if regime == 'Calm' else ''
        print(f"{label:<22s} {regime:<10s} {r['n_days']:5d} {r['annualized_return']:>8.2%} "
              f"{r['annualized_vol']:>7.2%} {r['sharpe']:>7.2f} {r['avg_total_weight']:>6.2%}")
    print()

# ─── 5. Rebound Capture Analysis ───────────────────────────────────────
print("\n" + "=" * 70)
print("Rebound Capture Analysis (post-VIX>30 episodes)")
print("=" * 70)

# Identify VIX > 30 episodes (contiguous blocks)
crisis_mask = vix_close >= 30
crisis_dates = vix_close.index[crisis_mask]

# Find episode boundaries: when VIX drops below 30 after being >= 30
episodes = []
if len(crisis_dates) > 0:
    ep_start = crisis_dates[0]
    for i in range(1, len(crisis_dates)):
        # Gap > 5 business days = new episode
        gap = (crisis_dates[i] - crisis_dates[i-1]).days
        if gap > 7:
            episodes.append((ep_start, crisis_dates[i-1]))
            ep_start = crisis_dates[i]
    episodes.append((ep_start, crisis_dates[-1]))

print(f"\nIdentified {len(episodes)} VIX > 30 episodes:")
rebound_results = {}
REBOUND_WINDOW = 20  # trading days

for i, (ep_start, ep_end) in enumerate(episodes):
    peak_vix = vix_close.loc[ep_start:ep_end].max()
    n_crisis_days = len(vix_close.loc[ep_start:ep_end])
    print(f"\n  Episode {i+1}: {ep_start.date()} to {ep_end.date()} "
          f"({n_crisis_days} days, peak VIX = {peak_vix:.1f})")

    # Find the REBOUND_WINDOW days AFTER the episode ends
    all_dates = vix_close.index
    end_pos = all_dates.get_loc(ep_end)
    rebound_start = end_pos + 1
    rebound_end = min(end_pos + 1 + REBOUND_WINDOW, len(all_dates))

    if rebound_start >= len(all_dates):
        print(f"    [No rebound data - episode too recent]")
        continue

    rebound_dates = all_dates[rebound_start:rebound_end]
    actual_rebound_days = len(rebound_dates)

    # SPY buy-and-hold return during rebound
    spy_rebound = spy_ret.loc[spy_ret.index.isin(rebound_dates)]
    spy_cum = (1 + spy_rebound).prod() - 1
    print(f"    Rebound window: {rebound_dates[0].date()} to {rebound_dates[-1].date()} ({actual_rebound_days} days)")
    print(f"    SPY buy-hold rebound: {spy_cum:.2%}")

    # Each strategy's performance during rebound
    ep_key = f"ep{i+1}_{ep_start.date()}"
    rebound_results[ep_key] = {
        'crisis_start': str(ep_start.date()),
        'crisis_end': str(ep_end.date()),
        'peak_vix': round(float(peak_vix), 1),
        'crisis_days': int(n_crisis_days),
        'rebound_days': int(actual_rebound_days),
        'spy_bh_rebound': round(float(spy_cum), 4),
        'strategies': {},
    }

    for key, df in strategy_dfs.items():
        # Crisis period performance
        crisis_rets = df.loc[df.index.isin(vix_close.loc[ep_start:ep_end].index), 'return']
        crisis_cum = (1 + crisis_rets).prod() - 1 if len(crisis_rets) > 0 else 0
        crisis_avg_wt = df.loc[df.index.isin(vix_close.loc[ep_start:ep_end].index), 'total_weight'].mean() \
                        if len(crisis_rets) > 0 else 0

        # Rebound period performance
        rebound_rets = df.loc[df.index.isin(rebound_dates), 'return']
        rebound_cum = (1 + rebound_rets).prod() - 1 if len(rebound_rets) > 0 else 0
        rebound_avg_wt = df.loc[df.index.isin(rebound_dates), 'total_weight'].mean() \
                         if len(rebound_rets) > 0 else 0

        # SPY during crisis for comparison
        spy_crisis = spy_ret.loc[spy_ret.index.isin(vix_close.loc[ep_start:ep_end].index)]
        spy_crisis_cum = (1 + spy_crisis).prod() - 1 if len(spy_crisis) > 0 else 0

        rebound_results[ep_key]['spy_bh_crisis'] = round(float(spy_crisis_cum), 4)

        rebound_results[ep_key]['strategies'][key] = {
            'crisis_return': round(float(crisis_cum), 4),
            'crisis_avg_weight': round(float(crisis_avg_wt), 4),
            'rebound_return': round(float(rebound_cum), 4),
            'rebound_avg_weight': round(float(rebound_avg_wt), 4),
        }

        print(f"    {STRATEGY_LABELS[key]:<25s}: crisis {crisis_cum:>7.2%} (w={crisis_avg_wt:.2f}), "
              f"rebound {rebound_cum:>7.2%} (w={rebound_avg_wt:.2f})")

# ─── 6. Regime Transition Analysis ─────────────────────────────────────
print("\n" + "=" * 70)
print("Regime Transition Analysis")
print("=" * 70)

# Detect transitions
transitions = []
prev_regime = None
for date, regime in regime_series.items():
    if prev_regime is not None and regime != prev_regime:
        transitions.append({
            'date': date,
            'from': prev_regime,
            'to': regime,
            'vix': float(vix_close.loc[date]),
        })
    prev_regime = regime

print(f"\nTotal transitions: {len(transitions)}")

# Categorize transitions
transition_types = defaultdict(list)
for t in transitions:
    key = f"{t['from']}→{t['to']}"
    transition_types[key].append(t)

transition_results = {}
for ttype, tlist in sorted(transition_types.items()):
    n = len(tlist)
    print(f"\n  {ttype}: {n} occurrences")

    # Strategy performance on transition days
    strat_perf = {}
    for key, df in strategy_dfs.items():
        t_dates = [t['date'] for t in tlist if t['date'] in df.index]
        if len(t_dates) == 0:
            continue
        rets = df.loc[t_dates, 'return']
        weights = df.loc[t_dates, 'total_weight']
        mean_ret = rets.mean()
        strat_perf[key] = {
            'mean_return': round(float(mean_ret), 6),
            'n_obs': len(t_dates),
            'avg_weight': round(float(weights.mean()), 4),
        }

    transition_results[ttype] = {
        'count': n,
        'strategies': strat_perf,
    }

    # Print top performers on this transition
    sorted_strats = sorted(strat_perf.items(), key=lambda x: x[1]['mean_return'], reverse=True)
    for skey, sp in sorted_strats[:3]:
        print(f"    {STRATEGY_LABELS[skey]:<25s}: {sp['mean_return']:>8.4%} (w={sp['avg_weight']:.2f})")

# ─── 7. Opportunity Cost & Protection Value ────────────────────────────
print("\n" + "=" * 70)
print("Net Regime Value: Protection vs Opportunity Cost")
print("=" * 70)

net_value = {}

for key, df in strategy_dfs.items():
    common_idx = df.index.intersection(spy_ret.index).intersection(regime_series.index)
    df_a = df.loc[common_idx]
    spy_a = spy_ret.loc[common_idx]
    regime_a = regime_series.loc[common_idx]

    # Protection value: drawdown avoided during Crisis (VIX >= 30)
    crisis_mask = regime_a == 'Crisis'
    if crisis_mask.sum() > 0:
        spy_crisis_cum = (1 + spy_a[crisis_mask]).prod() - 1
        strat_crisis_cum = (1 + df_a.loc[crisis_mask, 'return']).prod() - 1
        protection_saved = float(spy_crisis_cum - strat_crisis_cum)
        # Negative means strategy lost less (or gained more) than SPY
        # Protection = how much LESS the strategy lost vs SPY (positive = good)
        protection = float(strat_crisis_cum - spy_crisis_cum)
    else:
        protection = 0.0
        spy_crisis_cum = 0.0
        strat_crisis_cum = 0.0

    # Opportunity cost: return missed during Calm periods
    calm_mask = regime_a == 'Calm'
    if calm_mask.sum() > 0:
        spy_calm_cum = (1 + spy_a[calm_mask]).prod() - 1
        strat_calm_cum = (1 + df_a.loc[calm_mask, 'return']).prod() - 1
        opportunity_cost = float(spy_calm_cum - strat_calm_cum)
    else:
        opportunity_cost = 0.0
        spy_calm_cum = 0.0
        strat_calm_cum = 0.0

    # Rebound missed (Elevated → Normal transition, first 20 days after crisis)
    # Already captured in section 5, summarize here
    total_rebound_missed = 0.0
    total_spy_rebound = 0.0
    for ep_key, ep_data in rebound_results.items():
        if key in ep_data['strategies']:
            strat_reb = ep_data['strategies'][key]['rebound_return']
            spy_reb = ep_data['spy_bh_rebound']
            total_rebound_missed += (spy_reb - strat_reb)
            total_spy_rebound += spy_reb

    # Net value = Protection gained - Opportunity cost - Rebound missed
    net = protection - opportunity_cost - total_rebound_missed

    net_value[key] = {
        'protection_during_crisis': round(protection, 4),
        'spy_crisis_return': round(float(spy_crisis_cum), 4),
        'strategy_crisis_return': round(float(strat_crisis_cum), 4),
        'opportunity_cost_calm': round(opportunity_cost, 4),
        'spy_calm_return': round(float(spy_calm_cum), 4),
        'strategy_calm_return': round(float(strat_calm_cum), 4),
        'rebound_missed': round(total_rebound_missed, 4),
        'net_regime_value': round(net, 4),
    }

# Print
print(f"\n{'Strategy':<25s} {'Protection':>11s} {'Opp Cost':>10s} {'Reb Miss':>10s} {'Net Value':>10s}")
print("-" * 70)
for key in STRATEGY_KEYS:
    if key not in net_value:
        continue
    nv = net_value[key]
    print(f"{STRATEGY_LABELS[key]:<25s} {nv['protection_during_crisis']:>10.2%} "
          f"{nv['opportunity_cost_calm']:>10.2%} {nv['rebound_missed']:>10.2%} "
          f"{nv['net_regime_value']:>10.2%}")

# ─── 8. Architecture Comparison ────────────────────────────────────────
print("\n" + "=" * 70)
print("Architecture Comparison")
print("=" * 70)

arch_groups = defaultdict(list)
for key in STRATEGY_KEYS:
    if key in strategy_dfs:
        arch_groups[ARCHITECTURE[key]].append(key)

arch_summary = {}
for arch, keys in arch_groups.items():
    print(f"\n  {arch.upper()} strategies:")
    arch_metrics = {
        'strategies': [STRATEGY_LABELS[k] for k in keys],
        'regimes': {},
    }

    for regime in ['Calm', 'Normal', 'Elevated', 'Crisis']:
        regime_rets = []
        regime_weights = []
        regime_sharpes = []
        for key in keys:
            if key in results_by_regime and regime in results_by_regime[key]:
                r = results_by_regime[key][regime]
                if r['annualized_return'] is not None:
                    regime_rets.append(r['annualized_return'])
                    regime_weights.append(r['avg_total_weight'])
                    regime_sharpes.append(r['sharpe'])

        if regime_rets:
            avg_ret = np.mean(regime_rets)
            avg_wt = np.mean(regime_weights)
            avg_sharpe = np.mean(regime_sharpes)
            arch_metrics['regimes'][regime] = {
                'avg_ann_return': round(float(avg_ret), 4),
                'avg_weight': round(float(avg_wt), 4),
                'avg_sharpe': round(float(avg_sharpe), 3),
            }
            print(f"    {regime:<10s}: Avg Ret={avg_ret:>7.2%}, Avg Weight={avg_wt:>5.2%}, "
                  f"Avg Sharpe={avg_sharpe:.2f}")

    # Net regime value average
    net_vals = [net_value[k]['net_regime_value'] for k in keys if k in net_value]
    if net_vals:
        avg_net = np.mean(net_vals)
        arch_metrics['avg_net_regime_value'] = round(float(avg_net), 4)
        print(f"    Net Regime Value (avg): {avg_net:.2%}")

    arch_summary[arch] = arch_metrics

# ─── 9. Weight Dynamics During Regime Transitions ──────────────────────
print("\n" + "=" * 70)
print("Weight Dynamics: How fast do strategies react to regime changes?")
print("=" * 70)

# For key transitions: Crisis→Elevated (recovery) and Normal→Crisis (shock)
weight_dynamics = {}

for ttype in ['Crisis→Elevated', 'Elevated→Crisis', 'Normal→Elevated', 'Elevated→Normal']:
    if ttype not in transition_types:
        continue

    tlist = transition_types[ttype]
    print(f"\n  {ttype} ({len(tlist)} events):")

    dynamics = {}
    for key, df in strategy_dfs.items():
        # For each transition event, look at weight 5 days before and 5 days after
        before_weights = []
        after_weights = []

        for t in tlist:
            t_date = t['date']
            if t_date not in df.index:
                continue
            t_pos = df.index.get_loc(t_date)

            # 5 days before
            start = max(0, t_pos - 5)
            bw = df.iloc[start:t_pos]['total_weight'].mean()
            before_weights.append(bw)

            # 5 days after
            end = min(len(df), t_pos + 6)
            aw = df.iloc[t_pos:end]['total_weight'].mean()
            after_weights.append(aw)

        if before_weights and after_weights:
            avg_before = np.mean(before_weights)
            avg_after = np.mean(after_weights)
            weight_change = avg_after - avg_before

            dynamics[key] = {
                'avg_weight_before': round(float(avg_before), 4),
                'avg_weight_after': round(float(avg_after), 4),
                'weight_change': round(float(weight_change), 4),
            }

            direction = "↑" if weight_change > 0.01 else ("↓" if weight_change < -0.01 else "→")
            print(f"    {STRATEGY_LABELS[key]:<25s}: {avg_before:.2%} {direction} {avg_after:.2%} "
                  f"(Δ={weight_change:+.2%})")

    weight_dynamics[ttype] = dynamics

# ─── 10. 2025 Tariff Shock Deep Dive ───────────────────────────────────
print("\n" + "=" * 70)
print("2025 Tariff Shock Deep Dive")
print("=" * 70)

# Find the 2025 VIX spike
vix_2025 = vix_close['2025-01-01':'2025-12-31']
if len(vix_2025) > 0:
    peak_date = vix_2025.idxmax()
    peak_val = vix_2025.max()
    print(f"\n  2025 VIX peak: {peak_val:.1f} on {peak_date.date()}")

    # Pre-shock (30 days before), shock (VIX>25 period), recovery (30 days after)
    shock_start_candidates = vix_2025[vix_2025 >= 25].index
    if len(shock_start_candidates) > 0:
        shock_start = shock_start_candidates[0]
        # Find when VIX drops back below 25
        post_peak = vix_2025.loc[peak_date:]
        below_25 = post_peak[post_peak < 25].index
        shock_end = below_25[0] if len(below_25) > 0 else vix_2025.index[-1]

        print(f"  Shock period (VIX≥25): {shock_start.date()} to {shock_end.date()}")

        # Pre-shock: 30 trading days before
        all_vix_dates = vix_close.index
        shock_start_pos = all_vix_dates.get_loc(shock_start)
        pre_start = max(0, shock_start_pos - 30)
        pre_dates = all_vix_dates[pre_start:shock_start_pos]

        # Shock period
        shock_dates = all_vix_dates[(all_vix_dates >= shock_start) & (all_vix_dates <= shock_end)]

        # Recovery: 30 trading days after
        shock_end_pos = all_vix_dates.get_loc(shock_end)
        rec_end = min(len(all_vix_dates), shock_end_pos + 31)
        rec_dates = all_vix_dates[shock_end_pos+1:rec_end]

        tariff_results = {}
        print(f"\n  {'Strategy':<25s} {'Pre-Shock':>10s} {'Shock':>10s} {'Recovery':>10s} {'Total':>10s}")
        print("  " + "-" * 65)

        for key, df in strategy_dfs.items():
            pre_rets = df.loc[df.index.isin(pre_dates), 'return']
            shock_rets = df.loc[df.index.isin(shock_dates), 'return']
            rec_rets = df.loc[df.index.isin(rec_dates), 'return']

            pre_cum = (1 + pre_rets).prod() - 1 if len(pre_rets) > 0 else 0
            shock_cum = (1 + shock_rets).prod() - 1 if len(shock_rets) > 0 else 0
            rec_cum = (1 + rec_rets).prod() - 1 if len(rec_rets) > 0 else 0
            total_cum = (1 + pd.concat([pre_rets, shock_rets, rec_rets])).prod() - 1

            shock_avg_wt = df.loc[df.index.isin(shock_dates), 'total_weight'].mean() \
                           if len(shock_rets) > 0 else 0
            rec_avg_wt = df.loc[df.index.isin(rec_dates), 'total_weight'].mean() \
                         if len(rec_rets) > 0 else 0

            tariff_results[key] = {
                'pre_shock_return': round(float(pre_cum), 4),
                'shock_return': round(float(shock_cum), 4),
                'recovery_return': round(float(rec_cum), 4),
                'total_return': round(float(total_cum), 4),
                'shock_avg_weight': round(float(shock_avg_wt), 4),
                'recovery_avg_weight': round(float(rec_avg_wt), 4),
            }

            print(f"  {STRATEGY_LABELS[key]:<25s} {pre_cum:>9.2%} {shock_cum:>9.2%} "
                  f"{rec_cum:>9.2%} {total_cum:>9.2%}")

        # SPY benchmark
        spy_pre = (1 + spy_ret.loc[spy_ret.index.isin(pre_dates)]).prod() - 1
        spy_shock = (1 + spy_ret.loc[spy_ret.index.isin(shock_dates)]).prod() - 1
        spy_rec = (1 + spy_ret.loc[spy_ret.index.isin(rec_dates)]).prod() - 1
        print(f"  {'SPY Buy-Hold':<25s} {float(spy_pre):>9.2%} {float(spy_shock):>9.2%} "
              f"{float(spy_rec):>9.2%}")
else:
    tariff_results = {}
    print("  No 2025 data available")

# ─── 11. Overall Strategy Performance (full period) ────────────────────
print("\n" + "=" * 70)
print("Overall Strategy Performance (Full Paper Trading Period)")
print("=" * 70)

overall_results = {}
for key, df in strategy_dfs.items():
    rets = df['return']
    cum_ret = (1 + rets).prod() - 1
    ann_ret = (1 + cum_ret) ** (252 / len(rets)) - 1
    ann_vol = rets.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 1e-8 else 0

    # Max drawdown
    cum_wealth = (1 + rets).cumprod()
    peak = cum_wealth.cummax()
    dd = (cum_wealth - peak) / peak
    max_dd = dd.min()

    overall_results[key] = {
        'total_return': round(float(cum_ret), 4),
        'annualized_return': round(float(ann_ret), 4),
        'annualized_vol': round(float(ann_vol), 4),
        'sharpe': round(float(sharpe), 3),
        'max_drawdown': round(float(max_dd), 4),
        'n_days': len(rets),
        'avg_weight': round(float(df['total_weight'].mean()), 4),
        'architecture': ARCHITECTURE[key],
    }

print(f"\n{'Strategy':<25s} {'Total':>8s} {'Ann Ret':>8s} {'Vol':>7s} {'Sharpe':>7s} {'MDD':>8s} {'Avg Wt':>7s}")
print("-" * 75)
for key in STRATEGY_KEYS:
    if key not in overall_results:
        continue
    o = overall_results[key]
    print(f"{STRATEGY_LABELS[key]:<25s} {o['total_return']:>7.2%} {o['annualized_return']:>7.2%} "
          f"{o['annualized_vol']:>6.2%} {o['sharpe']:>7.2f} {o['max_drawdown']:>7.2%} "
          f"{o['avg_weight']:>6.2%}")

# SPY benchmark
spy_common = spy_ret.loc[spy_ret.index.isin(strategy_dfs['slow_vt'].index)]
spy_cum = (1 + spy_common).prod() - 1
spy_ann = (1 + float(spy_cum)) ** (252 / len(spy_common)) - 1
spy_vol = float(spy_common.std()) * np.sqrt(252)
spy_sharpe = spy_ann / spy_vol if spy_vol > 0 else 0
spy_wealth = (1 + spy_common).cumprod()
spy_mdd = float(((spy_wealth - spy_wealth.cummax()) / spy_wealth.cummax()).min())
print(f"{'SPY Buy-Hold':<25s} {float(spy_cum):>7.2%} {spy_ann:>7.2%} "
      f"{spy_vol:>6.2%} {spy_sharpe:>7.2f} {spy_mdd:>7.2%} {'100.0%':>7s}")

# ─── 12. Key Insights ──────────────────────────────────────────────────
print("\n" + "=" * 70)
print("KEY INSIGHTS")
print("=" * 70)

# Find best/worst performers per regime
for regime in ['Calm', 'Normal', 'Elevated', 'Crisis']:
    sharpes = {}
    for key in STRATEGY_KEYS:
        if key in results_by_regime and regime in results_by_regime[key]:
            r = results_by_regime[key][regime]
            if r['sharpe'] is not None:
                sharpes[key] = r['sharpe']
    if sharpes:
        best = max(sharpes, key=sharpes.get)
        worst = min(sharpes, key=sharpes.get)
        print(f"\n  {regime} regime:")
        print(f"    Best:  {STRATEGY_LABELS[best]} (Sharpe={sharpes[best]:.2f})")
        print(f"    Worst: {STRATEGY_LABELS[worst]} (Sharpe={sharpes[worst]:.2f})")

# Architecture ranking
print("\n  Architecture Net Regime Value:")
for arch, metrics in sorted(arch_summary.items(),
                             key=lambda x: x[1].get('avg_net_regime_value', -999),
                             reverse=True):
    nrv = metrics.get('avg_net_regime_value', 'N/A')
    if isinstance(nrv, float):
        print(f"    {arch:<20s}: {nrv:>7.2%}")
    else:
        print(f"    {arch:<20s}: {nrv}")

# ─── 13. Save Results ──────────────────────────────────────────────────
output = {
    'experiment_id': 'K641',
    'title': 'VT Strategy Performance by VIX Regime — Regime Decomposition',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data_source': 'paper_trading.json + yfinance (^VIX, SPY)',
    'data_period': f"{strategy_dfs['slow_vt'].index[0].date()} to {strategy_dfs['slow_vt'].index[-1].date()}",
    'methodology': {
        'regime_definition': REGIMES,
        'rebound_window_days': REBOUND_WINDOW,
        'strategies_analyzed': list(STRATEGY_LABELS.values()),
        'architecture_types': {v: k for k, v in ARCHITECTURE.items()},
    },
    'vix_statistics': {
        'mean': round(float(vix_close.mean()), 2),
        'median': round(float(vix_close.median()), 2),
        'min': round(float(vix_close.min()), 2),
        'max': round(float(vix_close.max()), 2),
        'regime_distribution': {r: int(regime_counts.get(r, 0)) for r in REGIMES},
    },
    'regime_performance': results_by_regime,
    'rebound_analysis': rebound_results,
    'transition_analysis': transition_results,
    'net_regime_value': net_value,
    'architecture_comparison': arch_summary,
    'weight_dynamics': weight_dynamics,
    'tariff_shock_2025': tariff_results,
    'overall_performance': overall_results,
    'spy_benchmark': {
        'total_return': round(float(spy_cum), 4),
        'annualized_return': round(float(spy_ann), 4),
        'annualized_vol': round(float(spy_vol), 4),
        'sharpe': round(float(spy_sharpe), 3),
        'max_drawdown': round(float(spy_mdd), 4),
    },
}

with open(RESULTS_PATH, 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n\nResults saved to: {RESULTS_PATH}")
print("=" * 70)
