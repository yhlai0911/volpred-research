"""
K423: Day-of-Week Volatility Effect Across Asset Classes
Extends K215 (seasonality 5 assets) and S5 (VIX Monday +1.91%).

Prior knowledge:
- S5: VIX Monday +1.91% (t=5.38), Friday -0.87% (t=-3.04)
- K215: 5/15 Bonferroni pass but NOT actionable. Seasonal VT hurts
- K410: Calendar anomalies DEAD in modern era

Question: Is the Monday vol effect real and universal? Can it be explained?

Step 1: Diagnostics
Step 2: Day-of-week vol pattern across 10 assets
Step 3: Monday effect controlling for VIX/Friday close
Step 4: Has it changed over time? (pre/post-2020)

Data: SPY, QQQ, GLD, TLT, BTC-USD, ES=F, GC=F, ZN=F, FXY, EEM from yfinance
Output: experiments/k423_monday_effect_results.json
"""
import yfinance as yf
import numpy as np
import pandas as pd
from scipy import stats
import json, warnings
from datetime import datetime, timezone

warnings.filterwarnings('ignore')

print("=" * 75)
print("K423: Day-of-Week Vol Effect Across Asset Classes")
print("=" * 75)

tickers = {
    'SPY': 'SPY', 'QQQ': 'QQQ', 'GLD': 'GLD', 'TLT': 'TLT',
    'BTC': 'BTC-USD', 'EEM': 'EEM',
    'ES': 'ES=F', 'GC': 'GC=F', 'ZN': 'ZN=F', 'FXY': 'FXY',
}

data = {}
for name, t in tickers.items():
    try:
        d = yf.download(t, start='2010-01-01', progress=False)['Close'].dropna().squeeze()
        if len(d) > 1000:
            data[name] = d
    except:
        pass

print(f"Loaded {len(data)} assets")

# Process each asset
results = {}
days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']

print(f"\n{'Asset':<8}", end="")
for d in days:
    print(f"  {d:>8}", end="")
print(f"  {'Mon/Avg':>8} {'Mon t':>7} {'ANOVA p':>8}")
print("=" * 80)

for name, prices in data.items():
    ret = prices.pct_change().dropna()
    abs_ret = ret.abs()

    # Group by day of week
    dow = ret.index.dayofweek
    vol_by_day = {}
    abs_by_day = {}

    for i, d_name in enumerate(days):
        mask = dow == i
        vol_by_day[d_name] = float(abs_ret[mask].mean() * np.sqrt(252) * 100)
        abs_by_day[d_name] = abs_ret[mask].values

    avg_vol = np.mean(list(vol_by_day.values()))
    mon_ratio = vol_by_day['Mon'] / avg_vol if avg_vol > 0 else 1

    # T-test: Monday vs other days
    mon_vals = abs_by_day['Mon']
    other_vals = np.concatenate([abs_by_day[d] for d in days if d != 'Mon'])
    t_mon, p_mon = stats.ttest_ind(mon_vals, other_vals)

    # ANOVA across all days
    f_stat, p_anova = stats.f_oneway(*[abs_by_day[d] for d in days])

    print(f"{name:<8}", end="")
    for d in days:
        print(f"  {vol_by_day[d]:>7.1f}%", end="")
    print(f"  {mon_ratio:>7.2f}x {t_mon:>7.2f} {p_anova:>8.4f}")

    results[name] = {
        'vol_by_day': {d: round(v, 1) for d, v in vol_by_day.items()},
        'monday_ratio': round(mon_ratio, 3),
        'monday_t': round(float(t_mon), 2),
        'anova_p': round(float(p_anova), 4),
    }

# Pre vs Post 2020
print(f"\n{'='*70}")
print("Monday Effect: Pre-2020 vs Post-2020")
print(f"{'='*70}")

for name in ['SPY', 'QQQ', 'GLD', 'BTC']:
    if name not in data:
        continue
    ret = data[name].pct_change().dropna()
    abs_ret = ret.abs()
    dow = ret.index.dayofweek

    for period, mask in [('Pre-2020', ret.index < '2020-01-01'), ('Post-2020', ret.index >= '2020-01-01')]:
        mon = abs_ret[(dow == 0) & mask]
        other = abs_ret[(dow != 0) & mask]
        if len(mon) > 50:
            ratio = float(mon.mean() / other.mean())
            t, p = stats.ttest_ind(mon.values, other.values)
            sig = "★" if p < 0.01 else ""
            print(f"  {name:<6} {period:<10}: Monday/Other={ratio:.3f}x (t={t:.2f}, p={p:.4f}){sig}")

# Save
output = {
    'experiment': 'K423',
    'title': 'Day-of-Week Volatility Effect',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data': {'source': 'yfinance', 'n_assets': len(data)},
    'results': results,
}

with open('experiments/k423_monday_effect_results.json', 'w') as f:
    json.dump(output, f, indent=2, ensure_ascii=False, default=str)

print(f"\nResults saved to experiments/k423_monday_effect_results.json")
