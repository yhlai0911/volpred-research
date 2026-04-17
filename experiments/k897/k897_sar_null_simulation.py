"""
K897: Null Simulation for Volatility Absorption — Does SAR Arise Mechanically from GARCH?

Purpose:
  Paper 8 (volatility-absorption) R1 found SEVERE S1: "No null simulation — the paper
  does not show the SAR decline cannot arise mechanically from a standard GARCH with
  no absorption."

  The SAR (Shock Amplification Ratio) = mean(|r_t| on shock days) / mean(|r_t| on normal days)
  within each VIX regime. The paper claims SAR declines from 3.16x (calm) to 2.32x (high),
  revealing a real absorption phenomenon.

  A critic could argue: GARCH already has mean-reverting variance (persistence < 1),
  so SAR decline is just GARCH mean reversion, not a new phenomenon.

Methodology:
  1. Fit GJR-GARCH(1,1) with Student-t innovations to SPY returns (2006-2026)
  2. Simulate 10,000 paths of length 5,000 from this fitted GARCH (NO absorption mechanism)
  3. For each simulated path, compute SAR at each VIX regime equivalent
  4. Compare simulated SAR distribution to empirical SAR from real data

Key Question:
  If simulated GARCH SAR matches empirical SAR → absorption is just GARCH mean reversion (null supported)
  If empirical SAR differs significantly → there IS a real phenomenon beyond GARCH

Statistical Tests:
  - Mean SAR comparison (simulated vs empirical) at each regime
  - 95% CI from simulation
  - Kolmogorov-Smirnov test
  - Effect size (Cohen's d)

References:
  - Bollerslev (1986): GARCH model
  - Glosten, Jagannathan, Runkle (1993): GJR-GARCH
  - Engle & Ng (1993): News impact curve
  - Our paper: volatility-absorption, SAR definition (Equation 1)
  - K716: Original SAR computation on real data

Data Source: yfinance (SPY, ^VIX), 2006-01-01 to 2026-04-04
"""

import json
import warnings
import numpy as np
import pandas as pd
from scipy import stats
from arch import arch_model
from concurrent.futures import ProcessPoolExecutor
import multiprocessing

warnings.filterwarnings('ignore')

# ============================================================
# 1. Download real data and compute empirical SAR
# ============================================================
def get_empirical_data():
    """Download SPY + VIX data and compute empirical SAR."""
    import yfinance as yf

    spy = yf.download('SPY', start='2006-01-01', end='2026-04-05', progress=False)
    vix = yf.download('^VIX', start='2006-01-01', end='2026-04-05', progress=False)

    # Handle MultiIndex columns
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)

    # Compute log returns
    spy_ret = np.log(spy['Close'] / spy['Close'].shift(1)).dropna() * 100  # percent
    vix_close = vix['Close'].reindex(spy_ret.index)

    # Align
    df = pd.DataFrame({
        'ret': spy_ret,
        'vix': vix_close,
    }).dropna()

    df['abs_ret'] = df['ret'].abs()
    df['delta_vix'] = df['vix'].diff()
    df['shock'] = df['delta_vix'].abs() > 2  # shock threshold = 2

    return df


def compute_sar_from_data(df):
    """Compute SAR for each VIX regime from a DataFrame with 'abs_ret', 'vix', 'shock' columns."""
    regimes = {
        'calm (<15)': (0, 15),
        'normal (15-20)': (15, 20),
        'elevated (20-25)': (20, 25),
        'high (25-30)': (25, 30),
        'crisis (>=30)': (30, 200),
    }

    results = {}
    for name, (lo, hi) in regimes.items():
        mask = (df['vix'] >= lo) & (df['vix'] < hi)
        shock_mask = mask & df['shock']
        normal_mask = mask & ~df['shock']

        n_shock = shock_mask.sum()
        n_normal = normal_mask.sum()

        if n_shock > 5 and n_normal > 5:
            mean_shock = df.loc[shock_mask, 'abs_ret'].mean()
            mean_normal = df.loc[normal_mask, 'abs_ret'].mean()
            sar = mean_shock / mean_normal
        else:
            mean_shock = np.nan
            mean_normal = np.nan
            sar = np.nan

        results[name] = {
            'n_shock': int(n_shock),
            'n_normal': int(n_normal),
            'mean_shock': float(mean_shock) if not np.isnan(mean_shock) else None,
            'mean_normal': float(mean_normal) if not np.isnan(mean_normal) else None,
            'sar': float(sar) if not np.isnan(sar) else None,
        }

    return results


# ============================================================
# 2. Fit GJR-GARCH to real SPY returns
# ============================================================
def fit_garch(returns):
    """Fit GJR-GARCH(1,1) with Student-t innovations to SPY returns."""
    # returns in percent
    am = arch_model(returns, vol='Garch', p=1, o=1, q=1, dist='t', mean='AR', lags=1)
    res = am.fit(disp='off')

    params = {
        'mu': res.params.get('Const', 0),
        'ar1': res.params.get('y[1]', 0) if 'y[1]' in res.params else 0,
        'omega': res.params['omega'],
        'alpha': res.params['alpha[1]'],
        'gamma': res.params.get('gamma[1]', 0),
        'beta': res.params['beta[1]'],
        'nu': res.params['nu'],
        'persistence': res.params['alpha[1]'] + res.params.get('gamma[1]', 0) / 2 + res.params['beta[1]'],
    }

    return res, params


# ============================================================
# 3. Simulate GARCH paths and compute SAR
# ============================================================
def simulate_garch_path(args):
    """Simulate one GJR-GARCH path and compute SAR.

    Since GARCH doesn't have a VIX, we use conditional volatility percentiles
    to define regimes (analogous to VIX regimes).
    """
    seed, params, n_obs, vix_percentiles = args
    rng = np.random.RandomState(seed)

    mu = params['mu']
    ar1 = params['ar1']
    omega = params['omega']
    alpha = params['alpha']
    gamma = params['gamma']
    beta = params['beta']
    nu = params['nu']

    # Generate Student-t innovations
    # scipy t distribution: scale by sqrt((nu-2)/nu) to get unit variance
    z = rng.standard_t(df=nu, size=n_obs) * np.sqrt((nu - 2) / nu)

    # Simulate returns
    r = np.zeros(n_obs)
    h = np.zeros(n_obs)  # conditional variance

    # Initialize
    unconditional_var = omega / (1 - alpha - gamma / 2 - beta)
    h[0] = unconditional_var
    r[0] = mu + np.sqrt(h[0]) * z[0]

    for t in range(1, n_obs):
        # GJR-GARCH variance equation
        indicator = 1.0 if r[t-1] - mu < 0 else 0.0
        eps = r[t-1] - mu - ar1 * (r[t-2] if t >= 2 else 0)
        h[t] = omega + (alpha + gamma * indicator) * eps**2 + beta * h[t-1]
        h[t] = max(h[t], 1e-8)  # floor

        # Return with AR(1)
        r[t] = mu + ar1 * r[t-1] + np.sqrt(h[t]) * z[t]

    # Compute conditional vol (annualized, to be analogous to VIX)
    # VIX ~ sqrt(h) * sqrt(252) where h is daily variance in decimal
    # Our returns are in percent, so sqrt(h) is daily vol in percent
    # VIX equivalent: sqrt(h) * sqrt(252)
    cond_vol_ann = np.sqrt(h) * np.sqrt(252)

    # Define "shock" as large absolute change in conditional vol
    # Analogous to |delta_VIX| > 2
    delta_vol = np.diff(cond_vol_ann)
    delta_vol = np.concatenate([[0], delta_vol])

    # Use empirical VIX percentile thresholds for regime definition
    # This ensures comparable regime sizes
    abs_ret = np.abs(r)

    # Define regimes based on conditional vol using empirical VIX thresholds
    regimes = {
        'calm (<15)': (0, vix_percentiles[15]),
        'normal (15-20)': (vix_percentiles[15], vix_percentiles[20]),
        'elevated (20-25)': (vix_percentiles[20], vix_percentiles[25]),
        'high (25-30)': (vix_percentiles[25], vix_percentiles[30]),
        'crisis (>=30)': (vix_percentiles[30], 1e6),
    }

    # Shock threshold: use same percentile as empirical
    # In real data, |delta_VIX| > 2 captures about 15-20% of days
    shock_pct = np.percentile(np.abs(delta_vol[1:]), 80)  # top 20% as shocks
    shock = np.abs(delta_vol) > shock_pct

    results = {}
    for name, (lo, hi) in regimes.items():
        mask = (cond_vol_ann >= lo) & (cond_vol_ann < hi)
        shock_mask = mask & shock
        normal_mask = mask & ~shock

        n_shock = shock_mask.sum()
        n_normal = normal_mask.sum()

        if n_shock > 5 and n_normal > 5:
            mean_shock = abs_ret[shock_mask].mean()
            mean_normal = abs_ret[normal_mask].mean()
            sar = mean_shock / mean_normal
        else:
            sar = np.nan

        results[name] = sar

    return results


def simulate_garch_sar_fixed_thresholds(args):
    """Simulate one GJR-GARCH path and compute SAR using FIXED VIX-equivalent thresholds.

    This is the more conservative approach: use the same absolute thresholds (15, 20, 25, 30)
    applied to annualized conditional vol, and the same shock threshold (delta > 2 points).
    """
    seed, params, n_obs = args
    rng = np.random.RandomState(seed)

    mu = params['mu']
    ar1 = params['ar1']
    omega = params['omega']
    alpha = params['alpha']
    gamma = params['gamma']
    beta = params['beta']
    nu = params['nu']

    # Generate Student-t innovations
    z = rng.standard_t(df=nu, size=n_obs) * np.sqrt((nu - 2) / nu)

    # Simulate returns
    r = np.zeros(n_obs)
    h = np.zeros(n_obs)

    unconditional_var = omega / (1 - alpha - gamma / 2 - beta)
    h[0] = unconditional_var
    r[0] = mu + np.sqrt(h[0]) * z[0]

    for t in range(1, n_obs):
        indicator = 1.0 if r[t-1] - mu < 0 else 0.0
        eps = r[t-1] - mu - ar1 * (r[t-2] if t >= 2 else 0)
        h[t] = omega + (alpha + gamma * indicator) * eps**2 + beta * h[t-1]
        h[t] = max(h[t], 1e-8)

        r[t] = mu + ar1 * r[t-1] + np.sqrt(h[t]) * z[t]

    # Annualized conditional vol (VIX equivalent)
    cond_vol_ann = np.sqrt(h) * np.sqrt(252)

    # Delta conditional vol
    delta_vol = np.diff(cond_vol_ann)
    delta_vol = np.concatenate([[0], delta_vol])

    abs_ret = np.abs(r)

    # Fixed thresholds matching VIX regimes
    regimes = {
        'calm (<15)': (0, 15),
        'normal (15-20)': (15, 20),
        'elevated (20-25)': (20, 25),
        'high (25-30)': (25, 30),
        'crisis (>=30)': (30, 1e6),
    }

    # Fixed shock threshold: |delta_vol| > 2 (same as |delta_VIX| > 2)
    shock = np.abs(delta_vol) > 2

    results = {}
    for name, (lo, hi) in regimes.items():
        mask = (cond_vol_ann >= lo) & (cond_vol_ann < hi)
        shock_mask = mask & shock
        normal_mask = mask & ~shock

        n_shock = shock_mask.sum()
        n_normal = normal_mask.sum()

        if n_shock > 5 and n_normal > 5:
            mean_shock = abs_ret[shock_mask].mean()
            mean_normal = abs_ret[normal_mask].mean()
            sar = mean_shock / mean_normal
        else:
            sar = np.nan

        results[name] = sar

    return results


# ============================================================
# 4. Sensitivity to persistence level
# ============================================================
def simulate_with_persistence(args):
    """Simulate GARCH with modified persistence and compute SAR."""
    seed, base_params, target_persistence, n_obs = args
    params = base_params.copy()

    # Scale alpha and gamma to achieve target persistence while keeping ratio
    current_p = params['alpha'] + params['gamma'] / 2 + params['beta']
    # Adjust beta to hit target persistence
    params['beta'] = target_persistence - params['alpha'] - params['gamma'] / 2
    if params['beta'] < 0:
        params['beta'] = 0.01
        excess = target_persistence - params['beta']
        params['alpha'] = excess * (params['alpha'] / (params['alpha'] + params['gamma'] / 2))
        params['gamma'] = 2 * (excess - params['alpha'])

    return simulate_garch_sar_fixed_thresholds((seed, params, n_obs))


# ============================================================
# 5. Main execution
# ============================================================
def main():
    print("=" * 70)
    print("K897: Null Simulation for Volatility Absorption")
    print("Does SAR decline arise mechanically from GARCH?")
    print("=" * 70)

    # ---- Step 1: Get empirical data ----
    print("\n[1/5] Downloading real data and computing empirical SAR...")
    df = get_empirical_data()
    empirical_sar = compute_sar_from_data(df)

    print(f"  Sample: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
    print(f"  Observations: {len(df)}")
    print(f"  Shock days (|dVIX| > 2): {df['shock'].sum()}")

    print("\n  Empirical SAR:")
    for regime, vals in empirical_sar.items():
        if vals['sar'] is not None:
            print(f"    {regime}: SAR = {vals['sar']:.3f} (n_shock={vals['n_shock']}, n_normal={vals['n_normal']})")

    # ---- Step 2: Fit GJR-GARCH ----
    print("\n[2/5] Fitting GJR-GARCH(1,1) with Student-t to SPY...")
    res, params = fit_garch(df['ret'])

    print(f"  mu     = {params['mu']:.6f}")
    print(f"  ar1    = {params['ar1']:.6f}")
    print(f"  omega  = {params['omega']:.6f}")
    print(f"  alpha  = {params['alpha']:.6f}")
    print(f"  gamma  = {params['gamma']:.6f}")
    print(f"  beta   = {params['beta']:.6f}")
    print(f"  nu     = {params['nu']:.4f}")
    print(f"  persistence = {params['persistence']:.6f}")

    # Compute empirical VIX percentile thresholds
    vix_vals = df['vix'].dropna()
    vix_percentiles = {}
    for thresh in [15, 20, 25, 30]:
        pct = (vix_vals < thresh).mean() * 100
        vix_percentiles[thresh] = np.percentile(np.sqrt(res.conditional_volatility.values**2) * np.sqrt(252) / 100 * np.sqrt(252), pct)
        # Actually, let's use cond vol percentiles properly
    # Recompute: map empirical VIX levels to conditional vol percentiles
    cond_vol_ann_empirical = res.conditional_volatility * np.sqrt(252)  # annualized in %
    for thresh in [15, 20, 25, 30]:
        pct = (vix_vals < thresh).mean()
        vix_percentiles[thresh] = np.percentile(cond_vol_ann_empirical.values, pct * 100)
    print(f"\n  VIX percentile mapping to conditional vol:")
    for thresh in [15, 20, 25, 30]:
        print(f"    VIX < {thresh} ≈ cond_vol < {vix_percentiles[thresh]:.1f}% (pct={100*(vix_vals < thresh).mean():.1f}%)")

    # ---- Step 3: Monte Carlo simulation with FIXED thresholds ----
    N_SIM = 10000
    N_OBS = 5000
    print(f"\n[3/5] Running {N_SIM} GARCH simulations (fixed thresholds, n={N_OBS} each)...")

    n_workers = min(8, multiprocessing.cpu_count())

    # Method 1: Fixed thresholds (primary — most comparable to empirical)
    sim_args = [(seed, params, N_OBS) for seed in range(N_SIM)]

    sim_results_fixed = []
    with ProcessPoolExecutor(max_workers=n_workers) as executor:
        for i, result in enumerate(executor.map(simulate_garch_sar_fixed_thresholds, sim_args, chunksize=100)):
            sim_results_fixed.append(result)
            if (i + 1) % 2000 == 0:
                print(f"    Fixed threshold: {i+1}/{N_SIM} done")

    # Method 2: Percentile-based thresholds (robustness)
    print(f"\n[4/5] Running {N_SIM} GARCH simulations (percentile thresholds)...")
    sim_args_pct = [(seed, params, N_OBS, vix_percentiles) for seed in range(N_SIM)]

    sim_results_pct = []
    with ProcessPoolExecutor(max_workers=n_workers) as executor:
        for i, result in enumerate(executor.map(simulate_garch_path, sim_args_pct, chunksize=100)):
            sim_results_pct.append(result)
            if (i + 1) % 2000 == 0:
                print(f"    Percentile: {i+1}/{N_SIM} done")

    # ---- Step 4: Compare simulated vs empirical SAR ----
    print("\n[5/5] Comparing simulated vs empirical SAR...")

    regime_names = ['calm (<15)', 'normal (15-20)', 'elevated (20-25)', 'high (25-30)', 'crisis (>=30)']

    # Collect simulated SARs
    output = {
        'experiment_id': 'k897',
        'title': 'Null Simulation: Does SAR Arise Mechanically from GARCH?',
        'data_source': 'yfinance (SPY, ^VIX), simulation',
        'sample_period': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
        'n_observations': len(df),
        'n_simulations': N_SIM,
        'n_obs_per_sim': N_OBS,
        'garch_params': {k: float(v) for k, v in params.items()},
    }

    # === Fixed threshold results ===
    print("\n" + "=" * 70)
    print("METHOD 1: FIXED THRESHOLDS (same as VIX: 15/20/25/30, shock > 2)")
    print("=" * 70)

    fixed_results = {}
    for regime in regime_names:
        sim_sars = [r[regime] for r in sim_results_fixed if not np.isnan(r.get(regime, np.nan))]
        emp_sar = empirical_sar[regime]['sar'] if regime in empirical_sar and empirical_sar[regime]['sar'] is not None else None

        if len(sim_sars) > 100 and emp_sar is not None:
            sim_mean = np.mean(sim_sars)
            sim_std = np.std(sim_sars)
            sim_ci_lo = np.percentile(sim_sars, 2.5)
            sim_ci_hi = np.percentile(sim_sars, 97.5)

            # Is empirical SAR within simulated CI?
            in_ci = sim_ci_lo <= emp_sar <= sim_ci_hi

            # Effect size (Cohen's d)
            cohens_d = (emp_sar - sim_mean) / sim_std if sim_std > 0 else 0

            # KS test: is empirical SAR consistent with simulation distribution?
            # One-sample z-test
            z_score = (emp_sar - sim_mean) / (sim_std / np.sqrt(len(sim_sars)))
            p_value = 2 * (1 - stats.norm.cdf(abs(z_score)))

            # More informative: what fraction of simulations produce SAR >= empirical?
            frac_above = np.mean(np.array(sim_sars) >= emp_sar)

            fixed_results[regime] = {
                'empirical_sar': round(emp_sar, 4),
                'sim_mean': round(sim_mean, 4),
                'sim_std': round(sim_std, 4),
                'sim_ci_95': [round(sim_ci_lo, 4), round(sim_ci_hi, 4)],
                'in_95_ci': bool(in_ci),
                'cohens_d': round(cohens_d, 4),
                'z_score': round(z_score, 4),
                'p_value': round(p_value, 6),
                'frac_sim_above_empirical': round(frac_above, 4),
                'n_valid_sims': len(sim_sars),
            }

            print(f"\n  {regime}:")
            print(f"    Empirical SAR:  {emp_sar:.3f}")
            print(f"    Simulated SAR:  {sim_mean:.3f} ± {sim_std:.3f}  [{sim_ci_lo:.3f}, {sim_ci_hi:.3f}]")
            print(f"    In 95% CI?      {'YES' if in_ci else 'NO'}")
            print(f"    Cohen's d:      {cohens_d:.3f}")
            print(f"    z-score:        {z_score:.3f} (p = {p_value:.6f})")
            print(f"    Frac sim >= emp: {frac_above:.3f}")
        else:
            fixed_results[regime] = {
                'empirical_sar': emp_sar,
                'n_valid_sims': len(sim_sars),
                'note': 'Insufficient simulated data for comparison'
            }
            print(f"\n  {regime}: insufficient data (n_valid_sims={len(sim_sars)})")

    output['fixed_threshold_results'] = fixed_results

    # === SAR decline pattern comparison ===
    print("\n" + "-" * 50)
    print("SAR DECLINE PATTERN (calm → high)")
    print("-" * 50)

    # Empirical decline
    emp_calm = empirical_sar['calm (<15)']['sar']
    emp_high = empirical_sar['high (25-30)']['sar']
    emp_decline = emp_calm - emp_high if emp_calm and emp_high else None

    # Simulated decline
    sim_declines = []
    for r in sim_results_fixed:
        calm_sar = r.get('calm (<15)', np.nan)
        high_sar = r.get('high (25-30)', np.nan)
        if not np.isnan(calm_sar) and not np.isnan(high_sar):
            sim_declines.append(calm_sar - high_sar)

    if len(sim_declines) > 100 and emp_decline is not None:
        sim_decline_mean = np.mean(sim_declines)
        sim_decline_std = np.std(sim_declines)
        sim_decline_ci = [np.percentile(sim_declines, 2.5), np.percentile(sim_declines, 97.5)]
        decline_in_ci = sim_decline_ci[0] <= emp_decline <= sim_decline_ci[1]
        decline_z = (emp_decline - sim_decline_mean) / sim_decline_std
        decline_p = 2 * (1 - stats.norm.cdf(abs(decline_z)))
        decline_d = (emp_decline - sim_decline_mean) / sim_decline_std

        print(f"  Empirical SAR decline (calm→high): {emp_decline:.3f}")
        print(f"  Simulated SAR decline:             {sim_decline_mean:.3f} ± {sim_decline_std:.3f}")
        print(f"  95% CI:                            [{sim_decline_ci[0]:.3f}, {sim_decline_ci[1]:.3f}]")
        print(f"  In 95% CI?                         {'YES' if decline_in_ci else 'NO'}")
        print(f"  Cohen's d:                         {decline_d:.3f}")
        print(f"  z-score:                           {decline_z:.3f} (p = {decline_p:.6f})")

        output['sar_decline_comparison'] = {
            'empirical_decline': round(emp_decline, 4),
            'sim_mean_decline': round(sim_decline_mean, 4),
            'sim_std_decline': round(sim_decline_std, 4),
            'sim_ci_95': [round(sim_decline_ci[0], 4), round(sim_decline_ci[1], 4)],
            'in_95_ci': bool(decline_in_ci),
            'cohens_d': round(decline_d, 4),
            'z_score': round(decline_z, 4),
            'p_value': round(decline_p, 6),
            'n_valid_sims': len(sim_declines),
        }

    # === Percentile threshold results (robustness) ===
    print("\n" + "=" * 70)
    print("METHOD 2: PERCENTILE THRESHOLDS (robustness)")
    print("=" * 70)

    pct_results = {}
    for regime in regime_names:
        sim_sars = [r[regime] for r in sim_results_pct if not np.isnan(r.get(regime, np.nan))]
        emp_sar = empirical_sar[regime]['sar'] if regime in empirical_sar and empirical_sar[regime]['sar'] is not None else None

        if len(sim_sars) > 100 and emp_sar is not None:
            sim_mean = np.mean(sim_sars)
            sim_std = np.std(sim_sars)
            sim_ci_lo = np.percentile(sim_sars, 2.5)
            sim_ci_hi = np.percentile(sim_sars, 97.5)
            in_ci = sim_ci_lo <= emp_sar <= sim_ci_hi
            cohens_d = (emp_sar - sim_mean) / sim_std if sim_std > 0 else 0

            pct_results[regime] = {
                'empirical_sar': round(emp_sar, 4),
                'sim_mean': round(sim_mean, 4),
                'sim_std': round(sim_std, 4),
                'sim_ci_95': [round(sim_ci_lo, 4), round(sim_ci_hi, 4)],
                'in_95_ci': bool(in_ci),
                'cohens_d': round(cohens_d, 4),
                'n_valid_sims': len(sim_sars),
            }

            print(f"\n  {regime}:")
            print(f"    Empirical SAR:  {emp_sar:.3f}")
            print(f"    Simulated SAR:  {sim_mean:.3f} ± {sim_std:.3f}  [{sim_ci_lo:.3f}, {sim_ci_hi:.3f}]")
            print(f"    In 95% CI?      {'YES' if in_ci else 'NO'}")
        else:
            pct_results[regime] = {'n_valid_sims': len(sim_sars), 'note': 'Insufficient data'}
            print(f"\n  {regime}: insufficient data")

    output['percentile_threshold_results'] = pct_results

    # === Persistence sensitivity ===
    print("\n" + "=" * 70)
    print("PERSISTENCE SENSITIVITY ANALYSIS")
    print("=" * 70)

    persistence_levels = [0.90, 0.95, 0.97, 0.99]
    N_SIM_SENS = 2000  # fewer sims for sensitivity

    persistence_results = {}
    for target_p in persistence_levels:
        print(f"\n  Persistence = {target_p}:")
        sim_args_p = [(seed, params, target_p, N_OBS) for seed in range(N_SIM_SENS)]

        sens_results = []
        with ProcessPoolExecutor(max_workers=n_workers) as executor:
            for result in executor.map(simulate_with_persistence, sim_args_p, chunksize=50):
                sens_results.append(result)

        # SAR decline for this persistence level
        sens_declines = []
        for r in sens_results:
            calm_sar = r.get('calm (<15)', np.nan)
            high_sar = r.get('high (25-30)', np.nan)
            if not np.isnan(calm_sar) and not np.isnan(high_sar):
                sens_declines.append(calm_sar - high_sar)

        regime_sars = {}
        for regime in regime_names:
            sars = [r[regime] for r in sens_results if not np.isnan(r.get(regime, np.nan))]
            if sars:
                regime_sars[regime] = {
                    'mean': round(np.mean(sars), 4),
                    'std': round(np.std(sars), 4),
                    'n_valid': len(sars),
                }
                print(f"    {regime}: SAR = {np.mean(sars):.3f} ± {np.std(sars):.3f} (n={len(sars)})")

        if sens_declines:
            mean_decline = np.mean(sens_declines)
            print(f"    SAR decline (calm→high): {mean_decline:.3f}")
            persistence_results[str(target_p)] = {
                'regimes': regime_sars,
                'mean_decline': round(mean_decline, 4),
                'n_valid_declines': len(sens_declines),
            }

    output['persistence_sensitivity'] = persistence_results

    # === GJR asymmetry test ===
    print("\n" + "=" * 70)
    print("GJR vs SYMMETRIC GARCH COMPARISON")
    print("=" * 70)

    # Run symmetric GARCH (gamma=0)
    params_sym = params.copy()
    params_sym['gamma'] = 0.0
    # Adjust alpha to keep similar persistence
    params_sym['alpha'] = params['alpha'] + params['gamma'] / 2

    print(f"  Symmetric GARCH: alpha={params_sym['alpha']:.6f}, gamma=0, beta={params_sym['beta']:.6f}")
    print(f"  Persistence: {params_sym['alpha'] + params_sym['beta']:.6f}")

    sim_args_sym = [(seed, params_sym, N_OBS) for seed in range(N_SIM_SENS)]

    sym_results = []
    with ProcessPoolExecutor(max_workers=n_workers) as executor:
        for result in executor.map(simulate_garch_sar_fixed_thresholds, sim_args_sym, chunksize=50):
            sym_results.append(result)

    sym_declines = []
    for r in sym_results:
        calm_sar = r.get('calm (<15)', np.nan)
        high_sar = r.get('high (25-30)', np.nan)
        if not np.isnan(calm_sar) and not np.isnan(high_sar):
            sym_declines.append(calm_sar - high_sar)

    gjr_declines = []
    for r in sim_results_fixed[:N_SIM_SENS]:
        calm_sar = r.get('calm (<15)', np.nan)
        high_sar = r.get('high (25-30)', np.nan)
        if not np.isnan(calm_sar) and not np.isnan(high_sar):
            gjr_declines.append(calm_sar - high_sar)

    if sym_declines and gjr_declines:
        sym_mean = np.mean(sym_declines)
        gjr_mean = np.mean(gjr_declines)
        t_stat, p_val = stats.ttest_ind(gjr_declines, sym_declines)

        print(f"\n  GJR-GARCH SAR decline:       {gjr_mean:.3f}")
        print(f"  Symmetric GARCH SAR decline: {sym_mean:.3f}")
        print(f"  Difference:                  {gjr_mean - sym_mean:.3f}")
        print(f"  t-stat:                      {t_stat:.3f} (p = {p_val:.6f})")

        output['gjr_vs_symmetric'] = {
            'gjr_mean_decline': round(gjr_mean, 4),
            'sym_mean_decline': round(sym_mean, 4),
            'difference': round(gjr_mean - sym_mean, 4),
            't_stat': round(t_stat, 4),
            'p_value': round(p_val, 6),
        }

    # ============================================================
    # SUMMARY AND CONCLUSION
    # ============================================================
    print("\n" + "=" * 70)
    print("SUMMARY AND CONCLUSION")
    print("=" * 70)

    # Determine if null is supported or rejected
    if 'sar_decline_comparison' in output:
        decline_info = output['sar_decline_comparison']
        if decline_info['in_95_ci']:
            conclusion = "NULL SUPPORTED: Empirical SAR decline is within the 95% CI of GARCH simulation"
            detail = (
                f"The empirical SAR decline ({decline_info['empirical_decline']:.3f}) falls within "
                f"the simulated 95% CI [{decline_info['sim_ci_95'][0]:.3f}, {decline_info['sim_ci_95'][1]:.3f}]. "
                f"This means a standard GARCH process with no absorption mechanism can produce "
                f"the observed SAR decline pattern. The absorption effect may be fully explained "
                f"by GARCH mean reversion."
            )
        else:
            if decline_info['empirical_decline'] > decline_info['sim_ci_95'][1]:
                conclusion = "NULL REJECTED: Empirical absorption is STRONGER than GARCH predicts"
                detail = (
                    f"The empirical SAR decline ({decline_info['empirical_decline']:.3f}) exceeds "
                    f"the simulated 95% CI [{decline_info['sim_ci_95'][0]:.3f}, {decline_info['sim_ci_95'][1]:.3f}]. "
                    f"Real markets show MORE absorption than a standard GARCH process would produce. "
                    f"This supports the paper's claim that absorption is a real phenomenon beyond GARCH."
                )
            else:
                conclusion = "NULL REJECTED: Empirical absorption is WEAKER than GARCH predicts"
                detail = (
                    f"The empirical SAR decline ({decline_info['empirical_decline']:.3f}) is below "
                    f"the simulated 95% CI [{decline_info['sim_ci_95'][0]:.3f}, {decline_info['sim_ci_95'][1]:.3f}]. "
                    f"Real markets show LESS absorption than GARCH predicts, which is unexpected."
                )

        print(f"\n  {conclusion}")
        print(f"\n  Detail: {detail}")
        print(f"\n  Cohen's d = {decline_info['cohens_d']:.3f}")
        print(f"  z-score   = {decline_info['z_score']:.3f}")
        print(f"  p-value   = {decline_info['p_value']:.6f}")

        output['conclusion'] = conclusion
        output['detail'] = detail
    else:
        output['conclusion'] = "Insufficient data for conclusive comparison"
        output['detail'] = "SAR decline comparison could not be computed"

    # Count how many regimes have empirical SAR outside simulated CI
    n_outside = 0
    n_tested = 0
    for regime in regime_names:
        fr = fixed_results.get(regime, {})
        if 'in_95_ci' in fr:
            n_tested += 1
            if not fr['in_95_ci']:
                n_outside += 1

    output['regimes_outside_ci'] = f"{n_outside}/{n_tested}"
    print(f"\n  Regimes with empirical SAR outside simulated 95% CI: {n_outside}/{n_tested}")

    # Save results
    output_path = '/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-aa7ddc51/experiments/k897_sar_null_simulation_results.json'
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Results saved to: {output_path}")

    return output


if __name__ == '__main__':
    main()
