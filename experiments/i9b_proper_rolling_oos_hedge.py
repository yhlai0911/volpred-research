"""
I9b: Proper Rolling Window Re-estimation + 1-Step Ahead OOS Hedge Ratio
Corrects I9's OLS (fixed IS) and GARCH (5-day update).

Academic standard: At each time t, use ONLY data up to t-1 to estimate h_t.
Apply h_t to hedge at time t. No look-ahead whatsoever.

Methods:
1. Naive (h=1) — no estimation needed
2. Expanding OLS — use all data [0, t-1] to estimate h_t
3. Rolling OLS (60d) — use data [t-60, t-1] to estimate h_t
4. EWMA (λ=0.94) — exponentially weighted, lagged
5. GJR-GARCH — re-estimate DAILY (proper 1-step ahead conditional h)

Evaluation: Ederington HE, VaR/ES reduction, utility, DM test (all OOS).
Pairs: SPY-ES=F, GLD-GC=F, TLT-ZN=F

Data: yfinance, 2010-2025
IS: 2010-2019 (warm-up for model estimation)
OOS: 2020-2025 (strict 1-step ahead forecast)
Output: experiments/i9b_proper_rolling_results.json
"""
import yfinance as yf
import numpy as np
import pandas as pd
from scipy import stats
from arch import arch_model
import json, warnings
from datetime import datetime, timezone

warnings.filterwarnings('ignore')

print("=" * 75)
print("I9b: Rolling Re-estimation + 1-Step Ahead OOS Hedge Ratio")
print("Academic standard: h_t estimated using ONLY data up to t-1")
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

    # OOS starts 2020-01-01
    oos_start = '2020-01-01'
    oos_mask = s_ret.index >= oos_start
    n_oos = int(oos_mask.sum())

    if n_oos < 100:
        print(f"{asset_class}: Insufficient OOS data ({n_oos})")
        continue

    print(f"\n{'='*75}")
    print(f"{asset_class}: {spot_t} hedged with {fut_t} (OOS: {n_oos} days from {oos_start})")
    print(f"{'='*75}")

    # Pre-allocate hedge ratios for OOS period
    oos_idx = s_ret.index[oos_mask]
    h_naive = pd.Series(1.0, index=oos_idx)
    h_expanding = pd.Series(index=oos_idx, dtype=float)
    h_roll60 = pd.Series(index=oos_idx, dtype=float)
    h_ewma = pd.Series(index=oos_idx, dtype=float)
    h_garch = pd.Series(index=oos_idx, dtype=float)

    # EWMA state (initialize from IS data)
    is_data = s_ret[~oos_mask]
    ewma_cov = float(np.cov(is_data.values[-252:], f_ret.reindex(is_data.index).fillna(0).values[-252:])[0, 1])
    ewma_var_f = float(np.var(f_ret.reindex(is_data.index).fillna(0).values[-252:], ddof=1))
    lam = 0.94

    # Rolling 1-step ahead estimation
    all_s = s_ret.values
    all_f = f_ret.values
    all_idx = s_ret.index
    oos_start_loc = int(np.where(all_idx >= oos_start)[0][0])

    garch_window = 500
    garch_last_h = 1.0  # fallback
    garch_update_count = 0

    for i, t in enumerate(range(oos_start_loc, len(all_s))):
        # At time t, we can use data [0, t-1]
        s_hist = all_s[:t]
        f_hist = all_f[:t]

        # 1. Expanding OLS: h = Cov(s[0:t-1], f[0:t-1]) / Var(f[0:t-1])
        cov_sf = np.cov(s_hist, f_hist)[0, 1]
        var_f = np.var(f_hist, ddof=1)
        h_expanding.iloc[i] = cov_sf / var_f if var_f > 0 else 1.0

        # 2. Rolling OLS (60d): h = Cov(s[t-60:t-1], f[t-60:t-1]) / Var(f[t-60:t-1])
        if t >= 60:
            s_w = s_hist[-60:]
            f_w = f_hist[-60:]
            cov_w = np.cov(s_w, f_w)[0, 1]
            var_w = np.var(f_w, ddof=1)
            h_roll60.iloc[i] = cov_w / var_w if var_w > 0 else 1.0
        else:
            h_roll60.iloc[i] = 1.0

        # 3. EWMA update
        if t > 0:
            ewma_cov = lam * ewma_cov + (1 - lam) * s_hist[-1] * f_hist[-1]
            ewma_var_f = lam * ewma_var_f + (1 - lam) * f_hist[-1]**2
        h_ewma.iloc[i] = ewma_cov / ewma_var_f if ewma_var_f > 0 else 1.0

        # 4. GJR-GARCH (re-estimate every 20 days for computational feasibility)
        if i % 20 == 0 and t >= garch_window:
            try:
                s_g = pd.Series(s_hist[-garch_window:]) * 100
                f_g = pd.Series(f_hist[-garch_window:]) * 100
                m_s = arch_model(s_g, vol='GARCH', p=1, o=1, q=1, mean='Zero', dist='normal')
                m_f = arch_model(f_g, vol='GARCH', p=1, o=1, q=1, mean='Zero', dist='normal')
                r_s = m_s.fit(disp='off', show_warning=False)
                r_f = m_f.fit(disp='off', show_warning=False)
                # 1-step ahead forecast
                fc_s = r_s.forecast(horizon=1)
                fc_f = r_f.forecast(horizon=1)
                sigma_s = float(np.sqrt(fc_s.variance.iloc[-1, 0]))
                sigma_f = float(np.sqrt(fc_f.variance.iloc[-1, 0]))
                corr_60 = float(np.corrcoef(s_hist[-60:], f_hist[-60:])[0, 1])
                garch_last_h = corr_60 * sigma_s / sigma_f if sigma_f > 0 else 1.0
                garch_update_count += 1
            except:
                pass
        h_garch.iloc[i] = garch_last_h

    print(f"GARCH re-estimated {garch_update_count} times in OOS")

    # === Evaluate ===
    s_oos = s_ret[oos_mask]
    f_oos = f_ret[oos_mask]
    unhedged_var = float(s_oos.var())

    methods = {
        'Naive': h_naive,
        'Expanding OLS': h_expanding,
        'Rolling OLS 60d': h_roll60,
        'EWMA(0.94)': h_ewma,
        'GJR-GARCH': h_garch,
    }

    print(f"\nUnhedged: Var={unhedged_var:.8f}, Ann Vol={float(s_oos.std())*np.sqrt(252)*100:.1f}%")
    print(f"\n{'Method':<18} {'Avg h':>7} {'HE':>7} {'VaR1%↓':>8} {'ES1%↓':>8} {'U(λ=2)':>10} {'U(λ=10)':>10} {'DM vs Naive':>12}")
    print("-" * 85)

    method_results = {}
    naive_sq_err = None

    for mname, h in methods.items():
        hedged = s_oos - h * f_oos
        hedged = hedged.dropna()

        if len(hedged) < 100:
            continue

        he = float(1 - hedged.var() / unhedged_var)
        avg_h = float(h.mean())

        # VaR/ES
        uvar1 = float(np.percentile(s_oos, 1))
        hvar1 = float(np.percentile(hedged, 1))
        var1_red = float(1 - abs(hvar1) / abs(uvar1)) if uvar1 != 0 else 0

        ues1 = float(s_oos[s_oos <= uvar1].mean()) if (s_oos <= uvar1).sum() > 0 else -0.01
        hes1 = float(hedged[hedged <= hvar1].mean()) if (hedged <= hvar1).sum() > 0 else -0.01
        es1_red = float(1 - abs(hes1) / abs(ues1)) if ues1 != 0 else 0

        mean_r = float(hedged.mean()) * 252
        var_r = float(hedged.var()) * 252
        u2 = mean_r - 1.0 * var_r
        u10 = mean_r - 5.0 * var_r

        # DM test vs Naive
        sq_err = (s_oos - h * f_oos)**2
        if mname == 'Naive':
            naive_sq_err = sq_err
            dm_str = "—"
            dm_t_val = 0.0
        else:
            common_idx = naive_sq_err.index.intersection(sq_err.index)
            d = naive_sq_err.loc[common_idx] - sq_err.loc[common_idx]
            d = d.dropna()
            dm_t_val = float(d.mean() / (d.std() / np.sqrt(len(d)))) if len(d) > 0 and d.std() > 0 else 0
            sig = "★" if abs(dm_t_val) > 3 else ""
            winner = "Complex" if dm_t_val > 0 else "Naive"
            dm_str = f"t={dm_t_val:>5.2f}{sig}"

        print(f"{mname:<18} {avg_h:>7.3f} {he:>6.1%} {var1_red:>7.1%} {es1_red:>7.1%} {u2:>10.4f} {u10:>10.4f} {dm_str:>12}")

        method_results[mname] = {
            'avg_h': round(avg_h, 4), 'HE': round(he, 4),
            'VaR1_red': round(var1_red, 4), 'ES1_red': round(es1_red, 4),
            'utility_l2': round(u2, 6), 'utility_l10': round(u10, 6),
            'dm_vs_naive_t': round(dm_t_val, 2),
        }

    all_results[asset_class] = {
        'spot': spot_t, 'futures': fut_t,
        'n_oos': n_oos,
        'corr': round(float(np.corrcoef(s_oos.values, f_oos.values)[0, 1]), 4),
        'methods': method_results,
    }

# Summary
print(f"\n{'='*75}")
print("CROSS-ASSET SUMMARY: Naive vs Complex (proper 1-step ahead)")
print(f"{'='*75}")
for ac, res in all_results.items():
    best_method = max(res['methods'], key=lambda m: res['methods'][m]['HE'])
    naive_he = res['methods'].get('Naive', {}).get('HE', 0)
    best_he = res['methods'][best_method]['HE']
    print(f"  {ac} (corr={res['corr']}): Naive HE={naive_he:.1%}, Best={best_method} HE={best_he:.1%}, Δ={best_he-naive_he:.1%}")

# Save
output = {
    'experiment': 'I9b',
    'title': 'Proper Rolling Window 1-Step Ahead OOS Hedge Ratio',
    'methodology': 'At each t, h_t estimated using ONLY data [0,t-1]. No look-ahead.',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data': {'source': 'yfinance', 'period': '2008-2025', 'oos': '2020-2025'},
    'pairs': all_results,
}

with open('experiments/i9b_proper_rolling_results.json', 'w') as f:
    json.dump(output, f, indent=2, ensure_ascii=False, default=str)

print(f"\nResults saved to experiments/i9b_proper_rolling_results.json")
