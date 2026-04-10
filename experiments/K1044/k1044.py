"""
K1044: Gamma-VT Causal Panel Test (Cross-Asset Causal Verification)

Background:
- K53: gamma (GJR leverage) vs VT alpha correlation r=0.564 (N=22, p<0.01)
- K49: VT dual mechanism (Sharpe from TSMOM, MDD from VIX sizing)
- K58: Sector VT uniform — gamma doesn't predict sector VT
- N145: Gamma does NOT predict VT Sharpe improvement (rho=-0.264, p=0.34, N=15)
- N97: Combined 17-asset proposition test rho=0.874 (p=4e-6)

Core Questions:
1. Does K53's r=0.564 hold when expanded to 13+ assets?
2. LOO stability — is it driven by a few extreme assets (e.g., BTC)?
3. Does gamma -> autocorrelation -> VT alpha causal chain hold?
4. Sizing channel (VIX) vs Momentum channel (gamma) — which matters more?

Data: yfinance, 2007-01-01 ~ 2026-04-10 (BTC from 2014)
OOS for VT: 2015-01-01 ~ 2026-04-10
GARCH window: 2000, refit: 63
VT: 12/VIX, daily, capped at 1.5
Bootstrap: 5000 reps, seed=42

References:
- Moreira & Muir (2017) "Volatility-Managed Portfolios" JF
- Engle & Ng (1993) "Measuring and Testing the Impact of News on Volatility" JF
- Glosten, Jagannathan & Runkle (1993) "On the Relation between the Expected Value and the Volatility of the Nominal Excess Return on Stocks" JF
- Hood & Raughtigan (2025) "VT = trend following"
"""

import numpy as np
import pandas as pd
import yfinance as yf
import json
import warnings
import os
import sys
from datetime import datetime
from scipy import stats
from arch import arch_model

# Try to import clean_tw50_data
try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from src.volpred.utils import clean_tw50_data
    HAS_CLEAN_TW50 = True
except ImportError:
    HAS_CLEAN_TW50 = False
    print("WARNING: clean_tw50_data not available, will handle 0050.TW manually")

warnings.filterwarnings('ignore')
np.random.seed(42)

# ============================================================
# Configuration
# ============================================================
ASSETS = [
    'SPY', 'QQQ', 'IWM', 'EFA', 'EEM',  # equity ETFs
    'GLD', 'SLV', 'USO',                  # commodity ETFs
    'TLT', 'HYG',                          # fixed income
    'BTC-USD',                              # crypto
    '0050.TW',                              # Taiwan
    'XLF',                                  # sector
]

START_DATE = '2007-01-01'
END_DATE = '2026-04-10'
OOS_START = '2015-01-01'
GARCH_WINDOW = 2000
GARCH_REFIT = 63
VT_CAP = 1.5
BOOTSTRAP_REPS = 5000
VIX_TICKER = '^VIX'

RESULTS_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# Step 0: Download Data
# ============================================================
def download_data():
    """Download price data for all assets + VIX."""
    print("=" * 60)
    print("Step 0: Downloading data")
    print("=" * 60)

    # Download VIX
    vix = yf.download(VIX_TICKER, start=START_DATE, end=END_DATE, progress=False)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)
    vix_close = vix['Close'].squeeze()
    print(f"VIX: {len(vix_close)} observations, {vix_close.index[0].date()} to {vix_close.index[-1].date()}")

    # Download assets
    asset_data = {}
    for asset in ASSETS:
        try:
            df = yf.download(asset, start=START_DATE, end=END_DATE, progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            prices = df['Adj Close'].squeeze() if 'Adj Close' in df.columns else df['Close'].squeeze()

            # Handle 0050.TW split issue
            if asset == '0050.TW':
                if HAS_CLEAN_TW50:
                    prices, _ = clean_tw50_data(prices)
                    print(f"  {asset}: cleaned with clean_tw50_data")
                else:
                    # Manual fix: 2014 1:4 split, Yahoo only adjusts back to 2014
                    # Data before 2014 may be unadjusted
                    prices = prices[prices.index >= '2014-01-01']
                    print(f"  {asset}: trimmed to post-2014 (manual split handling)")

            returns = prices.pct_change().dropna()

            # Filter out extreme outliers (likely data errors)
            returns = returns[returns.abs() < 0.5]

            asset_data[asset] = {
                'prices': prices,
                'returns': returns,
                'start': returns.index[0].date(),
                'end': returns.index[-1].date(),
                'n_obs': len(returns)
            }
            print(f"  {asset}: {len(returns)} obs, {returns.index[0].date()} to {returns.index[-1].date()}")
        except Exception as e:
            print(f"  {asset}: FAILED - {e}")

    return asset_data, vix_close


# ============================================================
# Step 1: Estimate gamma for each asset via GJR-GARCH
# ============================================================
def estimate_gamma(returns, window=GARCH_WINDOW, refit_freq=GARCH_REFIT):
    """
    Estimate GJR-GARCH gamma (leverage parameter) using rolling estimation.
    Returns average gamma over OOS period.
    """
    oos_start_idx = returns.index.searchsorted(pd.Timestamp(OOS_START))
    if oos_start_idx < window:
        oos_start_idx = window

    gammas = []
    gamma_ts = []  # time series of gamma estimates

    for t in range(oos_start_idx, len(returns), refit_freq):
        train = returns.iloc[max(0, t - window):t] * 100  # scale for arch package

        try:
            model = arch_model(train, vol='GARCH', p=1, o=1, q=1, dist='normal')
            res = model.fit(disp='off', show_warning=False)
            gamma = res.params.get('gamma[1]', 0.0)
            gammas.append(gamma)
            gamma_ts.append({'date': returns.index[t], 'gamma': gamma})
        except Exception:
            continue

    if len(gammas) == 0:
        return np.nan, np.nan, []

    avg_gamma = np.mean(gammas)
    std_gamma = np.std(gammas)

    return avg_gamma, std_gamma, gamma_ts


# ============================================================
# Step 2: Compute VT metrics for each asset
# ============================================================
def compute_vt_metrics(returns, vix_close):
    """
    Compute 12/VIX volatility targeting metrics.
    signal.shift(1) enforced for lag.
    """
    # Align returns and VIX
    common_idx = returns.index.intersection(vix_close.index)
    ret = returns.loc[common_idx]
    vix = vix_close.loc[common_idx]

    # OOS only
    oos_mask = ret.index >= OOS_START
    ret = ret[oos_mask]
    vix = vix[oos_mask]

    if len(ret) < 252:
        return None

    # VT weights: 12/VIX, capped at VT_CAP
    raw_weight = 12.0 / vix
    weight = raw_weight.clip(upper=VT_CAP)

    # CRITICAL: signal.shift(1) — use yesterday's VIX for today's return
    weight_lagged = weight.shift(1)

    # Drop first NaN
    valid = weight_lagged.notna()
    ret = ret[valid]
    weight_lagged = weight_lagged[valid]

    # VT return
    vt_ret = weight_lagged * ret
    bh_ret = ret

    # Metrics
    ann_factor = 252

    # BH metrics
    bh_sharpe = bh_ret.mean() / bh_ret.std() * np.sqrt(ann_factor)
    bh_cum = (1 + bh_ret).cumprod()
    bh_dd = bh_cum / bh_cum.cummax() - 1
    bh_mdd = bh_dd.min()
    bh_ann_ret = bh_ret.mean() * ann_factor
    bh_ann_vol = bh_ret.std() * np.sqrt(ann_factor)

    # VT metrics
    vt_sharpe = vt_ret.mean() / vt_ret.std() * np.sqrt(ann_factor)
    vt_cum = (1 + vt_ret).cumprod()
    vt_dd = vt_cum / vt_cum.cummax() - 1
    vt_mdd = vt_dd.min()
    vt_ann_ret = vt_ret.mean() * ann_factor
    vt_ann_vol = vt_ret.std() * np.sqrt(ann_factor)

    # VT alpha = annualized excess return over BH
    vt_alpha = vt_ann_ret - bh_ann_ret
    sharpe_diff = vt_sharpe - bh_sharpe
    mdd_improvement = bh_mdd - vt_mdd  # positive = VT better

    return {
        'bh_sharpe': float(bh_sharpe),
        'bh_mdd': float(bh_mdd),
        'bh_ann_ret': float(bh_ann_ret),
        'bh_ann_vol': float(bh_ann_vol),
        'vt_sharpe': float(vt_sharpe),
        'vt_mdd': float(vt_mdd),
        'vt_ann_ret': float(vt_ann_ret),
        'vt_ann_vol': float(vt_ann_vol),
        'vt_alpha': float(vt_alpha),
        'sharpe_diff': float(sharpe_diff),
        'mdd_improvement': float(mdd_improvement),
        'n_obs_oos': int(len(ret)),
        'avg_weight': float(weight_lagged.mean()),
    }


# ============================================================
# Step 3: Autocorrelation analysis
# ============================================================
def compute_autocorrelation(returns, oos_start=OOS_START):
    """Compute lag-1 autocorrelation of returns in OOS period."""
    oos = returns[returns.index >= oos_start]
    if len(oos) < 100:
        return np.nan
    return float(oos.autocorr(lag=1))


def compute_vix_return_corr(returns, vix_close, oos_start=OOS_START):
    """Compute correlation between VIX changes and returns in OOS period."""
    common_idx = returns.index.intersection(vix_close.index)
    ret = returns.loc[common_idx]
    vix = vix_close.loc[common_idx]

    oos_mask = ret.index >= oos_start
    ret = ret[oos_mask]
    vix_chg = vix[oos_mask].pct_change().dropna()

    common = ret.index.intersection(vix_chg.index)
    if len(common) < 100:
        return np.nan

    return float(ret.loc[common].corr(vix_chg.loc[common]))


# ============================================================
# Step 4: Cross-sectional analysis
# ============================================================
def cross_sectional_analysis(panel_data):
    """
    Cross-sectional tests:
    A. Spearman & Pearson correlation: gamma vs VT alpha
    B. Bootstrap CI on correlation
    C. Leave-One-Out stability
    D. Mechanism decomposition
    """
    assets = list(panel_data.keys())
    n = len(assets)

    gammas = np.array([panel_data[a]['gamma'] for a in assets])
    vt_alphas = np.array([panel_data[a]['vt_alpha'] for a in assets])
    sharpe_diffs = np.array([panel_data[a]['sharpe_diff'] for a in assets])
    mdd_improvements = np.array([panel_data[a]['mdd_improvement'] for a in assets])
    autocorrs = np.array([panel_data[a]['autocorr_lag1'] for a in assets])
    vix_corrs = np.array([panel_data[a]['vix_return_corr'] for a in assets])

    results = {}

    # --- A. Correlations: gamma vs VT metrics ---
    print("\n--- A. Cross-Sectional Correlations ---")

    # gamma vs VT alpha
    rho_alpha, p_alpha = stats.spearmanr(gammas, vt_alphas)
    r_alpha, pr_alpha = stats.pearsonr(gammas, vt_alphas)
    print(f"Gamma vs VT Alpha:     Spearman rho={rho_alpha:.3f} (p={p_alpha:.4f}), Pearson r={r_alpha:.3f} (p={pr_alpha:.4f})")

    # gamma vs Sharpe diff
    rho_sharpe, p_sharpe = stats.spearmanr(gammas, sharpe_diffs)
    r_sharpe, pr_sharpe = stats.pearsonr(gammas, sharpe_diffs)
    print(f"Gamma vs Sharpe diff:  Spearman rho={rho_sharpe:.3f} (p={p_sharpe:.4f}), Pearson r={r_sharpe:.3f} (p={pr_sharpe:.4f})")

    # gamma vs MDD improvement
    rho_mdd, p_mdd = stats.spearmanr(gammas, mdd_improvements)
    r_mdd, pr_mdd = stats.pearsonr(gammas, mdd_improvements)
    print(f"Gamma vs MDD improve:  Spearman rho={rho_mdd:.3f} (p={p_mdd:.4f}), Pearson r={r_mdd:.3f} (p={pr_mdd:.4f})")

    results['correlations'] = {
        'gamma_vs_vt_alpha': {
            'spearman_rho': float(rho_alpha), 'spearman_p': float(p_alpha),
            'pearson_r': float(r_alpha), 'pearson_p': float(pr_alpha),
        },
        'gamma_vs_sharpe_diff': {
            'spearman_rho': float(rho_sharpe), 'spearman_p': float(p_sharpe),
            'pearson_r': float(r_sharpe), 'pearson_p': float(pr_sharpe),
        },
        'gamma_vs_mdd_improvement': {
            'spearman_rho': float(rho_mdd), 'spearman_p': float(p_mdd),
            'pearson_r': float(r_mdd), 'pearson_p': float(pr_mdd),
        },
    }

    # --- B. Bootstrap CI on correlation ---
    print("\n--- B. Bootstrap Confidence Intervals (5000 reps) ---")
    rng = np.random.default_rng(42)

    boot_rho_alpha = []
    boot_rho_sharpe = []
    boot_rho_mdd = []

    for _ in range(BOOTSTRAP_REPS):
        idx = rng.choice(n, size=n, replace=True)
        g = gammas[idx]
        va = vt_alphas[idx]
        sd = sharpe_diffs[idx]
        mi = mdd_improvements[idx]

        # Handle degenerate bootstrap samples
        if np.std(g) < 1e-10 or np.std(va) < 1e-10:
            continue

        rho_a, _ = stats.spearmanr(g, va)
        boot_rho_alpha.append(rho_a)

        if np.std(sd) > 1e-10:
            rho_s, _ = stats.spearmanr(g, sd)
            boot_rho_sharpe.append(rho_s)

        if np.std(mi) > 1e-10:
            rho_m, _ = stats.spearmanr(g, mi)
            boot_rho_mdd.append(rho_m)

    boot_rho_alpha = np.array(boot_rho_alpha)
    boot_rho_sharpe = np.array(boot_rho_sharpe)
    boot_rho_mdd = np.array(boot_rho_mdd)

    ci_alpha = np.percentile(boot_rho_alpha, [2.5, 97.5]) if len(boot_rho_alpha) > 0 else [np.nan, np.nan]
    ci_sharpe = np.percentile(boot_rho_sharpe, [2.5, 97.5]) if len(boot_rho_sharpe) > 0 else [np.nan, np.nan]
    ci_mdd = np.percentile(boot_rho_mdd, [2.5, 97.5]) if len(boot_rho_mdd) > 0 else [np.nan, np.nan]

    print(f"Gamma vs VT Alpha CI:    [{ci_alpha[0]:.3f}, {ci_alpha[1]:.3f}]")
    print(f"Gamma vs Sharpe diff CI: [{ci_sharpe[0]:.3f}, {ci_sharpe[1]:.3f}]")
    print(f"Gamma vs MDD improve CI: [{ci_mdd[0]:.3f}, {ci_mdd[1]:.3f}]")

    results['bootstrap_ci'] = {
        'gamma_vs_vt_alpha_95ci': [float(ci_alpha[0]), float(ci_alpha[1])],
        'gamma_vs_sharpe_diff_95ci': [float(ci_sharpe[0]), float(ci_sharpe[1])],
        'gamma_vs_mdd_improvement_95ci': [float(ci_mdd[0]), float(ci_mdd[1])],
        'n_bootstrap': BOOTSTRAP_REPS,
    }

    # --- C. Leave-One-Out Stability ---
    print("\n--- C. Leave-One-Out Stability ---")
    loo_results = []
    for i, asset in enumerate(assets):
        g_loo = np.delete(gammas, i)
        va_loo = np.delete(vt_alphas, i)
        sd_loo = np.delete(sharpe_diffs, i)
        mi_loo = np.delete(mdd_improvements, i)

        rho_a_loo, p_a_loo = stats.spearmanr(g_loo, va_loo)
        rho_s_loo, _ = stats.spearmanr(g_loo, sd_loo)
        rho_m_loo, _ = stats.spearmanr(g_loo, mi_loo)

        loo_results.append({
            'removed_asset': asset,
            'rho_alpha': float(rho_a_loo),
            'rho_sharpe': float(rho_s_loo),
            'rho_mdd': float(rho_m_loo),
            'delta_rho_alpha': float(rho_a_loo - rho_alpha),
        })

        flag = " ***" if abs(rho_a_loo - rho_alpha) > 0.15 else ""
        print(f"  Remove {asset:10s}: rho_alpha={rho_a_loo:+.3f} (delta={rho_a_loo - rho_alpha:+.3f}){flag}")

    results['leave_one_out'] = loo_results

    # Identify influential assets
    max_delta = max(loo_results, key=lambda x: abs(x['delta_rho_alpha']))
    print(f"\n  Most influential: {max_delta['removed_asset']} (delta_rho={max_delta['delta_rho_alpha']:+.3f})")

    # --- D. Mechanism Decomposition ---
    print("\n--- D. Mechanism Decomposition ---")

    # Channel 1: gamma -> autocorrelation
    valid_ac = ~np.isnan(autocorrs)
    if valid_ac.sum() >= 7:
        rho_g_ac, p_g_ac = stats.spearmanr(gammas[valid_ac], autocorrs[valid_ac])
        print(f"Gamma vs Autocorr(lag1):       rho={rho_g_ac:.3f} (p={p_g_ac:.4f})")
    else:
        rho_g_ac, p_g_ac = np.nan, np.nan
        print(f"Gamma vs Autocorr(lag1):       insufficient data")

    # Channel 2: gamma -> VIX-return correlation
    valid_vc = ~np.isnan(vix_corrs)
    if valid_vc.sum() >= 7:
        rho_g_vc, p_g_vc = stats.spearmanr(gammas[valid_vc], vix_corrs[valid_vc])
        print(f"Gamma vs VIX-return corr:      rho={rho_g_vc:.3f} (p={p_g_vc:.4f})")
    else:
        rho_g_vc, p_g_vc = np.nan, np.nan
        print(f"Gamma vs VIX-return corr:      insufficient data")

    # Channel 3: autocorrelation -> VT alpha
    if valid_ac.sum() >= 7:
        rho_ac_alpha, p_ac_alpha = stats.spearmanr(autocorrs[valid_ac], vt_alphas[valid_ac])
        print(f"Autocorr(lag1) vs VT alpha:    rho={rho_ac_alpha:.3f} (p={p_ac_alpha:.4f})")
    else:
        rho_ac_alpha, p_ac_alpha = np.nan, np.nan

    # Channel 4: VIX-return corr -> VT alpha
    if valid_vc.sum() >= 7:
        rho_vc_alpha, p_vc_alpha = stats.spearmanr(vix_corrs[valid_vc], vt_alphas[valid_vc])
        print(f"VIX-return corr vs VT alpha:   rho={rho_vc_alpha:.3f} (p={p_vc_alpha:.4f})")
    else:
        rho_vc_alpha, p_vc_alpha = np.nan, np.nan

    # Channel 5: autocorrelation -> Sharpe diff
    if valid_ac.sum() >= 7:
        rho_ac_sharpe, p_ac_sharpe = stats.spearmanr(autocorrs[valid_ac], sharpe_diffs[valid_ac])
        print(f"Autocorr(lag1) vs Sharpe diff: rho={rho_ac_sharpe:.3f} (p={p_ac_sharpe:.4f})")
    else:
        rho_ac_sharpe, p_ac_sharpe = np.nan, np.nan

    # Channel 6: VIX-return corr -> MDD improvement (sizing channel)
    if valid_vc.sum() >= 7:
        rho_vc_mdd, p_vc_mdd = stats.spearmanr(vix_corrs[valid_vc], mdd_improvements[valid_vc])
        print(f"VIX-return corr vs MDD improve:rho={rho_vc_mdd:.3f} (p={p_vc_mdd:.4f})")
    else:
        rho_vc_mdd, p_vc_mdd = np.nan, np.nan

    results['mechanism_decomposition'] = {
        'gamma_vs_autocorr': {'rho': float(rho_g_ac) if not np.isnan(rho_g_ac) else None,
                              'p': float(p_g_ac) if not np.isnan(p_g_ac) else None},
        'gamma_vs_vix_return_corr': {'rho': float(rho_g_vc) if not np.isnan(rho_g_vc) else None,
                                     'p': float(p_g_vc) if not np.isnan(p_g_vc) else None},
        'autocorr_vs_vt_alpha': {'rho': float(rho_ac_alpha) if not np.isnan(rho_ac_alpha) else None,
                                 'p': float(p_ac_alpha) if not np.isnan(p_ac_alpha) else None},
        'vix_corr_vs_vt_alpha': {'rho': float(rho_vc_alpha) if not np.isnan(rho_vc_alpha) else None,
                                 'p': float(p_vc_alpha) if not np.isnan(p_vc_alpha) else None},
        'autocorr_vs_sharpe_diff': {'rho': float(rho_ac_sharpe) if not np.isnan(rho_ac_sharpe) else None,
                                    'p': float(p_ac_sharpe) if not np.isnan(p_ac_sharpe) else None},
        'vix_corr_vs_mdd_improvement': {'rho': float(rho_vc_mdd) if not np.isnan(rho_vc_mdd) else None,
                                        'p': float(p_vc_mdd) if not np.isnan(p_vc_mdd) else None},
    }

    return results


# ============================================================
# Step 5: Generate plots
# ============================================================
def generate_plots(panel_data, results):
    """Generate scatter plots and mechanism decomposition chart."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    assets = list(panel_data.keys())
    gammas = np.array([panel_data[a]['gamma'] for a in assets])
    vt_alphas = np.array([panel_data[a]['vt_alpha'] for a in assets])
    sharpe_diffs = np.array([panel_data[a]['sharpe_diff'] for a in assets])
    mdd_improvements = np.array([panel_data[a]['mdd_improvement'] for a in assets])
    autocorrs = np.array([panel_data[a]['autocorr_lag1'] for a in assets])
    vix_corrs = np.array([panel_data[a]['vix_return_corr'] for a in assets])

    # --- Plot 1: Gamma vs VT Alpha scatter ---
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))

    # Panel A: gamma vs VT alpha
    ax = axes[0]
    ax.scatter(gammas, vt_alphas, s=80, c='steelblue', edgecolors='navy', zorder=5)
    for i, asset in enumerate(assets):
        ax.annotate(asset, (gammas[i], vt_alphas[i]), fontsize=7, ha='left', va='bottom')

    # Add regression line
    slope, intercept = np.polyfit(gammas, vt_alphas, 1)
    x_line = np.linspace(gammas.min() - 0.02, gammas.max() + 0.02, 100)
    ax.plot(x_line, slope * x_line + intercept, 'r--', alpha=0.7, lw=1.5)

    rho_a = results['correlations']['gamma_vs_vt_alpha']['spearman_rho']
    p_a = results['correlations']['gamma_vs_vt_alpha']['spearman_p']
    ax.set_title(f'A. Gamma vs VT Alpha\nSpearman rho={rho_a:.3f} (p={p_a:.4f})', fontsize=11)
    ax.set_xlabel('GJR-GARCH Gamma (leverage effect)')
    ax.set_ylabel('VT Alpha (annualized)')
    ax.axhline(y=0, color='gray', linestyle=':', alpha=0.5)
    ax.axvline(x=0, color='gray', linestyle=':', alpha=0.5)
    ax.grid(True, alpha=0.3)

    # Panel B: gamma vs Sharpe diff
    ax = axes[1]
    ax.scatter(gammas, sharpe_diffs, s=80, c='coral', edgecolors='darkred', zorder=5)
    for i, asset in enumerate(assets):
        ax.annotate(asset, (gammas[i], sharpe_diffs[i]), fontsize=7, ha='left', va='bottom')

    slope2, intercept2 = np.polyfit(gammas, sharpe_diffs, 1)
    ax.plot(x_line, slope2 * x_line + intercept2, 'r--', alpha=0.7, lw=1.5)

    rho_s = results['correlations']['gamma_vs_sharpe_diff']['spearman_rho']
    p_s = results['correlations']['gamma_vs_sharpe_diff']['spearman_p']
    ax.set_title(f'B. Gamma vs Sharpe Diff\nSpearman rho={rho_s:.3f} (p={p_s:.4f})', fontsize=11)
    ax.set_xlabel('GJR-GARCH Gamma (leverage effect)')
    ax.set_ylabel('Sharpe Difference (VT - BH)')
    ax.axhline(y=0, color='gray', linestyle=':', alpha=0.5)
    ax.axvline(x=0, color='gray', linestyle=':', alpha=0.5)
    ax.grid(True, alpha=0.3)

    # Panel C: gamma vs MDD improvement
    ax = axes[2]
    ax.scatter(gammas, mdd_improvements, s=80, c='forestgreen', edgecolors='darkgreen', zorder=5)
    for i, asset in enumerate(assets):
        ax.annotate(asset, (gammas[i], mdd_improvements[i]), fontsize=7, ha='left', va='bottom')

    slope3, intercept3 = np.polyfit(gammas, mdd_improvements, 1)
    ax.plot(x_line, slope3 * x_line + intercept3, 'r--', alpha=0.7, lw=1.5)

    rho_m = results['correlations']['gamma_vs_mdd_improvement']['spearman_rho']
    p_m = results['correlations']['gamma_vs_mdd_improvement']['spearman_p']
    ax.set_title(f'C. Gamma vs MDD Improvement\nSpearman rho={rho_m:.3f} (p={p_m:.4f})', fontsize=11)
    ax.set_xlabel('GJR-GARCH Gamma (leverage effect)')
    ax.set_ylabel('MDD Improvement (BH_MDD - VT_MDD)')
    ax.axhline(y=0, color='gray', linestyle=':', alpha=0.5)
    ax.axvline(x=0, color='gray', linestyle=':', alpha=0.5)
    ax.grid(True, alpha=0.3)

    plt.suptitle('K1044: Gamma vs VT Effectiveness — Cross-Asset Panel (N=13)', fontsize=14, fontweight='bold', y=1.02)
    plt.tight_layout()
    plot1_path = os.path.join(RESULTS_DIR, 'k1044_gamma_vt_scatter.png')
    plt.savefig(plot1_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"\nPlot 1 saved: {plot1_path}")

    # --- Plot 2: Mechanism Decomposition ---
    fig, axes = plt.subplots(2, 3, figsize=(18, 12))

    # Row 1: Gamma -> Channels
    # (1) gamma -> autocorrelation
    ax = axes[0, 0]
    valid = ~np.isnan(autocorrs)
    ax.scatter(gammas[valid], autocorrs[valid], s=80, c='purple', edgecolors='darkviolet', zorder=5)
    for i, asset in enumerate(assets):
        if valid[i]:
            ax.annotate(asset, (gammas[i], autocorrs[i]), fontsize=7)
    mech = results['mechanism_decomposition']
    rho_val = mech['gamma_vs_autocorr']['rho']
    p_val = mech['gamma_vs_autocorr']['p']
    ax.set_title(f'(1) Gamma -> Autocorr(1)\nrho={rho_val:.3f} (p={p_val:.4f})' if rho_val is not None else '(1) Gamma -> Autocorr(1)', fontsize=10)
    ax.set_xlabel('Gamma')
    ax.set_ylabel('Autocorr(lag=1)')
    ax.axhline(y=0, color='gray', linestyle=':', alpha=0.5)
    ax.grid(True, alpha=0.3)

    # (2) gamma -> VIX-return correlation
    ax = axes[0, 1]
    valid_vc = ~np.isnan(vix_corrs)
    ax.scatter(gammas[valid_vc], vix_corrs[valid_vc], s=80, c='darkorange', edgecolors='saddlebrown', zorder=5)
    for i, asset in enumerate(assets):
        if valid_vc[i]:
            ax.annotate(asset, (gammas[i], vix_corrs[i]), fontsize=7)
    rho_val = mech['gamma_vs_vix_return_corr']['rho']
    p_val = mech['gamma_vs_vix_return_corr']['p']
    ax.set_title(f'(2) Gamma -> VIX-Ret Corr\nrho={rho_val:.3f} (p={p_val:.4f})' if rho_val is not None else '(2) Gamma -> VIX-Ret Corr', fontsize=10)
    ax.set_xlabel('Gamma')
    ax.set_ylabel('Corr(Return, dVIX)')
    ax.axhline(y=0, color='gray', linestyle=':', alpha=0.5)
    ax.grid(True, alpha=0.3)

    # (3) Summary: causal chain strength
    ax = axes[0, 2]
    channels = ['gamma->autocorr', 'gamma->vix_corr', 'autocorr->alpha', 'vix_corr->alpha', 'autocorr->sharpe', 'vix_corr->mdd']
    rhos_chain = []
    for key in ['gamma_vs_autocorr', 'gamma_vs_vix_return_corr', 'autocorr_vs_vt_alpha',
                'vix_corr_vs_vt_alpha', 'autocorr_vs_sharpe_diff', 'vix_corr_vs_mdd_improvement']:
        val = mech[key]['rho']
        rhos_chain.append(val if val is not None else 0)

    colors = ['purple' if abs(r) >= 0.5 else 'orange' if abs(r) >= 0.3 else 'gray' for r in rhos_chain]
    bars = ax.barh(channels, rhos_chain, color=colors, edgecolor='black', alpha=0.8)
    ax.set_xlabel('Spearman rho')
    ax.set_title('(3) Causal Chain Strength', fontsize=10)
    ax.axvline(x=0, color='black', lw=0.5)
    for i, (ch, r) in enumerate(zip(channels, rhos_chain)):
        ax.text(r + 0.02 if r >= 0 else r - 0.02, i, f'{r:.3f}', va='center', ha='left' if r >= 0 else 'right', fontsize=9)
    ax.grid(True, alpha=0.3, axis='x')

    # Row 2: Channels -> VT outcomes
    # (4) autocorr -> VT alpha
    ax = axes[1, 0]
    ax.scatter(autocorrs[valid], vt_alphas[valid], s=80, c='teal', edgecolors='darkcyan', zorder=5)
    for i, asset in enumerate(assets):
        if valid[i]:
            ax.annotate(asset, (autocorrs[i], vt_alphas[i]), fontsize=7)
    rho_val = mech['autocorr_vs_vt_alpha']['rho']
    p_val = mech['autocorr_vs_vt_alpha']['p']
    ax.set_title(f'(4) Autocorr -> VT Alpha\nrho={rho_val:.3f} (p={p_val:.4f})' if rho_val is not None else '(4) Autocorr -> VT Alpha', fontsize=10)
    ax.set_xlabel('Autocorr(lag=1)')
    ax.set_ylabel('VT Alpha (ann.)')
    ax.axhline(y=0, color='gray', linestyle=':', alpha=0.5)
    ax.grid(True, alpha=0.3)

    # (5) VIX-return corr -> MDD improvement
    ax = axes[1, 1]
    ax.scatter(vix_corrs[valid_vc], mdd_improvements[valid_vc], s=80, c='crimson', edgecolors='darkred', zorder=5)
    for i, asset in enumerate(assets):
        if valid_vc[i]:
            ax.annotate(asset, (vix_corrs[i], mdd_improvements[i]), fontsize=7)
    rho_val = mech['vix_corr_vs_mdd_improvement']['rho']
    p_val = mech['vix_corr_vs_mdd_improvement']['p']
    ax.set_title(f'(5) VIX-Ret Corr -> MDD Improve\nrho={rho_val:.3f} (p={p_val:.4f})' if rho_val is not None else '(5) VIX-Ret Corr -> MDD Improve', fontsize=10)
    ax.set_xlabel('Corr(Return, dVIX)')
    ax.set_ylabel('MDD Improvement')
    ax.grid(True, alpha=0.3)

    # (6) LOO stability
    ax = axes[1, 2]
    loo = results['leave_one_out']
    loo_assets = [l['removed_asset'] for l in loo]
    loo_deltas = [l['delta_rho_alpha'] for l in loo]
    colors_loo = ['red' if abs(d) > 0.15 else 'steelblue' for d in loo_deltas]
    ax.barh(loo_assets, loo_deltas, color=colors_loo, edgecolor='black', alpha=0.8)
    ax.set_xlabel('Delta rho (gamma vs VT alpha)')
    ax.set_title('(6) LOO Stability\n(red = influential, |delta|>0.15)', fontsize=10)
    ax.axvline(x=0, color='black', lw=0.5)
    ax.axvline(x=0.15, color='red', linestyle='--', alpha=0.5)
    ax.axvline(x=-0.15, color='red', linestyle='--', alpha=0.5)
    ax.grid(True, alpha=0.3, axis='x')

    plt.suptitle('K1044: Mechanism Decomposition — Gamma -> VT Alpha Causal Channels', fontsize=14, fontweight='bold', y=1.02)
    plt.tight_layout()
    plot2_path = os.path.join(RESULTS_DIR, 'k1044_mechanism_decomposition.png')
    plt.savefig(plot2_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Plot 2 saved: {plot2_path}")

    return plot1_path, plot2_path


# ============================================================
# Main
# ============================================================
def main():
    print("=" * 60)
    print("K1044: Gamma-VT Causal Panel Test")
    print("Cross-Asset Causal Verification (N=13)")
    print("=" * 60)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Assets: {ASSETS}")
    print(f"OOS: {OOS_START} ~ {END_DATE}")
    print(f"GARCH: window={GARCH_WINDOW}, refit={GARCH_REFIT}")
    print(f"VT: 12/VIX, cap={VT_CAP}, signal.shift(1)")
    print(f"Bootstrap: {BOOTSTRAP_REPS} reps, seed=42")
    print()

    # Step 0: Download
    asset_data, vix_close = download_data()

    # Step 1 & 2: Estimate gamma + VT for each asset
    panel_data = {}

    print("\n" + "=" * 60)
    print("Step 1-2: Gamma estimation + VT metrics")
    print("=" * 60)

    for asset in ASSETS:
        if asset not in asset_data:
            print(f"\n{asset}: skipped (no data)")
            continue

        print(f"\n--- {asset} ---")
        ret = asset_data[asset]['returns']

        # Estimate gamma
        print(f"  Estimating GJR-GARCH gamma (window={GARCH_WINDOW})...")
        avg_gamma, std_gamma, gamma_ts = estimate_gamma(ret)

        if np.isnan(avg_gamma):
            print(f"  FAILED: could not estimate gamma")
            continue

        print(f"  Gamma: {avg_gamma:.4f} +/- {std_gamma:.4f}")

        # VT metrics
        print(f"  Computing VT metrics...")
        vt_metrics = compute_vt_metrics(ret, vix_close)

        if vt_metrics is None:
            print(f"  FAILED: insufficient OOS data for VT")
            continue

        # Autocorrelation
        ac = compute_autocorrelation(ret)

        # VIX-return correlation
        vrc = compute_vix_return_corr(ret, vix_close)

        print(f"  BH: Sharpe={vt_metrics['bh_sharpe']:.3f}, MDD={vt_metrics['bh_mdd']:.3f}")
        print(f"  VT: Sharpe={vt_metrics['vt_sharpe']:.3f}, MDD={vt_metrics['vt_mdd']:.3f}")
        print(f"  VT Alpha={vt_metrics['vt_alpha']:.4f}, Sharpe Diff={vt_metrics['sharpe_diff']:.3f}")
        print(f"  MDD Improvement={vt_metrics['mdd_improvement']:.3f}")
        print(f"  Autocorr(1)={ac:.4f}, VIX-Return Corr={vrc:.4f}")

        panel_data[asset] = {
            'gamma': avg_gamma,
            'gamma_std': std_gamma,
            'n_gamma_estimates': len(gamma_ts),
            'autocorr_lag1': ac,
            'vix_return_corr': vrc,
            **vt_metrics,
        }

    n_assets = len(panel_data)
    print(f"\n\nPanel data: {n_assets} assets successfully processed")

    if n_assets < 7:
        print("ERROR: Need at least 7 assets for cross-sectional analysis (preamble rule)")
        return

    # Step 3-4: Cross-sectional analysis
    print("\n" + "=" * 60)
    print("Step 3-4: Cross-Sectional Analysis")
    print("=" * 60)

    cs_results = cross_sectional_analysis(panel_data)

    # Step 5: Generate plots
    print("\n" + "=" * 60)
    print("Step 5: Generate Plots")
    print("=" * 60)

    plot1_path, plot2_path = generate_plots(panel_data, cs_results)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    corrs = cs_results['correlations']
    ci = cs_results['bootstrap_ci']
    mech = cs_results['mechanism_decomposition']

    print(f"\n1. Core Result: Gamma vs VT Alpha")
    print(f"   Spearman rho = {corrs['gamma_vs_vt_alpha']['spearman_rho']:.3f} (p={corrs['gamma_vs_vt_alpha']['spearman_p']:.4f})")
    print(f"   Bootstrap 95% CI: [{ci['gamma_vs_vt_alpha_95ci'][0]:.3f}, {ci['gamma_vs_vt_alpha_95ci'][1]:.3f}]")
    print(f"   K53 original: r=0.564 (N=22)")
    print(f"   K1044 result: N={n_assets}")

    print(f"\n2. Sharpe vs MDD channels:")
    print(f"   Gamma vs Sharpe diff: rho = {corrs['gamma_vs_sharpe_diff']['spearman_rho']:.3f}")
    print(f"   Gamma vs MDD improve: rho = {corrs['gamma_vs_mdd_improvement']['spearman_rho']:.3f}")

    print(f"\n3. Mechanism decomposition:")
    for key, label in [('gamma_vs_autocorr', 'Gamma->Autocorr'),
                       ('gamma_vs_vix_return_corr', 'Gamma->VIX-Ret Corr'),
                       ('autocorr_vs_vt_alpha', 'Autocorr->VT Alpha'),
                       ('vix_corr_vs_vt_alpha', 'VIX-Corr->VT Alpha')]:
        r = mech[key]['rho']
        p = mech[key]['p']
        if r is not None:
            sig = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.1 else "ns"
            print(f"   {label:30s}: rho={r:.3f} (p={p:.4f}) {sig}")

    print(f"\n4. LOO stability:")
    influential = [l for l in cs_results['leave_one_out'] if abs(l['delta_rho_alpha']) > 0.15]
    if influential:
        print(f"   Influential assets: {', '.join([l['removed_asset'] for l in influential])}")
    else:
        print(f"   No influential assets (all |delta| < 0.15) = STABLE")

    # Determine conclusions
    rho_core = corrs['gamma_vs_vt_alpha']['spearman_rho']
    p_core = corrs['gamma_vs_vt_alpha']['spearman_p']
    rho_sharpe = corrs['gamma_vs_sharpe_diff']['spearman_rho']
    rho_mdd = corrs['gamma_vs_mdd_improvement']['spearman_rho']

    # Assess which channel is stronger
    momentum_strength = abs(mech['gamma_vs_autocorr']['rho'] or 0) * abs(mech['autocorr_vs_vt_alpha']['rho'] or 0)
    sizing_strength = abs(mech['gamma_vs_vix_return_corr']['rho'] or 0) * abs(mech['vix_corr_vs_vt_alpha']['rho'] or 0)

    dominant_channel = 'momentum' if momentum_strength > sizing_strength else 'sizing'

    print(f"\n5. Channel strength:")
    print(f"   Momentum (gamma->autocorr->alpha): {momentum_strength:.4f}")
    print(f"   Sizing (gamma->vix_corr->alpha):   {sizing_strength:.4f}")
    print(f"   Dominant channel: {dominant_channel}")

    # Conclusion
    if p_core < 0.05:
        conclusion = f"CONFIRMED: Gamma-VT alpha correlation is significant (rho={rho_core:.3f}, p={p_core:.4f}) at N={n_assets}"
    elif p_core < 0.10:
        conclusion = f"MARGINAL: Gamma-VT alpha correlation is marginally significant (rho={rho_core:.3f}, p={p_core:.4f}) at N={n_assets}"
    else:
        conclusion = f"NOT CONFIRMED: Gamma-VT alpha correlation is not significant (rho={rho_core:.3f}, p={p_core:.4f}) at N={n_assets}"

    print(f"\n{'='*60}")
    print(f"CONCLUSION: {conclusion}")
    print(f"{'='*60}")

    # Build asset summary table
    asset_table = []
    for asset in panel_data:
        d = panel_data[asset]
        asset_table.append({
            'asset': asset,
            'gamma': round(d['gamma'], 4),
            'gamma_std': round(d['gamma_std'], 4),
            'vt_alpha': round(d['vt_alpha'], 4),
            'sharpe_diff': round(d['sharpe_diff'], 3),
            'mdd_improvement': round(d['mdd_improvement'], 3),
            'autocorr_lag1': round(d['autocorr_lag1'], 4),
            'vix_return_corr': round(d['vix_return_corr'], 4),
            'bh_sharpe': round(d['bh_sharpe'], 3),
            'vt_sharpe': round(d['vt_sharpe'], 3),
            'bh_mdd': round(d['bh_mdd'], 3),
            'vt_mdd': round(d['vt_mdd'], 3),
            'n_obs_oos': d['n_obs_oos'],
        })

    # Save results
    full_results = {
        'experiment_id': 'K1044',
        'title': 'Gamma-VT Causal Panel Test (Cross-Asset Causal Verification)',
        'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'config': {
            'assets': ASSETS,
            'n_assets_processed': n_assets,
            'start_date': START_DATE,
            'end_date': END_DATE,
            'oos_start': OOS_START,
            'garch_window': GARCH_WINDOW,
            'garch_refit': GARCH_REFIT,
            'vt_formula': '12/VIX',
            'vt_cap': VT_CAP,
            'vt_lag': 'signal.shift(1)',
            'bootstrap_reps': BOOTSTRAP_REPS,
            'seed': 42,
        },
        'data_source': 'yfinance (daily adjusted close) + ^VIX',
        'asset_panel': asset_table,
        'cross_sectional_results': cs_results,
        'conclusion': conclusion,
        'dominant_channel': dominant_channel,
        'channel_strengths': {
            'momentum_path': momentum_strength,
            'sizing_path': sizing_strength,
        },
        'comparison_with_prior': {
            'K53_r': 0.564,
            'K53_N': 22,
            'K1044_rho': rho_core,
            'K1044_N': n_assets,
            'N145_rho_sharpe': -0.264,
            'K1044_rho_sharpe': rho_sharpe,
        },
        'plots': [
            'k1044_gamma_vt_scatter.png',
            'k1044_mechanism_decomposition.png',
        ],
        'references': [
            'Moreira & Muir (2017) Volatility-Managed Portfolios, JF',
            'Engle & Ng (1993) Measuring and Testing the Impact of News on Volatility, JF',
            'Glosten, Jagannathan & Runkle (1993) GJR-GARCH, JF',
            'Hood & Raughtigan (2025) VT = trend following',
        ],
        'limitations': [
            f'Cross-sectional N={n_assets} is small; Spearman test has low power',
            'VIX is US-specific; non-US assets use US VIX as sizing proxy',
            '0050.TW may have data quality issues despite cleaning',
            'BTC has shorter history (from 2014)',
            'USO has structural contango/roll issues',
            'Causality cannot be established from cross-sectional correlation alone',
            'VT alpha depends on the specific VT formula (12/VIX, cap=1.5)',
        ],
    }

    results_path = os.path.join(RESULTS_DIR, 'k1044_results.json')
    with open(results_path, 'w') as f:
        json.dump(full_results, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved: {results_path}")

    # Print asset table
    print("\n\nAsset Panel Summary:")
    print(f"{'Asset':10s} {'Gamma':>8s} {'VT_Alpha':>10s} {'Sharpe_D':>10s} {'MDD_Imp':>10s} {'AC(1)':>8s} {'VIX_Corr':>10s}")
    print("-" * 72)
    for row in sorted(asset_table, key=lambda x: x['gamma'], reverse=True):
        print(f"{row['asset']:10s} {row['gamma']:8.4f} {row['vt_alpha']:10.4f} {row['sharpe_diff']:10.3f} {row['mdd_improvement']:10.3f} {row['autocorr_lag1']:8.4f} {row['vix_return_corr']:10.4f}")


if __name__ == '__main__':
    main()
