"""
I8: Futures Basis as Volatility Predictor — Multi-Market
Extending K340 (ES basis null) to GC, ZN, and cross-market.

Result: MOSTLY NULL. SPY-ES r=-0.045 FAIL, GLD-GC null,
TLT-ZN IS t=5.11 PASS but OOS collapses (ΔR²=-0.074).
Sixth Law (K407) confirmed.

Data: SPY/ES=F/GLD/GC=F/TLT/ZN=F/^VIX from yfinance, 2010-2025
Output: experiments/i8/i8_futures_basis_results.json
"""
from pathlib import Path

import yfinance as yf
import numpy as np
import pandas as pd
from scipy import stats
import json
from datetime import datetime, timezone

EXPERIMENT_DIR = Path(__file__).resolve().parent
RESULTS_FILE = EXPERIMENT_DIR / 'i8_futures_basis_results.json'

tickers = {
    'SPY': 'SPY', 'ES': 'ES=F',
    'GLD': 'GLD', 'GC': 'GC=F',
    'TLT': 'TLT', 'ZN': 'ZN=F',
}
data = {}
for name, ticker in tickers.items():
    d = yf.download(ticker, start='2010-01-01', progress=False)['Close'].dropna().squeeze()
    data[name] = d
vix = yf.download('^VIX', start='2010-01-01', progress=False)['Close'].dropna().squeeze()

common = data['SPY'].index
for k in data:
    common = common.intersection(data[k].index)
common = common.intersection(vix.index)
for k in data:
    data[k] = data[k].loc[common]
vix = vix.loc[common]

pairs = [('SPY', 'ES', 'Equity'), ('GLD', 'GC', 'Gold'), ('TLT', 'ZN', 'Bond')]
pair_results = []

for spot_name, fut_name, asset_class in pairs:
    spot = data[spot_name]
    fut = data[fut_name]
    basis = ((fut - spot) / spot * 100)
    spot_ret = spot.pct_change().dropna()
    future_rv = spot_ret.rolling(22).std().shift(-22) * np.sqrt(252) * 100

    df = pd.DataFrame({
        'basis': basis, 'abs_basis': basis.abs(),
        'future_rv': future_rv, 'vix': vix,
    }).dropna()

    if len(df) < 252:
        continue

    n = len(df)
    r_simple, p_simple = stats.pearsonr(df['abs_basis'], df['future_rv'])

    X_vix = np.column_stack([np.ones(n), df['vix'].values])
    res_basis = df['abs_basis'].values - X_vix @ np.linalg.lstsq(X_vix, df['abs_basis'].values, rcond=None)[0]
    res_futvol = df['future_rv'].values - X_vix @ np.linalg.lstsq(X_vix, df['future_rv'].values, rcond=None)[0]
    r_partial, p_partial = stats.pearsonr(res_basis, res_futvol)
    t_partial = r_partial * np.sqrt((n-3) / (1 - r_partial**2))

    is_mask = df.index < '2020-01-01'
    oos_mask = df.index >= '2020-01-01'

    if oos_mask.sum() > 100:
        X_is = np.column_stack([np.ones(is_mask.sum()), df.loc[is_mask, 'abs_basis'].values, df.loc[is_mask, 'vix'].values])
        y_is = df.loc[is_mask, 'future_rv'].values
        coef = np.linalg.lstsq(X_is, y_is, rcond=None)[0]

        X_oos = np.column_stack([np.ones(oos_mask.sum()), df.loc[oos_mask, 'abs_basis'].values, df.loc[oos_mask, 'vix'].values])
        y_oos = df.loc[oos_mask, 'future_rv'].values
        pred_full = X_oos @ coef

        X_vix_is = np.column_stack([np.ones(is_mask.sum()), df.loc[is_mask, 'vix'].values])
        coef_vix = np.linalg.lstsq(X_vix_is, y_is, rcond=None)[0]
        X_vix_oos = np.column_stack([np.ones(oos_mask.sum()), df.loc[oos_mask, 'vix'].values])
        pred_vix = X_vix_oos @ coef_vix

        ss_res_full = np.sum((y_oos - pred_full)**2)
        ss_res_vix = np.sum((y_oos - pred_vix)**2)
        ss_tot = np.sum((y_oos - y_oos.mean())**2)
        incr_r2 = (1 - ss_res_full/ss_tot) - (1 - ss_res_vix/ss_tot)
    else:
        incr_r2 = float('nan')

    pair_results.append({
        'asset_class': asset_class,
        'pair': f"{spot_name}-{fut_name}",
        'n': n,
        'r_simple': round(float(r_simple), 3),
        'r_partial': round(float(r_partial), 3),
        't_partial': round(float(t_partial), 2),
        'harvey_pass': abs(t_partial) > 3.0,
        'oos_incr_r2': round(float(incr_r2), 4) if not np.isnan(incr_r2) else None,
    })

results = {
    'experiment': 'I8',
    'title': 'Futures Basis Multi-Market Vol Prediction',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data': {
        'source': 'yfinance',
        'tickers': list(tickers.values()) + ['^VIX'],
        'period': f"{common[0].date()} to {common[-1].date()}",
        'n_obs': len(common),
    },
    'pair_results': pair_results,
    'conclusion': 'MOSTLY NULL. TLT-ZN IS passes Harvey but OOS collapses. Sixth Law confirmed.',
}

with open(RESULTS_FILE, 'w') as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)

print(f"Results saved to {RESULTS_FILE}")
for r in pair_results:
    h = "★ PASS" if r['harvey_pass'] else "FAIL"
    print(f"  {r['pair']}: partial r={r['r_partial']}, t={r['t_partial']}, Harvey {h}, OOS ΔR²={r['oos_incr_r2']}")
