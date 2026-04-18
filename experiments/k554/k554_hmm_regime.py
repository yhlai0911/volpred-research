#!/usr/bin/env python3
"""
K554: Hidden Markov Model Regime Detection for VT
==================================================
Can HMM identify vol regimes better than VIX thresholds?

Motivation:
All our VT strategies use VIX directly. HMM can identify latent market
regimes (bull/bear/crisis) from returns without looking at VIX. If HMM
regimes provide different information from VIX, combining them might help.

This is a "jump direction" experiment — completely different methodology.

Prior knowledge:
- K533: ★★★ HAR best predictor but worst VT — 12/VIX irreducible kernel (7th confirmation)
- Regime-adaptive overlay worsens Sharpe from 0.61 to 0.53 (high-vol has +11.1% ann return)
- VRP Regime Switching: null result (VIX already contains full VRP info)
- GARCH vs VIX cross-correlation r≈0.82

Design:
1. Data: SPY daily returns from yfinance (2005-2026)
2. Fit 2-state and 3-state Gaussian HMM using hmmlearn:
   - 2-state: low-vol, high-vol
   - 3-state: calm, transition, crisis
3. Features for HMM: daily return + 5-day abs return (2D observation)
4. Strategies:
   a. HMM-VT: use HMM state probability for position sizing
      - P(calm) > 0.7: full 12/VIX weight
      - P(crisis) > 0.5: reduce to 50% of 12/VIX weight
   b. HMM-Binary: 12/VIX when P(calm) > 0.5, 8/VIX when P(crisis) > 0.5
   c. HMM-VIX-Ensemble: blend HMM regime prob with VIX level
5. Benchmark: pure 12/VIX
6. Rolling estimation: refit HMM every 252 days (annual)
7. Cross-OOS: 3 periods
8. Harvey t>3.0

Literature:
- Hamilton (1989): "A New Approach to the Economic Analysis of Nonstationary
  Time Series and the Business Cycle", Econometrica — foundational HMM in economics
- Ang & Bekaert (2002): "International Asset Allocation With Regime Shifts",
  Review of Financial Studies — regime switching for asset allocation
- Guidolin & Timmermann (2007): "Asset Allocation Under Multivariate Regime
  Switching", Journal of Economic Dynamics and Control
- Moreira & Muir (2017): "Volatility-Managed Portfolios", JF
- Harvey, Liu & Zhu (2016): "...and the Cross-Section of Expected Returns", RFS

Data source: yfinance (SPY, ^VIX)
"""

import json
import time
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from datetime import datetime
from hmmlearn.hmm import GaussianHMM

warnings.filterwarnings('ignore')

start_time = time.time()

print("=" * 70)
print("K554: Hidden Markov Model Regime Detection for VT")
print("=" * 70)

# =================================================================
# 1. DATA DOWNLOAD
# =================================================================
print("\n[1] Downloading data...")

spy = yf.download("SPY", start="2004-01-01", end="2026-12-31", progress=False)
vix = yf.download("^VIX", start="2004-01-01", end="2026-12-31", progress=False)

for d in [spy, vix]:
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = d.columns.get_level_values(0)

spy_ret = spy['Close'].pct_change().dropna()
spy_ret.name = 'spy_ret'
vix_close = vix['Close'].dropna()
vix_close.name = 'vix'

df = pd.DataFrame({'spy_ret': spy_ret, 'vix': vix_close}).dropna()
df = df[df.index >= '2005-01-01']

# Create features for HMM: daily return + 5-day abs return
df['abs_ret_5d'] = df['spy_ret'].abs().rolling(5).mean()
df = df.dropna()

print(f"  Data range: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
print(f"  Total observations: {len(df)}")

# =================================================================
# 2. DATA DIAGNOSTICS
# =================================================================
print("\n[2] Data Diagnostics...")

ret = df['spy_ret']
print(f"  SPY returns: mean={ret.mean()*252:.4f} (ann), std={ret.std()*np.sqrt(252):.4f} (ann)")
print(f"  Skewness: {ret.skew():.4f}")
print(f"  Kurtosis: {ret.kurtosis():.4f}")
print(f"  VIX: mean={df['vix'].mean():.2f}, std={df['vix'].std():.2f}")
print(f"  VIX range: [{df['vix'].min():.2f}, {df['vix'].max():.2f}]")

# ADF test on returns
from scipy.stats import jarque_bera
jb_stat, jb_p = jarque_bera(ret.values)
print(f"  Jarque-Bera: stat={jb_stat:.1f}, p={jb_p:.4e} (non-normal)")

# =================================================================
# 3. HMM FITTING AND ANALYSIS
# =================================================================
print("\n[3] HMM Fitting (full sample for analysis)...")

# Prepare observations: [daily_return, 5d_abs_return]
obs_full = df[['spy_ret', 'abs_ret_5d']].values

# --- 2-state HMM ---
print("\n  --- 2-State HMM ---")
hmm2 = GaussianHMM(n_components=2, covariance_type='full', n_iter=200,
                    random_state=42, tol=1e-4)
hmm2.fit(obs_full)
states2 = hmm2.predict(obs_full)
probs2 = hmm2.predict_proba(obs_full)

# Identify which state is low-vol and high-vol
means2 = hmm2.means_
if means2[0, 1] < means2[1, 1]:  # abs_ret_5d lower → calm
    calm_idx_2, stress_idx_2 = 0, 1
else:
    calm_idx_2, stress_idx_2 = 1, 0

print(f"  State 0: mean_ret={means2[0,0]*252:.4f}, mean_absret5d={means2[0,1]*252:.4f}")
print(f"  State 1: mean_ret={means2[1,0]*252:.4f}, mean_absret5d={means2[1,1]*252:.4f}")
print(f"  Calm state: {calm_idx_2}, Stress state: {stress_idx_2}")
print(f"  Calm days: {(states2==calm_idx_2).sum()} ({(states2==calm_idx_2).mean()*100:.1f}%)")
print(f"  Stress days: {(states2==stress_idx_2).sum()} ({(states2==stress_idx_2).mean()*100:.1f}%)")
print(f"  Log-likelihood: {hmm2.score(obs_full):.2f}")

# Transition matrix
print(f"  Transition matrix:")
print(f"    {hmm2.transmat_}")

# --- 3-state HMM ---
print("\n  --- 3-State HMM ---")
hmm3 = GaussianHMM(n_components=3, covariance_type='full', n_iter=200,
                    random_state=42, tol=1e-4)
hmm3.fit(obs_full)
states3 = hmm3.predict(obs_full)
probs3 = hmm3.predict_proba(obs_full)

means3 = hmm3.means_
# Sort states by abs_ret_5d (ascending = calm → transition → crisis)
state_order = np.argsort(means3[:, 1])
calm_idx_3, trans_idx_3, crisis_idx_3 = state_order[0], state_order[1], state_order[2]

for i, label in zip(state_order, ['Calm', 'Transition', 'Crisis']):
    n_days = (states3 == i).sum()
    pct = n_days / len(states3) * 100
    print(f"  {label} (state {i}): mean_ret={means3[i,0]*252:.4f}, "
          f"mean_absret5d={means3[i,1]*252:.4f}, days={n_days} ({pct:.1f}%)")

print(f"  Log-likelihood: {hmm3.score(obs_full):.2f}")
print(f"  Transition matrix:")
print(f"    {hmm3.transmat_}")

# --- Compare HMM regimes with VIX regimes ---
print("\n  --- HMM vs VIX Regime Comparison ---")
df['state2'] = states2
df['state3'] = states3
df['p_calm_2'] = probs2[:, calm_idx_2]
df['p_stress_2'] = probs2[:, stress_idx_2]
df['p_calm_3'] = probs3[:, calm_idx_3]
df['p_trans_3'] = probs3[:, trans_idx_3]
df['p_crisis_3'] = probs3[:, crisis_idx_3]

# VIX regime definition (standard)
df['vix_regime'] = pd.cut(df['vix'], bins=[0, 15, 20, 30, 100],
                          labels=['low', 'normal', 'elevated', 'crisis'])

# Correlation between HMM stress probability and VIX
corr_2state = df['p_stress_2'].corr(df['vix'])
corr_3state = df['p_crisis_3'].corr(df['vix'])
print(f"  Corr(P(stress_2state), VIX): {corr_2state:.4f}")
print(f"  Corr(P(crisis_3state), VIX): {corr_3state:.4f}")

# Cross-tab: HMM state vs VIX regime
ct = pd.crosstab(df['state2'].map({calm_idx_2: 'HMM_calm', stress_idx_2: 'HMM_stress'}),
                 df['vix_regime'], normalize='index')
print(f"\n  2-State HMM vs VIX regime (row-normalized):")
print(f"  {ct.to_string()}")

# Key insight: HMM disagreement with VIX
hmm_stress = df['p_stress_2'] > 0.5
vix_stress = df['vix'] > 20
agreement = (hmm_stress == vix_stress).mean()
print(f"\n  HMM-VIX agreement rate: {agreement*100:.1f}%")

# When they disagree
disagree_mask = hmm_stress != vix_stress
if disagree_mask.sum() > 0:
    disagree_df = df[disagree_mask]
    # HMM says stress but VIX doesn't
    hmm_only_stress = disagree_df[disagree_df['p_stress_2'] > 0.5]
    # VIX says stress but HMM doesn't
    vix_only_stress = disagree_df[disagree_df['vix'] > 20]
    print(f"  Disagreement days: {disagree_mask.sum()} ({disagree_mask.mean()*100:.1f}%)")
    print(f"    HMM stress, VIX calm: {len(hmm_only_stress)} days")
    print(f"    VIX stress, HMM calm: {len(vix_only_stress)} days")
    if len(hmm_only_stress) > 0:
        print(f"    HMM-only stress: next-day ret={hmm_only_stress['spy_ret'].shift(-1).mean()*252:.4f} (ann)")
    if len(vix_only_stress) > 0:
        print(f"    VIX-only stress: next-day ret={vix_only_stress['spy_ret'].shift(-1).mean()*252:.4f} (ann)")

# =================================================================
# 4. ROLLING HMM VT STRATEGIES (Cross-OOS)
# =================================================================
print("\n[4] Rolling HMM VT Strategies with Cross-OOS...")

# Cross-OOS periods
oos_periods = [
    ('2015-01-01', '2017-12-31'),
    ('2018-01-01', '2020-12-31'),
    ('2021-01-01', '2023-12-31'),
]

# Warmup period for HMM: need at least 1000 days
WARMUP = 1000
REFIT_FREQ = 252  # refit annually

def compute_metrics(returns, ann_factor=252):
    """Compute strategy metrics."""
    if len(returns) == 0 or returns.std() == 0:
        return {'sharpe': 0, 'cagr': 0, 'mdd': 0, 'calmar': 0, 'sortino': 0,
                'volatility': 0, 'mean_weight': 0}

    mean_ret = returns.mean() * ann_factor
    std_ret = returns.std() * np.sqrt(ann_factor)
    sharpe = mean_ret / std_ret if std_ret > 0 else 0

    # CAGR
    cum = (1 + returns).cumprod()
    n_years = len(returns) / ann_factor
    cagr = (cum.iloc[-1] ** (1 / n_years) - 1) if n_years > 0 and cum.iloc[-1] > 0 else 0

    # MDD
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    # Calmar
    calmar = cagr / abs(mdd) if mdd != 0 else 0

    # Sortino
    downside = returns[returns < 0].std() * np.sqrt(ann_factor)
    sortino = mean_ret / downside if downside > 0 else 0

    return {
        'sharpe': round(sharpe, 4),
        'cagr': round(cagr * 100, 2),
        'mdd': round(mdd * 100, 2),
        'calmar': round(calmar, 4),
        'sortino': round(sortino, 4),
        'volatility': round(std_ret * 100, 2),
    }


def run_oos_period(df_full, oos_start, oos_end):
    """Run all strategies on one OOS period with rolling HMM."""
    oos_mask = (df_full.index >= oos_start) & (df_full.index <= oos_end)
    oos_dates = df_full.index[oos_mask]

    if len(oos_dates) == 0:
        return None

    # Prepare observation matrix
    obs_cols = ['spy_ret', 'abs_ret_5d']

    # Storage for daily weights
    results = {
        'date': [],
        'spy_ret': [],
        'vix': [],
        'w_baseline': [],      # 12/VIX
        'w_hmm_vt_2': [],      # HMM-VT (2-state)
        'w_hmm_vt_3': [],      # HMM-VT (3-state)
        'w_hmm_binary': [],    # HMM-Binary
        'w_hmm_ensemble': [],  # HMM-VIX-Ensemble
        'p_calm_2': [],
        'p_stress_2': [],
        'p_calm_3': [],
        'p_crisis_3': [],
    }

    # Current HMM models (will be refit periodically)
    current_hmm2 = None
    current_hmm3 = None
    current_calm2 = 0
    current_stress2 = 1
    current_calm3 = 0
    current_crisis3 = 2
    last_refit = None
    n_refits = 0

    for i, date in enumerate(oos_dates):
        loc = df_full.index.get_loc(date)

        # Check if we need to refit
        if current_hmm2 is None or (last_refit is not None and
                                     (date - last_refit).days >= REFIT_FREQ):
            # Use all data up to this point for fitting
            train_start = max(0, loc - WARMUP)
            train_data = df_full.iloc[train_start:loc][obs_cols].values

            if len(train_data) >= 200:
                try:
                    h2 = GaussianHMM(n_components=2, covariance_type='full',
                                     n_iter=100, random_state=42, tol=1e-4)
                    h2.fit(train_data)
                    current_hmm2 = h2
                    # Identify calm/stress
                    m2 = h2.means_
                    if m2[0, 1] < m2[1, 1]:
                        current_calm2, current_stress2 = 0, 1
                    else:
                        current_calm2, current_stress2 = 1, 0
                except Exception:
                    pass

                try:
                    h3 = GaussianHMM(n_components=3, covariance_type='full',
                                     n_iter=100, random_state=42, tol=1e-4)
                    h3.fit(train_data)
                    current_hmm3 = h3
                    m3 = h3.means_
                    order = np.argsort(m3[:, 1])
                    current_calm3, current_crisis3 = order[0], order[2]
                except Exception:
                    pass

                last_refit = date
                n_refits += 1

        # Get today's observation for state prediction
        today_obs = df_full.iloc[loc:loc+1][obs_cols].values
        today_ret = df_full.iloc[loc]['spy_ret']
        today_vix = df_full.iloc[loc]['vix']

        # Baseline: 12/VIX
        w_base = min(max(12.0 / today_vix, 0), 2.0)

        # HMM state probabilities (using all data up to today for decode)
        # Use only recent history for computational efficiency
        recent_start = max(0, loc - 500)
        recent_obs = df_full.iloc[recent_start:loc+1][obs_cols].values

        p_calm_2, p_stress_2 = 0.5, 0.5
        p_calm_3, p_crisis_3 = 0.33, 0.33

        if current_hmm2 is not None and len(recent_obs) > 1:
            try:
                probs = current_hmm2.predict_proba(recent_obs)
                p_calm_2 = probs[-1, current_calm2]
                p_stress_2 = probs[-1, current_stress2]
            except Exception:
                pass

        if current_hmm3 is not None and len(recent_obs) > 1:
            try:
                probs = current_hmm3.predict_proba(recent_obs)
                p_calm_3 = probs[-1, current_calm3]
                p_crisis_3 = probs[-1, current_crisis3]
            except Exception:
                pass

        # --- Strategy A: HMM-VT (2-state) ---
        # P(calm) > 0.7: full weight; P(stress) > 0.5: reduce to 50%
        if p_calm_2 > 0.7:
            w_hmm_vt_2 = w_base
        elif p_stress_2 > 0.5:
            w_hmm_vt_2 = w_base * 0.5
        else:
            w_hmm_vt_2 = w_base * 0.75  # middle ground

        # --- Strategy B: HMM-VT (3-state) ---
        # Use 3-state probabilities
        if p_calm_3 > 0.7:
            w_hmm_vt_3 = w_base
        elif p_crisis_3 > 0.5:
            w_hmm_vt_3 = w_base * 0.5
        else:
            w_hmm_vt_3 = w_base * 0.75

        # --- Strategy C: HMM-Binary ---
        # Calm → 12/VIX, Stress → 8/VIX
        if p_calm_2 > 0.5:
            w_hmm_binary = min(max(12.0 / today_vix, 0), 2.0)
        else:
            w_hmm_binary = min(max(8.0 / today_vix, 0), 2.0)

        # --- Strategy D: HMM-VIX-Ensemble ---
        # Blend: weight = (1 - 0.3 * P(stress)) * 12/VIX
        stress_blend = max(p_stress_2, p_crisis_3)  # take max stress signal
        w_hmm_ensemble = w_base * (1 - 0.3 * stress_blend)

        # Cap all weights
        for w_name in ['w_hmm_vt_2', 'w_hmm_vt_3', 'w_hmm_binary', 'w_hmm_ensemble']:
            val = locals()[w_name]
            locals()[w_name] = min(max(val, 0), 2.0)

        results['date'].append(date)
        results['spy_ret'].append(today_ret)
        results['vix'].append(today_vix)
        results['w_baseline'].append(w_base)
        results['w_hmm_vt_2'].append(min(max(w_hmm_vt_2, 0), 2.0))
        results['w_hmm_vt_3'].append(min(max(w_hmm_vt_3, 0), 2.0))
        results['w_hmm_binary'].append(min(max(w_hmm_binary, 0), 2.0))
        results['w_hmm_ensemble'].append(min(max(w_hmm_ensemble, 0), 2.0))
        results['p_calm_2'].append(p_calm_2)
        results['p_stress_2'].append(p_stress_2)
        results['p_calm_3'].append(p_calm_3)
        results['p_crisis_3'].append(p_crisis_3)

    res_df = pd.DataFrame(results)
    res_df.set_index('date', inplace=True)

    # Compute strategy returns
    strategies = {}
    for strat_name, w_col in [
        ('12/VIX', 'w_baseline'),
        ('HMM-VT-2state', 'w_hmm_vt_2'),
        ('HMM-VT-3state', 'w_hmm_vt_3'),
        ('HMM-Binary', 'w_hmm_binary'),
        ('HMM-VIX-Ensemble', 'w_hmm_ensemble'),
    ]:
        strat_ret = res_df[w_col].shift(1) * res_df['spy_ret']  # use previous day weight
        strat_ret = strat_ret.dropna()
        metrics = compute_metrics(strat_ret)
        metrics['mean_weight'] = round(res_df[w_col].mean(), 4)
        strategies[strat_name] = metrics

    # Buy & Hold
    bh_ret = res_df['spy_ret']
    strategies['Buy&Hold'] = compute_metrics(bh_ret)
    strategies['Buy&Hold']['mean_weight'] = 1.0

    # Weight correlation
    weight_corrs = {}
    for w_col in ['w_hmm_vt_2', 'w_hmm_vt_3', 'w_hmm_binary', 'w_hmm_ensemble']:
        weight_corrs[w_col] = round(res_df['w_baseline'].corr(res_df[w_col]), 4)

    return {
        'n_days': len(res_df),
        'n_refits': n_refits,
        'strategies': strategies,
        'weight_correlations': weight_corrs,
        'hmm_stats': {
            'mean_p_calm_2': round(res_df['p_calm_2'].mean(), 4),
            'mean_p_stress_2': round(res_df['p_stress_2'].mean(), 4),
            'mean_p_calm_3': round(res_df['p_calm_3'].mean(), 4),
            'mean_p_crisis_3': round(res_df['p_crisis_3'].mean(), 4),
        },
        'res_df': res_df,  # for DM test
    }


# Run all OOS periods
all_results = {}
all_res_dfs = []

for period_idx, (oos_start, oos_end) in enumerate(oos_periods):
    print(f"\n  --- OOS Period {period_idx+1}: {oos_start} to {oos_end} ---")
    result = run_oos_period(df, oos_start, oos_end)
    if result is not None:
        all_results[f"period_{period_idx+1}"] = {
            'oos_start': oos_start,
            'oos_end': oos_end,
            'n_days': result['n_days'],
            'n_refits': result['n_refits'],
            'strategies': result['strategies'],
            'weight_correlations': result['weight_correlations'],
            'hmm_stats': result['hmm_stats'],
        }
        all_res_dfs.append(result['res_df'])

        print(f"    Days: {result['n_days']}, Refits: {result['n_refits']}")
        print(f"    {'Strategy':<20} {'Sharpe':>8} {'CAGR%':>8} {'MDD%':>8} {'Calmar':>8} {'AvgW':>8}")
        print(f"    {'-'*60}")
        for name, m in result['strategies'].items():
            print(f"    {name:<20} {m['sharpe']:>8.4f} {m['cagr']:>8.2f} {m['mdd']:>8.2f} {m['calmar']:>8.4f} {m['mean_weight']:>8.4f}")

# =================================================================
# 5. AGGREGATE RESULTS
# =================================================================
print("\n[5] Aggregate Results Across OOS Periods...")

strat_names = ['12/VIX', 'HMM-VT-2state', 'HMM-VT-3state', 'HMM-Binary',
               'HMM-VIX-Ensemble', 'Buy&Hold']

agg = {}
for sname in strat_names:
    sharpes = []
    cagrs = []
    mdds = []
    for pk, pv in all_results.items():
        if sname in pv['strategies']:
            sharpes.append(pv['strategies'][sname]['sharpe'])
            cagrs.append(pv['strategies'][sname]['cagr'])
            mdds.append(pv['strategies'][sname]['mdd'])
    agg[sname] = {
        'mean_sharpe': round(np.mean(sharpes), 4),
        'std_sharpe': round(np.std(sharpes), 4),
        'sharpes': sharpes,
        'mean_cagr': round(np.mean(cagrs), 2),
        'mean_mdd': round(np.mean(mdds), 2),
        'n_periods': len(sharpes),
    }

print(f"\n  {'Strategy':<20} {'MeanSharpe':>12} {'StdSharpe':>12} {'MeanCAGR%':>10} {'MeanMDD%':>10}")
print(f"  {'-'*70}")
for sname in strat_names:
    a = agg[sname]
    print(f"  {sname:<20} {a['mean_sharpe']:>12.4f} {a['std_sharpe']:>12.4f} {a['mean_cagr']:>10.2f} {a['mean_mdd']:>10.2f}")

# =================================================================
# 6. STATISTICAL TESTS
# =================================================================
print("\n[6] Statistical Tests (DM test + Bootstrap)...")

# Concatenate all OOS returns for overall DM test
all_oos = pd.concat(all_res_dfs)

# DM test: compare each HMM strategy vs 12/VIX baseline
dm_results = {}
baseline_ret = (all_oos['w_baseline'].shift(1) * all_oos['spy_ret']).dropna()

for strat_name, w_col in [
    ('HMM-VT-2state', 'w_hmm_vt_2'),
    ('HMM-VT-3state', 'w_hmm_vt_3'),
    ('HMM-Binary', 'w_hmm_binary'),
    ('HMM-VIX-Ensemble', 'w_hmm_ensemble'),
]:
    alt_ret = (all_oos[w_col].shift(1) * all_oos['spy_ret']).dropna()

    # Align
    common_idx = baseline_ret.index.intersection(alt_ret.index)
    b = baseline_ret.loc[common_idx]
    a = alt_ret.loc[common_idx]

    # Loss differential (squared returns as loss proxy — lower is better for risk-adjusted)
    # Actually, for Sharpe comparison, use return differential
    d = a - b
    d_mean = d.mean()
    d_std = d.std()
    n = len(d)

    # Newey-West HAC standard error (lag = int(n^(1/3)))
    lag = int(n ** (1/3))
    gamma0 = np.var(d)
    gamma_sum = 0
    for k in range(1, lag + 1):
        w = 1 - k / (lag + 1)
        gamma_k = np.cov(d.values[k:], d.values[:-k])[0, 1]
        gamma_sum += 2 * w * gamma_k
    hac_var = (gamma0 + gamma_sum) / n
    hac_se = np.sqrt(max(hac_var, 1e-20))

    t_stat = d_mean / hac_se
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=n-1))

    # Bootstrap for Sharpe difference
    n_boot = 10000
    boot_diffs = np.zeros(n_boot)
    b_vals = b.values
    a_vals = a.values
    for boot_i in range(n_boot):
        idx = np.random.randint(0, n, size=n)
        b_boot = b_vals[idx]
        a_boot = a_vals[idx]
        s_b = b_boot.mean() / b_boot.std() if b_boot.std() > 0 else 0
        s_a = a_boot.mean() / a_boot.std() if a_boot.std() > 0 else 0
        boot_diffs[boot_i] = s_a - s_b

    boot_mean = np.mean(boot_diffs)
    boot_ci_lo = np.percentile(boot_diffs, 2.5)
    boot_ci_hi = np.percentile(boot_diffs, 97.5)
    boot_p_positive = (boot_diffs > 0).mean()

    dm_results[strat_name] = {
        'dm_t': round(t_stat, 4),
        'dm_p': round(p_val, 6),
        'harvey_pass': abs(t_stat) > 3.0,
        'mean_diff_ann': round(d_mean * 252 * 100, 4),
        'boot_sharpe_diff_mean': round(boot_mean * np.sqrt(252), 4),
        'boot_ci_95': [round(boot_ci_lo * np.sqrt(252), 4),
                       round(boot_ci_hi * np.sqrt(252), 4)],
        'boot_p_positive': round(boot_p_positive, 4),
    }

    sig = "★ PASS" if abs(t_stat) > 3.0 else "NS"
    print(f"\n  {strat_name} vs 12/VIX:")
    print(f"    DM t-stat: {t_stat:.4f} (p={p_val:.4f}) [{sig}]")
    print(f"    Mean return diff (ann): {d_mean*252*100:.4f}%")
    print(f"    Bootstrap Sharpe diff: {boot_mean*np.sqrt(252):.4f} "
          f"[{boot_ci_lo*np.sqrt(252):.4f}, {boot_ci_hi*np.sqrt(252):.4f}]")
    print(f"    P(HMM > VIX): {boot_p_positive:.4f}")

# =================================================================
# 7. REGIME ANALYSIS: RETURNS BY HMM STATE
# =================================================================
print("\n[7] Regime Analysis: Returns by HMM State...")

# In the combined OOS data, check if HMM regime info predicts returns
for state_type, p_col, label in [
    ('2-state', 'p_calm_2', 'P(calm)'),
    ('3-state', 'p_crisis_3', 'P(crisis)'),
]:
    print(f"\n  --- {state_type}: {label} ---")
    # Quintile analysis
    all_oos['prob_q'] = pd.qcut(all_oos[p_col], 5, labels=False, duplicates='drop')
    for q in sorted(all_oos['prob_q'].dropna().unique()):
        mask = all_oos['prob_q'] == q
        q_ret = all_oos.loc[mask, 'spy_ret']
        q_vix = all_oos.loc[mask, 'vix']
        ann_ret = q_ret.mean() * 252
        ann_vol = q_ret.std() * np.sqrt(252)
        print(f"    Q{int(q)+1}: n={mask.sum()}, ann_ret={ann_ret:.4f}, "
              f"ann_vol={ann_vol:.4f}, avg_vix={q_vix.mean():.2f}")

# =================================================================
# 8. INFORMATION CONTENT ANALYSIS
# =================================================================
print("\n[8] Information Content: Does HMM add to VIX?...")

# Regression: next-day |return| ~ VIX + P(stress)
from numpy.linalg import lstsq

y = all_oos['spy_ret'].shift(-1).abs().dropna().values[:-1]
X_vix = all_oos['vix'].values[:-2]
X_stress = all_oos['p_stress_2'].values[:-2]

# VIX only
X1 = np.column_stack([np.ones(len(X_vix)), X_vix])
beta1, _, _, _ = lstsq(X1, y[:len(X1)], rcond=None)
resid1 = y[:len(X1)] - X1 @ beta1
r2_vix = 1 - np.var(resid1) / np.var(y[:len(X1)])

# VIX + HMM
X2 = np.column_stack([np.ones(len(X_vix)), X_vix, X_stress])
beta2, _, _, _ = lstsq(X2, y[:len(X2)], rcond=None)
resid2 = y[:len(X2)] - X2 @ beta2
r2_both = 1 - np.var(resid2) / np.var(y[:len(X2)])

# Partial R^2 of HMM
partial_r2 = (r2_both - r2_vix) / (1 - r2_vix) if r2_vix < 1 else 0

print(f"  R^2 (VIX only): {r2_vix:.6f}")
print(f"  R^2 (VIX + HMM): {r2_both:.6f}")
print(f"  Partial R^2 of HMM: {partial_r2:.6f}")
print(f"  Beta(VIX): {beta2[1]:.6f}")
print(f"  Beta(HMM_stress): {beta2[2]:.6f}")

# F-test for incremental HMM variable
n_obs = len(y[:len(X2)])
ssr1 = np.sum(resid1**2)
ssr2 = np.sum(resid2**2)
f_stat = ((ssr1 - ssr2) / 1) / (ssr2 / (n_obs - 3))
f_p = 1 - stats.f.cdf(f_stat, 1, n_obs - 3)
print(f"  F-test (HMM incremental): F={f_stat:.4f}, p={f_p:.6f}")

# =================================================================
# 9. TURNOVER ANALYSIS
# =================================================================
print("\n[9] Turnover Analysis...")

for w_col, label in [
    ('w_baseline', '12/VIX'),
    ('w_hmm_vt_2', 'HMM-VT-2state'),
    ('w_hmm_vt_3', 'HMM-VT-3state'),
    ('w_hmm_binary', 'HMM-Binary'),
    ('w_hmm_ensemble', 'HMM-VIX-Ensemble'),
]:
    turnover = all_oos[w_col].diff().abs().mean()
    print(f"  {label:<20}: daily turnover = {turnover:.6f}")

# =================================================================
# 10. WIN/LOSS PERIOD ANALYSIS
# =================================================================
print("\n[10] Win/Loss Period Analysis...")

for strat_name in ['HMM-VT-2state', 'HMM-VT-3state', 'HMM-Binary', 'HMM-VIX-Ensemble']:
    wins = 0
    for pk, pv in all_results.items():
        if strat_name in pv['strategies'] and '12/VIX' in pv['strategies']:
            if pv['strategies'][strat_name]['sharpe'] > pv['strategies']['12/VIX']['sharpe']:
                wins += 1
    total = len(all_results)
    print(f"  {strat_name:<20}: wins {wins}/{total} vs 12/VIX")

# =================================================================
# 11. SUMMARY & CONCLUSIONS
# =================================================================
print("\n" + "=" * 70)
print("[SUMMARY] K554: HMM Regime Detection for VT")
print("=" * 70)

elapsed = time.time() - start_time

# Determine overall verdict
any_pass = any(v['harvey_pass'] for v in dm_results.values())
best_hmm = max(
    [(name, agg[name]['mean_sharpe']) for name in strat_names if 'HMM' in name],
    key=lambda x: x[1]
)
baseline_sharpe = agg['12/VIX']['mean_sharpe']

print(f"\n  Baseline (12/VIX) mean Sharpe: {baseline_sharpe:.4f}")
print(f"  Best HMM strategy: {best_hmm[0]} (mean Sharpe: {best_hmm[1]:.4f})")
print(f"  Sharpe delta: {best_hmm[1] - baseline_sharpe:+.4f}")
print(f"  Harvey test pass (any): {any_pass}")
print(f"  HMM-VIX regime agreement: {agreement*100:.1f}%")
print(f"  HMM partial R^2 beyond VIX: {partial_r2:.6f}")
print(f"  Elapsed: {elapsed:.1f}s")

if not any_pass:
    print(f"\n  ★ CONCLUSION: NULL RESULT — HMM regime detection does not")
    print(f"    improve 12/VIX for VT strategy. This is consistent with:")
    print(f"    - K533: backward-looking models lose to forward-looking VIX")
    print(f"    - Regime-adaptive overlay already shown redundant")
    print(f"    - VIX already encodes regime information")
    print(f"    HMM identifies real regimes (high agreement with VIX)")
    print(f"    but cannot ADD information beyond what VIX already provides.")
    verdict = "NULL"
else:
    print(f"\n  ★ SIGNIFICANT RESULT — HMM regime provides value beyond VIX!")
    verdict = "SIGNIFICANT"

# =================================================================
# 12. SAVE RESULTS
# =================================================================
print("\n[12] Saving results...")

results_json = {
    "experiment_id": "k554",
    "title": "K554: Hidden Markov Model Regime Detection for VT",
    "date": datetime.now().strftime("%Y-%m-%d"),
    "verdict": verdict,
    "data_source": "yfinance (SPY, ^VIX)",
    "data_period": f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    "n_observations": len(df),
    "methodology": {
        "hmm_library": "hmmlearn.GaussianHMM",
        "features": ["daily_return", "5d_abs_return"],
        "n_states": [2, 3],
        "refit_frequency": "252 days (annual)",
        "warmup": 1000,
        "weight_cap": 2.0,
        "cross_oos_periods": 3,
        "harvey_threshold": 3.0,
        "bootstrap_reps": 10000,
    },
    "literature": [
        "Hamilton (1989): HMM for business cycles, Econometrica",
        "Ang & Bekaert (2002): Regime switching asset allocation, RFS",
        "Guidolin & Timmermann (2007): Multivariate regime switching, JEDC",
        "Moreira & Muir (2017): Volatility-Managed Portfolios, JF",
        "Harvey, Liu & Zhu (2016): ...and the Cross-Section, RFS",
    ],
    "full_sample_analysis": {
        "hmm_2state": {
            "calm_pct": round((states2 == calm_idx_2).mean() * 100, 1),
            "stress_pct": round((states2 == stress_idx_2).mean() * 100, 1),
            "corr_p_stress_vix": round(corr_2state, 4),
            "agreement_with_vix": round(agreement * 100, 1),
        },
        "hmm_3state": {
            "corr_p_crisis_vix": round(corr_3state, 4),
        },
    },
    "cross_oos_results": all_results,
    "aggregate": agg,
    "dm_tests": dm_results,
    "information_content": {
        "r2_vix_only": round(r2_vix, 6),
        "r2_vix_plus_hmm": round(r2_both, 6),
        "partial_r2_hmm": round(partial_r2, 6),
        "f_stat": round(f_stat, 4),
        "f_p": round(f_p, 6),
    },
    "elapsed_seconds": round(elapsed, 1),
}

output_path = "experiments/k554_hmm_regime_results.json"
with open(output_path, 'w') as f:
    json.dump(results_json, f, indent=2, default=str)
print(f"  Saved to {output_path}")

print(f"\n  Total elapsed: {elapsed:.1f}s")
print("  DONE.")
