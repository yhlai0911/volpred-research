"""
K1261: Non-VT Crowding ABM Ablation — fork from K827v3 (P5 baseline)
======================================================================
[提出: 主線程 (Tier B P5 推進), 執行: TBD worktree agent]
類型：模擬實驗（非實證數據）— skeleton only, implementation TODO

Goal:
  Address NotebookLM cross-paper meta-eval critique「P5 ABM 70% threshold 是
  λ/γ 數學結果非 emergent」+「無 non-VT 對照組」by running the same K827v3 ABM
  framework with non-VT strategy agents (Trend-Following, Mean-Reversion) +
  pure-noise control. If non-VT also shows critical adoption thresholds → P5
  finding generalizes to positive-feedback crowding (not VT-specific). If only
  VT shows threshold → P5 claim stands.

Design (per `experiments/k1261/README.md`):
  Phase 1 (this script):
    3 treatments × 7 adoption × 500 MC = 10,500 sims
    - Treatment 0 (VT-baseline replication of K827v3): sanity check
    - Treatment 1 (TF): trend-following 22-day momentum
    - Treatment 2 (MR): mean-reversion 22-day counter-momentum
    - Treatment 3 (NoiseControl): all 800 = noise (no strategy crowding)
  Phase 2 (separate K1261b script if Phase 1 finds non-VT threshold):
    OAT sensitivity λ/γ ±50% × 3 treatments × 3 adoption × 200 sims = 5,400 sims

Open Questions resolved (per README + baseline_check_2026_04_27.md):
  Q1 N (momentum window): 22 days (CTA convention, near 20-day vol window)
  Q2 Noise trader baseline: 200 fixed across all treatments + control
  Q3 VIX feedback: γ=200 across all treatments + sensitivity (γ=0) Phase 2
  Q4 OAT scope: 2-phase plan, Phase 1 baseline first

Implementation TODO (worktree agent):
  1. Fork K827v3's `run_single_simulation()` → factor out VT-specific logic
     (L152-156) into pluggable strategy class
  2. Implement TFAgent / MRAgent / NoiseAgent classes (signatures below)
  3. Run 10,500 sims with multiprocessing.Pool(8), bootstrap CIs
  4. Output `experiments/k1261/k1261_results.json` with same schema as
     K827v3 part1_results (per-cell sharpe / kurtosis / vix_spike_pct etc.)
  5. Threshold detection: critical adoption = where Sharpe drops > 50% from
     baseline AND kurtosis > 10 AND vol amplification > 50%
  6. Cross-treatment comparison table → `k1261_threshold_comparison.png`

Sanity gate (Phase 1.0, ~30 min wall):
  Run VT-treatment 7 adoption × 100 MC = 700 sims; verify Sharpe at 50%/70%/100%
  matches K827v3 to within 5% (validates fork didn't break K827v3 dynamics).

References:
  - paper/vt-crowding-abm/experiments/k827v3_abm_fixed_liquidity.py (canonical baseline)
  - paper/vt-crowding-abm/experiments/k827v3_abm_fixed_liquidity_results.json (verified byte-match P5 Table 2)
  - experiments/k1261/README.md (full design)
  - experiments/k1261/baseline_check_2026_04_27.md (K827v3 source confirmed + Q3 resolution)
  - .claude/rules/experiments.md (lookahead `signal.shift(1)` 等效, fixed seed=42, multistart 100+ if pooled-MLE)
  - .claude/skills/autonomous-research/references/agent-brief-template.md (worktree agent brief 6-element)

NOT IMPLEMENTED — this file is methodology decision skeleton only.
Worktree agent dispatch will fork from K827v3, implement, and run.
"""

# ============================================================
# Configuration (mirrors K827v3 + adds K1261-specific knobs)
# ============================================================

# Same as K827v3 baseline (do NOT modify these for fair comparison):
N_AGENTS = 1000
N_NOISE_FIXED = 200          # fixed liquidity per K827v3 design
N_BH_VT_POOL = 800           # 800 strategy agents (VT/TF/MR/Noise replacement)
N_DAYS = 2520                # 10 years
N_SIMS_MAIN = 500
N_SIMS_SANITY = 100          # Phase 1.0 sanity gate
N_BOOTSTRAP = 2000

ADOPTION_LEVELS = [0.0, 0.10, 0.20, 0.30, 0.50, 0.70, 1.00]

# Strategy parameters
MOMENTUM_WINDOW = 22         # N for TF/MR (per Q1 resolution; CTA convention)
TF_SCALING = 10.0            # multiplier on cum-return → target weight (TBD calibrate)
EXPOSURE_CAP = 1.5           # same as VT_CAP in K827v3

# Treatment definitions
TREATMENTS = {
    'VT_baseline':   {'class': 'VTAgent',    'description': 'Replicate K827v3 12/VIX rule (sanity)'},
    'TF':            {'class': 'TFAgent',    'description': 'Trend-following 22d momentum'},
    'MR':            {'class': 'MRAgent',    'description': 'Mean-reversion 22d counter-momentum'},
    'NoiseControl':  {'class': 'NoiseAgent', 'description': 'Pure-noise (control: no strategy crowding)'},
}


# ============================================================
# Strategy agent classes (signatures only — worktree agent implements)
# ============================================================

class StrategyAgent:
    """Base class. Subclass and implement update_target_weight()."""
    def update_target_weight(self, t, prices, returns, vix_series, **kwargs):
        raise NotImplementedError


class VTAgent(StrategyAgent):
    """Volatility-targeting agent (P5 K827v3 rule).

    Target weight = min(12 / VIX_{t-1}, VT_CAP). Reads VIX, sells on VIX rise.
    Implementation: Copy K827v3 L152-156 verbatim.
    """
    def update_target_weight(self, t, prices, returns, vix_series, **kwargs):
        raise NotImplementedError  # TODO worktree agent


class TFAgent(StrategyAgent):
    """Trend-following agent.

    Target weight = clip(scaling * sum(returns_{t-N..t-1}), -CAP, +CAP).
    Long on positive momentum (buys on up), short on negative (sells on down).
    Mechanism: correlated buy-on-up / sell-on-down → 同樣 positive feedback as VT
    (different signal trigger but similar crowding pressure).
    """
    def __init__(self, window=MOMENTUM_WINDOW, scaling=TF_SCALING, cap=EXPOSURE_CAP):
        self.window = window
        self.scaling = scaling
        self.cap = cap

    def update_target_weight(self, t, prices, returns, vix_series, **kwargs):
        raise NotImplementedError  # TODO worktree agent


class MRAgent(StrategyAgent):
    """Mean-reversion agent (opposite of TFAgent).

    Target weight = clip(-scaling * sum(returns_{t-N..t-1}), -CAP, +CAP).
    Buys on dip, sells on rip. Mechanism: counter-pressure → 應 dampen crowding,
    no critical threshold (or threshold reversed → 高 adoption 反而穩定市場).
    """
    def __init__(self, window=MOMENTUM_WINDOW, scaling=TF_SCALING, cap=EXPOSURE_CAP):
        self.window = window
        self.scaling = scaling
        self.cap = cap

    def update_target_weight(self, t, prices, returns, vix_series, **kwargs):
        raise NotImplementedError  # TODO worktree agent


class NoiseAgent(StrategyAgent):
    """Control treatment: agent slot is replaced by noise traders.

    update_target_weight returns constant 0.5 (matching K827v3 noise_weights init).
    With 100% NoiseAgent adoption, total = 200 fixed noise + 800 noise = 1000
    pure-noise market, NO strategy crowding by construction. Establishes that
    any threshold under VT/TF/MR is strategy-induced, not microstructure artifact.
    """
    def update_target_weight(self, t, prices, returns, vix_series, **kwargs):
        raise NotImplementedError  # TODO worktree agent


# ============================================================
# Simulation runner (worktree agent implements)
# ============================================================

def run_single_simulation(args):
    """Single sim, fork from K827v3 L101-243.

    Args:
        treatment: str in TREATMENTS keys
        adoption: float in ADOPTION_LEVELS
        seed: int
        param_overrides: dict (kyle_lambda / vix_vol_sensitivity / vix_mr_speed)

    Worktree agent TODO:
      1. Replace K827v3 hardcoded VT logic (L152-156) with strategy.update_target_weight()
      2. Apply same Kyle market maker + endogenous VIX evolution (preserve baseline)
      3. Compute same metrics schema (ann_return / ann_vol / sharpe / kurtosis / etc.)
    """
    raise NotImplementedError


def run_treatment(treatment_name, adoption_levels, n_sims, n_workers=8):
    """Run all adoption levels × n_sims for one treatment via multiprocessing.Pool."""
    raise NotImplementedError


def detect_critical_threshold(per_adoption_results):
    """Critical adoption = first level where ALL of:
      - Sharpe drops > 50% from baseline (treatment-specific 0% or 10%)
      - Kurtosis > 10
      - Vol amplification > 50%
    Returns: (critical_adoption: float | None, justification: dict)
    """
    raise NotImplementedError


def main():
    """K1261 main entry — worktree agent implements:
      Phase 1.0 sanity: run VT_baseline 7 adoption × 100 MC = 700 sims, verify
        Sharpe matches K827v3 to within 5%.
      Phase 1 main: run all 4 treatments × 7 × 500 MC = 14,000 sims.
        (3 non-VT × 3,500 + 1 VT sanity × 3,500 = 14,000 total; if compute-bound
         skip VT main and rely on K827v3 stored results for VT comparison.)
      Output: experiments/k1261/k1261_results.json + threshold_comparison plot.
    """
    raise NotImplementedError


if __name__ == '__main__':
    raise NotImplementedError(
        "K1261 skeleton only. Implementation TODO by worktree agent.\n"
        "See experiments/k1261/README.md for design + dispatch brief."
    )
