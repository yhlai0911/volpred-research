"""
K421: VIX ETP Market Impact on SPY
Based on: Bangsgaard & Kokholm (2025) JBF — VIX ETP rebalancing
predicts SPX futures close-to-close returns.

Literature finding: VIX ETP demand significantly predicts SPX returns
(portfolio rebalancing, not fundamental info). Price reversal follows.

Prior knowledge check:
- K38: 0DTE hasn't broken VT. VIX-SPY corr unchanged
- K168: GARCH Vol-of-Vol — high VoV paradoxically conservative
- K278: VIX regime transitions — escalation 3-4x faster than de-escalation

Research Question: Can we detect VIX ETP rebalancing effects using
UVXY/SVXY volume data from yfinance?

Step 1: Data diagnostics
Step 2: Test ETP volume → SPY next-day return/vol
Step 3: End-of-day effect detection

Data: SPY, UVXY, SVXY (if available), ^VIX from yfinance
Output: experiments/k421_vix_etp_results.json
"""
import yfinance as yf
import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.diagnostic import het_arch
from statsmodels.tsa.stattools import adfuller
import json, warnings
from datetime import datetime, timezone

warnings.filterwarnings('ignore')

print("=" * 75)
print("K421: VIX ETP Market Impact")
print("Based on Bangsgaard & Kokholm (2025) JBF")
print("=" * 75)

# Data
spy = yf.download('SPY', start='2018-01-01', progress=False)
uvxy = yf.download('UVXY', start='2018-01-01', progress=False)
svxy = yf.download('SVXY', start='2018-01-01', progress=False)
vix = yf.download('^VIX', start='2018-01-01', progress=False)['Close'].dropna().squeeze()

spy_close = spy['Close'].dropna().squeeze()
spy_vol = spy['Volume'].dropna().squeeze()
uvxy_close = uvxy['Close'].dropna().squeeze()
uvxy_vol = uvxy['Volume'].dropna().squeeze()

# SVXY may have data issues (Volmageddon 2018)
svxy_ok = len(svxy) > 500
if svxy_ok:
    svxy_close = svxy['Close'].dropna().squeeze()
    svxy_vol = svxy['Volume'].dropna().squeeze()

# Align
common = spy_close.index.intersection(uvxy_close.index).intersection(vix.index)
spy_close = spy_close.loc[common]
spy_vol = spy_vol.reindex(common).fillna(0)
uvxy_close = uvxy_close.loc[common]
uvxy_vol = uvxy_vol.reindex(common).fillna(0)
vix_v = vix.loc[common]

spy_ret = spy_close.pct_change().dropna()
uvxy_ret = uvxy_close.pct_change().dropna().reindex(spy_ret.index).fillna(0)
uvxy_vol = uvxy_vol.reindex(spy_ret.index).fillna(0)
spy_vol = spy_vol.reindex(spy_ret.index).fillna(0)
vix_v = vix_v.reindex(spy_ret.index).fillna(20)

n = len(spy_ret)
print(f"Data: {n} days ({spy_ret.index[0].date()} to {spy_ret.index[-1].date()})")

# --- Step 1: Diagnostics ---
print(f"\n--- Diagnostics ---")
print(f"SPY ret: mean={spy_ret.mean()*252*100:.1f}%/yr, vol={spy_ret.std()*np.sqrt(252)*100:.1f}%, skew={spy_ret.skew():.2f}")
print(f"UVXY ret: mean={uvxy_ret.mean()*252*100:.1f}%/yr, vol={uvxy_ret.std()*np.sqrt(252)*100:.1f}%")
print(f"SPY-UVXY corr: {spy_ret.corr(uvxy_ret):.3f}")
print(f"UVXY daily vol (shares): mean={uvxy_vol.mean()/1e6:.1f}M, std={uvxy_vol.std()/1e6:.1f}M")

# --- Step 2: ETP Volume Signals ---
print(f"\n{'='*70}")
print("Step 2: VIX ETP Volume → SPY Next-Day Prediction")
print(f"{'='*70}")

# Create predictors
# 1. UVXY volume ratio (abnormal volume)
uvxy_vol_ratio = uvxy_vol / uvxy_vol.rolling(20).mean()
uvxy_vol_ratio = uvxy_vol_ratio.replace([np.inf, -np.inf], np.nan)

# 2. UVXY/SPY volume ratio (relative fear demand)
vol_ratio = uvxy_vol / (spy_vol + 1)
vol_ratio_norm = vol_ratio / vol_ratio.rolling(20).mean()
vol_ratio_norm = vol_ratio_norm.replace([np.inf, -np.inf], np.nan)

# 3. UVXY return magnitude (proxy for rebalancing pressure)
uvxy_abs_ret = uvxy_ret.abs()

# 4. VIX-UVXY tracking error (rebalancing friction)
# UVXY targets 1.5x VIX daily (since 2022, was 2x before)
vix_ret = vix_v.pct_change().dropna().reindex(spy_ret.index).fillna(0)
tracking_error = uvxy_ret - 1.5 * vix_ret  # crude approximation

# Next-day SPY targets
spy_next_ret = spy_ret.shift(-1)
spy_next_abs = spy_ret.shift(-1).abs()
rv_22_future = spy_ret.rolling(22).std().shift(-22) * np.sqrt(252) * 100

predictors = {
    'UVXY Vol Ratio': uvxy_vol_ratio,
    'UVXY/SPY Vol Ratio': vol_ratio_norm,
    'UVXY |Return|': uvxy_abs_ret,
    'Tracking Error': tracking_error.abs(),
}

# Test each predictor
print(f"\n{'Predictor':<22} {'→ Next Ret':>12} {'→ Next |Ret|':>14} {'→ 22d RV':>10} {'Partial r|VIX':>14}")
print("-" * 75)

results_pred = {}
for pname, pred in predictors.items():
    df = pd.DataFrame({
        'pred': pred, 'next_ret': spy_next_ret,
        'next_abs': spy_next_abs, 'rv22': rv_22_future,
        'vix': vix_v,
    }).dropna()

    if len(df) < 100:
        continue

    # Simple correlations
    r_ret, _ = stats.pearsonr(df['pred'], df['next_ret'])
    r_abs, _ = stats.pearsonr(df['pred'], df['next_abs'])

    # Partial r|VIX for vol prediction
    n_df = len(df)
    X = np.column_stack([np.ones(n_df), df['vix'].values])
    res_p = df['pred'].values - X @ np.linalg.lstsq(X, df['pred'].values, rcond=None)[0]
    res_rv = df['rv22'].values - X @ np.linalg.lstsq(X, df['rv22'].values, rcond=None)[0]
    r_partial, p_partial = stats.pearsonr(res_p, res_rv)
    t_partial = r_partial * np.sqrt((n_df-3) / (1-r_partial**2))
    harvey = "★" if abs(t_partial) > 3 else ""

    print(f"{pname:<22} {r_ret:>12.3f} {r_abs:>14.3f} {r_partial:>9.3f}{harvey} (t={t_partial:.1f})")

    results_pred[pname] = {
        'r_next_ret': round(float(r_ret), 3),
        'r_next_abs': round(float(r_abs), 3),
        'partial_r_rv22': round(float(r_partial), 3),
        't_partial': round(float(t_partial), 2),
    }

# --- Step 3: Reversal Effect ---
print(f"\n{'='*70}")
print("Step 3: UVXY Volume Spike → SPY Reversal?")
print(f"{'='*70}")

# High UVXY volume days (top 10%)
high_vol_threshold = uvxy_vol_ratio.quantile(0.90)
high_vol_days = uvxy_vol_ratio > high_vol_threshold
n_high = int(high_vol_days.sum())
print(f"High UVXY volume days (top 10%): {n_high}")

if n_high > 20:
    # SPY return on high UVXY volume days
    spy_on_high = spy_ret[high_vol_days.reindex(spy_ret.index).fillna(False)]
    spy_on_normal = spy_ret[~high_vol_days.reindex(spy_ret.index).fillna(True)]

    # Next-day reversal
    next_ret_high = spy_next_ret[high_vol_days.reindex(spy_next_ret.index).fillna(False)]
    next_ret_normal = spy_next_ret[~high_vol_days.reindex(spy_next_ret.index).fillna(True)]

    print(f"  Same-day SPY return: High vol={spy_on_high.mean()*100:.2f}%, Normal={spy_on_normal.mean()*100:.2f}%")
    print(f"  Next-day SPY return: High vol={next_ret_high.mean()*100:.2f}%, Normal={next_ret_normal.mean()*100:.2f}%")

    t_reversal, p_reversal = stats.ttest_ind(next_ret_high.dropna(), next_ret_normal.dropna())
    print(f"  Reversal t-test: t={t_reversal:.2f}, p={p_reversal:.4f}")

    # 5-day cumulative reversal
    spy_5d_ret = spy_ret.rolling(5).sum().shift(-5)
    next_5d_high = spy_5d_ret[high_vol_days.reindex(spy_5d_ret.index).fillna(False)]
    next_5d_normal = spy_5d_ret[~high_vol_days.reindex(spy_5d_ret.index).fillna(True)]

    if len(next_5d_high.dropna()) > 10:
        print(f"  5-day cum return: High vol={next_5d_high.mean()*100:.2f}%, Normal={next_5d_normal.mean()*100:.2f}%")

# Save
output = {
    'experiment': 'K421',
    'title': 'VIX ETP Market Impact',
    'reference': 'Bangsgaard & Kokholm (2025) JBF',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data': {'source': 'yfinance', 'tickers': ['SPY', 'UVXY', '^VIX'], 'n': n},
    'predictors': results_pred,
}

with open('experiments/k421_vix_etp_results.json', 'w') as f:
    json.dump(output, f, indent=2, ensure_ascii=False, default=str)

print(f"\nResults saved to experiments/k421_vix_etp_results.json")
