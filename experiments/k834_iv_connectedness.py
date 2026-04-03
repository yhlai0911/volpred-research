"""
K834: Implied-Vol Connectedness Regime Filter
================================================
用跨資產 IV 溢出預測系統風險，基於 Diebold & Yilmaz (2012) connectedness 框架

假設：高 TCI (Total Connectedness Index) = 系統風險上升 = 應該減少股票部位

數據來源：yfinance（CBOE IV 指數：^VIX, ^VXN, ^GVZ, ^OVX）
方法：Rolling VAR(5) → FEVD → TCI → Strategy overlay

參考文獻：
- Diebold, F.X. & Yilmaz, K. (2012). Better to give than to receive: Predictive directional
  measurement of volatility spillovers. Int. J. Forecasting, 28(1), 57-66.
- Diebold, F.X. & Yilmaz, K. (2014). On the network topology of variance decompositions:
  Measuring the connectedness of financial firms. J. Econometrics, 182(1), 119-134.

Error Log 防錯：
- signal.shift(1)：TCI 用昨天的值（lag=1 強制）
- DM test：使用 volpred.stats.model_evaluation.strategy_dm_test
- VAR 穩定性：確認所有 eigenvalues < 1
- Sharpe > 2x baseline → 幾乎一定有 bug
"""

import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from scipy import stats
from statsmodels.tsa.api import VAR
from volpred.stats.model_evaluation import strategy_dm_test

warnings.filterwarnings('ignore')

# ============================================================
# 1. Data Download
# ============================================================
print("=" * 60)
print("K834: Implied-Vol Connectedness Regime Filter")
print("=" * 60)

# Try downloading all 4 IV indices
tickers = {
    '^VIX': 'VIX',
    '^VXN': 'VXN',   # Nasdaq 100 vol
    '^GVZ': 'GVZ',   # Gold vol
    '^OVX': 'OVX',   # Oil vol
}

print("\n[1] Downloading IV indices...")
iv_data = {}
for ticker, name in tickers.items():
    try:
        df = yf.download(ticker, start='2008-01-01', end='2025-12-31', progress=False)
        if len(df) > 100:
            # Handle both single and multi-level columns
            if isinstance(df.columns, pd.MultiIndex):
                close = df['Close'].iloc[:, 0]
            else:
                close = df['Close']
            iv_data[name] = close
            print(f"  {name}: {len(close)} obs, {close.index[0].date()} ~ {close.index[-1].date()}")
        else:
            print(f"  {name}: insufficient data ({len(df)} obs), skipping")
    except Exception as e:
        print(f"  {name}: download failed ({e}), skipping")

if len(iv_data) < 2:
    raise ValueError("Need at least 2 IV indices for connectedness analysis")

# Combine into DataFrame
iv_df = pd.DataFrame(iv_data)
iv_df = iv_df.dropna()
print(f"\n  Combined panel: {len(iv_df)} obs, {iv_df.index[0].date()} ~ {iv_df.index[-1].date()}")
print(f"  Available indices: {list(iv_df.columns)}")

# ============================================================
# 2. Log-changes of IV indices
# ============================================================
print("\n[2] Computing log-changes of IV indices...")
log_iv = np.log(iv_df).diff().dropna()
# Remove extreme outliers (> 5 std)
for col in log_iv.columns:
    std_val = log_iv[col].std()
    mask = log_iv[col].abs() > 5 * std_val
    if mask.sum() > 0:
        print(f"  {col}: {mask.sum()} extreme values clipped")
        log_iv.loc[mask, col] = np.sign(log_iv.loc[mask, col]) * 5 * std_val

print(f"  Log-changes shape: {log_iv.shape}")
print(f"  Descriptive stats:")
desc = log_iv.describe().T[['mean', 'std', 'min', 'max']]
print(desc.to_string())

# ============================================================
# 3. Rolling VAR + FEVD → Connectedness
# ============================================================
print("\n[3] Computing Rolling Connectedness (VAR(5) + FEVD)...")

ROLLING_WINDOW = 252  # 1 year
VAR_LAGS = 5
FEVD_STEPS = 10
N = len(log_iv.columns)

def compute_connectedness(data_window, var_lags=5, fevd_steps=10):
    """
    Compute Total Connectedness Index from VAR FEVD.
    Returns TCI and directional spillovers.

    FEVD decomp shape in statsmodels: (N_vars, N_steps, N_vars)
    decomp[i, step, j] = fraction of variable i's h-step-ahead forecast error
                          variance attributable to shocks from variable j

    Stability: statsmodels VAR roots are roots of the characteristic polynomial.
    For stability, all roots should have modulus > 1 (outside unit circle).
    Use results.is_stable() for the correct check.
    """
    try:
        model = VAR(data_window)
        results = model.fit(maxlags=var_lags, ic=None, verbose=False)

        # Check stability
        if not results.is_stable():
            return None  # Unstable VAR

        N_vars = len(data_window.columns)

        # FEVD
        fevd = results.fevd(fevd_steps)
        decomp = fevd.decomp  # shape: (N_vars, N_steps, N_vars)

        # Build D matrix at the last step: D[i,j] = decomp[i, -1, j]
        D = np.zeros((N_vars, N_vars))
        for i in range(N_vars):
            D[i, :] = decomp[i, -1, :]  # last step

        # Total Connectedness Index
        # TCI = 100 * sum(off-diagonal) / N
        off_diag = D.sum() - np.trace(D)
        tci = 100.0 * off_diag / N_vars

        # Directional: FROM others to each variable
        from_others = {}
        cols = data_window.columns.tolist()
        for i, col in enumerate(cols):
            from_val = 100.0 * (D[i, :].sum() - D[i, i]) / N_vars
            from_others[col] = from_val

        # Directional: TO others from each variable
        to_others = {}
        for j, col in enumerate(cols):
            to_val = 100.0 * (D[:, j].sum() - D[j, j]) / N_vars
            to_others[col] = to_val

        return {
            'tci': tci,
            'from_others': from_others,
            'to_others': to_others,
        }
    except Exception:
        return None

# Rolling computation
dates = log_iv.index[ROLLING_WINDOW:]
tci_series = []
from_vix_series = []  # How much VIX receives from others
to_vix_series = []    # How much VIX transmits to others

n_total = len(dates)
n_success = 0
n_fail = 0

for i in range(len(dates)):
    window = log_iv.iloc[i:i + ROLLING_WINDOW]
    result = compute_connectedness(window, VAR_LAGS, FEVD_STEPS)

    if result is not None:
        tci_series.append({'date': dates[i], 'tci': result['tci']})
        if 'VIX' in result['from_others']:
            from_vix_series.append({'date': dates[i], 'from_vix': result['from_others']['VIX']})
        if 'VIX' in result['to_others']:
            to_vix_series.append({'date': dates[i], 'to_vix': result['to_others']['VIX']})
        n_success += 1
    else:
        n_fail += 1

    if (i + 1) % 500 == 0:
        print(f"  Processed {i+1}/{n_total} windows ({n_success} success, {n_fail} failed)")

print(f"  Done: {n_success} success, {n_fail} failed out of {n_total}")

tci_df = pd.DataFrame(tci_series).set_index('date')
from_vix_df = pd.DataFrame(from_vix_series).set_index('date') if from_vix_series else None
to_vix_df = pd.DataFrame(to_vix_series).set_index('date') if to_vix_series else None

print(f"\n  TCI stats:")
print(f"    Mean: {tci_df['tci'].mean():.2f}")
print(f"    Std:  {tci_df['tci'].std():.2f}")
print(f"    Min:  {tci_df['tci'].min():.2f}")
print(f"    Max:  {tci_df['tci'].max():.2f}")
print(f"    P20:  {tci_df['tci'].quantile(0.2):.2f}")
print(f"    P80:  {tci_df['tci'].quantile(0.8):.2f}")

# ============================================================
# 4. Download SPY for strategy testing
# ============================================================
print("\n[4] Downloading SPY...")
spy = yf.download('SPY', start='2008-01-01', end='2025-12-31', progress=False)
if isinstance(spy.columns, pd.MultiIndex):
    spy_close = spy['Close'].iloc[:, 0]
else:
    spy_close = spy['Close']
spy_ret = spy_close.pct_change().dropna()
spy_ret.name = 'spy_return'
print(f"  SPY returns: {len(spy_ret)} obs")

# Download VIX level for 12/VIX baseline
vix_level = iv_df['VIX'] if 'VIX' in iv_df.columns else None

# ============================================================
# 5. Merge everything + align dates
# ============================================================
print("\n[5] Merging data...")
master = pd.DataFrame({'spy_return': spy_ret})
master = master.join(tci_df, how='inner')
if from_vix_df is not None:
    master = master.join(from_vix_df, how='inner')
if vix_level is not None:
    master = master.join(pd.DataFrame({'vix_level': vix_level}), how='inner')

master = master.dropna()
print(f"  Merged dataset: {len(master)} obs, {master.index[0].date()} ~ {master.index[-1].date()}")

# ============================================================
# 6. TCI Predictive Power Analysis
# ============================================================
print("\n[6] TCI Predictive Power Analysis...")

# 6a. TCI vs next-week SPY drawdown
forward_5d_return = master['spy_return'].rolling(5).sum().shift(-5)  # next 5 days cumulative
forward_5d_min = master['spy_return'].rolling(5).min().shift(-5)     # worst day in next 5

# Spearman correlation: TCI_t vs forward returns
mask = ~(forward_5d_return.isna())
if mask.sum() > 100:
    rho_5d, p_5d = stats.spearmanr(master.loc[mask, 'tci'], forward_5d_return[mask])
    print(f"  TCI vs next-5d cumulative return: Spearman r = {rho_5d:.4f}, p = {p_5d:.6f}")
else:
    rho_5d, p_5d = np.nan, np.nan

# TCI vs next-month drawdown
forward_22d_return = master['spy_return'].rolling(22).sum().shift(-22)
mask22 = ~(forward_22d_return.isna())
if mask22.sum() > 100:
    rho_22d, p_22d = stats.spearmanr(master.loc[mask22, 'tci'], forward_22d_return[mask22])
    print(f"  TCI vs next-22d cumulative return: Spearman r = {rho_22d:.4f}, p = {p_22d:.6f}")
else:
    rho_22d, p_22d = np.nan, np.nan

# TCI vs same-day VIX level
if 'vix_level' in master.columns:
    rho_vix, p_vix = stats.spearmanr(master['tci'], master['vix_level'])
    print(f"  TCI vs VIX level (concurrent): Spearman r = {rho_vix:.4f}, p = {p_vix:.6f}")
else:
    rho_vix, p_vix = np.nan, np.nan

# TCI vs next-5d SPY realized vol
forward_5d_vol = master['spy_return'].rolling(5).std().shift(-5) * np.sqrt(252)
mask_vol = ~(forward_5d_vol.isna())
if mask_vol.sum() > 100:
    rho_vol, p_vol = stats.spearmanr(master.loc[mask_vol, 'tci'], forward_5d_vol[mask_vol])
    print(f"  TCI vs next-5d realized vol: Spearman r = {rho_vol:.4f}, p = {p_vol:.6f}")
else:
    rho_vol, p_vol = np.nan, np.nan

# Conditional analysis: high TCI vs low TCI regimes
tci_p80 = master['tci'].quantile(0.8)
tci_p20 = master['tci'].quantile(0.2)
high_tci = master[master['tci'] > tci_p80]
low_tci = master[master['tci'] < tci_p20]
mid_tci = master[(master['tci'] >= tci_p20) & (master['tci'] <= tci_p80)]

print(f"\n  Regime analysis (SPY returns by TCI regime):")
for regime_name, regime_data in [('High TCI (>P80)', high_tci),
                                   ('Mid TCI', mid_tci),
                                   ('Low TCI (<P20)', low_tci)]:
    ret = regime_data['spy_return']
    ann_ret = ret.mean() * 252
    ann_vol = ret.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else np.nan
    print(f"    {regime_name}: n={len(ret)}, ann_ret={ann_ret:.4f}, ann_vol={ann_vol:.4f}, Sharpe={sharpe:.3f}")

# ============================================================
# 7. Strategy Construction & Backtesting
# ============================================================
print("\n[7] Strategy Construction & Backtesting...")

# Define OOS period
OOS_START = '2020-01-01'
OOS_END = '2024-12-31'

# Full sample for in-sample percentiles
is_data = master[master.index < OOS_START]
oos_data = master[(master.index >= OOS_START) & (master.index <= OOS_END)]
print(f"  IS: {len(is_data)} obs ({is_data.index[0].date()} ~ {is_data.index[-1].date()})")
print(f"  OOS: {len(oos_data)} obs ({oos_data.index[0].date()} ~ {oos_data.index[-1].date()})")

# Compute expanding percentiles (no lookahead)
expanding_p80 = master['tci'].expanding(min_periods=252).quantile(0.8)
expanding_p20 = master['tci'].expanding(min_periods=252).quantile(0.2)

# S0: Buy & Hold SPY
master['s0_weight'] = 1.0
master['s0_return'] = master['spy_return']

# S1: 12/VIX baseline
if 'vix_level' in master.columns:
    raw_12vix = 12.0 / master['vix_level']
    master['s1_weight'] = raw_12vix.clip(0.0, 1.0).shift(1)  # LAG=1
    master['s1_return'] = master['s1_weight'] * master['spy_return']
else:
    master['s1_weight'] = np.nan
    master['s1_return'] = np.nan

# S2: TCI-Conditional VT
# Base weight = 12/VIX, then scale by TCI regime
if 'vix_level' in master.columns:
    base_weight = (12.0 / master['vix_level']).clip(0.0, 1.0)
    tci_lagged = master['tci'].shift(1)  # LAG=1 for TCI signal
    p80_lagged = expanding_p80.shift(1)  # LAG=1 for thresholds
    p20_lagged = expanding_p20.shift(1)

    # Apply TCI scaling
    scale = pd.Series(1.0, index=master.index)
    scale[tci_lagged > p80_lagged] = 0.7   # High connectedness → reduce exposure
    scale[tci_lagged < p20_lagged] = 1.3   # Low connectedness → increase exposure

    master['s2_weight'] = (base_weight * scale).clip(0.0, 1.0).shift(1)  # LAG=1 for base weight too
    master['s2_return'] = master['s2_weight'] * master['spy_return']
else:
    master['s2_weight'] = np.nan
    master['s2_return'] = np.nan

# S3: FROM_SPY Conditional
# Use spillover FROM others TO VIX as signal
if from_vix_df is not None and 'vix_level' in master.columns:
    base_weight_s3 = (12.0 / master['vix_level']).clip(0.0, 1.0)
    from_vix_lagged = master['from_vix'].shift(1)  # LAG=1
    from_vix_p80 = master['from_vix'].expanding(min_periods=252).quantile(0.8).shift(1)
    from_vix_p20 = master['from_vix'].expanding(min_periods=252).quantile(0.2).shift(1)

    scale_s3 = pd.Series(1.0, index=master.index)
    scale_s3[from_vix_lagged > from_vix_p80] = 0.7
    scale_s3[from_vix_lagged < from_vix_p20] = 1.3

    master['s3_weight'] = (base_weight_s3 * scale_s3).clip(0.0, 1.0).shift(1)  # LAG=1
    master['s3_return'] = master['s3_weight'] * master['spy_return']
else:
    master['s3_weight'] = np.nan
    master['s3_return'] = np.nan

# ============================================================
# 8. Performance Evaluation (OOS)
# ============================================================
print("\n[8] OOS Performance Evaluation...")

strategies = {
    'S0_BH_SPY': 's0_return',
    'S1_12VIX': 's1_return',
    'S2_TCI_VT': 's2_return',
    'S3_FROM_SPY': 's3_return',
}

oos = master[(master.index >= OOS_START) & (master.index <= OOS_END)].copy()
oos = oos.dropna(subset=[c for c in ['s0_return', 's1_return', 's2_return', 's3_return']
                          if not oos[c].isna().all()])

perf_results = {}
for name, col in strategies.items():
    if col not in oos.columns or oos[col].isna().all():
        print(f"  {name}: no data, skipping")
        continue

    ret = oos[col].dropna()
    if len(ret) < 50:
        continue

    cum_ret = (1 + ret).cumprod()
    ann_ret = ret.mean() * 252
    ann_vol = ret.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else np.nan

    # Max drawdown
    peak = cum_ret.expanding().max()
    dd = (cum_ret - peak) / peak
    mdd = dd.min()

    # Calmar
    calmar = ann_ret / abs(mdd) if mdd != 0 else np.nan

    perf_results[name] = {
        'n_obs': len(ret),
        'ann_return': float(ann_ret),
        'ann_vol': float(ann_vol),
        'sharpe': float(sharpe),
        'max_drawdown': float(mdd),
        'calmar': float(calmar),
        'total_return': float(cum_ret.iloc[-1] - 1),
    }

    print(f"  {name}: Sharpe={sharpe:.3f}, AnnRet={ann_ret:.4f}, AnnVol={ann_vol:.4f}, MDD={mdd:.4f}")

# ============================================================
# 9. DM Tests
# ============================================================
print("\n[9] Diebold-Mariano Tests (Harvey t>3.0 threshold)...")

dm_results = {}
pairs = [
    ('S2_TCI_VT', 'S0_BH_SPY', 's2_return', 's0_return'),
    ('S2_TCI_VT', 'S1_12VIX', 's2_return', 's1_return'),
    ('S3_FROM_SPY', 'S0_BH_SPY', 's3_return', 's0_return'),
    ('S3_FROM_SPY', 'S1_12VIX', 's3_return', 's1_return'),
    ('S2_TCI_VT', 'S3_FROM_SPY', 's2_return', 's3_return'),
]

for name1, name2, col1, col2 in pairs:
    if col1 not in oos.columns or col2 not in oos.columns:
        continue
    r1 = oos[col1].dropna()
    r2 = oos[col2].dropna()
    common = r1.index.intersection(r2.index)
    if len(common) < 100:
        continue

    t_stat, p_val = strategy_dm_test(r1.loc[common].values, r2.loc[common].values)
    sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else ("*" if abs(t_stat) > 1.65 else ""))
    print(f"  {name1} vs {name2}: t={t_stat:.3f}, p={p_val:.4f} {sig}")
    dm_results[f"{name1}_vs_{name2}"] = {
        't_stat': float(t_stat),
        'p_value': float(p_val),
        'significant_harvey': abs(t_stat) > 3.0,
    }

# ============================================================
# 10. Cross-OOS Robustness
# ============================================================
print("\n[10] Cross-OOS Robustness (5 periods)...")

cross_oos_periods = [
    ('2012-01-01', '2013-12-31'),
    ('2014-01-01', '2015-12-31'),
    ('2016-01-01', '2017-12-31'),
    ('2018-01-01', '2019-12-31'),
    ('2020-01-01', '2021-12-31'),
]

cross_oos_results = []
for start, end in cross_oos_periods:
    sub = master[(master.index >= start) & (master.index <= end)].copy()
    if len(sub) < 100:
        print(f"  {start}~{end}: insufficient data ({len(sub)}), skipping")
        continue

    # S0 vs S2
    s0_ret = sub['s0_return'].dropna()
    s2_ret = sub['s2_return'].dropna()

    if len(s0_ret) < 50 or len(s2_ret) < 50:
        continue

    s0_sharpe = s0_ret.mean() * 252 / (s0_ret.std() * np.sqrt(252))
    s2_sharpe = s2_ret.mean() * 252 / (s2_ret.std() * np.sqrt(252))
    s2_wins = s2_sharpe > s0_sharpe

    cross_oos_results.append({
        'period': f"{start}~{end}",
        'n_obs': len(s0_ret),
        's0_sharpe': float(s0_sharpe),
        's2_sharpe': float(s2_sharpe),
        's2_wins': bool(s2_wins),
    })
    print(f"  {start}~{end}: S0={s0_sharpe:.3f}, S2={s2_sharpe:.3f}, {'S2 wins' if s2_wins else 'S0 wins'}")

n_wins = sum(1 for r in cross_oos_results if r['s2_wins'])
print(f"\n  S2 wins {n_wins}/{len(cross_oos_results)} periods")

# ============================================================
# 11. Incremental value of TCI over VIX
# ============================================================
print("\n[11] Incremental value of TCI over VIX alone...")

# Partial correlation: TCI vs forward return, controlling for VIX
if 'vix_level' in master.columns:
    fwd = forward_5d_return.copy()
    mask_full = ~(fwd.isna() | master['tci'].isna() | master['vix_level'].isna())

    if mask_full.sum() > 100:
        from scipy.stats import pearsonr

        # Residualize TCI on VIX
        tci_vals = master.loc[mask_full, 'tci'].values
        vix_vals = master.loc[mask_full, 'vix_level'].values
        fwd_vals = fwd[mask_full].values

        # Partial corr via residuals
        slope_tv = np.polyfit(vix_vals, tci_vals, 1)
        resid_tci = tci_vals - np.polyval(slope_tv, vix_vals)

        slope_fv = np.polyfit(vix_vals, fwd_vals, 1)
        resid_fwd = fwd_vals - np.polyval(slope_fv, vix_vals)

        partial_r, partial_p = pearsonr(resid_tci, resid_fwd)
        print(f"  Partial corr (TCI vs fwd_5d_return | VIX): r={partial_r:.4f}, p={partial_p:.6f}")

        # Also: TCI orthogonal component predicting realized vol
        fwd_vol_vals = forward_5d_vol[mask_full & mask_vol].values if mask_vol.sum() > 100 else None
        if fwd_vol_vals is not None and len(fwd_vol_vals) > 100:
            common_mask = mask_full & mask_vol
            tci_v2 = master.loc[common_mask, 'tci'].values
            vix_v2 = master.loc[common_mask, 'vix_level'].values
            fwd_vol_v2 = forward_5d_vol[common_mask].values

            slope_tv2 = np.polyfit(vix_v2, tci_v2, 1)
            resid_tci2 = tci_v2 - np.polyval(slope_tv2, vix_v2)

            slope_fv2 = np.polyfit(vix_v2, fwd_vol_v2, 1)
            resid_fwd_vol = fwd_vol_v2 - np.polyval(slope_fv2, vix_v2)

            partial_r_vol, partial_p_vol = pearsonr(resid_tci2, resid_fwd_vol)
            print(f"  Partial corr (TCI vs fwd_5d_vol | VIX): r={partial_r_vol:.4f}, p={partial_p_vol:.6f}")
        else:
            partial_r_vol, partial_p_vol = np.nan, np.nan
    else:
        partial_r, partial_p = np.nan, np.nan
        partial_r_vol, partial_p_vol = np.nan, np.nan
else:
    partial_r, partial_p = np.nan, np.nan
    partial_r_vol, partial_p_vol = np.nan, np.nan

# ============================================================
# 12. COVID stress test
# ============================================================
print("\n[12] COVID Stress Test (2020-02 ~ 2020-04)...")
covid = master[(master.index >= '2020-02-01') & (master.index <= '2020-04-30')]
if len(covid) > 20:
    for name, col in strategies.items():
        if col not in covid.columns or covid[col].isna().all():
            continue
        ret = covid[col].dropna()
        cum = (1 + ret).cumprod()
        mdd = ((cum - cum.expanding().max()) / cum.expanding().max()).min()
        total = cum.iloc[-1] - 1
        print(f"  {name}: total={total:.4f}, MDD={mdd:.4f}")

# ============================================================
# 13. Save Results
# ============================================================
print("\n[13] Saving results...")

results = {
    'experiment_id': 'K834',
    'title': 'Implied-Vol Connectedness Regime Filter',
    'description': 'Cross-asset IV spillover (Diebold-Yilmaz 2012) for systemic risk prediction',
    'data_source': 'yfinance (^VIX, ^VXN, ^GVZ, ^OVX)',
    'method': 'Rolling VAR(5) → FEVD(10) → TCI + directional spillovers',
    'references': [
        'Diebold & Yilmaz (2012) Int. J. Forecasting',
        'Diebold & Yilmaz (2014) J. Econometrics',
    ],
    'data_period': {
        'iv_indices': list(iv_df.columns),
        'start': str(iv_df.index[0].date()),
        'end': str(iv_df.index[-1].date()),
        'n_obs_raw': len(iv_df),
        'n_obs_merged': len(master),
    },
    'tci_stats': {
        'mean': float(tci_df['tci'].mean()),
        'std': float(tci_df['tci'].std()),
        'min': float(tci_df['tci'].min()),
        'max': float(tci_df['tci'].max()),
        'p20': float(tci_df['tci'].quantile(0.2)),
        'p80': float(tci_df['tci'].quantile(0.8)),
        'n_var_success': n_success,
        'n_var_fail': n_fail,
    },
    'predictive_power': {
        'tci_vs_fwd_5d_return': {'spearman_r': float(rho_5d) if not np.isnan(rho_5d) else None, 'p_value': float(p_5d) if not np.isnan(p_5d) else None},
        'tci_vs_fwd_22d_return': {'spearman_r': float(rho_22d) if not np.isnan(rho_22d) else None, 'p_value': float(p_22d) if not np.isnan(p_22d) else None},
        'tci_vs_vix_level': {'spearman_r': float(rho_vix) if not np.isnan(rho_vix) else None, 'p_value': float(p_vix) if not np.isnan(p_vix) else None},
        'tci_vs_fwd_5d_vol': {'spearman_r': float(rho_vol) if not np.isnan(rho_vol) else None, 'p_value': float(p_vol) if not np.isnan(p_vol) else None},
        'partial_tci_vs_fwd_5d_return_given_vix': {'r': float(partial_r) if not np.isnan(partial_r) else None, 'p': float(partial_p) if not np.isnan(partial_p) else None},
        'partial_tci_vs_fwd_5d_vol_given_vix': {'r': float(partial_r_vol) if not np.isnan(partial_r_vol) else None, 'p': float(partial_p_vol) if not np.isnan(partial_p_vol) else None},
    },
    'oos_performance': perf_results,
    'dm_tests': dm_results,
    'cross_oos': {
        'periods': cross_oos_results,
        's2_win_rate': f"{n_wins}/{len(cross_oos_results)}",
    },
    'conclusions': [],  # filled below
}

# Build conclusions
conclusions = []

# TCI predictive power
if rho_5d is not None and not np.isnan(rho_5d):
    if abs(rho_5d) > 0.05 and p_5d < 0.05:
        conclusions.append(f"TCI has weak but significant predictive power for 5-day returns (r={rho_5d:.4f})")
    else:
        conclusions.append(f"TCI has negligible predictive power for 5-day returns (r={rho_5d:.4f})")

# Partial correlation
if partial_r is not None and not np.isnan(partial_r):
    if abs(partial_r) > 0.03 and partial_p < 0.05:
        conclusions.append(f"TCI adds marginal information beyond VIX (partial r={partial_r:.4f})")
    else:
        conclusions.append(f"TCI adds NO incremental information beyond VIX (partial r={partial_r:.4f})")

# Strategy comparison
if 'S2_TCI_VT' in perf_results and 'S1_12VIX' in perf_results:
    s2_sh = perf_results['S2_TCI_VT']['sharpe']
    s1_sh = perf_results['S1_12VIX']['sharpe']
    diff = s2_sh - s1_sh
    conclusions.append(f"TCI-Conditional VT Sharpe={s2_sh:.3f} vs 12/VIX Sharpe={s1_sh:.3f} (diff={diff:.3f})")

    # Check DM test
    dm_key = 'S2_TCI_VT_vs_S1_12VIX'
    if dm_key in dm_results:
        if dm_results[dm_key]['significant_harvey']:
            conclusions.append("Difference is statistically significant (Harvey t>3.0)")
        else:
            conclusions.append(f"Difference is NOT statistically significant (t={dm_results[dm_key]['t_stat']:.3f})")

# Cross-OOS
if cross_oos_results:
    conclusions.append(f"Cross-OOS: S2 wins {n_wins}/{len(cross_oos_results)} periods vs BH SPY")

# TCI-VIX relationship
if rho_vix is not None and not np.isnan(rho_vix):
    conclusions.append(f"TCI is {'highly' if abs(rho_vix) > 0.5 else 'moderately' if abs(rho_vix) > 0.3 else 'weakly'} correlated with VIX level (r={rho_vix:.4f})")

results['conclusions'] = conclusions

# Save
output_path = 'experiments/k834_iv_connectedness_results.json'
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\n  Results saved to {output_path}")

# ============================================================
# Summary
# ============================================================
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
for c in conclusions:
    print(f"  • {c}")
print("=" * 60)
