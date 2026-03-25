"""
K424: Expected Loss Deviation (ELD) Optimal Hedge Ratio
Based on: Finance Research Letters (2025) — ELD measure achieves 94.5%
variance reduction and 82% VaR reduction, outperforming ES and EVaR.

Standard MV-OHR minimizes variance. ELD-OHR minimizes expected loss deviation
(downside-focused). Does it improve tail risk hedging?

Prior knowledge:
- I9/I9b: Academic HE evaluation done with MV-OHR
- I11: 15 pairs, Naive wins 8/15
- K417: Cao & Conlon partially rejected

Step 1: Diagnostics (already done in I0)
Step 2: Implement ELD-OHR (semivariance-based)
Step 3: Compare MV-OHR vs ELD-OHR on VaR/ES reduction
Step 4: DM test

Data: SPY-ES=F, GLD-GC=F, TLT-ZN=F from yfinance, OOS 2020-2025
Output: experiments/k424_eld_hedge_results.json
"""
import yfinance as yf
import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import minimize_scalar
import json, warnings
from datetime import datetime, timezone

warnings.filterwarnings('ignore')

print("=" * 75)
print("K424: Expected Loss Deviation (ELD) Optimal Hedge Ratio")
print("Based on Finance Research Letters (2025)")
print("=" * 75)

pairs = [
    ('SPY', 'ES=F', 'Equity'),
    ('GLD', 'GC=F', 'Gold'),
    ('TLT', 'ZN=F', 'Bond'),
]

all_results = {}

for spot_t, fut_t, asset_class in pairs:
    spot = yf.download(spot_t, start='2008-01-01', progress=False)['Close'].dropna().squeeze()
    fut = yf.download(fut_t, start='2008-01-01', progress=False)['Close'].dropna().squeeze()

    common = spot.index.intersection(fut.index)
    spot, fut = spot.loc[common], fut.loc[common]
    s_ret = spot.pct_change().dropna()
    f_ret = fut.pct_change().dropna().reindex(s_ret.index).fillna(0)

    oos_start = '2020-01-01'
    oos_mask = s_ret.index >= oos_start
    oos_start_loc = int(np.where(s_ret.index >= oos_start)[0][0])
    n_oos = int(oos_mask.sum())

    print(f"\n{'='*70}")
    print(f"{asset_class}: {spot_t} hedged with {fut_t} (OOS: {n_oos} days)")
    print(f"{'='*70}")

    all_s = s_ret.values
    all_f = f_ret.values
    s_oos = s_ret[oos_mask]
    f_oos = f_ret[oos_mask]

    # Define hedge ratio methods
    def compute_mv_ohr(s, f):
        """Minimum Variance OHR = Cov(s,f)/Var(f)"""
        cov = np.cov(s, f)[0, 1]
        var = np.var(f, ddof=1)
        return cov / var if var > 0 else 1.0

    def compute_eld_ohr(s, f, alpha=0.05):
        """Expected Loss Deviation OHR: minimize E[max(0, -hedged_ret - threshold)]
        where threshold = VaR at alpha level.
        Approximated by minimizing lower partial moment (semivariance below 0)."""
        def eld_loss(h):
            hedged = s - h * f
            losses = hedged[hedged < 0]
            if len(losses) == 0:
                return 0
            return float(np.mean(losses**2))  # LPM(2,0) = downside semivariance

        result = minimize_scalar(eld_loss, bounds=(0, 3), method='bounded')
        return float(result.x)

    def compute_es_ohr(s, f, alpha=0.05):
        """Expected Shortfall OHR: minimize ES at alpha level."""
        def es_loss(h):
            hedged = s - h * f
            var_alpha = np.percentile(hedged, alpha * 100)
            tail = hedged[hedged <= var_alpha]
            return -float(np.mean(tail)) if len(tail) > 0 else 0

        result = minimize_scalar(es_loss, bounds=(0, 3), method='bounded')
        return float(result.x)

    # Rolling 1-step ahead OOS
    h_mv = []
    h_eld = []
    h_es = []
    window = 500

    for t in range(oos_start_loc, len(all_s)):
        s_hist = all_s[max(0, t-window):t]
        f_hist = all_f[max(0, t-window):t]

        h_mv.append(compute_mv_ohr(s_hist, f_hist))
        h_eld.append(compute_eld_ohr(s_hist, f_hist))
        h_es.append(compute_es_ohr(s_hist, f_hist))

    h_mv = pd.Series(h_mv, index=s_oos.index)
    h_eld = pd.Series(h_eld, index=s_oos.index)
    h_es = pd.Series(h_es, index=s_oos.index)
    h_naive = pd.Series(1.0, index=s_oos.index)

    methods = {
        'Naive': h_naive,
        'MV-OHR': h_mv,
        'ELD-OHR': h_eld,
        'ES-OHR': h_es,
    }

    # Evaluate
    unhedged_var = float(s_oos.var())
    uvar1 = float(np.percentile(s_oos, 1))
    uvar5 = float(np.percentile(s_oos, 5))
    ues1 = float(s_oos[s_oos <= uvar1].mean()) if (s_oos <= uvar1).sum() > 0 else -0.01

    print(f"\n{'Method':<12} {'Avg h':>7} {'HE':>7} {'VaR1%↓':>8} {'VaR5%↓':>8} {'ES1%↓':>8} {'LPM2↓':>7}")
    print("-" * 60)

    method_results = {}
    for mname, h in methods.items():
        hedged = s_oos - h * f_oos

        he = float(1 - hedged.var() / unhedged_var)
        hvar1 = float(np.percentile(hedged, 1))
        hvar5 = float(np.percentile(hedged, 5))
        hes1 = float(hedged[hedged <= hvar1].mean()) if (hedged <= hvar1).sum() > 0 else -0.01

        var1_red = float(1 - abs(hvar1) / abs(uvar1)) if uvar1 != 0 else 0
        var5_red = float(1 - abs(hvar5) / abs(uvar5)) if uvar5 != 0 else 0
        es1_red = float(1 - abs(hes1) / abs(ues1)) if ues1 != 0 else 0

        # LPM2 (downside semivariance)
        ulpm = float(np.mean(s_oos[s_oos < 0]**2))
        hlpm = float(np.mean(hedged[hedged < 0]**2)) if (hedged < 0).sum() > 0 else 0
        lpm_red = float(1 - hlpm / ulpm) if ulpm > 0 else 0

        avg_h = float(h.mean())
        print(f"{mname:<12} {avg_h:>7.3f} {he:>6.1%} {var1_red:>7.1%} {var5_red:>7.1%} {es1_red:>7.1%} {lpm_red:>6.1%}")

        method_results[mname] = {
            'avg_h': round(avg_h, 4), 'HE': round(he, 4),
            'VaR1_red': round(var1_red, 4), 'VaR5_red': round(var5_red, 4),
            'ES1_red': round(es1_red, 4), 'LPM2_red': round(lpm_red, 4),
        }

    # DM tests: ELD vs MV on squared hedging errors
    hedged_mv = s_oos - h_mv * f_oos
    hedged_eld = s_oos - h_eld * f_oos
    hedged_es = s_oos - h_es * f_oos

    d_eld_mv = hedged_mv**2 - hedged_eld**2
    d_es_mv = hedged_mv**2 - hedged_es**2
    dm_eld = float(d_eld_mv.mean() / (d_eld_mv.std() / np.sqrt(len(d_eld_mv)))) if d_eld_mv.std() > 0 else 0
    dm_es = float(d_es_mv.mean() / (d_es_mv.std() / np.sqrt(len(d_es_mv)))) if d_es_mv.std() > 0 else 0

    print(f"\nDM tests (vs MV-OHR):")
    print(f"  ELD vs MV: t={dm_eld:.2f} ({'★' if abs(dm_eld) > 3 else 'NS'})")
    print(f"  ES vs MV:  t={dm_es:.2f} ({'★' if abs(dm_es) > 3 else 'NS'})")

    all_results[asset_class] = {
        'spot': spot_t, 'futures': fut_t, 'n_oos': n_oos,
        'methods': method_results,
        'dm_eld_vs_mv': round(dm_eld, 2),
        'dm_es_vs_mv': round(dm_es, 2),
    }

# Save
output = {
    'experiment': 'K424',
    'title': 'ELD Optimal Hedge Ratio (FRL 2025)',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data': {'source': 'yfinance', 'oos': '2020-2025'},
    'pairs': all_results,
}

with open('experiments/k424_eld_hedge_results.json', 'w') as f:
    json.dump(output, f, indent=2, ensure_ascii=False, default=str)

print(f"\n{'='*70}")
print("Results saved to experiments/k424_eld_hedge_results.json")
