"""
I1b: Commodity Futures Hedging — Do commodity futures benefit more from
dynamic hedge ratios than equity index futures?

Hypothesis: ES=F is near-perfect hedge for SPY (I5: OHR≈1 stable).
Commodity ETF-futures pairs have lower correlation → dynamic OHR may help more.

Data: GLD-GC=F, USO-CL=F, SLV-SI=F, UNG-NG=F from yfinance, 2010-2025
Output: experiments/i1b_commodity_futures_results.json
"""
import yfinance as yf
import numpy as np
import pandas as pd
from scipy import stats
import json
from datetime import datetime, timezone

pairs = [
    ('GLD', 'GC=F', 'Gold'),
    ('USO', 'CL=F', 'Crude Oil'),
    ('SLV', 'SI=F', 'Silver'),
    ('UNG', 'NG=F', 'Natural Gas'),
    ('TLT', 'ZN=F', '10yr Bond'),
    ('FXY', '6J=F', 'Japanese Yen'),
]

results_all = {}
print(f"{'Pair':<15} {'N':>5} {'Corr':>6} {'Static':>8} {'Roll60':>8} {'EWMA':>8} {'Best':>10} {'DM t':>6}")
print("=" * 75)

for spot_t, fut_t, name in pairs:
    try:
        spot = yf.download(spot_t, start='2010-01-01', progress=False)['Close'].dropna().squeeze()
        fut = yf.download(fut_t, start='2010-01-01', progress=False)['Close'].dropna().squeeze()
    except:
        print(f"{name:<15} DOWNLOAD FAILED")
        continue

    common = spot.index.intersection(fut.index)
    if len(common) < 504:
        print(f"{name:<15} Insufficient data ({len(common)})")
        continue

    spot = spot.loc[common]
    fut = fut.loc[common]
    s_ret = spot.pct_change().dropna()
    f_ret = fut.pct_change().dropna().reindex(s_ret.index).fillna(0)
    n = len(s_ret)

    # Correlation
    corr = float(np.corrcoef(s_ret.values, f_ret.values)[0, 1])

    # Method 1: Static OHR (full sample)
    static_ohr = float(np.cov(s_ret.values, f_ret.values)[0, 1] / np.var(f_ret.values, ddof=1))
    hedged_static = s_ret - static_ohr * f_ret
    var_red_static = float(1 - hedged_static.var() / s_ret.var())

    # Method 2: Rolling 60d OHR (lagged)
    roll_ohr = pd.Series(index=s_ret.index, dtype=float)
    for i in range(60, n):
        s = s_ret.iloc[i-60:i].values
        f = f_ret.iloc[i-60:i].values
        var_f = np.var(f, ddof=1)
        if var_f > 0:
            roll_ohr.iloc[i] = np.cov(s, f)[0, 1] / var_f
    roll_ohr = roll_ohr.shift(1).dropna()
    cidx = roll_ohr.index.intersection(s_ret.index)
    hedged_roll = s_ret.loc[cidx] - roll_ohr.loc[cidx] * f_ret.loc[cidx]
    var_red_roll = float(1 - hedged_roll.var() / s_ret.loc[cidx].var())

    # Method 3: EWMA(0.94) (lagged)
    ewma_cov = s_ret.ewm(alpha=0.06).cov(f_ret)
    ewma_var = f_ret.ewm(alpha=0.06).var()
    ewma_ohr = (ewma_cov / ewma_var).shift(1).dropna()
    eidx = ewma_ohr.index.intersection(s_ret.index)
    hedged_ewma = s_ret.loc[eidx] - ewma_ohr.loc[eidx] * f_ret.loc[eidx]
    var_red_ewma = float(1 - hedged_ewma.var() / s_ret.loc[eidx].var())

    # Best method
    methods = {'Static': var_red_static, 'Roll60': var_red_roll, 'EWMA': var_red_ewma}
    best = max(methods, key=methods.get)

    # DM test: EWMA vs Static (on common period)
    dm_idx = hedged_static.index.intersection(hedged_ewma.index)
    if len(dm_idx) > 100:
        e_s = (hedged_static.loc[dm_idx])**2
        e_e = (hedged_ewma.loc[dm_idx])**2
        d = e_s - e_e
        dm_t = float(d.mean() / (d.std() / np.sqrt(len(d))))
    else:
        dm_t = float('nan')

    sig = "★" if abs(dm_t) > 3 else "NS" if not np.isnan(dm_t) else "?"

    print(f"{name:<15} {n:>5} {corr:>6.3f} {var_red_static:>7.1%} {var_red_roll:>7.1%} {var_red_ewma:>7.1%} {best:>10} {dm_t:>5.1f}{sig}")

    results_all[name] = {
        'spot': spot_t, 'futures': fut_t, 'n': n,
        'correlation': round(corr, 3),
        'var_reduction': {
            'static': round(var_red_static, 4),
            'rolling_60d': round(var_red_roll, 4),
            'ewma_094': round(var_red_ewma, 4),
        },
        'best_method': best,
        'dm_ewma_vs_static': {'t': round(dm_t, 2) if not np.isnan(dm_t) else None, 'sig': sig},
    }

# Summary
print(f"\n{'='*75}")
print("KEY FINDINGS:")
print(f"{'='*75}")
n_ewma_wins = sum(1 for r in results_all.values() if r['best_method'] == 'EWMA')
n_static_wins = sum(1 for r in results_all.values() if r['best_method'] == 'Static')
n_roll_wins = sum(1 for r in results_all.values() if r['best_method'] == 'Roll60')
n_sig = sum(1 for r in results_all.values() if r['dm_ewma_vs_static']['sig'] == '★')
print(f"Best method wins: Static {n_static_wins}, Roll60 {n_roll_wins}, EWMA {n_ewma_wins}")
print(f"EWMA vs Static DM significant: {n_sig}/{len(results_all)}")

# Save
output = {
    'experiment': 'I1b',
    'title': 'Commodity Futures Dynamic Hedging',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data': {'source': 'yfinance', 'period': '2010-2025'},
    'pairs': results_all,
    'conclusion': f'Best: Static {n_static_wins}, Roll60 {n_roll_wins}, EWMA {n_ewma_wins}. DM sig: {n_sig}/{len(results_all)}.',
}

with open('experiments/i1b_commodity_futures_results.json', 'w') as f:
    json.dump(output, f, indent=2, ensure_ascii=False, default=str)

print(f"\nResults saved to experiments/i1b_commodity_futures_results.json")
