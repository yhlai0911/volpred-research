"""
K422: Commodity Volatility Spillover Network
Jumping direction: How does vol transmit across commodity futures?

Uses available commodity futures: GC=F, SI=F, CL=F, NG=F, ZC=F, ZW=F, ZS=F, HG=F
Plus equity (ES=F) and bond (ZN=F) as reference.

Step 1: Data diagnostics
Step 2: Granger causality network
Step 3: Diebold-Yilmaz spillover index
Step 4: Does commodity vol spillover predict equity vol?

Prior knowledge:
- K7: SPY hub in vol spillover network
- K169: Dynamic vol network — SPY hub 82%, crisis → IWM/XLF
- K148: Climate vol NULL (except USO hurricanes)
- K21: Commodity VT null (supply-driven vol orthogonal to VIX)

Data: yfinance commodity futures, 2010-2025
Output: experiments/k422_commodity_spillover_results.json
"""
import yfinance as yf
import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.tsa.stattools import grangercausalitytests
import json, warnings
from datetime import datetime, timezone

warnings.filterwarnings('ignore')

print("=" * 75)
print("K422: Commodity Volatility Spillover Network")
print("=" * 75)

# Data
tickers = {
    'Gold': 'GC=F', 'Silver': 'SI=F', 'Oil': 'CL=F', 'NatGas': 'NG=F',
    'Corn': 'ZC=F', 'Wheat': 'ZW=F', 'Soybean': 'ZS=F', 'Copper': 'HG=F',
    'SPX': 'ES=F', 'Bond': 'ZN=F',
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

# Align and compute returns + realized vol
common = list(data.values())[0].index
for k in data:
    common = common.intersection(data[k].index)
for k in data:
    data[k] = data[k].loc[common]

rets = {k: data[k].pct_change().dropna() for k in data}
# 22-day realized vol
rvols = {k: rets[k].rolling(22).std() * np.sqrt(252) for k in data}

n = len(list(rets.values())[0])
assets = list(data.keys())
print(f"Common dates: {n} ({common[0].date()} to {common[-1].date()})")
print(f"Assets: {', '.join(assets)}")

# === Step 1: Diagnostics ===
print(f"\n--- Diagnostics ---")
print(f"{'Asset':<10} {'Vol%':>6} {'Skew':>6} {'Kurt':>6} {'Corr(SPX)':>10}")
print("-" * 40)
for a in assets:
    vol = float(rets[a].std() * np.sqrt(252) * 100)
    skew = float(rets[a].skew())
    kurt = float(rets[a].kurtosis())
    corr = float(rets[a].corr(rets.get('SPX', rets[a])))
    print(f"{a:<10} {vol:>5.1f}% {skew:>6.2f} {kurt:>6.1f} {corr:>10.3f}")

# === Step 2: Granger Causality Network ===
print(f"\n{'='*70}")
print("Step 2: Vol Granger Causality (lag=5, using RV)")
print(f"{'='*70}")

rv_df = pd.DataFrame(rvols).dropna()
granger_matrix = pd.DataFrame(0.0, index=assets, columns=assets)

for cause in assets:
    for effect in assets:
        if cause == effect:
            continue
        try:
            test_data = rv_df[[effect, cause]].dropna()
            if len(test_data) > 100:
                result = grangercausalitytests(test_data.values, maxlag=5, verbose=False)
                # Use lag=5 F-test p-value
                p_val = result[5][0]['ssr_ftest'][1]
                granger_matrix.loc[cause, effect] = round(float(p_val), 4)
        except:
            granger_matrix.loc[cause, effect] = 1.0

# Count significant Granger links
sig_threshold = 0.05
print(f"\nGranger causality network (p < {sig_threshold}):")
print(f"{'From':<10} → {'To':<10} {'p-value':>10}")
print("-" * 35)

links = []
for cause in assets:
    for effect in assets:
        if cause != effect and granger_matrix.loc[cause, effect] < sig_threshold:
            links.append((cause, effect, granger_matrix.loc[cause, effect]))

links.sort(key=lambda x: x[2])
for cause, effect, p in links[:20]:
    print(f"{cause:<10} → {effect:<10} {p:>10.4f}")

print(f"\nTotal significant links: {len(links)} / {len(assets)*(len(assets)-1)}")

# Hub analysis: out-degree (causes others) and in-degree (caused by others)
print(f"\n{'Asset':<10} {'Out-degree':>11} {'In-degree':>10} {'Net':>5} {'Role':>12}")
print("-" * 50)

roles = {}
for a in assets:
    out_deg = sum(1 for _, e, p in links if _ == a)
    in_deg = sum(1 for c, _, p in links if _ == a)
    net = out_deg - in_deg
    role = 'NET SENDER' if net > 2 else 'NET RECEIVER' if net < -2 else 'BALANCED'
    roles[a] = {'out': out_deg, 'in': in_deg, 'net': net, 'role': role}
    print(f"{a:<10} {out_deg:>11} {in_deg:>10} {net:>5} {role:>12}")

# === Step 3: Does commodity vol predict equity vol? ===
print(f"\n{'='*70}")
print("Step 3: Commodity Vol → Equity (SPX) Vol Prediction")
print(f"{'='*70}")

spy_future_rv = rvols['SPX'].shift(-22)  # 22d ahead
vix = yf.download('^VIX', start='2010-01-01', progress=False)['Close'].dropna().squeeze()
vix = vix.reindex(rv_df.index).fillna(20) / 100

print(f"\n{'Commodity RV':<12} {'Simple r':>10} {'Partial r|VIX':>14} {'t':>7} {'Harvey':>8}")
print("-" * 55)

pred_results = {}
for a in assets:
    if a in ['SPX', 'Bond']:
        continue

    df = pd.DataFrame({
        'pred': rvols[a],
        'target': spy_future_rv,
        'vix': vix,
    }).dropna()

    if len(df) < 252:
        continue

    n_df = len(df)
    r_simple, _ = stats.pearsonr(df['pred'], df['target'])

    X = np.column_stack([np.ones(n_df), df['vix'].values])
    res_p = df['pred'].values - X @ np.linalg.lstsq(X, df['pred'].values, rcond=None)[0]
    res_t = df['target'].values - X @ np.linalg.lstsq(X, df['target'].values, rcond=None)[0]
    r_partial, p_partial = stats.pearsonr(res_p, res_t)
    t_val = r_partial * np.sqrt((n_df-3) / (1-r_partial**2))
    harvey = "★" if abs(t_val) > 3 else ""

    print(f"{a:<12} {r_simple:>10.3f} {r_partial:>14.3f} {t_val:>7.2f} {harvey:>8}")
    pred_results[a] = {'simple_r': round(float(r_simple), 3), 'partial_r': round(float(r_partial), 3), 't': round(float(t_val), 2)}

# Save
output = {
    'experiment': 'K422',
    'title': 'Commodity Volatility Spillover Network',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data': {'source': 'yfinance', 'assets': assets, 'n': n},
    'granger_network': {'total_sig_links': len(links), 'roles': roles},
    'commodity_to_equity': pred_results,
}

with open('experiments/k422_commodity_spillover_results.json', 'w') as f:
    json.dump(output, f, indent=2, ensure_ascii=False, default=str)

print(f"\nResults saved to experiments/k422_commodity_spillover_results.json")
