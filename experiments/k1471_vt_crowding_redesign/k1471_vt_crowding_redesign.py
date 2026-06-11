"""
K1471: VT-crowding ABM resimulation redesign (vt-crowding-abm v5 blocking fixes)
================================================================================
[提出: 主線程 (experiment_vt_crowding_resimulation_2026_06_11),
 執行: 主線程派遣 agent]
類型：模擬實驗（非實證；K1262b methodology redesign + full rerun）

Motivation
----------
paper/vt-crowding-abm v5_independent（2026-05-21）Codex + Antigravity 雙
REJECT，audit_2026-06-10/audit_findings.json 列 5 HIGH 全為 methodology
重設計需求。本實驗實作 5 項重設計並重跑全 OAT：

(a) EXOGENOUS DETECTOR — 移除 P5-style「先知 70% 閾值」循環校準。
    改為對每 (cell, treatment) 的 sim-level Sharpe-vs-φ 曲線做
    supremum-Wald 單斷點結構檢定（sup over interior split points of a
    Welch-type Wald statistic），p-value 由 label-permutation null
    (B=999, fixed seed) 取得。斷點位置的不確定性由 path-level bootstrap
    (B=500, fixed seed) 重抽 sim-level Sharpe 後重算 argmax 斷點 →
    報 frequency distribution + 80% interval。
    舊 P5-style drop>70% 規則降級為 descriptive robustness grid
    {30%, 50%, 70%}（報告用，非 calibration anchor）。

(b) ACTIVE CONTROL — 新增 RandomRebalance agents（RR_VT / RR_TF / RR_MR）：
    隨機方向、coherent-block 再平衡，|Δw| 分佈（lognormal matched to
    measured mean/std）與再平衡頻率 match 同 cell × 同 adoption 下
    VT/TF/MR treatment 的實際 turnover（兩階段：先跑 treatments 記錄
    turnover stats，再跑 matched controls）。方向 ±1 等機率、由獨立
    RNG stream 抽出，與價格/波動歷史正交。
    舊 NoiseControl（固定 0.5 權重 + 微小擾動）降級為 sanity check。

(c) CI 統一 — 全部 headline CI 改 path-level bootstrap（對 M 條
    sim-level Sharpe / kurtosis / MDD 重抽樣，B=2000, percentile CI）。
    pooled-return 統計量（pooled kurtosis）僅在 cell1 報告，改用
    two-level circular block bootstrap（path 重抽 × path 內 42-day
    circular blocks，B=300）。不再有 iid pooled 1.26M-day CI。

(d) CELL1 GRID 加密 — cell1 adoption grid = {10,30,40,50,60,70,100}%；
    cells 2-5 = {10,30,50,70,100}%（加 50% 提升斷點解析度）。
    每個 threshold 報 path-level bootstrap CI（見 (a)）。

(e) CELL3 處理 — detector applicability gate：若最低 adoption 的
    mean Sharpe < APPLICABILITY_FLOOR (= -0.5，分析前外生設定)，
    detector 回報 'not_applicable_saturated_loss'，不強行宣稱斷點。
    （cell3 λ_high 下 MR baseline Sharpe ≈ -5.56 即此 regime。）

Simulation core 與 K827v3 / K1261 / K1262 / K1262b 完全相同
（VIX feedback、Kyle price impact、noise traders、metrics），確保
重設計差異只來自 detector / control / CI，不來自 market microstructure。

Lookahead 防護（verbatim 繼承）：
  - VT 讀 vix_series[t-1]
  - TF/MR signal 用 returns[t-window:t]（不含 t）
  - RR_* 決策由獨立 RNG，不讀任何價格/波動歷史
所有隨機程序固定 seed（sim seeds 沿用 K1262b formula + treatment offset；
permutation/bootstrap 各有固定 base seed）。

Usage
-----
  smoke (M=50):  uv run python k1471_vt_crowding_redesign.py --n-sims 50 --tag smoke
  full  (M=500): uv run python k1471_vt_crowding_redesign.py --n-sims 500 --tag full

Outputs: k1471_{tag}_results.json (+ threshold table markdown)

References
----------
- paper/vt-crowding-abm/review_history/audit_2026-06-10/audit_findings.json
- experiments/k1262b/k1262b.py（fork source；simulation core verbatim）
- experiments/k1262/k1262.py, experiments/k1261/
- Andrews (1993, Econometrica) sup-Wald structural break
- Politis & Romano (1992) circular block bootstrap
- .claude/rules/experiments.md（lookahead / seed / 三件套）
"""

import argparse
import json
import os
import sys
import time
import warnings
import zlib
from datetime import datetime
from multiprocessing import Pool, cpu_count

import numpy as np
from scipy import stats as sp_stats

warnings.filterwarnings("ignore")

# ============================================================
# Configuration — market microstructure VERBATIM K827v3/K1261/K1262/K1262b
# ============================================================

N_AGENTS = 1000
N_NOISE_FIXED = 200
N_BH_VT_POOL = 800
N_DAYS = 2520

LAMBDA_GRID = {0: 0.0025, 1: 0.005, 2: 0.0075}
GAMMA_GRID = {0: 100.0, 1: 200.0, 2: 300.0}

OAT_CELLS = [
    ('cell1_baseline',    1, 1),
    ('cell2_lambda_low',  0, 1),
    ('cell3_lambda_high', 2, 1),
    ('cell4_gamma_low',   1, 0),
    ('cell5_gamma_high',  1, 2),
]

# (d) densified grid: cell1 gets 40/50/60; others get 50
ADOPTION_GRID_CELL1 = [0.10, 0.30, 0.40, 0.50, 0.60, 0.70, 1.00]
ADOPTION_GRID_OTHER = [0.10, 0.30, 0.50, 0.70, 1.00]

# Treatments: 3 strategies + 3 matched active controls (b) + legacy sanity
STRATEGY_TREATMENTS = ['VT_baseline', 'TF', 'MR']
CONTROL_TREATMENTS = ['RR_VT', 'RR_TF', 'RR_MR']   # matched random-rebalance
SANITY_TREATMENTS = ['NoiseControl']                # legacy, sanity only
ALL_TREATMENTS = STRATEGY_TREATMENTS + CONTROL_TREATMENTS + SANITY_TREATMENTS

TF_SCALING = 10
MOMENTUM_WINDOW = 22
EXPOSURE_CAP = 1.5

INITIAL_PRICE = 100.0
INITIAL_VIX = 15.0
ANNUAL_DRIFT = 0.08
DAILY_DRIFT = ANNUAL_DRIFT / 252
FUNDAMENTAL_VOL = 0.16 / np.sqrt(252)
VIX_MEAN = 18.0
VIX_NOISE_STD = 0.3
VIX_MR_SPEED = 0.03
VT_CAP = 1.5
NOISE_TRADER_STD = 0.02

N_WORKERS = min(cpu_count(), 8)

# --- (a)(e) detector constants — EXOGENOUS, fixed before any analysis ---
DETECTOR_ALPHA = 0.05            # sup-Wald permutation test level
PERMUTATION_B = 999              # permutation replicates
PERM_BASE_SEED = 20260611        # fixed
THRESHOLD_BOOT_B = 500           # path-level bootstrap reps for breakpoint CI
THRESHOLD_BOOT_SEED = 47114711   # fixed
APPLICABILITY_FLOOR = -0.5       # (e) baseline mean Sharpe below this →
                                 # detector not applicable (saturated loss)
ROBUSTNESS_DROP_GRID = [30.0, 50.0, 70.0]  # descriptive only, NOT anchor

# --- (c) CI constants ---
PATH_BOOT_B = 2000               # path-level bootstrap reps for metric CIs
PATH_BOOT_SEED = 13579           # fixed
BLOCK_BOOT_B = 300               # two-level block bootstrap (cell1 pooled)
BLOCK_LEN_DAYS = 42              # ~2 months circular blocks
BLOCK_BOOT_SEED = 24680          # fixed

# --- (b) matched control constants ---
RR_RNG_OFFSET = 10_000_019       # independent RNG stream for RR decisions
TURNOVER_EPS = 1e-12             # |Δw| above this counts as a rebalance day

# Treatment seed offsets (extend K1262b formula so RR_* runs use fresh,
# deterministic, non-overlapping seeds vs their matched treatment)
TREATMENT_SEED_OFFSET = {
    'VT_baseline': 0, 'TF': 0, 'MR': 0, 'NoiseControl': 0,  # = K1262b lineage
    'RR_VT': 7_000_003, 'RR_TF': 7_100_003, 'RR_MR': 7_200_003,
}


# ============================================================
# Strategy agent classes (VT/TF/MR/Noise verbatim from K1262b)
# ============================================================

class StrategyAgent:
    def update_target_weight(self, t, prices, returns, vix_series, current_weights):
        raise NotImplementedError


class VTAgent(StrategyAgent):
    """Volatility-targeting (P5 K827v3 rule). Reads VIX at t-1 — no lookahead."""
    def __init__(self, cap=EXPOSURE_CAP):
        self.cap = cap

    def update_target_weight(self, t, prices, returns, vix_series, current_weights):
        n = len(current_weights)
        if n == 0:
            return current_weights, 0.0
        vt_target = min(12.0 / vix_series[t-1], self.cap)
        demand = (vt_target - current_weights) * n
        return np.full(n, vt_target), float(np.sum(demand))


class TFAgent(StrategyAgent):
    """Trend-following. Signal = returns[t-window:t] (excludes t — no lookahead)."""
    def __init__(self, window=MOMENTUM_WINDOW, scaling=TF_SCALING, cap=EXPOSURE_CAP):
        self.window = window
        self.scaling = scaling
        self.cap = cap

    def update_target_weight(self, t, prices, returns, vix_series, current_weights):
        n = len(current_weights)
        if n == 0:
            return current_weights, 0.0
        momentum = 0.0 if t < self.window + 1 else float(np.sum(returns[t-self.window:t]))
        target = float(np.clip(self.scaling * momentum, -self.cap, self.cap))
        demand = (target - current_weights) * n
        return np.full(n, target), float(np.sum(demand))


class MRAgent(StrategyAgent):
    """Mean-reversion (opposite sign of TF)."""
    def __init__(self, window=MOMENTUM_WINDOW, scaling=TF_SCALING, cap=EXPOSURE_CAP):
        self.window = window
        self.scaling = scaling
        self.cap = cap

    def update_target_weight(self, t, prices, returns, vix_series, current_weights):
        n = len(current_weights)
        if n == 0:
            return current_weights, 0.0
        momentum = 0.0 if t < self.window + 1 else float(np.sum(returns[t-self.window:t]))
        target = float(np.clip(-self.scaling * momentum, -self.cap, self.cap))
        demand = (target - current_weights) * n
        return np.full(n, target), float(np.sum(demand))


class NoiseAgent(StrategyAgent):
    """LEGACY sanity control (K1261/K1262b): near-zero net flow."""
    def __init__(self, std=NOISE_TRADER_STD):
        self.std = std
        self._rng = None

    def update_target_weight(self, t, prices, returns, vix_series, current_weights):
        n = len(current_weights)
        if n == 0:
            return current_weights, 0.0
        rng = self._rng or np.random.RandomState(0)
        changes = rng.normal(0, self.std, size=n)
        new_w = np.clip(current_weights + changes, 0.0, 1.5)
        return new_w, float(np.sum(changes))


class RandomRebalanceAgent(StrategyAgent):
    """(b) ACTIVE control: coherent-block random-direction rebalancer.

    Tests the alternative hypothesis 'ANY large coordinated trading bloc
    destabilizes the market' — same trading footprint as the matched
    strategy, but direction orthogonal to price/vol history.

    - Rebalances with probability `freq` per day (matched to the strategy's
      measured fraction of active-rebalance days in the same cell×adoption).
    - On a rebalance day the whole bloc moves coherently by Δw = s·|Δw|,
      s = ±1 with prob 0.5, |Δw| ~ lognormal with mean/std matched to the
      strategy's measured per-day |Δw| (mean-weight change of the bloc).
    - Decisions come from a DEDICATED RNG stream (seed+RR_RNG_OFFSET) and
      never read prices / returns / vix → orthogonality by construction.
    - Weights clipped to [-EXPOSURE_CAP, EXPOSURE_CAP] (TF/MR support);
      RR_VT clipped to [0, EXPOSURE_CAP] to match VT's long-only support.
    """
    def __init__(self, freq, dw_mean, dw_std, long_only=False, cap=EXPOSURE_CAP):
        self.freq = float(min(max(freq, 0.0), 1.0))
        dw_mean = max(float(dw_mean), 1e-8)
        dw_std = max(float(dw_std), 1e-10)
        # lognormal parameterization matched to mean/std of |Δw|
        sigma2 = np.log(1.0 + (dw_std / dw_mean) ** 2)
        self.ln_sigma = float(np.sqrt(sigma2))
        self.ln_mu = float(np.log(dw_mean) - 0.5 * sigma2)
        self.long_only = long_only
        self.cap = cap
        self._rng = None  # dedicated stream, set by caller

    def update_target_weight(self, t, prices, returns, vix_series, current_weights):
        n = len(current_weights)
        if n == 0:
            return current_weights, 0.0
        rng = self._rng
        if rng.random_sample() >= self.freq:
            return current_weights, 0.0   # no rebalance today
        sign = 1.0 if rng.random_sample() < 0.5 else -1.0
        dw = sign * rng.lognormal(self.ln_mu, self.ln_sigma)
        lo = 0.0 if self.long_only else -self.cap
        new_w = np.clip(current_weights + dw, lo, self.cap)
        demand = float(np.sum(new_w - current_weights))
        return new_w, demand


def _build_strategy(treatment, rng_seed, turnover_params=None):
    if treatment == 'VT_baseline':
        return VTAgent(cap=VT_CAP)
    if treatment == 'TF':
        return TFAgent()
    if treatment == 'MR':
        return MRAgent()
    if treatment == 'NoiseControl':
        return NoiseAgent()
    if treatment in ('RR_VT', 'RR_TF', 'RR_MR'):
        tp = turnover_params
        if tp is None:
            raise ValueError(f"{treatment} requires turnover_params")
        agent = RandomRebalanceAgent(
            freq=tp['freq'], dw_mean=tp['dw_mean'], dw_std=tp['dw_std'],
            long_only=(treatment == 'RR_VT'),
        )
        agent._rng = np.random.RandomState((rng_seed + RR_RNG_OFFSET) % (2**31 - 1))
        return agent
    raise ValueError(f"Unknown treatment: {treatment}")


# ============================================================
# Core simulation — market mechanics VERBATIM K1262b
# ============================================================

def run_single_simulation(args):
    """One sim. args = (treatment, adoption, seed, kyle_lambda, gamma,
                        turnover_params_or_None, keep_returns_bool)"""
    (treatment, adoption, seed, kyle_lambda, vix_vol_sensitivity,
     turnover_params, keep_returns) = args

    rng = np.random.RandomState(seed)

    n_noise = N_NOISE_FIXED
    n_strategy = int(N_BH_VT_POOL * adoption)
    n_bh = N_BH_VT_POOL - n_strategy

    strategy = _build_strategy(treatment, seed, turnover_params)
    if isinstance(strategy, NoiseAgent):
        strategy._rng = rng

    prices = np.zeros(N_DAYS)
    returns = np.zeros(N_DAYS)
    vix_series = np.zeros(N_DAYS)

    if treatment == 'VT_baseline':
        init_w = min(12.0 / INITIAL_VIX, VT_CAP)
    elif treatment in ('TF', 'MR'):
        init_w = 0.0
    elif treatment == 'NoiseControl':
        init_w = 0.5
    elif treatment in ('RR_VT',):
        init_w = min(12.0 / INITIAL_VIX, VT_CAP)   # same starting bloc as VT
    elif treatment in ('RR_TF', 'RR_MR'):
        init_w = 0.0                                # same starting bloc as TF/MR
    else:
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

    # turnover recording (for (b) matched-control calibration)
    abs_dw_sum = 0.0
    abs_dw_sq_sum = 0.0
    n_rebalance_days = 0
    n_decision_days = 0

    for t in range(1, N_DAYS):
        # VIX update — VERBATIM K827v3/K1261/K1262/K1262b
        realized_vol_20d = (np.std(ret_buffer) * np.sqrt(252) if t > 1
                            else FUNDAMENTAL_VOL * np.sqrt(252))
        vix_target = VIX_MEAN + vix_vol_sensitivity * max(0, realized_vol_20d - 0.16)
        vix_series[t] = (vix_series[t-1]
                         + VIX_MR_SPEED * (vix_target - vix_series[t-1])
                         + rng.normal(0, VIX_NOISE_STD))
        vix_series[t] = max(9.0, min(80.0, vix_series[t]))

        net_demand = 0.0

        if n_strategy > 0:
            prev_mean_w = float(np.mean(strategy_weights))
            new_w, strategy_demand = strategy.update_target_weight(
                t, prices, returns, vix_series, strategy_weights)
            net_demand += strategy_demand
            strategy_weights = new_w
            cur_mean_w = float(np.mean(strategy_weights))
            strategy_weight_history[t] = cur_mean_w
            # record turnover of the bloc (per-agent mean |Δw|)
            adw = abs(cur_mean_w - prev_mean_w)
            n_decision_days += 1
            if adw > TURNOVER_EPS:
                n_rebalance_days += 1
                abs_dw_sum += adw
                abs_dw_sq_sum += adw * adw
        else:
            strategy_weight_history[t] = strategy_weight_history[t-1]

        # Noise traders — VERBATIM
        noise_changes = rng.normal(0, NOISE_TRADER_STD, size=n_noise)
        noise_weights = np.clip(noise_weights + noise_changes, 0.0, 1.5)
        net_demand += np.sum(noise_changes)

        # Kyle price formation — VERBATIM
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

    # Metrics — VERBATIM K1262b
    valid_returns = returns[1:]
    ann_vol = np.std(valid_returns) * np.sqrt(252)
    ann_return = np.mean(valid_returns) * 252

    cum = np.cumprod(1 + valid_returns)
    running_max = np.maximum.accumulate(cum)
    max_dd = float(np.min(cum / running_max - 1))

    sigma_daily = np.std(valid_returns)
    flash = np.sum(valid_returns < -3 * sigma_daily) if sigma_daily > 0 else 0
    flash_crash_freq = flash / len(valid_returns) * 252

    kurtosis = sp_stats.kurtosis(valid_returns, fisher=True)
    skewness = sp_stats.skew(valid_returns)

    vt_sharpe = np.nan
    if n_strategy > 0:
        if treatment == 'VT_baseline':
            w = np.minimum(12.0 / vix_series[:-1], VT_CAP)
        else:
            w = strategy_weight_history[:-1]
        port = w * valid_returns
        pr = np.mean(port) * 252
        pv = np.std(port) * np.sqrt(252)
        vt_sharpe = pr / pv if pv > 0 else 0.0

    # turnover summary for this sim
    if n_rebalance_days > 0:
        dw_mean = abs_dw_sum / n_rebalance_days
        dw_var = max(abs_dw_sq_sum / n_rebalance_days - dw_mean ** 2, 0.0)
        dw_std = float(np.sqrt(dw_var))
    else:
        dw_mean, dw_std = 0.0, 0.0
    rebalance_freq = (n_rebalance_days / n_decision_days) if n_decision_days else 0.0

    out = {
        'sharpe': float(vt_sharpe) if np.isfinite(vt_sharpe) else None,
        'ann_return': float(ann_return),
        'ann_vol': float(ann_vol),
        'max_dd': max_dd,
        'kurtosis': float(kurtosis),
        'skewness': float(skewness),
        'flash_crash_freq': float(flash_crash_freq),
        'final_price': float(prices[-1]),
        'n_nan_events': int(n_nan_events),
        'n_price_clamp': int(n_price_clamp),
        'turnover_dw_mean': float(dw_mean),
        'turnover_dw_std': float(dw_std),
        'turnover_freq': float(rebalance_freq),
    }
    if keep_returns:
        out['returns'] = valid_returns.astype(np.float32)
    return out


# ============================================================
# (a) EXOGENOUS sup-Wald breakpoint detector + permutation null
# ============================================================

def _sup_wald(groups):
    """groups: list of 1-D arrays of sim-level Sharpe, ordered by adoption.
    Returns (sup_stat, argmax_split_k). Split k means groups[:k+1] vs
    groups[k+1:]. Welch-type Wald on pooled observations."""
    G = len(groups)
    best_stat, best_k = -np.inf, None
    sizes = [len(g) for g in groups]
    for k in range(G - 1):
        left = np.concatenate(groups[:k+1])
        right = np.concatenate(groups[k+1:])
        n1, n2 = len(left), len(right)
        if n1 < 2 or n2 < 2:
            continue
        m1, m2 = left.mean(), right.mean()
        v1 = left.var(ddof=1) / n1
        v2 = right.var(ddof=1) / n2
        denom = v1 + v2
        stat = (m1 - m2) ** 2 / denom if denom > 0 else 0.0
        if stat > best_stat:
            best_stat, best_k = stat, k
    return best_stat, best_k


def detect_threshold_exogenous(sharpe_by_adoption, adoption_labels,
                               perm_seed, boot_seed):
    """Exogenous structural-break detector on the Sharpe-vs-φ curve.

    No reference to any pre-known threshold. Procedure fixed ex ante:
      1. Applicability gate (e): baseline (lowest adoption) mean Sharpe <
         APPLICABILITY_FLOOR → 'not_applicable_saturated_loss'.
      2. sup-Wald over interior split points of the ordered adoption grid.
      3. Permutation p-value: permute adoption labels over pooled obs
         (B=PERMUTATION_B, seeded).
      4. If p < DETECTOR_ALPHA and post-break mean < pre-break mean →
         threshold = first adoption level of the post-break regime.
      5. Path-level bootstrap (B=THRESHOLD_BOOT_B, seeded): resample sims
         within each adoption group, recompute argmax split → breakpoint
         frequency distribution + 80% interval.
    """
    groups = [np.asarray(sharpe_by_adoption[lbl], dtype=float)
              for lbl in adoption_labels]
    groups = [g[np.isfinite(g)] for g in groups]
    base_mean = float(groups[0].mean()) if len(groups[0]) else np.nan

    result = {
        'detector': 'exogenous sup-Wald breakpoint + permutation null',
        'baseline_mean_sharpe': base_mean,
        'applicability_floor': APPLICABILITY_FLOOR,
    }

    # (e) applicability gate
    if not np.isfinite(base_mean) or base_mean < APPLICABILITY_FLOOR:
        result.update({
            'status': 'not_applicable_saturated_loss',
            'threshold': None, 'p_value': None,
            'note': ('baseline mean Sharpe below applicability floor — '
                     'strategy already in saturated loss regime before the '
                     'lowest adoption level; Sharpe-degradation breakpoint '
                     'detection is uninformative here.'),
        })
        return result

    sup_obs, k_obs = _sup_wald(groups)
    if k_obs is None:
        result.update({'status': 'degenerate', 'threshold': None, 'p_value': None})
        return result

    # permutation null (fixed seed)
    pooled = np.concatenate(groups)
    sizes = [len(g) for g in groups]
    rng = np.random.RandomState(perm_seed % (2**31 - 1))
    count_ge = 0
    for _ in range(PERMUTATION_B):
        perm = rng.permutation(pooled)
        pg, pos = [], 0
        for s in sizes:
            pg.append(perm[pos:pos+s]); pos += s
        s_perm, _ = _sup_wald(pg)
        if s_perm >= sup_obs:
            count_ge += 1
    p_value = (count_ge + 1) / (PERMUTATION_B + 1)

    pre_mean = float(np.concatenate(groups[:k_obs+1]).mean())
    post_mean = float(np.concatenate(groups[k_obs+1:]).mean())
    degradation = post_mean < pre_mean

    significant = p_value < DETECTOR_ALPHA
    threshold = adoption_labels[k_obs + 1] if (significant and degradation) else None

    # breakpoint bootstrap CI (path-level, fixed seed)
    brng = np.random.RandomState(boot_seed % (2**31 - 1))
    boot_thresholds = []
    for _ in range(THRESHOLD_BOOT_B):
        bg = [g[brng.randint(0, len(g), size=len(g))] for g in groups]
        _, kb = _sup_wald(bg)
        if kb is not None:
            # direction check within replicate
            pre_b = np.concatenate(bg[:kb+1]).mean()
            post_b = np.concatenate(bg[kb+1:]).mean()
            boot_thresholds.append(
                adoption_labels[kb + 1] if post_b < pre_b else 'no_degradation')
        else:
            boot_thresholds.append('degenerate')
    freq = {}
    for tlbl in boot_thresholds:
        freq[tlbl] = freq.get(tlbl, 0) + 1
    freq = {k2: v / len(boot_thresholds) for k2, v in
            sorted(freq.items(), key=lambda x: -x[1])}
    # 80% interval over numeric breakpoint labels
    numeric = sorted(
        [float(t.rstrip('%')) for t in boot_thresholds
         if isinstance(t, str) and t.endswith('%')])
    if len(numeric) >= 10:
        lo = numeric[int(0.10 * len(numeric))]
        hi = numeric[min(int(0.90 * len(numeric)), len(numeric) - 1)]
        boot_interval = [f"{lo:.0f}%", f"{hi:.0f}%"]
    else:
        boot_interval = None

    result.update({
        'status': 'ok',
        'sup_wald': float(sup_obs),
        'p_value': float(p_value),
        'breakpoint_split_after': adoption_labels[k_obs],
        'pre_break_mean': pre_mean,
        'post_break_mean': post_mean,
        'degradation_direction': bool(degradation),
        'threshold': threshold,
        'threshold_bootstrap_freq': freq,
        'threshold_bootstrap_80pct_interval': boot_interval,
        'n_bootstrap': THRESHOLD_BOOT_B,
        'n_permutations': PERMUTATION_B,
    })
    return result


def robustness_drop_grid(sharpe_by_adoption, adoption_labels):
    """DESCRIPTIVE relative-drop grid {30/50/70%} vs lowest-adoption baseline.
    Reported as robustness table only — NOT a calibration anchor."""
    base = np.asarray(sharpe_by_adoption[adoption_labels[0]], dtype=float)
    base = base[np.isfinite(base)]
    base_mean = base.mean() if len(base) else np.nan
    out = {}
    for drop in ROBUSTNESS_DROP_GRID:
        first = None
        if np.isfinite(base_mean) and abs(base_mean) > 1e-6:
            for lbl in adoption_labels[1:]:
                g = np.asarray(sharpe_by_adoption[lbl], dtype=float)
                g = g[np.isfinite(g)]
                if not len(g):
                    continue
                drop_pct = (g.mean() - base_mean) / abs(base_mean) * 100
                if drop_pct < -drop:
                    first = lbl
                    break
        out[f"drop>{drop:.0f}%"] = first
    return out


# ============================================================
# (c) path-level bootstrap CIs + two-level block bootstrap (cell1 pooled)
# ============================================================

def path_bootstrap_ci(values, seed, b=PATH_BOOT_B, level=0.95):
    """Percentile bootstrap CI for the mean of sim-level statistics."""
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    if len(v) < 3:
        return None
    rng = np.random.RandomState(seed % (2**31 - 1))
    idx = rng.randint(0, len(v), size=(b, len(v)))
    means = v[idx].mean(axis=1)
    alpha = (1 - level) / 2
    return {
        'mean': float(v.mean()),
        'ci_lo': float(np.percentile(means, 100 * alpha)),
        'ci_hi': float(np.percentile(means, 100 * (1 - alpha))),
        'n': int(len(v)),
        'method': f'path-level percentile bootstrap (B={b})',
    }


def pooled_kurtosis_block_bootstrap(returns_list, seed, b=BLOCK_BOOT_B,
                                    block_len=BLOCK_LEN_DAYS):
    """Two-level bootstrap for the POOLED kurtosis (cell1 only):
    resample paths with replacement, then within each sampled path do a
    circular block bootstrap of its daily returns; pool and compute kurtosis.
    Replaces the invalid iid pooled bootstrap flagged in the v5 audit."""
    if not returns_list:
        return None
    rng = np.random.RandomState(seed % (2**31 - 1))
    M = len(returns_list)
    T = len(returns_list[0])
    n_blocks = int(np.ceil(T / block_len))
    pooled_obs = np.concatenate(returns_list)
    point = float(sp_stats.kurtosis(pooled_obs, fisher=True))
    reps = np.empty(b)
    for i in range(b):
        path_idx = rng.randint(0, M, size=M)
        chunks = []
        for pi in path_idx:
            r = returns_list[pi]
            starts = rng.randint(0, T, size=n_blocks)
            rolled = [np.take(r, np.arange(s, s + block_len) % T) for s in starts]
            chunks.append(np.concatenate(rolled)[:T])
        reps[i] = sp_stats.kurtosis(np.concatenate(chunks), fisher=True)
    return {
        'pooled_kurtosis': point,
        'ci_lo': float(np.percentile(reps, 2.5)),
        'ci_hi': float(np.percentile(reps, 97.5)),
        'method': (f'two-level circular block bootstrap '
                   f'(paths × {block_len}-day blocks, B={b})'),
    }


# ============================================================
# Runner
# ============================================================

def _det_hash(*parts):
    """Deterministic string hash (Python's hash() is per-process randomized
    for str → would break fixed-seed reproducibility)."""
    return zlib.crc32('|'.join(str(p) for p in parts).encode()) % 10**6


def _seed_for(treatment, adoption, sim_idx, lambda_idx, gamma_idx):
    """Extends K1262b seed formula with deterministic treatment offset."""
    return (int(adoption * 100000) + sim_idx + 42
            + TF_SCALING * 1000 + MOMENTUM_WINDOW * 10
            + lambda_idx * 100 + gamma_idx * 10
            + TREATMENT_SEED_OFFSET[treatment])


def run_batch(treatment, adoption, lambda_idx, gamma_idx, n_sims,
              turnover_params=None, keep_returns=False, pool=None):
    args_list = [
        (treatment, adoption,
         _seed_for(treatment, adoption, i, lambda_idx, gamma_idx),
         LAMBDA_GRID[lambda_idx], GAMMA_GRID[gamma_idx],
         turnover_params, keep_returns)
        for i in range(n_sims)
    ]
    if pool is not None:
        return pool.map(run_single_simulation, args_list)
    return [run_single_simulation(a) for a in args_list]


SIM_METRIC_KEYS = ['sharpe', 'ann_return', 'ann_vol', 'max_dd', 'kurtosis',
                   'skewness', 'flash_crash_freq', 'final_price']


def summarize_batch(sims, ci_seed):
    """Sim-level arrays + path-level bootstrap CIs for headline metrics."""
    summary = {}
    for j, key in enumerate(SIM_METRIC_KEYS):
        vals = [s[key] for s in sims if s[key] is not None]
        vals = [v for v in vals if np.isfinite(v)]
        if not vals:
            summary[key] = None
            continue
        entry = {
            'mean': float(np.mean(vals)),
            'std': float(np.std(vals)),
            'median': float(np.median(vals)),
            'n_valid': len(vals),
        }
        if key in ('sharpe', 'kurtosis', 'max_dd'):
            entry['boot_ci'] = path_bootstrap_ci(vals, seed=ci_seed + j)
        summary[key] = entry
    summary['_diagnostics'] = {
        'total_nan_events': int(sum(s['n_nan_events'] for s in sims)),
        'total_price_clamps': int(sum(s['n_price_clamp'] for s in sims)),
        'n_simulations': len(sims),
    }
    summary['_turnover'] = {
        'dw_mean': float(np.mean([s['turnover_dw_mean'] for s in sims])),
        'dw_std': float(np.mean([s['turnover_dw_std'] for s in sims])),
        'freq': float(np.mean([s['turnover_freq'] for s in sims])),
    }
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n-sims', type=int, default=50)
    ap.add_argument('--tag', type=str, default='smoke')
    ap.add_argument('--cells', type=str, default='all',
                    help="comma list of cell labels or 'all'")
    args = ap.parse_args()

    n_sims = args.n_sims
    tag = args.tag
    out_dir = os.path.dirname(os.path.abspath(__file__))
    t0 = time.time()

    cells_to_run = OAT_CELLS if args.cells == 'all' else [
        c for c in OAT_CELLS if c[0] in args.cells.split(',')]

    print("=" * 72)
    print(f"K1471 VT-crowding redesign — tag={tag}, M={n_sims}")
    print(f"  cells: {[c[0] for c in cells_to_run]}")
    print(f"  treatments: {ALL_TREATMENTS}")
    print(f"  cell1 grid: {ADOPTION_GRID_CELL1}; other: {ADOPTION_GRID_OTHER}")
    print(f"  workers: {N_WORKERS}")
    print(f"  detector: exogenous sup-Wald (alpha={DETECTOR_ALPHA}, "
          f"perm B={PERMUTATION_B}, boot B={THRESHOLD_BOOT_B})")
    print(f"  started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 72)

    results = {'cells': {}}
    total_sims = 0

    with Pool(N_WORKERS) as pool:
        for cell_label, li, gi in cells_to_run:
            grid = ADOPTION_GRID_CELL1 if cell_label == 'cell1_baseline' \
                else ADOPTION_GRID_OTHER
            labels = [f"{a*100:.0f}%" for a in grid]
            cell = {
                'config': {'kyle_lambda': LAMBDA_GRID[li],
                           'vix_vol_sensitivity': GAMMA_GRID[gi],
                           'adoption_grid': labels},
                'treatments': {},
            }
            # measured turnover per (strategy, adoption) — drives stage 2
            turnover_lookup = {}

            # ---- stage 1: strategy treatments + legacy sanity control ----
            for treatment in STRATEGY_TREATMENTS + SANITY_TREATMENTS:
                tr = {'per_adoption': {}, 'sharpe_sims': {}}
                for a, lbl in zip(grid, labels):
                    keep = (cell_label == 'cell1_baseline'
                            and treatment in STRATEGY_TREATMENTS)
                    sims = run_batch(treatment, a, li, gi, n_sims,
                                     keep_returns=keep, pool=pool)
                    total_sims += n_sims
                    ci_seed = PATH_BOOT_SEED + _det_hash(cell_label, treatment, lbl)
                    summ = summarize_batch(sims, ci_seed)
                    # (c) cell1 pooled kurtosis via two-level block bootstrap
                    if keep:
                        rets = [s['returns'].astype(np.float64) for s in sims]
                        summ['pooled_kurtosis_block_boot'] = \
                            pooled_kurtosis_block_bootstrap(
                                rets, seed=BLOCK_BOOT_SEED
                                + _det_hash(treatment, lbl))
                        del rets
                    tr['per_adoption'][lbl] = summ
                    tr['sharpe_sims'][lbl] = [
                        s['sharpe'] for s in sims if s['sharpe'] is not None]
                    if treatment in STRATEGY_TREATMENTS:
                        turnover_lookup[(treatment, lbl)] = summ['_turnover']
                cell['treatments'][treatment] = tr
                print(f"  [{cell_label}] {treatment} done "
                      f"({time.time()-t0:.0f}s elapsed)")

            # ---- stage 2: matched active controls (b) ----
            for rr, src in [('RR_VT', 'VT_baseline'), ('RR_TF', 'TF'),
                            ('RR_MR', 'MR')]:
                tr = {'per_adoption': {}, 'sharpe_sims': {},
                      'matched_to': src}
                for a, lbl in zip(grid, labels):
                    tp = turnover_lookup[(src, lbl)]
                    sims = run_batch(rr, a, li, gi, n_sims,
                                     turnover_params=tp, pool=pool)
                    total_sims += n_sims
                    ci_seed = PATH_BOOT_SEED + _det_hash(cell_label, rr, lbl)
                    summ = summarize_batch(sims, ci_seed)
                    summ['matched_turnover_params'] = tp
                    tr['per_adoption'][lbl] = summ
                    tr['sharpe_sims'][lbl] = [
                        s['sharpe'] for s in sims if s['sharpe'] is not None]
                cell['treatments'][rr] = tr
                print(f"  [{cell_label}] {rr} (matched to {src}) done "
                      f"({time.time()-t0:.0f}s elapsed)")

            # ---- detector pass (a)(d)(e) ----
            cell['detector'] = {}
            cell['robustness_drop_grid'] = {}
            for treatment in ALL_TREATMENTS:
                sh = cell['treatments'][treatment]['sharpe_sims']
                det_seed = PERM_BASE_SEED + _det_hash(cell_label, treatment)
                bt_seed = THRESHOLD_BOOT_SEED + _det_hash(cell_label, treatment)
                cell['detector'][treatment] = detect_threshold_exogenous(
                    sh, labels, perm_seed=det_seed, boot_seed=bt_seed)
                cell['robustness_drop_grid'][treatment] = \
                    robustness_drop_grid(sh, labels)

            # drop bulky sharpe_sims from saved JSON for full runs? keep —
            # needed for reproducibility & downstream paper figures.
            results['cells'][cell_label] = cell
            print(f"[{cell_label}] COMPLETE ({time.time()-t0:.0f}s elapsed)")

    elapsed = time.time() - t0
    output = {
        'experiment_id': 'K1471_vt_crowding_redesign',
        'tag': tag,
        'type': 'SIMULATION (methodology redesign, vt-crowding-abm v5 fixes)',
        'timestamp': datetime.now().isoformat(),
        'runtime_seconds': elapsed,
        'total_sims': total_sims,
        'n_sims_per_batch': n_sims,
        'config': {
            'treatments': ALL_TREATMENTS,
            'adoption_grid_cell1': ADOPTION_GRID_CELL1,
            'adoption_grid_other': ADOPTION_GRID_OTHER,
            'detector': {
                'name': 'exogenous sup-Wald breakpoint',
                'alpha': DETECTOR_ALPHA,
                'permutation_B': PERMUTATION_B,
                'perm_base_seed': PERM_BASE_SEED,
                'threshold_boot_B': THRESHOLD_BOOT_B,
                'threshold_boot_seed': THRESHOLD_BOOT_SEED,
                'applicability_floor': APPLICABILITY_FLOOR,
            },
            'ci': {
                'path_bootstrap_B': PATH_BOOT_B,
                'path_bootstrap_seed': PATH_BOOT_SEED,
                'block_bootstrap_B': BLOCK_BOOT_B,
                'block_len_days': BLOCK_LEN_DAYS,
                'block_bootstrap_seed': BLOCK_BOOT_SEED,
            },
            'matched_control': {
                'rr_rng_offset': RR_RNG_OFFSET,
                'treatment_seed_offset': TREATMENT_SEED_OFFSET,
            },
            'market': {
                'n_agents': N_AGENTS, 'n_noise_fixed': N_NOISE_FIXED,
                'n_days': N_DAYS, 'lambda_grid': LAMBDA_GRID,
                'gamma_grid': GAMMA_GRID, 'tf_scaling': TF_SCALING,
                'momentum_window': MOMENTUM_WINDOW,
                'vix_mr_speed': VIX_MR_SPEED,
            },
            'seed_formula': ('int(adoption*100000)+sim_idx+42+scaling*1000'
                             '+window*10+lambda_idx*100+gamma_idx*10'
                             '+TREATMENT_SEED_OFFSET[treatment]'),
        },
        'cells': results['cells'],
    }

    out_path = os.path.join(out_dir, f'k1471_{tag}_results.json')
    with open(out_path, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n[SAVED] {out_path}")

    # threshold summary table
    md = [f"# K1471 threshold table — exogenous sup-Wald detector ({tag}, M={n_sims})",
          "", f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
          f"**Runtime**: {elapsed:.0f}s | **Total sims**: {total_sims}", "",
          "| Cell | Treatment | status | threshold | p-value | boot 80% interval | baseline Sh |",
          "|---|---|---|---|---|---|---|"]
    for cl in results['cells']:
        for tre in ALL_TREATMENTS:
            d = results['cells'][cl]['detector'][tre]
            iv = d.get('threshold_bootstrap_80pct_interval')
            md.append(
                f"| {cl} | {tre} | {d.get('status')} | "
                f"{d.get('threshold') or 'null'} | "
                f"{d.get('p_value') if d.get('p_value') is not None else 'n/a'} | "
                f"{('['+iv[0]+', '+iv[1]+']') if iv else 'n/a'} | "
                f"{d.get('baseline_mean_sharpe'):.3f} |")
    tbl_path = os.path.join(out_dir, f'k1471_{tag}_threshold_table.md')
    with open(tbl_path, 'w') as f:
        f.write('\n'.join(md))
    print(f"[SAVED] {tbl_path}")
    print(f"\nK1471 {tag} COMPLETE — {elapsed:.0f}s, {total_sims} sims")


if __name__ == '__main__':
    main()
