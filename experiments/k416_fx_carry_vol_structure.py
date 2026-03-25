"""
K416: FX Carry Trade Volatility Structure
Jumping direction: How do FX carry currencies' vol differ from safe-haven currencies?
Does carry trade unwinding predict equity vol?

Uses available FX futures pairs: FXE-6E, FXY-6J, FXB-6B, FXA-6A
Related: K18 (VIX-timed forex carry), K29 (VT vs alternatives)

Data: FXE/FXY/FXB/FXA + SPY + ^VIX from yfinance, 2010-2025
Output: experiments/k416_fx_carry_vol_results.json
"""
import yfinance as yf
import numpy as np
import pandas as pd
from scipy import stats
import json
from datetime import datetime, timezone

print("=" * 70)
print("K416: FX Carry Volatility Structure")
print("=" * 70)

# Download FX ETFs (proxy for currency exposure)
tickers = {
    'FXE': 'EUR/USD (funding)',
    'FXY': 'JPY/USD (safe haven)',
    'FXB': 'GBP/USD (mixed)',
    'FXA': 'AUD/USD (carry)',
    'SPY': 'S&P 500',
}

data = {}
for t in list(tickers.keys()) + ['^VIX']:
    d = yf.download(t, start='2010-01-01', progress=False)['Close'].dropna().squeeze()
    data[t] = d

# Align
common = data['SPY'].index
for k in data:
    common = common.intersection(data[k].index)
for k in data:
    data[k] = data[k].loc[common]

vix = data['^VIX']
rets = {k: data[k].pct_change().dropna() for k in tickers}
vix_v = vix.reindex(rets['SPY'].index).fillna(20)
n = len(rets['SPY'])
print(f"Data: {n} days ({rets['SPY'].index[0].date()} to {rets['SPY'].index[-1].date()})")

# Part 1: Volatility characteristics of each currency
print(f"\n{'Currency':<25} {'Ann Vol':>8} {'Skew':>6} {'Kurt':>6} {'Corr(SPY)':>10} {'Beta(VIX)':>10}")
print("=" * 70)

fx_results = {}
for t, name in tickers.items():
    r = rets[t]
    vol = float(r.std() * np.sqrt(252) * 100)
    skew = float(r.skew())
    kurt = float(r.kurtosis())
    corr_spy = float(r.corr(rets['SPY']))

    # Beta to VIX changes
    vix_chg = vix_v.pct_change().dropna().reindex(r.index).fillna(0)
    slope, intercept, r_val, p_val, se = stats.linregress(vix_chg.values, r.values)

    print(f"{name:<25} {vol:>7.1f}% {skew:>6.2f} {kurt:>6.2f} {corr_spy:>10.3f} {slope*100:>9.2f}%")

    fx_results[t] = {
        'name': name, 'ann_vol': round(vol, 1),
        'skewness': round(skew, 2), 'kurtosis': round(kurt, 2),
        'corr_spy': round(corr_spy, 3),
        'vix_beta': round(float(slope), 6),
    }

# Part 2: Carry trade proxy — AUD/JPY spread
# AUD is carry (high yield), JPY is safe haven (low yield)
# AUD/JPY ≈ FXA/FXY (simplified)
aud_ret = rets['FXA']
jpy_ret = rets['FXY']
carry_ret = aud_ret - jpy_ret  # Long AUD, short JPY

carry_rv22 = carry_ret.rolling(22).std() * np.sqrt(252) * 100
spy_future_rv = rets['SPY'].rolling(22).std().shift(-22) * np.sqrt(252) * 100

print(f"\n{'='*70}")
print("Part 2: AUD/JPY Carry Trade Vol → SPY Future Vol?")
print(f"{'='*70}")

# Correlation: carry vol → SPY future vol
df = pd.DataFrame({
    'carry_rv': carry_rv22,
    'spy_future_rv': spy_future_rv,
    'vix': vix_v,
}).dropna()

r_simple, p_simple = stats.pearsonr(df['carry_rv'], df['spy_future_rv'])
print(f"Simple r(carry_rv, spy_future_rv): {r_simple:.3f} (p={p_simple:.6f})")

# Partial r controlling VIX
n_df = len(df)
X_vix = np.column_stack([np.ones(n_df), df['vix'].values])
res_carry = df['carry_rv'].values - X_vix @ np.linalg.lstsq(X_vix, df['carry_rv'].values, rcond=None)[0]
res_spy = df['spy_future_rv'].values - X_vix @ np.linalg.lstsq(X_vix, df['spy_future_rv'].values, rcond=None)[0]
r_partial, p_partial = stats.pearsonr(res_carry, res_spy)
t_partial = r_partial * np.sqrt((n_df-3) / (1-r_partial**2))
harvey = "★ PASS" if abs(t_partial) > 3 else "FAIL"
print(f"Partial r(carry_rv | VIX): {r_partial:.3f} (t={t_partial:.2f}, p={p_partial:.6f}) Harvey: {harvey}")

# Part 3: Carry trade crash → equity vol spike?
print(f"\n{'='*70}")
print("Part 3: Carry Trade Crash → Equity Vol Spike?")
print(f"{'='*70}")

# Define carry crash: daily AUD/JPY return < -2%
carry_crash = carry_ret < -0.02
n_crashes = int(carry_crash.sum())
print(f"Carry crashes (daily ret < -2%): {n_crashes} events")

if n_crashes > 10:
    # SPY vol in next 5 days after carry crash
    spy_abs_ret = rets['SPY'].abs()

    crash_dates = carry_crash[carry_crash].index
    post_crash_vol = []
    normal_vol = []

    for date in crash_dates:
        idx = rets['SPY'].index.get_loc(date)
        if idx + 5 < len(rets['SPY']):
            post_vol = float(spy_abs_ret.iloc[idx+1:idx+6].mean()) * np.sqrt(252) * 100
            post_crash_vol.append(post_vol)

    # Normal days vol
    non_crash = ~carry_crash
    for i in range(0, min(n_crashes*5, int(non_crash.sum())), 5):
        idx = non_crash[non_crash].index[i]
        loc = rets['SPY'].index.get_loc(idx)
        if loc + 5 < len(rets['SPY']):
            norm_vol = float(spy_abs_ret.iloc[loc+1:loc+6].mean()) * np.sqrt(252) * 100
            normal_vol.append(norm_vol)

    if post_crash_vol and normal_vol:
        mean_post = np.mean(post_crash_vol)
        mean_norm = np.mean(normal_vol[:len(post_crash_vol)])
        t_stat, p_val = stats.ttest_ind(post_crash_vol, normal_vol[:len(post_crash_vol)])
        ratio = mean_post / mean_norm if mean_norm > 0 else float('inf')

        print(f"Post-crash 5d SPY vol: {mean_post:.1f}%")
        print(f"Normal 5d SPY vol:     {mean_norm:.1f}%")
        print(f"Ratio: {ratio:.2f}x")
        print(f"t-test: t={t_stat:.2f}, p={p_val:.4f}")

# Part 4: FX vol regime → SPY performance
print(f"\n{'='*70}")
print("Part 4: FX Implied Vol Regime (proxy: carry spread vol)")
print(f"{'='*70}")

# High carry vol = risk-off
carry_vol_q = pd.qcut(carry_rv22.dropna(), 3, labels=['Low', 'Medium', 'High'])
spy_ret_aligned = rets['SPY'].reindex(carry_vol_q.dropna().index)

for q in ['Low', 'Medium', 'High']:
    mask = carry_vol_q == q
    mask = mask.reindex(spy_ret_aligned.index).fillna(False)
    if mask.sum() > 50:
        r = spy_ret_aligned[mask]
        ann_ret = float(r.mean()) * 252 * 100
        ann_vol = float(r.std()) * np.sqrt(252) * 100
        sharpe = float(r.mean() / r.std() * np.sqrt(252))
        print(f"  {q:<8} carry vol: SPY ann ret={ann_ret:>6.1f}%, vol={ann_vol:>5.1f}%, Sharpe={sharpe:.3f}")

# Save results
output = {
    'experiment': 'K416',
    'title': 'FX Carry Volatility Structure',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data': {
        'source': 'yfinance',
        'tickers': list(tickers.keys()) + ['^VIX'],
        'period': f"{rets['SPY'].index[0].date()} to {rets['SPY'].index[-1].date()}",
        'n_obs': n,
    },
    'fx_characteristics': fx_results,
    'carry_vol_prediction': {
        'simple_r': round(float(r_simple), 3),
        'partial_r_vix': round(float(r_partial), 3),
        't_partial': round(float(t_partial), 2),
        'harvey_pass': abs(t_partial) > 3,
    },
    'carry_crash_analysis': {
        'n_crashes': n_crashes,
    },
}

with open('experiments/k416_fx_carry_vol_results.json', 'w') as f:
    json.dump(output, f, indent=2, ensure_ascii=False, default=str)

print(f"\nResults saved to experiments/k416_fx_carry_vol_results.json")
