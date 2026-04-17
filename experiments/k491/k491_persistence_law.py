"""
K491: Universal Volatility Persistence Law — Cross-Asset Analysis
=================================================================

Background:
  GARCH persistence (α + γ/2 + β) is the key parameter governing how quickly
  volatility shocks decay. Prior findings:
  - K435: SPY persistence=0.970 (full-sample), per-regime mean=0.897 (Hillebrand inflation +0.073)
  - K483: USO inverted leverage, GLD weak leverage
  - K445: BTC gamma regime-dependent
  - T37: Vol clustering duration follows power-law α=2.6-3.1 across 5 assets (universal)
  - K132: GLD QLIKE capture rate only 19.4% (vs SPY 62.7%)
  - Paper 1: Cross-asset evidence on leverage direction

Research Questions:
  1. Is persistence correlated with asset's market cap / liquidity / vol level?
  2. Is persistence correlated with leverage effect (gamma)?
  3. Is there a cross-sectional universal persistence range?
  4. Does rolling persistence show co-movement across assets?

Assets (15, spanning all asset classes):
  US Equity: SPY, QQQ, IWM, XLE, XLF
  International Equity: EEM, EWT, EWJ
  Bonds: TLT, HYG
  Commodities: GLD, USO
  Crypto: BTC-USD
  FX: UUP
  (VIX excluded — not tradable, different dynamics)

Analysis:
  1. Full-sample GJR-GARCH(1,1) for each asset → persistence, gamma, AIC, diagnostics
  2. Cross-sectional: mean/std/range of persistence, corr(persistence, gamma), etc.
  3. Rolling persistence (504-day window) → time-varying persistence, cross-asset correlation
  4. Hillebrand test: compare full-sample vs mean of rolling estimates

Models:
  GJR-GARCH(1,1) with Student-t errors — standard specification across all assets

Evaluation:
  - Descriptive statistics (mean, std, skew, kurtosis) of returns per asset
  - ADF stationarity test, ARCH-LM test
  - GJR parameter estimates with standard errors
  - Cross-sectional correlation analysis
  - Rolling persistence time series

References:
  - Hillebrand (2005) "Neglecting parameter changes in GARCH models" J Econometrics
  - Glosten, Jagannathan, Runkle (1993) "On the Relation between..." JF
  - Engle & Bollerslev (1986) "Modelling the Persistence of Conditional Variances" Econometric Reviews
  - Lamoureux & Lastrapes (1990) "Persistence in Variance, Structural Change..." JBES
  - Mikosch & Starica (2004) "Nonstationarities in Financial Time Series" Rev Econ Stat
  - Black (1976) "Studies of Stock Price Volatility Changes" — leverage effect
  - K435, K483, K445, T37 — prior findings

Data: yfinance, 2010-01-01 to present (to ensure all ETFs have data)
Author: [Proposed: User(persistence law), Executed: Claude]
"""

import json
import warnings
import time
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from scipy import stats
from arch import arch_model
import statsmodels.api as sm
from statsmodels.tsa.stattools import adfuller
from statsmodels.stats.diagnostic import het_arch

warnings.filterwarnings('ignore')

t_start = time.time()

# =============================================================================
# 1. DATA COLLECTION
# =============================================================================

ASSETS = {
    # US equity
    'SPY': 'US Large Cap',
    'QQQ': 'US Tech',
    'IWM': 'US Small Cap',
    'XLE': 'US Energy',
    'XLF': 'US Financials',
    # International equity
    'EEM': 'Emerging Markets',
    'EWT': 'Taiwan',
    'EWJ': 'Japan',
    # Bonds
    'TLT': 'Long-term Bond',
    'HYG': 'High Yield',
    # Commodities
    'GLD': 'Gold',
    'USO': 'Oil',
    # Crypto
    'BTC-USD': 'Bitcoin',
    # FX
    'UUP': 'US Dollar',
}

DATA_START = '2010-01-01'
DATA_END = '2026-03-25'
ROLLING_WINDOW = 504  # ~2 years trading days

print("=" * 80)
print("K491: Universal Volatility Persistence Law — Cross-Asset Analysis")
print("=" * 80)
print(f"\nAssets: {len(ASSETS)}")
print(f"Data period: {DATA_START} to {DATA_END}")
print(f"Rolling window: {ROLLING_WINDOW} days")

# Download all data
print("\n--- Downloading data ---")
all_returns = {}
asset_stats = {}

for ticker, label in ASSETS.items():
    try:
        df = yf.download(ticker, start=DATA_START, end=DATA_END, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if len(df) < 1000:
            print(f"  {ticker} ({label}): Only {len(df)} obs — SKIPPING (need >= 1000)")
            continue

        ret = 100 * np.log(df['Close'] / df['Close'].shift(1)).dropna()
        ret = ret.replace([np.inf, -np.inf], np.nan).dropna()
        all_returns[ticker] = ret

        # Descriptive statistics
        asset_stats[ticker] = {
            'label': label,
            'n_obs': len(ret),
            'start': str(ret.index[0].date()),
            'end': str(ret.index[-1].date()),
            'mean': float(ret.mean()),
            'std': float(ret.std()),
            'skew': float(ret.skew()),
            'kurtosis': float(ret.kurtosis()),  # excess kurtosis
            'min': float(ret.min()),
            'max': float(ret.max()),
            'mean_abs_ret': float(ret.abs().mean()),
        }

        # ADF test
        adf_stat, adf_pval, _, _, _, _ = adfuller(ret.values, maxlag=20, autolag='AIC')
        asset_stats[ticker]['adf_stat'] = float(adf_stat)
        asset_stats[ticker]['adf_pval'] = float(adf_pval)

        # ARCH-LM test (5 lags)
        try:
            arch_lm_stat, arch_lm_pval, _, _ = het_arch(ret.values, nlags=5)
            asset_stats[ticker]['arch_lm_stat'] = float(arch_lm_stat)
            asset_stats[ticker]['arch_lm_pval'] = float(arch_lm_pval)
        except Exception:
            asset_stats[ticker]['arch_lm_stat'] = None
            asset_stats[ticker]['arch_lm_pval'] = None

        print(f"  {ticker} ({label}): {len(ret)} obs, mean={ret.mean():.4f}, "
              f"std={ret.std():.4f}, skew={ret.skew():.2f}, kurt={ret.kurtosis():.2f}")
    except Exception as e:
        print(f"  {ticker} ({label}): FAILED — {e}")

print(f"\nSuccessfully loaded: {len(all_returns)} / {len(ASSETS)} assets")

# =============================================================================
# 2. FULL-SAMPLE GJR-GARCH ESTIMATION
# =============================================================================

print("\n" + "=" * 80)
print("2. Full-Sample GJR-GARCH(1,1) Estimation")
print("=" * 80)

garch_results = {}

for ticker in all_returns:
    ret = all_returns[ticker]
    label = ASSETS[ticker]

    try:
        # GJR-GARCH(1,1) with Student-t
        am = arch_model(ret, vol='Garch', p=1, o=1, q=1, dist='t', mean='Constant')
        res = am.fit(disp='off', options={'maxiter': 500})

        params = res.params
        omega = float(params.get('omega', np.nan))
        alpha = float(params.get('alpha[1]', np.nan))
        gamma = float(params.get('gamma[1]', np.nan))
        beta = float(params.get('beta[1]', np.nan))
        nu = float(params.get('nu', np.nan))
        mu = float(params.get('mu', np.nan))

        persistence = alpha + gamma / 2.0 + beta

        # Standard errors
        se = res.std_err
        gamma_se = float(se.get('gamma[1]', np.nan))
        gamma_tstat = gamma / gamma_se if gamma_se > 0 else np.nan
        gamma_pval = 2 * (1 - stats.t.cdf(abs(gamma_tstat), df=len(ret) - len(params)))

        # Convergence
        converged = res.convergence_flag == 0

        # AIC / BIC
        aic = float(res.aic)
        bic = float(res.bic)
        loglik = float(res.loglikelihood)

        # Residual ARCH-LM test
        std_resid = res.resid / res.conditional_volatility
        std_resid_clean = std_resid.dropna()
        try:
            resid_arch_stat, resid_arch_pval, _, _ = het_arch(std_resid_clean.values, nlags=5)
        except Exception:
            resid_arch_stat, resid_arch_pval = np.nan, np.nan

        # Unconditional variance
        if persistence < 1:
            uncond_var = omega / (1 - persistence)
            uncond_vol = np.sqrt(uncond_var) if uncond_var > 0 else np.nan
        else:
            uncond_var = np.nan
            uncond_vol = np.nan

        # Half-life of variance shocks
        if 0 < persistence < 1:
            half_life = np.log(0.5) / np.log(persistence)
        else:
            half_life = np.nan

        garch_results[ticker] = {
            'label': label,
            'omega': omega,
            'alpha': alpha,
            'gamma': gamma,
            'beta': beta,
            'nu': nu,
            'mu': mu,
            'persistence': float(persistence),
            'gamma_se': gamma_se,
            'gamma_tstat': float(gamma_tstat),
            'gamma_pval': float(gamma_pval),
            'gamma_significant': bool(abs(gamma_tstat) > 1.96),
            'converged': converged,
            'aic': aic,
            'bic': bic,
            'loglikelihood': loglik,
            'resid_arch_lm_stat': float(resid_arch_stat),
            'resid_arch_lm_pval': float(resid_arch_pval),
            'resid_arch_clean': bool(resid_arch_pval > 0.05) if not np.isnan(resid_arch_pval) else None,
            'uncond_vol_annual': float(uncond_vol * np.sqrt(252)) if not np.isnan(uncond_vol) else None,
            'half_life_days': float(half_life),
        }

        gamma_sig = "***" if abs(gamma_tstat) > 2.576 else "**" if abs(gamma_tstat) > 1.96 else ""
        sign = "+" if gamma >= 0 else "-"
        print(f"  {ticker:8s} ({label:18s}): pers={persistence:.4f}, "
              f"gamma={gamma:+.4f} (t={gamma_tstat:+.2f}){gamma_sig}, "
              f"half-life={half_life:.1f}d, nu={nu:.2f}, "
              f"conv={'OK' if converged else 'FAIL'}")

    except Exception as e:
        print(f"  {ticker:8s} ({label:18s}): FAILED — {e}")
        garch_results[ticker] = {'label': label, 'error': str(e)}

# =============================================================================
# 3. CROSS-SECTIONAL ANALYSIS
# =============================================================================

print("\n" + "=" * 80)
print("3. Cross-Sectional Analysis")
print("=" * 80)

# Filter to successfully estimated assets
valid_tickers = [t for t in garch_results if 'persistence' in garch_results[t]]
n_valid = len(valid_tickers)

persistence_vals = np.array([garch_results[t]['persistence'] for t in valid_tickers])
gamma_vals = np.array([garch_results[t]['gamma'] for t in valid_tickers])
alpha_vals = np.array([garch_results[t]['alpha'] for t in valid_tickers])
beta_vals = np.array([garch_results[t]['beta'] for t in valid_tickers])
halflife_vals = np.array([garch_results[t]['half_life_days'] for t in valid_tickers])
nu_vals = np.array([garch_results[t]['nu'] for t in valid_tickers])

# Return characteristics
kurtosis_vals = np.array([asset_stats[t]['kurtosis'] for t in valid_tickers])
skew_vals = np.array([asset_stats[t]['skew'] for t in valid_tickers])
std_vals = np.array([asset_stats[t]['std'] for t in valid_tickers])
mean_abs_ret_vals = np.array([asset_stats[t]['mean_abs_ret'] for t in valid_tickers])

# Cross-sectional summary
cross_section = {
    'n_assets': n_valid,
    'persistence': {
        'mean': float(np.mean(persistence_vals)),
        'std': float(np.std(persistence_vals)),
        'min': float(np.min(persistence_vals)),
        'max': float(np.max(persistence_vals)),
        'median': float(np.median(persistence_vals)),
        'range': f"{float(np.min(persistence_vals)):.4f} - {float(np.max(persistence_vals)):.4f}",
        'iqr': float(np.percentile(persistence_vals, 75) - np.percentile(persistence_vals, 25)),
        'q25': float(np.percentile(persistence_vals, 25)),
        'q75': float(np.percentile(persistence_vals, 75)),
    },
    'gamma': {
        'mean': float(np.mean(gamma_vals)),
        'std': float(np.std(gamma_vals)),
        'min': float(np.min(gamma_vals)),
        'max': float(np.max(gamma_vals)),
        'n_positive': int(np.sum(gamma_vals > 0)),
        'n_negative': int(np.sum(gamma_vals < 0)),
        'n_significant': int(sum(1 for t in valid_tickers if garch_results[t].get('gamma_significant', False))),
    },
    'half_life': {
        'mean': float(np.nanmean(halflife_vals)),
        'std': float(np.nanstd(halflife_vals)),
        'min': float(np.nanmin(halflife_vals)),
        'max': float(np.nanmax(halflife_vals)),
        'median': float(np.nanmedian(halflife_vals)),
    },
}

print(f"\nPersistence across {n_valid} assets:")
print(f"  Mean:   {cross_section['persistence']['mean']:.4f}")
print(f"  Std:    {cross_section['persistence']['std']:.4f}")
print(f"  Range:  {cross_section['persistence']['range']}")
print(f"  Median: {cross_section['persistence']['median']:.4f}")
print(f"  IQR:    [{cross_section['persistence']['q25']:.4f}, {cross_section['persistence']['q75']:.4f}]")

print(f"\nGamma (leverage effect) across {n_valid} assets:")
print(f"  Mean:   {cross_section['gamma']['mean']:.4f}")
print(f"  Range:  [{cross_section['gamma']['min']:.4f}, {cross_section['gamma']['max']:.4f}]")
print(f"  Positive: {cross_section['gamma']['n_positive']}, Negative: {cross_section['gamma']['n_negative']}")
print(f"  Significant (|t|>1.96): {cross_section['gamma']['n_significant']} / {n_valid}")

print(f"\nHalf-life of volatility shocks:")
print(f"  Mean:   {cross_section['half_life']['mean']:.1f} days")
print(f"  Median: {cross_section['half_life']['median']:.1f} days")
print(f"  Range:  [{cross_section['half_life']['min']:.1f}, {cross_section['half_life']['max']:.1f}] days")

# Cross-sectional correlations
print("\n--- Cross-Sectional Correlations ---")
correlations = {}

def safe_corr(x, y, label):
    """Compute Spearman correlation with p-value, handle NaN."""
    mask = ~(np.isnan(x) | np.isnan(y))
    if mask.sum() < 5:
        return {'rho': np.nan, 'pval': np.nan, 'n': int(mask.sum())}
    rho, pval = stats.spearmanr(x[mask], y[mask])
    sig = "***" if pval < 0.01 else "**" if pval < 0.05 else "*" if pval < 0.10 else ""
    print(f"  {label:40s}: rho={rho:+.3f}, p={pval:.4f} {sig}")
    return {'rho': float(rho), 'pval': float(pval), 'n': int(mask.sum())}

correlations['persistence_vs_gamma'] = safe_corr(
    persistence_vals, gamma_vals, "Persistence vs Gamma")
correlations['persistence_vs_kurtosis'] = safe_corr(
    persistence_vals, kurtosis_vals, "Persistence vs Kurtosis")
correlations['persistence_vs_skewness'] = safe_corr(
    persistence_vals, skew_vals, "Persistence vs Skewness")
correlations['persistence_vs_volatility'] = safe_corr(
    persistence_vals, std_vals, "Persistence vs Return Std")
correlations['persistence_vs_mean_abs_ret'] = safe_corr(
    persistence_vals, mean_abs_ret_vals, "Persistence vs Mean |Return|")
correlations['persistence_vs_nu'] = safe_corr(
    persistence_vals, nu_vals, "Persistence vs Tail thickness (nu)")
correlations['persistence_vs_halflife'] = safe_corr(
    persistence_vals, halflife_vals, "Persistence vs Half-life")
correlations['gamma_vs_skewness'] = safe_corr(
    gamma_vals, skew_vals, "Gamma vs Return Skewness")
correlations['gamma_vs_kurtosis'] = safe_corr(
    gamma_vals, kurtosis_vals, "Gamma vs Kurtosis")
correlations['gamma_vs_volatility'] = safe_corr(
    gamma_vals, std_vals, "Gamma vs Return Std")

cross_section['correlations'] = correlations

# =============================================================================
# 4. ASSET CLASS GROUPING ANALYSIS
# =============================================================================

print("\n" + "=" * 80)
print("4. Asset Class Grouping Analysis")
print("=" * 80)

# Define groups
groups = {
    'US_Equity': ['SPY', 'QQQ', 'IWM', 'XLE', 'XLF'],
    'Intl_Equity': ['EEM', 'EWT', 'EWJ'],
    'Bonds': ['TLT', 'HYG'],
    'Commodities': ['GLD', 'USO'],
    'Crypto': ['BTC-USD'],
    'FX': ['UUP'],
}

group_stats = {}
for group_name, group_tickers in groups.items():
    valid_in_group = [t for t in group_tickers if t in garch_results and 'persistence' in garch_results[t]]
    if not valid_in_group:
        continue

    p_vals = [garch_results[t]['persistence'] for t in valid_in_group]
    g_vals = [garch_results[t]['gamma'] for t in valid_in_group]
    hl_vals = [garch_results[t]['half_life_days'] for t in valid_in_group]

    group_stats[group_name] = {
        'n': len(valid_in_group),
        'tickers': valid_in_group,
        'persistence_mean': float(np.mean(p_vals)),
        'persistence_std': float(np.std(p_vals)) if len(p_vals) > 1 else 0.0,
        'gamma_mean': float(np.mean(g_vals)),
        'half_life_mean': float(np.nanmean(hl_vals)),
    }

    print(f"\n  {group_name} (n={len(valid_in_group)}):")
    print(f"    Persistence: mean={np.mean(p_vals):.4f} ± {np.std(p_vals):.4f}")
    print(f"    Gamma:       mean={np.mean(g_vals):+.4f}")
    print(f"    Half-life:   mean={np.nanmean(hl_vals):.1f} days")
    for t in valid_in_group:
        r = garch_results[t]
        print(f"      {t:8s}: pers={r['persistence']:.4f}, gamma={r['gamma']:+.4f}, "
              f"HL={r['half_life_days']:.1f}d")

# Kruskal-Wallis test: does persistence differ by asset class?
# (non-parametric — small samples per group)
print("\n--- Kruskal-Wallis Test: Persistence by Asset Class ---")
kw_groups = []
kw_labels = []
for group_name, group_tickers in groups.items():
    valid_in_group = [t for t in group_tickers if t in garch_results and 'persistence' in garch_results[t]]
    if len(valid_in_group) >= 2:
        p_vals = [garch_results[t]['persistence'] for t in valid_in_group]
        kw_groups.append(p_vals)
        kw_labels.append(group_name)

if len(kw_groups) >= 2:
    kw_stat, kw_pval = stats.kruskal(*kw_groups)
    print(f"  H-statistic: {kw_stat:.3f}, p-value: {kw_pval:.4f}")
    print(f"  Groups tested: {kw_labels}")
    cross_section['kruskal_wallis'] = {
        'H_stat': float(kw_stat),
        'p_value': float(kw_pval),
        'groups': kw_labels,
        'significant': bool(kw_pval < 0.05),
    }
else:
    print("  Not enough groups with >= 2 members for KW test")
    cross_section['kruskal_wallis'] = None

# =============================================================================
# 5. ROLLING PERSISTENCE ANALYSIS
# =============================================================================

print("\n" + "=" * 80)
print("5. Rolling Persistence Analysis (window = 504 days)")
print("=" * 80)

rolling_results = {}
# Use step size to keep it fast: every 63 days (~quarterly)
STEP_SIZE = 63

for ticker in valid_tickers:
    ret = all_returns[ticker]
    label = ASSETS[ticker]
    n = len(ret)

    if n < ROLLING_WINDOW + 100:
        print(f"  {ticker}: Not enough data for rolling ({n} < {ROLLING_WINDOW + 100})")
        continue

    rolling_pers = []
    rolling_gamma = []
    rolling_dates = []
    n_failed = 0

    # Rolling windows with step
    starts = range(0, n - ROLLING_WINDOW, STEP_SIZE)

    for i in starts:
        window_ret = ret.iloc[i:i + ROLLING_WINDOW]
        window_date = ret.index[i + ROLLING_WINDOW - 1]

        try:
            am = arch_model(window_ret, vol='Garch', p=1, o=1, q=1, dist='t', mean='Constant')
            res = am.fit(disp='off', options={'maxiter': 300})

            a = float(res.params.get('alpha[1]', np.nan))
            g = float(res.params.get('gamma[1]', np.nan))
            b = float(res.params.get('beta[1]', np.nan))
            p = a + g / 2.0 + b

            if res.convergence_flag == 0 and 0 < p < 1.05:
                rolling_pers.append(p)
                rolling_gamma.append(g)
                rolling_dates.append(window_date)
            else:
                n_failed += 1
        except Exception:
            n_failed += 1

    if len(rolling_pers) >= 5:
        rolling_results[ticker] = {
            'dates': [str(d.date()) for d in rolling_dates],
            'persistence': rolling_pers,
            'gamma': rolling_gamma,
            'n_windows': len(rolling_pers),
            'n_failed': n_failed,
            'mean_rolling_pers': float(np.mean(rolling_pers)),
            'std_rolling_pers': float(np.std(rolling_pers)),
            'min_rolling_pers': float(np.min(rolling_pers)),
            'max_rolling_pers': float(np.max(rolling_pers)),
        }

        # Hillebrand inflation: full-sample persistence vs mean of rolling
        full_pers = garch_results[ticker]['persistence']
        mean_rolling = np.mean(rolling_pers)
        hillebrand_gap = full_pers - mean_rolling
        rolling_results[ticker]['hillebrand_gap'] = float(hillebrand_gap)

        print(f"  {ticker:8s}: {len(rolling_pers):3d} windows, "
              f"rolling mean={mean_rolling:.4f} ± {np.std(rolling_pers):.4f}, "
              f"full={full_pers:.4f}, Hillebrand gap={hillebrand_gap:+.4f}")
    else:
        print(f"  {ticker:8s}: Too few valid windows ({len(rolling_pers)})")

# =============================================================================
# 6. CROSS-ASSET PERSISTENCE CO-MOVEMENT
# =============================================================================

print("\n" + "=" * 80)
print("6. Cross-Asset Persistence Co-Movement")
print("=" * 80)

# Build aligned persistence time series
rolling_tickers = list(rolling_results.keys())
if len(rolling_tickers) >= 3:
    # Create DataFrame with dates as index
    pers_dfs = {}
    for t in rolling_tickers:
        idx = pd.to_datetime(rolling_results[t]['dates'])
        pers_dfs[t] = pd.Series(rolling_results[t]['persistence'], index=idx, name=t)

    # Merge on nearest date (quarterly aligned)
    pers_df = pd.DataFrame(pers_dfs)
    # Forward fill to handle misaligned dates (max 1 quarter gap)
    pers_df = pers_df.sort_index()

    # Pairwise correlation of rolling persistence
    pers_corr = pers_df.corr(method='spearman')

    # Extract upper triangle
    co_movement = {}
    n_pairs = 0
    total_corr = 0.0
    sig_positive = 0

    for i, t1 in enumerate(rolling_tickers):
        for j, t2 in enumerate(rolling_tickers):
            if j <= i:
                continue

            # Compute on overlapping non-NaN
            overlap = pers_df[[t1, t2]].dropna()
            if len(overlap) >= 5:
                rho, pval = stats.spearmanr(overlap[t1], overlap[t2])
                pair_key = f"{t1}_vs_{t2}"
                co_movement[pair_key] = {
                    'rho': float(rho),
                    'pval': float(pval),
                    'n_overlap': len(overlap),
                }
                n_pairs += 1
                total_corr += rho
                if rho > 0 and pval < 0.05:
                    sig_positive += 1

    mean_co_movement = total_corr / n_pairs if n_pairs > 0 else np.nan

    print(f"\n  Pairwise correlations of rolling persistence:")
    print(f"  Total pairs: {n_pairs}")
    print(f"  Mean Spearman rho: {mean_co_movement:.3f}")
    print(f"  Significantly positive (p<0.05): {sig_positive} / {n_pairs}")

    # Top 5 and bottom 5
    sorted_pairs = sorted(co_movement.items(), key=lambda x: x[1]['rho'], reverse=True)
    print(f"\n  Top 5 co-moving pairs:")
    for pair, vals in sorted_pairs[:5]:
        sig = "***" if vals['pval'] < 0.01 else "**" if vals['pval'] < 0.05 else ""
        print(f"    {pair:25s}: rho={vals['rho']:+.3f} {sig}")

    print(f"\n  Bottom 5 (least co-moving):")
    for pair, vals in sorted_pairs[-5:]:
        sig = "***" if vals['pval'] < 0.01 else "**" if vals['pval'] < 0.05 else ""
        print(f"    {pair:25s}: rho={vals['rho']:+.3f} {sig}")

    cross_section['persistence_co_movement'] = {
        'n_pairs': n_pairs,
        'mean_rho': float(mean_co_movement),
        'sig_positive_pairs': sig_positive,
        'top_5': {k: v for k, v in sorted_pairs[:5]},
        'bottom_5': {k: v for k, v in sorted_pairs[-5:]},
    }
else:
    print("  Not enough assets with rolling results for co-movement analysis")
    co_movement = {}

# =============================================================================
# 7. HILLEBRAND INFLATION ANALYSIS
# =============================================================================

print("\n" + "=" * 80)
print("7. Hillebrand (2005) Persistence Inflation Analysis")
print("=" * 80)

hillebrand_data = {}
gaps = []
for t in rolling_results:
    if 'hillebrand_gap' in rolling_results[t]:
        gap = rolling_results[t]['hillebrand_gap']
        gaps.append(gap)
        hillebrand_data[t] = {
            'full_sample_persistence': garch_results[t]['persistence'],
            'mean_rolling_persistence': rolling_results[t]['mean_rolling_pers'],
            'hillebrand_gap': gap,
        }

if gaps:
    gaps_arr = np.array(gaps)
    # One-sample t-test: is mean gap > 0?
    t_stat, t_pval = stats.ttest_1samp(gaps_arr, 0)

    hillebrand_summary = {
        'mean_gap': float(np.mean(gaps_arr)),
        'std_gap': float(np.std(gaps_arr)),
        'median_gap': float(np.median(gaps_arr)),
        'min_gap': float(np.min(gaps_arr)),
        'max_gap': float(np.max(gaps_arr)),
        'n_positive': int(np.sum(gaps_arr > 0)),
        'n_negative': int(np.sum(gaps_arr < 0)),
        'n_total': len(gaps_arr),
        'ttest_stat': float(t_stat),
        'ttest_pval': float(t_pval),
        'significant_inflation': bool(t_pval < 0.05 and np.mean(gaps_arr) > 0),
    }

    print(f"\n  N assets: {len(gaps_arr)}")
    print(f"  Mean Hillebrand gap: {np.mean(gaps_arr):+.4f}")
    print(f"  Std:                 {np.std(gaps_arr):.4f}")
    print(f"  Median:              {np.median(gaps_arr):+.4f}")
    print(f"  Range:               [{np.min(gaps_arr):+.4f}, {np.max(gaps_arr):+.4f}]")
    print(f"  Positive gaps:       {np.sum(gaps_arr > 0)} / {len(gaps_arr)}")
    print(f"  t-test (gap > 0):    t={t_stat:.3f}, p={t_pval:.4f}")
    print(f"  Significant inflation: {'YES' if hillebrand_summary['significant_inflation'] else 'NO'}")

    print(f"\n  Per-asset Hillebrand gaps:")
    for t in sorted(hillebrand_data, key=lambda x: hillebrand_data[x]['hillebrand_gap'], reverse=True):
        d = hillebrand_data[t]
        print(f"    {t:8s}: full={d['full_sample_persistence']:.4f}, "
              f"roll_mean={d['mean_rolling_persistence']:.4f}, "
              f"gap={d['hillebrand_gap']:+.4f}")
else:
    hillebrand_summary = None
    print("  No rolling results available for Hillebrand analysis")

# =============================================================================
# 8. RANKING TABLE
# =============================================================================

print("\n" + "=" * 80)
print("8. Persistence Ranking Table (sorted by persistence)")
print("=" * 80)

ranking = sorted(valid_tickers, key=lambda t: garch_results[t]['persistence'], reverse=True)

print(f"\n  {'Rank':4s} {'Ticker':8s} {'Label':18s} {'Pers':8s} {'Gamma':8s} {'t(γ)':8s} "
      f"{'HL(d)':8s} {'nu':6s} {'Skew':8s} {'Kurt':8s} {'σ(%)':8s}")
print("  " + "-" * 100)

for i, t in enumerate(ranking):
    r = garch_results[t]
    s = asset_stats[t]
    gamma_sig = "***" if abs(r['gamma_tstat']) > 2.576 else "**" if abs(r['gamma_tstat']) > 1.96 else ""
    print(f"  {i+1:4d} {t:8s} {r['label']:18s} {r['persistence']:8.4f} {r['gamma']:+8.4f} "
          f"{r['gamma_tstat']:+7.2f}{gamma_sig:3s} {r['half_life_days']:7.1f} {r['nu']:6.2f} "
          f"{s['skew']:+8.2f} {s['kurtosis']:8.2f} {s['std']:8.4f}")

# =============================================================================
# 9. COMPILE RESULTS
# =============================================================================

elapsed = time.time() - t_start
print(f"\n{'=' * 80}")
print(f"Total runtime: {elapsed:.1f} seconds")
print(f"{'=' * 80}")

# Summary conclusions
conclusions = []

# 1. Universal range?
p_mean = cross_section['persistence']['mean']
p_std = cross_section['persistence']['std']
p_min = cross_section['persistence']['min']
p_max = cross_section['persistence']['max']
conclusions.append(f"Persistence range: [{p_min:.4f}, {p_max:.4f}], mean={p_mean:.4f} ± {p_std:.4f}")

if p_std < 0.05:
    conclusions.append("Very tight clustering — suggestive of a universal persistence law")
elif p_std < 0.10:
    conclusions.append("Moderate clustering — partially universal, asset-class differences exist")
else:
    conclusions.append("Wide dispersion — no universal persistence law, asset-specific dynamics")

# 2. Hillebrand
if hillebrand_summary:
    if hillebrand_summary['significant_inflation']:
        conclusions.append(f"Hillebrand inflation CONFIRMED: mean gap={hillebrand_summary['mean_gap']:+.4f} "
                          f"(t={hillebrand_summary['ttest_stat']:.2f}, p={hillebrand_summary['ttest_pval']:.4f})")
    else:
        conclusions.append(f"Hillebrand inflation NOT significant: mean gap={hillebrand_summary['mean_gap']:+.4f} "
                          f"(p={hillebrand_summary['ttest_pval']:.4f})")

# 3. Co-movement
if 'persistence_co_movement' in cross_section:
    cm = cross_section['persistence_co_movement']
    conclusions.append(f"Persistence co-movement: mean rho={cm['mean_rho']:.3f}, "
                      f"{cm['sig_positive_pairs']}/{cm['n_pairs']} pairs significantly positive")

# 4. Gamma relationship
if 'persistence_vs_gamma' in correlations:
    c = correlations['persistence_vs_gamma']
    conclusions.append(f"Persistence vs Gamma: rho={c['rho']:+.3f}, p={c['pval']:.4f}")

print("\n--- KEY CONCLUSIONS ---")
for c in conclusions:
    print(f"  • {c}")

# Build results JSON
results = {
    'experiment_id': 'K491',
    'title': 'Universal Volatility Persistence Law — Cross-Asset Analysis',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'runtime_seconds': float(elapsed),
    'data_source': 'yfinance',
    'data_period': f'{DATA_START} to {DATA_END}',
    'rolling_window': ROLLING_WINDOW,
    'rolling_step': STEP_SIZE,
    'n_assets_attempted': len(ASSETS),
    'n_assets_successful': n_valid,
    'methodology': {
        'model': 'GJR-GARCH(1,1) with Student-t errors',
        'persistence_formula': 'alpha + gamma/2 + beta',
        'rolling_window': f'{ROLLING_WINDOW} trading days (~2 years)',
        'rolling_step': f'{STEP_SIZE} trading days (~quarterly)',
        'correlations': 'Spearman rank correlation',
    },
    'references': [
        'Hillebrand (2005) "Neglecting parameter changes in GARCH models" J Econometrics',
        'Glosten, Jagannathan, Runkle (1993) "On the Relation between..." JF',
        'Engle & Bollerslev (1986) "Modelling the Persistence of Conditional Variances"',
        'Lamoureux & Lastrapes (1990) "Persistence in Variance, Structural Change..." JBES',
        'Mikosch & Starica (2004) "Nonstationarities in Financial Time Series"',
        'Black (1976) "Studies of Stock Price Volatility Changes"',
    ],
    'prior_findings': [
        'K435: SPY persistence=0.970 (full), per-regime mean=0.897 (Hillebrand gap +0.073)',
        'K483: USO inverted leverage, GLD weak leverage',
        'K445: BTC gamma regime-dependent',
        'T37: Vol clustering duration power-law α=2.6-3.1 across 5 assets (universal)',
    ],
    'asset_descriptive_stats': asset_stats,
    'garch_estimates': garch_results,
    'cross_sectional_analysis': cross_section,
    'group_analysis': group_stats,
    'rolling_persistence': {
        t: {k: v for k, v in rolling_results[t].items() if k not in ('dates', 'persistence', 'gamma')}
        for t in rolling_results
    },
    'rolling_persistence_timeseries': {
        t: {
            'dates': rolling_results[t]['dates'],
            'persistence': [round(p, 6) for p in rolling_results[t]['persistence']],
            'gamma': [round(g, 6) for g in rolling_results[t]['gamma']],
        }
        for t in rolling_results
    },
    'hillebrand_analysis': {
        'per_asset': hillebrand_data,
        'summary': hillebrand_summary,
    },
    'co_movement': co_movement if co_movement else None,
    'conclusions': conclusions,
    'ranking': [
        {
            'rank': i + 1,
            'ticker': t,
            'label': garch_results[t]['label'],
            'persistence': garch_results[t]['persistence'],
            'gamma': garch_results[t]['gamma'],
            'gamma_tstat': garch_results[t]['gamma_tstat'],
            'half_life_days': garch_results[t]['half_life_days'],
        }
        for i, t in enumerate(ranking)
    ],
}

# Save
output_path = 'experiments/k491_persistence_law_results.json'
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\nResults saved to {output_path}")
print("DONE.")
