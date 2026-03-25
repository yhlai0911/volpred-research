"""
K418: Taiwan Institutional Sentiment → Vol Prediction
Based on: Wang et al. (2024) JFM — frequency-decomposed institutional
investor sentiment in Taiwan futures market.

Literature finding: Long-term sentiment component best predicts in bull markets.
Our question: Can we get institutional data from yfinance for Taiwan?

Prior knowledge:
- G8: 台股 4 指標全 null（外資買賣超是落後指標, PUT/CALL ratio artifact）
- K3: 台灣特有指標深度 — SPY magnitude 1.84x
- T5b: SPY→台股 spillover r=0.376

Data check: yfinance provides volume for 0050.TW and ^TWII.
We'll use volume as a proxy for institutional activity.

Output: experiments/k418_institutional_sentiment_results.json
"""
import yfinance as yf
import numpy as np
import pandas as pd
from scipy import stats
import json
from datetime import datetime, timezone

print("=" * 75)
print("K418: Taiwan Volume-Based Institutional Sentiment → Vol")
print("Inspired by Wang et al. (2024) JFM")
print("=" * 75)

# Data
tw50 = yf.download('0050.TW', start='2010-01-01', progress=False)
twii = yf.download('^TWII', start='2010-01-01', progress=False)
spy = yf.download('SPY', start='2010-01-01', progress=False)
vix = yf.download('^VIX', start='2010-01-01', progress=False)['Close'].dropna().squeeze()

tw50_close = tw50['Close'].dropna().squeeze()
tw50_vol = tw50['Volume'].dropna().squeeze()
twii_close = twii['Close'].dropna().squeeze()
twii_vol = twii['Volume'].dropna().squeeze()

# Align
common = tw50_close.index.intersection(twii_close.index).intersection(spy['Close'].dropna().index).intersection(vix.index)
tw50_close = tw50_close.loc[common]
tw50_vol = tw50_vol.reindex(common).fillna(0)
twii_vol = twii_vol.reindex(common).fillna(0)
spy_close = spy['Close'].dropna().squeeze().loc[common]
vix_v = vix.loc[common]

tw50_ret = tw50_close.pct_change().dropna()
tw50_vol = tw50_vol.reindex(tw50_ret.index).fillna(0)
twii_vol = twii_vol.reindex(tw50_ret.index).fillna(0)
spy_ret = spy_close.pct_change().dropna().reindex(tw50_ret.index).fillna(0)
vix_v = vix_v.reindex(tw50_ret.index).fillna(20)

n = len(tw50_ret)
print(f"Data: {n} days ({tw50_ret.index[0].date()} to {tw50_ret.index[-1].date()})")

# === Part 1: Volume-based sentiment proxies ===
print(f"\n{'='*70}")
print("Part 1: Volume-Based Sentiment Proxies")
print(f"{'='*70}")

# 1. Volume ratio (current / 20d MA)
vol_ratio = tw50_vol / tw50_vol.rolling(20).mean()
vol_ratio = vol_ratio.replace([np.inf, -np.inf], np.nan).dropna()

# 2. Volume change (log difference)
vol_chg = np.log(tw50_vol + 1).diff()

# 3. TWII volume ratio
twii_vol_ratio = twii_vol / twii_vol.rolling(20).mean()
twii_vol_ratio = twii_vol_ratio.replace([np.inf, -np.inf], np.nan).dropna()

# 4. Amihud illiquidity (|return|/volume)
amihud = tw50_ret.abs() / (tw50_vol / 1e6 + 0.001)  # scale volume to millions

# Future realized vol
rv_22 = tw50_ret.rolling(22).std().shift(-22) * np.sqrt(252) * 100

# === Part 2: Predictive regressions ===
print(f"\n{'='*70}")
print("Part 2: Predictive Power for Future Vol (partial r controlling VIX)")
print(f"{'='*70}")

predictors = {
    'Vol Ratio (20d)': vol_ratio,
    'Vol Change': vol_chg,
    'TWII Vol Ratio': twii_vol_ratio,
    'Amihud': amihud,
    'SPY Ret (lag)': spy_ret,
}

print(f"{'Predictor':<22} {'Simple r':>10} {'Partial r|VIX':>14} {'t':>7} {'Harvey':>8}")
print("-" * 65)

results_pred = {}
for pname, pred in predictors.items():
    df = pd.DataFrame({
        'pred': pred, 'rv': rv_22, 'vix': vix_v,
    }).dropna()

    if len(df) < 252:
        continue

    n_df = len(df)
    r_simple, p_simple = stats.pearsonr(df['pred'], df['rv'])

    # Partial r controlling VIX
    X = np.column_stack([np.ones(n_df), df['vix'].values])
    res_pred = df['pred'].values - X @ np.linalg.lstsq(X, df['pred'].values, rcond=None)[0]
    res_rv = df['rv'].values - X @ np.linalg.lstsq(X, df['rv'].values, rcond=None)[0]
    r_partial, p_partial = stats.pearsonr(res_pred, res_rv)
    t_partial = r_partial * np.sqrt((n_df-3) / (1-r_partial**2))
    harvey = "★ PASS" if abs(t_partial) > 3 else "FAIL"

    print(f"{pname:<22} {r_simple:>10.3f} {r_partial:>14.3f} {t_partial:>7.2f} {harvey:>8}")

    results_pred[pname] = {
        'n': n_df, 'simple_r': round(float(r_simple), 3),
        'partial_r': round(float(r_partial), 3),
        't': round(float(t_partial), 2),
        'harvey': abs(t_partial) > 3,
    }

# === Part 3: OOS test ===
print(f"\n{'='*70}")
print("Part 3: OOS Test (IS 2010-2019, OOS 2020-2025)")
print(f"{'='*70}")

for pname, pred in predictors.items():
    df = pd.DataFrame({
        'pred': pred, 'rv': rv_22, 'vix': vix_v,
    }).dropna()

    if len(df) < 252:
        continue

    is_mask = df.index < '2020-01-01'
    oos_mask = df.index >= '2020-01-01'

    if oos_mask.sum() < 100:
        continue

    # IS: fit regression rv = a + b*pred + c*vix
    X_is = np.column_stack([np.ones(is_mask.sum()), df.loc[is_mask, 'pred'].values, df.loc[is_mask, 'vix'].values])
    y_is = df.loc[is_mask, 'rv'].values
    coef = np.linalg.lstsq(X_is, y_is, rcond=None)[0]

    # OOS predict
    X_oos = np.column_stack([np.ones(oos_mask.sum()), df.loc[oos_mask, 'pred'].values, df.loc[oos_mask, 'vix'].values])
    y_oos = df.loc[oos_mask, 'rv'].values
    pred_full = X_oos @ coef

    # VIX-only
    X_vix_is = np.column_stack([np.ones(is_mask.sum()), df.loc[is_mask, 'vix'].values])
    coef_vix = np.linalg.lstsq(X_vix_is, y_is, rcond=None)[0]
    X_vix_oos = np.column_stack([np.ones(oos_mask.sum()), df.loc[oos_mask, 'vix'].values])
    pred_vix = X_vix_oos @ coef_vix

    # OOS R²
    ss_full = np.sum((y_oos - pred_full)**2)
    ss_vix = np.sum((y_oos - pred_vix)**2)
    ss_tot = np.sum((y_oos - y_oos.mean())**2)
    incr_r2 = (1 - ss_full/ss_tot) - (1 - ss_vix/ss_tot)

    # DM test
    e_full = (y_oos - pred_full)**2
    e_vix = (y_oos - pred_vix)**2
    d = e_vix - e_full
    dm_t = float(d.mean() / (d.std() / np.sqrt(len(d)))) if d.std() > 0 else 0
    sig = "★" if dm_t > 3 else ""

    print(f"  {pname:<22}: OOS ΔR²={incr_r2:>7.4f}, DM t={dm_t:>5.2f}{sig}")

# Save
output = {
    'experiment': 'K418',
    'title': 'Taiwan Volume-Based Institutional Sentiment',
    'reference': 'Wang et al. (2024) JFM',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data': {
        'source': 'yfinance',
        'tickers': ['0050.TW', '^TWII', 'SPY', '^VIX'],
        'period': f"{tw50_ret.index[0].date()} to {tw50_ret.index[-1].date()}",
        'n_obs': n,
    },
    'predictors': results_pred,
}

with open('experiments/k418_institutional_sentiment_results.json', 'w') as f:
    json.dump(output, f, indent=2, ensure_ascii=False, default=str)

print(f"\nResults saved to experiments/k418_institutional_sentiment_results.json")
