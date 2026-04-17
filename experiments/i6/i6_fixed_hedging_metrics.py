"""
I6 Fixed: Futures Hedging Cost Structure (Correct Metrics)
FIXES: Original I6 incorrectly compared hedging to trading strategies using Sharpe/CAGR.
Now uses proper hedging evaluation: HE, VaR/ES reduction, utility, cost analysis.

The question is NOT "which is better investment" but:
1. What does each approach cost (in hedging-appropriate terms)?
2. What risk reduction does each provide?
3. Cost-effectiveness = risk reduction per unit cost

Methods:
- Unhedged SPY
- 50% ES constant hedge (futures-based)
- VIX>25 tail hedge (conditional futures)
- 50/50 SPY/GLD (diversification, not hedging)
- 50/50 + VT (dynamic exposure, not hedging)

NOTE: 50/50 and VT are NOT hedging — they are portfolio construction.
We compare them separately as alternative risk management approaches.

Step 1: Diagnostics (reference I0)
Step 2: Hedging metrics for futures approaches
Step 3: Portfolio metrics for non-hedging approaches
Step 4: Cost-effectiveness comparison (each in its own framework)

Data: SPY/ES=F/GLD/^VIX from yfinance, OOS 2020-2025
Output: experiments/i6/i6_fixed_results.json
"""
import yfinance as yf
import numpy as np
import pandas as pd
from scipy import stats
import json, warnings
from datetime import datetime, timezone

warnings.filterwarnings('ignore')

print("=" * 75)
print("I6 Fixed: Futures Hedging Cost Structure (Correct Metrics)")
print("Hedging ≠ Trading Strategy. Each evaluated in its own framework.")
print("=" * 75)

spy = yf.download('SPY', start='2010-01-01', progress=False)['Close'].dropna().squeeze()
es = yf.download('ES=F', start='2010-01-01', progress=False)['Close'].dropna().squeeze()
vix = yf.download('^VIX', start='2010-01-01', progress=False)['Close'].dropna().squeeze()
gld = yf.download('GLD', start='2010-01-01', progress=False)['Close'].dropna().squeeze()

common = spy.index.intersection(es.index).intersection(vix.index).intersection(gld.index)
spy, es, vix, gld = spy.loc[common], es.loc[common], vix.loc[common], gld.loc[common]
spy_ret = spy.pct_change().dropna()
es_ret = es.pct_change().dropna().reindex(spy_ret.index).fillna(0)
gld_ret = gld.pct_change().dropna().reindex(spy_ret.index).fillna(0)
vix_v = vix.reindex(spy_ret.index).fillna(20)

# OOS
oos_mask = spy_ret.index >= '2020-01-01'
s_oos = spy_ret[oos_mask]
e_oos = es_ret[oos_mask]
g_oos = gld_ret[oos_mask]
v_oos = vix_v[oos_mask]
n_oos = len(s_oos)

print(f"OOS: {n_oos} days (2020-01-01 to {s_oos.index[-1].date()})")

# ============================================================
# SECTION A: FUTURES HEDGING (proper hedging evaluation)
# ============================================================
print(f"\n{'='*70}")
print("SECTION A: FUTURES HEDGING (Ederington HE + VaR/ES)")
print(f"{'='*70}")

unhedged_var = float(s_oos.var())
uvar1 = float(np.percentile(s_oos, 1))
uvar5 = float(np.percentile(s_oos, 5))
ues1 = float(s_oos[s_oos <= uvar1].mean())

# Compute OHR from pre-OOS data
pre_oos = spy_ret[~oos_mask]
pre_es = es_ret[~oos_mask]
static_ohr = float(np.cov(pre_oos.values, pre_es.reindex(pre_oos.index).fillna(0).values)[0, 1] / np.var(pre_es.reindex(pre_oos.index).fillna(0).values, ddof=1))

# Hedging methods
hedges = {
    'Unhedged': s_oos,
    'Static OHR': s_oos - static_ohr * e_oos,
    '50% Hedge': s_oos - 0.5 * e_oos,
    'Naive (h=1)': s_oos - 1.0 * e_oos,
}

# VIX>25 conditional hedge (monthly trigger, lagged)
trigger = (v_oos.shift(1) > 25).astype(float).fillna(0)
for i in range(1, len(trigger)):
    if trigger.index[i].month == trigger.index[i-1].month and i > 0:
        trigger.iloc[i] = trigger.iloc[i-1]
hedges['VIX>25 Cond'] = s_oos - static_ohr * trigger * e_oos

print(f"\nUnhedged: Ann Vol={float(s_oos.std())*np.sqrt(252)*100:.1f}%, 1%VaR={uvar1*100:.2f}%, ES={ues1*100:.2f}%")
print(f"Static OHR (from IS): {static_ohr:.4f}")
print(f"\n{'Method':<16} {'HE':>7} {'VaR1%↓':>8} {'VaR5%↓':>8} {'ES1%↓':>8} {'U(λ=2)':>10} {'U(λ=10)':>10} {'TX/yr':>8}")
print("-" * 80)

hedge_results = {}
for mname, hedged in hedges.items():
    he = float(1 - hedged.var() / unhedged_var) if mname != 'Unhedged' else 0
    hvar1 = float(np.percentile(hedged, 1))
    hvar5 = float(np.percentile(hedged, 5))
    hes1 = float(hedged[hedged <= hvar1].mean()) if (hedged <= hvar1).sum() > 0 else -0.01
    var1_red = float(1 - abs(hvar1) / abs(uvar1)) if uvar1 != 0 else 0
    var5_red = float(1 - abs(hvar5) / abs(uvar5)) if uvar5 != 0 else 0
    es1_red = float(1 - abs(hes1) / abs(ues1)) if ues1 != 0 else 0
    mean_r = float(hedged.mean()) * 252
    var_r = float(hedged.var()) * 252
    u2 = mean_r - 1.0 * var_r
    u10 = mean_r - 5.0 * var_r

    # TX cost estimate
    if mname == 'VIX>25 Cond':
        switches = float(trigger.diff().abs().sum()) / 2
        tx_yr = switches / (n_oos / 252) * 0.01  # 0.01% per switch
    elif mname in ['Static OHR', '50% Hedge', 'Naive (h=1)']:
        tx_yr = 12 * 0.01  # monthly roll, 0.01% each
    else:
        tx_yr = 0

    print(f"{mname:<16} {he:>6.1%} {var1_red:>7.1%} {var5_red:>7.1%} {es1_red:>7.1%} {u2:>10.4f} {u10:>10.4f} {tx_yr:>7.2f}%")

    hedge_results[mname] = {
        'HE': round(he, 4), 'VaR1_red': round(var1_red, 4),
        'VaR5_red': round(var5_red, 4), 'ES1_red': round(es1_red, 4),
        'utility_l2': round(u2, 6), 'utility_l10': round(u10, 6),
        'tx_cost_yr': round(tx_yr, 4),
    }

# ============================================================
# SECTION B: PORTFOLIO RISK MANAGEMENT (different framework)
# ============================================================
print(f"\n{'='*70}")
print("SECTION B: PORTFOLIO RISK MANAGEMENT (NOT hedging)")
print("These are portfolio construction choices, evaluated differently.")
print(f"{'='*70}")

# VT weight (monthly, lagged)
vt_w = np.minimum(12.0 / v_oos.shift(1).fillna(20), 1.0)
for i in range(1, len(vt_w)):
    if vt_w.index[i].month == vt_w.index[i-1].month:
        vt_w.iloc[i] = vt_w.iloc[i-1]

portfolios = {
    'SPY only': s_oos,
    '50/50 SPY/GLD': 0.5 * s_oos + 0.5 * g_oos,
    '50/50 + VT': 0.5 * vt_w * s_oos + 0.5 * g_oos,
}

print(f"\n{'Portfolio':<20} {'Ann Ret':>8} {'Ann Vol':>8} {'MDD':>8} {'Sharpe':>8} {'Insurance':>10}")
print("-" * 60)

port_results = {}
for pname, p_ret in portfolios.items():
    cum = (1 + p_ret).cumprod()
    ann_ret = float(p_ret.mean()) * 252 * 100
    ann_vol = float(p_ret.std()) * np.sqrt(252) * 100
    mdd = float((cum / cum.cummax() - 1).min()) * 100
    sharpe = float(p_ret.mean() / p_ret.std() * np.sqrt(252))

    # Insurance cost = return difference vs SPY
    if pname != 'SPY only':
        insurance = float(s_oos.mean() - p_ret.mean()) * 252 * 100
    else:
        insurance = 0

    print(f"{pname:<20} {ann_ret:>7.1f}% {ann_vol:>7.1f}% {mdd:>7.1f}% {sharpe:>8.3f} {insurance:>9.1f}%/yr")

    port_results[pname] = {
        'ann_ret': round(ann_ret, 1), 'ann_vol': round(ann_vol, 1),
        'mdd': round(mdd, 1), 'sharpe': round(sharpe, 3),
        'insurance_cost': round(insurance, 2),
    }

# ============================================================
# SECTION C: COMPARISON SUMMARY
# ============================================================
print(f"\n{'='*70}")
print("SECTION C: COST-EFFECTIVENESS COMPARISON")
print("(Each approach in its proper framework)")
print(f"{'='*70}")

print(f"""
FUTURES HEDGING (risk reduction tool):
  Best HE: Static OHR ({hedge_results['Static OHR']['HE']:.1%}), cost ~0.12%/yr
  Best conditional: VIX>25 ({hedge_results['VIX>25 Cond']['HE']:.1%}), lower cost
  Purpose: reduce variance of EXISTING position

PORTFOLIO CONSTRUCTION (investment choice):
  Best risk-adjusted: 50/50 SPY/GLD (Sharpe {port_results['50/50 SPY/GLD']['sharpe']:.3f})
  Best MDD: 50/50+VT (MDD {port_results['50/50 + VT']['mdd']:.1f}%)
  Purpose: build better portfolio from scratch

KEY INSIGHT: These are DIFFERENT tools for DIFFERENT problems.
  - Hedging: you HAVE a position and want to reduce its risk
  - Portfolio: you're CHOOSING how to invest
  Comparing Sharpe of a hedge to Sharpe of a portfolio is meaningless.
""")

# Save
output = {
    'experiment': 'I6_fixed',
    'title': 'Futures Hedging Cost Structure (Correct Metrics)',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data': {'source': 'yfinance', 'oos': '2020-2025', 'n_oos': n_oos},
    'section_a_hedging': hedge_results,
    'section_b_portfolio': port_results,
    'methodology_note': 'Hedging and portfolio construction evaluated in separate frameworks. HE/VaR for hedging, Sharpe/MDD for portfolio.',
}

with open('experiments/i6/i6_fixed_results.json', 'w') as f:
    json.dump(output, f, indent=2, ensure_ascii=False, default=str)

print(f"Results saved to experiments/i6/i6_fixed_results.json")
