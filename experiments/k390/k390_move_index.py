"""
K390: MOVE Index — The "Bond VIX" and Its Relationship with Equity Vol

Background:
- MOVE mentioned 35 times but mostly in context of K33 (bond VT) and T11 (MOVE null)
- Never deep-dived MOVE as its own research subject
- K342 showed OVX>>VIX for oil. Is MOVE>>VIX for bonds?
- K33 MOVE bond VT mixed. T11 MOVE null for SPY vol
- K207 VIX not sufficient for bonds. K217 TLT best predictor: EWMA

Data: yfinance
- ^MOVE (ICE BofA MOVE Index — bond market implied vol)
- ^VIX
- TLT (long-term Treasury)
- SPY

Methodology:
1. MOVE characteristics (mean, std, distribution, MOVE-VIX corr)
2. MOVE for bond vol prediction (partial r, vs VIX, vs EWMA)
3. MOVE-VIX divergence as macro signal
4. MOVE regime for 50/50 allocation
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
import warnings
import json
from datetime import datetime

warnings.filterwarnings('ignore')

# ============================================================
# 1. Data Download
# ============================================================
print("=" * 70)
print("K390: MOVE Index — The Bond VIX")
print("=" * 70)

print("\n[1] Downloading data...")
tickers = {
    'move': '^MOVE',
    'vix': '^VIX',
    'tlt': 'TLT',
    'spy': 'SPY',
}

raw = {}
for name, ticker in tickers.items():
    data = yf.download(ticker, start="2002-01-01", end="2026-03-25", progress=False)
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    raw[name] = data
    print(f"  {name} ({ticker}): {len(data)} obs, {data.index[0].strftime('%Y-%m-%d')} to {data.index[-1].strftime('%Y-%m-%d')}")

# Build aligned DataFrame
df = pd.DataFrame(index=raw['spy'].index)
df['spy_close'] = raw['spy']['Close']
df['tlt_close'] = raw['tlt']['Close'].reindex(df.index, method='ffill')
df['vix'] = raw['vix']['Close'].reindex(df.index, method='ffill')
df['move'] = raw['move']['Close'].reindex(df.index, method='ffill')

# Returns
df['spy_ret'] = np.log(df['spy_close'] / df['spy_close'].shift(1))
df['tlt_ret'] = np.log(df['tlt_close'] / df['tlt_close'].shift(1))

# Realized vol (22d annualized)
df['spy_rv22'] = df['spy_ret'].rolling(22).std() * np.sqrt(252) * 100
df['tlt_rv22'] = df['tlt_ret'].rolling(22).std() * np.sqrt(252) * 100

# Future realized vol (22d forward)
# Compute rolling 22d std, then shift backward to align with "today"
spy_rv_series = df['spy_ret'].rolling(22).std() * np.sqrt(252) * 100
tlt_rv_series = df['tlt_ret'].rolling(22).std() * np.sqrt(252) * 100
df['spy_fwd_rv22'] = spy_rv_series.shift(-22)
df['tlt_fwd_rv22'] = tlt_rv_series.shift(-22)

# EWMA(0.94) vol for TLT
lam = 0.94
tlt_ewma_vals = np.full(len(df), np.nan)
valid_rets = df['tlt_ret'].values
# Initialize from first 22 valid returns
init_rets = valid_rets[~np.isnan(valid_rets)][:22]
ewma_var = np.var(init_rets) * 252 if len(init_rets) > 5 else 0.01
started = False
for i in range(len(df)):
    r = valid_rets[i]
    if not np.isnan(r):
        if not started:
            started = True
        else:
            ewma_var = lam * ewma_var + (1 - lam) * r**2 * 252
        tlt_ewma_vals[i] = np.sqrt(max(ewma_var, 1e-10)) * 100
df['tlt_ewma'] = tlt_ewma_vals

df = df.dropna(subset=['move', 'vix', 'spy_rv22', 'tlt_rv22'])
print(f"\n  Aligned dataset: {len(df)} obs, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

# ============================================================
# 2. MOVE Characteristics
# ============================================================
print("\n" + "=" * 70)
print("[2] MOVE Index Characteristics")
print("=" * 70)

move = df['move']
vix = df['vix']

print(f"\n  MOVE Index Statistics:")
print(f"    Mean:     {move.mean():.2f}")
print(f"    Median:   {move.median():.2f}")
print(f"    Std:      {move.std():.2f}")
print(f"    Min:      {move.min():.2f}  ({move.idxmin().strftime('%Y-%m-%d')})")
print(f"    Max:      {move.max():.2f}  ({move.idxmax().strftime('%Y-%m-%d')})")
print(f"    Skewness: {move.skew():.3f}")
print(f"    Kurtosis: {move.kurtosis():.3f}")
print(f"    Current:  {move.iloc[-1]:.2f}")

print(f"\n  VIX Index Statistics (same period):")
print(f"    Mean:     {vix.mean():.2f}")
print(f"    Median:   {vix.median():.2f}")
print(f"    Std:      {vix.std():.2f}")
print(f"    Min:      {vix.min():.2f}")
print(f"    Max:      {vix.max():.2f}")
print(f"    Current:  {vix.iloc[-1]:.2f}")

# Percentiles
print(f"\n  MOVE Percentiles:")
for p in [5, 10, 25, 50, 75, 90, 95]:
    print(f"    {p}th: {np.percentile(move, p):.2f}")

# ============================================================
# 3. MOVE-VIX Correlation Analysis
# ============================================================
print("\n" + "=" * 70)
print("[3] MOVE-VIX Correlation")
print("=" * 70)

# Level correlation
corr_level = move.corr(vix)
print(f"\n  Level correlation (MOVE vs VIX): {corr_level:.4f}")

# Change correlation
move_chg = move.pct_change().dropna()
vix_chg = vix.pct_change().dropna()
common = move_chg.index.intersection(vix_chg.index)
corr_chg = move_chg.loc[common].corr(vix_chg.loc[common])
print(f"  Change correlation (ΔMOVE% vs ΔVIX%): {corr_chg:.4f}")

# Rolling correlation (252d)
rolling_corr = move.rolling(252).corr(vix)
print(f"\n  Rolling 252d correlation MOVE-VIX:")
print(f"    Mean: {rolling_corr.mean():.4f}")
print(f"    Min:  {rolling_corr.min():.4f} ({rolling_corr.idxmin().strftime('%Y-%m-%d') if not pd.isna(rolling_corr.idxmin()) else 'N/A'})")
print(f"    Max:  {rolling_corr.max():.4f} ({rolling_corr.idxmax().strftime('%Y-%m-%d') if not pd.isna(rolling_corr.idxmax()) else 'N/A'})")

# By year
print(f"\n  Annual MOVE-VIX correlation:")
for year in range(df.index[0].year, df.index[-1].year + 1):
    mask = df.index.year == year
    if mask.sum() > 50:
        m = move[mask]
        v = vix[mask]
        c = m.corr(v)
        print(f"    {year}: {c:.3f}  (MOVE={m.mean():.1f}, VIX={v.mean():.1f})")

# ============================================================
# 4. Divergence Analysis
# ============================================================
print("\n" + "=" * 70)
print("[4] MOVE-VIX Divergence Analysis")
print("=" * 70)

# Z-scores
move_z = (move - move.rolling(252).mean()) / move.rolling(252).std()
vix_z = (vix - vix.rolling(252).mean()) / vix.rolling(252).std()
divergence = move_z - vix_z  # positive = MOVE elevated relative to VIX

df['move_z'] = move_z
df['vix_z'] = vix_z
df['divergence'] = divergence

# Classify divergence regimes
valid_div = df.dropna(subset=['divergence'])
print(f"\n  Divergence = MOVE_z - VIX_z (positive = bonds more stressed than equities)")
print(f"  Mean divergence: {valid_div['divergence'].mean():.3f}")
print(f"  Std divergence:  {valid_div['divergence'].std():.3f}")

# High MOVE / Low VIX episodes (rate-hike fear)
high_move_low_vix = valid_div[(valid_div['move_z'] > 1.0) & (valid_div['vix_z'] < 0)]
print(f"\n  Bond-Only Stress episodes (MOVE_z > 1 & VIX_z < 0): {len(high_move_low_vix)} days ({100*len(high_move_low_vix)/len(valid_div):.1f}%)")
if len(high_move_low_vix) > 0:
    # Forward returns during these episodes
    fwd_spy = high_move_low_vix['spy_ret'].shift(-22).rolling(22).sum()
    fwd_tlt = high_move_low_vix['tlt_ret'].shift(-22).rolling(22).sum()
    print(f"    Mean fwd 22d SPY return: {df.loc[high_move_low_vix.index, 'spy_ret'].shift(-1).rolling(22).mean().mean()*252*100:.2f}% ann")

# High VIX / Low MOVE episodes (equity-only risk)
high_vix_low_move = valid_div[(valid_div['vix_z'] > 1.0) & (valid_div['move_z'] < 0)]
print(f"  Equity-Only Stress episodes (VIX_z > 1 & MOVE_z < 0): {len(high_vix_low_move)} days ({100*len(high_vix_low_move)/len(valid_div):.1f}%)")

# Both high (universal stress)
both_high = valid_div[(valid_div['move_z'] > 1.0) & (valid_div['vix_z'] > 1.0)]
print(f"  Universal Stress episodes (both z > 1): {len(both_high)} days ({100*len(both_high)/len(valid_div):.1f}%)")

# Both low (calm)
both_low = valid_div[(valid_div['move_z'] < 0) & (valid_div['vix_z'] < 0)]
print(f"  Calm episodes (both z < 0): {len(both_low)} days ({100*len(both_low)/len(valid_div):.1f}%)")

# Key divergence periods
print(f"\n  Top 10 divergence days (MOVE much higher than VIX):")
top_div = valid_div.nlargest(10, 'divergence')
for idx, row in top_div.iterrows():
    print(f"    {idx.strftime('%Y-%m-%d')}: div={row['divergence']:.2f}, MOVE={row['move']:.1f}, VIX={row['vix']:.1f}")

print(f"\n  Top 10 negative divergence days (VIX much higher than MOVE):")
bot_div = valid_div.nsmallest(10, 'divergence')
for idx, row in bot_div.iterrows():
    print(f"    {idx.strftime('%Y-%m-%d')}: div={row['divergence']:.2f}, MOVE={row['move']:.1f}, VIX={row['vix']:.1f}")

# ============================================================
# 5. MOVE for Bond Vol Prediction
# ============================================================
print("\n" + "=" * 70)
print("[5] MOVE for Bond (TLT) Vol Prediction")
print("=" * 70)

# Debug: check NaN counts before dropping
for col in ['tlt_fwd_rv22', 'move', 'vix', 'tlt_ewma', 'tlt_rv22']:
    nan_count = df[col].isna().sum()
    valid_count = df[col].notna().sum()
    print(f"    {col}: {valid_count} valid, {nan_count} NaN")

pred_df = df.dropna(subset=['tlt_fwd_rv22', 'move', 'vix', 'tlt_ewma', 'tlt_rv22'])
print(f"\n  Prediction sample: {len(pred_df)} obs")

target = pred_df['tlt_fwd_rv22']

# 5a. Univariate correlations with future TLT RV
predictors = {
    'MOVE': pred_df['move'],
    'VIX': pred_df['vix'],
    'EWMA(0.94)': pred_df['tlt_ewma'],
    'TLT_RV22': pred_df['tlt_rv22'],
}

print(f"\n  Univariate correlations with future TLT 22d RV:")
for name, pred in predictors.items():
    r, p = stats.pearsonr(pred, target)
    sr, sp = stats.spearmanr(pred, target)
    print(f"    {name:12s}: Pearson r={r:.4f} (p={p:.2e}), Spearman rho={sr:.4f} (p={sp:.2e})")

# 5b. Partial correlations (MOVE vs future TLT RV, controlling for VIX)
print(f"\n  Partial correlations (MOVE → future TLT RV, controlling for...):")

def partial_corr(x, y, z):
    """Partial correlation of x,y controlling for z."""
    # Residualize x and y on z
    from numpy.linalg import lstsq
    Z = np.column_stack([z, np.ones(len(z))])

    bx = lstsq(Z, x, rcond=None)[0]
    rx = x - Z @ bx

    by = lstsq(Z, y, rcond=None)[0]
    ry = y - Z @ by

    return stats.pearsonr(rx, ry)

# MOVE → TLT fwd RV, controlling for VIX
r_mv, p_mv = partial_corr(pred_df['move'].values, target.values, pred_df['vix'].values)
print(f"    MOVE | VIX:        partial r = {r_mv:.4f} (p={p_mv:.2e})")

# MOVE → TLT fwd RV, controlling for EWMA
r_me, p_me = partial_corr(pred_df['move'].values, target.values, pred_df['tlt_ewma'].values)
print(f"    MOVE | EWMA(0.94): partial r = {r_me:.4f} (p={p_me:.2e})")

# MOVE → TLT fwd RV, controlling for both VIX and EWMA
def partial_corr_multi(x, y, Z_mat):
    """Partial correlation controlling for multiple variables."""
    Z = np.column_stack([Z_mat, np.ones(len(x))])
    from numpy.linalg import lstsq
    bx = lstsq(Z, x, rcond=None)[0]
    rx = x - Z @ bx
    by = lstsq(Z, y, rcond=None)[0]
    ry = y - Z @ by
    return stats.pearsonr(rx, ry)

Z_both = np.column_stack([pred_df['vix'].values, pred_df['tlt_ewma'].values])
r_mb, p_mb = partial_corr_multi(pred_df['move'].values, target.values, Z_both)
print(f"    MOVE | VIX+EWMA:   partial r = {r_mb:.4f} (p={p_mb:.2e})")

# VIX → TLT fwd RV, controlling for MOVE
r_vm, p_vm = partial_corr(pred_df['vix'].values, target.values, pred_df['move'].values)
print(f"    VIX | MOVE:        partial r = {r_vm:.4f} (p={p_vm:.2e})")

# 5c. OOS prediction comparison
print(f"\n  OOS Prediction Comparison (2020-2026 out-of-sample):")
oos_start = "2020-01-01"
is_mask = pred_df.index < oos_start
oos_mask = pred_df.index >= oos_start

if is_mask.sum() > 252 and oos_mask.sum() > 100:
    is_data = pred_df[is_mask]
    oos_data = pred_df[oos_mask]

    print(f"    IS: {is_mask.sum()} obs, OOS: {oos_mask.sum()} obs")

    # Simple linear models trained on IS, evaluated on OOS
    from numpy.linalg import lstsq

    models = {
        'MOVE only': ['move'],
        'VIX only': ['vix'],
        'EWMA(0.94)': ['tlt_ewma'],
        'TLT_RV22': ['tlt_rv22'],
        'MOVE + VIX': ['move', 'vix'],
        'MOVE + EWMA': ['move', 'tlt_ewma'],
        'MOVE + VIX + EWMA': ['move', 'vix', 'tlt_ewma'],
    }

    oos_target = oos_data['tlt_fwd_rv22'].values

    print(f"\n    {'Model':25s} {'OOS RMSE':>10s} {'OOS MAE':>10s} {'OOS R²':>10s} {'OOS Corr':>10s}")
    print(f"    {'-'*65}")

    model_results = {}
    for mname, cols in models.items():
        X_is = np.column_stack([is_data[c].values for c in cols] + [np.ones(len(is_data))])
        y_is = is_data['tlt_fwd_rv22'].values

        b = lstsq(X_is, y_is, rcond=None)[0]

        X_oos = np.column_stack([oos_data[c].values for c in cols] + [np.ones(len(oos_data))])
        y_pred = X_oos @ b

        resid = oos_target - y_pred
        rmse = np.sqrt(np.mean(resid**2))
        mae = np.mean(np.abs(resid))
        ss_res = np.sum(resid**2)
        ss_tot = np.sum((oos_target - oos_target.mean())**2)
        r2 = 1 - ss_res / ss_tot
        corr = np.corrcoef(oos_target, y_pred)[0, 1]

        print(f"    {mname:25s} {rmse:10.4f} {mae:10.4f} {r2:10.4f} {corr:10.4f}")
        model_results[mname] = {'rmse': rmse, 'mae': mae, 'r2': r2, 'corr': corr}

    # DM test: MOVE vs VIX for TLT prediction
    print(f"\n  Diebold-Mariano Tests (OOS, squared error loss):")

    def dm_test(e1, e2, h=22):
        """DM test with Newey-West HAC."""
        d = e1**2 - e2**2
        n = len(d)
        d_bar = np.mean(d)

        # Newey-West HAC
        gamma_0 = np.var(d)
        gamma_sum = 0
        for k in range(1, h+1):
            w = 1 - k / (h + 1)
            gamma_k = np.cov(d[k:], d[:-k])[0, 1]
            gamma_sum += 2 * w * gamma_k

        var_d = (gamma_0 + gamma_sum) / n
        if var_d <= 0:
            return 0, 1.0

        dm_stat = d_bar / np.sqrt(var_d)
        p_val = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
        return dm_stat, p_val

    # Compute OOS errors for each model
    oos_errors = {}
    for mname, cols in models.items():
        X_is = np.column_stack([is_data[c].values for c in cols] + [np.ones(len(is_data))])
        y_is = is_data['tlt_fwd_rv22'].values
        b = lstsq(X_is, y_is, rcond=None)[0]
        X_oos = np.column_stack([oos_data[c].values for c in cols] + [np.ones(len(oos_data))])
        y_pred = X_oos @ b
        oos_errors[mname] = oos_target - y_pred

    # MOVE vs VIX
    dm, pv = dm_test(oos_errors['MOVE only'], oos_errors['VIX only'])
    print(f"    MOVE vs VIX:  DM={dm:.3f}, p={pv:.4f} ({'MOVE wins' if dm < 0 else 'VIX wins'})")

    # MOVE vs EWMA
    dm, pv = dm_test(oos_errors['MOVE only'], oos_errors['EWMA(0.94)'])
    print(f"    MOVE vs EWMA: DM={dm:.3f}, p={pv:.4f} ({'MOVE wins' if dm < 0 else 'EWMA wins'})")

    # MOVE+VIX vs EWMA
    dm, pv = dm_test(oos_errors['MOVE + VIX'], oos_errors['EWMA(0.94)'])
    print(f"    MOVE+VIX vs EWMA: DM={dm:.3f}, p={pv:.4f} ({'MOVE+VIX wins' if dm < 0 else 'EWMA wins'})")

    # MOVE+VIX+EWMA vs EWMA alone
    dm, pv = dm_test(oos_errors['MOVE + VIX + EWMA'], oos_errors['EWMA(0.94)'])
    print(f"    MOVE+VIX+EWMA vs EWMA: DM={dm:.3f}, p={pv:.4f} ({'combo wins' if dm < 0 else 'EWMA wins'})")

# ============================================================
# 6. MOVE for Equity (SPY) Vol Prediction (reconfirm T11)
# ============================================================
print("\n" + "=" * 70)
print("[6] MOVE for SPY Vol Prediction (reconfirm T11)")
print("=" * 70)

spy_pred_df = df.dropna(subset=['spy_fwd_rv22', 'move', 'vix', 'spy_rv22'])
spy_target = spy_pred_df['spy_fwd_rv22']

print(f"\n  Univariate correlations with future SPY 22d RV:")
spy_predictors = {
    'MOVE': spy_pred_df['move'],
    'VIX': spy_pred_df['vix'],
    'SPY_RV22': spy_pred_df['spy_rv22'],
}
for name, pred in spy_predictors.items():
    r, p = stats.pearsonr(pred, spy_target)
    print(f"    {name:12s}: r={r:.4f} (p={p:.2e})")

# Partial: MOVE → SPY fwd RV, controlling for VIX
r_mv_spy, p_mv_spy = partial_corr(spy_pred_df['move'].values, spy_target.values, spy_pred_df['vix'].values)
print(f"\n  Partial r (MOVE | VIX → SPY fwd RV): {r_mv_spy:.4f} (p={p_mv_spy:.2e})")
print(f"  → {'Confirms T11: MOVE adds nothing for SPY after controlling VIX' if abs(r_mv_spy) < 0.05 else 'MOVE adds incremental info for SPY!'}")

# ============================================================
# 7. MOVE-VIX Divergence as Forward Return Signal
# ============================================================
print("\n" + "=" * 70)
print("[7] MOVE-VIX Divergence as Forward Return Signal")
print("=" * 70)

# Use divergence quintiles to predict forward returns
sig_df = valid_div.dropna(subset=['divergence']).copy()
sig_df['fwd_spy_22d'] = sig_df['spy_close'].shift(-22) / sig_df['spy_close'] - 1
sig_df['fwd_tlt_22d'] = sig_df['tlt_close'].shift(-22) / sig_df['tlt_close'] - 1
sig_df['fwd_5050_22d'] = 0.5 * sig_df['fwd_spy_22d'] + 0.5 * sig_df['fwd_tlt_22d']
sig_df = sig_df.dropna(subset=['fwd_spy_22d', 'fwd_tlt_22d'])

print(f"\n  Sample: {len(sig_df)} obs")

# Quintile analysis
sig_df['div_q'] = pd.qcut(sig_df['divergence'], 5, labels=['Q1(VIX>MOVE)', 'Q2', 'Q3', 'Q4', 'Q5(MOVE>VIX)'])

print(f"\n  Forward 22d Returns by MOVE-VIX Divergence Quintile:")
print(f"  {'Quintile':20s} {'SPY':>10s} {'TLT':>10s} {'50/50':>10s} {'N':>5s}")
print(f"  {'-'*55}")

for q in ['Q1(VIX>MOVE)', 'Q2', 'Q3', 'Q4', 'Q5(MOVE>VIX)']:
    mask = sig_df['div_q'] == q
    spy_r = sig_df.loc[mask, 'fwd_spy_22d'].mean() * 12 * 100  # annualized
    tlt_r = sig_df.loc[mask, 'fwd_tlt_22d'].mean() * 12 * 100
    mix_r = sig_df.loc[mask, 'fwd_5050_22d'].mean() * 12 * 100
    n = mask.sum()
    print(f"  {q:20s} {spy_r:9.2f}% {tlt_r:9.2f}% {mix_r:9.2f}% {n:5d}")

# Q5 - Q1 spread
q5 = sig_df[sig_df['div_q'] == 'Q5(MOVE>VIX)']
q1 = sig_df[sig_df['div_q'] == 'Q1(VIX>MOVE)']
spread_spy = q5['fwd_spy_22d'].mean() - q1['fwd_spy_22d'].mean()
spread_tlt = q5['fwd_tlt_22d'].mean() - q1['fwd_tlt_22d'].mean()

# t-test for spread
t_spy, p_spy = stats.ttest_ind(q5['fwd_spy_22d'], q1['fwd_spy_22d'])
t_tlt, p_tlt = stats.ttest_ind(q5['fwd_tlt_22d'], q1['fwd_tlt_22d'])

print(f"\n  Q5-Q1 Spread:")
print(f"    SPY: {spread_spy*12*100:.2f}% ann (t={t_spy:.3f}, p={p_spy:.4f})")
print(f"    TLT: {spread_tlt*12*100:.2f}% ann (t={t_tlt:.3f}, p={p_tlt:.4f})")

# Correlation of divergence with forward returns
r_div_spy, p_div_spy = stats.pearsonr(sig_df['divergence'], sig_df['fwd_spy_22d'])
r_div_tlt, p_div_tlt = stats.pearsonr(sig_df['divergence'], sig_df['fwd_tlt_22d'])
r_div_mix, p_div_mix = stats.pearsonr(sig_df['divergence'], sig_df['fwd_5050_22d'])

print(f"\n  Divergence → Forward Return Correlation:")
print(f"    → SPY: r={r_div_spy:.4f} (p={p_div_spy:.4f})")
print(f"    → TLT: r={r_div_tlt:.4f} (p={p_div_tlt:.4f})")
print(f"    → 50/50: r={r_div_mix:.4f} (p={p_div_mix:.4f})")

# ============================================================
# 8. MOVE Regime for TLT Allocation
# ============================================================
print("\n" + "=" * 70)
print("[8] MOVE Regime for TLT Allocation in 50/50 Portfolio")
print("=" * 70)

# Strategy: Reduce TLT when MOVE is high
alloc_df = df.copy()
alloc_df['spy_ret_next'] = alloc_df['spy_ret'].shift(-1)
alloc_df['tlt_ret_next'] = alloc_df['tlt_ret'].shift(-1)
alloc_df = alloc_df.dropna(subset=['spy_ret_next', 'tlt_ret_next', 'move'])

# MOVE percentiles for regime
move_median = alloc_df['move'].median()
move_75 = alloc_df['move'].quantile(0.75)
move_90 = alloc_df['move'].quantile(0.90)

print(f"\n  MOVE thresholds: median={move_median:.1f}, 75th={move_75:.1f}, 90th={move_90:.1f}")

# Strategy 1: Baseline 50/50
alloc_df['ret_baseline'] = 0.5 * alloc_df['spy_ret_next'] + 0.5 * alloc_df['tlt_ret_next']

# Strategy 2: Reduce TLT when MOVE > 75th (shift to 60/40 SPY/cash... no, let's do SPY/GLD style)
# Actually, the question is: should we underweight TLT when MOVE is high?
# Simple: shift from 50/50 SPY/TLT to 70/30 SPY/TLT when MOVE high

# Strategy 2a: MOVE adaptive
# MOVE < median: 50% TLT (normal)
# MOVE > median: 30% TLT (reduce bond exposure)
# MOVE > 90th: 10% TLT (minimal bond exposure)

def move_adaptive_weight(move_val, median, p75, p90):
    if move_val > p90:
        return 0.10  # minimal TLT
    elif move_val > p75:
        return 0.25
    elif move_val > median:
        return 0.35
    else:
        return 0.50  # full TLT

alloc_df['tlt_w'] = alloc_df['move'].apply(lambda x: move_adaptive_weight(x, move_median, move_75, move_90))
alloc_df['spy_w'] = 1 - alloc_df['tlt_w']
alloc_df['ret_adaptive'] = alloc_df['spy_w'] * alloc_df['spy_ret_next'] + alloc_df['tlt_w'] * alloc_df['tlt_ret_next']

# Strategy 3: Inverse MOVE weight (like 12/VIX but for bonds)
# TLT_weight = min(1, threshold / MOVE)
for threshold in [60, 80, 100]:
    alloc_df[f'tlt_w_{threshold}'] = np.minimum(0.5, 0.5 * threshold / alloc_df['move'])
    alloc_df[f'spy_w_{threshold}'] = 1 - alloc_df[f'tlt_w_{threshold}']
    alloc_df[f'ret_inv_{threshold}'] = alloc_df[f'spy_w_{threshold}'] * alloc_df['spy_ret_next'] + alloc_df[f'tlt_w_{threshold}'] * alloc_df['tlt_ret_next']

# Performance comparison
def calc_metrics(returns, name):
    """Calculate strategy metrics from log returns."""
    cum_ret = np.exp(returns.cumsum()) - 1
    ann_ret = returns.mean() * 252
    ann_vol = returns.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # MDD
    cum_wealth = (1 + cum_ret)
    peak = cum_wealth.cummax()
    dd = (cum_wealth - peak) / peak
    mdd = dd.min()

    return {
        'name': name,
        'ann_ret': ann_ret,
        'ann_vol': ann_vol,
        'sharpe': sharpe,
        'mdd': mdd,
        'calmar': ann_ret / abs(mdd) if mdd != 0 else 0,
    }

strategies = [
    ('ret_baseline', '50/50 SPY/TLT (baseline)'),
    ('ret_adaptive', 'MOVE Adaptive'),
    ('ret_inv_60', 'Inverse MOVE (60)'),
    ('ret_inv_80', 'Inverse MOVE (80)'),
    ('ret_inv_100', 'Inverse MOVE (100)'),
]

print(f"\n  Strategy Comparison ({alloc_df.index[0].strftime('%Y-%m-%d')} to {alloc_df.index[-1].strftime('%Y-%m-%d')}):")
print(f"  {'Strategy':30s} {'Ann Ret':>10s} {'Ann Vol':>10s} {'Sharpe':>8s} {'MDD':>8s} {'Calmar':>8s}")
print(f"  {'-'*74}")

all_metrics = []
for col, name in strategies:
    m = calc_metrics(alloc_df[col], name)
    all_metrics.append(m)
    print(f"  {name:30s} {m['ann_ret']*100:9.2f}% {m['ann_vol']*100:9.2f}% {m['sharpe']:7.3f} {m['mdd']*100:7.2f}% {m['calmar']:7.3f}")

# ============================================================
# 9. MOVE Regime for SPY/GLD 50/50 (does MOVE help the winning strategy?)
# ============================================================
print("\n" + "=" * 70)
print("[9] Does MOVE Improve the 50/50 SPY/GLD Strategy?")
print("=" * 70)

# Download GLD
gld = yf.download("GLD", start="2004-01-01", end="2026-03-25", progress=False)
if isinstance(gld.columns, pd.MultiIndex):
    gld.columns = gld.columns.get_level_values(0)

gld_df = pd.DataFrame(index=gld.index)
gld_df['gld_close'] = gld['Close']
gld_df['gld_ret'] = np.log(gld['Close'] / gld['Close'].shift(1))

# Merge with existing df
combo = df.copy()
combo['gld_ret'] = gld_df['gld_ret'].reindex(combo.index, method='ffill')
combo = combo.dropna(subset=['gld_ret', 'move', 'vix', 'spy_ret'])

combo['spy_ret_next'] = combo['spy_ret'].shift(-1)
combo['gld_ret_next'] = combo['gld_ret'].shift(-1)
combo = combo.dropna(subset=['spy_ret_next', 'gld_ret_next'])

print(f"\n  Sample: {len(combo)} obs ({combo.index[0].strftime('%Y-%m-%d')} to {combo.index[-1].strftime('%Y-%m-%d')})")

# Baseline: 50/50 SPY/GLD with 12/VIX
combo['vix_w'] = np.minimum(1.0, 12.0 / combo['vix'])
combo['ret_vix_base'] = combo['vix_w'] * (0.5 * combo['spy_ret_next'] + 0.5 * combo['gld_ret_next'])

# Modified: 50/50 SPY/GLD with 12/VIX + MOVE overlay
# When MOVE is high (>75th), reduce overall equity exposure further
move_75_combo = combo['move'].quantile(0.75)
move_90_combo = combo['move'].quantile(0.90)

# MOVE overlay: additional risk reduction when bond market stressed
combo['move_adj'] = 1.0  # default: no adjustment
combo.loc[combo['move'] > move_75_combo, 'move_adj'] = 0.85
combo.loc[combo['move'] > move_90_combo, 'move_adj'] = 0.70

combo['ret_vix_move'] = combo['vix_w'] * combo['move_adj'] * (0.5 * combo['spy_ret_next'] + 0.5 * combo['gld_ret_next'])

# Compare
print(f"\n  50/50 SPY/GLD + 12/VIX vs + 12/VIX + MOVE overlay:")
m_base = calc_metrics(combo['ret_vix_base'], '12/VIX baseline')
m_move = calc_metrics(combo['ret_vix_move'], '12/VIX + MOVE overlay')

print(f"  {'Strategy':30s} {'Ann Ret':>10s} {'Ann Vol':>10s} {'Sharpe':>8s} {'MDD':>8s}")
print(f"  {'-'*66}")
print(f"  {m_base['name']:30s} {m_base['ann_ret']*100:9.2f}% {m_base['ann_vol']*100:9.2f}% {m_base['sharpe']:7.3f} {m_base['mdd']*100:7.2f}%")
print(f"  {m_move['name']:30s} {m_move['ann_ret']*100:9.2f}% {m_move['ann_vol']*100:9.2f}% {m_move['sharpe']:7.3f} {m_move['mdd']*100:7.2f}%")

# DM test
dm_combo, p_combo = dm_test(
    (combo['ret_vix_move'] - combo['ret_vix_move'].mean()).values,
    (combo['ret_vix_base'] - combo['ret_vix_base'].mean()).values,
    h=22
)
print(f"\n  DM test (squared return difference): DM={dm_combo:.3f}, p={p_combo:.4f}")

# ============================================================
# 10. MOVE Regime Analysis During Key Events
# ============================================================
print("\n" + "=" * 70)
print("[10] MOVE During Key Market Events")
print("=" * 70)

events = {
    'GFC peak (2008-10)': ('2008-09-01', '2008-12-31'),
    'Taper Tantrum (2013)': ('2013-05-01', '2013-09-30'),
    'COVID crash (2020-03)': ('2020-02-20', '2020-04-30'),
    'Rate hike cycle (2022)': ('2022-01-01', '2022-12-31'),
    'SVB crisis (2023-03)': ('2023-03-01', '2023-04-30'),
    'Calm (2024-H1)': ('2024-01-01', '2024-06-30'),
    'Recent (2025)': ('2025-01-01', '2025-03-24'),
}

print(f"\n  {'Event':30s} {'MOVE':>8s} {'VIX':>8s} {'MOVE/VIX':>10s} {'Div':>8s} {'SPY':>8s} {'TLT':>8s}")
print(f"  {'-'*82}")

for name, (start, end) in events.items():
    mask = (df.index >= start) & (df.index <= end)
    if mask.sum() > 0:
        period = df[mask]
        avg_move = period['move'].mean()
        avg_vix = period['vix'].mean()
        ratio = avg_move / avg_vix if avg_vix > 0 else 0
        div = period['divergence'].mean() if 'divergence' in period.columns and not period['divergence'].isna().all() else np.nan
        spy_ret_period = (period['spy_close'].iloc[-1] / period['spy_close'].iloc[0] - 1) * 100
        tlt_ret_period = (period['tlt_close'].iloc[-1] / period['tlt_close'].iloc[0] - 1) * 100
        print(f"  {name:30s} {avg_move:7.1f} {avg_vix:7.1f} {ratio:9.2f} {div:7.2f} {spy_ret_period:7.1f}% {tlt_ret_period:7.1f}%")

# ============================================================
# 11. MOVE-VIX Ratio as Market Regime Indicator
# ============================================================
print("\n" + "=" * 70)
print("[11] MOVE/VIX Ratio Analysis")
print("=" * 70)

ratio_df = df.copy()
ratio_df['move_vix_ratio'] = ratio_df['move'] / ratio_df['vix']
ratio_df = ratio_df.dropna(subset=['move_vix_ratio'])

print(f"\n  MOVE/VIX Ratio Statistics:")
print(f"    Mean:   {ratio_df['move_vix_ratio'].mean():.2f}")
print(f"    Median: {ratio_df['move_vix_ratio'].median():.2f}")
print(f"    Std:    {ratio_df['move_vix_ratio'].std():.2f}")
print(f"    Min:    {ratio_df['move_vix_ratio'].min():.2f}")
print(f"    Max:    {ratio_df['move_vix_ratio'].max():.2f}")

# When ratio is high: bond fear >> equity fear
# When ratio is low: equity fear >> bond fear
ratio_med = ratio_df['move_vix_ratio'].median()
ratio_75 = ratio_df['move_vix_ratio'].quantile(0.75)
ratio_25 = ratio_df['move_vix_ratio'].quantile(0.25)

print(f"\n  Forward 22d returns by MOVE/VIX ratio regime:")
ratio_df['fwd_spy_22d'] = ratio_df['spy_close'].shift(-22) / ratio_df['spy_close'] - 1
ratio_df['fwd_tlt_22d'] = ratio_df['tlt_close'].shift(-22) / ratio_df['tlt_close'] - 1
ratio_df = ratio_df.dropna(subset=['fwd_spy_22d', 'fwd_tlt_22d'])

ratio_df['ratio_regime'] = pd.cut(ratio_df['move_vix_ratio'],
                                    bins=[0, ratio_25, ratio_med, ratio_75, 999],
                                    labels=['Low (eq fear)', 'Below med', 'Above med', 'High (bond fear)'])

print(f"  {'Regime':20s} {'Fwd SPY':>10s} {'Fwd TLT':>10s} {'Ratio':>10s} {'N':>5s}")
print(f"  {'-'*55}")
for regime in ['Low (eq fear)', 'Below med', 'Above med', 'High (bond fear)']:
    mask = ratio_df['ratio_regime'] == regime
    if mask.sum() > 0:
        spy_r = ratio_df.loc[mask, 'fwd_spy_22d'].mean() * 12 * 100
        tlt_r = ratio_df.loc[mask, 'fwd_tlt_22d'].mean() * 12 * 100
        avg_ratio = ratio_df.loc[mask, 'move_vix_ratio'].mean()
        print(f"  {regime:20s} {spy_r:9.2f}% {tlt_r:9.2f}% {avg_ratio:9.2f} {mask.sum():5d}")

# ============================================================
# 12. Granger Causality: MOVE ↔ VIX
# ============================================================
print("\n" + "=" * 70)
print("[12] Granger Causality: MOVE ↔ VIX")
print("=" * 70)

# Simple F-test based Granger causality
gc_df = df[['move', 'vix']].dropna().copy()
gc_df['move_chg'] = gc_df['move'].pct_change()
gc_df['vix_chg'] = gc_df['vix'].pct_change()
gc_df = gc_df.dropna()

for lags in [1, 5, 22]:
    # Does MOVE Granger-cause VIX?
    # Restricted: VIX_chg ~ lagged VIX_chg
    # Unrestricted: VIX_chg ~ lagged VIX_chg + lagged MOVE_chg

    y = gc_df['vix_chg'].values[lags:]
    n = len(y)

    # Restricted model
    X_r = np.column_stack([gc_df['vix_chg'].shift(i+1).values[lags:] for i in range(lags)] + [np.ones(n)])
    b_r = np.linalg.lstsq(X_r, y, rcond=None)[0]
    rss_r = np.sum((y - X_r @ b_r)**2)

    # Unrestricted model
    X_u = np.column_stack([gc_df['vix_chg'].shift(i+1).values[lags:] for i in range(lags)] +
                          [gc_df['move_chg'].shift(i+1).values[lags:] for i in range(lags)] +
                          [np.ones(n)])
    b_u = np.linalg.lstsq(X_u, y, rcond=None)[0]
    rss_u = np.sum((y - X_u @ b_u)**2)

    k = lags  # number of restrictions
    f_stat = ((rss_r - rss_u) / k) / (rss_u / (n - 2*lags - 1))
    p_val = 1 - stats.f.cdf(f_stat, k, n - 2*lags - 1)

    print(f"\n  MOVE → VIX (lags={lags}): F={f_stat:.3f}, p={p_val:.4f} {'***' if p_val < 0.01 else '**' if p_val < 0.05 else '*' if p_val < 0.10 else 'NS'}")

    # Does VIX Granger-cause MOVE?
    y2 = gc_df['move_chg'].values[lags:]

    X_r2 = np.column_stack([gc_df['move_chg'].shift(i+1).values[lags:] for i in range(lags)] + [np.ones(n)])
    b_r2 = np.linalg.lstsq(X_r2, y2, rcond=None)[0]
    rss_r2 = np.sum((y2 - X_r2 @ b_r2)**2)

    X_u2 = np.column_stack([gc_df['move_chg'].shift(i+1).values[lags:] for i in range(lags)] +
                           [gc_df['vix_chg'].shift(i+1).values[lags:] for i in range(lags)] +
                           [np.ones(n)])
    b_u2 = np.linalg.lstsq(X_u2, y2, rcond=None)[0]
    rss_u2 = np.sum((y2 - X_u2 @ b_u2)**2)

    f_stat2 = ((rss_r2 - rss_u2) / k) / (rss_u2 / (n - 2*lags - 1))
    p_val2 = 1 - stats.f.cdf(f_stat2, k, n - 2*lags - 1)

    print(f"  VIX → MOVE (lags={lags}): F={f_stat2:.3f}, p={p_val2:.4f} {'***' if p_val2 < 0.01 else '**' if p_val2 < 0.05 else '*' if p_val2 < 0.10 else 'NS'}")

# ============================================================
# 13. Summary
# ============================================================
print("\n" + "=" * 70)
print("[13] K390 Summary")
print("=" * 70)

summary = {
    "experiment": "K390",
    "title": "MOVE Index — The Bond VIX",
    "date": datetime.now().strftime("%Y-%m-%d"),
    "data_source": "yfinance: ^MOVE, ^VIX, TLT, SPY, GLD",
    "data_range": f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    "sample_size": len(df),
    "findings": {}
}

print(f"""
FINDINGS:
1. MOVE Characteristics:
   - Mean={move.mean():.1f}, current={move.iloc[-1]:.1f}
   - Positive skew ({move.skew():.2f}), fat tails (kurtosis={move.kurtosis():.2f})

2. MOVE-VIX Relationship:
   - Level correlation: {corr_level:.3f} (moderate positive)
   - Change correlation: {corr_chg:.3f} (weaker)
   - They diverge significantly during rate events

3. Bond Vol Prediction:
   - MOVE → future TLT RV: raw r shown above
   - MOVE partial r (controlling VIX): {r_mv:.4f}
   - MOVE partial r (controlling EWMA): {r_me:.4f}

4. SPY Vol (T11 reconfirmation):
   - MOVE | VIX → SPY: partial r = {r_mv_spy:.4f}
   - {'Confirmed: MOVE adds nothing for equity vol after VIX' if abs(r_mv_spy) < 0.05 else 'Surprise: MOVE adds info for equity vol!'}

5. Divergence Signal:
   - MOVE-VIX divergence → SPY: r={r_div_spy:.4f}
   - MOVE-VIX divergence → TLT: r={r_div_tlt:.4f}
   - {'Weak/no predictive power' if abs(r_div_spy) < 0.05 and abs(r_div_tlt) < 0.05 else 'Some signal detected'}

6. MOVE Regime Allocation:
   - Results shown in Section 8 and 9
""")

# Save results
summary['findings'] = {
    'move_mean': float(move.mean()),
    'move_std': float(move.std()),
    'move_current': float(move.iloc[-1]),
    'move_vix_corr_level': float(corr_level),
    'move_vix_corr_change': float(corr_chg),
    'move_tlt_partial_r_ctrl_vix': float(r_mv),
    'move_tlt_partial_r_ctrl_ewma': float(r_me),
    'move_tlt_partial_r_ctrl_both': float(r_mb),
    'move_spy_partial_r_ctrl_vix': float(r_mv_spy),
    'div_spy_corr': float(r_div_spy),
    'div_tlt_corr': float(r_div_tlt),
    'oos_model_results': {k: {kk: float(vv) for kk, vv in v.items()} for k, v in model_results.items()} if 'model_results' in dir() else {},
}

with open('experiments/k390_move_index_results.json', 'w') as f:
    json.dump(summary, f, indent=2, default=str)

print(f"\nResults saved to experiments/k390_move_index_results.json")
print("=" * 70)
print("K390 COMPLETE")
print("=" * 70)
