"""
K299: Under-Explored Directions — 3 Quick Pilot Tests
======================================================
Based on K298 gap analysis of 23 under-explored themes.

Pilot A: Multivariate GARCH (DCC) for portfolio vol
Pilot B: Network Centrality Change as Vol Predictor
Pilot C: Sentiment via Extreme Fear Episodes

Data: yfinance daily, 2005-2024.
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from datetime import datetime
import json
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# DATA DOWNLOAD
# ============================================================
print("=" * 70)
print("K299: Under-Explored Directions — 3 Quick Pilot Tests")
print("=" * 70)

tickers = ['SPY', 'GLD', 'TLT', 'QQQ', 'IWM', 'EEM', '^VIX']
print(f"\nDownloading {tickers} from yfinance, 2005-01-01 to 2024-12-31...")

data = yf.download(tickers, start='2005-01-01', end='2024-12-31', auto_adjust=True)
prices = data['Close'].dropna()
prices.columns = [c.replace('^', '') for c in prices.columns]

# GLD started Nov 2004, EEM started Apr 2003 — should be fine
print(f"Price data: {prices.index[0].date()} to {prices.index[-1].date()}, {len(prices)} obs")
print(f"Assets: {list(prices.columns)}")

# Log returns
rets = np.log(prices / prices.shift(1)).dropna()
print(f"Returns: {rets.index[0].date()} to {rets.index[-1].date()}, {len(rets)} obs")

# Realized vol (22d forward)
rv22 = rets['SPY'].rolling(22).std() * np.sqrt(252)
rv22_fwd = rv22.shift(-22)  # forward-looking 22d realized vol

results = {}

# ============================================================
# PILOT A: DCC-GARCH for Portfolio Variance Forecast
# ============================================================
print("\n" + "=" * 70)
print("PILOT A: DCC vs Fixed-Correlation Portfolio Vol (SPY-GLD)")
print("=" * 70)

spy_ret = rets['SPY'].values
gld_ret = rets['GLD'].values
dates = rets.index

# Rolling windows
roll_dcc = 252  # 1-year rolling for DCC proxy
roll_eval = 66  # evaluation window for realized portfolio vol

# We'll approximate DCC with a rolling exponentially-weighted correlation
# True DCC requires iterative MLE; for a quick pilot, EWMA correlation is
# the standard practitioner proxy (RiskMetrics approach)

def ewma_cov(r1, r2, lam=0.94):
    """Exponentially weighted covariance (RiskMetrics)"""
    n = len(r1)
    cov = np.zeros(n)
    cov[0] = r1[0] * r2[0]
    for t in range(1, n):
        cov[t] = lam * cov[t-1] + (1 - lam) * r1[t] * r2[t]
    return cov

def ewma_var(r, lam=0.94):
    """Exponentially weighted variance"""
    n = len(r)
    var = np.zeros(n)
    var[0] = r[0] ** 2
    for t in range(1, n):
        var[t] = lam * var[t-1] + (1 - lam) * r[t] ** 2
    return var

# EWMA variances and covariance (DCC proxy)
ewma_var_spy = ewma_var(spy_ret)
ewma_var_gld = ewma_var(gld_ret)
ewma_cov_sg = ewma_cov(spy_ret, gld_ret)

# EWMA correlation
ewma_corr = ewma_cov_sg / (np.sqrt(ewma_var_spy) * np.sqrt(ewma_var_gld) + 1e-12)
ewma_corr = np.clip(ewma_corr, -0.999, 0.999)

# Fixed (expanding) correlation
fix_corr = pd.Series(spy_ret).expanding(min_periods=252).corr(pd.Series(gld_ret)).values

# 50/50 portfolio variance forecasts
w = np.array([0.5, 0.5])

# DCC portfolio vol forecast (annualized)
dcc_port_var = (w[0]**2 * ewma_var_spy + w[1]**2 * ewma_var_gld +
                2 * w[0] * w[1] * ewma_cov_sg)
dcc_port_vol = np.sqrt(dcc_port_var * 252)

# Fixed-corr portfolio vol forecast
fix_port_var = (w[0]**2 * ewma_var_spy + w[1]**2 * ewma_var_gld +
                2 * w[0] * w[1] * fix_corr * np.sqrt(ewma_var_spy) * np.sqrt(ewma_var_gld))
fix_port_vol = np.sqrt(np.maximum(fix_port_var, 0) * 252)

# Realized portfolio vol (forward 22d)
port_ret = 0.5 * spy_ret + 0.5 * gld_ret
port_rv22 = pd.Series(port_ret).rolling(22).std().values * np.sqrt(252)
port_rv22_fwd = np.roll(port_rv22, -22)  # forward 22d

# Evaluation: compare forecast accuracy (OOS from 2010 onward)
eval_start = np.searchsorted(dates, pd.Timestamp('2010-01-01'))
eval_end = len(dates) - 22  # leave room for forward vol

valid = np.arange(eval_start, eval_end)
valid = valid[~np.isnan(dcc_port_vol[valid]) & ~np.isnan(fix_port_vol[valid]) &
              ~np.isnan(port_rv22_fwd[valid]) & (port_rv22_fwd[valid] > 0)]

dcc_err = (dcc_port_vol[valid] - port_rv22_fwd[valid]) ** 2
fix_err = (fix_port_vol[valid] - port_rv22_fwd[valid]) ** 2

# Diebold-Mariano test (DCC vs Fixed)
d = fix_err - dcc_err  # positive = DCC better
dm_mean = np.mean(d)
dm_se = np.std(d) / np.sqrt(len(d))
dm_t = dm_mean / dm_se
dm_p = 2 * (1 - stats.t.cdf(abs(dm_t), df=len(d)-1))

rmse_dcc = np.sqrt(np.mean(dcc_err))
rmse_fix = np.sqrt(np.mean(fix_err))

# Correlation between DCC forecast and realized
corr_dcc = np.corrcoef(dcc_port_vol[valid], port_rv22_fwd[valid])[0, 1]
corr_fix = np.corrcoef(fix_port_vol[valid], port_rv22_fwd[valid])[0, 1]

print(f"\nEvaluation period: {dates[eval_start].date()} to {dates[eval_end].date()}")
print(f"N observations: {len(valid)}")
print(f"\nRMSE  DCC (EWMA):     {rmse_dcc:.6f}")
print(f"RMSE  Fixed-corr:     {rmse_fix:.6f}")
print(f"RMSE improvement:     {(rmse_fix - rmse_dcc) / rmse_fix * 100:.2f}%")
print(f"\nCorr(forecast, realized) DCC:   {corr_dcc:.4f}")
print(f"Corr(forecast, realized) Fixed: {corr_fix:.4f}")
print(f"\nDM test (H0: equal accuracy):")
print(f"  t-stat = {dm_t:.3f}, p-value = {dm_p:.4f}")

# Partial correlation controlling for VIX
vix_level = prices['VIX'].reindex(dates).values
vix_valid = vix_level[valid]
mask_vix = ~np.isnan(vix_valid)

if mask_vix.sum() > 100:
    from numpy.linalg import lstsq

    def partial_corr(x, y, z):
        """Partial correlation of x,y controlling for z"""
        mask = ~(np.isnan(x) | np.isnan(y) | np.isnan(z))
        x, y, z = x[mask], y[mask], z[mask]
        # Residualize
        Z = np.column_stack([z, np.ones(len(z))])
        rx = x - Z @ lstsq(Z, x, rcond=None)[0]
        ry = y - Z @ lstsq(Z, y, rcond=None)[0]
        return np.corrcoef(rx, ry)[0, 1], len(x)

    pr_dcc, n_pr = partial_corr(dcc_port_vol[valid], port_rv22_fwd[valid], vix_valid)
    pr_fix, _ = partial_corr(fix_port_vol[valid], port_rv22_fwd[valid], vix_valid)

    # t-stat for partial correlation
    t_pr_dcc = pr_dcc * np.sqrt((n_pr - 3) / (1 - pr_dcc**2))
    t_pr_fix = pr_fix * np.sqrt((n_pr - 3) / (1 - pr_fix**2))

    print(f"\nPartial r(forecast, realized | VIX):")
    print(f"  DCC:   {pr_dcc:.4f}  (t={t_pr_dcc:.2f})")
    print(f"  Fixed: {pr_fix:.4f}  (t={t_pr_fix:.2f})")

# Summary stats on rolling correlation
ewma_corr_valid = ewma_corr[valid]
print(f"\nEWMA correlation (SPY-GLD) stats:")
print(f"  Mean: {np.nanmean(ewma_corr_valid):.4f}")
print(f"  Std:  {np.nanstd(ewma_corr_valid):.4f}")
print(f"  Min:  {np.nanmin(ewma_corr_valid):.4f}")
print(f"  Max:  {np.nanmax(ewma_corr_valid):.4f}")

results['pilot_a'] = {
    'rmse_dcc': float(rmse_dcc),
    'rmse_fixed': float(rmse_fix),
    'rmse_improvement_pct': float((rmse_fix - rmse_dcc) / rmse_fix * 100),
    'corr_dcc_realized': float(corr_dcc),
    'corr_fix_realized': float(corr_fix),
    'dm_t_stat': float(dm_t),
    'dm_p_value': float(dm_p),
    'partial_r_dcc': float(pr_dcc) if mask_vix.sum() > 100 else None,
    'partial_r_fix': float(pr_fix) if mask_vix.sum() > 100 else None,
    'ewma_corr_mean': float(np.nanmean(ewma_corr_valid)),
    'ewma_corr_std': float(np.nanstd(ewma_corr_valid)),
    'n_obs': int(len(valid)),
}

print("\n--- Pilot A Conclusion ---")
if dm_p < 0.05:
    print(f"DCC (EWMA proxy) {'IMPROVES' if dm_t > 0 else 'WORSENS'} portfolio vol "
          f"forecasts vs fixed correlation (DM t={dm_t:.2f}, p={dm_p:.4f}).")
else:
    print(f"No significant difference between DCC and fixed-correlation forecasts "
          f"(DM t={dm_t:.2f}, p={dm_p:.4f}).")


# ============================================================
# PILOT B: Network Centrality Change as Vol Predictor
# ============================================================
print("\n" + "=" * 70)
print("PILOT B: Network Centrality Change → SPY Vol")
print("=" * 70)

net_assets = ['SPY', 'QQQ', 'GLD', 'TLT', 'IWM', 'EEM']
net_rets = rets[net_assets].dropna()
print(f"Network assets: {net_assets}")
print(f"Data: {net_rets.index[0].date()} to {net_rets.index[-1].date()}, {len(net_rets)} obs")

def eigenvector_centrality(corr_matrix):
    """Compute eigenvector centrality from correlation matrix.
    Uses absolute correlations (connection strength regardless of sign)."""
    # Use absolute correlation as adjacency
    adj = np.abs(corr_matrix)
    np.fill_diagonal(adj, 0)  # no self-loops

    # Power iteration for dominant eigenvector
    n = adj.shape[0]
    v = np.ones(n) / n
    for _ in range(100):
        v_new = adj @ v
        norm = np.linalg.norm(v_new)
        if norm > 0:
            v_new = v_new / norm
        if np.allclose(v, v_new, atol=1e-10):
            break
        v = v_new
    return v

# Rolling 66d correlation → eigenvector centrality of SPY
roll_net = 66
spy_idx = net_assets.index('SPY')

centrality_spy = []
centrality_dates = []

for i in range(roll_net, len(net_rets)):
    window = net_rets.iloc[i-roll_net:i]
    corr_mat = window.corr().values

    # Check for NaN
    if np.any(np.isnan(corr_mat)):
        centrality_spy.append(np.nan)
    else:
        ec = eigenvector_centrality(corr_mat)
        centrality_spy.append(ec[spy_idx])
    centrality_dates.append(net_rets.index[i])

centrality_series = pd.Series(centrality_spy, index=centrality_dates)

# Change in centrality (5-day)
centrality_change = centrality_series.diff(5)

# Align with forward realized vol
rv22_fwd_aligned = rv22_fwd.reindex(centrality_change.index)

# Also get VIX for partial correlation
vix_aligned = prices['VIX'].reindex(centrality_change.index)

# Clean data
df_b = pd.DataFrame({
    'centrality': centrality_series,
    'cent_change': centrality_change,
    'rv22_fwd': rv22_fwd_aligned,
    'vix': vix_aligned
}).dropna()

# OOS: 2010+
df_b_oos = df_b[df_b.index >= '2010-01-01']
print(f"\nOOS evaluation: {df_b_oos.index[0].date()} to {df_b_oos.index[-1].date()}, N={len(df_b_oos)}")

# Simple correlation
corr_cent_vol = df_b_oos['cent_change'].corr(df_b_oos['rv22_fwd'])
print(f"\nCorr(centrality_change_5d, rv22_fwd): {corr_cent_vol:.4f}")

# Partial correlation controlling for VIX
def partial_corr_df(df, x_col, y_col, z_col):
    """Partial correlation from dataframe"""
    x = df[x_col].values
    y = df[y_col].values
    z = df[z_col].values
    Z = np.column_stack([z, np.ones(len(z))])
    from numpy.linalg import lstsq
    rx = x - Z @ lstsq(Z, x, rcond=None)[0]
    ry = y - Z @ lstsq(Z, y, rcond=None)[0]
    r = np.corrcoef(rx, ry)[0, 1]
    n = len(x)
    t = r * np.sqrt((n - 3) / (1 - r**2))
    p = 2 * (1 - stats.t.cdf(abs(t), df=n-3))
    return r, t, p, n

pr_b, t_b, p_b, n_b = partial_corr_df(df_b_oos, 'cent_change', 'rv22_fwd', 'vix')
print(f"Partial r(cent_change, rv22_fwd | VIX): {pr_b:.4f}  (t={t_b:.2f}, p={p_b:.4f})")

# Level of centrality (not just change)
pr_b_lev, t_b_lev, p_b_lev, _ = partial_corr_df(df_b_oos, 'centrality', 'rv22_fwd', 'vix')
print(f"Partial r(centrality_level, rv22_fwd | VIX): {pr_b_lev:.4f}  (t={t_b_lev:.2f}, p={p_b_lev:.4f})")

# Quintile analysis
df_b_oos = df_b_oos.copy()
df_b_oos['cent_quintile'] = pd.qcut(df_b_oos['cent_change'], 5, labels=False, duplicates='drop')
quintile_vol = df_b_oos.groupby('cent_quintile')['rv22_fwd'].mean()
print(f"\nMean future vol by centrality-change quintile:")
for q in quintile_vol.index:
    print(f"  Q{int(q)+1}: {quintile_vol[q]:.4f}")

# Monotonicity check
q_vals = quintile_vol.values
monotonic = all(q_vals[i] <= q_vals[i+1] for i in range(len(q_vals)-1)) or \
            all(q_vals[i] >= q_vals[i+1] for i in range(len(q_vals)-1))
print(f"  Monotonic: {monotonic}")

# Centrality stats
print(f"\nSPY eigenvector centrality stats:")
print(f"  Mean: {centrality_series.mean():.4f}")
print(f"  Std:  {centrality_series.std():.4f}")
print(f"  Min:  {centrality_series.min():.4f}")
print(f"  Max:  {centrality_series.max():.4f}")

results['pilot_b'] = {
    'corr_cent_change_vol': float(corr_cent_vol),
    'partial_r_cent_change': float(pr_b),
    'partial_r_t_stat': float(t_b),
    'partial_r_p_value': float(p_b),
    'partial_r_cent_level': float(pr_b_lev),
    'partial_r_level_t': float(t_b_lev),
    'quintile_vols': {f'Q{int(k)+1}': float(v) for k, v in quintile_vol.items()},
    'monotonic': monotonic,
    'centrality_mean': float(centrality_series.mean()),
    'centrality_std': float(centrality_series.std()),
    'n_obs': int(n_b),
}

print("\n--- Pilot B Conclusion ---")
if abs(t_b) > 3.0:
    print(f"SPY centrality change has STRONG predictive power for future vol "
          f"(partial r={pr_b:.4f}, t={t_b:.2f}). Meets Harvey (2016) threshold.")
elif abs(t_b) > 1.96:
    print(f"SPY centrality change has MARGINAL predictive power (partial r={pr_b:.4f}, "
          f"t={t_b:.2f}). Significant at 5% but below Harvey threshold.")
else:
    print(f"SPY centrality change has NO significant predictive power beyond VIX "
          f"(partial r={pr_b:.4f}, t={t_b:.2f}).")


# ============================================================
# PILOT C: Extreme Fear Episodes → Future Vol & Returns
# ============================================================
print("\n" + "=" * 70)
print("PILOT C: Extreme Fear (VIX Spikes) → Future Vol & Contrarian Returns")
print("=" * 70)

vix_series = prices['VIX'].reindex(rets.index).dropna()
spy_rets = rets['SPY'].reindex(vix_series.index)

# VIX 5-day change
vix_5d_change = vix_series.diff(5)

# VIX 5d change rolling stats (expanding)
vix_5d_mean = vix_5d_change.expanding(min_periods=252).mean()
vix_5d_std = vix_5d_change.expanding(min_periods=252).std()

# Z-score of VIX 5d change
vix_5d_z = (vix_5d_change - vix_5d_mean) / vix_5d_std

# Extreme fear: VIX rises > 2 std in 5 days
extreme_fear = vix_5d_z > 2.0

# Forward 22d realized vol and return
fwd_22d_vol = spy_rets.rolling(22).std().shift(-22) * np.sqrt(252)
fwd_22d_ret = spy_rets.rolling(22).sum().shift(-22)  # log return over next 22 days

# Align
df_c = pd.DataFrame({
    'vix': vix_series,
    'vix_5d_z': vix_5d_z,
    'extreme_fear': extreme_fear,
    'rv22_fwd': fwd_22d_vol,
    'ret_22d_fwd': fwd_22d_ret,
    'spy_ret': spy_rets
}).dropna()

# OOS: 2010+
df_c_oos = df_c[df_c.index >= '2010-01-01']
print(f"\nOOS period: {df_c_oos.index[0].date()} to {df_c_oos.index[-1].date()}, N={len(df_c_oos)}")

# Count extreme fear days
n_fear = df_c_oos['extreme_fear'].sum()
n_calm = len(df_c_oos) - n_fear
print(f"Extreme fear days: {int(n_fear)} ({n_fear/len(df_c_oos)*100:.1f}%)")
print(f"Normal days: {int(n_calm)} ({n_calm/len(df_c_oos)*100:.1f}%)")

# Vol comparison
fear_vol = df_c_oos.loc[df_c_oos['extreme_fear'], 'rv22_fwd'].mean()
calm_vol = df_c_oos.loc[~df_c_oos['extreme_fear'], 'rv22_fwd'].mean()
vol_ratio = fear_vol / calm_vol

print(f"\nMean 22d forward vol:")
print(f"  After extreme fear: {fear_vol:.4f}")
print(f"  Normal periods:     {calm_vol:.4f}")
print(f"  Ratio (fear/calm):  {vol_ratio:.2f}x")

# t-test
t_vol, p_vol = stats.ttest_ind(
    df_c_oos.loc[df_c_oos['extreme_fear'], 'rv22_fwd'],
    df_c_oos.loc[~df_c_oos['extreme_fear'], 'rv22_fwd']
)
print(f"  t-test: t={t_vol:.2f}, p={p_vol:.4f}")

# Contrarian returns
fear_ret = df_c_oos.loc[df_c_oos['extreme_fear'], 'ret_22d_fwd'].mean()
calm_ret = df_c_oos.loc[~df_c_oos['extreme_fear'], 'ret_22d_fwd'].mean()

fear_ret_ann = fear_ret * 252 / 22  # annualized
calm_ret_ann = calm_ret * 252 / 22

print(f"\nMean 22d forward return (log):")
print(f"  After extreme fear: {fear_ret:.4f} (ann. {fear_ret_ann:.4f})")
print(f"  Normal periods:     {calm_ret:.4f} (ann. {calm_ret_ann:.4f})")
print(f"  Excess (fear-calm): {(fear_ret - calm_ret):.4f}")

t_ret, p_ret = stats.ttest_ind(
    df_c_oos.loc[df_c_oos['extreme_fear'], 'ret_22d_fwd'],
    df_c_oos.loc[~df_c_oos['extreme_fear'], 'ret_22d_fwd']
)
print(f"  t-test: t={t_ret:.2f}, p={p_ret:.4f}")

# Sharpe of contrarian strategy
fear_rets = df_c_oos.loc[df_c_oos['extreme_fear'], 'ret_22d_fwd']
if len(fear_rets) > 10:
    sharpe_fear = fear_rets.mean() / fear_rets.std() * np.sqrt(252/22)
    print(f"\n  Contrarian Sharpe (buy on fear, hold 22d): {sharpe_fear:.3f}")
else:
    sharpe_fear = np.nan

# Partial correlation: VIX Z-score → future vol, controlling for VIX level
pr_c, t_c, p_c, n_c = partial_corr_df(df_c_oos, 'vix_5d_z', 'rv22_fwd', 'vix')
print(f"\nPartial r(VIX_5d_zscore, rv22_fwd | VIX_level): {pr_c:.4f}  (t={t_c:.2f}, p={p_c:.4f})")

# Also test: VIX z-score → future returns | VIX level
pr_c_ret, t_c_ret, p_c_ret, _ = partial_corr_df(df_c_oos, 'vix_5d_z', 'ret_22d_fwd', 'vix')
print(f"Partial r(VIX_5d_zscore, ret22_fwd | VIX_level): {pr_c_ret:.4f}  (t={t_c_ret:.2f}, p={p_c_ret:.4f})")

# Win rate after extreme fear
if n_fear > 0:
    win_rate = (fear_rets > 0).mean()
    print(f"\nWin rate (22d return > 0 after extreme fear): {win_rate:.1%}")

# List extreme fear episodes
fear_dates = df_c_oos[df_c_oos['extreme_fear']].index
# Cluster episodes (within 10 days = same episode)
episodes = []
current_episode = [fear_dates[0]]
for i in range(1, len(fear_dates)):
    if (fear_dates[i] - fear_dates[i-1]).days <= 10:
        current_episode.append(fear_dates[i])
    else:
        episodes.append(current_episode)
        current_episode = [fear_dates[i]]
episodes.append(current_episode)

print(f"\nDistinct fear episodes (>10d gap): {len(episodes)}")
print("Notable episodes:")
for ep in episodes[:10]:
    start = ep[0].strftime('%Y-%m-%d')
    end = ep[-1].strftime('%Y-%m-%d')
    vix_at = vix_series.loc[ep[-1]]
    fwd = df_c_oos.loc[ep[-1], 'ret_22d_fwd'] if ep[-1] in df_c_oos.index else np.nan
    print(f"  {start} to {end} ({len(ep)}d), VIX={vix_at:.1f}, 22d fwd ret={fwd:.3f}")

results['pilot_c'] = {
    'n_extreme_fear': int(n_fear),
    'pct_extreme_fear': float(n_fear / len(df_c_oos) * 100),
    'n_episodes': len(episodes),
    'mean_vol_fear': float(fear_vol),
    'mean_vol_calm': float(calm_vol),
    'vol_ratio': float(vol_ratio),
    'vol_t_stat': float(t_vol),
    'vol_p_value': float(p_vol),
    'mean_ret_fear': float(fear_ret),
    'mean_ret_calm': float(calm_ret),
    'ret_excess': float(fear_ret - calm_ret),
    'ret_t_stat': float(t_ret),
    'ret_p_value': float(p_ret),
    'contrarian_sharpe': float(sharpe_fear) if not np.isnan(sharpe_fear) else None,
    'win_rate': float(win_rate) if n_fear > 0 else None,
    'partial_r_vix_z_vol': float(pr_c),
    'partial_r_vix_z_vol_t': float(t_c),
    'partial_r_vix_z_ret': float(pr_c_ret),
    'partial_r_vix_z_ret_t': float(t_c_ret),
    'n_obs': int(n_c),
}

print("\n--- Pilot C Conclusion ---")
if p_vol < 0.01:
    print(f"Extreme VIX spikes DO predict elevated future vol (ratio={vol_ratio:.2f}x, "
          f"t={t_vol:.2f}).")
else:
    print(f"Extreme VIX spikes have weak vol prediction (ratio={vol_ratio:.2f}x, "
          f"t={t_vol:.2f}).")

if fear_ret > calm_ret and p_ret < 0.05:
    print(f"Contrarian strategy (buy on fear) shows POSITIVE excess return "
          f"({(fear_ret-calm_ret)*10000:.0f} bps/22d, t={t_ret:.2f}).")
elif fear_ret > calm_ret:
    print(f"Contrarian strategy shows positive but insignificant excess "
          f"({(fear_ret-calm_ret)*10000:.0f} bps/22d, t={t_ret:.2f}).")
else:
    print(f"Contrarian strategy shows NEGATIVE excess return — fear begets more fear.")


# ============================================================
# OVERALL SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("K299 OVERALL SUMMARY")
print("=" * 70)

print("""
Pilot A (DCC Portfolio Vol):
  - Tests whether dynamic correlation (EWMA/DCC proxy) improves
    50/50 SPY-GLD portfolio variance forecasts vs fixed correlation.
  - Result: See DM test above.

Pilot B (Network Centrality):
  - Tests whether SPY's eigenvector centrality change in a 6-asset
    correlation network predicts future SPY volatility.
  - Partial r controlling for VIX level.

Pilot C (Extreme Fear):
  - Tests contrarian timing: buy SPY after extreme VIX spikes (>2σ
    5-day VIX increase), hold 22 days.
  - Examines both vol prediction and return prediction.
""")

# Rank pilots by promise
pilots_promise = []
for name, key, stat in [
    ('A: DCC Portfolio Vol', 'pilot_a', abs(results['pilot_a']['dm_t_stat'])),
    ('B: Network Centrality', 'pilot_b', abs(results['pilot_b']['partial_r_t_stat'])),
    ('C: Extreme Fear', 'pilot_c', abs(results['pilot_c']['partial_r_vix_z_vol_t'])),
]:
    pilots_promise.append((name, stat))

pilots_promise.sort(key=lambda x: x[1], reverse=True)
print("Ranked by strength of evidence (|t-stat|):")
for i, (name, t) in enumerate(pilots_promise):
    harvey = "✓ Harvey" if t > 3.0 else "✗"
    print(f"  {i+1}. {name}: |t|={t:.2f} {harvey}")

# Save results
output_path = 'experiments/k299_gap_pilots_results.json'
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\nResults saved to {output_path}")

print("\n" + "=" * 70)
print("K299 COMPLETE")
print("=" * 70)
