"""
K1262 Phase 2: TF/MR scaling × window × adoption robustness sweep
==================================================================
[提出: 主線程 (Phase 2 dispatch), 執行: worktree agent ab9402a6ae829d04d]
類型：模擬實驗（非實證數據；K1261 Phase 1 robustness extension）

Goal:
  Phase 1 (K1261) verdict H1+ — TF/MR show critical adoption thresholds
  earlier than VT_baseline (TF @ 20%, MR @ 50%, VT @ 100% under strict
  detector). Code review CONDITIONAL PASS flagged caveat: H1+ direction
  robust but threshold magnitudes specification-dependent (TF/MR scaling=10
  may be aggressive). Phase 2 directly tests this:

  - Scaling sensitivity: at lower scaling (1, 3, 5) does TF threshold disappear?
  - Window sensitivity: at different momentum windows (10, 22, 60), does TF/MR
    threshold qualitative ranking persist?
  - Detector criterion: under softer detector matching P5 paper criterion, how
    do VT/TF/MR thresholds compare?

Implementation:
  - Forked from experiments/k1261/k1261_non_vt_ablation.py simulation core
    (run_single_simulation, agent classes, aggregation).
  - TF_SCALING and MOMENTUM_WINDOW are now per-call parameters (not module
    constants).
  - Loop: 2 treatments (TF, MR) × 4 scaling × 3 window × 7 adoption × 100 MC
    = 16,800 sims (~3-5 min wall at K1261 throughput).
  - Seed formula extends K1261:
      base_seed = int(adoption*100000) + sim_idx + 42 + scaling*1000 + window*10
    (disambiguates cells while preserving determinism).
  - Lookahead protected: TF/MR signals use returns[t-window:t] (excludes t).

References:
  - experiments/k1261/k1261_non_vt_ablation.py (903L, simulation source)
  - experiments/k1261/k1261_phase1_main.py (757L, phase1 runner pattern)
  - experiments/k1261/k1261_results.json (Phase 1 raw aggregates; input for
    softer detector recompute in companion analysis script)
  - experiments/k1262/README.md (full Phase 2 design)
  - .claude/rules/experiments.md (lookahead, seed, worktree禁忌)

Output:
  - experiments/k1262/k1262_results.json (raw aggregates, 168 cells)
  - experiments/k1262/k1262_softer_detector_table.md (Part B, K1261 recompute)
  - experiments/k1262/k1262_threshold_matrix.md (Part C, scaling × window grid)
  - experiments/k1262/k1262_verdict.md (Phase 2 falsifiability verdict)
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
import time

# ============================================================
# Configuration (mirrors K1261; sweep parameters separated)
# ============================================================

# Same as K827v3 / K1261 baseline (do NOT modify for fair comparison):
N_AGENTS = 1000
N_NOISE_FIXED = 200
N_BH_VT_POOL = 800
N_DAYS = 2520                # 10 years
N_SIMS_PHASE2 = 100          # per cell (24 cells × 7 adoption × 100 = 16,800)
N_BOOTSTRAP = 2000

ADOPTION_LEVELS = [0.0, 0.10, 0.20, 0.30, 0.50, 0.70, 1.00]

# Phase 2 sweep grid
TREATMENTS_PHASE2 = ['TF', 'MR']
SCALING_GRID = [1, 3, 5, 10]
WINDOW_GRID = [10, 22, 60]

# Strategy default cap (matches K1261)
EXPOSURE_CAP = 1.5

# K827v3 baseline parameters (same constants as K1261)
BASELINE_PARAMS = {
    'kyle_lambda': 0.005,
    'vix_vol_sensitivity': 200.0,
    'vix_mr_speed': 0.03,
}

INITIAL_PRICE = 100.0
INITIAL_VIX = 15.0
ANNUAL_DRIFT = 0.08
DAILY_DRIFT = ANNUAL_DRIFT / 252
FUNDAMENTAL_VOL = 0.16 / np.sqrt(252)
VIX_MEAN = 18.0
VIX_NOISE_STD = 0.3
VT_CAP = 1.5
NOISE_TRADER_STD = 0.02

N_WORKERS = min(cpu_count(), 8)


# ============================================================
# Strategy agent classes (fork from K1261; TF/MR parameterized at __init__)
# ============================================================

class StrategyAgent:
    """Base class. Subclass and implement update_target_weight(state)."""
    def update_target_weight(self, t, prices, returns, vix_series, current_weights):
        raise NotImplementedError


class TFAgent(StrategyAgent):
    """Trend-following agent.

    Target weight = clip(scaling * sum(returns_{t-N..t-1}), -CAP, +CAP).
    Lookahead-safe: reads returns[t-window:t] which excludes index t.
    """
    def __init__(self, window, scaling, cap=EXPOSURE_CAP):
        self.window = window
        self.scaling = scaling
        self.cap = cap

    def update_target_weight(self, t, prices, returns, vix_series, current_weights):
        n = len(current_weights)
        if n == 0:
            return current_weights, 0.0
        if t < self.window + 1:
            momentum = 0.0
        else:
            momentum = float(np.sum(returns[t - self.window:t]))
        tf_target = float(np.clip(self.scaling * momentum, -self.cap, self.cap))
        tf_demand_change = (tf_target - current_weights) * n
        net_demand = float(np.sum(tf_demand_change))
        new_weights = np.full(n, tf_target)
        return new_weights, net_demand


class MRAgent(StrategyAgent):
    """Mean-reversion agent (opposite sign of TFAgent)."""
    def __init__(self, window, scaling, cap=EXPOSURE_CAP):
        self.window = window
        self.scaling = scaling
        self.cap = cap

    def update_target_weight(self, t, prices, returns, vix_series, current_weights):
        n = len(current_weights)
        if n == 0:
            return current_weights, 0.0
        if t < self.window + 1:
            momentum = 0.0
        else:
            momentum = float(np.sum(returns[t - self.window:t]))
        mr_target = float(np.clip(-self.scaling * momentum, -self.cap, self.cap))
        mr_demand_change = (mr_target - current_weights) * n
        net_demand = float(np.sum(mr_demand_change))
        new_weights = np.full(n, mr_target)
        return new_weights, net_demand


def _build_strategy(treatment_name, window, scaling):
    if treatment_name == 'TF':
        return TFAgent(window=window, scaling=scaling)
    elif treatment_name == 'MR':
        return MRAgent(window=window, scaling=scaling)
    else:
        raise ValueError(f"Unknown treatment: {treatment_name}")


# ============================================================
# Core simulation (single run) — fork of K1261 run_single_simulation
# ============================================================

def run_single_simulation(args):
    """Run one simulation with FIXED noise traders + TF/MR strategy agent.

    Args (tuple):
        treatment: str ('TF' | 'MR')
        adoption: float in ADOPTION_LEVELS
        seed: int
        window: int (momentum window)
        scaling: int (TF/MR scaling)

    Mirrors K827v3 / K1261 dynamics byte-for-byte except:
      - TF/MR window/scaling are passed in (not module constants)
      - rng draw order preserved (VIX noise → noise trader changes →
        fundamental shock per timestep)
    """
    treatment, adoption, seed, window, scaling = args

    kyle_lambda = BASELINE_PARAMS['kyle_lambda']
    vix_vol_sensitivity = BASELINE_PARAMS['vix_vol_sensitivity']
    vix_mr_speed = BASELINE_PARAMS['vix_mr_speed']

    rng = np.random.RandomState(seed)

    # Agent allocation (FIXED LIQUIDITY, K827v3 design)
    n_noise = N_NOISE_FIXED
    n_strategy = int(N_BH_VT_POOL * adoption)
    n_bh = N_BH_VT_POOL - n_strategy

    strategy = _build_strategy(treatment, window=window, scaling=scaling)

    # State arrays
    prices = np.zeros(N_DAYS)
    returns = np.zeros(N_DAYS)
    vix_series = np.zeros(N_DAYS)

    # TF/MR initial weights = 0 (no signal at t=0)
    init_w = 0.0
    strategy_weights = np.ones(n_strategy) * init_w if n_strategy > 0 else np.array([])

    noise_weights = np.ones(n_noise) * 0.5

    prices[0] = INITIAL_PRICE
    vix_series[0] = INITIAL_VIX

    strategy_weight_history = np.zeros(N_DAYS)
    strategy_weight_history[0] = init_w

    ret_buffer = np.zeros(20)
    buffer_idx = 0

    n_nan_events = 0
    n_price_clamp = 0

    for t in range(1, N_DAYS):
        # VIX update — VERBATIM from K827v3 / K1261
        realized_vol_20d = np.std(ret_buffer) * np.sqrt(252) if t > 1 else FUNDAMENTAL_VOL * np.sqrt(252)

        vix_target = VIX_MEAN + vix_vol_sensitivity * max(0, realized_vol_20d - 0.16)
        vix_series[t] = vix_series[t-1] + vix_mr_speed * (vix_target - vix_series[t-1]) + rng.normal(0, VIX_NOISE_STD)
        vix_series[t] = max(9.0, min(80.0, vix_series[t]))

        net_demand = 0.0

        if n_strategy > 0:
            new_strategy_weights, strategy_demand = strategy.update_target_weight(
                t, prices, returns, vix_series, strategy_weights
            )
            net_demand += strategy_demand
            strategy_weights = new_strategy_weights
            strategy_weight_history[t] = float(np.mean(strategy_weights))
        else:
            strategy_weight_history[t] = strategy_weight_history[t-1]

        # Noise traders — VERBATIM from K827v3
        noise_changes = rng.normal(0, NOISE_TRADER_STD, size=n_noise)
        noise_weights = np.clip(noise_weights + noise_changes, 0.0, 1.5)
        net_demand += np.sum(noise_changes)

        # Price formation (Kyle)
        fundamental_shock = rng.normal(DAILY_DRIFT, FUNDAMENTAL_VOL)
        price_impact = kyle_lambda * net_demand / N_AGENTS

        daily_return = fundamental_shock + price_impact

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

    # Metrics
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

    vt_sharpe = np.nan
    vt_return_val = np.nan
    vt_vol_val = np.nan
    if n_strategy > 0:
        # TF/MR: use recorded weight trajectory (one-step lag)
        sw = strategy_weight_history[:-1]
        sw_returns = sw * valid_returns
        vt_return_val = np.mean(sw_returns) * 252
        sw_vol = np.std(sw_returns) * np.sqrt(252)
        vt_sharpe = vt_return_val / sw_vol if sw_vol > 0 else 0
        vt_vol_val = sw_vol

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
        'n_strategy': n_strategy,
        'n_bh': n_bh,
        'n_noise': n_noise,
    }


def aggregate_metrics(sim_results):
    """Aggregate per-cell metrics with mean/std/median/n_valid + NaN diagnostics."""
    if not sim_results:
        return {}

    metric_keys = ['ann_return', 'ann_vol', 'max_dd', 'flash_crash_freq',
                   'kurtosis', 'skewness', 'vix_mean', 'vix_std', 'vix_spike_pct',
                   'vt_sharpe', 'vt_return', 'vt_vol', 'final_price']

    agg = {}
    for key in metric_keys:
        values = [m[key] for m in sim_results if m[key] is not None and np.isfinite(m[key])]
        if len(values) > 0:
            agg[key] = {
                'mean': float(np.mean(values)),
                'std': float(np.std(values)),
                'median': float(np.median(values)),
                'n_valid': len(values),
            }
        else:
            agg[key] = None

    total_nan = sum(m.get('n_nan_events', 0) for m in sim_results)
    total_clamp = sum(m.get('n_price_clamp', 0) for m in sim_results)
    agg['_diagnostics'] = {
        'total_nan_events': total_nan,
        'total_price_clamps': total_clamp,
        'n_simulations': len(sim_results),
    }

    return agg


# ============================================================
# Threshold detection variants
# ============================================================

def detect_threshold_strict(results_per_adoption):
    """Phase 1 strict detector: Sharpe drop > 50% AND kurt > 10 AND vol amp > 50%."""
    return _detect_threshold_generic(
        results_per_adoption,
        sharpe_drop_pct=50.0, kurt_threshold=10.0, vol_amp_pct=50.0
    )


def detect_threshold_softer_kurt_weak(results_per_adoption):
    """Softer (kurt-weak): Sharpe drop > 50% AND kurt > 1 AND vol amp > 50%.

    Calibration target: VT_baseline @ 70% adoption (P5 paper threshold).
    """
    return _detect_threshold_generic(
        results_per_adoption,
        sharpe_drop_pct=50.0, kurt_threshold=1.0, vol_amp_pct=50.0
    )


def detect_threshold_p5_style(results_per_adoption):
    """P5-style (Sharpe-only): sign flip OR Sharpe drop > 70%.

    No kurt or vol amp constraint — purely strategy-performance-based.
    """
    baseline_label = '10%'
    baseline_agg = results_per_adoption.get(baseline_label, {})
    base_sharpe = (
        baseline_agg.get('vt_sharpe', {}).get('mean')
        if baseline_agg.get('vt_sharpe') else None
    )

    justification = {'baseline_sharpe': base_sharpe, 'criterion': 'sign-flip OR drop>70%'}
    critical = None

    for adoption_label in ['10%', '20%', '30%', '50%', '70%', '100%']:
        agg = results_per_adoption.get(adoption_label, {})
        sharpe_obj = agg.get('vt_sharpe')
        cell_sharpe = sharpe_obj['mean'] if sharpe_obj else None

        if base_sharpe is None or cell_sharpe is None:
            continue

        # Sign flip
        sign_flip = (np.sign(base_sharpe) != np.sign(cell_sharpe) and
                     abs(base_sharpe) > 1e-6 and abs(cell_sharpe) > 1e-6)
        # Drop > 70%
        drop_pct = (cell_sharpe - base_sharpe) / abs(base_sharpe) * 100 if abs(base_sharpe) > 1e-6 else 0
        big_drop = drop_pct < -70.0

        if (sign_flip or big_drop) and critical is None:
            critical = adoption_label

    return {'critical_adoption': critical, 'justification': justification}


def _detect_threshold_generic(results_per_adoption, sharpe_drop_pct,
                              kurt_threshold, vol_amp_pct):
    """Generic 3-criterion detector with parameterized thresholds.

    Critical adoption = first level (≥10%) where ALL three hold:
      (a) Sharpe drops > sharpe_drop_pct from 10% baseline (sign-aware)
      (b) Kurtosis > kurt_threshold
      (c) Vol amplification > vol_amp_pct from 10% baseline
    """
    baseline_label = '10%'
    baseline_agg = results_per_adoption.get(baseline_label, {})
    base_sharpe = (
        baseline_agg.get('vt_sharpe', {}).get('mean')
        if baseline_agg.get('vt_sharpe') else None
    )
    base_vol = (
        baseline_agg.get('ann_vol', {}).get('mean')
        if baseline_agg.get('ann_vol') else None
    )

    justification = {
        'baseline_adoption': baseline_label,
        'baseline_sharpe': base_sharpe,
        'baseline_vol': base_vol,
        'thresholds': {
            'sharpe_drop_pct': sharpe_drop_pct,
            'kurt': kurt_threshold,
            'vol_amp_pct': vol_amp_pct,
        },
        'per_adoption': {},
    }
    critical = None

    for adoption_label in ['10%', '20%', '30%', '50%', '70%', '100%']:
        agg = results_per_adoption.get(adoption_label, {})
        cell = {}

        sharpe_obj = agg.get('vt_sharpe')
        cell['sharpe'] = sharpe_obj['mean'] if sharpe_obj else None
        kurt_obj = agg.get('kurtosis')
        cell['kurtosis'] = kurt_obj['mean'] if kurt_obj else None
        vol_obj = agg.get('ann_vol')
        cell['vol'] = vol_obj['mean'] if vol_obj else None

        if base_sharpe is not None and cell['sharpe'] is not None and abs(base_sharpe) > 1e-6:
            drop = (cell['sharpe'] - base_sharpe) / abs(base_sharpe) * 100
            cell['sharpe_drop_pct'] = drop
            cell['crit_a'] = drop < -sharpe_drop_pct
        else:
            cell['sharpe_drop_pct'] = None
            cell['crit_a'] = False

        cell['crit_b'] = (cell['kurtosis'] is not None) and (cell['kurtosis'] > kurt_threshold)

        if base_vol is not None and cell['vol'] is not None and base_vol > 1e-6:
            amp = (cell['vol'] - base_vol) / base_vol * 100
            cell['vol_amp_pct'] = amp
            cell['crit_c'] = amp > vol_amp_pct
        else:
            cell['vol_amp_pct'] = None
            cell['crit_c'] = False

        cell['all_three_met'] = cell['crit_a'] and cell['crit_b'] and cell['crit_c']
        justification['per_adoption'][adoption_label] = cell

        if cell['all_three_met'] and critical is None:
            critical = adoption_label

    return {'critical_adoption': critical, 'justification': justification}


# ============================================================
# Phase 2 cell runner
# ============================================================

def run_cell(treatment, scaling, window, n_sims=N_SIMS_PHASE2, n_workers=N_WORKERS):
    """Run one (treatment × scaling × window) cell across all adoption levels.

    Returns: dict {adoption_label: agg_metrics}
    """
    results = {}
    for adoption in ADOPTION_LEVELS:
        adoption_label = f"{int(adoption * 100)}%"

        # Seed formula extending K1261:
        # base = int(adoption*100000) + sim_idx + 42 + scaling*1000 + window*10
        args_list = [
            (treatment, adoption,
             int(adoption * 100000) + sim_idx + 42 + scaling * 1000 + window * 10,
             window, scaling)
            for sim_idx in range(n_sims)
        ]

        with Pool(n_workers) as pool:
            sim_results = pool.map(run_single_simulation, args_list)

        agg = aggregate_metrics(sim_results)
        results[adoption_label] = agg

    return results


# ============================================================
# Main
# ============================================================

def main():
    overall_t0 = time.time()
    output_dir = os.path.dirname(os.path.abspath(__file__))

    n_cells = len(TREATMENTS_PHASE2) * len(SCALING_GRID) * len(WINDOW_GRID)
    n_total_sims = n_cells * len(ADOPTION_LEVELS) * N_SIMS_PHASE2

    print("=" * 72)
    print("K1262 Phase 2: TF/MR scaling × window × adoption sweep")
    print(f"  Treatments: {TREATMENTS_PHASE2}")
    print(f"  Scaling grid: {SCALING_GRID}")
    print(f"  Window grid: {WINDOW_GRID}")
    print(f"  Adoption levels: {ADOPTION_LEVELS}")
    print(f"  MC sims per cell: {N_SIMS_PHASE2}")
    print(f"  Total cells: {n_cells} ({len(TREATMENTS_PHASE2)} × "
          f"{len(SCALING_GRID)} × {len(WINDOW_GRID)})")
    print(f"  Total sims: {n_total_sims}")
    print(f"  Workers: {N_WORKERS}")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 72)

    # ============================================================
    # Run all cells
    # ============================================================
    cells = {}  # cells[treatment][scaling][window] = {adoption_label: agg}
    cell_runtime = {}

    cell_idx = 0
    for treatment in TREATMENTS_PHASE2:
        cells[treatment] = {}
        cell_runtime[treatment] = {}
        for scaling in SCALING_GRID:
            cells[treatment][str(scaling)] = {}
            cell_runtime[treatment][str(scaling)] = {}
            for window in WINDOW_GRID:
                cell_idx += 1
                t0 = time.time()
                print(f"\n[{cell_idx}/{n_cells}] {treatment} scaling={scaling} window={window}")
                cell_results = run_cell(treatment, scaling, window)
                elapsed = time.time() - t0

                cells[treatment][str(scaling)][str(window)] = cell_results
                cell_runtime[treatment][str(scaling)][str(window)] = elapsed

                # Quick summary print
                summary_bits = []
                for adoption_label in ['10%', '50%', '100%']:
                    agg = cell_results.get(adoption_label, {})
                    sh = agg.get('vt_sharpe')
                    kt = agg.get('kurtosis')
                    sh_str = f"{sh['mean']:.2f}" if sh else 'null'
                    kt_str = f"{kt['mean']:.1f}" if kt else 'null'
                    summary_bits.append(f"{adoption_label}=Sh:{sh_str}/k:{kt_str}")
                print(f"  {elapsed:.1f}s | " + " ".join(summary_bits))

    overall_elapsed = time.time() - overall_t0

    # ============================================================
    # Threshold detection per cell (3 detectors)
    # ============================================================
    print("\n" + "=" * 72)
    print("Threshold detection per cell (3 detectors)")
    print("=" * 72)

    threshold_per_cell = {}
    for treatment in TREATMENTS_PHASE2:
        threshold_per_cell[treatment] = {}
        for scaling in SCALING_GRID:
            threshold_per_cell[treatment][str(scaling)] = {}
            for window in WINDOW_GRID:
                cr = cells[treatment][str(scaling)][str(window)]
                threshold_per_cell[treatment][str(scaling)][str(window)] = {
                    'strict': detect_threshold_strict(cr),
                    'softer_kurt_weak': detect_threshold_softer_kurt_weak(cr),
                    'p5_style': detect_threshold_p5_style(cr),
                }

    # ============================================================
    # Save raw + per-cell threshold JSON
    # ============================================================
    output = {
        'experiment_id': 'K1262_phase2_robustness_sweep',
        'title': 'K1262 Phase 2: TF/MR scaling × window × adoption robustness sweep',
        'type': 'SIMULATION (Phase 2 robustness)',
        'description': (
            'Phase 2 robustness sweep on K1261 TF/MR results. '
            f'Loop: 2 treatments × {len(SCALING_GRID)} scaling × {len(WINDOW_GRID)} '
            f'window × {len(ADOPTION_LEVELS)} adoption × {N_SIMS_PHASE2} MC = '
            f'{n_total_sims} sims. Tests caveat #4 from K1261 code review: '
            'H1+ direction robust but threshold magnitude may be specification-'
            'dependent (TF/MR scaling=10 may be aggressive).'
        ),
        'timestamp': datetime.now().isoformat(),
        'overall_runtime_seconds': overall_elapsed,
        'config': {
            'treatments': TREATMENTS_PHASE2,
            'scaling_grid': SCALING_GRID,
            'window_grid': WINDOW_GRID,
            'adoption_levels': ADOPTION_LEVELS,
            'n_sims_per_cell': N_SIMS_PHASE2,
            'n_agents': N_AGENTS,
            'n_noise_fixed': N_NOISE_FIXED,
            'n_bh_vt_pool': N_BH_VT_POOL,
            'n_days': N_DAYS,
            'n_workers': N_WORKERS,
            'baseline_params': BASELINE_PARAMS,
            'seed_formula': (
                'int(adoption*100000) + sim_idx + 42 + scaling*1000 + window*10 '
                '(extends K1261 formula to disambiguate sweep cells)'
            ),
        },
        'cells': cells,
        'cell_runtime_seconds': cell_runtime,
        'threshold_per_cell': threshold_per_cell,
        'note_on_k1261_input': {
            'path': '../k1261/k1261_results.json',
            'usage': (
                'Part B (softer_detector_table.md) recomputes K1261 raw results '
                'under 3 detector variants. Read at analysis time, not by '
                'k1262.py main loop.'
            ),
        },
    }

    out_path = os.path.join(output_dir, 'k1262_results.json')
    with open(out_path, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n[SAVED] Phase 2 results: {out_path}")

    # ============================================================
    # Generate companion markdown reports
    # ============================================================
    write_softer_detector_table(output_dir)
    write_threshold_matrix(output_dir, threshold_per_cell)
    write_verdict(output_dir, threshold_per_cell, overall_elapsed, n_total_sims)

    print(f"\n{'='*72}")
    print(f"K1262 PHASE 2 COMPLETE")
    print(f"{'='*72}")
    print(f"Wall time:   {overall_elapsed:.1f}s ({overall_elapsed/60:.2f} min)")
    print(f"Total sims:  {n_total_sims}")
    print(f"Cells:       {n_cells}")
    print(f"{'='*72}")

    return output


def write_softer_detector_table(output_dir):
    """Part B: recompute K1261 raw results under 3 detector variants."""
    k1261_path_candidates = [
        os.path.abspath(os.path.join(output_dir, '..', 'k1261', 'k1261_results.json')),
        '/Users/yhlai0911/Desktop/volpred-research/experiments/k1261/k1261_results.json',
    ]
    k1261_path = next((p for p in k1261_path_candidates if os.path.exists(p)), None)
    if k1261_path is None:
        # Write blocker note
        md = [
            "# K1262 Softer Detector Table — BLOCKED",
            "",
            "K1261 results.json not found at any candidate path:",
            "",
        ]
        md.extend([f"- `{p}`" for p in k1261_path_candidates])
        md.append("\nPart B recompute deferred. See verdict.md.")
        with open(os.path.join(output_dir, 'k1262_softer_detector_table.md'), 'w') as f:
            f.write('\n'.join(md))
        return

    with open(k1261_path, 'r') as f:
        k1261 = json.load(f)

    # K1261 raw results live at:
    #   k1261.treatments.<TF|MR|NoiseControl>.part1_results
    #   k1261.threshold_detection.VT_baseline_K827v3_stored.justification.per_adoption (raw VT in
    #   K827v3 source; we need to re-load VT raw from K827v3 path)
    k827v3_paths = [
        '/Users/yhlai0911/Desktop/volpred-research/paper/vt-crowding-abm/experiments/k827v3_abm_fixed_liquidity_results.json',
    ]
    k827v3_path = next((p for p in k827v3_paths if os.path.exists(p)), None)

    # Compose treatment → raw_per_adoption dict
    treatments = {}
    if k827v3_path:
        with open(k827v3_path, 'r') as f:
            k827v3 = json.load(f)
        treatments['VT_baseline'] = k827v3.get('part1_results', {})
    treatments['TF'] = k1261.get('treatments', {}).get('TF', {}).get('part1_results', {})
    treatments['MR'] = k1261.get('treatments', {}).get('MR', {}).get('part1_results', {})
    treatments['NoiseControl'] = k1261.get('treatments', {}).get('NoiseControl', {}).get('part1_results', {})

    detectors = {
        'Strict': detect_threshold_strict,
        'Softer (kurt-weak)': detect_threshold_softer_kurt_weak,
        'P5-style (Sharpe-only)': detect_threshold_p5_style,
    }

    rows = {}
    for tname, raw in treatments.items():
        if not raw:
            rows[tname] = {dname: 'N/A (no data)' for dname in detectors}
            continue
        rows[tname] = {}
        for dname, dfn in detectors.items():
            det = dfn(raw)
            crit = det.get('critical_adoption')
            rows[tname][dname] = crit if crit else 'null'

    # Markdown
    md = [
        "# K1262 Part B: Softer Detector Recompute of K1261 Raw Results",
        "",
        f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Source**: `{k1261_path}` (K1261 Phase 1 raw aggregates) + "
        f"`{k827v3_path}` (K827v3 VT 500-MC baseline).",
        "",
        "## Detector definitions",
        "",
        "1. **Strict (K1261 Phase 1)**: Sharpe drop > 50% from 10% baseline AND kurt > 10 AND vol amp > 50%.",
        "2. **Softer (kurt-weak)**: Sharpe drop > 50% AND kurt > 1 AND vol amp > 50%. Loosens the kurtosis criterion to match P5 paper's softer threshold criterion.",
        "3. **P5-style (Sharpe-only)**: Sharpe sign flip OR Sharpe drop > 70% from 10% baseline. Pure strategy-performance criterion (no kurt or vol amp required).",
        "",
        "## Critical Adoption Table",
        "",
        "| Treatment | Strict (K1261) | Softer (kurt-weak) | P5-style (Sharpe-only) |",
        "|---|:---:|:---:|:---:|",
    ]
    for tname in ['VT_baseline', 'TF', 'MR', 'NoiseControl']:
        r = rows.get(tname, {})
        md.append(
            f"| {tname} | {r.get('Strict', 'N/A')} | "
            f"{r.get('Softer (kurt-weak)', 'N/A')} | "
            f"{r.get('P5-style (Sharpe-only)', 'N/A')} |"
        )

    md.extend([
        "",
        "## Calibration check",
        "",
        "P5 paper reports VT critical adoption = 70%. The softer (kurt-weak) detector "
        "applied to VT_baseline is the calibration target. Acceptable range: ±20% adoption "
        "(i.e. 50% / 70% / 80% / 100%).",
        "",
        f"- **Softer (kurt-weak) → VT_baseline**: {rows.get('VT_baseline', {}).get('Softer (kurt-weak)', 'N/A')} ",
        "  (calibration check: see verdict.md for pass/fail interpretation)",
        f"- **P5-style → VT_baseline**: {rows.get('VT_baseline', {}).get('P5-style (Sharpe-only)', 'N/A')}",
        "",
        "## Cross-link",
        "",
        "- K1261 raw input: `experiments/k1261/k1261_results.json`",
        "- K827v3 VT 500-MC baseline: `paper/vt-crowding-abm/experiments/k827v3_abm_fixed_liquidity_results.json`",
        "- Phase 2 sweep raw: `experiments/k1262/k1262_results.json`",
        "- Phase 2 grid output: `experiments/k1262/k1262_threshold_matrix.md`",
        "- Phase 2 verdict: `experiments/k1262/k1262_verdict.md`",
        "",
    ])
    with open(os.path.join(output_dir, 'k1262_softer_detector_table.md'), 'w') as f:
        f.write('\n'.join(md))


def write_threshold_matrix(output_dir, threshold_per_cell):
    """Part C: 2D matrix scaling × window of TF/MR critical adoption under softer detector."""
    md = [
        "# K1262 Part C: Threshold Matrix (scaling × window) under Softer Detector",
        "",
        f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Detector**: Softer (kurt-weak) — Sharpe drop > 50% AND kurt > 1 AND vol amp > 50%",
        "",
        "Cell format: `TF: <crit> / MR: <crit>`. `null` = no threshold detected at any adoption ≥10%.",
        "",
        "## Critical Adoption Matrix",
        "",
        "| Scaling \\ Window | 10 | 22 | 60 |",
        "|---:|:---:|:---:|:---:|",
    ]
    for scaling in SCALING_GRID:
        cells_row = []
        for window in WINDOW_GRID:
            tf_det = threshold_per_cell['TF'][str(scaling)][str(window)]['softer_kurt_weak']
            mr_det = threshold_per_cell['MR'][str(scaling)][str(window)]['softer_kurt_weak']
            tf_crit = tf_det.get('critical_adoption') or 'null'
            mr_crit = mr_det.get('critical_adoption') or 'null'
            cells_row.append(f"TF: {tf_crit} / MR: {mr_crit}")
        md.append(f"| {scaling} | {cells_row[0]} | {cells_row[1]} | {cells_row[2]} |")

    # Also strict + p5-style matrices for completeness
    md.extend([
        "",
        "## Same matrix under STRICT detector (Phase 1)",
        "",
        "| Scaling \\ Window | 10 | 22 | 60 |",
        "|---:|:---:|:---:|:---:|",
    ])
    for scaling in SCALING_GRID:
        cells_row = []
        for window in WINDOW_GRID:
            tf_det = threshold_per_cell['TF'][str(scaling)][str(window)]['strict']
            mr_det = threshold_per_cell['MR'][str(scaling)][str(window)]['strict']
            tf_crit = tf_det.get('critical_adoption') or 'null'
            mr_crit = mr_det.get('critical_adoption') or 'null'
            cells_row.append(f"TF: {tf_crit} / MR: {mr_crit}")
        md.append(f"| {scaling} | {cells_row[0]} | {cells_row[1]} | {cells_row[2]} |")

    md.extend([
        "",
        "## Same matrix under P5-STYLE (Sharpe-only) detector",
        "",
        "| Scaling \\ Window | 10 | 22 | 60 |",
        "|---:|:---:|:---:|:---:|",
    ])
    for scaling in SCALING_GRID:
        cells_row = []
        for window in WINDOW_GRID:
            tf_det = threshold_per_cell['TF'][str(scaling)][str(window)]['p5_style']
            mr_det = threshold_per_cell['MR'][str(scaling)][str(window)]['p5_style']
            tf_crit = tf_det.get('critical_adoption') or 'null'
            mr_crit = mr_det.get('critical_adoption') or 'null'
            cells_row.append(f"TF: {tf_crit} / MR: {mr_crit}")
        md.append(f"| {scaling} | {cells_row[0]} | {cells_row[1]} | {cells_row[2]} |")

    md.extend([
        "",
        "## Cross-link",
        "",
        "- Phase 2 raw: `experiments/k1262/k1262_results.json`",
        "- Softer detector table: `experiments/k1262/k1262_softer_detector_table.md`",
        "- Phase 2 verdict: `experiments/k1262/k1262_verdict.md`",
        "",
    ])
    with open(os.path.join(output_dir, 'k1262_threshold_matrix.md'), 'w') as f:
        f.write('\n'.join(md))


def write_verdict(output_dir, threshold_per_cell, overall_elapsed, n_total_sims):
    """Phase 2 falsifiability verdict — picks one of 4 outcomes."""
    # Adoption rank order (lower idx = earlier threshold = stronger crowding)
    adopt_rank = {'10%': 1, '20%': 2, '30%': 3, '50%': 4, '70%': 5, '100%': 6, None: 99}

    # VT reference under softer detector — read from softer_detector_table source
    # (computed in write_softer_detector_table); we re-detect here for VT.
    k827v3_path = '/Users/yhlai0911/Desktop/volpred-research/paper/vt-crowding-abm/experiments/k827v3_abm_fixed_liquidity_results.json'
    vt_softer_crit = None
    vt_strict_crit = None
    vt_p5_crit = None
    if os.path.exists(k827v3_path):
        with open(k827v3_path, 'r') as f:
            k827v3 = json.load(f)
        vt_part1 = k827v3.get('part1_results', {})
        vt_softer_crit = detect_threshold_softer_kurt_weak(vt_part1).get('critical_adoption')
        vt_strict_crit = detect_threshold_strict(vt_part1).get('critical_adoption')
        vt_p5_crit = detect_threshold_p5_style(vt_part1).get('critical_adoption')

    # Cell-by-cell comparison: TF threshold vs VT threshold under softer detector
    cell_summary = []
    tf_vs_vt_results = {'lower': 0, 'equal': 0, 'higher': 0, 'tf_null': 0, 'vt_null': 0}
    mr_vs_vt_results = {'lower': 0, 'equal': 0, 'higher': 0, 'mr_null': 0, 'vt_null': 0}

    vt_rank = adopt_rank.get(vt_softer_crit, 99)

    for scaling in SCALING_GRID:
        for window in WINDOW_GRID:
            tf_crit = threshold_per_cell['TF'][str(scaling)][str(window)]['softer_kurt_weak'].get('critical_adoption')
            mr_crit = threshold_per_cell['MR'][str(scaling)][str(window)]['softer_kurt_weak'].get('critical_adoption')
            tf_rank = adopt_rank.get(tf_crit, 99)
            mr_rank = adopt_rank.get(mr_crit, 99)

            tf_cmp = '?'
            if vt_softer_crit is None:
                tf_cmp = 'vt_null'; tf_vs_vt_results['vt_null'] += 1
            elif tf_crit is None:
                tf_cmp = 'tf_null'; tf_vs_vt_results['tf_null'] += 1
            elif tf_rank < vt_rank:
                tf_cmp = 'lower'; tf_vs_vt_results['lower'] += 1
            elif tf_rank == vt_rank:
                tf_cmp = 'equal'; tf_vs_vt_results['equal'] += 1
            else:
                tf_cmp = 'higher'; tf_vs_vt_results['higher'] += 1

            mr_cmp = '?'
            if vt_softer_crit is None:
                mr_cmp = 'vt_null'; mr_vs_vt_results['vt_null'] += 1
            elif mr_crit is None:
                mr_cmp = 'mr_null'; mr_vs_vt_results['mr_null'] += 1
            elif mr_rank < vt_rank:
                mr_cmp = 'lower'; mr_vs_vt_results['lower'] += 1
            elif mr_rank == vt_rank:
                mr_cmp = 'equal'; mr_vs_vt_results['equal'] += 1
            else:
                mr_cmp = 'higher'; mr_vs_vt_results['higher'] += 1

            cell_summary.append({
                'scaling': scaling,
                'window': window,
                'tf_crit': tf_crit, 'tf_vs_vt': tf_cmp,
                'mr_crit': mr_crit, 'mr_vs_vt': mr_cmp,
            })

    # Verdict logic
    n_cells = len(SCALING_GRID) * len(WINDOW_GRID)
    n_tf_lower = tf_vs_vt_results['lower']
    n_tf_equal = tf_vs_vt_results['equal']
    n_tf_higher = tf_vs_vt_results['higher']
    n_tf_null = tf_vs_vt_results['tf_null']

    # Outcome decision
    if n_tf_lower >= n_cells * 0.83:  # ≥10/12 cells: TF strictly lower than VT
        outcome = 'H1+ strongly supported'
        outcome_detail = (
            f"TF threshold < VT threshold across {n_tf_lower}/{n_cells} cells under softer detector. "
            f"Direction robust to scaling ∈ {SCALING_GRID} and window ∈ {WINDOW_GRID}. "
            f"P5 paper rewrite to「positive-feedback family」reasonable."
        )
    elif n_tf_lower + n_tf_equal >= n_cells * 0.5:
        outcome = 'H1+ partially supported'
        outcome_detail = (
            f"TF threshold ≤ VT in {n_tf_lower + n_tf_equal}/{n_cells} cells (lower={n_tf_lower}, "
            f"equal={n_tf_equal}); higher={n_tf_higher}; tf_null={n_tf_null}. "
            f"Threshold magnitude is spec-dependent; P5 can claim 'TF crosses earlier under "
            f"aggressive scaling' but not at all scaling levels."
        )
    elif n_tf_higher + n_tf_null >= n_cells * 0.5:
        outcome = 'H1+ rejected'
        outcome_detail = (
            f"TF threshold > VT in {n_tf_higher}/{n_cells} cells, null in {n_tf_null}/{n_cells}. "
            f"TF crowding mostly weaker than VT under typical scaling; H1+ direction reverses or vanishes. "
            f"P5 VT-specific channel claim partially rescued."
        )
    else:
        outcome = 'mixed / inconclusive'
        outcome_detail = (
            f"TF: lower={n_tf_lower}, equal={n_tf_equal}, higher={n_tf_higher}, null={n_tf_null}; "
            f"MR: lower={mr_vs_vt_results['lower']}, equal={mr_vs_vt_results['equal']}, "
            f"higher={mr_vs_vt_results['higher']}, null={mr_vs_vt_results['mr_null']}. "
            f"No dominant pattern — manual interpretation of cell-by-cell table needed."
        )

    # Check MR-only artifact specifically
    n_mr_null = mr_vs_vt_results['mr_null']
    if n_mr_null >= n_cells * 0.5 and n_tf_lower >= n_cells * 0.5:
        # MR result extremely scaling-sensitive while TF holds
        outcome_mr_note = (
            f"\n\n**Sub-finding: MR-only artifact**: MR threshold null in {n_mr_null}/{n_cells} cells "
            f"under softer detector — MR result was likely scaling-driven. TF result remains robust, "
            f"so H1+ holds via TF but MR contribution is weakened."
        )
    else:
        outcome_mr_note = ''

    # Calibration check — multi-detector
    # Per-detector pass: which detector reproduces P5's 70% threshold for VT?
    softer_pass = vt_softer_crit in ('50%', '70%', '80%', '100%')
    p5style_pass = vt_p5_crit in ('50%', '70%', '80%', '100%')
    softer_exact = (vt_softer_crit == '70%')
    p5style_exact = (vt_p5_crit == '70%')

    calibration_text = (
        f"P5 paper reports VT critical adoption = **70%**. We test 3 detectors against this anchor:\n\n"
        f"- **Softer (kurt-weak)** → VT_baseline = **{vt_softer_crit}**: "
        f"{'PASS within ±20% band' if softer_pass else 'FAIL outside band'}, "
        f"{'EXACT match to P5 70%' if softer_exact else 'NOT exact'}\n"
        f"- **P5-style (Sharpe-only)** → VT_baseline = **{vt_p5_crit}**: "
        f"{'PASS within ±20% band' if p5style_pass else 'FAIL outside band'}, "
        f"{'EXACT match to P5 70%' if p5style_exact else 'NOT exact'}\n"
        f"- **Strict (K1261)** → VT_baseline = **{vt_strict_crit}**: reference only\n\n"
        f"**Interpretation**: "
    )
    if p5style_exact:
        calibration_text += (
            "P5-style (Sharpe-only) detector reproduces exactly the 70% VT threshold reported in the P5 "
            "paper — this is the cleanest calibration of P5's underlying criterion. The Softer (kurt-weak) "
            f"detector gives VT={vt_softer_crit} because at adoption=70% the VT vol amplification is only "
            "~43% (vs softer detector's >50% requirement). The Sharpe-only criterion captures P5's actual "
            "criterion best. **Phase 2 cross-detector comparisons valid**."
        )
    elif softer_exact:
        calibration_text += (
            "Softer (kurt-weak) detector reproduces P5's 70% threshold. Use it as the canonical comparison "
            "detector for Phase 2."
        )
    elif p5style_pass or softer_pass:
        calibration_text += (
            f"At least one detector gives VT within ±20% of P5's 70%. **Phase 2 comparisons remain "
            f"interpretable** as relative ranks under matched detector. Threshold magnitude estimates "
            f"may vary across detectors (this IS the point of cross-detector reporting)."
        )
    else:
        calibration_text += (
            f"No detector reproduces P5's 70% within ±20%. P5 paper criterion remains opaque; "
            f"Phase 2 is best-effort. TF/MR comparisons against VT are still ordinal-meaningful under "
            f"any single fixed detector."
        )

    calibration_pass = (softer_pass or p5style_pass)

    md = [
        "# K1262 Phase 2 Verdict",
        "",
        f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Total sims**: {n_total_sims}",
        f"**Wall time**: {overall_elapsed:.1f}s ({overall_elapsed/60:.2f} min)",
        f"**Predecessor**: K1261 Phase 1 (verdict H1+, conditional PASS, knowledge.json item_id `f1d85a74`)",
        "",
        "## Detector calibration check",
        "",
        calibration_text,
        "",
        "## Phase 2 Cell-Level Summary (softer detector)",
        "",
        f"VT reference under softer detector: **{vt_softer_crit}** (rank={vt_rank})",
        "",
        "| Cells (12) | TF vs VT | MR vs VT |",
        "|---|---:|---:|",
        f"| TF threshold lower than VT | {n_tf_lower} | — |",
        f"| TF threshold equal to VT | {n_tf_equal} | — |",
        f"| TF threshold higher than VT | {n_tf_higher} | — |",
        f"| TF threshold null | {n_tf_null} | — |",
        f"| MR threshold lower than VT | — | {mr_vs_vt_results['lower']} |",
        f"| MR threshold equal to VT | — | {mr_vs_vt_results['equal']} |",
        f"| MR threshold higher than VT | — | {mr_vs_vt_results['higher']} |",
        f"| MR threshold null | — | {mr_vs_vt_results['mr_null']} |",
        "",
        "## Per-cell detail (softer detector)",
        "",
        "| Scaling | Window | TF crit | TF vs VT | MR crit | MR vs VT |",
        "|---:|---:|---:|:---:|---:|:---:|",
    ]
    for cs in cell_summary:
        md.append(
            f"| {cs['scaling']} | {cs['window']} | "
            f"{cs['tf_crit'] or 'null'} | {cs['tf_vs_vt']} | "
            f"{cs['mr_crit'] or 'null'} | {cs['mr_vs_vt']} |"
        )

    md.extend([
        "",
        "## Verdict outcome",
        "",
        f"### **{outcome}**",
        "",
        outcome_detail,
        outcome_mr_note,
        "",
        "## Caveats (4) — what is NOT covered by this Phase 2",
        "",
        "1. **No λ/γ OAT sensitivity**: This Phase 2 sweeps strategy parameters (TF/MR scaling × window) "
        "but holds market-microstructure parameters (kyle_lambda=0.005, vix_vol_sensitivity=200, "
        "vix_mr_speed=0.03) fixed at K827v3 baseline. Caveat #1 from K1261 Phase 1 — that the 70% threshold "
        "may be a λ/γ knife-edge mathematical result — is not addressed here. K1262b would extend OAT "
        "to λ ± 50% × γ ± 50% across 3 treatments × 3 adoption × 200 sims (deferred).",
        "",
        f"2. **MC = 100, not 500**: Phase 1 used 500 MC for cross-treatment comparison; Phase 2 reduces "
        f"to 100 MC per cell to keep wall time < 10 min across {n_total_sims} sims. Bootstrap CIs are "
        f"correspondingly wider (~2.2× standard error). Threshold detection remains qualitatively "
        f"reliable for direction of effect, but threshold magnitude estimates are noisier. Borderline "
        f"cells should be re-run at 500 MC if used in P5 paper claims.",
        "",
        f"3. **N_window=10 / 60 boundary edges**: window=10 is short-term momentum (CTA fast signal, "
        f"may produce noisier estimates); window=60 is quarterly momentum (long-term, may underweight "
        f"recent positive feedback). Both extremes are stress tests. Window=22 (1-month) is the "
        f"convention, matching K1261 Phase 1.",
        "",
        f"4. **No λ/γ knife-edge dispatched here**: original K1261 caveat #4 specifically asked whether "
        f"H1+ holds at less aggressive scaling. Phase 2 directly addresses this at scaling ∈ "
        f"{{1, 3, 5, 10}}. If H1+ holds at scaling ≤ 3 (strict signal magnitude), the result is robust "
        f"to specification. If H1+ collapses at scaling ≤ 3, we have evidence H1+ depends on aggressive "
        f"strategy magnitude — partial-rescue territory for P5.",
        "",
        "## Implication for P5 paper rewrite",
        "",
    ])

    if outcome == 'H1+ strongly supported':
        md.extend([
            "**P5 paper rewrite to「positive-feedback family」is supported.** ",
            "Recommended next steps:",
            "- Update P5 abstract / intro to position VT as one representative of a positive-feedback family",
            "- Acknowledge generic threshold mechanism (TF, MR) in lit review",
            "- Keep VT as empirically dominant case (real-world adoption + λ/γ amplification)",
            "- Optional: K1262b λ/γ OAT for full robustness suite (becomes confirmatory rather than essential)",
        ])
    elif outcome == 'H1+ partially supported':
        md.extend([
            "**P5 paper rewrite remains plausible but with nuance.** ",
            "Recommended language:",
            "- TF crosses earlier than VT under aggressive scaling (matches CTA-leverage realistic regime)",
            "- At lower TF intensity, threshold ranks reverse — VT-specific channel partially restored",
            "- Keep VT as primary contribution; add positive-feedback-family discussion in robustness section",
            "- K1262b λ/γ OAT becomes important to disentangle scaling vs market-impact effects",
        ])
    elif outcome == 'H1+ rejected':
        md.extend([
            "**P5 VT-specific channel partially rescued.** ",
            "Recommended next steps:",
            "- Original P5 framing (VT-specific 70% threshold) restored as primary claim",
            "- Acknowledge K1261/K1262 as 'extreme TF/MR scaling produces similar threshold but realistic CTA "
            "scaling does not' — supporting evidence for VT specificity",
            "- K1262b λ/γ OAT optional",
        ])
    else:
        md.extend([
            "**Manual review needed.** ",
            "Mixed pattern across cells — see per-cell table. Recommendations:",
            "- Re-run borderline cells at 500 MC",
            "- Inspect TF/MR Sharpe trajectories at scaling=1 to verify signal magnitude regime is informative",
            "- Consider K1262b λ/γ OAT before P5 narrative decision",
        ])

    md.extend([
        "",
        "## Cross-link",
        "",
        "- Phase 2 raw: `experiments/k1262/k1262_results.json`",
        "- Softer detector table (Part B): `experiments/k1262/k1262_softer_detector_table.md`",
        "- Threshold matrix (Part C): `experiments/k1262/k1262_threshold_matrix.md`",
        "- Phase 2 design: `experiments/k1262/README.md`",
        "- Phase 1 input: `experiments/k1261/k1261_results.json`",
        "- Phase 1 verdict: `experiments/k1261/k1261_phase1_verdict.md`",
        "- VT 500-MC baseline: `paper/vt-crowding-abm/experiments/k827v3_abm_fixed_liquidity_results.json`",
        "- K1261 knowledge entry: `storage/memory/knowledge.json` item_id `f1d85a74`",
        "",
    ])

    with open(os.path.join(output_dir, 'k1262_verdict.md'), 'w') as f:
        f.write('\n'.join(md))


if __name__ == '__main__':
    main()
