#!/usr/bin/env python3
"""
K223: Inflation Regime and Volatility — Does CPI Predict Vol Differently Than VIX?
===================================================================================
跳躍式探索：總體經濟因子（通膨）對波動率預測的影響

研究問題：
1. 通膨預期（TIP/TLT ratio proxy）是否在 VIX 之外提供增量波動率預測資訊？
2. 通膨體制（上升 vs 下降）是否影響不同資產的波動率？
3. GLD 在通膨上升期是否提供更好的避險？
4. 50/50+VT 在不同通膨體制下表現是否不同？
5. 通膨體制對 SPY vs GLD 波動率的影響是否不對稱？

方法：
a. 通膨代理變數：TIP/TLT ratio（反映 breakeven 通膨預期）
   - Rising: 66d 趨勢上升
   - Falling: 66d 趨勢下降
b. 偏相關分析：控制 VIX 後，通膨 proxy 與未來 RV 的關聯
c. 跨資產比較：SPY vs GLD vs TLT
d. VT 策略在不同通膨體制下的績效
e. 明確聲明：TIP/TLT ratio 是通膨預期的 proxy，不是實際 CPI

數據來源：yfinance（SPY, GLD, TLT, TIP, ^VIX），2006-2024
OOS: 2023-2024

[提出: 用戶, 執行: Claude]
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
import json
import warnings
import os
from datetime import datetime

warnings.filterwarnings('ignore')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ============================================================
# 1. Data Collection
# ============================================================
print("=" * 70)
print("K223: Inflation Regime and Volatility")
print("Does Inflation Predict Vol Differently Than VIX?")
print("=" * 70)
print("\n⚠️  IMPORTANT: TIP/TLT ratio is used as a PROXY for inflation")
print("    expectations (breakeven inflation), NOT actual CPI data.")
print("    This proxy reflects market-implied inflation expectations.\n")

tickers = {
    'SPY': 'S&P 500 ETF',
    'GLD': 'Gold ETF',
    'TLT': '20+ Year Treasury Bond ETF',
    'TIP': 'TIPS ETF (inflation-protected)',
    '^VIX': 'CBOE Volatility Index',
}

print("[1] Downloading data 2006-2024...")
data = {}
for ticker, desc in tickers.items():
    try:
        df = yf.download(ticker, start='2006-01-01', end='2024-12-31',
                         progress=False, auto_adjust=True)
        if len(df) > 0:
            close = df['Close']
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            data[ticker] = close
            print(f"  {ticker}: {len(df)} days ({desc})")
        else:
            print(f"  {ticker}: NO DATA")
    except Exception as e:
        print(f"  {ticker}: ERROR - {e}")

# Align all series on common dates
common_idx = data['SPY'].index
for t in data:
    common_idx = common_idx.intersection(data[t].index)
common_idx = common_idx.sort_values()

prices = pd.DataFrame({t: data[t].reindex(common_idx) for t in data})
prices = prices.dropna()
print(f"\n  Aligned: {len(prices)} common trading days "
      f"({prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')})")

# ============================================================
# 2. Construct Variables
# ============================================================
print("\n[2] Constructing variables...")

# Returns
ret = {}
for asset in ['SPY', 'GLD', 'TLT']:
    ret[asset] = np.log(prices[asset] / prices[asset].shift(1))
ret = pd.DataFrame(ret).dropna()

# Realized volatility (22-day rolling)
rv = {}
for asset in ['SPY', 'GLD', 'TLT']:
    rv[asset] = ret[asset].rolling(22).std() * np.sqrt(252)
rv = pd.DataFrame(rv).dropna()

# Forward RV (next 22 days) — what we want to predict
fwd_rv = {}
for asset in ['SPY', 'GLD', 'TLT']:
    fwd_rv[asset] = ret[asset].rolling(22).std().shift(-22) * np.sqrt(252)
fwd_rv = pd.DataFrame(fwd_rv)

# VIX level (annualized, already in %)
vix = prices['^VIX'] / 100  # Convert to decimal for consistency

# Inflation proxy: TIP/TLT ratio
infl_ratio = prices['TIP'] / prices['TLT']
print(f"  TIP/TLT ratio range: {infl_ratio.min():.3f} to {infl_ratio.max():.3f}")

# Inflation trend (66-day = ~3 months)
TREND_WINDOW = 66
infl_change = infl_ratio - infl_ratio.shift(TREND_WINDOW)
infl_regime = pd.Series(np.where(infl_change > 0, 'rising', 'falling'),
                        index=infl_change.index)
infl_regime[infl_change.isna()] = np.nan

# Also compute z-scored inflation change for regression
infl_z = (infl_change - infl_change.rolling(252).mean()) / infl_change.rolling(252).std()

# Align everything
common = ret.index.intersection(rv.index).intersection(fwd_rv.dropna().index)
common = common.intersection(vix.dropna().index).intersection(infl_z.dropna().index)
common = common.intersection(infl_regime.dropna().index)
common = common.sort_values()

print(f"  Analysis sample: {len(common)} days "
      f"({common[0].strftime('%Y-%m-%d')} to {common[-1].strftime('%Y-%m-%d')})")

rising_days = (infl_regime.loc[common] == 'rising').sum()
falling_days = (infl_regime.loc[common] == 'falling').sum()
print(f"  Rising inflation: {rising_days} days ({100*rising_days/len(common):.1f}%)")
print(f"  Falling inflation: {falling_days} days ({100*falling_days/len(common):.1f}%)")

results = {
    'experiment': 'K223',
    'title': 'Inflation Regime and Volatility',
    'proxy_disclaimer': 'TIP/TLT ratio used as proxy for inflation expectations, NOT actual CPI',
    'data_period': f"{common[0].strftime('%Y-%m-%d')} to {common[-1].strftime('%Y-%m-%d')}",
    'n_days': len(common),
    'rising_pct': float(100 * rising_days / len(common)),
    'falling_pct': float(100 * falling_days / len(common)),
    'trend_window_days': TREND_WINDOW,
}

# ============================================================
# 3. Test 1: Partial Correlation — Inflation vs Future RV | VIX
# ============================================================
print("\n" + "=" * 70)
print("[3] TEST 1: Partial Correlation of Inflation Proxy with Future RV")
print("    (Controlling for VIX)")
print("=" * 70)

def partial_corr(x, y, z):
    """Partial correlation between x and y, controlling for z."""
    # Regress x on z, get residuals
    mask = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    x_, y_, z_ = x[mask], y[mask], z[mask]

    slope_xz, inter_xz, _, _, _ = stats.linregress(z_, x_)
    resid_x = x_ - (slope_xz * z_ + inter_xz)

    slope_yz, inter_yz, _, _, _ = stats.linregress(z_, y_)
    resid_y = y_ - (slope_yz * z_ + inter_yz)

    r, p = stats.pearsonr(resid_x, resid_y)
    n = len(x_)
    return r, p, n

print(f"\n  {'Asset':<8} {'r(infl,fwd_RV)':<18} {'r_partial|VIX':<18} {'p-value':<12} {'N':<8} {'Significant?'}")
print("  " + "-" * 75)

partial_corr_results = {}
for asset in ['SPY', 'GLD', 'TLT']:
    x = infl_z.loc[common].values
    y = fwd_rv[asset].loc[common].values
    z = vix.loc[common].values

    # Raw correlation
    mask = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    r_raw, p_raw = stats.pearsonr(x[mask], y[mask])

    # Partial correlation controlling for VIX
    r_partial, p_partial, n = partial_corr(x, y, z)

    sig = "YES***" if p_partial < 0.001 else "YES**" if p_partial < 0.01 else "YES*" if p_partial < 0.05 else "NO"
    print(f"  {asset:<8} {r_raw:>+.4f} (p={p_raw:.4f})  {r_partial:>+.4f}            {p_partial:<12.6f} {n:<8} {sig}")

    partial_corr_results[asset] = {
        'r_raw': float(r_raw),
        'p_raw': float(p_raw),
        'r_partial_controlling_vix': float(r_partial),
        'p_partial': float(p_partial),
        'n': int(n),
        'significant_0.05': p_partial < 0.05,
    }

results['test1_partial_correlation'] = partial_corr_results

# ============================================================
# 4. Test 2: Inflation Regime → Vol Level (Rising vs Falling)
# ============================================================
print("\n" + "=" * 70)
print("[4] TEST 2: Volatility Levels by Inflation Regime")
print("=" * 70)

regime_vol_results = {}
for asset in ['SPY', 'GLD', 'TLT']:
    rv_asset = rv[asset].loc[common]
    regime = infl_regime.loc[common]

    rv_rising = rv_asset[regime == 'rising']
    rv_falling = rv_asset[regime == 'falling']

    # Two-sample t-test
    t_stat, p_val = stats.ttest_ind(rv_rising.dropna(), rv_falling.dropna())

    # Mann-Whitney U test (non-parametric)
    u_stat, p_mw = stats.mannwhitneyu(rv_rising.dropna(), rv_falling.dropna(), alternative='two-sided')

    print(f"\n  {asset}:")
    print(f"    Rising inflation:  mean RV = {rv_rising.mean():.4f} (σ={rv_rising.std():.4f}, N={len(rv_rising.dropna())})")
    print(f"    Falling inflation: mean RV = {rv_falling.mean():.4f} (σ={rv_falling.std():.4f}, N={len(rv_falling.dropna())})")
    print(f"    Difference: {rv_rising.mean() - rv_falling.mean():+.4f}")
    print(f"    t-test: t={t_stat:.3f}, p={p_val:.4f} {'***' if p_val<0.001 else '**' if p_val<0.01 else '*' if p_val<0.05 else ''}")
    print(f"    Mann-Whitney: U={u_stat:.0f}, p={p_mw:.4f} {'***' if p_mw<0.001 else '**' if p_mw<0.01 else '*' if p_mw<0.05 else ''}")

    regime_vol_results[asset] = {
        'rv_rising_mean': float(rv_rising.mean()),
        'rv_rising_std': float(rv_rising.std()),
        'rv_falling_mean': float(rv_falling.mean()),
        'rv_falling_std': float(rv_falling.std()),
        'diff': float(rv_rising.mean() - rv_falling.mean()),
        't_stat': float(t_stat),
        'p_ttest': float(p_val),
        'p_mannwhitney': float(p_mw),
    }

results['test2_regime_vol_levels'] = regime_vol_results

# ============================================================
# 5. Test 3: Asset-specific — Inflation affects GLD vol differently?
# ============================================================
print("\n" + "=" * 70)
print("[5] TEST 3: Regression — Inflation Proxy → Future RV (asset-specific)")
print("    Model: FWD_RV = a + b1*VIX + b2*INFL_Z + b3*VIX*INFL_Z + e")
print("=" * 70)

regression_results = {}
for asset in ['SPY', 'GLD', 'TLT']:
    y = fwd_rv[asset].loc[common].values
    x_vix = vix.loc[common].values
    x_infl = infl_z.loc[common].values
    x_interact = x_vix * x_infl

    mask = np.isfinite(y) & np.isfinite(x_vix) & np.isfinite(x_infl)
    y_, vix_, infl_, inter_ = y[mask], x_vix[mask], x_infl[mask], x_interact[mask]

    # Full model: FWD_RV = a + b1*VIX + b2*INFL + b3*VIX*INFL
    X = np.column_stack([np.ones(len(y_)), vix_, infl_, inter_])
    betas, residuals, rank, sv = np.linalg.lstsq(X, y_, rcond=None)

    y_hat = X @ betas
    ss_res = np.sum((y_ - y_hat) ** 2)
    ss_tot = np.sum((y_ - np.mean(y_)) ** 2)
    r2_full = 1 - ss_res / ss_tot

    # VIX-only model for comparison
    X_vix = np.column_stack([np.ones(len(y_)), vix_])
    betas_vix, _, _, _ = np.linalg.lstsq(X_vix, y_, rcond=None)
    y_hat_vix = X_vix @ betas_vix
    ss_res_vix = np.sum((y_ - y_hat_vix) ** 2)
    r2_vix = 1 - ss_res_vix / ss_tot

    # Incremental R² from inflation
    delta_r2 = r2_full - r2_vix

    # F-test for incremental R² (2 additional regressors: infl + interaction)
    n = len(y_)
    k_full = 4  # intercept + VIX + infl + interaction
    k_restricted = 2  # intercept + VIX
    df_num = k_full - k_restricted
    df_den = n - k_full
    f_stat = ((ss_res_vix - ss_res) / df_num) / (ss_res / df_den)
    p_f = 1 - stats.f.cdf(f_stat, df_num, df_den)

    # Standard errors for coefficients
    mse = ss_res / (n - k_full)
    var_betas = mse * np.linalg.inv(X.T @ X).diagonal()
    se_betas = np.sqrt(np.abs(var_betas))
    t_stats = betas / se_betas
    p_vals = 2 * (1 - stats.t.cdf(np.abs(t_stats), n - k_full))

    print(f"\n  {asset}:")
    print(f"    R² (VIX only):       {r2_vix:.4f}")
    print(f"    R² (VIX + inflation): {r2_full:.4f}")
    print(f"    ΔR² from inflation:   {delta_r2:.4f} (F={f_stat:.2f}, p={p_f:.4f})")
    print(f"    Coefficients:")
    labels = ['Intercept', 'VIX', 'Infl_Z', 'VIX×Infl']
    for i, lab in enumerate(labels):
        sig = '***' if p_vals[i] < 0.001 else '**' if p_vals[i] < 0.01 else '*' if p_vals[i] < 0.05 else ''
        print(f"      {lab:<12}: β={betas[i]:>+.6f}, SE={se_betas[i]:.6f}, t={t_stats[i]:>+.3f}, p={p_vals[i]:.4f} {sig}")

    regression_results[asset] = {
        'r2_vix_only': float(r2_vix),
        'r2_full': float(r2_full),
        'delta_r2': float(delta_r2),
        'f_stat': float(f_stat),
        'p_f_test': float(p_f),
        'betas': {lab: float(betas[i]) for i, lab in enumerate(labels)},
        't_stats': {lab: float(t_stats[i]) for i, lab in enumerate(labels)},
        'p_values': {lab: float(p_vals[i]) for i, lab in enumerate(labels)},
        'n': int(n),
        'significant_incremental': p_f < 0.05,
    }

results['test3_regression'] = regression_results

# ============================================================
# 6. Test 4: VT Performance by Inflation Regime
# ============================================================
print("\n" + "=" * 70)
print("[6] TEST 4: 50/50 SPY/GLD + 12/VIX VT in Different Inflation Regimes")
print("=" * 70)

# Implement 50/50 SPY/GLD with 12/VIX VT (lagged weights)
spy_ret = ret['SPY'].loc[common]
gld_ret = ret['GLD'].loc[common]
vix_common = prices['^VIX'].loc[common]
regime_common = infl_regime.loc[common]

# VT weight: min(12/VIX, 1.0), using previous day's VIX
vt_weight = np.minimum(12.0 / vix_common.shift(1), 1.0)
vt_weight = vt_weight.clip(0, 1)

# Portfolio returns
port_bh = 0.5 * spy_ret + 0.5 * gld_ret  # buy & hold
port_vt = vt_weight * (0.5 * spy_ret + 0.5 * gld_ret)  # VT-scaled
# Cash return during VT reduction (simplified as 0)
port_vt = port_vt.dropna()

# Split by regime
rising_mask = regime_common == 'rising'
falling_mask = regime_common == 'falling'

def calc_perf(returns, label):
    """Calculate performance metrics for a return series."""
    r = returns.dropna()
    if len(r) < 22:
        return None
    ann_ret = r.mean() * 252
    ann_vol = r.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # Max drawdown
    cum = (1 + r).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    return {
        'label': label,
        'n_days': int(len(r)),
        'ann_return': float(ann_ret),
        'ann_vol': float(ann_vol),
        'sharpe': float(sharpe),
        'mdd': float(mdd),
    }

print(f"\n  {'Strategy':<25} {'Regime':<10} {'Ann Ret':<10} {'Ann Vol':<10} {'Sharpe':<10} {'MDD':<10} {'N days'}")
print("  " + "-" * 85)

vt_regime_results = {}
for strat_name, strat_ret in [('50/50 B&H', port_bh), ('50/50 + VT', port_vt)]:
    for regime_name, mask in [('Rising', rising_mask), ('Falling', falling_mask), ('All', pd.Series(True, index=common))]:
        r = strat_ret[mask].dropna()
        perf = calc_perf(r, f"{strat_name} ({regime_name})")
        if perf:
            print(f"  {perf['label']:<25} {regime_name:<10} {perf['ann_return']:>+.4f}    {perf['ann_vol']:>.4f}    {perf['sharpe']:>+.3f}     {perf['mdd']:>+.4f}   {perf['n_days']}")
            vt_regime_results[f"{strat_name}_{regime_name}"] = perf

# Difference-in-differences: VT improvement in rising vs falling
vt_sharpe_rising = vt_regime_results.get('50/50 + VT_Rising', {}).get('sharpe', 0)
bh_sharpe_rising = vt_regime_results.get('50/50 B&H_Rising', {}).get('sharpe', 0)
vt_sharpe_falling = vt_regime_results.get('50/50 + VT_Falling', {}).get('sharpe', 0)
bh_sharpe_falling = vt_regime_results.get('50/50 B&H_Falling', {}).get('sharpe', 0)

vt_improvement_rising = vt_sharpe_rising - bh_sharpe_rising
vt_improvement_falling = vt_sharpe_falling - bh_sharpe_falling
did = vt_improvement_rising - vt_improvement_falling

print(f"\n  VT Sharpe improvement (rising):  {vt_improvement_rising:+.4f}")
print(f"  VT Sharpe improvement (falling): {vt_improvement_falling:+.4f}")
print(f"  Difference-in-differences:       {did:+.4f}")

vt_regime_results['did_sharpe'] = {
    'vt_improvement_rising': float(vt_improvement_rising),
    'vt_improvement_falling': float(vt_improvement_falling),
    'did': float(did),
}

results['test4_vt_by_regime'] = vt_regime_results

# ============================================================
# 7. Test 5: GLD as Inflation Hedge — Regime-Conditional Analysis
# ============================================================
print("\n" + "=" * 70)
print("[7] TEST 5: GLD as Inflation Hedge — Performance by Regime")
print("=" * 70)

# GLD performance by inflation regime
gld_rising = ret['GLD'].loc[common][rising_mask].dropna()
gld_falling = ret['GLD'].loc[common][falling_mask].dropna()

# SPY-GLD correlation by regime
spy_gld_rising = ret[['SPY', 'GLD']].loc[common][rising_mask].dropna()
spy_gld_falling = ret[['SPY', 'GLD']].loc[common][falling_mask].dropna()

corr_rising = spy_gld_rising['SPY'].corr(spy_gld_rising['GLD'])
corr_falling = spy_gld_falling['SPY'].corr(spy_gld_falling['GLD'])

# Fisher z-test for correlation difference
def fisher_z_test(r1, n1, r2, n2):
    """Test if two correlations are significantly different."""
    z1 = 0.5 * np.log((1 + r1) / (1 - r1))
    z2 = 0.5 * np.log((1 + r2) / (1 - r2))
    se = np.sqrt(1/(n1-3) + 1/(n2-3))
    z = (z1 - z2) / se
    p = 2 * (1 - stats.norm.cdf(np.abs(z)))
    return z, p

z_corr, p_corr = fisher_z_test(corr_rising, len(spy_gld_rising),
                                 corr_falling, len(spy_gld_falling))

gld_perf_rising = calc_perf(gld_rising, 'GLD Rising')
gld_perf_falling = calc_perf(gld_falling, 'GLD Falling')

print(f"\n  GLD Performance:")
print(f"    Rising inflation:  Ann Ret = {gld_perf_rising['ann_return']:+.4f}, Vol = {gld_perf_rising['ann_vol']:.4f}, Sharpe = {gld_perf_rising['sharpe']:+.3f}")
print(f"    Falling inflation: Ann Ret = {gld_perf_falling['ann_return']:+.4f}, Vol = {gld_perf_falling['ann_vol']:.4f}, Sharpe = {gld_perf_falling['sharpe']:+.3f}")
print(f"\n  SPY-GLD Correlation:")
print(f"    Rising inflation:  ρ = {corr_rising:+.4f}")
print(f"    Falling inflation: ρ = {corr_falling:+.4f}")
print(f"    Fisher z-test: z = {z_corr:.3f}, p = {p_corr:.4f} {'***' if p_corr<0.001 else '**' if p_corr<0.01 else '*' if p_corr<0.05 else ''}")
print(f"    → {'Correlation differs significantly' if p_corr < 0.05 else 'No significant difference in correlation'} across regimes")

# TLT-GLD correlation by regime (bond-gold relationship)
tlt_gld_rising = ret[['TLT', 'GLD']].loc[common][rising_mask].dropna()
tlt_gld_falling = ret[['TLT', 'GLD']].loc[common][falling_mask].dropna()

corr_tlt_gld_rising = tlt_gld_rising['TLT'].corr(tlt_gld_rising['GLD'])
corr_tlt_gld_falling = tlt_gld_falling['TLT'].corr(tlt_gld_falling['GLD'])

z_tlt_gld, p_tlt_gld = fisher_z_test(corr_tlt_gld_rising, len(tlt_gld_rising),
                                        corr_tlt_gld_falling, len(tlt_gld_falling))

print(f"\n  TLT-GLD Correlation:")
print(f"    Rising inflation:  ρ = {corr_tlt_gld_rising:+.4f}")
print(f"    Falling inflation: ρ = {corr_tlt_gld_falling:+.4f}")
print(f"    Fisher z-test: z = {z_tlt_gld:.3f}, p = {p_tlt_gld:.4f} {'***' if p_tlt_gld<0.001 else '**' if p_tlt_gld<0.01 else '*' if p_tlt_gld<0.05 else ''}")

results['test5_gld_inflation_hedge'] = {
    'gld_rising': gld_perf_rising,
    'gld_falling': gld_perf_falling,
    'spy_gld_corr_rising': float(corr_rising),
    'spy_gld_corr_falling': float(corr_falling),
    'spy_gld_corr_fisher_z': float(z_corr),
    'spy_gld_corr_fisher_p': float(p_corr),
    'tlt_gld_corr_rising': float(corr_tlt_gld_rising),
    'tlt_gld_corr_falling': float(corr_tlt_gld_falling),
    'tlt_gld_corr_fisher_z': float(z_tlt_gld),
    'tlt_gld_corr_fisher_p': float(p_tlt_gld),
}

# ============================================================
# 8. Test 6: OOS Validation (2023-2024)
# ============================================================
print("\n" + "=" * 70)
print("[8] TEST 6: Out-of-Sample Validation (2023-2024)")
print("=" * 70)

oos_start = '2023-01-01'
oos_mask = common >= pd.Timestamp(oos_start)
is_mask = common < pd.Timestamp(oos_start)

print(f"  In-sample:  {is_mask.sum()} days (before {oos_start})")
print(f"  Out-of-sample: {oos_mask.sum()} days (from {oos_start})")

oos_results = {}
for asset in ['SPY', 'GLD', 'TLT']:
    # IS partial correlation
    x_is = infl_z.loc[common[is_mask]].values
    y_is = fwd_rv[asset].loc[common[is_mask]].values
    z_is = vix.loc[common[is_mask]].values
    r_is, p_is, n_is = partial_corr(x_is, y_is, z_is)

    # OOS partial correlation
    x_oos = infl_z.loc[common[oos_mask]].values
    y_oos = fwd_rv[asset].loc[common[oos_mask]].values
    z_oos = vix.loc[common[oos_mask]].values
    r_oos, p_oos, n_oos = partial_corr(x_oos, y_oos, z_oos)

    print(f"\n  {asset}:")
    print(f"    IS  partial corr: r = {r_is:+.4f} (p={p_is:.4f}, N={n_is})")
    print(f"    OOS partial corr: r = {r_oos:+.4f} (p={p_oos:.4f}, N={n_oos})")
    print(f"    OOS/IS ratio: {abs(r_oos)/abs(r_is):.2f}" if abs(r_is) > 0.001 else "    OOS/IS ratio: N/A")

    oos_results[asset] = {
        'is_r': float(r_is),
        'is_p': float(p_is),
        'is_n': int(n_is),
        'oos_r': float(r_oos),
        'oos_p': float(p_oos),
        'oos_n': int(n_oos),
        'oos_is_ratio': float(abs(r_oos) / abs(r_is)) if abs(r_is) > 0.001 else None,
    }

results['test6_oos_validation'] = oos_results

# ============================================================
# 9. Test 7: Rolling Inflation Regime Analysis (2022-2023 Focus)
# ============================================================
print("\n" + "=" * 70)
print("[9] TEST 7: 2022-2023 Inflation Episode Analysis")
print("=" * 70)

# Focus on 2022-2023: high inflation period
crisis_start = '2022-01-01'
crisis_end = '2023-12-31'
crisis_mask = (common >= pd.Timestamp(crisis_start)) & (common <= pd.Timestamp(crisis_end))

# Pre-crisis: 2019-2021
pre_start = '2019-01-01'
pre_end = '2021-12-31'
pre_mask = (common >= pd.Timestamp(pre_start)) & (common <= pd.Timestamp(pre_end))

print(f"\n  Pre-inflation (2019-2021): {pre_mask.sum()} days")
print(f"  High inflation (2022-2023): {crisis_mask.sum()} days")

episode_results = {}
for period_name, mask in [('Pre (2019-2021)', pre_mask), ('High (2022-2023)', crisis_mask)]:
    period_days = common[mask]
    if len(period_days) == 0:
        continue

    # Avg TIP/TLT ratio
    avg_ratio = infl_ratio.loc[period_days].mean()

    # Asset volatilities
    spy_vol = ret['SPY'].loc[period_days].std() * np.sqrt(252)
    gld_vol = ret['GLD'].loc[period_days].std() * np.sqrt(252)
    tlt_vol = ret['TLT'].loc[period_days].std() * np.sqrt(252)

    # SPY-GLD correlation
    corr_sg = ret['SPY'].loc[period_days].corr(ret['GLD'].loc[period_days])
    # SPY-TLT correlation
    corr_st = ret['SPY'].loc[period_days].corr(ret['TLT'].loc[period_days])
    # GLD-TLT correlation
    corr_gt = ret['GLD'].loc[period_days].corr(ret['TLT'].loc[period_days])

    # VT portfolio performance
    port_vt_period = port_vt.loc[port_vt.index.isin(period_days)].dropna()
    port_bh_period = port_bh.loc[port_bh.index.isin(period_days)].dropna()

    vt_perf = calc_perf(port_vt_period, f'VT {period_name}')
    bh_perf = calc_perf(port_bh_period, f'B&H {period_name}')

    print(f"\n  {period_name}:")
    print(f"    Avg TIP/TLT ratio: {avg_ratio:.4f}")
    print(f"    Volatilities: SPY={spy_vol:.4f}, GLD={gld_vol:.4f}, TLT={tlt_vol:.4f}")
    print(f"    Correlations: SPY-GLD={corr_sg:+.3f}, SPY-TLT={corr_st:+.3f}, GLD-TLT={corr_gt:+.3f}")
    if bh_perf and vt_perf:
        print(f"    50/50 B&H: Sharpe={bh_perf['sharpe']:+.3f}, MDD={bh_perf['mdd']:+.4f}")
        print(f"    50/50 VT:  Sharpe={vt_perf['sharpe']:+.3f}, MDD={vt_perf['mdd']:+.4f}")

    episode_results[period_name] = {
        'avg_tip_tlt_ratio': float(avg_ratio),
        'spy_vol': float(spy_vol),
        'gld_vol': float(gld_vol),
        'tlt_vol': float(tlt_vol),
        'corr_spy_gld': float(corr_sg),
        'corr_spy_tlt': float(corr_st),
        'corr_gld_tlt': float(corr_gt),
        'vt_perf': vt_perf,
        'bh_perf': bh_perf,
    }

# Key finding: SPY-TLT correlation breakdown
print(f"\n  ★ KEY: SPY-TLT correlation shift:")
pre_corr_st = episode_results.get('Pre (2019-2021)', {}).get('corr_spy_tlt', 0)
crisis_corr_st = episode_results.get('High (2022-2023)', {}).get('corr_spy_tlt', 0)
print(f"    Pre-inflation: ρ(SPY,TLT) = {pre_corr_st:+.3f}")
print(f"    High inflation: ρ(SPY,TLT) = {crisis_corr_st:+.3f}")
print(f"    Change: {crisis_corr_st - pre_corr_st:+.3f}")

if pre_corr_st < 0 and crisis_corr_st > 0:
    print("    → CORRELATION BREAKDOWN: bonds no longer hedging equities during high inflation!")
elif crisis_corr_st > pre_corr_st:
    print("    → Correlation moved more positive during high inflation")
else:
    print("    → No clear breakdown pattern")

results['test7_2022_2023_episode'] = episode_results

# ============================================================
# 10. Test 8: Granger Causality — Inflation → Vol
# ============================================================
print("\n" + "=" * 70)
print("[10] TEST 8: Granger Causality — Inflation Change → Future Volatility")
print("=" * 70)

granger_results = {}
for asset in ['SPY', 'GLD', 'TLT']:
    # Prepare series: weekly frequency to reduce autocorrelation
    weekly_rv = rv[asset].loc[common].resample('W').last().dropna()
    weekly_infl = infl_change.loc[common].resample('W').last().dropna()
    weekly_vix = vix.loc[common].resample('W').last().dropna()

    # Align
    w_idx = weekly_rv.index.intersection(weekly_infl.index).intersection(weekly_vix.index)
    w_rv = weekly_rv.loc[w_idx].values
    w_infl = weekly_infl.loc[w_idx].values
    w_vix = weekly_vix.loc[w_idx].values

    # Granger test: Does adding lagged inflation improve vol prediction beyond lagged vol + VIX?
    # Restricted: RV_t = a + b1*RV_{t-1} + b2*VIX_{t-1}
    # Unrestricted: RV_t = a + b1*RV_{t-1} + b2*VIX_{t-1} + b3*INFL_{t-1} + b4*INFL_{t-2}

    n_lags = 2
    valid = slice(n_lags, None)
    y = w_rv[valid]

    # Restricted model
    X_r = np.column_stack([
        np.ones(len(y)),
        w_rv[n_lags-1:-1],   # RV_{t-1}
        w_vix[n_lags-1:-1],  # VIX_{t-1}
    ])

    # Unrestricted model
    X_u = np.column_stack([
        np.ones(len(y)),
        w_rv[n_lags-1:-1],
        w_vix[n_lags-1:-1],
        w_infl[n_lags-1:-1],  # INFL_{t-1}
        w_infl[n_lags-2:-2],  # INFL_{t-2}
    ])

    # Fit both
    mask = np.all(np.isfinite(X_u), axis=1) & np.isfinite(y)
    y_ = y[mask]
    X_r_ = X_r[mask]
    X_u_ = X_u[mask]

    b_r, _, _, _ = np.linalg.lstsq(X_r_, y_, rcond=None)
    b_u, _, _, _ = np.linalg.lstsq(X_u_, y_, rcond=None)

    ss_r = np.sum((y_ - X_r_ @ b_r) ** 2)
    ss_u = np.sum((y_ - X_u_ @ b_u) ** 2)

    n = len(y_)
    k_r = X_r_.shape[1]
    k_u = X_u_.shape[1]
    df_num = k_u - k_r
    df_den = n - k_u

    f_stat = ((ss_r - ss_u) / df_num) / (ss_u / df_den)
    p_granger = 1 - stats.f.cdf(f_stat, df_num, df_den)

    sig = '***' if p_granger < 0.001 else '**' if p_granger < 0.01 else '*' if p_granger < 0.05 else ''
    print(f"\n  {asset}:")
    print(f"    Granger F-test (inflation → vol | VIX): F={f_stat:.3f}, p={p_granger:.4f} {sig}")
    print(f"    N weeks = {n}, lags = {n_lags}")
    print(f"    → {'Inflation Granger-causes vol beyond VIX' if p_granger < 0.05 else 'Inflation does NOT Granger-cause vol beyond VIX'}")

    granger_results[asset] = {
        'f_stat': float(f_stat),
        'p_granger': float(p_granger),
        'n_weeks': int(n),
        'n_lags': n_lags,
        'significant_0.05': p_granger < 0.05,
    }

results['test8_granger_causality'] = granger_results

# ============================================================
# 11. Summary
# ============================================================
print("\n" + "=" * 70)
print("[11] SUMMARY OF FINDINGS")
print("=" * 70)

print("""
K223: Inflation Regime and Volatility — Summary
================================================

⚠️  PROXY LIMITATION: All results use TIP/TLT ratio as a market-based
    proxy for inflation expectations, not actual CPI data. This proxy
    reflects breakeven inflation implied by TIPS vs nominal Treasury
    bond prices.

Test 1 (Partial Correlation):
  - After controlling for VIX, does inflation proxy predict future RV?
""")

for asset in ['SPY', 'GLD', 'TLT']:
    pc = partial_corr_results[asset]
    print(f"    {asset}: r_partial = {pc['r_partial_controlling_vix']:+.4f} (p={pc['p_partial']:.4f}) → {'YES' if pc['significant_0.05'] else 'NO'}")

print(f"""
Test 2 (Vol by Regime):
  - Is volatility higher during rising vs falling inflation?""")
for asset in ['SPY', 'GLD', 'TLT']:
    rv_r = regime_vol_results[asset]
    print(f"    {asset}: Rising={rv_r['rv_rising_mean']:.4f} vs Falling={rv_r['rv_falling_mean']:.4f} (p={rv_r['p_ttest']:.4f})")

print(f"""
Test 3 (Regression ΔR²):
  - Does inflation add to VIX-only model for predicting future RV?""")
for asset in ['SPY', 'GLD', 'TLT']:
    rr = regression_results[asset]
    print(f"    {asset}: ΔR² = {rr['delta_r2']:.4f} (p={rr['p_f_test']:.4f}) → {'YES' if rr['significant_incremental'] else 'NO'}")

print(f"""
Test 4 (VT by Regime):
  - VT Sharpe improvement: Rising = {vt_improvement_rising:+.4f}, Falling = {vt_improvement_falling:+.4f}
  - Difference-in-differences = {did:+.4f}

Test 5 (GLD Inflation Hedge):
  - GLD Sharpe: Rising = {results['test5_gld_inflation_hedge']['gld_rising']['sharpe']:+.3f}, Falling = {results['test5_gld_inflation_hedge']['gld_falling']['sharpe']:+.3f}
  - SPY-GLD corr: Rising = {corr_rising:+.3f}, Falling = {corr_falling:+.3f} (Fisher p={p_corr:.4f})

Test 8 (Granger Causality):
  - Does inflation Granger-cause vol beyond VIX?""")
for asset in ['SPY', 'GLD', 'TLT']:
    gr = granger_results[asset]
    print(f"    {asset}: F={gr['f_stat']:.3f}, p={gr['p_granger']:.4f} → {'YES' if gr['significant_0.05'] else 'NO'}")

# Determine overall conclusion
any_partial_sig = any(partial_corr_results[a]['significant_0.05'] for a in ['SPY', 'GLD', 'TLT'])
any_regression_sig = any(regression_results[a]['significant_incremental'] for a in ['SPY', 'GLD', 'TLT'])
any_granger_sig = any(granger_results[a]['significant_0.05'] for a in ['SPY', 'GLD', 'TLT'])

overall = "MIXED" if (any_partial_sig or any_regression_sig or any_granger_sig) else "NULL"

if overall == "NULL":
    print("""
★ OVERALL CONCLUSION: NULL — Inflation proxy (TIP/TLT ratio) does NOT
  provide significant incremental vol prediction beyond VIX.
  This reinforces the VIX sufficient statistic finding (J3/J4/etc.).
  VIX already captures inflation-related vol expectations.""")
else:
    sig_count = sum([any_partial_sig, any_regression_sig, any_granger_sig])
    print(f"""
★ OVERALL CONCLUSION: MIXED — Some evidence ({sig_count}/3 test families significant)
  that inflation proxy has incremental information beyond VIX, but
  economic significance needs further investigation.""")

results['summary'] = {
    'overall_conclusion': overall,
    'any_partial_corr_significant': any_partial_sig,
    'any_regression_significant': any_regression_sig,
    'any_granger_significant': any_granger_sig,
    'vix_sufficient_statistic_reinforced': overall == "NULL",
    'proxy_disclaimer': 'TIP/TLT ratio is a proxy, not actual CPI. Results should be interpreted accordingly.',
}

# ============================================================
# Save results
# ============================================================
output_path = os.path.join(BASE_DIR, 'experiments', 'k223_inflation_regime_results.json')
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\n  Results saved to: {output_path}")

print("\n" + "=" * 70)
print("K223 COMPLETE")
print("=" * 70)
