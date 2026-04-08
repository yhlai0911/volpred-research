#!/usr/bin/env python3
"""
K929: Asymmetric Volatility Transmission SPY→0050.TW
Fear Contagion vs Greed Diffusion

Builds on K919 (Gap channel dominates 99.7%, beta=0.472).
Tests whether negative SPY returns transmit more strongly to 0050.TW
overnight gaps than positive SPY returns.

Data: yfinance (SPY, 0050.TW, ^VIX), 2012-2026
Error log rules: 0050.TW must use clean_tw50_data, fixed seed=42

References:
- Engle & Ng (1993): News Impact Curves
- Glosten, Jagannathan & Runkle (1993): GJR-GARCH asymmetry
- Baele (2005): Volatility spillover in equity markets
- Bekaert, Ehrmann, Fratzscher & Mehl (2014): Global crises and equity market contagion
"""

import json
import sys
import os
import warnings
warnings.filterwarnings('ignore')

import numpy as np
np.random.seed(42)

import pandas as pd
import yfinance as yf
from scipy import stats
import statsmodels.api as sm
from datetime import datetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from volpred.utils import clean_tw50_data


def fetch_data():
    """Fetch SPY, 0050.TW, and VIX data."""
    print("=== Fetching data ===")

    spy = yf.download('SPY', start='2012-01-01', end='2026-04-05', progress=False)
    tw50 = yf.download('0050.TW', start='2012-01-01', end='2026-04-05', progress=False)
    vix = yf.download('^VIX', start='2012-01-01', end='2026-04-05', progress=False)

    # Handle multi-level columns from yfinance
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    if isinstance(tw50.columns, pd.MultiIndex):
        tw50.columns = tw50.columns.get_level_values(0)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)

    # Clean 0050.TW data
    tw50_close_clean, _ = clean_tw50_data(tw50['Close'])
    tw50['Close'] = tw50_close_clean
    # Also clean Open for gap calculation
    tw50_open_clean, _ = clean_tw50_data(tw50['Open'])
    tw50['Open'] = tw50_open_clean

    print(f"SPY: {len(spy)} days ({spy.index[0].strftime('%Y-%m-%d')} to {spy.index[-1].strftime('%Y-%m-%d')})")
    print(f"0050.TW: {len(tw50)} days ({tw50.index[0].strftime('%Y-%m-%d')} to {tw50.index[-1].strftime('%Y-%m-%d')})")
    print(f"VIX: {len(vix)} days")

    return spy, tw50, vix


def compute_returns_and_gaps(spy, tw50, vix):
    """Compute SPY returns, 0050.TW overnight gaps, and align dates."""
    print("\n=== Computing returns and gaps ===")

    # SPY close-to-close log return
    spy_ret = np.log(spy['Close'] / spy['Close'].shift(1))
    spy_ret.name = 'spy_ret'

    # 0050.TW overnight gap: log(Open_t / Close_{t-1})
    tw_gap = np.log(tw50['Open'] / tw50['Close'].shift(1))
    tw_gap.name = 'tw_gap'

    # VIX close
    vix_close = vix['Close'].copy()
    vix_close.name = 'vix'

    # Create aligned dataframe
    # SPY return at t → 0050.TW gap at t+1
    # So we need SPY(t) and TW_gap(t+1) on the same row
    # Shift tw_gap back by finding next available TW trading day after each SPY day

    # Alternative approach: for each TW trading day, find the most recent SPY return
    # This handles different trading calendars

    df = pd.DataFrame({
        'tw_gap': tw_gap,
        'tw_close': tw50['Close'],
        'tw_open': tw50['Open']
    })

    # For each TW trading day, get the most recent SPY return
    # Taiwan opens after US closes, so TW day t gap reflects SPY day t-1 close
    # More precisely: TW opens at 9:00 AM Taipei (1:00 AM UTC)
    # US closes at 4:00 PM ET (8:00 PM UTC previous day, or 9:00 PM in winter)
    # So TW gap on day t reflects SPY close on day t-1 (US calendar)

    # We forward-fill SPY returns to handle TW trading days when US is closed
    spy_ret_ff = spy_ret.reindex(df.index, method='ffill')
    vix_ff = vix_close.reindex(df.index, method='ffill')

    # SPY return should be shifted: use previous day's SPY return to predict today's TW gap
    # spy_ret_ff is already the most recent SPY return as of each TW date
    # But we need the PREVIOUS SPY trading day's return
    df['spy_ret_prev'] = spy_ret_ff.shift(1)  # Previous day's most recent SPY return
    df['vix'] = vix_ff.shift(1)  # Previous day's VIX

    # Drop NaN
    df = df.dropna(subset=['tw_gap', 'spy_ret_prev', 'vix'])

    # Remove extreme outliers (likely data errors) - beyond 15%
    mask = (df['tw_gap'].abs() < 0.15) & (df['spy_ret_prev'].abs() < 0.15)
    df = df[mask]

    print(f"Aligned observations: {len(df)}")
    print(f"Period: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
    print(f"\nSPY return: mean={df['spy_ret_prev'].mean()*100:.4f}%, std={df['spy_ret_prev'].std()*100:.4f}%")
    print(f"TW gap:     mean={df['tw_gap'].mean()*100:.4f}%, std={df['tw_gap'].std()*100:.4f}%")

    return df


def descriptive_statistics(df):
    """Compute descriptive statistics for both series."""
    print("\n=== Descriptive Statistics ===")

    results = {}
    for col, label in [('spy_ret_prev', 'SPY Return'), ('tw_gap', 'TW Gap')]:
        s = df[col]
        desc = {
            'mean': float(s.mean()),
            'std': float(s.std()),
            'skew': float(s.skew()),
            'kurtosis': float(s.kurtosis()),
            'min': float(s.min()),
            'max': float(s.max()),
            'n': int(len(s)),
            'adf_stat': float(sm.tsa.stattools.adfuller(s, maxlag=20)[0]),
            'adf_pvalue': float(sm.tsa.stattools.adfuller(s, maxlag=20)[1]),
        }
        results[col] = desc
        print(f"\n{label}:")
        print(f"  N={desc['n']}, Mean={desc['mean']*100:.4f}%, Std={desc['std']*100:.4f}%")
        print(f"  Skew={desc['skew']:.3f}, Kurt={desc['kurtosis']:.3f}")
        print(f"  Range: [{desc['min']*100:.3f}%, {desc['max']*100:.3f}%]")
        print(f"  ADF stat={desc['adf_stat']:.3f}, p={desc['adf_pvalue']:.6f} → {'Stationary' if desc['adf_pvalue'] < 0.05 else 'Non-stationary'}")

    # Correlation
    corr = float(df['spy_ret_prev'].corr(df['tw_gap']))
    results['correlation'] = corr
    print(f"\nCorrelation(SPY_ret, TW_gap): {corr:.4f}")

    return results


def symmetric_regression(df):
    """Model 1: Symmetric baseline regression."""
    print("\n=== Model 1: Symmetric Regression ===")

    X = sm.add_constant(df['spy_ret_prev'])
    y = df['tw_gap']

    model = sm.OLS(y, X).fit(cov_type='HC3')

    print(model.summary().tables[1])

    results = {
        'alpha': float(model.params['const']),
        'alpha_se': float(model.bse['const']),
        'alpha_t': float(model.tvalues['const']),
        'alpha_p': float(model.pvalues['const']),
        'beta': float(model.params['spy_ret_prev']),
        'beta_se': float(model.bse['spy_ret_prev']),
        'beta_t': float(model.tvalues['spy_ret_prev']),
        'beta_p': float(model.pvalues['spy_ret_prev']),
        'r_squared': float(model.rsquared),
        'adj_r_squared': float(model.rsquared_adj),
        'n_obs': int(model.nobs),
    }

    print(f"\nbeta = {results['beta']:.4f} (t={results['beta_t']:.2f})")
    print(f"R² = {results['r_squared']:.4f}")

    return results, model


def asymmetric_regression(df):
    """Model 2: Asymmetric (GJR-style) regression."""
    print("\n=== Model 2: Asymmetric Regression (GJR-style) ===")

    # Create indicator variables
    df_reg = df.copy()
    df_reg['spy_pos'] = df_reg['spy_ret_prev'] * (df_reg['spy_ret_prev'] > 0).astype(float)
    df_reg['spy_neg'] = df_reg['spy_ret_prev'] * (df_reg['spy_ret_prev'] <= 0).astype(float)

    X = sm.add_constant(df_reg[['spy_pos', 'spy_neg']])
    y = df_reg['tw_gap']

    model = sm.OLS(y, X).fit(cov_type='HC3')

    print(model.summary().tables[1])

    beta_pos = float(model.params['spy_pos'])
    beta_neg = float(model.params['spy_neg'])

    # Wald test: H0: beta_neg = beta_pos
    # Use the restriction matrix R @ beta = 0, where R = [0, -1, 1]
    r_matrix = np.array([[0, -1, 1]])
    wald_test = model.wald_test(r_matrix)
    # Extract scalar from Wald test result
    if hasattr(wald_test, 'fvalue'):
        wald_f = float(np.asarray(wald_test.fvalue).flat[0])
    elif hasattr(wald_test, 'statistic'):
        wald_f = float(np.asarray(wald_test.statistic).flat[0])
    else:
        wald_f = float('nan')
    wald_p = float(np.asarray(wald_test.pvalue).flat[0])

    # Asymmetry ratio
    asymmetry_ratio = beta_neg / beta_pos if beta_pos != 0 else float('inf')
    asymmetry_diff = beta_neg - beta_pos

    results = {
        'alpha': float(model.params['const']),
        'alpha_se': float(model.bse['const']),
        'alpha_t': float(model.tvalues['const']),
        'beta_pos': beta_pos,
        'beta_pos_se': float(model.bse['spy_pos']),
        'beta_pos_t': float(model.tvalues['spy_pos']),
        'beta_pos_p': float(model.pvalues['spy_pos']),
        'beta_neg': beta_neg,
        'beta_neg_se': float(model.bse['spy_neg']),
        'beta_neg_t': float(model.tvalues['spy_neg']),
        'beta_neg_p': float(model.pvalues['spy_neg']),
        'asymmetry_diff': asymmetry_diff,
        'asymmetry_ratio': asymmetry_ratio,
        'wald_f': wald_f,
        'wald_p': wald_p,
        'r_squared': float(model.rsquared),
        'adj_r_squared': float(model.rsquared_adj),
        'n_obs': int(model.nobs),
    }

    print(f"\nbeta_pos = {beta_pos:.4f} (t={model.tvalues['spy_pos']:.2f})")
    print(f"beta_neg = {beta_neg:.4f} (t={model.tvalues['spy_neg']:.2f})")
    print(f"Asymmetry: beta_neg - beta_pos = {asymmetry_diff:.4f}")
    print(f"Asymmetry ratio: beta_neg / beta_pos = {asymmetry_ratio:.3f}")
    print(f"Wald test H0(beta_neg=beta_pos): F={wald_f:.3f}, p={wald_p:.4f}")
    print(f"R² = {results['r_squared']:.4f}")

    return results, model


def bootstrap_asymmetry(df, n_boot=10000):
    """Bootstrap confidence interval for asymmetry coefficient."""
    print(f"\n=== Bootstrap CI for Asymmetry ({n_boot} replications) ===")

    rng = np.random.default_rng(42)
    n = len(df)

    spy_ret = df['spy_ret_prev'].values
    tw_gap = df['tw_gap'].values

    boot_diffs = np.zeros(n_boot)

    for b in range(n_boot):
        idx = rng.integers(0, n, size=n)
        spy_b = spy_ret[idx]
        tw_b = tw_gap[idx]

        pos_mask = spy_b > 0
        neg_mask = spy_b <= 0

        # OLS for positive
        if pos_mask.sum() > 2:
            X_pos = sm.add_constant(spy_b[pos_mask])
            y_pos = tw_b[pos_mask]
            beta_pos = np.linalg.lstsq(X_pos, y_pos, rcond=None)[0][1]
        else:
            beta_pos = 0

        # OLS for negative
        if neg_mask.sum() > 2:
            X_neg = sm.add_constant(spy_b[neg_mask])
            y_neg = tw_b[neg_mask]
            beta_neg = np.linalg.lstsq(X_neg, y_neg, rcond=None)[0][1]
        else:
            beta_neg = 0

        boot_diffs[b] = beta_neg - beta_pos

    ci_lower = float(np.percentile(boot_diffs, 2.5))
    ci_upper = float(np.percentile(boot_diffs, 97.5))
    boot_mean = float(np.mean(boot_diffs))
    boot_std = float(np.std(boot_diffs))

    # Proportion of bootstrap samples where beta_neg > beta_pos
    prop_neg_greater = float(np.mean(boot_diffs > 0))

    results = {
        'boot_mean_diff': boot_mean,
        'boot_std_diff': boot_std,
        'ci_95_lower': ci_lower,
        'ci_95_upper': ci_upper,
        'prop_neg_greater': prop_neg_greater,
        'n_boot': n_boot,
    }

    print(f"Bootstrap mean(beta_neg - beta_pos) = {boot_mean:.4f}")
    print(f"95% CI: [{ci_lower:.4f}, {ci_upper:.4f}]")
    print(f"P(beta_neg > beta_pos) = {prop_neg_greater:.4f}")

    return results, boot_diffs


def quintile_analysis(df):
    """Analyze TW gap response by SPY return quintile."""
    print("\n=== Quintile Analysis ===")

    df_q = df.copy()
    df_q['spy_quintile'] = pd.qcut(df_q['spy_ret_prev'], 5, labels=['Q1(worst)', 'Q2', 'Q3', 'Q4', 'Q5(best)'])

    results = {}
    print(f"{'Quintile':<12} {'N':>5} {'SPY_mean':>10} {'TW_gap_mean':>12} {'TW_gap_med':>12} {'TW_gap_std':>10} {'Ratio':>8}")
    print("-" * 80)

    for q in ['Q1(worst)', 'Q2', 'Q3', 'Q4', 'Q5(best)']:
        subset = df_q[df_q['spy_quintile'] == q]
        spy_mean = subset['spy_ret_prev'].mean()
        tw_mean = subset['tw_gap'].mean()
        tw_med = subset['tw_gap'].median()
        tw_std = subset['tw_gap'].std()
        ratio = tw_mean / spy_mean if spy_mean != 0 else float('inf')

        results[q] = {
            'n': int(len(subset)),
            'spy_mean': float(spy_mean),
            'tw_gap_mean': float(tw_mean),
            'tw_gap_median': float(tw_med),
            'tw_gap_std': float(tw_std),
            'transmission_ratio': float(ratio),
        }

        print(f"{q:<12} {len(subset):>5} {spy_mean*100:>9.3f}% {tw_mean*100:>11.3f}% {tw_med*100:>11.3f}% {tw_std*100:>9.3f}% {ratio:>7.3f}")

    # Test for monotonicity: Spearman rank correlation between quintile midpoint and tw_gap mean
    quintile_means = [results[q]['tw_gap_mean'] for q in ['Q1(worst)', 'Q2', 'Q3', 'Q4', 'Q5(best)']]
    spearman_corr, spearman_p = stats.spearmanr(range(5), quintile_means)
    results['monotonicity_spearman'] = float(spearman_corr)
    results['monotonicity_p'] = float(spearman_p)

    print(f"\nMonotonicity: Spearman r = {spearman_corr:.4f}, p = {spearman_p:.6f}")

    # Non-linearity test: compare Q1 transmission ratio vs Q5 transmission ratio
    q1_ratio = abs(results['Q1(worst)']['transmission_ratio'])
    q5_ratio = abs(results['Q5(best)']['transmission_ratio'])
    nonlinearity = q1_ratio / q5_ratio if q5_ratio != 0 else float('inf')
    results['q1_q5_ratio_ratio'] = float(nonlinearity)
    print(f"Q1/Q5 transmission ratio: {nonlinearity:.3f} (>1 = fear amplification)")

    return results


def extreme_event_analysis(df):
    """Analyze extreme SPY events and their impact on TW gap."""
    print("\n=== Extreme Event Analysis ===")

    spy_std = df['spy_ret_prev'].std()
    spy_mean = df['spy_ret_prev'].mean()

    results = {}

    thresholds = [1.0, 1.5, 2.0, 2.5, 3.0]

    print(f"{'Threshold':>10} {'N_down':>7} {'N_up':>7} {'Gap_down':>10} {'Gap_up':>10} {'Ratio':>8} {'KS_stat':>8} {'KS_p':>10}")
    print("-" * 85)

    for t in thresholds:
        extreme_down = df[df['spy_ret_prev'] < spy_mean - t * spy_std]
        extreme_up = df[df['spy_ret_prev'] > spy_mean + t * spy_std]

        if len(extreme_down) < 3 or len(extreme_up) < 3:
            continue

        gap_down_mean = extreme_down['tw_gap'].mean()
        gap_up_mean = extreme_up['tw_gap'].mean()

        # Absolute gap comparison
        abs_ratio = abs(gap_down_mean) / abs(gap_up_mean) if abs(gap_up_mean) > 0 else float('inf')

        # KS test: are the distributions different?
        ks_stat, ks_p = stats.ks_2samp(
            extreme_down['tw_gap'].abs().values,
            extreme_up['tw_gap'].abs().values
        )

        # Welch t-test on absolute gaps
        t_stat, t_p = stats.ttest_ind(
            extreme_down['tw_gap'].abs().values,
            extreme_up['tw_gap'].abs().values,
            equal_var=False
        )

        results[f'{t}sigma'] = {
            'n_down': int(len(extreme_down)),
            'n_up': int(len(extreme_up)),
            'gap_down_mean': float(gap_down_mean),
            'gap_down_median': float(extreme_down['tw_gap'].median()),
            'gap_down_std': float(extreme_down['tw_gap'].std()),
            'gap_up_mean': float(gap_up_mean),
            'gap_up_median': float(extreme_up['tw_gap'].median()),
            'gap_up_std': float(extreme_up['tw_gap'].std()),
            'abs_gap_ratio': float(abs_ratio),
            'ks_stat': float(ks_stat),
            'ks_p': float(ks_p),
            'ttest_stat': float(t_stat),
            'ttest_p': float(t_p),
        }

        print(f"{t:>9.1f}σ {len(extreme_down):>7} {len(extreme_up):>7} "
              f"{gap_down_mean*100:>9.3f}% {gap_up_mean*100:>9.3f}% "
              f"{abs_ratio:>7.2f}x {ks_stat:>7.3f} {ks_p:>10.4f}")

    return results


def vix_regime_asymmetry(df):
    """Analyze asymmetry across VIX regimes."""
    print("\n=== VIX Regime × Asymmetry ===")

    # 4 VIX regimes by quartile
    df_v = df.copy()
    df_v['vix_quartile'] = pd.qcut(df_v['vix'], 4, labels=['Low', 'Med-Low', 'Med-High', 'High'])

    results = {}

    print(f"{'VIX Regime':<12} {'VIX_range':>20} {'beta_pos':>10} {'beta_neg':>10} {'Diff':>10} {'Ratio':>8} {'Wald_p':>10}")
    print("-" * 85)

    for regime in ['Low', 'Med-Low', 'Med-High', 'High']:
        subset = df_v[df_v['vix_quartile'] == regime]

        if len(subset) < 50:
            continue

        vix_range = f"[{subset['vix'].min():.1f}, {subset['vix'].max():.1f}]"

        # Asymmetric regression within regime
        subset_reg = subset.copy()
        subset_reg['spy_pos'] = subset_reg['spy_ret_prev'] * (subset_reg['spy_ret_prev'] > 0).astype(float)
        subset_reg['spy_neg'] = subset_reg['spy_ret_prev'] * (subset_reg['spy_ret_prev'] <= 0).astype(float)

        X = sm.add_constant(subset_reg[['spy_pos', 'spy_neg']])
        y = subset_reg['tw_gap']

        try:
            model = sm.OLS(y, X).fit(cov_type='HC3')
            beta_pos = float(model.params['spy_pos'])
            beta_neg = float(model.params['spy_neg'])
            diff = beta_neg - beta_pos
            ratio = beta_neg / beta_pos if beta_pos != 0 else float('inf')

            # Wald test
            r_matrix = np.array([[0, -1, 1]])
            try:
                wald_test = model.wald_test(r_matrix)
                wald_p = float(wald_test.pvalue)
            except:
                wald_p = float('nan')

            results[regime] = {
                'n': int(len(subset)),
                'vix_min': float(subset['vix'].min()),
                'vix_max': float(subset['vix'].max()),
                'vix_mean': float(subset['vix'].mean()),
                'beta_pos': beta_pos,
                'beta_neg': beta_neg,
                'asymmetry_diff': diff,
                'asymmetry_ratio': ratio,
                'wald_p': wald_p,
                'r_squared': float(model.rsquared),
            }

            print(f"{regime:<12} {vix_range:>20} {beta_pos:>9.4f} {beta_neg:>9.4f} {diff:>9.4f} {ratio:>7.2f}x {wald_p:>10.4f}")
        except Exception as e:
            print(f"{regime:<12} ERROR: {e}")

    return results


def structural_break_analysis(df):
    """Test for structural breaks: pre/post night session, pre/post COVID."""
    print("\n=== Structural Break Analysis ===")

    breaks = {
        'night_session': pd.Timestamp('2017-05-15'),
        'covid': pd.Timestamp('2020-03-01'),
    }

    results = {}

    for break_name, break_date in breaks.items():
        print(f"\n--- Break: {break_name} ({break_date.strftime('%Y-%m-%d')}) ---")

        pre = df[df.index < break_date]
        post = df[df.index >= break_date]

        for period_name, subset in [('pre', pre), ('post', post)]:
            if len(subset) < 50:
                continue

            subset_reg = subset.copy()
            subset_reg['spy_pos'] = subset_reg['spy_ret_prev'] * (subset_reg['spy_ret_prev'] > 0).astype(float)
            subset_reg['spy_neg'] = subset_reg['spy_ret_prev'] * (subset_reg['spy_ret_prev'] <= 0).astype(float)

            X = sm.add_constant(subset_reg[['spy_pos', 'spy_neg']])
            y = subset_reg['tw_gap']

            model = sm.OLS(y, X).fit(cov_type='HC3')
            beta_pos = float(model.params['spy_pos'])
            beta_neg = float(model.params['spy_neg'])
            diff = beta_neg - beta_pos
            ratio = beta_neg / beta_pos if beta_pos != 0 else float('inf')

            key = f"{break_name}_{period_name}"
            results[key] = {
                'n': int(len(subset)),
                'period': f"{subset.index[0].strftime('%Y-%m-%d')} to {subset.index[-1].strftime('%Y-%m-%d')}",
                'beta_pos': beta_pos,
                'beta_neg': beta_neg,
                'asymmetry_diff': diff,
                'asymmetry_ratio': ratio,
                'r_squared': float(model.rsquared),
                'symmetric_beta': float(sm.OLS(subset['tw_gap'], sm.add_constant(subset['spy_ret_prev'])).fit().params.iloc[1]),
            }

            print(f"  {period_name}: N={len(subset)}, beta_pos={beta_pos:.4f}, beta_neg={beta_neg:.4f}, "
                  f"diff={diff:.4f}, ratio={ratio:.3f}")

    # Chow test approximation: compare asymmetry coefficients across periods
    for break_name in breaks:
        pre_key = f"{break_name}_pre"
        post_key = f"{break_name}_post"
        if pre_key in results and post_key in results:
            pre_diff = results[pre_key]['asymmetry_diff']
            post_diff = results[post_key]['asymmetry_diff']
            change = post_diff - pre_diff
            results[f"{break_name}_change"] = {
                'asymmetry_change': change,
                'pre_diff': pre_diff,
                'post_diff': post_diff,
            }
            print(f"\n  Asymmetry change ({break_name}): {pre_diff:.4f} → {post_diff:.4f} (Δ = {change:.4f})")

    return results


def rolling_asymmetry(df, window=504):
    """Compute rolling asymmetry coefficient."""
    print(f"\n=== Rolling Asymmetry (window={window} trading days) ===")

    n = len(df)
    dates = []
    betas_pos = []
    betas_neg = []
    diffs = []

    for i in range(window, n, 21):  # Monthly steps
        subset = df.iloc[i-window:i]

        subset_reg = subset.copy()
        subset_reg['spy_pos'] = subset_reg['spy_ret_prev'] * (subset_reg['spy_ret_prev'] > 0).astype(float)
        subset_reg['spy_neg'] = subset_reg['spy_ret_prev'] * (subset_reg['spy_ret_prev'] <= 0).astype(float)

        X = sm.add_constant(subset_reg[['spy_pos', 'spy_neg']])
        y = subset_reg['tw_gap']

        try:
            model = sm.OLS(y, X).fit()
            bp = float(model.params['spy_pos'])
            bn = float(model.params['spy_neg'])

            dates.append(df.index[i])
            betas_pos.append(bp)
            betas_neg.append(bn)
            diffs.append(bn - bp)
        except:
            pass

    results = {
        'dates': [d.strftime('%Y-%m-%d') for d in dates],
        'betas_pos': betas_pos,
        'betas_neg': betas_neg,
        'diffs': diffs,
        'mean_diff': float(np.mean(diffs)),
        'std_diff': float(np.std(diffs)),
        'pct_neg_greater': float(np.mean(np.array(diffs) > 0)),
    }

    print(f"Rolling windows: {len(dates)}")
    print(f"Mean asymmetry diff: {results['mean_diff']:.4f}")
    print(f"% windows where beta_neg > beta_pos: {results['pct_neg_greater']*100:.1f}%")

    return results


def create_plots(df, asymmetric_results, quintile_results, extreme_results,
                 boot_diffs, vix_results, rolling_results, output_dir):
    """Create publication-quality plots."""

    # ============ Plot 1: Main asymmetry analysis ============
    fig = plt.figure(figsize=(16, 12))
    gs = gridspec.GridSpec(2, 2, figure=fig, hspace=0.35, wspace=0.3)

    # Panel A: Scatter + asymmetric regression lines
    ax1 = fig.add_subplot(gs[0, 0])

    spy_ret = df['spy_ret_prev'].values * 100
    tw_gap = df['tw_gap'].values * 100

    pos_mask = spy_ret > 0
    neg_mask = spy_ret <= 0

    ax1.scatter(spy_ret[pos_mask], tw_gap[pos_mask], alpha=0.15, s=8, c='green', label='SPY > 0')
    ax1.scatter(spy_ret[neg_mask], tw_gap[neg_mask], alpha=0.15, s=8, c='red', label='SPY ≤ 0')

    # Regression lines
    x_neg = np.linspace(spy_ret.min(), 0, 100)
    x_pos = np.linspace(0, spy_ret.max(), 100)

    bp = asymmetric_results['beta_pos']
    bn = asymmetric_results['beta_neg']
    alpha = asymmetric_results['alpha'] * 100

    ax1.plot(x_pos, alpha + bp * x_pos, 'g-', linewidth=2.5,
             label=f'β+ = {bp:.3f}')
    ax1.plot(x_neg, alpha + bn * x_neg, 'r-', linewidth=2.5,
             label=f'β- = {bn:.3f}')

    ax1.axhline(y=0, color='gray', linestyle='--', alpha=0.5)
    ax1.axvline(x=0, color='gray', linestyle='--', alpha=0.5)
    ax1.set_xlabel('SPY Return (%)', fontsize=11)
    ax1.set_ylabel('0050.TW Overnight Gap (%)', fontsize=11)
    ax1.set_title('(A) Asymmetric Transmission', fontsize=13, fontweight='bold')
    ax1.legend(fontsize=9, loc='upper left')

    # Panel B: Quintile analysis
    ax2 = fig.add_subplot(gs[0, 1])

    quintile_names = ['Q1\n(worst)', 'Q2', 'Q3', 'Q4', 'Q5\n(best)']
    spy_means = [quintile_results[q]['spy_mean'] * 100 for q in ['Q1(worst)', 'Q2', 'Q3', 'Q4', 'Q5(best)']]
    tw_means = [quintile_results[q]['tw_gap_mean'] * 100 for q in ['Q1(worst)', 'Q2', 'Q3', 'Q4', 'Q5(best)']]

    x = np.arange(5)
    width = 0.35
    bars1 = ax2.bar(x - width/2, spy_means, width, label='SPY Return', color='steelblue', alpha=0.8)
    bars2 = ax2.bar(x + width/2, tw_means, width, label='TW Gap', color='coral', alpha=0.8)

    ax2.set_xticks(x)
    ax2.set_xticklabels(quintile_names, fontsize=9)
    ax2.set_ylabel('Mean Return (%)', fontsize=11)
    ax2.set_title('(B) SPY Quintile → TW Gap Response', fontsize=13, fontweight='bold')
    ax2.legend(fontsize=9)
    ax2.axhline(y=0, color='gray', linestyle='--', alpha=0.5)

    # Annotate transmission ratios
    for i, q in enumerate(['Q1(worst)', 'Q2', 'Q3', 'Q4', 'Q5(best)']):
        ratio = quintile_results[q]['transmission_ratio']
        y_pos = max(abs(spy_means[i]), abs(tw_means[i])) * 1.1
        if spy_means[i] < 0:
            y_pos = -y_pos
        ax2.annotate(f'×{ratio:.2f}', (i, y_pos), ha='center', fontsize=8, color='purple')

    # Panel C: Bootstrap distribution
    ax3 = fig.add_subplot(gs[1, 0])

    ax3.hist(boot_diffs, bins=80, density=True, alpha=0.7, color='steelblue', edgecolor='white')
    ax3.axvline(x=0, color='red', linestyle='--', linewidth=2, label='H0: no asymmetry')
    ax3.axvline(x=np.mean(boot_diffs), color='green', linestyle='-', linewidth=2,
                label=f'Mean = {np.mean(boot_diffs):.4f}')

    ci_lower = np.percentile(boot_diffs, 2.5)
    ci_upper = np.percentile(boot_diffs, 97.5)
    ax3.axvline(x=ci_lower, color='orange', linestyle=':', linewidth=1.5)
    ax3.axvline(x=ci_upper, color='orange', linestyle=':', linewidth=1.5,
                label=f'95% CI: [{ci_lower:.4f}, {ci_upper:.4f}]')

    ax3.set_xlabel('β_neg - β_pos', fontsize=11)
    ax3.set_ylabel('Density', fontsize=11)
    ax3.set_title('(C) Bootstrap Distribution of Asymmetry', fontsize=13, fontweight='bold')
    ax3.legend(fontsize=8)

    # Panel D: VIX regime asymmetry
    ax4 = fig.add_subplot(gs[1, 1])

    regimes = [r for r in ['Low', 'Med-Low', 'Med-High', 'High'] if r in vix_results]
    if regimes:
        x = np.arange(len(regimes))
        bp_vals = [vix_results[r]['beta_pos'] for r in regimes]
        bn_vals = [vix_results[r]['beta_neg'] for r in regimes]

        width = 0.35
        ax4.bar(x - width/2, bp_vals, width, label='β_pos (SPY up)', color='green', alpha=0.7)
        ax4.bar(x + width/2, bn_vals, width, label='β_neg (SPY down)', color='red', alpha=0.7)

        ax4.set_xticks(x)
        ax4.set_xticklabels(regimes, fontsize=10)
        ax4.set_ylabel('Beta Coefficient', fontsize=11)
        ax4.set_title('(D) VIX Regime × Asymmetry', fontsize=13, fontweight='bold')
        ax4.legend(fontsize=9)

        # Annotate ratios
        for i, r in enumerate(regimes):
            ratio = vix_results[r]['asymmetry_ratio']
            y_max = max(bp_vals[i], bn_vals[i])
            ax4.annotate(f'ratio={ratio:.2f}', (i, y_max + 0.02), ha='center', fontsize=8, color='purple')

    plt.suptitle('K929: Asymmetric Volatility Transmission SPY → 0050.TW\nFear Contagion vs Greed Diffusion',
                 fontsize=14, fontweight='bold', y=1.02)

    fig.savefig(os.path.join(output_dir, 'k929_asymmetry.png'), dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"\nSaved: k929_asymmetry.png")

    # ============ Plot 2: Extreme events + rolling ============
    fig2 = plt.figure(figsize=(16, 10))
    gs2 = gridspec.GridSpec(2, 2, figure=fig2, hspace=0.35, wspace=0.3)

    # Panel A: Extreme event gap distributions
    ax5 = fig2.add_subplot(gs2[0, 0])

    spy_std = df['spy_ret_prev'].std()
    spy_mean_val = df['spy_ret_prev'].mean()

    extreme_down = df[df['spy_ret_prev'] < spy_mean_val - 2 * spy_std]['tw_gap'] * 100
    extreme_up = df[df['spy_ret_prev'] > spy_mean_val + 2 * spy_std]['tw_gap'] * 100

    if len(extreme_down) > 0 and len(extreme_up) > 0:
        ax5.hist(extreme_down, bins=30, alpha=0.6, color='red', label=f'SPY < -2σ (N={len(extreme_down)})', density=True)
        ax5.hist(extreme_up, bins=30, alpha=0.6, color='green', label=f'SPY > +2σ (N={len(extreme_up)})', density=True)
        ax5.axvline(x=extreme_down.mean(), color='darkred', linestyle='--', linewidth=2)
        ax5.axvline(x=extreme_up.mean(), color='darkgreen', linestyle='--', linewidth=2)
        ax5.set_xlabel('0050.TW Overnight Gap (%)', fontsize=11)
        ax5.set_ylabel('Density', fontsize=11)
        ax5.set_title('(A) TW Gap Distribution: Extreme SPY Days', fontsize=13, fontweight='bold')
        ax5.legend(fontsize=9)

    # Panel B: Extreme event box plots
    ax6 = fig2.add_subplot(gs2[0, 1])

    if len(extreme_down) > 0 and len(extreme_up) > 0:
        bp = ax6.boxplot([extreme_down.abs().values, extreme_up.abs().values],
                        labels=['SPY < -2σ', 'SPY > +2σ'],
                        patch_artist=True)
        bp['boxes'][0].set_facecolor('lightcoral')
        bp['boxes'][1].set_facecolor('lightgreen')
        ax6.set_ylabel('|0050.TW Overnight Gap| (%)', fontsize=11)
        ax6.set_title('(B) Absolute Gap: Fear vs Greed', fontsize=13, fontweight='bold')

        # Annotate means
        means = [extreme_down.abs().mean(), extreme_up.abs().mean()]
        for i, m in enumerate(means):
            ax6.annotate(f'mean={m:.3f}%', (i+1, m), xytext=(15, 5),
                        textcoords='offset points', fontsize=9, color='blue')

    # Panel C: Rolling asymmetry over time
    ax7 = fig2.add_subplot(gs2[1, :])

    if rolling_results and len(rolling_results['dates']) > 0:
        roll_dates = pd.to_datetime(rolling_results['dates'])
        roll_diffs = rolling_results['diffs']
        roll_bp = rolling_results['betas_pos']
        roll_bn = rolling_results['betas_neg']

        ax7.fill_between(roll_dates, roll_diffs, 0,
                         where=np.array(roll_diffs) > 0, alpha=0.3, color='red',
                         label='β_neg > β_pos (fear dominates)')
        ax7.fill_between(roll_dates, roll_diffs, 0,
                         where=np.array(roll_diffs) <= 0, alpha=0.3, color='green',
                         label='β_pos > β_neg (greed dominates)')
        ax7.plot(roll_dates, roll_diffs, 'k-', linewidth=1, alpha=0.8)

        # Mark structural breaks
        ax7.axvline(x=pd.Timestamp('2017-05-15'), color='blue', linestyle='--', alpha=0.5, label='Night session start')
        ax7.axvline(x=pd.Timestamp('2020-03-01'), color='purple', linestyle='--', alpha=0.5, label='COVID-19')

        ax7.axhline(y=0, color='gray', linestyle='-', alpha=0.3)
        ax7.set_xlabel('Date', fontsize=11)
        ax7.set_ylabel('β_neg - β_pos', fontsize=11)
        ax7.set_title('(C) Rolling Asymmetry Coefficient (2-year window)', fontsize=13, fontweight='bold')
        ax7.legend(fontsize=9, loc='upper left')

    plt.suptitle('K929: Extreme Events & Time-Varying Asymmetry',
                 fontsize=14, fontweight='bold', y=1.02)

    fig2.savefig(os.path.join(output_dir, 'k929_extreme_events.png'), dpi=150, bbox_inches='tight')
    plt.close(fig2)
    print(f"Saved: k929_extreme_events.png")


def piecewise_regression(df):
    """Model 3: Piecewise regression with threshold at median and extreme."""
    print("\n=== Model 3: Piecewise Regression (Threshold Effects) ===")

    spy_ret = df['spy_ret_prev']
    spy_std = spy_ret.std()

    # Three regimes: extreme negative, normal, extreme positive
    df_pw = df.copy()
    df_pw['regime'] = 'normal'
    df_pw.loc[spy_ret < -spy_std, 'regime'] = 'extreme_neg'
    df_pw.loc[spy_ret > spy_std, 'regime'] = 'extreme_pos'

    results = {}

    for regime in ['extreme_neg', 'normal', 'extreme_pos']:
        subset = df_pw[df_pw['regime'] == regime]
        if len(subset) < 20:
            continue

        X = sm.add_constant(subset['spy_ret_prev'])
        y = subset['tw_gap']
        model = sm.OLS(y, X).fit(cov_type='HC3')

        beta = float(model.params['spy_ret_prev'])
        results[regime] = {
            'n': int(len(subset)),
            'beta': beta,
            'beta_se': float(model.bse['spy_ret_prev']),
            'beta_t': float(model.tvalues['spy_ret_prev']),
            'r_squared': float(model.rsquared),
        }

        print(f"  {regime}: N={len(subset)}, beta={beta:.4f} (t={model.tvalues['spy_ret_prev']:.2f}), R²={model.rsquared:.4f}")

    # Compare extreme_neg vs extreme_pos betas
    if 'extreme_neg' in results and 'extreme_pos' in results:
        ratio = results['extreme_neg']['beta'] / results['extreme_pos']['beta'] if results['extreme_pos']['beta'] != 0 else float('inf')
        results['extreme_ratio'] = float(ratio)
        print(f"\n  Extreme neg/pos beta ratio: {ratio:.3f}")

    return results


def main():
    """Run the full K929 experiment."""
    print("=" * 80)
    print("K929: Asymmetric Volatility Transmission SPY → 0050.TW")
    print("Fear Contagion vs Greed Diffusion")
    print("=" * 80)

    output_dir = os.path.dirname(os.path.abspath(__file__))

    # Step 1: Data
    spy, tw50, vix = fetch_data()

    # Step 2: Compute returns and gaps
    df = compute_returns_and_gaps(spy, tw50, vix)

    # Step 3: Descriptive statistics
    desc_stats = descriptive_statistics(df)

    # Step 4: Symmetric regression (baseline)
    sym_results, sym_model = symmetric_regression(df)

    # Step 5: Asymmetric regression
    asym_results, asym_model = asymmetric_regression(df)

    # Step 6: Bootstrap
    boot_results, boot_diffs = bootstrap_asymmetry(df, n_boot=10000)

    # Step 7: Quintile analysis
    quint_results = quintile_analysis(df)

    # Step 8: Extreme event analysis
    extreme_results = extreme_event_analysis(df)

    # Step 9: Piecewise regression
    piecewise_results = piecewise_regression(df)

    # Step 10: VIX regime × asymmetry
    vix_regime_results = vix_regime_asymmetry(df)

    # Step 11: Structural break analysis
    break_results = structural_break_analysis(df)

    # Step 12: Rolling asymmetry
    rolling_results = rolling_asymmetry(df, window=504)

    # Step 13: Create plots
    create_plots(df, asym_results, quint_results, extreme_results,
                boot_diffs, vix_regime_results, rolling_results, output_dir)

    # ============ Summary ============
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    print(f"\nSymmetric beta: {sym_results['beta']:.4f} (R²={sym_results['r_squared']:.4f})")
    print(f"Asymmetric beta_pos: {asym_results['beta_pos']:.4f}")
    print(f"Asymmetric beta_neg: {asym_results['beta_neg']:.4f}")
    print(f"Difference (β_neg - β_pos): {asym_results['asymmetry_diff']:.4f}")
    print(f"Ratio (β_neg / β_pos): {asym_results['asymmetry_ratio']:.3f}")
    print(f"Wald test p-value: {asym_results['wald_p']:.6f}")
    print(f"Bootstrap 95% CI: [{boot_results['ci_95_lower']:.4f}, {boot_results['ci_95_upper']:.4f}]")
    print(f"P(β_neg > β_pos) = {boot_results['prop_neg_greater']:.4f}")

    is_significant = asym_results['wald_p'] < 0.05
    is_fear_stronger = asym_results['asymmetry_diff'] > 0

    if is_significant and is_fear_stronger:
        conclusion = "CONFIRMED: Fear contagion significantly stronger than greed diffusion"
    elif not is_significant:
        conclusion = "NULL: No statistically significant asymmetry detected"
    else:
        conclusion = "REVERSED: Greed diffusion stronger than fear contagion (unexpected)"

    print(f"\nConclusion: {conclusion}")

    # ============ Save results ============
    all_results = {
        'experiment_id': 'K929',
        'title': 'K929: Asymmetric Volatility Transmission SPY→0050.TW — Fear Contagion vs Greed Diffusion',
        'timestamp': datetime.utcnow().isoformat(),
        'data_source': 'yfinance (SPY, 0050.TW, ^VIX)',
        'period': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
        'n_observations': int(len(df)),
        'conclusion': conclusion,
        'references': [
            'Engle & Ng (1993) - News Impact Curves',
            'Glosten, Jagannathan & Runkle (1993) - GJR-GARCH',
            'Baele (2005) - Volatility spillover in equity markets',
            'Bekaert, Ehrmann, Fratzscher & Mehl (2014) - Global crises and equity market contagion',
        ],
        'descriptive_statistics': desc_stats,
        'symmetric_regression': sym_results,
        'asymmetric_regression': asym_results,
        'bootstrap': boot_results,
        'quintile_analysis': {k: v for k, v in quint_results.items() if k not in ['monotonicity_spearman', 'monotonicity_p', 'q1_q5_ratio_ratio']},
        'quintile_monotonicity': {
            'spearman_r': quint_results.get('monotonicity_spearman'),
            'spearman_p': quint_results.get('monotonicity_p'),
            'q1_q5_ratio_ratio': quint_results.get('q1_q5_ratio_ratio'),
        },
        'extreme_events': extreme_results,
        'piecewise_regression': piecewise_results,
        'vix_regime_asymmetry': vix_regime_results,
        'structural_breaks': break_results,
        'rolling_asymmetry_summary': {
            'mean_diff': rolling_results['mean_diff'],
            'std_diff': rolling_results['std_diff'],
            'pct_neg_greater': rolling_results['pct_neg_greater'],
            'n_windows': len(rolling_results['dates']),
        },
        'limitations': [
            'Uses daily close-to-close SPY return as proxy for overnight news',
            '0050.TW gap includes both US-driven and local overnight news',
            'Forward-fill SPY returns on TW-only trading days may introduce noise',
            'No control for local Taiwan macro/political events',
            'Split adjustment for 0050.TW via clean_tw50_data (pre-2014 issue)',
        ],
    }

    results_path = os.path.join(output_dir, 'k929_asymmetric_transmission_results.json')
    with open(results_path, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nResults saved to: {results_path}")

    return all_results


if __name__ == '__main__':
    results = main()
