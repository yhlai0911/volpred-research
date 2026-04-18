"""
K827v2: ABM VT Crowding — Sensitivity Analysis + 500 Simulations
================================================================
[提出: Paper 5 Codex Reviewer (H1, H5), 執行: Claude]
類型：模擬實驗（非實證數據）

Enhancement over K827:
  - 500 simulations (up from 100) for robust tail statistics
  - Sensitivity analysis: lambda, gamma (VIX sensitivity), kappa (MR speed) ±50%
  - Bootstrap 95% CI for Sharpe, MDD, kurtosis
  - Multiprocessing for M1 Max 10-core

Research Questions:
  1. Is the 30-50% crowding critical threshold stable under parameter perturbation?
  2. Which parameter most affects the threshold?
  3. Are 100 sims sufficient for tail statistics (kurtosis)?

References:
  - K827: Original ABM VT crowding (100 sims, baseline params only)
  - Kyle (1985) Continuous Auctions and Insider Trading, Econometrica
  - Farmer & Foley (2009) Agent-based modelling, Nature
  - Bouchaud et al. (2018) Trades, Quotes and Prices, Cambridge UP
  - Brunnermeier & Pedersen (2009) Market Liquidity and Funding Liquidity, RFS

Error Log rules:
  - SIMULATION experiment, clearly labelled
  - Parameter perturbation: check for NaN/negative prices, skip & record
  - multiprocessing.Pool for M1 Max 10-core parallelism
"""

import sys
import os
import warnings
warnings.filterwarnings("ignore")

import numpy as np
from scipy import stats as sp_stats
import json
from datetime import datetime
from multiprocessing import Pool, cpu_count
from functools import partial
import time

# ============================================================
# Configuration
# ============================================================
N_AGENTS = 1000
N_DAYS = 2520        # 10 years of trading days
N_SIMS_MAIN = 500    # Part 1: increased from 100
N_SIMS_SENS = 200    # Part 2: sensitivity analysis
N_BOOTSTRAP = 2000   # Bootstrap resamples for CI

VT_FRACTIONS_MAIN = [0.0, 0.10, 0.20, 0.30, 0.50, 0.70, 1.00]
VT_FRACTIONS_SENS = [0.10, 0.30, 0.50]  # key levels for sensitivity

# Baseline parameters
BASELINE_PARAMS = {
    'kyle_lambda': 0.005,
    'vix_vol_sensitivity': 200.0,  # gamma
    'vix_mr_speed': 0.03,          # kappa
}

# Sensitivity grid: each param ±50%
SENSITIVITY_GRID = {
    'kyle_lambda': [0.0025, 0.005, 0.0075],
    'vix_vol_sensitivity': [100.0, 200.0, 300.0],
    'vix_mr_speed': [0.015, 0.03, 0.045],
}

# Fixed parameters
INITIAL_PRICE = 100.0
INITIAL_VIX = 15.0
ANNUAL_DRIFT = 0.08
DAILY_DRIFT = ANNUAL_DRIFT / 252
FUNDAMENTAL_VOL = 0.16 / np.sqrt(252)
VIX_MEAN = 18.0
VIX_NOISE_STD = 0.3
VT_CAP = 1.5
NOISE_TRADER_STD = 0.02

N_WORKERS = min(cpu_count(), 8)  # use up to 8 cores


# ============================================================
# Core simulation (single run)
# ============================================================

def run_single_simulation(args):
    """Run one simulation with given parameters.

    Args: tuple of (vt_fraction, seed, param_overrides)
    param_overrides: dict with optional keys kyle_lambda, vix_vol_sensitivity, vix_mr_speed
    """
    vt_fraction, seed, param_overrides = args

    # Extract parameters (with overrides)
    kyle_lambda = param_overrides.get('kyle_lambda', BASELINE_PARAMS['kyle_lambda'])
    vix_vol_sensitivity = param_overrides.get('vix_vol_sensitivity', BASELINE_PARAMS['vix_vol_sensitivity'])
    vix_mr_speed = param_overrides.get('vix_mr_speed', BASELINE_PARAMS['vix_mr_speed'])

    rng = np.random.RandomState(seed)

    # Agent allocation
    n_vt = int(N_AGENTS * vt_fraction)
    n_noise = int(N_AGENTS * 0.3 * (1 - vt_fraction))
    n_bh = N_AGENTS - n_vt - n_noise

    if n_noise < 10:
        n_noise = 10
        n_bh = max(0, N_AGENTS - n_vt - n_noise)

    # State arrays
    prices = np.zeros(N_DAYS)
    returns = np.zeros(N_DAYS)
    vix_series = np.zeros(N_DAYS)

    vt_weights = np.ones(n_vt) * min(12.0 / INITIAL_VIX, VT_CAP) if n_vt > 0 else np.array([])
    noise_weights = np.ones(n_noise) * 0.5

    prices[0] = INITIAL_PRICE
    vix_series[0] = INITIAL_VIX

    ret_buffer = np.zeros(20)
    buffer_idx = 0

    n_nan_events = 0
    n_price_clamp = 0

    for t in range(1, N_DAYS):
        # VIX update (endogenous)
        realized_vol_20d = np.std(ret_buffer) * np.sqrt(252) if t > 1 else FUNDAMENTAL_VOL * np.sqrt(252)

        vix_target = VIX_MEAN + vix_vol_sensitivity * max(0, realized_vol_20d - 0.16)
        vix_series[t] = vix_series[t-1] + vix_mr_speed * (vix_target - vix_series[t-1]) + rng.normal(0, VIX_NOISE_STD)
        vix_series[t] = max(9.0, min(80.0, vix_series[t]))

        # Agent demand
        net_demand = 0.0

        if n_vt > 0:
            vt_target = min(12.0 / vix_series[t-1], VT_CAP)  # signal from t-1 (no lookahead)
            vt_demand_change = (vt_target - vt_weights) * n_vt
            net_demand += np.sum(vt_demand_change)
            vt_weights[:] = vt_target

        noise_changes = rng.normal(0, NOISE_TRADER_STD, size=n_noise)
        noise_weights = np.clip(noise_weights + noise_changes, 0.0, 1.5)
        net_demand += np.sum(noise_changes) * N_AGENTS / n_noise if n_noise > 0 else 0

        # Price formation (Kyle model)
        fundamental_shock = rng.normal(DAILY_DRIFT, FUNDAMENTAL_VOL)
        price_impact = kyle_lambda * net_demand / N_AGENTS

        daily_return = fundamental_shock + price_impact

        # NaN/Inf check
        if not np.isfinite(daily_return):
            daily_return = 0.0
            n_nan_events += 1

        returns[t] = daily_return
        prices[t] = prices[t-1] * (1 + daily_return)

        if prices[t] <= 0:
            prices[t] = 0.01
            returns[t] = (prices[t] / prices[t-1]) - 1
            n_price_clamp += 1

        ret_buffer[buffer_idx % 20] = daily_return
        buffer_idx += 1

    # Compute metrics
    valid_returns = returns[1:]
    ann_vol = np.std(valid_returns) * np.sqrt(252)
    ann_return = np.mean(valid_returns) * 252

    cum_returns = np.cumprod(1 + valid_returns)
    running_max = np.maximum.accumulate(cum_returns)
    drawdowns = cum_returns / running_max - 1
    max_dd = np.min(drawdowns)

    sigma_daily = np.std(valid_returns)
    flash_crashes = np.sum(valid_returns < -3 * sigma_daily) if sigma_daily > 0 else 0
    flash_crash_freq = flash_crashes / len(valid_returns) * 252

    kurtosis = sp_stats.kurtosis(valid_returns, fisher=True)
    skewness = sp_stats.skew(valid_returns)

    vix_mean_val = np.mean(vix_series[1:])
    vix_std_val = np.std(vix_series[1:])
    vix_spikes = np.sum(vix_series[1:] > 30) / len(vix_series[1:])

    # VT strategy performance
    vt_sharpe = np.nan
    vt_return_val = np.nan
    vt_vol_val = np.nan
    if n_vt > 0:
        vt_w = np.minimum(12.0 / vix_series[:-1], VT_CAP)
        vt_port_returns = vt_w * valid_returns
        vt_return_val = np.mean(vt_port_returns) * 252
        vt_vol_calc = np.std(vt_port_returns) * np.sqrt(252)
        vt_sharpe = vt_return_val / vt_vol_calc if vt_vol_calc > 0 else 0
        vt_vol_val = vt_vol_calc

    return {
        'ann_return': float(ann_return),
        'ann_vol': float(ann_vol),
        'max_dd': float(max_dd),
        'flash_crash_freq': float(flash_crash_freq),
        'kurtosis': float(kurtosis),
        'skewness': float(skewness),
        'vix_mean': float(vix_mean_val),
        'vix_std': float(vix_std_val),
        'vix_spike_pct': float(vix_spikes * 100),
        'vt_sharpe': float(vt_sharpe) if not np.isnan(vt_sharpe) else None,
        'vt_return': float(vt_return_val) if not np.isnan(vt_return_val) else None,
        'vt_vol': float(vt_vol_val) if not np.isnan(vt_vol_val) else None,
        'final_price': float(prices[-1]),
        'n_nan_events': n_nan_events,
        'n_price_clamp': n_price_clamp,
    }


def bootstrap_ci(values, n_boot=N_BOOTSTRAP, ci=0.95):
    """Compute bootstrap confidence interval for the mean."""
    values = np.array(values)
    n = len(values)
    boot_means = np.zeros(n_boot)
    rng = np.random.RandomState(12345)
    for i in range(n_boot):
        sample = values[rng.randint(0, n, size=n)]
        boot_means[i] = np.mean(sample)
    alpha = (1 - ci) / 2
    lo = np.percentile(boot_means, alpha * 100)
    hi = np.percentile(boot_means, (1 - alpha) * 100)
    return float(lo), float(hi)


def aggregate_metrics(sim_results):
    """Aggregate list of simulation dicts into summary statistics with bootstrap CI."""
    if not sim_results:
        return {}

    metric_keys = ['ann_return', 'ann_vol', 'max_dd', 'flash_crash_freq',
                   'kurtosis', 'skewness', 'vix_mean', 'vix_std', 'vix_spike_pct',
                   'vt_sharpe', 'vt_return', 'vt_vol', 'final_price']

    agg = {}
    for key in metric_keys:
        values = [m[key] for m in sim_results if m[key] is not None]
        if len(values) > 0:
            ci_lo, ci_hi = bootstrap_ci(values)
            agg[key] = {
                'mean': float(np.mean(values)),
                'std': float(np.std(values)),
                'median': float(np.median(values)),
                'q5': float(np.percentile(values, 5)),
                'q95': float(np.percentile(values, 95)),
                'min': float(np.min(values)),
                'max': float(np.max(values)),
                'bootstrap_ci_95': [ci_lo, ci_hi],
                'n_valid': len(values),
            }
        else:
            agg[key] = None

    # Count NaN/clamp events
    total_nan = sum(m.get('n_nan_events', 0) for m in sim_results)
    total_clamp = sum(m.get('n_price_clamp', 0) for m in sim_results)
    agg['_diagnostics'] = {
        'total_nan_events': total_nan,
        'total_price_clamps': total_clamp,
        'n_simulations': len(sim_results),
    }

    return agg


# ============================================================
# Part 1: Main simulation (500 sims, baseline params)
# ============================================================

def run_part1():
    """Run 500 simulations at 7 crowding levels with baseline parameters."""
    print("=" * 72)
    print("PART 1: Extended Simulation (500 sims per level, baseline params)")
    print("=" * 72)

    all_results = {}

    for vt_frac in VT_FRACTIONS_MAIN:
        label = f"{int(vt_frac*100)}%"
        print(f"\n--- VT Fraction: {label} ({N_SIMS_MAIN} simulations) ---")

        # Prepare args for multiprocessing
        args_list = [
            (vt_frac, int(vt_frac * 100000) + sim_idx + 42, {})
            for sim_idx in range(N_SIMS_MAIN)
        ]

        t0 = time.time()
        with Pool(N_WORKERS) as pool:
            sim_results = pool.map(run_single_simulation, args_list)
        elapsed = time.time() - t0

        agg = aggregate_metrics(sim_results)
        all_results[label] = agg

        print(f"  Completed in {elapsed:.1f}s")
        print(f"  Market vol: {agg['ann_vol']['mean']:.4f} [{agg['ann_vol']['bootstrap_ci_95'][0]:.4f}, {agg['ann_vol']['bootstrap_ci_95'][1]:.4f}]")
        print(f"  Kurtosis: {agg['kurtosis']['mean']:.3f} [{agg['kurtosis']['bootstrap_ci_95'][0]:.3f}, {agg['kurtosis']['bootstrap_ci_95'][1]:.3f}]")
        print(f"  Max DD: {agg['max_dd']['mean']:.3f} [{agg['max_dd']['bootstrap_ci_95'][0]:.3f}, {agg['max_dd']['bootstrap_ci_95'][1]:.3f}]")
        if agg.get('vt_sharpe') is not None:
            print(f"  VT Sharpe: {agg['vt_sharpe']['mean']:.4f} [{agg['vt_sharpe']['bootstrap_ci_95'][0]:.4f}, {agg['vt_sharpe']['bootstrap_ci_95'][1]:.4f}]")
        diag = agg.get('_diagnostics', {})
        if diag.get('total_nan_events', 0) > 0 or diag.get('total_price_clamps', 0) > 0:
            print(f"  ⚠ NaN events: {diag['total_nan_events']}, Price clamps: {diag['total_price_clamps']}")

    return all_results


# ============================================================
# Part 2: Sensitivity Analysis
# ============================================================

def run_part2():
    """Run sensitivity analysis: 3 params × 3 values × 3 crowding levels × 200 sims."""
    print("\n" + "=" * 72)
    print("PART 2: Sensitivity Analysis (200 sims per combination)")
    print("=" * 72)

    sensitivity_results = {}

    for param_name, param_values in SENSITIVITY_GRID.items():
        sensitivity_results[param_name] = {}

        for param_val in param_values:
            is_baseline = (param_val == BASELINE_PARAMS[param_name])
            label_val = f"{param_val}"
            if is_baseline:
                label_val += " (baseline)"

            sensitivity_results[param_name][str(param_val)] = {}

            for vt_frac in VT_FRACTIONS_SENS:
                level_label = f"{int(vt_frac*100)}%"

                # Build param overrides
                overrides = dict(BASELINE_PARAMS)
                overrides[param_name] = param_val

                args_list = [
                    (vt_frac, int(param_val * 100000) + int(vt_frac * 10000) + sim_idx + 7777, overrides)
                    for sim_idx in range(N_SIMS_SENS)
                ]

                t0 = time.time()
                with Pool(N_WORKERS) as pool:
                    sim_results = pool.map(run_single_simulation, args_list)
                elapsed = time.time() - t0

                agg = aggregate_metrics(sim_results)
                sensitivity_results[param_name][str(param_val)][level_label] = agg

                sharpe_str = f"Sharpe={agg['vt_sharpe']['mean']:.4f}" if agg.get('vt_sharpe') else "N/A"
                print(f"  {param_name}={param_val}, VT={level_label}: "
                      f"vol={agg['ann_vol']['mean']:.4f}, kurt={agg['kurtosis']['mean']:.2f}, "
                      f"{sharpe_str} ({elapsed:.1f}s)")

    return sensitivity_results


# ============================================================
# Part 3: Analysis
# ============================================================

def analyze_results(part1_results, sensitivity_results):
    """Comprehensive analysis of results."""
    print("\n" + "=" * 72)
    print("PART 3: ANALYSIS")
    print("=" * 72)

    analysis = {}

    # --- 3a. Part 1 summary with bootstrap CI ---
    print("\n--- 3a. Strategy Degradation (Sharpe with 95% Bootstrap CI) ---")
    sharpe_trajectory = {}
    for frac in VT_FRACTIONS_MAIN:
        label = f"{int(frac*100)}%"
        s = part1_results[label].get('vt_sharpe')
        if s is not None:
            sharpe_trajectory[label] = {
                'mean': s['mean'],
                'ci_lo': s['bootstrap_ci_95'][0],
                'ci_hi': s['bootstrap_ci_95'][1],
                'std': s['std'],
            }
            print(f"  {label:>5s}: Sharpe = {s['mean']:.4f} [{s['bootstrap_ci_95'][0]:.4f}, {s['bootstrap_ci_95'][1]:.4f}]")
    analysis['sharpe_trajectory'] = sharpe_trajectory

    # --- 3b. Market stability ---
    print("\n--- 3b. Market Stability (Vol, Kurtosis, MDD with CI) ---")
    vol_baseline = part1_results['0%']['ann_vol']['mean']
    stability = {}
    for frac in VT_FRACTIONS_MAIN:
        label = f"{int(frac*100)}%"
        v = part1_results[label]['ann_vol']
        k = part1_results[label]['kurtosis']
        dd = part1_results[label]['max_dd']
        fc = part1_results[label]['flash_crash_freq']
        vol_change = (v['mean'] / vol_baseline - 1) * 100
        stability[label] = {
            'vol_mean': v['mean'], 'vol_ci': v['bootstrap_ci_95'], 'vol_change_pct': vol_change,
            'kurtosis_mean': k['mean'], 'kurtosis_ci': k['bootstrap_ci_95'],
            'mdd_mean': dd['mean'], 'mdd_ci': dd['bootstrap_ci_95'],
            'flash_freq': fc['mean'],
        }
        print(f"  {label:>5s}: Vol={v['mean']:.4f} ({vol_change:+.1f}%), "
              f"Kurt={k['mean']:.2f} [{k['bootstrap_ci_95'][0]:.2f}, {k['bootstrap_ci_95'][1]:.2f}], "
              f"MDD={dd['mean']:.3f}")
    analysis['stability'] = stability

    # --- 3c. Critical threshold detection ---
    print("\n--- 3c. Critical Threshold Detection ---")
    sharpe_10 = part1_results['10%']['vt_sharpe']['mean'] if part1_results['10%'].get('vt_sharpe') else None
    threshold_analysis = {}
    critical_threshold = None
    for frac in VT_FRACTIONS_MAIN[1:]:
        label = f"{int(frac*100)}%"
        if part1_results[label].get('vt_sharpe') is not None and sharpe_10 is not None:
            degradation = (1 - part1_results[label]['vt_sharpe']['mean'] / sharpe_10) * 100
            vol_increase = (part1_results[label]['ann_vol']['mean'] / vol_baseline - 1) * 100
            threshold_analysis[label] = {
                'sharpe_degradation_pct': degradation,
                'vol_increase_pct': vol_increase,
            }
            marker = ""
            if degradation > 30 and critical_threshold is None:
                critical_threshold = label
                marker = " *** CRITICAL ***"
            print(f"  {label:>5s}: Sharpe degradation={degradation:+.1f}%, "
                  f"Vol increase={vol_increase:+.1f}%{marker}")

    analysis['threshold'] = {
        'critical_level': critical_threshold,
        'degradation_by_level': threshold_analysis,
    }

    # --- 3d. Statistical significance (t-test: 10% vs each) ---
    print("\n--- 3d. Statistical Significance (Welch t-test, Harvey t>3.0) ---")
    if part1_results['10%'].get('vt_sharpe') is not None:
        base = part1_results['10%']['vt_sharpe']
        sig_tests = {}
        for frac in [0.20, 0.30, 0.50, 0.70, 1.00]:
            label = f"{int(frac*100)}%"
            if part1_results[label].get('vt_sharpe') is not None:
                other = part1_results[label]['vt_sharpe']
                n = N_SIMS_MAIN
                t_stat = (base['mean'] - other['mean']) / np.sqrt(
                    base['std']**2 / n + other['std']**2 / n
                )
                df_approx = 2 * n - 2
                p_value = 2 * (1 - sp_stats.t.cdf(abs(t_stat), df=df_approx))
                sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else ("*" if abs(t_stat) > 1.65 else "ns"))
                sig_tests[label] = {
                    't_stat': float(t_stat),
                    'p_value': float(p_value),
                    'significance': sig,
                }
                print(f"  10% vs {label:>5s}: t={t_stat:.2f}, p={p_value:.6f} [{sig}]")
        analysis['significance_tests'] = sig_tests

    # --- 3e. 100 vs 500 sim comparison (tail statistics) ---
    print("\n--- 3e. Simulation Count Impact (kurtosis stability) ---")
    # Compare kurtosis CI width at extreme crowding levels
    sim_comparison = {}
    for frac in VT_FRACTIONS_MAIN:
        label = f"{int(frac*100)}%"
        k = part1_results[label]['kurtosis']
        ci_width = k['bootstrap_ci_95'][1] - k['bootstrap_ci_95'][0]
        sim_comparison[label] = {
            'kurtosis_mean': k['mean'],
            'kurtosis_ci_width': ci_width,
            'kurtosis_std': k['std'],
        }
        print(f"  {label:>5s}: Kurt={k['mean']:.3f}, CI width={ci_width:.3f}, std={k['std']:.3f}")
    analysis['sim_count_comparison'] = sim_comparison

    # --- 3f. Sensitivity analysis ---
    print("\n--- 3f. Sensitivity Analysis Summary ---")
    sensitivity_summary = {}

    for param_name in SENSITIVITY_GRID:
        param_values = SENSITIVITY_GRID[param_name]
        sensitivity_summary[param_name] = {}
        print(f"\n  Parameter: {param_name}")

        # For each crowding level, compute how Sharpe changes across param values
        for vt_label in ['10%', '30%', '50%']:
            sharpes = []
            vols = []
            kurts = []
            for pv in param_values:
                r = sensitivity_results[param_name][str(pv)][vt_label]
                s = r.get('vt_sharpe')
                sharpes.append(s['mean'] if s else np.nan)
                vols.append(r['ann_vol']['mean'])
                kurts.append(r['kurtosis']['mean'])

            sharpe_range = max(sharpes) - min(sharpes) if all(np.isfinite(sharpes)) else np.nan
            vol_range = max(vols) - min(vols)
            kurt_range = max(kurts) - min(kurts)

            sensitivity_summary[param_name][vt_label] = {
                'sharpe_values': {str(pv): float(s) for pv, s in zip(param_values, sharpes)},
                'sharpe_range': float(sharpe_range) if np.isfinite(sharpe_range) else None,
                'vol_values': {str(pv): float(v) for pv, v in zip(param_values, vols)},
                'vol_range': float(vol_range),
                'kurt_values': {str(pv): float(k) for pv, k in zip(param_values, kurts)},
                'kurt_range': float(kurt_range),
            }

            print(f"    VT={vt_label}: Sharpe range={sharpe_range:.4f}, "
                  f"Vol range={vol_range:.4f}, Kurt range={kurt_range:.2f}")
            for pv, s, v, k in zip(param_values, sharpes, vols, kurts):
                baseline_marker = " *" if pv == BASELINE_PARAMS[param_name] else ""
                print(f"      {param_name}={pv}{baseline_marker}: Sharpe={s:.4f}, Vol={v:.4f}, Kurt={k:.2f}")

    analysis['sensitivity'] = sensitivity_summary

    # --- 3g. Which parameter is most influential? ---
    print("\n--- 3g. Parameter Influence Ranking ---")
    influence = {}
    for param_name in SENSITIVITY_GRID:
        # Average Sharpe range across crowding levels
        ranges = []
        for vt_label in ['10%', '30%', '50%']:
            sr = sensitivity_summary[param_name][vt_label].get('sharpe_range')
            if sr is not None:
                ranges.append(sr)
        avg_range = np.mean(ranges) if ranges else 0
        influence[param_name] = float(avg_range)

    # Sort by influence
    sorted_influence = sorted(influence.items(), key=lambda x: x[1], reverse=True)
    for rank, (param, inf) in enumerate(sorted_influence, 1):
        print(f"  #{rank} {param}: avg Sharpe range = {inf:.4f}")
    analysis['parameter_influence_ranking'] = {p: v for p, v in sorted_influence}

    # --- 3h. Is the critical threshold stable? ---
    print("\n--- 3h. Critical Threshold Stability ---")
    threshold_stability = {}
    for param_name in SENSITIVITY_GRID:
        param_values = SENSITIVITY_GRID[param_name]
        threshold_stability[param_name] = {}

        for pv in param_values:
            # Check Sharpe degradation from 10% to 50%
            s10 = sensitivity_results[param_name][str(pv)]['10%'].get('vt_sharpe')
            s30 = sensitivity_results[param_name][str(pv)]['30%'].get('vt_sharpe')
            s50 = sensitivity_results[param_name][str(pv)]['50%'].get('vt_sharpe')

            if s10 and s30 and s50:
                deg_30 = (1 - s30['mean'] / s10['mean']) * 100
                deg_50 = (1 - s50['mean'] / s10['mean']) * 100

                # Find threshold: first level with >30% degradation
                if deg_30 > 30:
                    thresh = "<=30%"
                elif deg_50 > 30:
                    thresh = "30-50%"
                else:
                    thresh = ">50%"

                threshold_stability[param_name][str(pv)] = {
                    'degradation_at_30pct': float(deg_30),
                    'degradation_at_50pct': float(deg_50),
                    'threshold_region': thresh,
                }
                baseline_marker = " *" if pv == BASELINE_PARAMS[param_name] else ""
                print(f"  {param_name}={pv}{baseline_marker}: "
                      f"deg@30%={deg_30:.1f}%, deg@50%={deg_50:.1f}% → threshold: {thresh}")

    analysis['threshold_stability'] = threshold_stability

    return analysis


# ============================================================
# Main
# ============================================================

if __name__ == '__main__':
    print("=" * 72)
    print("K827v2: ABM VT Crowding — Sensitivity Analysis + 500 Simulations")
    print("=" * 72)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Workers: {N_WORKERS} (cpu_count={cpu_count()})")
    print(f"Part 1: {N_SIMS_MAIN} sims × {len(VT_FRACTIONS_MAIN)} levels = {N_SIMS_MAIN * len(VT_FRACTIONS_MAIN)} sims")
    n_sens_total = len(SENSITIVITY_GRID) * 3 * len(VT_FRACTIONS_SENS) * N_SIMS_SENS
    print(f"Part 2: {n_sens_total} sims (3 params × 3 values × {len(VT_FRACTIONS_SENS)} levels × {N_SIMS_SENS} sims)")
    print()

    t_start = time.time()

    # Part 1
    part1_results = run_part1()
    t_part1 = time.time()
    print(f"\nPart 1 completed in {t_part1 - t_start:.1f}s")

    # Part 2
    sensitivity_results = run_part2()
    t_part2 = time.time()
    print(f"\nPart 2 completed in {t_part2 - t_part1:.1f}s")

    # Part 3: Analysis
    analysis = analyze_results(part1_results, sensitivity_results)

    # ============================================================
    # Final summary
    # ============================================================
    print("\n" + "=" * 72)
    print("FINAL CONCLUSIONS")
    print("=" * 72)

    # Determine if threshold is stable
    threshold_regions = set()
    for param_name in analysis.get('threshold_stability', {}):
        for pv, info in analysis['threshold_stability'][param_name].items():
            threshold_regions.add(info['threshold_region'])

    is_stable = len(threshold_regions) == 1
    print(f"\n1. Threshold stability: {'STABLE' if is_stable else 'VARIABLE'}")
    print(f"   Threshold regions across all param combos: {sorted(threshold_regions)}")

    # Most influential parameter
    if analysis.get('parameter_influence_ranking'):
        top_param = list(analysis['parameter_influence_ranking'].keys())[0]
        top_val = list(analysis['parameter_influence_ranking'].values())[0]
        print(f"\n2. Most influential parameter: {top_param} (avg Sharpe range = {top_val:.4f})")

    # K827 vs K827v2 comparison
    print(f"\n3. 500 sims vs 100 sims: See kurtosis CI widths above")
    print(f"   (Narrower CI = more precise tail estimates with 500 sims)")

    total_time = time.time() - t_start
    print(f"\nTotal runtime: {total_time:.1f}s ({total_time/60:.1f} min)")

    # ============================================================
    # Save results
    # ============================================================
    output = {
        'experiment_id': 'K827v2',
        'title': 'ABM VT Crowding — Sensitivity Analysis + 500 Simulations',
        'type': 'SIMULATION (not empirical)',
        'description': (
            'Enhanced K827 with (1) 500 sims for robust tail statistics, '
            '(2) sensitivity analysis of lambda/gamma/kappa ±50%, '
            '(3) bootstrap 95% CI. Tests if 30-50% crowding threshold is parameter-robust.'
        ),
        'timestamp': datetime.now().isoformat(),
        'runtime_seconds': total_time,
        'config': {
            'n_agents': N_AGENTS,
            'n_days': N_DAYS,
            'n_sims_main': N_SIMS_MAIN,
            'n_sims_sensitivity': N_SIMS_SENS,
            'n_bootstrap': N_BOOTSTRAP,
            'n_workers': N_WORKERS,
            'vt_fractions_main': VT_FRACTIONS_MAIN,
            'vt_fractions_sensitivity': VT_FRACTIONS_SENS,
            'baseline_params': BASELINE_PARAMS,
            'sensitivity_grid': {k: [float(v) for v in vals] for k, vals in SENSITIVITY_GRID.items()},
        },
        'part1_results': part1_results,
        'part2_sensitivity': sensitivity_results,
        'analysis': analysis,
        'conclusions': {
            'threshold_stable': is_stable,
            'threshold_regions': sorted(threshold_regions),
            'most_influential_param': top_param if analysis.get('parameter_influence_ranking') else None,
        },
        'references': [
            'K827: Original ABM VT crowding (100 sims, baseline params)',
            'Kyle (1985) Continuous Auctions and Insider Trading, Econometrica',
            'Farmer & Foley (2009) Agent-based modelling, Nature',
            'Bouchaud et al. (2018) Trades Quotes and Prices, Cambridge UP',
            'Brunnermeier & Pedersen (2009) Market Liquidity and Funding Liquidity, RFS',
        ],
        'limitations': [
            'Simplified Kyle market maker (no strategic traders)',
            'VIX dynamics endogenous but simplified',
            'No transaction costs',
            'Agents homogeneous within class',
            'No adaptive learning',
            'Results model-dependent, not directly applicable to real markets',
            'Sensitivity only tested ±50%; extreme values not explored',
            'Only 3 parameters tested; other params (VT_CAP, noise_std, VIX_MEAN) fixed',
        ],
    }

    results_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                'k827v2_abm_sensitivity_results.json')
    with open(results_path, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nResults saved to: {results_path}")
    print(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
