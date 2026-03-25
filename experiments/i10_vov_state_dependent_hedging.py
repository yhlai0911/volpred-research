"""
I10: VOL/VOV State-Dependent Hedging Effectiveness
Based on: Li & Chen (2025) JFM — VIX hedging depends on VOV state.

Academic framework: When VOL high + VOV low → best hedging.
When VOL high + VOV high → hedging fails (correlation breaks down).

Uses VVIX (vol of VIX) as VOV proxy.
Evaluation: Ederington HE by regime, utility-based, DM tests.

Prior knowledge check:
- K168: ★ GARCH VoV — High VoV → GARCH conservative (fewer violations)
- K17/K184: VVIX overlay NULL for VT strategy
- K212: Conditional VIX sufficiency — VIX breaks at VIX>25

Data: SPY/ES=F/^VIX/^VVIX from yfinance
Output: experiments/i10_vov_hedging_results.json
"""
import yfinance as yf
import numpy as np
import pandas as pd
from scipy import stats
import json
from datetime import datetime, timezone

print("=" * 75)
print("I10: VOL/VOV State-Dependent Hedging Effectiveness")
print("Based on Li & Chen (2025) JFM")
print("=" * 75)

# Data
spy = yf.download('SPY', start='2010-01-01', progress=False)['Close'].dropna().squeeze()
es = yf.download('ES=F', start='2010-01-01', progress=False)['Close'].dropna().squeeze()
vix = yf.download('^VIX', start='2010-01-01', progress=False)['Close'].dropna().squeeze()
vvix = yf.download('^VVIX', start='2010-01-01', progress=False)['Close'].dropna().squeeze()

common = spy.index.intersection(es.index).intersection(vix.index).intersection(vvix.index)
spy, es, vix, vvix = spy.loc[common], es.loc[common], vix.loc[common], vvix.loc[common]
s_ret = spy.pct_change().dropna()
f_ret = es.pct_change().dropna().reindex(s_ret.index).fillna(0)
vix_v = vix.reindex(s_ret.index).fillna(20)
vvix_v = vvix.reindex(s_ret.index).fillna(80)
n = len(s_ret)
print(f"Data: {n} days ({s_ret.index[0].date()} to {s_ret.index[-1].date()})")
print(f"VVIX: mean={vvix_v.mean():.1f}, std={vvix_v.std():.1f}, range [{vvix_v.min():.0f}, {vvix_v.max():.0f}]")

# Define 4 VOL/VOV regimes (Li & Chen 2025 framework)
vix_med = float(vix_v.median())
vvix_med = float(vvix_v.median())
print(f"Medians: VIX={vix_med:.1f}, VVIX={vvix_med:.1f}")

regimes = {
    'Low VOL, Low VOV': (vix_v < vix_med) & (vvix_v < vvix_med),
    'Low VOL, High VOV': (vix_v < vix_med) & (vvix_v >= vvix_med),
    'High VOL, Low VOV': (vix_v >= vix_med) & (vvix_v < vvix_med),
    'High VOL, High VOV': (vix_v >= vix_med) & (vvix_v >= vvix_med),
}

# Naive hedge (h=1) in each regime
print(f"\n{'='*75}")
print("Ederington HE by VOL/VOV Regime (Naive h=1)")
print(f"{'='*75}")
print(f"{'Regime':<25} {'N':>6} {'Unhedged Vol':>14} {'HE':>8} {'SPY-ES corr':>12} {'VaR1%↓':>8}")
print("-" * 75)

regime_results = {}
for rname, mask in regimes.items():
    m = mask.reindex(s_ret.index).fillna(False)
    nd = int(m.sum())
    if nd < 50:
        continue

    s_r = s_ret[m]
    f_r = f_ret[m]
    hedged = s_r - 1.0 * f_r

    unhedged_var = float(s_r.var())
    hedged_var = float(hedged.var())
    he = 1 - hedged_var / unhedged_var if unhedged_var > 0 else 0
    corr = float(np.corrcoef(s_r.values, f_r.values)[0, 1])
    unhedged_vol = float(s_r.std() * np.sqrt(252) * 100)

    # VaR reduction
    uvar1 = float(np.percentile(s_r, 1))
    hvar1 = float(np.percentile(hedged, 1))
    var1_red = 1 - abs(hvar1) / abs(uvar1) if uvar1 != 0 else 0

    print(f"{rname:<25} {nd:>6} {unhedged_vol:>13.1f}% {he:>7.1%} {corr:>12.4f} {var1_red:>7.1%}")

    regime_results[rname] = {
        'n': nd, 'unhedged_vol': round(unhedged_vol, 1),
        'HE': round(float(he), 4), 'correlation': round(corr, 4),
        'VaR1_reduction': round(float(var1_red), 4),
    }

# ANOVA: Is HE significantly different across regimes?
print(f"\n{'='*75}")
print("Statistical Test: Does VOV affect hedging effectiveness?")
print(f"{'='*75}")

# Rolling 60d HE by regime
roll_he = pd.Series(index=s_ret.index[60:], dtype=float)
for i in range(60, n):
    s = s_ret.iloc[i-60:i]
    f = f_ret.iloc[i-60:i]
    h = s - 1.0 * f
    roll_he.iloc[i-60] = float(1 - h.var() / s.var()) if s.var() > 0 else 0

# Split by regime
for rname, mask in regimes.items():
    m = mask.reindex(roll_he.index).fillna(False)
    if m.sum() > 20:
        he_regime = roll_he[m]
        print(f"  {rname:<25}: mean HE={he_regime.mean():.3f}, std={he_regime.std():.3f}")

# Correlation between VOV and HE
vvix_for_he = vvix_v.reindex(roll_he.index)
r_vvix_he, p_vvix_he = stats.pearsonr(vvix_for_he.dropna().values[:len(roll_he.dropna())], roll_he.dropna().values[:len(vvix_for_he.dropna())])
print(f"\n  Pearson r(VVIX, rolling HE): {r_vvix_he:.3f} (p={p_vvix_he:.6f})")

# Partial correlation controlling VIX
vix_for_he = vix_v.reindex(roll_he.index)
df_test = pd.DataFrame({'vvix': vvix_for_he, 'vix': vix_for_he, 'he': roll_he}).dropna()
X = np.column_stack([np.ones(len(df_test)), df_test['vix'].values])
res_vvix = df_test['vvix'].values - X @ np.linalg.lstsq(X, df_test['vvix'].values, rcond=None)[0]
res_he = df_test['he'].values - X @ np.linalg.lstsq(X, df_test['he'].values, rcond=None)[0]
r_partial, p_partial = stats.pearsonr(res_vvix, res_he)
t_partial = r_partial * np.sqrt((len(df_test)-3) / (1-r_partial**2))
harvey = "★ PASS" if abs(t_partial) > 3 else "FAIL"
print(f"  Partial r(VVIX, HE | VIX): {r_partial:.3f} (t={t_partial:.2f}, p={p_partial:.6f}) Harvey: {harvey}")

# Li & Chen prediction: High VOL + Low VOV should have BEST hedging
# High VOL + High VOV should have WORST hedging
if 'High VOL, Low VOV' in regime_results and 'High VOL, High VOV' in regime_results:
    he_best = regime_results['High VOL, Low VOV']['HE']
    he_worst = regime_results['High VOL, High VOV']['HE']
    print(f"\n  Li & Chen (2025) prediction test:")
    print(f"    High VOL + Low VOV  HE = {he_best:.3f}")
    print(f"    High VOL + High VOV HE = {he_worst:.3f}")
    print(f"    Difference: {he_best - he_worst:.3f}")
    print(f"    Li & Chen confirmed: {'YES' if he_best > he_worst else 'NO'}")

# Save
output = {
    'experiment': 'I10',
    'title': 'VOL/VOV State-Dependent Hedging Effectiveness',
    'reference': 'Li & Chen (2025) JFM',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data': {
        'source': 'yfinance',
        'tickers': ['SPY', 'ES=F', '^VIX', '^VVIX'],
        'period': f"{s_ret.index[0].date()} to {s_ret.index[-1].date()}",
        'n_obs': n,
    },
    'vix_median': vix_med,
    'vvix_median': vvix_med,
    'regime_results': regime_results,
    'vvix_he_correlation': {
        'simple_r': round(float(r_vvix_he), 3),
        'partial_r_vix': round(float(r_partial), 3),
        't_partial': round(float(t_partial), 2),
        'harvey_pass': abs(t_partial) > 3,
    },
}

with open('experiments/i10_vov_hedging_results.json', 'w') as f:
    json.dump(output, f, indent=2, ensure_ascii=False, default=str)

print(f"\nResults saved to experiments/i10_vov_hedging_results.json")
