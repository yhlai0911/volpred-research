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
N_SIMS = int(os.environ.get("K864_N_SIMS", "200"))  # Monte Carlo runs per config
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
FIXED_CRASH_THRESHOLD = -0.05
PRIMARY_DEMAND_SCALING = "quadratic"
DEMAND_SCALING_MODES = ["quadratic", "linear"]
HARVEY_T_THRESHOLD = 3.0

# EWMA lookback for Type D agents
EWMA_LOOKBACK = 22
EWMA_LAMBDA = 2.0 / (EWMA_LOOKBACK + 1)  # ~0.087

N_WORKERS = min(cpu_count(), 8)


def weighted_std(values, weights):
    """Population std for a small weighted cross-section."""
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)
    if len(values) == 0 or np.sum(weights) <= 0:
        return 0.0
    mean = np.average(values, weights=weights)
    var = np.average((values - mean) ** 2, weights=weights)
    return float(np.sqrt(max(var, 0.0)))


def portfolio_metrics(port_returns):
    """Return basic annualized metrics for a daily simple-return path."""
    port_returns = np.asarray(port_returns, dtype=float)
    if len(port_returns) == 0:
        return None
    ann_ret = float(np.mean(port_returns) * 252)
    ann_vol = float(np.std(port_returns) * np.sqrt(252))
    sharpe = float(ann_ret / ann_vol) if ann_vol > 0 else 0.0
    cum = np.cumprod(1 + port_returns)
    running_max = np.maximum.accumulate(cum)
    dd = cum / running_max - 1
    return {
        "ann_return": ann_ret,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "mdd": float(np.min(dd)),
    }


def safe_corr(x, y):
    """Correlation that returns None for degenerate series."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    if np.sum(mask) < 3:
        return None
    x = x[mask]
    y = y[mask]
    if np.std(x) <= 1e-12 or np.std(y) <= 1e-12:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def lagged_sell_flow_diagnostics(type_flows, max_lag=5):
    """Summarize whether A-type sell flow leads C/D sell flow."""
    diagnostics = {}
    sell = {k: np.maximum(-np.asarray(v, dtype=float), 0.0) for k, v in type_flows.items()}
    pairs = [("A", "C"), ("A", "D"), ("C", "D")]
    for src, dst in pairs:
        lag_rows = []
        for lag in range(0, max_lag + 1):
            if lag == 0:
                corr = safe_corr(sell[src], sell[dst])
            else:
                corr = safe_corr(sell[src][:-lag], sell[dst][lag:])
            lag_rows.append({"lag": lag, "corr": corr})
        valid = [r for r in lag_rows if r["corr"] is not None]
        if valid:
            best = max(valid, key=lambda r: abs(r["corr"]))
            best_lag = int(best["lag"])
            best_corr = float(best["corr"])
        else:
            best_lag = None
            best_corr = None
        diagnostics[f"{src}_to_{dst}"] = {
            "lag_corr": lag_rows,
            "best_abs_corr_lag": best_lag,
            "best_abs_corr": best_corr,
        }
    diagnostics["avg_abs_flow"] = {
        k: float(np.mean(np.abs(v[1:]))) for k, v in type_flows.items()
    }
    diagnostics["avg_sell_flow"] = {
        k: float(np.mean(sell[k][1:])) for k in type_flows
    }
    return diagnostics


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
        args: (vt_fraction, seed, heterogeneous: bool, demand_scaling)

    Returns: dict of metrics
    """
    if len(args) == 3:
        vt_fraction, seed, heterogeneous = args
        demand_scaling = PRIMARY_DEMAND_SCALING
    else:
        vt_fraction, seed, heterogeneous, demand_scaling = args
    if demand_scaling not in ("quadratic", "linear"):
        raise ValueError(f"Unsupported demand_scaling={demand_scaling}")
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

    type_counts = {'A': n_type_a, 'B': n_type_b, 'C': n_type_c, 'D': n_type_d}

    # Per-type VT weights. Agents of the same type are intentionally identical
    # in this stylized ABM; heterogeneity is across strategy types.
    vt_weights_by_type = {atype: 0.0 for atype in ['A', 'B', 'C', 'D']}
    if n_vt > 0:
        # Initialize weights based on type
        vt_weights_by_type['A'] = weight_type_a(INITIAL_VIX)
        vt_weights_by_type['B'] = weight_type_b(INITIAL_VIX)
        vt_weights_by_type['C'] = weight_type_c(0.16)  # initial guess
        vt_weights_by_type['D'] = weight_type_d(0.16, INITIAL_VIX)

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

    rolling_flash_crashes = 0
    fixed_5pct_crashes = 0
    type_flows = {atype: np.zeros(N_DAYS) for atype in ['A', 'B', 'C', 'D']}
    type_port_returns = {atype: np.zeros(N_DAYS - 1) for atype in ['A', 'B', 'C', 'D']}
    vt_port_returns_path = np.zeros(N_DAYS - 1) if n_vt > 0 else None

    for t in range(1, N_DAYS):
        # Realized vol (rolling 22-day)
        rolling_sigma_daily = FUNDAMENTAL_VOL
        if t > 1:
            n_filled = min(buffer_idx, 22)
            if n_filled > 1:
                rolling_sigma_daily = float(np.std(ret_buffer[:n_filled]))
                realized_vol_ann = rolling_sigma_daily * np.sqrt(252)
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
            new_weights_by_type = {}
            dispersion_values = []
            dispersion_counts = []
            demand_multiplier = n_vt if demand_scaling == "quadratic" else 1.0

            for atype, count in type_counts.items():
                if count <= 0:
                    continue
                if atype == 'A':
                    new_weight = weight_type_a(vix_series[t-1])
                elif atype == 'B':
                    new_weight = weight_type_b(vix_series[t-1])
                elif atype == 'C':
                    new_weight = weight_type_c(realized_vol_ann)
                else:
                    new_weight = weight_type_d(ewma_vol_ann, vix_series[t-1])

                new_weights_by_type[atype] = new_weight
                dispersion_values.append(new_weight)
                dispersion_counts.append(count)

                demand_change = (
                    (new_weight - vt_weights_by_type[atype])
                    * count
                    * demand_multiplier
                )
                type_flows[atype][t] = demand_change
                net_demand += demand_change

            # Track weight dispersion (std of target weights across agents)
            if n_vt > 1 and heterogeneous:
                weight_dispersion_sum += weighted_std(dispersion_values, dispersion_counts)
                weight_dispersion_count += 1

            # K827v3 demand model: each agent's impact scales by n_vt
            # (herding amplification — more VT agents → each has MORE impact)
            # K827v3: demand_change = (target - weights) * n_vt → sum over n_vt agents
            # This creates quadratic scaling: total_demand ~ n_vt^2 * delta_weight
            # V2 also runs a linear-demand sensitivity where demand_multiplier=1.
            vt_weights_by_type.update(new_weights_by_type)

        # BH agents: no demand (buy and hold = 0 net flow)

        # Noise traders: random demand (FIXED count = 200)
        noise_changes = rng.normal(0, NOISE_TRADER_STD, size=n_noise)
        old_noise_weights = noise_weights.copy()
        noise_weights = np.clip(noise_weights + noise_changes, 0.0, 1.5)
        net_demand += np.sum(noise_weights - old_noise_weights)

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
            daily_return = returns[t]
            n_price_clamp += 1

        if rolling_sigma_daily > 0 and daily_return < -3 * rolling_sigma_daily:
            rolling_flash_crashes += 1
        if daily_return < FIXED_CRASH_THRESHOLD:
            fixed_5pct_crashes += 1

        if n_vt > 0:
            weighted_vt_return = 0.0
            for atype, count in type_counts.items():
                if count <= 0:
                    continue
                type_ret = vt_weights_by_type[atype] * daily_return
                type_port_returns[atype][t - 1] = type_ret
                weighted_vt_return += count * type_ret
            vt_port_returns_path[t - 1] = weighted_vt_return / n_vt

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
    expost_flash_crashes = int(np.sum(valid_returns < -3 * sigma_daily)) if sigma_daily > 0 else 0
    expost_flash_crash_freq = float(expost_flash_crashes / len(valid_returns) * 252)
    flash_crash_freq = float(rolling_flash_crashes / len(valid_returns) * 252)
    fixed_crash_freq_5pct = float(fixed_5pct_crashes / len(valid_returns) * 252)

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
    per_type_performance = {}
    flow_diagnostics = None
    if n_vt > 0:
        vt_metrics = portfolio_metrics(vt_port_returns_path)
        vt_return_val = vt_metrics["ann_return"]
        vt_vol_val = vt_metrics["ann_vol"]
        vt_sharpe = vt_metrics["sharpe"]
        vt_mdd_val = vt_metrics["mdd"]

        for atype, count in type_counts.items():
            if count <= 0:
                continue
            per_type_performance[atype] = portfolio_metrics(type_port_returns[atype])
        if heterogeneous:
            flow_diagnostics = lagged_sell_flow_diagnostics(type_flows)

    # Weight dispersion (heterogeneous only)
    avg_weight_dispersion = (float(weight_dispersion_sum / weight_dispersion_count)
                             if weight_dispersion_count > 0 else None)

    return {
        'ann_return': ann_return,
        'ann_vol': ann_vol,
        'max_dd': max_dd,
        'flash_crash_freq': flash_crash_freq,
        'rolling_flash_crash_freq': flash_crash_freq,
        'fixed_crash_freq_5pct': fixed_crash_freq_5pct,
        'expost_flash_crash_freq': expost_flash_crash_freq,
        'kurtosis': kurtosis,
        'skewness': skewness,
        'vix_mean': vix_mean_val,
        'vix_std': vix_std_val,
        'vix_spike_pct': float(vix_spikes * 100),
        'vt_sharpe': vt_sharpe,
        'vt_return': vt_return_val,
        'vt_vol': vt_vol_val,
        'vt_mdd': vt_mdd_val,
        'per_type_performance': per_type_performance,
        'flow_diagnostics': flow_diagnostics,
        'weight_dispersion': avg_weight_dispersion,
        'final_price': float(prices[-1]),
        'n_nan_events': n_nan_events,
        'n_price_clamp': n_price_clamp,
        'n_vt': n_vt,
        'n_bh': n_bh,
        'n_noise': n_noise,
        'heterogeneous': heterogeneous,
        'demand_scaling': demand_scaling,
        'seed': seed,
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
                   'rolling_flash_crash_freq', 'fixed_crash_freq_5pct',
                   'expost_flash_crash_freq',
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

    per_type_agg = {}
    for atype in ['A', 'B', 'C', 'D']:
        rows = [
            m.get('per_type_performance', {}).get(atype)
            for m in sim_results
            if m.get('per_type_performance', {}).get(atype) is not None
        ]
        if not rows:
            continue
        per_type_agg[atype] = {}
        for metric in ['ann_return', 'ann_vol', 'sharpe', 'mdd']:
            vals = [r[metric] for r in rows if r.get(metric) is not None]
            if vals:
                ci_lo, ci_hi = bootstrap_ci(vals)
                per_type_agg[atype][metric] = {
                    'mean': float(np.mean(vals)),
                    'std': float(np.std(vals)),
                    'bootstrap_ci_95': [ci_lo, ci_hi],
                    'n_valid': len(vals),
                }
    agg['_per_type_performance'] = per_type_agg

    flow_rows = [
        m.get('flow_diagnostics') for m in sim_results
        if m.get('flow_diagnostics') is not None
    ]
    if flow_rows:
        flow_agg = {'avg_abs_flow': {}, 'avg_sell_flow': {}, 'lag_pairs': {}}
        for flow_key in ['avg_abs_flow', 'avg_sell_flow']:
            for atype in ['A', 'B', 'C', 'D']:
                vals = [r[flow_key][atype] for r in flow_rows if atype in r.get(flow_key, {})]
                if vals:
                    flow_agg[flow_key][atype] = float(np.mean(vals))
        for pair in ['A_to_C', 'A_to_D', 'C_to_D']:
            pair_rows = [r.get(pair) for r in flow_rows if r.get(pair)]
            if not pair_rows:
                continue
            lag_corr = []
            for lag in range(0, 6):
                vals = [
                    item['corr']
                    for row in pair_rows
                    for item in row.get('lag_corr', [])
                    if item.get('lag') == lag and item.get('corr') is not None
                ]
                lag_corr.append({
                    'lag': lag,
                    'mean_corr': float(np.mean(vals)) if vals else None,
                    'n_valid': len(vals),
                })
            best_lags = [
                row.get('best_abs_corr_lag') for row in pair_rows
                if row.get('best_abs_corr_lag') is not None
            ]
            flow_agg['lag_pairs'][pair] = {
                'lag_corr': lag_corr,
                'median_best_abs_corr_lag': float(np.median(best_lags)) if best_lags else None,
            }
        agg['_flow_diagnostics'] = flow_agg

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


def paired_hln_test(values_homo, values_hetero, metric_name, horizon=1):
    """Common-random-number paired test with HLN small-sample correction.

    This is DM-HLN-like only in the sense of testing paired loss/metric
    differentials with the Harvey-Leybourne-Newbold small-sample factor.
    K864 is an ABM Monte Carlo regime comparison, not a forecast-loss panel.
    """
    v1 = np.array(values_homo, dtype=float)
    v2 = np.array(values_hetero, dtype=float)
    n = min(len(v1), len(v2))
    if n < 3:
        return None
    v1 = v1[:n]
    v2 = v2[:n]
    diffs = v2 - v1
    diffs = diffs[np.isfinite(diffs)]
    n = len(diffs)
    if n < 3:
        return None
    diff_std = np.std(diffs, ddof=1)
    if diff_std <= 1e-12:
        t_stat = 0.0
    else:
        t_stat = float(np.mean(diffs) / (diff_std / np.sqrt(n)))
    h = max(1, int(horizon))
    hln_factor = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    hln_t = float(t_stat * hln_factor)
    p_val = float(2 * (1 - sp_stats.t.cdf(abs(hln_t), df=n - 1)))
    diff = float(np.mean(diffs))
    base_mean = float(np.mean(v1))
    return {
        'metric': metric_name,
        'test': 'paired_hln_common_random_numbers',
        'homo_mean': base_mean,
        'hetero_mean': float(np.mean(v2)),
        'difference': diff,
        'pct_change': float(diff / abs(base_mean) * 100) if abs(base_mean) > 1e-10 else None,
        'paired_t_stat': t_stat,
        'hln_t_stat': hln_t,
        'hln_factor': float(hln_factor),
        'p_value': p_val,
        'significant_5pct': bool(p_val < 0.05),
        'significant_1pct': bool(p_val < 0.01),
        'harvey_3sigma_pass': bool(abs(hln_t) >= HARVEY_T_THRESHOLD),
        'n_pairs': n,
    }


def build_statistical_tests(homo_results, hetero_results, test_metrics):
    all_tests = {}
    all_welch = {}
    for vf in VT_FRACTIONS:
        if vf == 0:
            continue
        key = f"{int(vf*100)}%"
        tests_for_level = {}
        welch_for_level = {}
        homo_sims = homo_results.get(key, [])
        hetero_sims = hetero_results.get(key, [])
        for metric in test_metrics:
            h_vals = [m[metric] for m in homo_sims if m[metric] is not None]
            e_vals = [m[metric] for m in hetero_sims if m[metric] is not None]
            test = paired_hln_test(h_vals, e_vals, metric)
            if test:
                tests_for_level[metric] = test
            wtest = welch_t_test(h_vals, e_vals, metric)
            if wtest:
                welch_for_level[metric] = wtest
        all_tests[key] = tests_for_level
        all_welch[key] = welch_for_level
    return all_tests, all_welch


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
    def run_config_set(demand_scaling):
        homo = {}
        hetero = {}
        all_args = []
        all_labels = []

        for vf in VT_FRACTIONS:
            base_seed = int(vf * 100000) + 42
            # Homogeneous and heterogeneous use common random numbers.
            for sim_idx in range(N_SIMS):
                seed = base_seed + sim_idx
                all_args.append((vf, seed, False, demand_scaling))
                all_labels.append(('homo', vf))
            if vf > 0:
                for sim_idx in range(N_SIMS):
                    seed = base_seed + sim_idx
                    all_args.append((vf, seed, True, demand_scaling))
                    all_labels.append(('hetero', vf))

        print(f"Demand scaling: {demand_scaling}")
        print(f"Total simulations: {len(all_args)}")
        print(f"Running with {N_WORKERS} workers...")

        t0 = time.time()
        with Pool(N_WORKERS) as pool:
            sim_results = pool.map(run_single_simulation, all_args)
        elapsed = time.time() - t0
        print(f"{demand_scaling} simulations completed in {elapsed:.1f}s")
        print()

        for label, result in zip(all_labels, sim_results):
            regime, vf = label
            key = f"{int(vf*100)}%"
            if regime == 'homo':
                homo.setdefault(key, []).append(result)
            else:
                hetero.setdefault(key, []).append(result)

        homo_agg_local = {}
        hetero_agg_local = {}
        for vf in VT_FRACTIONS:
            key = f"{int(vf*100)}%"
            homo_agg_local[key] = aggregate_metrics(homo.get(key, []))
            if key in hetero:
                hetero_agg_local[key] = aggregate_metrics(hetero[key])
        return homo, hetero, homo_agg_local, hetero_agg_local

    homo_results, hetero_results, homo_agg, hetero_agg = run_config_set(PRIMARY_DEMAND_SCALING)
    linear_homo_results, linear_hetero_results, linear_homo_agg, linear_hetero_agg = run_config_set("linear")

    # ====================================
    # Aggregate and compare
    # ====================================
    print("=" * 72)
    print("RESULTS")
    print("=" * 72)

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
    print("(paired common-random-number differences with HLN small-sample correction)")
    print("=" * 72)

    test_metrics = ['ann_vol', 'max_dd', 'flash_crash_freq', 'kurtosis',
                    'vt_sharpe', 'vt_mdd']

    all_tests, welch_reference_tests = build_statistical_tests(homo_results, hetero_results, test_metrics)
    linear_tests, linear_welch_reference_tests = build_statistical_tests(
        linear_homo_results, linear_hetero_results, test_metrics
    )
    for vf in VT_FRACTIONS:
        if vf == 0:
            continue
        key = f"{int(vf*100)}%"

        print(f"\n--- VT = {key} ---")
        for metric in test_metrics:
            test = all_tests.get(key, {}).get(metric)
            if test:
                sig = "***" if test['harvey_3sigma_pass'] else (
                    "**" if test['significant_1pct'] else ("*" if test['significant_5pct'] else "")
                )
                pct_str = f"{test['pct_change']:+.1f}%" if test['pct_change'] is not None else "N/A"
                print(f"  {metric:>20}: homo={test['homo_mean']:.4f}, hetero={test['hetero_mean']:.4f}, "
                      f"diff={test['difference']:+.4f} ({pct_str}), HLN t={test['hln_t_stat']:.2f}, "
                      f"p={test['p_value']:.4f} {sig}")

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
            advantages['vol_significant'] = vol_test.get('harvey_3sigma_pass', False)

        # Less negative MDD = better
        mdd_test = tests.get('max_dd')
        if mdd_test:
            advantages['mdd_improved'] = mdd_test['difference'] > 0  # less negative
            advantages['mdd_pct_change'] = mdd_test.get('pct_change')
            advantages['mdd_significant'] = mdd_test.get('harvey_3sigma_pass', False)

        # Higher VT Sharpe = better
        sr_test = tests.get('vt_sharpe')
        if sr_test:
            advantages['sharpe_improved'] = sr_test['difference'] > 0
            advantages['sharpe_pct_change'] = sr_test.get('pct_change')
            advantages['sharpe_significant'] = sr_test.get('harvey_3sigma_pass', False)

        # Fewer flash crashes = better
        fc_test = tests.get('flash_crash_freq')
        if fc_test:
            advantages['crashes_reduced'] = fc_test['difference'] < 0
            advantages['crashes_pct_change'] = fc_test.get('pct_change')
            advantages['crashes_significant'] = fc_test.get('harvey_3sigma_pass', False)

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

    print(f"\n  (* = passes Harvey-style |HLN t| >= {HARVEY_T_THRESHOLD:.1f})")

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

    def metric_change_table(homo_source, hetero_source):
        table = {}
        for vf in VT_FRACTIONS:
            if vf == 0:
                continue
            key = f"{int(vf*100)}%"
            row = {}
            for metric in ['ann_vol', 'max_dd', 'flash_crash_freq',
                           'fixed_crash_freq_5pct', 'vt_sharpe', 'vt_mdd']:
                h_metric = homo_source.get(key, {}).get(metric)
                e_metric = hetero_source.get(key, {}).get(metric)
                if not isinstance(h_metric, dict) or not isinstance(e_metric, dict):
                    continue
                h_mean = h_metric.get('mean')
                e_mean = e_metric.get('mean')
                if h_mean is None or e_mean is None:
                    continue
                diff = e_mean - h_mean
                row[metric] = {
                    'homo_mean': h_mean,
                    'hetero_mean': e_mean,
                    'difference': diff,
                    'pct_change': diff / abs(h_mean) * 100 if abs(h_mean) > 1e-10 else None,
                }
            table[key] = row
        return table

    primary_metric_changes = metric_change_table(homo_agg, hetero_agg)
    linear_metric_changes = metric_change_table(linear_homo_agg, linear_hetero_agg)

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
            'primary_demand_scaling': PRIMARY_DEMAND_SCALING,
            'demand_scaling_modes': DEMAND_SCALING_MODES,
            'fixed_crash_threshold': FIXED_CRASH_THRESHOLD,
            'flash_crash_definition': 'rolling t-1 sigma: r_t < -3 * sigma_{t-1,22d}',
            'seed_formula': 'base_seed=int(vt_fraction*100000)+42; homo and hetero share sim_idx seed',
            'harvey_t_threshold': HARVEY_T_THRESHOLD,
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
        'linear_demand_sensitivity': {
            'homogeneous_results': {k: v for k, v in linear_homo_agg.items()},
            'heterogeneous_results': {k: v for k, v in linear_hetero_agg.items()},
            'metric_changes': linear_metric_changes,
        },
        'primary_metric_changes': primary_metric_changes,
        'statistical_tests': all_tests,
        'welch_reference_tests': welch_reference_tests,
        'linear_demand_statistical_tests': linear_tests,
        'linear_demand_welch_reference_tests': linear_welch_reference_tests,
        'statistical_test_note': (
            'Primary tests use common-random-number paired differences with '
            'Harvey-Leybourne-Newbold small-sample correction and a Harvey-style '
            '|t|>=3 reporting gate. This is an ABM Monte Carlo regime comparison, '
            'not a forecast-loss DM panel.'
        ),
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
            'Heterogeneity is across 4 deterministic strategy types, not within-type beliefs',
            'Primary K827v3-compatible demand model is quadratic in n_vt; linear-demand sensitivity is reported separately',
            'Flash-crash metric uses rolling t-1 sigma; fixed -5% crash frequency is also reported',
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
