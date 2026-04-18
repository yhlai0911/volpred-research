"""
K425: Bond-Equity Decorrelation Regime Detection
Extends T19 (TLT structural break) and K269 (SPY-GLD correlation regime).

The 2022 TLT structural break (corr -0.42 → +0.09) is one of our most
important findings. Can we detect and predict regime changes?

Prior knowledge:
- T19: ★★ TLT corr break (Fisher z=-13.58, p<0.0001)
- K269: SPY-GLD corr NOT stable (range -0.61 to +0.69)
- K271: GLD self-healing (100%, 5/5)
- K403: SPY-GLD corr threat LOW (break-even 0.87)
- K163: CoVaR — TLT break confirmed by 3 methods

Step 1: Diagnostics
Step 2: Detect correlation regimes (rolling + CUSUM)
Step 3: What drives correlation regime changes?
Step 4: Can we predict the next break?

Data: SPY, TLT, GLD, ^VIX, ^TNX (10yr yield) from yfinance
Output: experiments/k425_decorrelation_results.json
"""
import yfinance as yf
import numpy as np
import pandas as pd
from scipy import stats
import json, warnings
from datetime import datetime, timezone

warnings.filterwarnings('ignore')

print("=" * 75)
print("K425: Bond-Equity Decorrelation Regime Detection")
print("=" * 75)

# Data
tickers = {'SPY': 'SPY', 'TLT': 'TLT', 'GLD': 'GLD', 'VIX': '^VIX', 'TNX': '^TNX'}
data = {}
for name, t in tickers.items():
    d = yf.download(t, start='2005-01-01', progress=False)['Close'].dropna().squeeze()
    data[name] = d

common = data['SPY'].index
for k in data:
    common = common.intersection(data[k].index)
for k in data:
    data[k] = data[k].loc[common]

rets = {k: data[k].pct_change().dropna() for k in ['SPY', 'TLT', 'GLD']}
vix = data['VIX'].reindex(rets['SPY'].index).fillna(20)
tnx = data['TNX'].reindex(rets['SPY'].index).fillna(3)  # 10yr yield
tnx_chg = tnx.diff()

n = len(rets['SPY'])
print(f"Data: {n} days ({rets['SPY'].index[0].date()} to {rets['SPY'].index[-1].date()})")

# === Step 1: Rolling Correlation ===
print(f"\n{'='*70}")
print("Step 1: Rolling 60d Correlation (SPY-TLT and SPY-GLD)")
print(f"{'='*70}")

corr_spy_tlt = rets['SPY'].rolling(60).corr(rets['TLT'])
corr_spy_gld = rets['SPY'].rolling(60).corr(rets['GLD'])

for pair_name, corr_series in [('SPY-TLT', corr_spy_tlt), ('SPY-GLD', corr_spy_gld)]:
    c = corr_series.dropna()
    print(f"\n{pair_name}:")
    print(f"  Full: mean={c.mean():.3f}, std={c.std():.3f}, range [{c.min():.3f}, {c.max():.3f}]")

    # Pre/Post 2022
    pre = c[c.index < '2022-01-01']
    post = c[c.index >= '2022-01-01']
    print(f"  Pre-2022:  mean={pre.mean():.3f}")
    print(f"  Post-2022: mean={post.mean():.3f}")
    t_break, p_break = stats.ttest_ind(pre.values, post.values)
    print(f"  Break test: t={t_break:.2f}, p={p_break:.6f}")

# === Step 2: CUSUM Break Detection ===
print(f"\n{'='*70}")
print("Step 2: CUSUM Break Detection")
print(f"{'='*70}")

def cusum_test(series, threshold=1.0):
    """Detect structural breaks using CUSUM."""
    s = series.dropna().values
    n = len(s)
    mean = s.mean()
    cusum = np.cumsum(s - mean)
    cusum_norm = cusum / (s.std() * np.sqrt(n))

    # Find max deviation point
    max_idx = np.argmax(np.abs(cusum_norm))
    max_val = cusum_norm[max_idx]

    # Critical value (approximate, 5% level for CUSUM)
    critical = 1.358  # Ploberger-Krämer
    sig = abs(max_val) > critical

    return max_idx, max_val, sig, cusum_norm

for pair_name, corr_series in [('SPY-TLT', corr_spy_tlt), ('SPY-GLD', corr_spy_gld)]:
    c = corr_series.dropna()
    idx, val, sig, cusum = cusum_test(c)
    break_date = c.index[idx]
    sig_str = "★ SIGNIFICANT" if sig else "NS"
    print(f"  {pair_name}: Max CUSUM at {break_date.date()} (val={val:.3f}) {sig_str}")

# === Step 3: What Drives Correlation Changes? ===
print(f"\n{'='*70}")
print("Step 3: Drivers of SPY-TLT Correlation Change")
print(f"{'='*70}")

corr_clean = corr_spy_tlt.dropna()

# Potential drivers
drivers = {
    'VIX Level': vix.reindex(corr_clean.index),
    'VIX Change': vix.pct_change().reindex(corr_clean.index),
    '10yr Yield': tnx.reindex(corr_clean.index),
    'Yield Change': tnx_chg.reindex(corr_clean.index),
    '|SPY ret|': rets['SPY'].abs().rolling(22).mean().reindex(corr_clean.index),
}

print(f"\n{'Driver':<18} {'r(corr)':>10} {'t':>8} {'Harvey':>8}")
print("-" * 48)

driver_results = {}
for dname, driver in drivers.items():
    df = pd.DataFrame({'corr': corr_clean, 'driver': driver}).dropna()
    if len(df) < 100:
        continue

    r, p = stats.pearsonr(df['corr'], df['driver'])
    t_val = r * np.sqrt((len(df)-2) / (1-r**2))
    harvey = "★" if abs(t_val) > 3 else ""
    print(f"{dname:<18} {r:>10.3f} {t_val:>8.2f} {harvey:>8}")
    driver_results[dname] = {'r': round(float(r), 3), 't': round(float(t_val), 2)}

# === Step 4: Predictive Test ===
print(f"\n{'='*70}")
print("Step 4: Can Yield Level Predict Future SPY-TLT Correlation?")
print(f"{'='*70}")

# Test: current yield → next 60d SPY-TLT correlation
future_corr = corr_spy_tlt.shift(-60)
df_pred = pd.DataFrame({
    'yield': tnx,
    'vix': vix,
    'future_corr': future_corr,
}).dropna()

# IS/OOS
is_mask = df_pred.index < '2020-01-01'
oos_mask = df_pred.index >= '2020-01-01'

if oos_mask.sum() > 100:
    # IS regression
    X_is = np.column_stack([np.ones(is_mask.sum()), df_pred.loc[is_mask, 'yield'].values, df_pred.loc[is_mask, 'vix'].values])
    y_is = df_pred.loc[is_mask, 'future_corr'].values
    coef = np.linalg.lstsq(X_is, y_is, rcond=None)[0]

    # OOS predict
    X_oos = np.column_stack([np.ones(oos_mask.sum()), df_pred.loc[oos_mask, 'yield'].values, df_pred.loc[oos_mask, 'vix'].values])
    y_oos = df_pred.loc[oos_mask, 'future_corr'].values
    pred = X_oos @ coef

    r2_oos = 1 - np.sum((y_oos - pred)**2) / np.sum((y_oos - y_oos.mean())**2)
    r_oos, p_oos = stats.pearsonr(pred, y_oos)

    print(f"  OOS R²: {r2_oos:.4f}")
    print(f"  OOS r(pred, actual): {r_oos:.3f} (p={p_oos:.6f})")
    print(f"  Yield coefficient: {coef[1]:.4f} (positive = higher yield → more positive corr)")

    # Current prediction
    current_yield = float(tnx.iloc[-1])
    current_vix = float(vix.iloc[-1])
    pred_corr = coef[0] + coef[1] * current_yield + coef[2] * current_vix
    print(f"\n  Current yield: {current_yield:.2f}%, VIX: {current_vix:.1f}")
    print(f"  Predicted 60d SPY-TLT corr: {pred_corr:.3f}")
    print(f"  Current actual 60d corr: {corr_spy_tlt.iloc[-1]:.3f}")

# Save
output = {
    'experiment': 'K425',
    'title': 'Bond-Equity Decorrelation Regime Detection',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data': {'source': 'yfinance', 'tickers': list(tickers.keys()), 'n': n},
    'correlation_stats': {
        'SPY-TLT': {'pre2022': round(float(corr_spy_tlt[corr_spy_tlt.index < '2022-01-01'].mean()), 3),
                     'post2022': round(float(corr_spy_tlt[corr_spy_tlt.index >= '2022-01-01'].mean()), 3)},
        'SPY-GLD': {'pre2022': round(float(corr_spy_gld[corr_spy_gld.index < '2022-01-01'].mean()), 3),
                     'post2022': round(float(corr_spy_gld[corr_spy_gld.index >= '2022-01-01'].mean()), 3)},
    },
    'drivers': driver_results,
}

with open('experiments/k425_decorrelation_results.json', 'w') as f:
    json.dump(output, f, indent=2, ensure_ascii=False, default=str)

print(f"\nResults saved to experiments/k425_decorrelation_results.json")
