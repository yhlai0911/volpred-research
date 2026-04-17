"""
K864: Heterogeneous ABM — Does Strategy Diversity Reduce VT Crowding?
=====================================================================
[提出: Claude (K827v3 limitation #4 "Agents homogeneous within class"), 執行: Claude]
類型：模擬實驗（非實證數據）

EXTENDS K827v3 (Fixed Liquidity ABM):
  K827v3: All VT agents use SAME 12/VIX rule → homogeneous crowding
  K864: VT agents use DIVERSE strategies → heterogeneous crowding

  Key question: Does strategy heterogeneity shift or soften the tipping point?

Agent Types (heterogeneous VT):
  Type A: 12/VIX (standard, aggressive) — same as K827v3
  Type B: Floor(0.3)+Cap(0.9) 12/VIX (K859 robust, moderate)
  Type C: Risk Parity (equal risk contribution, conservative)
  Type D: EWMA(22) VT (smoothed, slow reactor)

Design:
  - N = 500 total agents
  - noise_traders = 200 (fixed, K827v3 correction)
  - VT agents = variable (50, 100, 150, 200, 250, 300)
  - VT adoption rates: 10%, 20%, 30%, 40%, 50%, 60%
  - 2 regimes: Homogeneous (all Type A) vs Heterogeneous (equal mix A/B/C/D)
  - 50 Monte Carlo runs per configuration = 12 configs × 50 = 600 sims
  - T = 1000 days per run

Hypotheses:
  H1: Heterogeneous VT delays the tipping point (diverse reactions = less coordinated selling)
  H2: Heterogeneous VT reduces crash severity (MDD, flash crashes)
  H3: Floor+Cap agents (Type B) provide stabilizing ballast (min 30% equity maintained)

References:
  - K827v3: ABM VT crowding — fixed liquidity (tipping at 50-70%)
  - K859: Robust VT — Floor/Cap + EWMA best combo
  - Kyle (1985) Continuous Auctions and Insider Trading, Econometrica
  - Farmer & Foley (2009) Agent-based modelling, Nature
  - LeBaron (2006) Agent-based Computational Finance, Handbook of Comp. Econ.
  - Hommes (2006) Heterogeneous Agent Models in Economics and Finance, Handbook of Comp. Econ.

Error Log rules:
  - SIMULATION experiment, clearly labelled (not empirical)
  - Sanity check: compute actual values, never hard-code
  - noise_traders = 200 (fixed, K827v3 correction)
  - multiprocessing for M1 Max
  - NaN/Inf checks on every return
"""

import sys
import os
import warnings
warnings.filterwarnings("ignore")

import numpy as np
from scipy import stats as sp_stats
import json
from datetime import datetime, timezone
from multiprocessing import Pool, cpu_count
import time

# ============================================================
# Configuration
# ============================================================
N_AGENTS = 1000
N_NOISE_FIXED = 200        # Fixed noise traders (K827v3 correction)
N_POOL = N_AGENTS - N_NOISE_FIXED  # = 800, split between BH and VT

N_DAYS = 2520              # 10 years (matches K827v3)
N_SIMS = 200               # Monte Carlo runs per config
N_BOOTSTRAP = 1000

# VT adoption rates (fraction of N_POOL that are VT agents)
# Matches K827v3 range for direct comparison
VT_FRACTIONS = [0.0, 0.10, 0.20, 0.30, 0.50, 0.70, 1.00]

# Market parameters (aligned with K827v3 baseline)
KYLE_LAMBDA = 0.005
VIX_VOL_SENSITIVITY = 200.0  # gamma: how much realized vol moves VIX
VIX_MR_SPEED = 0.03          # kappa: VIX mean-reversion speed

INITIAL_PRICE = 100.0
INITIAL_VIX = 15.0
ANNUAL_DRIFT = 0.08
DAILY_DRIFT = ANNUAL_DRIFT / 252
FUNDAMENTAL_VOL = 0.16 / np.sqrt(252)
VIX_MEAN = 18.0
VIX_NOISE_STD = 0.3
VT_CAP = 1.5
NOISE_TRADER_STD = 0.02

# EWMA lookback for Type D agents
EWMA_LOOKBACK = 22
EWMA_LAMBDA = 2.0 / (EWMA_LOOKBACK + 1)  # ~0.087

N_WORKERS = min(cpu_count(), 8)


# ============================================================
# Strategy weight functions
# ============================================================

def weight_type_a(vix_prev):
    """Type A: 12/VIX (standard aggressive). Same as K827v3."""
    return min(12.0 / max(vix_prev, 9.0), VT_CAP)


def weight_type_b(vix_prev):
    """Type B: Floor(0.3)+Cap(0.9) on 12/VIX (K859 robust)."""
    raw = 12.0 / max(vix_prev, 9.0)
    return max(0.3, min(0.9, raw))


def weight_type_c(realized_vol_ann):
    """Type C: Risk Parity — target 10% portfolio vol.
    w = target_vol / realized_vol, capped at 1.5.
    If realized_vol is near zero, default to 0.6.
    """
    target_vol = 0.10
    if realized_vol_ann < 0.02:
        return 0.6  # default when vol estimate unreliable
    return min(target_vol / realized_vol_ann, VT_CAP)


def weight_type_d(ewma_vol_ann, vix_prev):
    """Type D: EWMA(22) VT — use EWMA vol instead of VIX.
    w = 12 / (ewma_vol_ann * 100), analogous to 12/VIX but smoothed.
    The *100 converts from decimal to VIX-like scale.
    """
    ewma_vix_equiv = ewma_vol_ann * 100  # e.g., 0.16 → 16
    ewma_vix_equiv = max(ewma_vix_equiv, 9.0)
    return min(12.0 / ewma_vix_equiv, VT_CAP)


# ============================================================
# Core simulation (single run)
# ============================================================

def run_single_simulation(args):
    """Run one simulation with optional heterogeneous VT agents.

    Args:
        args: (vt_fraction, seed, heterogeneous: bool)

    Returns: dict of metrics
    """
    vt_fraction, seed, heterogeneous = args
    rng = np.random.RandomState(seed)

    # Agent allocation
    n_noise = N_NOISE_FIXED  # Always 200
    n_vt = int(N_POOL * vt_fraction)
    n_bh = N_POOL - n_vt
    # Total = n_noise + n_vt + n_bh = 200 + 300 = 500

    # Assign VT agent types
    if n_vt > 0 and heterogeneous:
        # Equal split among 4 types (remainder goes to Type A)
        n_per_type = n_vt // 4
        n_type_a = n_vt - 3 * n_per_type  # gets remainder
        n_type_b = n_per_type
        n_type_c = n_per_type
        n_type_d = n_per_type
        agent_types = (['A'] * n_type_a + ['B'] * n_type_b +
                       ['C'] * n_type_c + ['D'] * n_type_d)
    elif n_vt > 0:
        # Homogeneous: all Type A
        n_type_a = n_vt
        n_type_b = n_type_c = n_type_d = 0
        agent_types = ['A'] * n_vt
    else:
        n_type_a = n_type_b = n_type_c = n_type_d = 0
        agent_types = []

    # State arrays
    prices = np.zeros(N_DAYS)
    returns = np.zeros(N_DAYS)
    vix_series = np.zeros(N_DAYS)

    prices[0] = INITIAL_PRICE
    vix_series[0] = INITIAL_VIX

    # Per-agent VT weights (track individually for heterogeneous)
    vt_weights = np.zeros(n_vt) if n_vt > 0 else np.array([])
    if n_vt > 0:
        # Initialize weights based on type
        for i, atype in enumerate(agent_types):
            if atype == 'A':
                vt_weights[i] = weight_type_a(INITIAL_VIX)
            elif atype == 'B':
                vt_weights[i] = weight_type_b(INITIAL_VIX)
            elif atype == 'C':
                vt_weights[i] = weight_type_c(0.16)  # initial guess
            elif atype == 'D':
                vt_weights[i] = weight_type_d(0.16, INITIAL_VIX)

    noise_weights = np.ones(n_noise) * 0.5

    # Rolling buffers for realized vol
    ret_buffer = np.zeros(22)
    buffer_idx = 0
    ewma_var = (FUNDAMENTAL_VOL) ** 2  # EWMA variance estimate

    n_nan_events = 0
    n_price_clamp = 0

    # Track weight dispersion for analysis
    weight_dispersion_sum = 0.0
    weight_dispersion_count = 0

    for t in range(1, N_DAYS):
        # Realized vol (rolling 22-day)
        if t > 1:
            n_filled = min(buffer_idx, 22)
            if n_filled > 1:
                realized_vol_daily = np.std(ret_buffer[:n_filled])
                realized_vol_ann = realized_vol_daily * np.sqrt(252)
            else:
                realized_vol_ann = FUNDAMENTAL_VOL * np.sqrt(252)
        else:
            realized_vol_ann = FUNDAMENTAL_VOL * np.sqrt(252)

        # Update EWMA variance
        if t > 1:
            ewma_var = EWMA_LAMBDA * returns[t-1]**2 + (1 - EWMA_LAMBDA) * ewma_var
        ewma_vol_ann = np.sqrt(ewma_var * 252)

        # VIX update (endogenous — same as K827v3)
        vix_target = VIX_MEAN + VIX_VOL_SENSITIVITY * max(0, realized_vol_ann - 0.16)
        vix_series[t] = (vix_series[t-1] +
                         VIX_MR_SPEED * (vix_target - vix_series[t-1]) +
                         rng.normal(0, VIX_NOISE_STD))
        vix_series[t] = max(9.0, min(80.0, vix_series[t]))

        # Agent demand computation
        net_demand = 0.0

        # VT agents: rebalance based on their strategy type
        # Signal from t-1 (no lookahead)
        if n_vt > 0:
            new_weights = np.zeros(n_vt)
            for i, atype in enumerate(agent_types):
                if atype == 'A':
                    new_weights[i] = weight_type_a(vix_series[t-1])
                elif atype == 'B':
                    new_weights[i] = weight_type_b(vix_series[t-1])
                elif atype == 'C':
                    new_weights[i] = weight_type_c(realized_vol_ann)
                elif atype == 'D':
                    new_weights[i] = weight_type_d(ewma_vol_ann, vix_series[t-1])

            # Track weight dispersion (std of target weights across agents)
            if n_vt > 1 and heterogeneous:
                weight_dispersion_sum += np.std(new_weights)
                weight_dispersion_count += 1

            # K827v3 demand model: each agent's impact scales by n_vt
            # (herding amplification — more VT agents → each has MORE impact)
            # K827v3: demand_change = (target - weights) * n_vt → sum over n_vt agents
            # This creates quadratic scaling: total_demand ~ n_vt^2 * delta_weight
            # We replicate this: each agent's demand_change * n_vt
            demand_change = (new_weights - vt_weights) * n_vt
            net_demand += np.sum(demand_change)
            vt_weights[:] = new_weights

        # BH agents: no demand (buy and hold = 0 net flow)

        # Noise traders: random demand (FIXED count = 200)
        noise_changes = rng.normal(0, NOISE_TRADER_STD, size=n_noise)
        noise_weights = np.clip(noise_weights + noise_changes, 0.0, 1.5)
        net_demand += np.sum(noise_changes)

        # Price formation (Kyle model)
        fundamental_shock = rng.normal(DAILY_DRIFT, FUNDAMENTAL_VOL)
        price_impact = KYLE_LAMBDA * net_demand / N_AGENTS
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

        ret_buffer[buffer_idx % 22] = daily_return
        buffer_idx += 1

    # ============================================================
    # Compute metrics
    # ============================================================
    valid_returns = returns[1:]
    ann_vol = float(np.std(valid_returns) * np.sqrt(252))
    ann_return = float(np.mean(valid_returns) * 252)

    cum_returns = np.cumprod(1 + valid_returns)
    running_max = np.maximum.accumulate(cum_returns)
    drawdowns = cum_returns / running_max - 1
    max_dd = float(np.min(drawdowns))

    sigma_daily = np.std(valid_returns)
    flash_crashes = int(np.sum(valid_returns < -3 * sigma_daily)) if sigma_daily > 0 else 0
    flash_crash_freq = float(flash_crashes / len(valid_returns) * 252)

    kurtosis = float(sp_stats.kurtosis(valid_returns, fisher=True))
    skewness = float(sp_stats.skew(valid_returns))

    vix_mean_val = float(np.mean(vix_series[1:]))
    vix_std_val = float(np.std(vix_series[1:]))
    vix_spikes = float(np.sum(vix_series[1:] > 30) / len(vix_series[1:]))

    # VT strategy performance (aggregate across all VT agents)
    vt_sharpe = None
    vt_return_val = None
    vt_vol_val = None
    vt_mdd_val = None
    if n_vt > 0:
        # Average weight across all VT agents at each time step
        # Re-compute weights for performance measurement
        avg_weights = np.zeros(N_DAYS - 1)
        for t_idx in range(N_DAYS - 1):
            # Weight at time t applies to return t+1
            # For simplicity, use the aggregate strategy
            t = t_idx + 1
            if t < N_DAYS:
                # Reconstruct weights at each step
                pass

        # Simpler: use the tracked vt_weights trajectory isn't stored,
        # so we use the VIX series to reconstruct average VT portfolio
        # This is exact for homogeneous, approximate for heterogeneous
        vt_port_returns = np.zeros(N_DAYS - 1)
        _ewma_var = FUNDAMENTAL_VOL ** 2
        _ret_buf = np.zeros(22)
        _buf_idx = 0

        for t in range(1, N_DAYS):
            # Reconstruct each agent's weight at t-1
            if t > 1:
                _n_filled = min(_buf_idx, 22)
                if _n_filled > 1:
                    _rv_ann = np.std(_ret_buf[:_n_filled]) * np.sqrt(252)
                else:
                    _rv_ann = FUNDAMENTAL_VOL * np.sqrt(252)
            else:
                _rv_ann = FUNDAMENTAL_VOL * np.sqrt(252)

            if t > 1:
                _ewma_var = EWMA_LAMBDA * returns[t-1]**2 + (1 - EWMA_LAMBDA) * _ewma_var
            _ewma_vol_ann = np.sqrt(_ewma_var * 252)

            w_sum = 0.0
            for atype in agent_types:
                if atype == 'A':
                    w_sum += weight_type_a(vix_series[t-1])
                elif atype == 'B':
                    w_sum += weight_type_b(vix_series[t-1])
                elif atype == 'C':
                    w_sum += weight_type_c(_rv_ann)
                elif atype == 'D':
                    w_sum += weight_type_d(_ewma_vol_ann, vix_series[t-1])

            avg_w = w_sum / n_vt
            vt_port_returns[t-1] = avg_w * valid_returns[t-1]

            _ret_buf[_buf_idx % 22] = returns[t]
            _buf_idx += 1

        vt_return_val = float(np.mean(vt_port_returns) * 252)
        vt_vol_calc = float(np.std(vt_port_returns) * np.sqrt(252))
        vt_sharpe = float(vt_return_val / vt_vol_calc) if vt_vol_calc > 0 else 0.0
        vt_vol_val = vt_vol_calc

        # VT MDD
        vt_cum = np.cumprod(1 + vt_port_returns)
        vt_running_max = np.maximum.accumulate(vt_cum)
        vt_dd = vt_cum / vt_running_max - 1
        vt_mdd_val = float(np.min(vt_dd))

    # Weight dispersion (heterogeneous only)
    avg_weight_dispersion = (float(weight_dispersion_sum / weight_dispersion_count)
                             if weight_dispersion_count > 0 else None)

    return {
        'ann_return': ann_return,
        'ann_vol': ann_vol,
        'max_dd': max_dd,
        'flash_crash_freq': flash_crash_freq,
        'kurtosis': kurtosis,
        'skewness': skewness,
        'vix_mean': vix_mean_val,
        'vix_std': vix_std_val,
        'vix_spike_pct': float(vix_spikes * 100),
        'vt_sharpe': vt_sharpe,
        'vt_return': vt_return_val,
        'vt_vol': vt_vol_val,
        'vt_mdd': vt_mdd_val,
        'weight_dispersion': avg_weight_dispersion,
        'final_price': float(prices[-1]),
        'n_nan_events': n_nan_events,
        'n_price_clamp': n_price_clamp,
        'n_vt': n_vt,
        'n_bh': n_bh,
        'n_noise': n_noise,
        'heterogeneous': heterogeneous,
        'n_type_a': n_type_a if n_vt > 0 else 0,
        'n_type_b': n_type_b if n_vt > 0 else 0,
        'n_type_c': n_type_c if n_vt > 0 else 0,
        'n_type_d': n_type_d if n_vt > 0 else 0,
    }


# ============================================================
# Aggregation with bootstrap CI
# ============================================================

def bootstrap_ci(values, n_boot=N_BOOTSTRAP, ci=0.95):
    """Bootstrap confidence interval for the mean."""
    values = np.array(values)
    n = len(values)
    rng = np.random.RandomState(12345)
    boot_means = np.array([np.mean(values[rng.randint(0, n, size=n)]) for _ in range(n_boot)])
    alpha = (1 - ci) / 2
    return float(np.percentile(boot_means, alpha * 100)), float(np.percentile(boot_means, (1 - alpha) * 100))


def aggregate_metrics(sim_results):
    """Aggregate simulation results with bootstrap CI."""
    if not sim_results:
        return {}

    metric_keys = ['ann_return', 'ann_vol', 'max_dd', 'flash_crash_freq',
                   'kurtosis', 'skewness', 'vix_mean', 'vix_std', 'vix_spike_pct',
                   'vt_sharpe', 'vt_return', 'vt_vol', 'vt_mdd', 'weight_dispersion']

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
                'bootstrap_ci_95': [ci_lo, ci_hi],
                'n_valid': len(values),
            }
        else:
            agg[key] = None

    # Diagnostics
    total_nan = sum(m.get('n_nan_events', 0) for m in sim_results)
    total_clamp = sum(m.get('n_price_clamp', 0) for m in sim_results)
    agg['_diagnostics'] = {
        'total_nan_events': total_nan,
        'total_price_clamps': total_clamp,
        'n_simulations': len(sim_results),
    }

    # Agent composition
    compositions = set()
    for m in sim_results:
        compositions.add((m.get('n_vt', -1), m.get('n_bh', -1), m.get('n_noise', -1),
                          m.get('n_type_a', 0), m.get('n_type_b', 0),
                          m.get('n_type_c', 0), m.get('n_type_d', 0)))
    agg['_agent_composition'] = [list(c) for c in compositions]

    return agg


# ============================================================
# Statistical tests: Homogeneous vs Heterogeneous
# ============================================================

def welch_t_test(values_homo, values_hetero, metric_name):
    """Welch's t-test for difference in means."""
    v1 = np.array(values_homo)
    v2 = np.array(values_hetero)
    if len(v1) < 2 or len(v2) < 2:
        return None
    t_stat, p_val = sp_stats.ttest_ind(v1, v2, equal_var=False)
    diff = np.mean(v2) - np.mean(v1)
    return {
        'metric': metric_name,
        'homo_mean': float(np.mean(v1)),
        'hetero_mean': float(np.mean(v2)),
        'difference': float(diff),
        'pct_change': float(diff / abs(np.mean(v1)) * 100) if abs(np.mean(v1)) > 1e-10 else None,
        't_stat': float(t_stat),
        'p_value': float(p_val),
        'significant_5pct': bool(p_val < 0.05),
        'significant_1pct': bool(p_val < 0.01),
        'n_homo': len(v1),
        'n_hetero': len(v2),
    }


# ============================================================
# Main experiment
# ============================================================

def run_experiment():
    """Run the full K864 heterogeneous ABM experiment."""
    print("=" * 72)
    print("K864: Heterogeneous ABM — Does Strategy Diversity Reduce VT Crowding?")
    print("=" * 72)
    print(f"  N_AGENTS = {N_AGENTS} (Noise={N_NOISE_FIXED}, Pool={N_POOL})")
    print(f"  N_DAYS = {N_DAYS}, N_SIMS = {N_SIMS}")
    print(f"  VT fractions: {VT_FRACTIONS}")
    print(f"  Workers: {N_WORKERS}")
    print()

    # Agent allocation table
    print("Agent Allocation Table:")
    print(f"  {'VT%':>5} {'n_VT':>6} {'n_BH':>6} {'Noise':>6} {'Total':>6} | "
          f"{'TypeA':>6} {'TypeB':>6} {'TypeC':>6} {'TypeD':>6} (hetero)")
    print(f"  {'----':>5} {'----':>6} {'----':>6} {'-----':>6} {'-----':>6} | "
          f"{'-----':>6} {'-----':>6} {'-----':>6} {'-----':>6}")
    for vf in VT_FRACTIONS:
        n_vt = int(N_POOL * vf)
        n_bh = N_POOL - n_vt
        n_per = n_vt // 4
        n_a = n_vt - 3 * n_per
        total = n_vt + n_bh + N_NOISE_FIXED
        print(f"  {int(vf*100):>4}% {n_vt:>6} {n_bh:>6} {N_NOISE_FIXED:>6} {total:>6} | "
              f"{n_a:>6} {n_per:>6} {n_per:>6} {n_per:>6}")
    print()

    # Strategy descriptions
    print("VT Strategy Types:")
    print("  A: 12/VIX (standard, aggressive) — same as K827v3")
    print("  B: Floor(0.3)+Cap(0.9) on 12/VIX (K859 robust)")
    print("  C: Risk Parity (target 10% vol, conservative)")
    print("  D: EWMA(22) VT (smoothed, slow reactor)")
    print()

    t_start = time.time()

    # ====================================
    # Run all configs
    # ====================================
    homo_results = {}  # vt_fraction -> [sim_results]
    hetero_results = {}

    all_args = []
    all_labels = []

    for vf in VT_FRACTIONS:
        base_seed = int(vf * 100000) + 42
        # Homogeneous
        for sim_idx in range(N_SIMS):
            all_args.append((vf, base_seed + sim_idx, False))
            all_labels.append(('homo', vf))
        # Heterogeneous (skip 0% — identical to homo)
        if vf > 0:
            for sim_idx in range(N_SIMS):
                all_args.append((vf, base_seed + 10000 + sim_idx, True))
                all_labels.append(('hetero', vf))

    print(f"Total simulations: {len(all_args)}")
    print(f"Running with {N_WORKERS} workers...")

    t0 = time.time()
    with Pool(N_WORKERS) as pool:
        all_sim_results = pool.map(run_single_simulation, all_args)
    elapsed = time.time() - t0
    print(f"All simulations completed in {elapsed:.1f}s")
    print()

    # Organize results
    for label, result in zip(all_labels, all_sim_results):
        regime, vf = label
        key = f"{int(vf*100)}%"
        if regime == 'homo':
            homo_results.setdefault(key, []).append(result)
        else:
            hetero_results.setdefault(key, []).append(result)

    # ====================================
    # Aggregate and compare
    # ====================================
    print("=" * 72)
    print("RESULTS")
    print("=" * 72)

    homo_agg = {}
    hetero_agg = {}

    for vf in VT_FRACTIONS:
        key = f"{int(vf*100)}%"
        homo_agg[key] = aggregate_metrics(homo_results.get(key, []))
        if key in hetero_results:
            hetero_agg[key] = aggregate_metrics(hetero_results[key])

    # Print comparison table
    print("\n--- Market Volatility (annualized) ---")
    print(f"  {'VT%':>5} {'Homo':>10} {'Hetero':>10} {'Diff':>10} {'Change%':>10}")
    for vf in VT_FRACTIONS:
        key = f"{int(vf*100)}%"
        h_vol = homo_agg[key]['ann_vol']['mean'] if homo_agg[key].get('ann_vol') else None
        e_vol = hetero_agg.get(key, {}).get('ann_vol', {})
        e_vol_mean = e_vol.get('mean') if isinstance(e_vol, dict) else None
        if h_vol and e_vol_mean:
            diff = e_vol_mean - h_vol
            pct = diff / h_vol * 100
            print(f"  {key:>5} {h_vol:>10.4f} {e_vol_mean:>10.4f} {diff:>+10.4f} {pct:>+9.1f}%")
        elif h_vol:
            print(f"  {key:>5} {h_vol:>10.4f} {'N/A':>10} {'':>10} {'':>10}")

    print("\n--- Max Drawdown ---")
    print(f"  {'VT%':>5} {'Homo':>10} {'Hetero':>10} {'Diff':>10} {'Better?':>10}")
    for vf in VT_FRACTIONS:
        key = f"{int(vf*100)}%"
        h_mdd = homo_agg[key]['max_dd']['mean'] if homo_agg[key].get('max_dd') else None
        e_mdd = hetero_agg.get(key, {}).get('max_dd', {})
        e_mdd_mean = e_mdd.get('mean') if isinstance(e_mdd, dict) else None
        if h_mdd and e_mdd_mean:
            diff = e_mdd_mean - h_mdd
            better = "YES" if e_mdd_mean > h_mdd else "no"  # less negative = better
            print(f"  {key:>5} {h_mdd:>10.4f} {e_mdd_mean:>10.4f} {diff:>+10.4f} {better:>10}")
        elif h_mdd:
            print(f"  {key:>5} {h_mdd:>10.4f} {'N/A':>10} {'':>10} {'':>10}")

    print("\n--- VT Strategy Sharpe Ratio ---")
    print(f"  {'VT%':>5} {'Homo':>10} {'Hetero':>10} {'Diff':>10} {'Change%':>10}")
    for vf in VT_FRACTIONS:
        key = f"{int(vf*100)}%"
        h_sr = homo_agg[key].get('vt_sharpe')
        e_sr = hetero_agg.get(key, {}).get('vt_sharpe')
        h_mean = h_sr['mean'] if isinstance(h_sr, dict) else None
        e_mean = e_sr['mean'] if isinstance(e_sr, dict) else None
        if h_mean is not None and e_mean is not None:
            diff = e_mean - h_mean
            pct = diff / abs(h_mean) * 100 if abs(h_mean) > 0.001 else 0
            print(f"  {key:>5} {h_mean:>10.3f} {e_mean:>10.3f} {diff:>+10.3f} {pct:>+9.1f}%")
        elif h_mean is not None:
            print(f"  {key:>5} {h_mean:>10.3f} {'N/A':>10} {'':>10} {'':>10}")

    print("\n--- Flash Crash Frequency (per year) ---")
    print(f"  {'VT%':>5} {'Homo':>10} {'Hetero':>10} {'Diff':>10} {'Reduced?':>10}")
    for vf in VT_FRACTIONS:
        key = f"{int(vf*100)}%"
        h_fc = homo_agg[key].get('flash_crash_freq')
        e_fc = hetero_agg.get(key, {}).get('flash_crash_freq')
        h_mean = h_fc['mean'] if isinstance(h_fc, dict) else None
        e_mean = e_fc['mean'] if isinstance(e_fc, dict) else None
        if h_mean is not None and e_mean is not None:
            diff = e_mean - h_mean
            reduced = "YES" if e_mean < h_mean else "no"
            print(f"  {key:>5} {h_mean:>10.3f} {e_mean:>10.3f} {diff:>+10.3f} {reduced:>10}")
        elif h_mean is not None:
            print(f"  {key:>5} {h_mean:>10.3f} {'N/A':>10} {'':>10} {'':>10}")

    print("\n--- Weight Dispersion (Heterogeneous only) ---")
    print(f"  {'VT%':>5} {'Dispersion':>12} (std of target weights across agent types)")
    for vf in VT_FRACTIONS:
        key = f"{int(vf*100)}%"
        wd = hetero_agg.get(key, {}).get('weight_dispersion')
        if isinstance(wd, dict) and wd.get('mean') is not None:
            print(f"  {key:>5} {wd['mean']:>12.4f}")

    # ====================================
    # Statistical tests
    # ====================================
    print("\n" + "=" * 72)
    print("STATISTICAL TESTS: Homogeneous vs Heterogeneous")
    print("=" * 72)

    test_metrics = ['ann_vol', 'max_dd', 'flash_crash_freq', 'kurtosis',
                    'vt_sharpe', 'vt_mdd']

    all_tests = {}
    for vf in VT_FRACTIONS:
        if vf == 0:
            continue
        key = f"{int(vf*100)}%"
        tests_for_level = {}

        homo_sims = homo_results.get(key, [])
        hetero_sims = hetero_results.get(key, [])

        print(f"\n--- VT = {key} ---")
        for metric in test_metrics:
            h_vals = [m[metric] for m in homo_sims if m[metric] is not None]
            e_vals = [m[metric] for m in hetero_sims if m[metric] is not None]

            test = welch_t_test(h_vals, e_vals, metric)
            if test:
                tests_for_level[metric] = test
                sig = "***" if test['significant_1pct'] else ("*" if test['significant_5pct'] else "")
                pct_str = f"{test['pct_change']:+.1f}%" if test['pct_change'] is not None else "N/A"
                print(f"  {metric:>20}: homo={test['homo_mean']:.4f}, hetero={test['hetero_mean']:.4f}, "
                      f"diff={test['difference']:+.4f} ({pct_str}), t={test['t_stat']:.2f}, "
                      f"p={test['p_value']:.4f} {sig}")

        all_tests[key] = tests_for_level

    # ====================================
    # Tipping point analysis
    # ====================================
    print("\n" + "=" * 72)
    print("TIPPING POINT ANALYSIS")
    print("=" * 72)

    # Define tipping point: VT Sharpe drops below baseline (0% VT) market Sharpe
    # Or more practically: when VT Sharpe starts declining meaningfully

    baseline_vol = homo_agg['0%']['ann_vol']['mean']
    baseline_ret = homo_agg['0%']['ann_return']['mean']
    baseline_mkt_sharpe = baseline_ret / baseline_vol if baseline_vol > 0 else 0

    print(f"\nBaseline (0% VT): vol={baseline_vol:.4f}, ret={baseline_ret:.4f}, "
          f"mkt_sharpe={baseline_mkt_sharpe:.3f}")

    print(f"\n{'VT%':>5} | {'--- Homogeneous ---':^30} | {'--- Heterogeneous ---':^30}")
    print(f"{'':>5} | {'VT_Sharpe':>10} {'MktVol':>10} {'MDD':>10} | "
          f"{'VT_Sharpe':>10} {'MktVol':>10} {'MDD':>10}")

    for vf in VT_FRACTIONS:
        key = f"{int(vf*100)}%"
        h_sr = homo_agg[key].get('vt_sharpe', {})
        h_vol = homo_agg[key].get('ann_vol', {})
        h_mdd = homo_agg[key].get('max_dd', {})

        h_sr_m = h_sr.get('mean', 0) if isinstance(h_sr, dict) else 0
        h_vol_m = h_vol.get('mean', 0) if isinstance(h_vol, dict) else 0
        h_mdd_m = h_mdd.get('mean', 0) if isinstance(h_mdd, dict) else 0

        e_sr = hetero_agg.get(key, {}).get('vt_sharpe', {})
        e_vol = hetero_agg.get(key, {}).get('ann_vol', {})
        e_mdd = hetero_agg.get(key, {}).get('max_dd', {})

        e_sr_m = e_sr.get('mean') if isinstance(e_sr, dict) else None
        e_vol_m = e_vol.get('mean') if isinstance(e_vol, dict) else None
        e_mdd_m = e_mdd.get('mean') if isinstance(e_mdd, dict) else None

        homo_str = f"{h_sr_m:>10.3f} {h_vol_m:>10.4f} {h_mdd_m:>10.4f}"
        if e_sr_m is not None:
            hetero_str = f"{e_sr_m:>10.3f} {e_vol_m:>10.4f} {e_mdd_m:>10.4f}"
        else:
            hetero_str = f"{'N/A':>10} {'N/A':>10} {'N/A':>10}"

        print(f"  {key:>4} | {homo_str} | {hetero_str}")

    # Identify tipping points
    homo_sharpes = {}
    hetero_sharpes = {}
    for vf in VT_FRACTIONS:
        key = f"{int(vf*100)}%"
        h_sr = homo_agg[key].get('vt_sharpe', {})
        if isinstance(h_sr, dict) and h_sr.get('mean') is not None:
            homo_sharpes[vf] = h_sr['mean']
        e_sr = hetero_agg.get(key, {}).get('vt_sharpe', {})
        if isinstance(e_sr, dict) and e_sr.get('mean') is not None:
            hetero_sharpes[vf] = e_sr['mean']

    # Find peak and where decline starts (>10% drop from peak)
    def find_tipping(sharpes_dict):
        if not sharpes_dict:
            return None, None
        fracs = sorted(sharpes_dict.keys())
        vals = [sharpes_dict[f] for f in fracs]
        if not vals:
            return None, None
        peak_idx = np.argmax(vals)
        peak_frac = fracs[peak_idx]
        peak_val = vals[peak_idx]

        tipping = None
        for i in range(peak_idx + 1, len(vals)):
            if vals[i] < peak_val * 0.9:  # 10% decline from peak
                tipping = fracs[i]
                break
        return peak_frac, tipping

    homo_peak, homo_tip = find_tipping(homo_sharpes)
    hetero_peak, hetero_tip = find_tipping(hetero_sharpes)

    print(f"\nTipping Point Detection (>10% Sharpe decline from peak):")
    print(f"  Homogeneous:   peak at {int(homo_peak*100) if homo_peak else '?'}%, "
          f"tipping at {int(homo_tip*100) if homo_tip else 'NOT REACHED'}%")
    print(f"  Heterogeneous: peak at {int(hetero_peak*100) if hetero_peak else '?'}%, "
          f"tipping at {int(hetero_tip*100) if hetero_tip else 'NOT REACHED'}%")

    if homo_tip and hetero_tip:
        shift = int((hetero_tip - homo_tip) * 100)
        print(f"  Tipping point shift: {shift:+d} percentage points")
    elif homo_tip and not hetero_tip:
        print(f"  Heterogeneity ELIMINATED tipping point within tested range!")

    # ====================================
    # Compile results
    # ====================================
    total_elapsed = time.time() - t_start

    # Key conclusions
    conclusions = {
        'homo_tipping_peak': f"{int(homo_peak*100)}%" if homo_peak else None,
        'homo_tipping_point': f"{int(homo_tip*100)}%" if homo_tip else "not_reached",
        'hetero_tipping_peak': f"{int(hetero_peak*100)}%" if hetero_peak else None,
        'hetero_tipping_point': f"{int(hetero_tip*100)}%" if hetero_tip else "not_reached",
    }

    # Check if heterogeneity helps at each level
    hetero_advantage = {}
    for vf in VT_FRACTIONS:
        if vf == 0:
            continue
        key = f"{int(vf*100)}%"
        tests = all_tests.get(key, {})
        advantages = {}

        # Lower vol = better for market stability
        vol_test = tests.get('ann_vol')
        if vol_test:
            advantages['vol_reduced'] = vol_test['difference'] < 0
            advantages['vol_pct_change'] = vol_test.get('pct_change')
            advantages['vol_significant'] = vol_test['significant_5pct']

        # Less negative MDD = better
        mdd_test = tests.get('max_dd')
        if mdd_test:
            advantages['mdd_improved'] = mdd_test['difference'] > 0  # less negative
            advantages['mdd_pct_change'] = mdd_test.get('pct_change')
            advantages['mdd_significant'] = mdd_test['significant_5pct']

        # Higher VT Sharpe = better
        sr_test = tests.get('vt_sharpe')
        if sr_test:
            advantages['sharpe_improved'] = sr_test['difference'] > 0
            advantages['sharpe_pct_change'] = sr_test.get('pct_change')
            advantages['sharpe_significant'] = sr_test['significant_5pct']

        # Fewer flash crashes = better
        fc_test = tests.get('flash_crash_freq')
        if fc_test:
            advantages['crashes_reduced'] = fc_test['difference'] < 0
            advantages['crashes_pct_change'] = fc_test.get('pct_change')
            advantages['crashes_significant'] = fc_test['significant_5pct']

        hetero_advantage[key] = advantages

    print("\n" + "=" * 72)
    print("HETEROGENEITY ADVANTAGE SUMMARY")
    print("=" * 72)
    print(f"  {'VT%':>5} {'VolReduced':>12} {'MDDImproved':>12} {'SharpeUp':>12} {'CrashDown':>12}")
    for vf in VT_FRACTIONS:
        if vf == 0:
            continue
        key = f"{int(vf*100)}%"
        adv = hetero_advantage.get(key, {})
        def fmt(improved, significant):
            if improved is None:
                return "N/A"
            sig = "*" if significant else ""
            return ("YES" if improved else "no") + sig

        vol_s = fmt(adv.get('vol_reduced'), adv.get('vol_significant'))
        mdd_s = fmt(adv.get('mdd_improved'), adv.get('mdd_significant'))
        sr_s = fmt(adv.get('sharpe_improved'), adv.get('sharpe_significant'))
        fc_s = fmt(adv.get('crashes_reduced'), adv.get('crashes_significant'))
        print(f"  {key:>5} {vol_s:>12} {mdd_s:>12} {sr_s:>12} {fc_s:>12}")

    print(f"\n  (* = statistically significant at 5%)")

    # Final summary
    n_levels = len([vf for vf in VT_FRACTIONS if vf > 0])
    vol_wins = sum(1 for k, v in hetero_advantage.items() if v.get('vol_reduced'))
    mdd_wins = sum(1 for k, v in hetero_advantage.items() if v.get('mdd_improved'))
    sr_wins = sum(1 for k, v in hetero_advantage.items() if v.get('sharpe_improved'))
    fc_wins = sum(1 for k, v in hetero_advantage.items() if v.get('crashes_reduced'))

    print(f"\n  Summary: Heterogeneity advantage across {n_levels} VT levels:")
    print(f"    Vol reduced:     {vol_wins}/{n_levels}")
    print(f"    MDD improved:    {mdd_wins}/{n_levels}")
    print(f"    Sharpe improved: {sr_wins}/{n_levels}")
    print(f"    Crashes reduced: {fc_wins}/{n_levels}")

    print(f"\n  Total runtime: {total_elapsed:.1f}s")

    # ====================================
    # Save results
    # ====================================
    results = {
        'experiment_id': 'K864',
        'title': 'Heterogeneous ABM — Does Strategy Diversity Reduce VT Crowding?',
        'type': 'SIMULATION (not empirical)',
        'description': (
            'Extends K827v3 by introducing strategy heterogeneity among VT agents. '
            'Instead of all VT agents using the same 12/VIX rule (homogeneous), '
            'K864 splits them equally among 4 strategy types: (A) 12/VIX aggressive, '
            '(B) Floor(0.3)+Cap(0.9) moderate, (C) Risk Parity conservative, '
            '(D) EWMA(22) slow reactor. Tests whether diversity delays or softens '
            'the crowding tipping point found in K827v3.'
        ),
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'runtime_seconds': total_elapsed,
        'config': {
            'n_agents': N_AGENTS,
            'n_noise_fixed': N_NOISE_FIXED,
            'n_pool': N_POOL,
            'n_days': N_DAYS,
            'n_sims': N_SIMS,
            'n_bootstrap': N_BOOTSTRAP,
            'n_workers': N_WORKERS,
            'vt_fractions': VT_FRACTIONS,
            'kyle_lambda': KYLE_LAMBDA,
            'vix_vol_sensitivity': VIX_VOL_SENSITIVITY,
            'vix_mr_speed': VIX_MR_SPEED,
            'ewma_lookback': EWMA_LOOKBACK,
            'strategy_types': {
                'A': '12/VIX (standard, aggressive)',
                'B': 'Floor(0.3)+Cap(0.9) on 12/VIX (K859 robust)',
                'C': 'Risk Parity (target 10% vol)',
                'D': 'EWMA(22) VT (smoothed, slow reactor)',
            },
        },
        'homogeneous_results': {k: v for k, v in homo_agg.items()},
        'heterogeneous_results': {k: v for k, v in hetero_agg.items()},
        'statistical_tests': all_tests,
        'tipping_point_analysis': conclusions,
        'heterogeneity_advantage': hetero_advantage,
        'summary': {
            'vol_wins': f"{vol_wins}/{n_levels}",
            'mdd_wins': f"{mdd_wins}/{n_levels}",
            'sharpe_wins': f"{sr_wins}/{n_levels}",
            'crash_wins': f"{fc_wins}/{n_levels}",
            'homo_tipping': conclusions['homo_tipping_point'],
            'hetero_tipping': conclusions['hetero_tipping_point'],
        },
        'references': [
            'K827v3: ABM VT crowding — fixed liquidity (tipping at 50-70%)',
            'K859: Robust VT — Floor/Cap + EWMA best combo',
            'Kyle (1985) Continuous Auctions and Insider Trading, Econometrica',
            'Farmer & Foley (2009) Agent-based modelling, Nature',
            'LeBaron (2006) Agent-based Computational Finance, Handbook of Comp. Econ.',
            'Hommes (2006) Heterogeneous Agent Models, Handbook of Comp. Econ.',
        ],
        'limitations': [
            'Simplified Kyle market maker (no strategic traders)',
            'VIX dynamics endogenous but simplified (circular feedback, same as K827v3)',
            'No transaction costs',
            'Equal type proportions only (not tested: unequal mixes)',
            'No adaptive learning (agents do not switch strategies)',
            'N=1000 (same as K827v3)',
            'T=2520 (same as K827v3)',
            '200 sims per config (fewer than K827v3 500 sims but sufficient for CI)',
            'Results model-dependent, not directly applicable to real markets',
        ],
    }

    out_path = os.path.join(os.path.dirname(__file__), 'k864_results.json')
    with open(out_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {out_path}")

    return results


if __name__ == '__main__':
    run_experiment()
