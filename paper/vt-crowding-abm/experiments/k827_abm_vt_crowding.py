"""
K827: Agent-Based Simulation of VT Strategy Crowding (Full ABM)
================================================================
[提出: Claude, 執行: Claude]
類型：模擬實驗（非實證數據）

Research Question:
  If a growing fraction of investors adopt 12/VIX Volatility Targeting,
  does the strategy crowd itself out? Does it destabilize markets?
  Is there a critical tipping point?

Model Architecture:
  - N=1000 heterogeneous agents in 3 classes:
    (a) Buy-and-Hold: fixed 100% equity
    (b) 12/VIX VT agents: w_t = min(12/VIX_t, 1.5), rebalance daily
    (c) Noise traders: random demand (liquidity providers)
  - Price formation: Kyle (1985) style market maker
    price_change = lambda * net_order_flow + sigma_fundamental * noise
  - Endogenous VIX: VIX_t = f(realized_vol_20d) with mean-reversion
  - Positive feedback: VT selling → price drop → vol up → VIX up → more selling

Parameters tested:
  VT agent fraction: 0%, 10%, 20%, 30%, 50%, 70%, 100%
  100 simulations per level, 2520 days (10 years) each

References:
  - Kyle (1985) "Continuous Auctions and Insider Trading", Econometrica
  - Farmer & Foley (2009) "The economy needs agent-based modelling", Nature
  - Bouchaud et al. (2018) "Trades, Quotes and Prices", Cambridge UP
  - Brunnermeier & Pedersen (2009) "Market Liquidity and Funding Liquidity", RFS
  - K110 (prior crowding simulation, simpler model)

Error Log rules applicable:
  - This is a SIMULATION experiment, must be clearly labelled as such
  - No lookahead concern (no real data backtesting)
  - Results cannot be directly applied to real markets
"""

import sys
import warnings
warnings.filterwarnings("ignore")

import numpy as np
from scipy import stats as sp_stats
import json
import os
from datetime import datetime

np.random.seed(42)

# ============================================================
# Configuration
# ============================================================
N_AGENTS = 1000
N_DAYS = 2520        # 10 years of trading days
N_SIMS = 100         # Monte Carlo simulations per crowding level
VT_FRACTIONS = [0.0, 0.10, 0.20, 0.30, 0.50, 0.70, 1.00]

# Market parameters
INITIAL_PRICE = 100.0
INITIAL_VIX = 15.0
ANNUAL_DRIFT = 0.08              # ~8% expected annual return
DAILY_DRIFT = ANNUAL_DRIFT / 252
FUNDAMENTAL_VOL = 0.16 / np.sqrt(252)  # ~16% annual → daily
KYLE_LAMBDA = 0.005              # Price impact per unit of net order flow
VIX_MEAN = 18.0                  # Long-run VIX mean
VIX_MR_SPEED = 0.03              # Mean-reversion speed (daily)
VIX_VOL_SENSITIVITY = 200.0      # How much realized vol lifts VIX
VIX_NOISE_STD = 0.3              # Daily VIX noise (in VIX points)

# Agent parameters
VT_CAP = 1.5                     # Max weight for VT agents
NOISE_TRADER_STD = 0.02          # Std of noise trader demand changes
BH_WEIGHT = 1.0                  # Buy-and-hold fixed weight

print("=" * 72)
print("K827: Agent-Based Simulation of VT Strategy Crowding")
print("=" * 72)
print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"Config: N_AGENTS={N_AGENTS}, N_DAYS={N_DAYS}, N_SIMS={N_SIMS}")
print(f"VT fractions: {VT_FRACTIONS}")
print()

# ============================================================
# Core simulation (vectorized over agents, sequential over days)
# ============================================================

def run_single_simulation(vt_fraction, seed):
    """Run one simulation with given VT adoption fraction."""
    rng = np.random.RandomState(seed)

    # Agent allocation
    n_vt = int(N_AGENTS * vt_fraction)
    n_noise = int(N_AGENTS * 0.3 * (1 - vt_fraction))  # noise traders scale down
    n_bh = N_AGENTS - n_vt - n_noise

    # Ensure at least some noise traders for liquidity
    if n_noise < 10:
        n_noise = 10
        n_bh = max(0, N_AGENTS - n_vt - n_noise)

    # State arrays
    prices = np.zeros(N_DAYS)
    returns = np.zeros(N_DAYS)
    vix_series = np.zeros(N_DAYS)

    # Agent weights (current equity allocation)
    # VT agents: variable; BH: fixed 1.0; Noise: random walk around 0.5
    vt_weights = np.ones(n_vt) * min(12.0 / INITIAL_VIX, VT_CAP) if n_vt > 0 else np.array([])
    noise_weights = np.ones(n_noise) * 0.5

    prices[0] = INITIAL_PRICE
    vix_series[0] = INITIAL_VIX

    # Realized vol buffer (20-day rolling)
    ret_buffer = np.zeros(20)
    buffer_idx = 0

    for t in range(1, N_DAYS):
        # --- 1. VIX update (endogenous) ---
        realized_vol_20d = np.std(ret_buffer) * np.sqrt(252) if t > 1 else FUNDAMENTAL_VOL * np.sqrt(252)

        # VIX = mean-revert + sensitivity to realized vol + noise
        vix_target = VIX_MEAN + VIX_VOL_SENSITIVITY * max(0, realized_vol_20d - 0.16)
        vix_series[t] = vix_series[t-1] + VIX_MR_SPEED * (vix_target - vix_series[t-1]) + rng.normal(0, VIX_NOISE_STD)
        vix_series[t] = max(9.0, min(80.0, vix_series[t]))  # clamp to realistic range

        # --- 2. Agent demand calculation ---
        # VT agents: target weight based on yesterday's VIX (lag=1, no lookahead)
        net_demand = 0.0

        if n_vt > 0:
            vt_target = min(12.0 / vix_series[t-1], VT_CAP)  # signal from t-1
            vt_demand_change = (vt_target - vt_weights) * n_vt  # aggregate demand change
            net_demand += np.sum(vt_demand_change)
            vt_weights[:] = vt_target

        # BH agents: no demand change (they just hold)
        # net_demand += 0

        # Noise traders: random demand changes
        noise_changes = rng.normal(0, NOISE_TRADER_STD, size=n_noise)
        noise_weights = np.clip(noise_weights + noise_changes, 0.0, 1.5)
        net_demand += np.sum(noise_changes) * N_AGENTS / n_noise if n_noise > 0 else 0

        # --- 3. Price formation (Kyle model) ---
        fundamental_shock = rng.normal(DAILY_DRIFT, FUNDAMENTAL_VOL)
        price_impact = KYLE_LAMBDA * net_demand / N_AGENTS  # normalize by N

        daily_return = fundamental_shock + price_impact
        returns[t] = daily_return
        prices[t] = prices[t-1] * (1 + daily_return)

        # Enforce positive prices
        if prices[t] <= 0:
            prices[t] = 0.01
            returns[t] = (prices[t] / prices[t-1]) - 1

        # Update return buffer for realized vol
        ret_buffer[buffer_idx % 20] = daily_return
        buffer_idx += 1

    # --- Compute metrics ---
    valid_returns = returns[1:]  # skip day 0

    # Market stability
    ann_vol = np.std(valid_returns) * np.sqrt(252)
    ann_return = np.mean(valid_returns) * 252

    # Max drawdown
    cum_returns = np.cumprod(1 + valid_returns)
    running_max = np.maximum.accumulate(cum_returns)
    drawdowns = cum_returns / running_max - 1
    max_dd = np.min(drawdowns)

    # Flash crash frequency (>3 sigma daily moves)
    sigma_daily = np.std(valid_returns)
    flash_crashes = np.sum(valid_returns < -3 * sigma_daily) if sigma_daily > 0 else 0
    flash_crash_freq = flash_crashes / len(valid_returns) * 252  # annualized

    # Tail statistics
    kurtosis = sp_stats.kurtosis(valid_returns, fisher=True)  # excess kurtosis
    skewness = sp_stats.skew(valid_returns)

    # VIX statistics
    vix_mean = np.mean(vix_series[1:])
    vix_std = np.std(vix_series[1:])
    vix_spikes = np.sum(vix_series[1:] > 30) / len(vix_series[1:])  # fraction of days VIX > 30
    vix_return_corr = np.corrcoef(vix_series[1:], valid_returns)[0, 1]

    # VT strategy performance (if VT agents exist)
    vt_sharpe = np.nan
    vt_return = np.nan
    vt_vol = np.nan
    if n_vt > 0:
        # Reconstruct VT portfolio returns
        # Weight at day t is based on VIX at day t-1 (lag=1, no lookahead)
        # valid_returns = returns[1:] → length N_DAYS-1
        # For day t (t=1..N_DAYS-1), weight = min(12/VIX[t-1], cap)
        vt_w = np.minimum(12.0 / vix_series[:-1], VT_CAP)  # VIX[0..N_DAYS-2] → length N_DAYS-1
        vt_port_returns = vt_w * valid_returns  # both length N_DAYS-1

        vt_return = np.mean(vt_port_returns) * 252
        vt_vol_val = np.std(vt_port_returns) * np.sqrt(252)
        vt_sharpe = vt_return / vt_vol_val if vt_vol_val > 0 else 0
        vt_vol = vt_vol_val

    return {
        'ann_return': float(ann_return),
        'ann_vol': float(ann_vol),
        'max_dd': float(max_dd),
        'flash_crash_freq': float(flash_crash_freq),
        'kurtosis': float(kurtosis),
        'skewness': float(skewness),
        'vix_mean': float(vix_mean),
        'vix_std': float(vix_std),
        'vix_spike_pct': float(vix_spikes * 100),
        'vix_return_corr': float(vix_return_corr),
        'vt_sharpe': float(vt_sharpe) if not np.isnan(vt_sharpe) else None,
        'vt_return': float(vt_return) if not np.isnan(vt_return) else None,
        'vt_vol': float(vt_vol) if not np.isnan(vt_vol) else None,
        'final_price': float(prices[-1]),
    }


# ============================================================
# Run all simulations
# ============================================================
all_results = {}

for vt_frac in VT_FRACTIONS:
    label = f"{int(vt_frac*100)}%"
    print(f"\n--- VT Fraction: {label} ({N_SIMS} simulations) ---")

    sim_metrics = []
    for sim_idx in range(N_SIMS):
        seed = int(vt_frac * 10000) + sim_idx + 42
        metrics = run_single_simulation(vt_frac, seed)
        sim_metrics.append(metrics)

        if (sim_idx + 1) % 25 == 0:
            print(f"  Completed {sim_idx+1}/{N_SIMS} simulations")

    # Aggregate statistics
    metric_keys = list(sim_metrics[0].keys())
    agg = {}
    for key in metric_keys:
        values = [m[key] for m in sim_metrics if m[key] is not None]
        if len(values) > 0:
            agg[key] = {
                'mean': float(np.mean(values)),
                'std': float(np.std(values)),
                'median': float(np.median(values)),
                'q5': float(np.percentile(values, 5)),
                'q95': float(np.percentile(values, 95)),
                'min': float(np.min(values)),
                'max': float(np.max(values)),
            }
        else:
            agg[key] = None

    all_results[label] = agg

    # Print summary
    print(f"  Market vol: {agg['ann_vol']['mean']:.3f} +/- {agg['ann_vol']['std']:.3f}")
    print(f"  Max DD: {agg['max_dd']['mean']:.3f} +/- {agg['max_dd']['std']:.3f}")
    print(f"  Kurtosis: {agg['kurtosis']['mean']:.2f} +/- {agg['kurtosis']['std']:.2f}")
    print(f"  Flash crash freq: {agg['flash_crash_freq']['mean']:.2f}/yr")
    print(f"  VIX mean: {agg['vix_mean']['mean']:.2f}")
    if agg.get('vt_sharpe') is not None:
        print(f"  VT Sharpe: {agg['vt_sharpe']['mean']:.3f} +/- {agg['vt_sharpe']['std']:.3f}")


# ============================================================
# Analysis: detect critical threshold
# ============================================================
print("\n" + "=" * 72)
print("ANALYSIS: Crowding Effects Summary")
print("=" * 72)

# Strategy degradation analysis
print("\n--- Strategy Degradation (VT Sharpe by crowding level) ---")
sharpe_by_level = {}
for frac in VT_FRACTIONS:
    label = f"{int(frac*100)}%"
    if all_results[label].get('vt_sharpe') is not None:
        s = all_results[label]['vt_sharpe']
        sharpe_by_level[label] = s['mean']
        print(f"  {label:>5s}: Sharpe = {s['mean']:.3f} +/- {s['std']:.3f}  "
              f"[{s['q5']:.3f}, {s['q95']:.3f}]")

# Market stability analysis
print("\n--- Market Stability (Volatility & Tail Risk) ---")
vol_baseline = all_results['0%']['ann_vol']['mean']
kurt_baseline = all_results['0%']['kurtosis']['mean']
for frac in VT_FRACTIONS:
    label = f"{int(frac*100)}%"
    v = all_results[label]['ann_vol']
    k = all_results[label]['kurtosis']
    fc = all_results[label]['flash_crash_freq']
    vol_change = (v['mean'] / vol_baseline - 1) * 100
    print(f"  {label:>5s}: Vol={v['mean']:.3f} ({vol_change:+.1f}%), "
          f"Kurt={k['mean']:.2f}, Flash={fc['mean']:.2f}/yr")

# VIX dynamics
print("\n--- VIX Dynamics ---")
for frac in VT_FRACTIONS:
    label = f"{int(frac*100)}%"
    vm = all_results[label]['vix_mean']
    vs = all_results[label]['vix_std']
    vsp = all_results[label]['vix_spike_pct']
    print(f"  {label:>5s}: VIX mean={vm['mean']:.2f}, std={vs['mean']:.2f}, "
          f"spike(>30)={vsp['mean']:.1f}%")

# Critical threshold detection
print("\n--- Critical Threshold Detection ---")
sharpe_10 = all_results['10%']['vt_sharpe']['mean'] if all_results['10%'].get('vt_sharpe') else None
for frac in VT_FRACTIONS[1:]:  # skip 0%
    label = f"{int(frac*100)}%"
    if all_results[label].get('vt_sharpe') is not None and sharpe_10 is not None:
        degradation = (1 - all_results[label]['vt_sharpe']['mean'] / sharpe_10) * 100
        vol_increase = (all_results[label]['ann_vol']['mean'] / vol_baseline - 1) * 100
        print(f"  {label:>5s}: Sharpe degradation={degradation:+.1f}%, "
              f"Vol increase={vol_increase:+.1f}%")
        if degradation > 30:
            print(f"         *** CRITICAL: >30% Sharpe degradation at {label} VT adoption ***")

# ============================================================
# Statistical tests: is the degradation significant?
# ============================================================
print("\n--- Statistical Significance (t-test: 10% vs each level) ---")
if all_results['10%'].get('vt_sharpe') is not None:
    baseline_sharpes_10 = all_results['10%']['vt_sharpe']
    for frac in [0.20, 0.30, 0.50, 0.70, 1.00]:
        label = f"{int(frac*100)}%"
        if all_results[label].get('vt_sharpe') is not None:
            other = all_results[label]['vt_sharpe']
            # Welch's t-test using summary statistics
            n = N_SIMS
            t_stat = (baseline_sharpes_10['mean'] - other['mean']) / np.sqrt(
                baseline_sharpes_10['std']**2 / n + other['std']**2 / n
            )
            # Approximate p-value (two-sided)
            df_approx = 2 * n - 2
            p_value = 2 * (1 - sp_stats.t.cdf(abs(t_stat), df=df_approx))
            sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else ("*" if abs(t_stat) > 1.65 else ""))
            print(f"  10% vs {label:>5s}: t={t_stat:.2f}, p={p_value:.4f} {sig}")


# ============================================================
# Save results
# ============================================================
output = {
    'experiment_id': 'K827',
    'title': 'Agent-Based Simulation of VT Strategy Crowding',
    'type': 'SIMULATION (not empirical)',
    'description': 'ABM with Kyle market maker, endogenous VIX, and heterogeneous agents to study crowding effects of 12/VIX VT strategy adoption',
    'timestamp': datetime.now().isoformat(),
    'config': {
        'n_agents': N_AGENTS,
        'n_days': N_DAYS,
        'n_sims': N_SIMS,
        'vt_fractions': VT_FRACTIONS,
        'kyle_lambda': KYLE_LAMBDA,
        'fundamental_vol_annual': 0.16,
        'initial_vix': INITIAL_VIX,
        'vix_mean_reversion': VIX_MR_SPEED,
        'vix_long_run_mean': VIX_MEAN,
        'vt_cap': VT_CAP,
    },
    'results_by_crowding_level': all_results,
    'references': [
        'Kyle (1985) Continuous Auctions and Insider Trading, Econometrica',
        'Farmer & Foley (2009) The economy needs agent-based modelling, Nature',
        'Bouchaud et al. (2018) Trades Quotes and Prices, Cambridge UP',
        'Brunnermeier & Pedersen (2009) Market Liquidity and Funding Liquidity, RFS',
        'K110: Prior VT crowding simulation (simpler model)',
    ],
    'limitations': [
        'Simplified Kyle market maker (no strategic traders, no inventory management)',
        'VIX dynamics are endogenous but simplified (not option-implied)',
        'No transaction costs in simulation',
        'Agents are homogeneous within class (all VT agents use same rule)',
        'No adaptive learning (agents don\'t change strategy)',
        'Results are model-dependent and cannot be directly applied to real markets',
        'N=1000 agents is small relative to real market (millions of participants)',
    ],
}

# Save
results_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            'k827_abm_vt_crowding_results.json')
with open(results_path, 'w') as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f"\nResults saved to: {results_path}")
print(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
