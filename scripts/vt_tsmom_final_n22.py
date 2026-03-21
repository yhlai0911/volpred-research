#!/usr/bin/env python3
"""
K55: Final VT-TSMOM Cross-Sectional Analysis (N=22)
====================================================
Expand K53 (N=15) by adding 7 new assets:
  EWJ, EWG, EWU, EWA, INDA, VNQ, SLV

For each new asset:
  1. Estimate GJR-GARCH → extract gamma
  2. Construct 12/VIX VT (monthly, lagged)
  3. Run: VT_excess = α + β₁×MKT + β₂×TSMOM_orth + ε (Newey-West HAC)
  4. Use contemporaneous T-bill (^IRX) as risk-free

Then combine with K53's 15 assets for N=22 cross-sectional analysis.
"""

import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats
from datetime import datetime

warnings.filterwarnings('ignore')

# ── Configuration ──
NEW_TICKERS = ['EWJ', 'EWG', 'EWU', 'EWA', 'INDA', 'VNQ', 'SLV']
ASSET_CLASS_MAP = {
    'EWJ': 'equity', 'EWG': 'equity', 'EWU': 'equity',
    'EWA': 'equity', 'INDA': 'equity',
    'VNQ': 'non_equity',  # Real Estate
    'SLV': 'non_equity',  # Commodity (Silver)
}
START_DATE = '2007-01-01'
END_DATE = '2026-03-20'
VIX_THRESHOLD = 12.0
TSMOM_LOOKBACK = 252
K53_PATH = '/Users/yhlai0911/Desktop/volpred-research/storage/experiments/vt_tsmom_expanded.json'
OUTPUT_PATH = '/Users/yhlai0911/Desktop/volpred-research/storage/experiments/vt_tsmom_final_n22.json'


def download_data():
    """Download all needed data."""
    print("=== 下載資料 ===")

    # Download new tickers
    prices = {}
    for ticker in NEW_TICKERS:
        df = yf.download(ticker, start=START_DATE, end=END_DATE, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        prices[ticker] = df['Close'].dropna()
        print(f"  {ticker}: {len(prices[ticker])} 天")

    # Download VIX and IRX
    vix_df = yf.download('^VIX', start=START_DATE, end=END_DATE, progress=False)
    if isinstance(vix_df.columns, pd.MultiIndex):
        vix_df.columns = vix_df.columns.get_level_values(0)
    vix = vix_df['Close'].dropna()
    print(f"  VIX: {len(vix)} 天")

    irx_df = yf.download('^IRX', start=START_DATE, end=END_DATE, progress=False)
    if isinstance(irx_df.columns, pd.MultiIndex):
        irx_df.columns = irx_df.columns.get_level_values(0)
    irx = irx_df['Close'].dropna()
    print(f"  IRX: {len(irx)} 天")

    # Download SPY for MKT factor
    spy_df = yf.download('SPY', start=START_DATE, end=END_DATE, progress=False)
    if isinstance(spy_df.columns, pd.MultiIndex):
        spy_df.columns = spy_df.columns.get_level_values(0)
    spy = spy_df['Close'].dropna()
    print(f"  SPY (MKT): {len(spy)} 天")

    return prices, vix, irx, spy


def estimate_gjr_gamma(returns_pct):
    """Estimate GJR-GARCH(1,1) and return gamma coefficient."""
    try:
        model = arch_model(returns_pct, vol='GARCH', p=1, o=1, q=1, dist='normal', mean='Constant')
        result = model.fit(disp='off', show_warning=False)
        gamma = result.params.get('gamma[1]', 0.0)
        return gamma
    except Exception as e:
        print(f"  GJR-GARCH estimation failed: {e}")
        return np.nan


def construct_vt_returns(price_series, vix, irx, threshold=12.0):
    """
    Construct 12/VIX monthly-rebalanced VT strategy returns.
    Uses lagged VIX (month-end VIX determines next month's weight).
    Returns daily excess returns for VT and Buy-Hold.
    """
    ret = price_series.pct_change().dropna()

    # Align all series
    common_idx = ret.index.intersection(vix.index).intersection(irx.index)
    ret = ret.loc[common_idx]
    vix_aligned = vix.loc[common_idx]
    irx_aligned = irx.loc[common_idx]

    # Daily risk-free rate from IRX (annualized %, convert to daily)
    rf_daily = (irx_aligned / 100) / 252

    # Monthly rebalance with lagged VIX
    # Get month-end VIX for next month's weight
    vix_monthly = vix_aligned.resample('ME').last()
    weight_monthly = (threshold / vix_monthly).clip(0, 1)

    # Map weights to daily: each day uses previous month-end's weight
    weight_daily = weight_monthly.reindex(ret.index, method='ffill')
    # Shift by 1 to ensure lagged (month M's VIX → month M+1's weight)
    weight_daily = weight_daily.shift(1)

    # Drop NaN rows
    valid = weight_daily.dropna().index
    ret = ret.loc[valid]
    weight_daily = weight_daily.loc[valid]
    rf_daily = rf_daily.reindex(valid, method='ffill').fillna(0)

    # VT return: w * asset_return + (1-w) * rf_daily
    vt_ret = weight_daily * ret + (1 - weight_daily) * rf_daily

    # Excess returns
    vt_excess = vt_ret - rf_daily
    bh_excess = ret - rf_daily

    return vt_excess, bh_excess, ret, rf_daily


def construct_tsmom(spy_ret, lookback=252):
    """
    Construct TSMOM factor: sign of past-lookback return × current return.
    """
    cum_ret = spy_ret.rolling(lookback).sum()
    signal = np.sign(cum_ret.shift(1))  # Lagged signal
    tsmom = signal * spy_ret
    return tsmom


def newey_west_regression(y, X, max_lag=None):
    """
    OLS regression with Newey-West HAC standard errors.
    y: pd.Series
    X: pd.DataFrame (should include constant column)
    Returns dict with coefficients, t-stats, p-values.
    """
    import statsmodels.api as sm

    # Align
    common = y.dropna().index.intersection(X.dropna().index)
    y = y.loc[common].values
    X = X.loc[common].values
    n, k = X.shape

    if max_lag is None:
        max_lag = int(np.floor(4 * (n / 100) ** (2/9)))

    # OLS
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    resid = y - X @ beta

    # Newey-West HAC
    S = np.zeros((k, k))
    for j in range(max_lag + 1):
        if j == 0:
            Gamma_j = (X * resid[:, None]).T @ (X * resid[:, None]) / n
        else:
            w = 1 - j / (max_lag + 1)  # Bartlett kernel
            Gamma_j = (X[j:] * resid[j:, None]).T @ (X[:n-j] * resid[:n-j, None]) / n
            S += w * (Gamma_j + Gamma_j.T)
            continue
        S += Gamma_j

    V = np.linalg.inv(X.T @ X / n) @ S @ np.linalg.inv(X.T @ X / n) / n
    se = np.sqrt(np.diag(V))
    t_stats = beta / se
    p_values = 2 * (1 - stats.t.cdf(np.abs(t_stats), df=n-k))

    # R-squared
    ss_res = np.sum(resid**2)
    ss_tot = np.sum((y - np.mean(y))**2)
    r2 = 1 - ss_res / ss_tot

    return {
        'beta': beta,
        't_stats': t_stats,
        'p_values': p_values,
        'se': se,
        'r2': r2,
        'n_obs': n,
        'nw_lags': max_lag
    }


def analyze_asset(ticker, price, vix, irx, spy_price):
    """Full analysis pipeline for one asset."""
    print(f"\n{'='*60}")
    print(f"  分析 {ticker} ({ASSET_CLASS_MAP[ticker]})")
    print(f"{'='*60}")

    # 1. Returns
    ret = price.pct_change().dropna() * 100  # percentage for GARCH

    # 2. GJR-GARCH gamma
    gamma = estimate_gjr_gamma(ret)
    print(f"  GJR gamma = {gamma:.6f}")

    # 3. VT strategy returns
    vt_excess, bh_excess, raw_ret, rf_daily = construct_vt_returns(price, vix, irx, VIX_THRESHOLD)

    # 4. Annualized performance
    vt_ann_ret = vt_excess.mean() * 252
    vt_ann_vol = vt_excess.std() * np.sqrt(252)
    vt_sharpe = vt_ann_ret / vt_ann_vol if vt_ann_vol > 0 else 0

    bh_ann_ret = bh_excess.mean() * 252
    bh_ann_vol = bh_excess.std() * np.sqrt(252)
    bh_sharpe = bh_ann_ret / bh_ann_vol if bh_ann_vol > 0 else 0

    print(f"  VT: Sharpe={vt_sharpe:.4f}, Return={vt_ann_ret:.4f}, Vol={vt_ann_vol:.4f}")
    print(f"  B&H: Sharpe={bh_sharpe:.4f}, Return={bh_ann_ret:.4f}, Vol={bh_ann_vol:.4f}")

    # 5. Build factors
    spy_ret = spy_price.pct_change().dropna()
    spy_excess = spy_ret - rf_daily.reindex(spy_ret.index, method='ffill').fillna(0)

    # MKT factor = SPY VT excess (12/VIX on SPY)
    spy_vt_excess, _, _, _ = construct_vt_returns(spy_price, vix, irx, VIX_THRESHOLD)
    mkt = spy_vt_excess

    # TSMOM factor
    tsmom = construct_tsmom(spy_ret, TSMOM_LOOKBACK)

    # Align all
    common = vt_excess.dropna().index
    common = common.intersection(mkt.dropna().index)
    common = common.intersection(tsmom.dropna().index)

    y = vt_excess.loc[common]
    mkt_f = mkt.loc[common]
    tsmom_f = tsmom.loc[common]

    n_obs = len(y)
    print(f"  有效觀測值: {n_obs}")

    # 6. Model 1: MKT only
    X1 = pd.DataFrame({'const': 1.0, 'MKT': mkt_f}, index=common)
    reg1 = newey_west_regression(y, X1)
    alpha1_ann = reg1['beta'][0] * 252

    print(f"  M1: alpha_ann={alpha1_ann:.6f}, t={reg1['t_stats'][0]:.4f}, R2={reg1['r2']:.4f}")

    # 7. Model 2: MKT + raw TSMOM
    X2 = pd.DataFrame({'const': 1.0, 'MKT': mkt_f, 'TSMOM': tsmom_f}, index=common)
    reg2 = newey_west_regression(y, X2)
    alpha2_ann = reg2['beta'][0] * 252

    print(f"  M2: alpha_ann={alpha2_ann:.6f}, t={reg2['t_stats'][0]:.4f}, beta_tsmom={reg2['beta'][2]:.4f}, t={reg2['t_stats'][2]:.4f}")

    # 8. Model 3: MKT + orthogonalized TSMOM
    # Orthogonalize TSMOM w.r.t. MKT
    X_orth = pd.DataFrame({'const': 1.0, 'MKT': mkt_f}, index=common)
    reg_orth = newey_west_regression(tsmom_f, X_orth)
    tsmom_orth = tsmom_f - X_orth.values @ reg_orth['beta']
    # Actually, simpler: regress TSMOM on MKT, take residual
    from numpy.linalg import lstsq
    X_for_orth = np.column_stack([np.ones(len(mkt_f)), mkt_f.values])
    b_orth = lstsq(X_for_orth, tsmom_f.values, rcond=None)[0]
    tsmom_orth_vals = tsmom_f.values - X_for_orth @ b_orth
    tsmom_orth_series = pd.Series(tsmom_orth_vals, index=common)

    X3 = pd.DataFrame({'const': 1.0, 'MKT': mkt_f, 'TSMOM_orth': tsmom_orth_series}, index=common)
    reg3 = newey_west_regression(y, X3)
    alpha3_ann = reg3['beta'][0] * 252

    print(f"  M3: alpha_ann={alpha3_ann:.6f}, t={reg3['t_stats'][0]:.4f}, beta_tsmom_orth={reg3['beta'][2]:.4f}, t={reg3['t_stats'][2]:.4f}")

    # Alpha reduction
    if abs(alpha1_ann) > 1e-10:
        alpha_reduction = (1 - alpha2_ann / alpha1_ann) * 100
    else:
        alpha_reduction = 0.0

    result = {
        'n_obs': n_obs,
        'nw_lags': reg1['nw_lags'],
        'gjr_gamma': gamma,
        'asset_class': ASSET_CLASS_MAP[ticker],
        'vt_performance': {
            'ann_return': round(vt_ann_ret, 4),
            'ann_vol': round(vt_ann_vol, 4),
            'sharpe': round(vt_sharpe, 4),
        },
        'bh_performance': {
            'ann_return': round(bh_ann_ret, 4),
            'ann_vol': round(bh_ann_vol, 4),
            'sharpe': round(bh_sharpe, 4),
        },
        'model1_mkt_only': {
            'alpha_ann': round(alpha1_ann, 6),
            'alpha_t_nw': round(reg1['t_stats'][0], 4),
            'alpha_p': round(reg1['p_values'][0], 6),
            'beta_mkt': round(reg1['beta'][1], 4),
            'beta_mkt_t': round(reg1['t_stats'][1], 4),
            'r2': round(reg1['r2'], 4),
        },
        'model2_raw_tsmom': {
            'alpha_ann': round(alpha2_ann, 6),
            'alpha_t_nw': round(reg2['t_stats'][0], 4),
            'alpha_p': round(reg2['p_values'][0], 6),
            'beta_mkt': round(reg2['beta'][1], 4),
            'beta_mkt_t': round(reg2['t_stats'][1], 4),
            'beta_tsmom_raw': round(reg2['beta'][2], 4),
            'beta_tsmom_raw_t': round(reg2['t_stats'][2], 4),
            'beta_tsmom_raw_p': round(reg2['p_values'][2], 6),
            'r2': round(reg2['r2'], 4),
        },
        'model3_orth_tsmom': {
            'alpha_ann': round(alpha3_ann, 6),
            'alpha_t_nw': round(reg3['t_stats'][0], 4),
            'beta_mkt': round(reg3['beta'][1], 4),
            'beta_mkt_t': round(reg3['t_stats'][1], 4),
            'beta_tsmom_orth': round(reg3['beta'][2], 4),
            'beta_tsmom_orth_t': round(reg3['t_stats'][2], 4),
            'beta_tsmom_orth_p': round(reg3['p_values'][2], 6),
            'r2': round(reg3['r2'], 4),
        },
        'alpha_reduction_pct': round(alpha_reduction, 2),
    }

    return result


def cross_sectional_analysis(all_results):
    """
    Cross-sectional analysis across all N assets.
    corr(GJR_gamma, TSMOM_loading), equity vs non-equity.
    """
    print(f"\n{'='*60}")
    print(f"  Cross-Sectional Analysis (N={len(all_results)})")
    print(f"{'='*60}")

    tickers = list(all_results.keys())
    gammas = np.array([all_results[t]['gjr_gamma'] for t in tickers])
    tsmom_orth_betas = np.array([all_results[t]['model3_orth_tsmom']['beta_tsmom_orth'] for t in tickers])
    tsmom_raw_betas = np.array([all_results[t]['model2_raw_tsmom']['beta_tsmom_raw'] for t in tickers])
    asset_classes = [all_results[t]['asset_class'] for t in tickers]

    # 1. Pearson correlation: gamma vs TSMOM_orth loading
    pearson_r, pearson_p = stats.pearsonr(gammas, tsmom_orth_betas)

    # Bootstrap 95% CI for Pearson r
    n_boot = 10000
    boot_rs = []
    np.random.seed(42)
    for _ in range(n_boot):
        idx = np.random.choice(len(gammas), len(gammas), replace=True)
        r, _ = stats.pearsonr(gammas[idx], tsmom_orth_betas[idx])
        boot_rs.append(r)
    ci_lo, ci_hi = np.percentile(boot_rs, [2.5, 97.5])

    # 2. Spearman correlation
    spearman_rho, spearman_p = stats.spearmanr(gammas, tsmom_orth_betas)

    # 3. Raw TSMOM pearson
    pearson_r_raw, pearson_p_raw = stats.pearsonr(gammas, tsmom_raw_betas)

    print(f"\n  Pearson r (gamma vs TSMOM_orth): {pearson_r:.4f} (p={pearson_p:.4f})")
    print(f"  Bootstrap 95% CI: [{ci_lo:.4f}, {ci_hi:.4f}]")
    print(f"  Spearman rho: {spearman_rho:.4f} (p={spearman_p:.4f})")
    print(f"  Pearson r (gamma vs TSMOM_raw): {pearson_r_raw:.4f} (p={pearson_p_raw:.4f})")

    # 4. Cross-sectional regression: TSMOM_orth_beta = γ₀ + γ₁×GJR_gamma + ε
    X_cs = np.column_stack([np.ones(len(gammas)), gammas])
    from numpy.linalg import lstsq
    b_cs = lstsq(X_cs, tsmom_orth_betas, rcond=None)[0]
    resid_cs = tsmom_orth_betas - X_cs @ b_cs
    se_cs = np.sqrt(np.sum(resid_cs**2) / (len(gammas) - 2) * np.diag(np.linalg.inv(X_cs.T @ X_cs)))
    t_cs = b_cs / se_cs
    p_cs = 2 * (1 - stats.t.cdf(np.abs(t_cs), df=len(gammas)-2))
    r2_cs = 1 - np.sum(resid_cs**2) / np.sum((tsmom_orth_betas - tsmom_orth_betas.mean())**2)

    print(f"\n  CS Regression: TSMOM_orth = {b_cs[0]:.4f} + {b_cs[1]:.4f}×gamma")
    print(f"  γ₁ t-stat = {t_cs[1]:.4f} (p={p_cs[1]:.4f}), R² = {r2_cs:.4f}")

    # 5. Equity vs Non-Equity
    eq_mask = np.array([c == 'equity' for c in asset_classes])
    ne_mask = ~eq_mask

    eq_betas = tsmom_orth_betas[eq_mask]
    ne_betas = tsmom_orth_betas[ne_mask]

    welch_t, welch_p = stats.ttest_ind(eq_betas, ne_betas, equal_var=False)

    print(f"\n  Equity TSMOM_orth mean: {eq_betas.mean():.4f} (n={len(eq_betas)})")
    print(f"  Non-Equity TSMOM_orth mean: {ne_betas.mean():.4f} (n={len(ne_betas)})")
    print(f"  Welch t = {welch_t:.4f} (p={welch_p:.4f})")

    # Alpha reduction
    alpha_reductions = np.array([all_results[t]['alpha_reduction_pct'] for t in tickers])
    ar_pearson_r, ar_pearson_p = stats.pearsonr(gammas, alpha_reductions)

    eq_ar = alpha_reductions[eq_mask]
    ne_ar = alpha_reductions[ne_mask]
    welch_t_ar, welch_p_ar = stats.ttest_ind(eq_ar, ne_ar, equal_var=False)

    cs_analysis = {
        'n_assets': len(all_results),
        'assets_used': tickers,
        'beta_tsmom_orth_vs_gamma': {
            'pearson_r': round(pearson_r, 4),
            'pearson_p': round(pearson_p, 6),
            'pearson_ci_95': [round(ci_lo, 4), round(ci_hi, 4)],
            'spearman_rho': round(spearman_rho, 4),
            'spearman_p': round(spearman_p, 6),
        },
        'beta_tsmom_raw_vs_gamma': {
            'pearson_r': round(pearson_r_raw, 4),
            'pearson_p': round(pearson_p_raw, 6),
        },
        'cs_regression_orth': {
            'gamma0': round(b_cs[0], 4),
            'gamma0_t': round(t_cs[0], 4),
            'gamma1': round(b_cs[1], 4),
            'gamma1_t': round(t_cs[1], 4),
            'gamma1_p': round(p_cs[1], 6),
            'r2': round(r2_cs, 4),
        },
        'alpha_reduction_vs_gamma': {
            'pearson_r': round(ar_pearson_r, 4),
            'pearson_p': round(ar_pearson_p, 6),
        },
    }

    eq_ne = {
        'equity_beta_tsmom_orth_mean': round(eq_betas.mean(), 4),
        'equity_beta_tsmom_orth_std': round(eq_betas.std(), 4),
        'equity_n': int(np.sum(eq_mask)),
        'non_equity_beta_tsmom_orth_mean': round(ne_betas.mean(), 4),
        'non_equity_beta_tsmom_orth_std': round(ne_betas.std(), 4),
        'non_equity_n': int(np.sum(ne_mask)),
        'welch_t_beta': round(welch_t, 4),
        'welch_p_beta': round(welch_p, 6),
        'equity_alpha_reduction_mean': round(eq_ar.mean(), 2),
        'non_equity_alpha_reduction_mean': round(ne_ar.mean(), 2),
        'welch_t_alpha': round(welch_t_ar, 4),
        'welch_p_alpha': round(welch_p_ar, 6),
    }

    return cs_analysis, eq_ne


def print_summary_table(all_results):
    """Print a formatted summary table."""
    print(f"\n{'='*110}")
    print(f"{'Ticker':>8} {'Class':>10} {'gamma':>8} {'VT_SR':>8} {'BH_SR':>8} {'TSMOM_orth':>12} {'t-stat':>8} {'p':>8} {'α_red%':>8}")
    print(f"{'='*110}")

    for ticker, res in all_results.items():
        ac = res['asset_class']
        gamma = res['gjr_gamma']
        vt_sr = res['vt_performance']['sharpe']
        bh_sr = res['bh_performance']['sharpe']
        tsmom = res['model3_orth_tsmom']['beta_tsmom_orth']
        tsmom_t = res['model3_orth_tsmom']['beta_tsmom_orth_t']
        tsmom_p = res['model3_orth_tsmom']['beta_tsmom_orth_p']
        ar = res['alpha_reduction_pct']

        sig = '***' if tsmom_p < 0.001 else '**' if tsmom_p < 0.01 else '*' if tsmom_p < 0.05 else ''
        print(f"{ticker:>8} {ac:>10} {gamma:>8.4f} {vt_sr:>8.4f} {bh_sr:>8.4f} {tsmom:>12.4f} {tsmom_t:>8.4f} {tsmom_p:>8.4f} {ar:>8.2f} {sig}")

    print(f"{'='*110}")


def main():
    print("=" * 70)
    print("K55: Final VT-TSMOM Cross-Sectional Analysis (N=22)")
    print("=" * 70)

    # 1. Load K53 results
    print("\n=== 載入 K53 結果 (N=15) ===")
    with open(K53_PATH, 'r') as f:
        k53 = json.load(f)

    k53_assets = k53['asset_results']
    print(f"  K53 資產: {list(k53_assets.keys())}")

    # 2. Download data for new assets
    prices, vix, irx, spy_price = download_data()

    # 3. Analyze each new asset
    new_results = {}
    for ticker in NEW_TICKERS:
        if ticker not in prices or len(prices[ticker]) < 500:
            print(f"\n  ⚠ {ticker}: 資料不足 ({len(prices.get(ticker, []))} 天)，跳過")
            continue
        try:
            result = analyze_asset(ticker, prices[ticker], vix, irx, spy_price)
            new_results[ticker] = result
        except Exception as e:
            print(f"\n  ⚠ {ticker} 分析失敗: {e}")
            import traceback
            traceback.print_exc()

    # 4. Merge with K53
    all_results = {}
    all_results.update(k53_assets)
    all_results.update(new_results)

    actual_new = list(new_results.keys())
    total_n = len(all_results)
    print(f"\n=== 合併結果 ===")
    print(f"  K53: {len(k53_assets)} 資產")
    print(f"  新增: {len(new_results)} 資產 ({actual_new})")
    print(f"  總計: {total_n} 資產")

    # 5. Summary table
    print_summary_table(all_results)

    # 6. Cross-sectional analysis
    cs_analysis, eq_ne = cross_sectional_analysis(all_results)

    # 7. Build output
    output = {
        'experiment': f'K55: Final VT-TSMOM Cross-Sectional Analysis (N={total_n})',
        'description': f'Expand K53 (N=15) to N={total_n} for Paper 3 submission. Added {actual_new}. Full methodology: GJR-GARCH gamma, 12/VIX monthly lagged VT, Newey-West HAC, orthogonalized TSMOM, contemporaneous T-bill RF.',
        'proposed_by': 'Codex (K50 critique) + Paper 3 outline',
        'executed_by': 'Claude',
        'timestamp': datetime.now().isoformat(),
        'config': {
            'original_tickers': list(k53_assets.keys()),
            'new_tickers': actual_new,
            'all_tickers': list(all_results.keys()),
            'start_date': START_DATE,
            'end_date': END_DATE,
            'vix_threshold': VIX_THRESHOLD,
            'tsmom_lookback': TSMOM_LOOKBACK,
            'se_type': 'Newey-West HAC (auto lag)',
            'rf_source': '^IRX (3-month T-bill)',
        },
        'asset_results': all_results,
        'cross_sectional_analysis': cs_analysis,
        'equity_vs_non_equity': eq_ne,
        'comparison_with_k53': {
            'k53_n': 15,
            'k55_n': total_n,
            'k53_pearson_r': k53['cross_sectional_analysis']['beta_tsmom_orth_vs_gamma']['pearson_r'],
            'k53_pearson_p': k53['cross_sectional_analysis']['beta_tsmom_orth_vs_gamma']['pearson_p'],
            'k55_pearson_r': cs_analysis['beta_tsmom_orth_vs_gamma']['pearson_r'],
            'k55_pearson_p': cs_analysis['beta_tsmom_orth_vs_gamma']['pearson_p'],
            'k53_spearman_rho': k53['cross_sectional_analysis']['beta_tsmom_orth_vs_gamma']['spearman_rho'],
            'k55_spearman_rho': cs_analysis['beta_tsmom_orth_vs_gamma']['spearman_rho'],
            'k53_cs_r2': k53['cross_sectional_analysis']['cs_regression_orth']['r2'],
            'k55_cs_r2': cs_analysis['cs_regression_orth']['r2'],
            'k53_welch_p': k53['equity_vs_non_equity']['welch_p_beta'],
            'k55_welch_p': eq_ne['welch_p_beta'],
        },
        'conclusions': {},  # Will fill below
    }

    # 8. Fill conclusions
    sig_count = sum(1 for t in all_results if abs(all_results[t]['model3_orth_tsmom']['beta_tsmom_orth_t']) > 1.96)

    output['conclusions'] = {
        'main_finding': f'在 {total_n} 個資產中，{sig_count} 個有顯著 TSMOM_orth loading (|t|>1.96)。'
                        f'Pearson r(gamma, TSMOM_orth) = {cs_analysis["beta_tsmom_orth_vs_gamma"]["pearson_r"]:.3f} '
                        f'(p={cs_analysis["beta_tsmom_orth_vs_gamma"]["pearson_p"]:.4f})。',
        'cross_sectional': f'GJR gamma vs beta_TSMOM_orth: Pearson r={cs_analysis["beta_tsmom_orth_vs_gamma"]["pearson_r"]:.3f} '
                          f'(p={cs_analysis["beta_tsmom_orth_vs_gamma"]["pearson_p"]:.4f}), '
                          f'Spearman rho={cs_analysis["beta_tsmom_orth_vs_gamma"]["spearman_rho"]:.3f} '
                          f'(p={cs_analysis["beta_tsmom_orth_vs_gamma"]["spearman_p"]:.4f}). '
                          f'Bootstrap 95% CI: [{cs_analysis["beta_tsmom_orth_vs_gamma"]["pearson_ci_95"][0]:.3f}, '
                          f'{cs_analysis["beta_tsmom_orth_vs_gamma"]["pearson_ci_95"][1]:.3f}]. '
                          f'Cross-sectional R²={cs_analysis["cs_regression_orth"]["r2"]:.3f}.',
        'classification': f'Equity vs Non-Equity TSMOM_orth beta: '
                         f'Equity mean={eq_ne["equity_beta_tsmom_orth_mean"]:.4f} (n={eq_ne["equity_n"]}), '
                         f'Non-Equity mean={eq_ne["non_equity_beta_tsmom_orth_mean"]:.4f} (n={eq_ne["non_equity_n"]}). '
                         f'Welch t={eq_ne["welch_t_beta"]:.3f} (p={eq_ne["welch_p_beta"]:.4f}).',
        'robustness': f'N=15→N={total_n} 擴展後相關性方向與顯著性 '
                     f'{"維持" if cs_analysis["beta_tsmom_orth_vs_gamma"]["pearson_p"] < 0.05 else "改變"}。'
                     f'K53 r={output["comparison_with_k53"]["k53_pearson_r"]:.3f} → '
                     f'K55 r={output["comparison_with_k53"]["k55_pearson_r"]:.3f}。',
        'paper3_ready': f'Cross-sectional sample size N={total_n} 滿足 Paper 3 requirement (N≥20).' if total_n >= 20 else f'N={total_n} < 20, 需要更多資產。',
    }

    # 9. Save
    with open(OUTPUT_PATH, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n=== 結果已儲存 ===")
    print(f"  {OUTPUT_PATH}")

    # 10. Final summary
    print(f"\n{'='*70}")
    print(f"  K55 最終摘要 (N={total_n})")
    print(f"{'='*70}")
    print(f"  Pearson r(gamma, TSMOM_orth) = {cs_analysis['beta_tsmom_orth_vs_gamma']['pearson_r']:.4f} "
          f"(p={cs_analysis['beta_tsmom_orth_vs_gamma']['pearson_p']:.4f})")
    print(f"  Spearman rho = {cs_analysis['beta_tsmom_orth_vs_gamma']['spearman_rho']:.4f} "
          f"(p={cs_analysis['beta_tsmom_orth_vs_gamma']['spearman_p']:.4f})")
    print(f"  Bootstrap 95% CI: [{cs_analysis['beta_tsmom_orth_vs_gamma']['pearson_ci_95'][0]:.4f}, "
          f"{cs_analysis['beta_tsmom_orth_vs_gamma']['pearson_ci_95'][1]:.4f}]")
    print(f"  CS Regression R² = {cs_analysis['cs_regression_orth']['r2']:.4f}")
    print(f"  Equity mean TSMOM_orth = {eq_ne['equity_beta_tsmom_orth_mean']:.4f} (n={eq_ne['equity_n']})")
    print(f"  Non-Equity mean TSMOM_orth = {eq_ne['non_equity_beta_tsmom_orth_mean']:.4f} (n={eq_ne['non_equity_n']})")
    print(f"  Welch t = {eq_ne['welch_t_beta']:.4f} (p={eq_ne['welch_p_beta']:.4f})")
    print(f"\n  K53 → K55 比較:")
    print(f"    Pearson r: {output['comparison_with_k53']['k53_pearson_r']:.4f} → {output['comparison_with_k53']['k55_pearson_r']:.4f}")
    print(f"    Spearman rho: {output['comparison_with_k53']['k53_spearman_rho']:.4f} → {output['comparison_with_k53']['k55_spearman_rho']:.4f}")
    print(f"    CS R²: {output['comparison_with_k53']['k53_cs_r2']:.4f} → {output['comparison_with_k53']['k55_cs_r2']:.4f}")
    print(f"    Welch p: {output['comparison_with_k53']['k53_welch_p']:.4f} → {output['comparison_with_k53']['k55_welch_p']:.4f}")

    sig_assets = [t for t in all_results if abs(all_results[t]['model3_orth_tsmom']['beta_tsmom_orth_t']) > 1.96]
    ns_assets = [t for t in all_results if abs(all_results[t]['model3_orth_tsmom']['beta_tsmom_orth_t']) <= 1.96]
    print(f"\n  顯著 TSMOM_orth loading (|t|>1.96): {len(sig_assets)}/{total_n}")
    print(f"    Significant: {sig_assets}")
    print(f"    Not significant: {ns_assets}")

    return output


if __name__ == '__main__':
    main()
