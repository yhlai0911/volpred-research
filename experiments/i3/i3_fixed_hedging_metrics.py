"""
I3 Fixed: Cross-Asset Futures Hedging (Correct Metrics)
FIXES: Original I3 used Sharpe/CAGR to compare hedges to trading strategies.
Now properly evaluates multi-futures hedging with HE/VaR/ES/Utility.

Question: Does adding ZN+GC to ES hedge improve hedging effectiveness?
(NOT: does multi-futures beat 50/50+VT as investment)

Step 1: Reference I0 diagnostics (Grade A+B only)
Step 2: Single vs multi-futures hedge (HE comparison)
Step 3: Marginal benefit of each additional future
Step 4: DM tests

Data: SPY/ES=F/GC=F/ZN=F from yfinance, OOS 2020-2025
Output: experiments/i3/i3_fixed_results.json
"""
import yfinance as yf
import numpy as np
import pandas as pd
from scipy import stats
import json, warnings
from datetime import datetime, timezone

warnings.filterwarnings('ignore')

print("=" * 75)
print("I3 Fixed: Multi-Futures Hedging (Proper HE Evaluation)")
print("=" * 75)

tickers = {'SPY': 'SPY', 'ES': 'ES=F', 'GC': 'GC=F', 'ZN': 'ZN=F'}
data = {}
for name, t in tickers.items():
    data[name] = yf.download(t, start='2008-01-01', progress=False)['Close'].dropna().squeeze()

common = data['SPY'].index
for k in data:
    common = common.intersection(data[k].index)
for k in data:
    data[k] = data[k].loc[common]

rets = {k: data[k].pct_change().dropna() for k in data}
n = len(rets['SPY'])

oos_start = '2020-01-01'
oos_mask = rets['SPY'].index >= oos_start
oos_start_loc = int(np.where(rets['SPY'].index >= oos_start)[0][0])
n_oos = int(oos_mask.sum())

s_oos = rets['SPY'][oos_mask]
e_oos = rets['ES'][oos_mask]
g_oos = rets['GC'][oos_mask]
z_oos = rets['ZN'][oos_mask]

all_s = rets['SPY'].values
all_e = rets['ES'].values
all_g = rets['GC'].values
all_z = rets['ZN'].values

print(f"OOS: {n_oos} days")
print(f"I0 reference: SPY-ES Grade A (corr 0.97), GC Grade A (0.91), ZN Grade B (0.80)")

unhedged_var = float(s_oos.var())

# === Rolling 1-step ahead for all methods ===
window = 500

h_es_only = []      # SPY hedged with ES only
h_es_gc = []        # SPY hedged with ES + GC
h_es_zn = []        # SPY hedged with ES + ZN
h_es_gc_zn = []     # SPY hedged with ES + GC + ZN

for t in range(oos_start_loc, len(all_s)):
    w = slice(max(0, t-window), t)
    s = all_s[w]
    e = all_e[w]
    g = all_g[w]
    z = all_z[w]

    # ES only
    cov_se = np.cov(s, e)[0, 1]
    var_e = np.var(e, ddof=1)
    h_es_only.append(cov_se / var_e if var_e > 0 else 1.0)

    # ES + GC
    F2 = np.column_stack([e, g])
    try:
        h2 = np.linalg.lstsq(F2, s, rcond=None)[0]
        h_es_gc.append(h2.tolist())
    except:
        h_es_gc.append([1.0, 0.0])

    # ES + ZN
    F2b = np.column_stack([e, z])
    try:
        h2b = np.linalg.lstsq(F2b, s, rcond=None)[0]
        h_es_zn.append(h2b.tolist())
    except:
        h_es_zn.append([1.0, 0.0])

    # ES + GC + ZN
    F3 = np.column_stack([e, g, z])
    try:
        h3 = np.linalg.lstsq(F3, s, rcond=None)[0]
        h_es_gc_zn.append(h3.tolist())
    except:
        h_es_gc_zn.append([1.0, 0.0, 0.0])

# Construct hedged returns
hedged = {
    'Unhedged': s_oos,
    'Naive (h=1)': s_oos - 1.0 * e_oos,
}


# ES only (scalar)
h_es_s = pd.Series(h_es_only, index=s_oos.index)
hedged['ES only'] = s_oos - h_es_s * e_oos

# ES + GC
h_eg = pd.DataFrame(h_es_gc, index=s_oos.index, columns=['h_es', 'h_gc'])
hedged['ES+GC'] = s_oos - h_eg['h_es'] * e_oos - h_eg['h_gc'] * g_oos

# ES + ZN
h_ez = pd.DataFrame(h_es_zn, index=s_oos.index, columns=['h_es', 'h_zn'])
hedged['ES+ZN'] = s_oos - h_ez['h_es'] * e_oos - h_ez['h_zn'] * z_oos

# ES + GC + ZN
h_egz = pd.DataFrame(h_es_gc_zn, index=s_oos.index, columns=['h_es', 'h_gc', 'h_zn'])
hedged['ES+GC+ZN'] = s_oos - h_egz['h_es'] * e_oos - h_egz['h_gc'] * g_oos - h_egz['h_zn'] * z_oos

# === Evaluate ===
uvar1 = float(np.percentile(s_oos, 1))
uvar5 = float(np.percentile(s_oos, 5))
ues1 = float(s_oos[s_oos <= uvar1].mean())

print(f"\n{'Method':<14} {'HE':>7} {'VaR1%↓':>8} {'VaR5%↓':>8} {'ES1%↓':>8} {'U(λ=5)':>10} {'Avg h_ES':>9}")
print("-" * 70)

results = {}
naive_sq = None
for mname, h_ret in hedged.items():
    h_ret = h_ret.dropna()
    he = float(1 - h_ret.var() / unhedged_var) if mname != 'Unhedged' else 0
    hvar1 = float(np.percentile(h_ret, 1))
    hvar5 = float(np.percentile(h_ret, 5))
    hes1 = float(h_ret[h_ret <= hvar1].mean()) if (h_ret <= hvar1).sum() > 0 else -0.01
    var1_red = float(1 - abs(hvar1) / abs(uvar1)) if uvar1 != 0 else 0
    var5_red = float(1 - abs(hvar5) / abs(uvar5)) if uvar5 != 0 else 0
    es1_red = float(1 - abs(hes1) / abs(ues1)) if ues1 != 0 else 0
    u5 = float(h_ret.mean()) * 252 - 2.5 * float(h_ret.var()) * 252

    # Average ES hedge ratio
    if mname == 'ES+GC+ZN':
        avg_h = f"{float(h_egz['h_es'].mean()):.3f}"
    elif mname == 'ES+GC':
        avg_h = f"{float(h_eg['h_es'].mean()):.3f}"
    elif mname == 'ES+ZN':
        avg_h = f"{float(h_ez['h_es'].mean()):.3f}"
    elif mname == 'ES only':
        avg_h = f"{float(h_es_s.mean()):.3f}"
    elif mname == 'Naive (h=1)':
        avg_h = "1.000"
    else:
        avg_h = "—"

    print(f"{mname:<14} {he:>6.1%} {var1_red:>7.1%} {var5_red:>7.1%} {es1_red:>7.1%} {u5:>10.4f} {avg_h:>9}")

    results[mname] = {
        'HE': round(he, 4), 'VaR1_red': round(var1_red, 4),
        'ES1_red': round(es1_red, 4), 'utility_l5': round(u5, 6),
    }

    if mname == 'ES only':
        naive_sq = h_ret**2

# DM: Multi vs ES-only
print(f"\nDM tests (vs ES-only):")
for mname in ['ES+GC', 'ES+ZN', 'ES+GC+ZN']:
    h_ret = hedged[mname].dropna()
    es_only_ret = hedged['ES only'].dropna()
    common_idx = h_ret.index.intersection(es_only_ret.index)
    d = es_only_ret.loc[common_idx]**2 - h_ret.loc[common_idx]**2
    dm_t = float(d.mean() / (d.std() / np.sqrt(len(d)))) if d.std() > 0 else 0
    sig = "★" if abs(dm_t) > 3 else "NS"
    print(f"  {mname} vs ES-only: DM t={dm_t:.2f} ({sig})")

# Save
output = {
    'experiment': 'I3_fixed',
    'title': 'Cross-Asset Futures Hedging (Correct HE Metrics)',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data': {'source': 'yfinance', 'oos': '2020-2025', 'n_oos': n_oos},
    'results': results,
}

with open('experiments/i3/i3_fixed_results.json', 'w') as f:
    json.dump(output, f, indent=2, ensure_ascii=False, default=str)

print(f"\nResults saved to experiments/i3/i3_fixed_results.json")
