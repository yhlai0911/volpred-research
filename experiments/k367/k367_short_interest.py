"""
K367: Short Interest as Volatility Signal — Does Bearish Positioning Predict Vol?
=================================================================================
[提出: Claude, 執行: Claude]

跳躍式探索：從市場微結構角度探討空頭部位是否能預測波動率。

⚠️ 重要聲明：真正的 short interest 數據由交易所每兩週公布一次（FINRA），
yfinance 不提供此數據。本實驗使用的是「代理變數」(proxies)：
- SH (ProShares Short S&P 500) 成交量 / SPY 成交量比率
- 反向 ETF 相對活躍度
- VIX × SPY volume 作為恐慌活動代理
這些代理變數的假設和局限性在結論中明確討論。

數據來源：yfinance（真實市場數據）
資產：SPY, QQQ, IWM, SH, SDS, VIX (^VIX)
資料期間：2007-01-01 至 2026-03-25（涵蓋 GFC、COVID、GameStop 等事件）
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from datetime import datetime
import json
import warnings
warnings.filterwarnings('ignore')

print("=" * 80)
print("K367: Short Interest as Volatility Signal")
print("Does Bearish Positioning Predict Volatility?")
print("=" * 80)
print()
print("⚠️  PROXY-BASED ANALYSIS: True short interest not available via yfinance.")
print("    Using inverse ETF volume ratios and VIX-volume composites as proxies.")
print()

# =============================================================================
# 1. DATA COLLECTION
# =============================================================================
print("=" * 80)
print("SECTION 1: Data Collection")
print("=" * 80)

tickers = {
    'SPY': 'SPY',       # S&P 500 ETF
    'QQQ': 'QQQ',       # Nasdaq 100 ETF
    'IWM': 'IWM',       # Russell 2000 ETF
    'SH': 'SH',         # ProShares Short S&P 500 (1x inverse)
    'SDS': 'SDS',       # ProShares UltraShort S&P 500 (2x inverse)
    'VIX': '^VIX',      # CBOE VIX
}

start_date = '2007-01-01'
end_date = '2026-03-25'

data = {}
for name, ticker in tickers.items():
    print(f"  Downloading {name} ({ticker})...")
    df = yf.download(ticker, start=start_date, end=end_date, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    data[name] = df
    print(f"    -> {len(df)} observations, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

print()

# Build combined DataFrame
spy = data['SPY'][['Close', 'Volume']].copy()
spy.columns = ['SPY_Close', 'SPY_Volume']

qqq = data['QQQ'][['Close', 'Volume']].copy()
qqq.columns = ['QQQ_Close', 'QQQ_Volume']

iwm = data['IWM'][['Close', 'Volume']].copy()
iwm.columns = ['IWM_Close', 'IWM_Volume']

sh = data['SH'][['Close', 'Volume']].copy()
sh.columns = ['SH_Close', 'SH_Volume']

sds = data['SDS'][['Close', 'Volume']].copy()
sds.columns = ['SDS_Close', 'SDS_Volume']

vix = data['VIX'][['Close']].copy()
vix.columns = ['VIX']

df = spy.join(qqq, how='inner').join(iwm, how='inner').join(sh, how='inner').join(sds, how='inner').join(vix, how='inner')
df = df.dropna()

print(f"Combined dataset: {len(df)} observations")
print(f"Period: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
print()

# =============================================================================
# 2. CONSTRUCT PROXY VARIABLES
# =============================================================================
print("=" * 80)
print("SECTION 2: Construct Short Interest Proxy Variables")
print("=" * 80)

# Returns
df['SPY_ret'] = np.log(df['SPY_Close'] / df['SPY_Close'].shift(1))
df['QQQ_ret'] = np.log(df['QQQ_Close'] / df['QQQ_Close'].shift(1))
df['IWM_ret'] = np.log(df['IWM_Close'] / df['IWM_Close'].shift(1))

# Realized volatility (forward-looking, 5-day and 21-day)
df['RV_5d'] = df['SPY_ret'].rolling(5).std() * np.sqrt(252)
df['RV_21d'] = df['SPY_ret'].rolling(21).std() * np.sqrt(252)

# Forward RV (what we want to predict)
df['fwd_RV_5d'] = df['RV_5d'].shift(-5)
df['fwd_RV_21d'] = df['RV_21d'].shift(-21)

# --- Proxy 1: SH/SPY Volume Ratio ---
# Interpretation: When inverse ETF gets relatively more volume, more bearish positioning
df['SH_SPY_vol_ratio'] = df['SH_Volume'] / df['SPY_Volume']
df['SH_SPY_vol_ratio_z'] = (df['SH_SPY_vol_ratio'] - df['SH_SPY_vol_ratio'].rolling(63).mean()) / df['SH_SPY_vol_ratio'].rolling(63).std()

# --- Proxy 2: SDS/SPY Volume Ratio (leveraged version) ---
df['SDS_SPY_vol_ratio'] = df['SDS_Volume'] / df['SPY_Volume']
df['SDS_SPY_vol_ratio_z'] = (df['SDS_SPY_vol_ratio'] - df['SDS_SPY_vol_ratio'].rolling(63).mean()) / df['SDS_SPY_vol_ratio'].rolling(63).std()

# --- Proxy 3: Combined Inverse Volume (SH + SDS) / SPY ---
df['inv_vol_ratio'] = (df['SH_Volume'] + df['SDS_Volume']) / df['SPY_Volume']
df['inv_vol_ratio_z'] = (df['inv_vol_ratio'] - df['inv_vol_ratio'].rolling(63).mean()) / df['inv_vol_ratio'].rolling(63).std()

# --- Proxy 4: VIX × SPY Volume composite (fear × activity) ---
df['fear_activity'] = df['VIX'] * df['SPY_Volume'] / 1e9  # scale
df['fear_activity_z'] = (df['fear_activity'] - df['fear_activity'].rolling(63).mean()) / df['fear_activity'].rolling(63).std()

# --- Proxy 5: SH volume momentum (5-day) ---
df['SH_vol_mom'] = df['SH_Volume'] / df['SH_Volume'].rolling(20).mean()

# --- Proxy 6: Days-to-cover proxy ---
# In real short interest: short shares / avg daily volume
# Proxy: inverse ETF volume persistence (rolling sum / recent average)
df['SH_vol_5d_sum'] = df['SH_Volume'].rolling(5).sum()
df['SH_vol_20d_avg'] = df['SH_Volume'].rolling(20).mean()
df['dtc_proxy'] = df['SH_vol_5d_sum'] / (df['SH_vol_20d_avg'] * 5)  # ratio of actual to expected

# Clean up
df = df.dropna(subset=['SH_SPY_vol_ratio_z', 'fwd_RV_5d', 'fwd_RV_21d', 'RV_21d'])

print(f"After proxy construction: {len(df)} observations")
print()

# Summary statistics for proxies
proxies = ['SH_SPY_vol_ratio', 'SDS_SPY_vol_ratio', 'inv_vol_ratio',
           'fear_activity', 'SH_vol_mom', 'dtc_proxy']
proxy_labels = ['SH/SPY Vol Ratio', 'SDS/SPY Vol Ratio', 'Combined Inv/SPY',
                'Fear×Activity', 'SH Vol Momentum', 'Days-to-Cover Proxy']

print("Proxy Variable Summary Statistics:")
print("-" * 80)
print(f"{'Proxy':<25s} {'Mean':>10s} {'Std':>10s} {'Min':>10s} {'Max':>10s} {'Skew':>8s}")
print("-" * 80)
for p, label in zip(proxies, proxy_labels):
    s = df[p]
    print(f"{label:<25s} {s.mean():>10.4f} {s.std():>10.4f} {s.min():>10.4f} {s.max():>10.4f} {s.skew():>8.2f}")
print()

# =============================================================================
# 3. UNCONDITIONAL CORRELATIONS
# =============================================================================
print("=" * 80)
print("SECTION 3: Unconditional Correlations with Future RV")
print("=" * 80)

z_proxies = ['SH_SPY_vol_ratio_z', 'SDS_SPY_vol_ratio_z', 'inv_vol_ratio_z',
             'fear_activity_z', 'SH_vol_mom', 'dtc_proxy']
z_labels = ['SH/SPY Ratio (z)', 'SDS/SPY Ratio (z)', 'Comb. Inv/SPY (z)',
            'Fear×Activity (z)', 'SH Vol Mom', 'DTC Proxy']

print(f"\n{'Proxy':<25s} {'r(fwd_RV5d)':>12s} {'p-value':>10s} {'r(fwd_RV21d)':>13s} {'p-value':>10s}")
print("-" * 75)

corr_results = {}
for p, label in zip(z_proxies, z_labels):
    mask5 = df[p].notna() & df['fwd_RV_5d'].notna()
    mask21 = df[p].notna() & df['fwd_RV_21d'].notna()

    r5, pv5 = stats.pearsonr(df.loc[mask5, p], df.loc[mask5, 'fwd_RV_5d'])
    r21, pv21 = stats.pearsonr(df.loc[mask21, p], df.loc[mask21, 'fwd_RV_21d'])

    sig5 = '***' if pv5 < 0.001 else '**' if pv5 < 0.01 else '*' if pv5 < 0.05 else ''
    sig21 = '***' if pv21 < 0.001 else '**' if pv21 < 0.01 else '*' if pv21 < 0.05 else ''

    print(f"{label:<25s} {r5:>10.4f}{sig5:<2s} {pv5:>10.2e} {r21:>11.4f}{sig21:<2s} {pv21:>10.2e}")
    corr_results[label] = {'r_5d': r5, 'p_5d': pv5, 'r_21d': r21, 'p_21d': pv21}

print()
print("Note: These are unconditional correlations. VIX already captures much of the")
print("fear signal. Partial correlations (controlling for VIX) are more informative.")
print()

# =============================================================================
# 4. PARTIAL CORRELATIONS (controlling for VIX)
# =============================================================================
print("=" * 80)
print("SECTION 4: Partial Correlations (controlling for VIX level)")
print("=" * 80)

def partial_corr(x, y, z):
    """Partial correlation between x and y, controlling for z."""
    mask = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    x, y, z = x[mask], y[mask], z[mask]
    n = len(x)

    # Residualize x and y on z
    slope_xz = np.polyfit(z, x, 1)
    resid_x = x - np.polyval(slope_xz, z)

    slope_yz = np.polyfit(z, y, 1)
    resid_y = y - np.polyval(slope_yz, z)

    r, p = stats.pearsonr(resid_x, resid_y)

    # Degrees of freedom for partial correlation
    t_stat = r * np.sqrt((n - 3) / (1 - r**2))
    p_adj = 2 * stats.t.sf(abs(t_stat), n - 3)

    return r, p_adj, n

print(f"\nPartial r(proxy, future_RV | VIX)")
print(f"{'Proxy':<25s} {'pr(fwd_RV5d)':>13s} {'p-value':>10s} {'pr(fwd_RV21d)':>14s} {'p-value':>10s} {'N':>6s}")
print("-" * 80)

partial_results = {}
for p, label in zip(z_proxies, z_labels):
    pr5, pp5, n5 = partial_corr(df[p].values, df['fwd_RV_5d'].values, df['VIX'].values)
    pr21, pp21, n21 = partial_corr(df[p].values, df['fwd_RV_21d'].values, df['VIX'].values)

    sig5 = '***' if pp5 < 0.001 else '**' if pp5 < 0.01 else '*' if pp5 < 0.05 else ''
    sig21 = '***' if pp21 < 0.001 else '**' if pp21 < 0.01 else '*' if pp21 < 0.05 else ''

    print(f"{label:<25s} {pr5:>11.4f}{sig5:<2s} {pp5:>10.2e} {pr21:>12.4f}{sig21:<2s} {pp21:>10.2e} {n5:>6d}")
    partial_results[label] = {'pr_5d': pr5, 'p_5d': pp5, 'pr_21d': pr21, 'p_21d': pp21, 'n': n5}

print()

# Also control for current RV (is the proxy adding info beyond momentum?)
print(f"\nPartial r(proxy, future_RV | VIX, current_RV)")
print(f"{'Proxy':<25s} {'pr(fwd_RV5d)':>13s} {'p-value':>10s} {'pr(fwd_RV21d)':>14s} {'p-value':>10s}")
print("-" * 80)

def partial_corr_multi(x, y, Z):
    """Partial correlation between x and y, controlling for multiple Z variables."""
    mask = np.isfinite(x) & np.isfinite(y)
    for z in Z:
        mask &= np.isfinite(z)
    x, y = x[mask], y[mask]
    Z_clean = [z[mask] for z in Z]
    n = len(x)

    # Residualize using OLS
    Z_mat = np.column_stack(Z_clean)
    Z_mat = np.column_stack([np.ones(n), Z_mat])

    beta_x = np.linalg.lstsq(Z_mat, x, rcond=None)[0]
    resid_x = x - Z_mat @ beta_x

    beta_y = np.linalg.lstsq(Z_mat, y, rcond=None)[0]
    resid_y = y - Z_mat @ beta_y

    r, _ = stats.pearsonr(resid_x, resid_y)
    k = len(Z)
    t_stat = r * np.sqrt((n - k - 2) / (1 - r**2))
    p = 2 * stats.t.sf(abs(t_stat), n - k - 2)

    return r, p, n

partial2_results = {}
for p, label in zip(z_proxies, z_labels):
    pr5, pp5, n5 = partial_corr_multi(
        df[p].values, df['fwd_RV_5d'].values,
        [df['VIX'].values, df['RV_21d'].values]
    )
    pr21, pp21, n21 = partial_corr_multi(
        df[p].values, df['fwd_RV_21d'].values,
        [df['VIX'].values, df['RV_21d'].values]
    )

    sig5 = '***' if pp5 < 0.001 else '**' if pp5 < 0.01 else '*' if pp5 < 0.05 else ''
    sig21 = '***' if pp21 < 0.001 else '**' if pp21 < 0.01 else '*' if pp21 < 0.05 else ''

    print(f"{label:<25s} {pr5:>11.4f}{sig5:<2s} {pp5:>10.2e} {pr21:>12.4f}{sig21:<2s} {pp21:>10.2e}")
    partial2_results[label] = {'pr_5d': pr5, 'p_5d': pp5, 'pr_21d': pr21, 'p_21d': pp21}

print()

# =============================================================================
# 5. EXTREME BEARISH POSITIONING DAYS
# =============================================================================
print("=" * 80)
print("SECTION 5: What Happens After Extreme Bearish Positioning Days?")
print("=" * 80)

# Define extreme days: SH/SPY volume ratio z-score > 2
extreme_bearish = df['SH_SPY_vol_ratio_z'] > 2.0
moderate_bearish = (df['SH_SPY_vol_ratio_z'] > 1.0) & (df['SH_SPY_vol_ratio_z'] <= 2.0)
normal = (df['SH_SPY_vol_ratio_z'] >= -1.0) & (df['SH_SPY_vol_ratio_z'] <= 1.0)

print(f"\nDay Classification (SH/SPY Volume Ratio z-score):")
print(f"  Extreme Bearish (z > 2):     {extreme_bearish.sum():>5d} days ({extreme_bearish.mean()*100:.1f}%)")
print(f"  Moderate Bearish (1 < z ≤ 2):{moderate_bearish.sum():>5d} days ({moderate_bearish.mean()*100:.1f}%)")
print(f"  Normal (-1 ≤ z ≤ 1):         {normal.sum():>5d} days ({normal.mean()*100:.1f}%)")
print()

# Forward-looking metrics after each regime
horizons = [1, 5, 10, 21]
regimes = {
    'Extreme Bearish': extreme_bearish,
    'Moderate Bearish': moderate_bearish,
    'Normal': normal,
}

print("Average Forward Realized Volatility (annualized) by Regime:")
print("-" * 80)
print(f"{'Regime':<22s}", end='')
for h in horizons:
    print(f"  {'fwd_'+str(h)+'d':>8s}", end='')
print(f"  {'N':>6s}")
print("-" * 80)

regime_fwd_rv = {}
for regime_name, regime_mask in regimes.items():
    rv_values = {}
    for h in horizons:
        fwd_rv = df['SPY_ret'].rolling(h).std().shift(-h) * np.sqrt(252)
        rv_val = fwd_rv[regime_mask].mean()
        rv_values[f'fwd_{h}d'] = rv_val

    n_obs = regime_mask.sum()
    print(f"{regime_name:<22s}", end='')
    for h in horizons:
        print(f"  {rv_values[f'fwd_{h}d']:>8.4f}", end='')
    print(f"  {n_obs:>6d}")
    regime_fwd_rv[regime_name] = rv_values

print()

# T-test: extreme vs normal
print("T-tests: Extreme Bearish vs Normal (forward RV):")
print("-" * 60)
for h in horizons:
    fwd_rv = df['SPY_ret'].rolling(h).std().shift(-h) * np.sqrt(252)
    extreme_vals = fwd_rv[extreme_bearish].dropna()
    normal_vals = fwd_rv[normal].dropna()

    t_stat, p_val = stats.ttest_ind(extreme_vals, normal_vals)
    sig = '***' if p_val < 0.001 else '**' if p_val < 0.01 else '*' if p_val < 0.05 else ''
    print(f"  {h:>2d}-day fwd RV: t = {t_stat:>7.3f}, p = {p_val:.4e} {sig}")
    print(f"    Extreme mean = {extreme_vals.mean():.4f}, Normal mean = {normal_vals.mean():.4f}")
    print(f"    Difference = {extreme_vals.mean() - normal_vals.mean():.4f} ({(extreme_vals.mean()/normal_vals.mean() - 1)*100:.1f}% higher)")

print()

# Forward returns (not just vol)
print("\nAverage Forward Returns by Regime:")
print("-" * 80)
print(f"{'Regime':<22s}", end='')
for h in horizons:
    print(f"  {'ret_'+str(h)+'d':>8s}", end='')
print()
print("-" * 80)
for regime_name, regime_mask in regimes.items():
    for h in horizons:
        fwd_ret = df['SPY_ret'].rolling(h).sum().shift(-h)
        print(f"  {fwd_ret[regime_mask].mean()*100:>7.3f}%", end='')
    print(f"  <- {regime_name}")
print()

# =============================================================================
# 6. SHORT SQUEEZE DETECTION
# =============================================================================
print("=" * 80)
print("SECTION 6: Short Squeeze Detection & Vol Signatures")
print("=" * 80)

# Define short squeeze candidates:
# SPY rises > 2% on high volume after sustained decline (5-day cumulative return < -3%)
df['cum_ret_5d'] = df['SPY_ret'].rolling(5).sum()
df['vol_z'] = (df['SPY_Volume'] - df['SPY_Volume'].rolling(20).mean()) / df['SPY_Volume'].rolling(20).std()

squeeze_candidates = (
    (df['SPY_ret'] > 0.02) &           # Big up day
    (df['vol_z'] > 1.5) &               # High volume
    (df['cum_ret_5d'].shift(1) < -0.03)  # Prior decline
)

print(f"\nShort Squeeze Candidates: {squeeze_candidates.sum()} days")
print(f"(Criteria: SPY return > 2%, volume z > 1.5, prior 5d return < -3%)")
print()

if squeeze_candidates.sum() > 0:
    squeeze_dates = df.index[squeeze_candidates]
    print("Squeeze candidate dates:")
    for d in squeeze_dates:
        ret = df.loc[d, 'SPY_ret'] * 100
        vol_z = df.loc[d, 'vol_z']
        prior = df.loc[d, 'cum_ret_5d'] * 100
        vix_level = df.loc[d, 'VIX']
        sh_ratio_z = df.loc[d, 'SH_SPY_vol_ratio_z']
        print(f"  {d.strftime('%Y-%m-%d')}: SPY +{ret:.1f}%, vol_z={vol_z:.1f}, "
              f"prior_5d={prior:.1f}%, VIX={vix_level:.1f}, SH_ratio_z={sh_ratio_z:.1f}")
    print()

    # Vol signature around squeeze events
    print("Volatility Signature Around Squeeze Events (average across events):")
    print("-" * 60)
    windows = range(-10, 11)
    print(f"{'Day':>5s}  {'Avg RV(5d)':>10s}  {'Avg |ret|':>10s}  {'Avg ret':>10s}")
    print("-" * 60)

    for w in windows:
        shifted_dates = squeeze_dates + pd.Timedelta(days=w)
        # Find closest trading days
        valid_mask = [d in df.index for d in shifted_dates]
        if sum(valid_mask) == 0:
            continue
        valid_dates = shifted_dates[valid_mask]
        rv = df.loc[valid_dates, 'RV_5d'].mean()
        abs_ret = df.loc[valid_dates, 'SPY_ret'].abs().mean() * 100
        avg_ret = df.loc[valid_dates, 'SPY_ret'].mean() * 100
        marker = ' <-- squeeze day' if w == 0 else ''
        print(f"  {w:>3d}   {rv:>10.4f}   {abs_ret:>9.3f}%   {avg_ret:>+9.3f}%{marker}")

    print()

    # Forward vol after squeeze vs normal big up days
    big_up_no_squeeze = (df['SPY_ret'] > 0.02) & (~squeeze_candidates)
    print(f"Big up days (>2%): {(df['SPY_ret'] > 0.02).sum()} total")
    print(f"  With squeeze characteristics: {squeeze_candidates.sum()}")
    print(f"  Without squeeze characteristics: {big_up_no_squeeze.sum()}")

    for h in [5, 21]:
        fwd_rv = df['SPY_ret'].rolling(h).std().shift(-h) * np.sqrt(252)
        sq_rv = fwd_rv[squeeze_candidates].mean()
        nosq_rv = fwd_rv[big_up_no_squeeze].mean()
        if squeeze_candidates.sum() >= 2:
            t, p = stats.ttest_ind(fwd_rv[squeeze_candidates].dropna(), fwd_rv[big_up_no_squeeze].dropna())
            sig = '***' if p < 0.001 else '**' if p < 0.01 else '*' if p < 0.05 else ''
            print(f"  {h}d fwd RV: squeeze={sq_rv:.4f}, no-squeeze={nosq_rv:.4f}, "
                  f"t={t:.2f}, p={p:.4f} {sig}")
        else:
            print(f"  {h}d fwd RV: squeeze={sq_rv:.4f}, no-squeeze={nosq_rv:.4f} (too few for t-test)")

print()

# =============================================================================
# 7. GAMESTOP ERA ANALYSIS (2021)
# =============================================================================
print("=" * 80)
print("SECTION 7: GameStop/Meme Stock Era — Market Structure Shift?")
print("=" * 80)

# Compare inverse ETF activity before/during/after GameStop
pre_gme = (df.index >= '2019-01-01') & (df.index < '2021-01-01')
gme_era = (df.index >= '2021-01-01') & (df.index < '2022-01-01')
post_gme = (df.index >= '2022-01-01') & (df.index < '2024-01-01')

eras = {
    'Pre-GME (2019-2020)': pre_gme,
    'GME Era (2021)': gme_era,
    'Post-GME (2022-2023)': post_gme,
}

print(f"\n{'Era':<25s} {'SH/SPY Ratio':>13s} {'SDS/SPY Ratio':>14s} {'VIX Mean':>10s} {'SPY Vol':>10s}")
print("-" * 80)
for era_name, era_mask in eras.items():
    sh_ratio = df.loc[era_mask, 'SH_SPY_vol_ratio'].mean()
    sds_ratio = df.loc[era_mask, 'SDS_SPY_vol_ratio'].mean()
    vix_mean = df.loc[era_mask, 'VIX'].mean()
    spy_vol = df.loc[era_mask, 'SPY_Volume'].mean()
    print(f"{era_name:<25s} {sh_ratio:>13.6f} {sds_ratio:>14.6f} {vix_mean:>10.2f} {spy_vol:>10.0f}")

print()

# Did the relationship between inverse ETF activity and future vol change?
print("Partial r(SH/SPY ratio, fwd_RV_21d | VIX) by Era:")
print("-" * 60)
for era_name, era_mask in eras.items():
    sub = df[era_mask].dropna(subset=['SH_SPY_vol_ratio_z', 'fwd_RV_21d', 'VIX'])
    if len(sub) > 50:
        pr, pp, n = partial_corr(sub['SH_SPY_vol_ratio_z'].values,
                                  sub['fwd_RV_21d'].values,
                                  sub['VIX'].values)
        sig = '***' if pp < 0.001 else '**' if pp < 0.01 else '*' if pp < 0.05 else ''
        print(f"  {era_name:<25s}: pr = {pr:>7.4f}, p = {pp:.4e} {sig}, N = {n}")
    else:
        print(f"  {era_name:<25s}: insufficient data")

print()

# January 2021 specifically
jan_2021 = (df.index >= '2021-01-01') & (df.index < '2021-02-01')
if jan_2021.sum() > 0:
    print(f"January 2021 (GameStop peak month):")
    jan_data = df[jan_2021]
    print(f"  Days: {len(jan_data)}")
    print(f"  Mean SH/SPY vol ratio: {jan_data['SH_SPY_vol_ratio'].mean():.6f}")
    print(f"  Max SH/SPY vol ratio z: {jan_data['SH_SPY_vol_ratio_z'].max():.2f}")
    print(f"  Mean VIX: {jan_data['VIX'].mean():.1f}")
    print(f"  SPY return: {jan_data['SPY_ret'].sum()*100:.2f}%")
    print(f"  Max daily |return|: {jan_data['SPY_ret'].abs().max()*100:.2f}%")

print()

# =============================================================================
# 8. CROSS-ASSET ANALYSIS
# =============================================================================
print("=" * 80)
print("SECTION 8: Cross-Asset Analysis — Does Bearish Proxy Predict Vol in QQQ/IWM?")
print("=" * 80)

# Use SH/SPY ratio to predict QQQ and IWM vol
for asset in ['QQQ', 'IWM']:
    fwd_rv = df[f'{asset}_ret'].rolling(21).std().shift(-21) * np.sqrt(252)
    df[f'{asset}_fwd_RV_21d'] = fwd_rv

print(f"\nPartial r(SH/SPY ratio, fwd_RV_21d | VIX) for different assets:")
print("-" * 60)
for asset in ['SPY', 'QQQ', 'IWM']:
    target = f'{asset}_fwd_RV_21d' if asset != 'SPY' else 'fwd_RV_21d'
    sub = df.dropna(subset=['SH_SPY_vol_ratio_z', target, 'VIX'])
    pr, pp, n = partial_corr(sub['SH_SPY_vol_ratio_z'].values,
                              sub[target].values,
                              sub['VIX'].values)
    sig = '***' if pp < 0.001 else '**' if pp < 0.01 else '*' if pp < 0.05 else ''
    print(f"  {asset}: pr = {pr:>7.4f}, p = {pp:.4e} {sig}, N = {n}")

print()

# =============================================================================
# 9. PREDICTIVE REGRESSION
# =============================================================================
print("=" * 80)
print("SECTION 9: Predictive Regression — Incremental R² from Short Interest Proxy")
print("=" * 80)

from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score

# Prepare data
reg_df = df[['VIX', 'RV_21d', 'SH_SPY_vol_ratio_z', 'inv_vol_ratio_z',
             'fear_activity_z', 'fwd_RV_21d']].dropna()

X_base = reg_df[['VIX', 'RV_21d']].values
y = reg_df['fwd_RV_21d'].values

# Base model: VIX + current RV
lr_base = LinearRegression().fit(X_base, y)
r2_base = r2_score(y, lr_base.predict(X_base))

print(f"\nBase model (VIX + current RV): R² = {r2_base:.4f}")
print()

# Add each proxy
proxy_cols = ['SH_SPY_vol_ratio_z', 'inv_vol_ratio_z', 'fear_activity_z']
proxy_names_reg = ['SH/SPY Ratio (z)', 'Combined Inv/SPY (z)', 'Fear×Activity (z)']

print(f"{'Model':<35s} {'R²':>8s} {'ΔR²':>8s} {'F-stat':>8s} {'p-value':>10s}")
print("-" * 75)
print(f"{'Base (VIX + RV_21d)':<35s} {r2_base:>8.4f}")

for col, name in zip(proxy_cols, proxy_names_reg):
    X_aug = np.column_stack([X_base, reg_df[col].values])
    lr_aug = LinearRegression().fit(X_aug, y)
    r2_aug = r2_score(y, lr_aug.predict(X_aug))
    delta_r2 = r2_aug - r2_base

    # F-test for nested models
    n = len(y)
    p_base = X_base.shape[1]
    p_aug = X_aug.shape[1]

    rss_base = np.sum((y - lr_base.predict(X_base))**2)
    rss_aug = np.sum((y - lr_aug.predict(X_aug))**2)

    f_stat = ((rss_base - rss_aug) / (p_aug - p_base)) / (rss_aug / (n - p_aug - 1))
    f_p = 1 - stats.f.cdf(f_stat, p_aug - p_base, n - p_aug - 1)

    sig = '***' if f_p < 0.001 else '**' if f_p < 0.01 else '*' if f_p < 0.05 else ''
    print(f"{'+ ' + name:<35s} {r2_aug:>8.4f} {delta_r2:>+8.4f} {f_stat:>8.2f} {f_p:>10.2e} {sig}")

print()

# =============================================================================
# 10. OUT-OF-SAMPLE TEST
# =============================================================================
print("=" * 80)
print("SECTION 10: Out-of-Sample Predictive Test (Rolling Window)")
print("=" * 80)

# Use expanding window, start predicting from 2015
train_start = '2007-01-01'
oos_start = '2015-01-01'

oos_df = reg_df.copy()
oos_df = oos_df.sort_index()

oos_mask = oos_df.index >= oos_start
oos_dates = oos_df.index[oos_mask]

preds_base = []
preds_aug = []
actuals = []

for i, date in enumerate(oos_dates):
    train_mask = oos_df.index < date
    if train_mask.sum() < 252:  # need at least 1 year
        continue

    train = oos_df[train_mask]
    test_row = oos_df.loc[date]

    X_train_base = train[['VIX', 'RV_21d']].values
    X_train_aug = train[['VIX', 'RV_21d', 'SH_SPY_vol_ratio_z']].values
    y_train = train['fwd_RV_21d'].values

    X_test_base = test_row[['VIX', 'RV_21d']].values.reshape(1, -1)
    X_test_aug = test_row[['VIX', 'RV_21d', 'SH_SPY_vol_ratio_z']].values.reshape(1, -1)
    y_test = test_row['fwd_RV_21d']

    lr_b = LinearRegression().fit(X_train_base, y_train)
    lr_a = LinearRegression().fit(X_train_aug, y_train)

    preds_base.append(lr_b.predict(X_test_base)[0])
    preds_aug.append(lr_a.predict(X_test_aug)[0])
    actuals.append(y_test)

preds_base = np.array(preds_base)
preds_aug = np.array(preds_aug)
actuals = np.array(actuals)

# OOS R²
ss_total = np.sum((actuals - actuals.mean())**2)
ss_res_base = np.sum((actuals - preds_base)**2)
ss_res_aug = np.sum((actuals - preds_aug)**2)

oos_r2_base = 1 - ss_res_base / ss_total
oos_r2_aug = 1 - ss_res_aug / ss_total

# OOS RMSE
rmse_base = np.sqrt(np.mean((actuals - preds_base)**2))
rmse_aug = np.sqrt(np.mean((actuals - preds_aug)**2))

# OOS MAE
mae_base = np.mean(np.abs(actuals - preds_base))
mae_aug = np.mean(np.abs(actuals - preds_aug))

print(f"\nOut-of-Sample Results ({oos_start} onwards, expanding window):")
print(f"  Number of OOS predictions: {len(actuals)}")
print(f"  OOS period: {oos_dates[0].strftime('%Y-%m-%d')} to {oos_dates[-1].strftime('%Y-%m-%d')}")
print()
print(f"{'Metric':<20s} {'Base (VIX+RV)':>15s} {'+ SH/SPY Ratio':>15s} {'Improvement':>15s}")
print("-" * 70)
print(f"{'OOS R²':<20s} {oos_r2_base:>15.4f} {oos_r2_aug:>15.4f} {oos_r2_aug-oos_r2_base:>+15.4f}")
print(f"{'RMSE':<20s} {rmse_base:>15.4f} {rmse_aug:>15.4f} {rmse_aug-rmse_base:>+15.4f}")
print(f"{'MAE':<20s} {mae_base:>15.4f} {mae_aug:>15.4f} {mae_aug-mae_base:>+15.4f}")
print()

# Diebold-Mariano test
e_base = actuals - preds_base
e_aug = actuals - preds_aug
d = e_base**2 - e_aug**2  # loss differential (positive = aug is better)
dm_stat = d.mean() / (d.std() / np.sqrt(len(d)))
dm_p = 2 * stats.norm.sf(abs(dm_stat))
sig = '***' if dm_p < 0.001 else '**' if dm_p < 0.01 else '*' if dm_p < 0.05 else ''

print(f"Diebold-Mariano test (H0: equal predictive accuracy):")
print(f"  DM statistic = {dm_stat:.4f}")
print(f"  p-value = {dm_p:.4e} {sig}")
print(f"  Interpretation: {'Aug model significantly better' if dm_p < 0.05 and dm_stat > 0 else 'Aug model significantly worse' if dm_p < 0.05 and dm_stat < 0 else 'No significant difference'}")
print()

# =============================================================================
# 11. SUB-PERIOD STABILITY
# =============================================================================
print("=" * 80)
print("SECTION 11: Sub-Period Stability — Is the Signal Consistent?")
print("=" * 80)

sub_periods = {
    '2007-2009 (GFC)': ('2007-01-01', '2009-12-31'),
    '2010-2014 (Recovery)': ('2010-01-01', '2014-12-31'),
    '2015-2019 (Bull)': ('2015-01-01', '2019-12-31'),
    '2020-2021 (COVID+Meme)': ('2020-01-01', '2021-12-31'),
    '2022-2025 (Recent)': ('2022-01-01', '2025-12-31'),
}

print(f"\nPartial r(SH/SPY ratio z, fwd_RV_21d | VIX) by sub-period:")
print("-" * 70)
print(f"{'Period':<28s} {'Partial r':>10s} {'p-value':>12s} {'N':>6s} {'Sig':>4s}")
print("-" * 70)

stability_results = {}
for period_name, (p_start, p_end) in sub_periods.items():
    sub = df[(df.index >= p_start) & (df.index <= p_end)]
    sub = sub.dropna(subset=['SH_SPY_vol_ratio_z', 'fwd_RV_21d', 'VIX'])
    if len(sub) > 50:
        pr, pp, n = partial_corr(sub['SH_SPY_vol_ratio_z'].values,
                                  sub['fwd_RV_21d'].values,
                                  sub['VIX'].values)
        sig = '***' if pp < 0.001 else '**' if pp < 0.01 else '*' if pp < 0.05 else ''
        print(f"  {period_name:<26s} {pr:>10.4f} {pp:>12.4e} {n:>6d} {sig:>4s}")
        stability_results[period_name] = {'pr': pr, 'p': pp, 'n': n}
    else:
        print(f"  {period_name:<26s} {'N/A':>10s} {'N/A':>12s} {len(sub):>6d}")

print()

# =============================================================================
# 12. HARVEY (2016) THRESHOLD CHECK
# =============================================================================
print("=" * 80)
print("SECTION 12: Harvey (2016) Multiple Testing Threshold Check")
print("=" * 80)

# For each main finding, compute t-statistic and compare to Harvey threshold of 3.0
print(f"\nHarvey (2016) threshold: |t| > 3.0 for new factors")
print(f"Number of proxies tested: 6")
print(f"Bonferroni-adjusted threshold at 5%: t > {stats.norm.ppf(1 - 0.05/(2*6)):.2f}")
print()

# Main partial correlation t-stats
print(f"{'Test':<45s} {'t-stat':>8s} {'Passes':>8s}")
print("-" * 65)

for label, res in partial_results.items():
    n = res['n']
    r = res['pr_21d']
    t = r * np.sqrt((n - 3) / (1 - r**2))
    passes = 'YES' if abs(t) > 3.0 else 'NO'
    print(f"  pr({label}, fwd_RV21d|VIX)       {t:>8.3f} {passes:>8s}")

print()

# =============================================================================
# 13. SUMMARY & CONCLUSIONS
# =============================================================================
print("=" * 80)
print("SECTION 13: Summary & Conclusions")
print("=" * 80)

print("""
EXPERIMENT K367: Short Interest as Volatility Signal
=====================================================

RESEARCH QUESTION: Does bearish positioning (proxied by inverse ETF
  volume relative to underlying) predict future realized volatility?

DATA SOURCE: yfinance (real market data)
PROXY DISCLAIMER: True short interest is published bi-weekly by FINRA/exchanges
  and is NOT available via yfinance. This experiment uses PROXY variables:
  - SH (ProShares Short S&P 500) volume / SPY volume ratio
  - SDS (ProShares UltraShort S&P 500) volume / SPY volume ratio
  - Combined inverse ETF volume ratio
  - VIX × SPY volume composite
  These proxies capture inverse ETF activity, which is correlated with but
  not identical to short interest. Key limitations:
  (1) Inverse ETFs are used by both hedgers and speculators
  (2) Institutional short selling occurs directly, not through ETFs
  (3) Options market provides alternative bearish positioning
  (4) The proxy may capture retail sentiment more than institutional positioning

KEY FINDINGS:
""")

# Dynamically summarize
best_proxy = max(partial_results.items(), key=lambda x: abs(x[1]['pr_21d']))
print(f"1. UNCONDITIONAL: Inverse ETF volume ratios show {'significant' if corr_results[list(corr_results.keys())[0]]['p_21d'] < 0.05 else 'non-significant'} correlations with future RV.")
print(f"   Best unconditional: {list(corr_results.keys())[0]}: r = {list(corr_results.values())[0]['r_21d']:.4f}")
print()

print(f"2. PARTIAL (controlling for VIX): Best proxy is {best_proxy[0]}")
print(f"   pr = {best_proxy[1]['pr_21d']:.4f} (p = {best_proxy[1]['p_21d']:.4e})")
print(f"   {'Statistically significant' if best_proxy[1]['p_21d'] < 0.05 else 'NOT statistically significant'} at 5% level")
print()

print(f"3. EXTREME BEARISH DAYS: ", end='')
if extreme_bearish.sum() > 0:
    ext_rv = df['SPY_ret'].rolling(21).std().shift(-21)[extreme_bearish].mean() * np.sqrt(252)
    nor_rv = df['SPY_ret'].rolling(21).std().shift(-21)[normal].mean() * np.sqrt(252)
    print(f"21d fwd RV = {ext_rv:.4f} vs normal {nor_rv:.4f} ({(ext_rv/nor_rv-1)*100:.1f}% higher)")
else:
    print("No extreme bearish days detected")
print()

print(f"4. OUT-OF-SAMPLE: Adding SH/SPY ratio to base model (VIX + RV):")
print(f"   OOS R² improvement: {oos_r2_aug - oos_r2_base:+.4f}")
print(f"   DM test: stat = {dm_stat:.4f}, p = {dm_p:.4e}")
print()

print(f"5. SHORT SQUEEZE EVENTS: {squeeze_candidates.sum()} detected")
print()

# Stability summary
pos_periods = sum(1 for v in stability_results.values() if v['pr'] > 0)
sig_periods = sum(1 for v in stability_results.values() if v['p'] < 0.05)
print(f"6. STABILITY: Signal positive in {pos_periods}/{len(stability_results)} sub-periods, "
      f"significant in {sig_periods}/{len(stability_results)}")
print()

# Harvey check
n_pass_harvey = sum(1 for res in partial_results.values()
                    if abs(res['pr_21d'] * np.sqrt((res['n']-3)/(1-res['pr_21d']**2))) > 3.0)
print(f"7. HARVEY (2016): {n_pass_harvey}/{len(partial_results)} proxies pass |t| > 3.0 threshold")
print()

print("OVERALL ASSESSMENT:")
if oos_r2_aug > oos_r2_base and dm_p < 0.05:
    print("  The short interest proxy adds SIGNIFICANT incremental predictive power")
    print("  beyond VIX and current RV, both in-sample and out-of-sample.")
elif oos_r2_aug > oos_r2_base:
    print("  The short interest proxy shows MARGINAL improvement in OOS prediction")
    print("  but the improvement is not statistically significant (DM test).")
elif best_proxy[1]['p_21d'] < 0.05:
    print("  The short interest proxy has SIGNIFICANT in-sample partial correlation")
    print("  but FAILS to improve OOS prediction — possible overfitting.")
else:
    print("  The short interest proxy (via inverse ETF volume) does NOT provide")
    print("  significant incremental predictive power for future volatility")
    print("  beyond what VIX already captures. The proxy may be too noisy,")
    print("  or the true short interest channel operates through institutional")
    print("  positioning that is not well-captured by retail-oriented inverse ETFs.")

print()
print("LIMITATIONS:")
print("  - Proxy, not true short interest (see disclaimer above)")
print("  - Inverse ETFs launched ~2006, limited pre-GFC data")
print("  - No options data (put/call ratio would be better proxy)")
print("  - Look-ahead bias in rolling z-score construction (mitigated by OOS test)")
print("  - Single market (US equities only)")
print()

# =============================================================================
# SAVE RESULTS
# =============================================================================
results = {
    'experiment': 'K367',
    'title': 'Short Interest as Volatility Signal',
    'data_source': 'yfinance (real market data)',
    'proxy_disclaimer': 'True short interest NOT available via yfinance. Using inverse ETF volume ratios as proxies.',
    'period': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    'n_observations': len(df),
    'unconditional_correlations': {k: {kk: float(vv) for kk, vv in v.items()} for k, v in corr_results.items()},
    'partial_correlations_given_VIX': {k: {kk: float(vv) for kk, vv in v.items()} for k, v in partial_results.items()},
    'partial_correlations_given_VIX_RV': {k: {kk: float(vv) for kk, vv in v.items()} for k, v in partial2_results.items()},
    'oos_results': {
        'base_r2': float(oos_r2_base),
        'augmented_r2': float(oos_r2_aug),
        'delta_r2': float(oos_r2_aug - oos_r2_base),
        'base_rmse': float(rmse_base),
        'augmented_rmse': float(rmse_aug),
        'dm_statistic': float(dm_stat),
        'dm_p_value': float(dm_p),
    },
    'squeeze_events': int(squeeze_candidates.sum()),
    'stability': {k: {kk: float(vv) for kk, vv in v.items()} for k, v in stability_results.items()},
    'harvey_threshold_passes': n_pass_harvey,
}

results_path = 'experiments/k367_short_interest_results.json'
with open(results_path, 'w') as f:
    json.dump(results, f, indent=2)
print(f"Results saved to {results_path}")
print()
print("=" * 80)
print("K367 COMPLETE")
print("=" * 80)
