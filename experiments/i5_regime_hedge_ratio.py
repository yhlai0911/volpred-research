"""
I5: Regime-Switching Hedge Ratio
Does the optimal futures hedge ratio change across VIX regimes?

Result: NULL improvement. OHR remarkably stable (0.952-0.973).
ANOVA sig but economically trivial (DM t=0.62 NS).
ES=F near-perfect hedge (r=0.978), OHR≈1 all regimes.

Data: SPY/ES=F/^VIX from yfinance, 2005-2025, 5337 obs
Output: experiments/i5_regime_hedge_ratio_results.json
"""
import yfinance as yf
import numpy as np
import pandas as pd
from scipy import stats
import json
from datetime import datetime, timezone

# Data
spy = yf.download('SPY', start='2005-01-01', progress=False)['Close'].dropna().squeeze()
es = yf.download('ES=F', start='2005-01-01', progress=False)['Close'].dropna().squeeze()
vix = yf.download('^VIX', start='2005-01-01', progress=False)['Close'].dropna().squeeze()

common = spy.index.intersection(es.index).intersection(vix.index)
spy, es, vix = spy.loc[common], es.loc[common], vix.loc[common]
spy_ret = spy.pct_change().dropna()
es_ret = es.pct_change().dropna().reindex(spy_ret.index).fillna(0)
vix_v = vix.reindex(spy_ret.index).fillna(20)
n = len(spy_ret)

# OLS hedge ratio by VIX regime
regimes = {
    'Low (VIX<15)': vix_v < 15,
    'Normal (15-20)': (vix_v >= 15) & (vix_v < 20),
    'Elevated (20-30)': (vix_v >= 20) & (vix_v < 30),
    'Crisis (VIX>30)': vix_v >= 30,
}

regime_results = {}
for regime_name, mask in regimes.items():
    m = mask.reindex(spy_ret.index).fillna(False)
    s_r = spy_ret[m].values
    e_r = es_ret[m].values
    nd = len(s_r)
    if nd < 30:
        continue
    cov_sf = np.cov(s_r, e_r)[0, 1]
    var_f = np.var(e_r, ddof=1)
    ohr = cov_sf / var_f
    hedged = s_r - ohr * e_r
    var_red = 1 - np.var(hedged) / np.var(s_r)
    regime_results[regime_name] = {
        'n': nd, 'ohr': round(float(ohr), 4),
        'var_reduction': round(float(var_red), 4),
        'hedged_vol_ann': round(float(np.std(hedged) * np.sqrt(252) * 100), 1)
    }

# Rolling 60d OHR
roll_ohr = pd.Series(index=spy_ret.index, dtype=float)
for i in range(60, n):
    s = spy_ret.iloc[i-60:i].values
    e = es_ret.iloc[i-60:i].values
    cov = np.cov(s, e)[0, 1]
    var = np.var(e, ddof=1)
    if var > 0:
        roll_ohr.iloc[i] = cov / var
roll_ohr = roll_ohr.dropna()

# ANOVA
vix_for_ohr = vix_v.reindex(roll_ohr.index)
quintiles = pd.qcut(vix_for_ohr, 5, labels=['Q1', 'Q2', 'Q3', 'Q4', 'Q5'])
groups = [roll_ohr[quintiles == q].values for q in ['Q1', 'Q2', 'Q3', 'Q4', 'Q5']]
f_stat, p_anova = stats.f_oneway(*groups)
rho, p_rho = stats.spearmanr(vix_for_ohr.values, roll_ohr.values)

# Hedging methods comparison
static_ohr = float(np.cov(spy_ret.values, es_ret.values)[0, 1] / np.var(es_ret.values, ddof=1))

def calc_metrics(rets):
    cum = (1 + rets).cumprod()
    return {
        'sharpe': round(float(rets.mean() / rets.std() * np.sqrt(252)), 3),
        'mdd': round(float((cum / cum.cummax() - 1).min()), 4),
        'var_reduction': round(float(1 - rets.var() / spy_ret.var()), 4),
        'ann_vol': round(float(rets.std() * np.sqrt(252) * 100), 1),
    }

hedged_static = spy_ret - static_ohr * es_ret
regime_hedge = spy_ret.copy()
for rname, mask in regimes.items():
    m = mask.reindex(spy_ret.index).fillna(False)
    if rname in regime_results:
        regime_hedge[m] = spy_ret[m] - regime_results[rname]['ohr'] * es_ret[m]

# DM test
common_dm = regime_hedge.index.intersection(hedged_static.index)
e_static = (hedged_static.loc[common_dm])**2
e_regime = (regime_hedge.loc[common_dm])**2
d = e_static - e_regime
dm_t = float(d.mean() / (d.std() / np.sqrt(len(d))))

results = {
    'experiment': 'I5',
    'title': 'Regime-Switching Hedge Ratio',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data': {
        'source': 'yfinance',
        'tickers': ['SPY', 'ES=F', '^VIX'],
        'period': f"{spy_ret.index[0].date()} to {spy_ret.index[-1].date()}",
        'n_obs': n,
    },
    'regime_ohr': regime_results,
    'anova': {'f_stat': round(float(f_stat), 2), 'p_value': float(p_anova)},
    'spearman_vix_ohr': {'rho': round(float(rho), 3), 'p': round(float(p_rho), 6)},
    'static_ohr': static_ohr,
    'method_comparison': {
        'static': calc_metrics(hedged_static),
        'regime_aware': calc_metrics(regime_hedge),
    },
    'dm_test': {'t': round(dm_t, 2), 'significant': abs(dm_t) > 3},
    'conclusion': 'NULL. OHR stable across regimes (0.952-0.973). Dynamic hedging adds zero value for equity index futures.',
}

with open('experiments/i5_regime_hedge_ratio_results.json', 'w') as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)

print("Results saved to experiments/i5_regime_hedge_ratio_results.json")
for k, v in regime_results.items():
    print(f"  {k}: OHR={v['ohr']}, VarRed={v['var_reduction']:.1%}")
print(f"  ANOVA F={f_stat:.2f}, p={p_anova:.6f}")
print(f"  DM test (static vs regime): t={dm_t:.2f} ({'sig' if abs(dm_t) > 3 else 'NS'})")
