"""
I9: Proper Hedging Effectiveness Evaluation (Academic Standard)
Following Ederington (1979), Park & Switzer (1995), and recent literature.

Corrects I3/I5/I6 which incorrectly compared hedging to trading strategies.
Hedging goal = RISK REDUCTION, evaluated with hedging-specific metrics.

Metrics:
1. HE (Hedging Effectiveness) = 1 - Var(hedged)/Var(unhedged) [Ederington 1979]
2. VaR Reduction: 1% and 5% VaR improvement
3. ES Reduction: Expected Shortfall improvement
4. Utility: U = E[R] - λ/2 × Var(R) for λ = {1, 2, 5, 10}
5. Basis Risk: Var(hedging error) stability over time
6. OHR Turnover: cost of dynamic rebalancing

Methods: Naive(h=1), OLS, Rolling-OLS(60d), EWMA(0.94), GJR-GARCH
Pairs: SPY-ES=F, GLD-GC=F, TLT-ZN=F
OOS: IS 2010-2019, OOS 2020-2025

Data: yfinance, 2010-2025
Output: experiments/i9/i9_proper_hedging_results.json
"""
from pathlib import Path

import yfinance as yf
import numpy as np
import pandas as pd
from scipy import stats
from arch import arch_model
import json, warnings
from datetime import datetime, timezone

warnings.filterwarnings('ignore')

EXPERIMENT_DIR = Path(__file__).resolve().parent
RESULTS_FILE = EXPERIMENT_DIR / 'i9_proper_hedging_results.json'

print("=" * 75)
print("I9: Proper Hedging Effectiveness Evaluation (Academic Standard)")
print("Following Ederington (1979), utility-based, VaR/ES reduction")
print("=" * 75)

# Data
pairs = [
    ('SPY', 'ES=F', 'Equity'),
    ('GLD', 'GC=F', 'Gold'),
    ('TLT', 'ZN=F', 'Bond'),
]

all_results = {}

for spot_t, fut_t, asset_class in pairs:
    spot = yf.download(spot_t, start='2010-01-01', progress=False)['Close'].dropna().squeeze()
    fut = yf.download(fut_t, start='2010-01-01', progress=False)['Close'].dropna().squeeze()

    common = spot.index.intersection(fut.index)
    spot, fut = spot.loc[common], fut.loc[common]
    s_ret = spot.pct_change().dropna()
    f_ret = fut.pct_change().dropna().reindex(s_ret.index).fillna(0)
    n = len(s_ret)

    # IS/OOS split
    is_mask = s_ret.index < '2020-01-01'
    oos_mask = s_ret.index >= '2020-01-01'
    n_is = int(is_mask.sum())
    n_oos = int(oos_mask.sum())

    # === Method 1: Naive (h=1) ===
    h_naive = pd.Series(1.0, index=s_ret.index)

    # === Method 2: OLS (IS only, applied to OOS) ===
    s_is, f_is = s_ret[is_mask].values, f_ret[is_mask].values
    h_ols_val = float(np.cov(s_is, f_is)[0, 1] / np.var(f_is, ddof=1))
    h_ols = pd.Series(h_ols_val, index=s_ret.index)

    # === Method 3: Rolling OLS (60d, lagged 1d) ===
    h_roll = pd.Series(index=s_ret.index, dtype=float)
    for i in range(60, n):
        s = s_ret.iloc[i-60:i].values
        f = f_ret.iloc[i-60:i].values
        var_f = np.var(f, ddof=1)
        h_roll.iloc[i] = np.cov(s, f)[0, 1] / var_f if var_f > 0 else 1.0
    h_roll = h_roll.shift(1)  # lagged for OOS

    # === Method 4: EWMA(0.94) (lagged) ===
    ewma_cov = s_ret.ewm(alpha=0.06).cov(f_ret)
    ewma_var = f_ret.ewm(alpha=0.06).var()
    h_ewma = (ewma_cov / ewma_var).shift(1)

    # === Method 5: GJR-GARCH (rolling, lagged) ===
    h_garch = pd.Series(index=s_ret.index, dtype=float)
    window = 500
    for i in range(window, n, 5):  # Re-estimate every 5 days for speed
        try:
            s_w = s_ret.iloc[i-window:i] * 100
            f_w = f_ret.iloc[i-window:i] * 100
            m_s = arch_model(s_w, vol='GARCH', p=1, o=1, q=1, mean='Zero', dist='normal')
            m_f = arch_model(f_w, vol='GARCH', p=1, o=1, q=1, mean='Zero', dist='normal')
            r_s = m_s.fit(disp='off', show_warning=False)
            r_f = m_f.fit(disp='off', show_warning=False)
            sigma_s = float(r_s.conditional_volatility.iloc[-1])
            sigma_f = float(r_f.conditional_volatility.iloc[-1])
            corr = float(np.corrcoef(s_w.values[-60:], f_w.values[-60:])[0, 1])
            h_val = corr * sigma_s / sigma_f if sigma_f > 0 else 1.0
            for j in range(min(5, n - i)):
                h_garch.iloc[i + j] = h_val
        except:
            pass
    h_garch = h_garch.shift(1)  # lagged

    methods = {
        'Naive': h_naive,
        'OLS': h_ols,
        'Roll-OLS': h_roll,
        'EWMA': h_ewma,
        'GJR-GARCH': h_garch,
    }

    # === Evaluate each method (OOS only) ===
    print(f"\n{'='*75}")
    print(f"{asset_class}: {spot_t} hedged with {fut_t} (IS={n_is}, OOS={n_oos})")
    print(f"{'='*75}")

    s_oos = s_ret[oos_mask]
    f_oos = f_ret[oos_mask]
    unhedged_var = float(s_oos.var())
    unhedged_var1 = float(np.percentile(s_oos, 1))
    unhedged_var5 = float(np.percentile(s_oos, 5))
    unhedged_es1 = float(s_oos[s_oos <= unhedged_var1].mean())

    print(f"\nUnhedged: Var={unhedged_var:.8f}, 1%VaR={unhedged_var1*100:.2f}%, 5%VaR={unhedged_var5*100:.2f}%, ES={unhedged_es1*100:.2f}%")
    print(f"\n{'Method':<12} {'HE':>7} {'VaR1%↓':>8} {'VaR5%↓':>8} {'ES1%↓':>8} {'U(λ=2)':>10} {'U(λ=5)':>10} {'U(λ=10)':>10} {'Turnover':>10}")
    print("-" * 90)

    method_results = {}
    for mname, h in methods.items():
        h_oos = h.reindex(s_oos.index).ffill().fillna(1.0)
        hedged_ret = s_oos - h_oos * f_oos
        hedged_ret = hedged_ret.dropna()

        if len(hedged_ret) < 100:
            continue

        # HE (Ederington)
        he = float(1 - hedged_ret.var() / unhedged_var)

        # VaR reduction
        h_var1 = float(np.percentile(hedged_ret, 1))
        h_var5 = float(np.percentile(hedged_ret, 5))
        var1_red = float(1 - abs(h_var1) / abs(unhedged_var1)) if unhedged_var1 != 0 else 0
        var5_red = float(1 - abs(h_var5) / abs(unhedged_var5)) if unhedged_var5 != 0 else 0

        # ES reduction
        h_es1 = float(hedged_ret[hedged_ret <= h_var1].mean()) if (hedged_ret <= h_var1).sum() > 0 else 0
        es1_red = float(1 - abs(h_es1) / abs(unhedged_es1)) if unhedged_es1 != 0 else 0

        # Utility: U = E[R] - λ/2 × Var(R)
        mean_r = float(hedged_ret.mean()) * 252
        var_r = float(hedged_ret.var()) * 252
        u2 = mean_r - 1.0 * var_r
        u5 = mean_r - 2.5 * var_r
        u10 = mean_r - 5.0 * var_r

        # Unhedged utility for comparison
        mean_uh = float(s_oos.mean()) * 252
        var_uh = float(s_oos.var()) * 252
        u2_uh = mean_uh - 1.0 * var_uh
        u5_uh = mean_uh - 2.5 * var_uh

        # Turnover (daily change in h)
        h_change = h_oos.diff().abs()
        turnover = float(h_change.mean()) * 252

        print(f"{mname:<12} {he:>6.1%} {var1_red:>7.1%} {var5_red:>7.1%} {es1_red:>7.1%} {u2:>10.4f} {u5:>10.4f} {u10:>10.4f} {turnover:>10.2f}")

        method_results[mname] = {
            'HE': round(he, 4),
            'VaR1_reduction': round(var1_red, 4),
            'VaR5_reduction': round(var5_red, 4),
            'ES1_reduction': round(es1_red, 4),
            'utility_lambda2': round(u2, 6),
            'utility_lambda5': round(u5, 6),
            'utility_lambda10': round(u10, 6),
            'annual_turnover': round(turnover, 4),
            'avg_h': round(float(h_oos.mean()), 4),
        }

    # DM test: best dynamic vs naive (on squared hedging errors)
    best_dynamic = max(['EWMA', 'GJR-GARCH'], key=lambda m: method_results.get(m, {}).get('HE', 0))
    h_best = methods[best_dynamic].reindex(s_oos.index).ffill().fillna(1.0)
    h_n = methods['Naive'].reindex(s_oos.index).fillna(1.0)
    e_naive = (s_oos - h_n * f_oos)**2
    e_best = (s_oos - h_best * f_oos)**2
    d = e_naive - e_best
    d = d.dropna()
    dm_t = float(d.mean() / (d.std() / np.sqrt(len(d)))) if len(d) > 0 and d.std() > 0 else 0
    harvey = "★ PASS" if abs(dm_t) > 3 else "FAIL"

    print(f"\nDM test ({best_dynamic} vs Naive): t={dm_t:.2f} ({harvey})")
    print(f"Unhedged utility: U(λ=2)={u2_uh:.4f}, U(λ=5)={u5_uh:.4f}")

    all_results[asset_class] = {
        'spot': spot_t, 'futures': fut_t,
        'n_is': n_is, 'n_oos': n_oos,
        'spot_futures_corr': round(float(np.corrcoef(s_oos.values, f_oos.values)[0, 1]), 4),
        'methods': method_results,
        'dm_best_vs_naive': {'method': best_dynamic, 't': round(dm_t, 2), 'harvey': harvey},
    }

# Save
output = {
    'experiment': 'I9',
    'title': 'Proper Hedging Effectiveness (Academic Standard)',
    'methodology': 'Ederington (1979) HE + VaR/ES reduction + utility-based + DM test',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data': {'source': 'yfinance', 'period': '2010-2025', 'is': '2010-2019', 'oos': '2020-2025'},
    'pairs': all_results,
}

with open(RESULTS_FILE, 'w') as f:
    json.dump(output, f, indent=2, ensure_ascii=False, default=str)

print(f"\n{'='*75}")
print(f"Results saved to {RESULTS_FILE}")
print(f"{'='*75}")
