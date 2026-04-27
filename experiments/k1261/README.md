# K1261 — P5 Non-VT Crowding ABM Ablation (Design Proposal)

**Status**: 🟡 **DESIGN ONLY** — no code / no run yet。本 slot 主線程 design proposal，後續 slot dispatch worktree agent 實作 + 跑。

**Date proposed**: 2026-04-27
**Target paper**: P5 vt-crowding-abm
**Tier**: B（per memory `project_paper_portfolio_decisions_2026_04_27`）
**Driver**: NotebookLM cross-paper meta-eval 揭露 P5 v2 round 「ABM 70% 崩盤閾值是 λ/γ 數學結果，不是 emergent finding」+「需補非 VT 策略對照組證明 finding 不僅是 VT-specific」

---

## Motivation

### Critique（per `feedback_paper_cross_paper_meta_eval` + P5 v2 README addendum）

NotebookLM portfolio-level lens 對 P5 v2 round 4.4★ 撤回到 3.5-3.8★，主因：

1. **設計性 vs emergent**: P5 ABM 70% 崩盤閾值是 λ (Kyle lambda 0.005) / γ (VIX 反饋 200) 參數的數學結果。Reviewer 會說「這不是發現臨界點是製造臨界點」。
2. **缺對照組**: 只跑 VT 策略 crowding，無法區分「VT 特有 crowding mechanism」vs「任何 correlated strategy 都會 crowding」。
3. P5 paper §1 L60 已 acknowledge「we quantify---rather than discovers」，但 reviewer 仍可能 challenge threshold magnitude IS λ/γ-determined。

### Defense via K1261 ablation

**Hypothesis**: If non-VT strategies (trend-following, mean-reversion) at same ABM framework also show critical adoption thresholds → P5's threshold finding **generalizes** (證實 crowding 是 generic positive-feedback feature, 不是 VT-specific bug). If only VT shows threshold → P5's claim **is VT-specific** (站得住腳 reviewer challenge).

**Either outcome is publishable** + directly addresses NotebookLM Argument 2 critique.

---

## Experimental Design

### Baseline (replicate P5 **K827v3** / `paper/vt-crowding-abm/experiments/k827v3_abm_fixed_liquidity.py` / paper Table 2)

- 1,000 heterogeneous agents（800 strategy agents + 200 fixed noise traders）
- 7 VT adoption levels: 0%, 10%, 20%, 30%, 50%, 70%, 100%
- 500 Monte Carlo simulations × 2,520 days each
- ABM dynamics per P5 paper §3 (Kyle lambda price impact + endogenous VIX feedback loop)
- λ = 0.005, γ = 200, κ = 0.03, σ_f = 0.16/√252, V̄ = 18

### Treatment 1: Trend-Following (TF) crowding

Replace VT agents with TF agents:
- TF agent rule: long if recent N-day return > 0; short if < 0; size proportional to |momentum|
- Recommended N: 22 days (1-month momentum, conventional CTA window)
- Replace VT's σ-scaled exposure with momentum-scaled exposure
- Same 7 adoption levels, same 500 MC sims

Expected mechanism: TF crowding via correlated buy-on-up / sell-on-down → 同樣 positive feedback loop（買漲推漲、賣跌推跌）→ should produce similar critical threshold as VT.

### Treatment 2: Mean-Reversion (MR) crowding

Replace VT agents with MR agents:
- MR agent rule: long if recent N-day return < 0 (buy dip); short if > 0 (sell rip)
- Same N=22, same 7 adoption levels

Expected mechanism: MR provides counter-pressure → 應該 **dampen** crowding, 不會出現 critical threshold（甚至高 adoption 可能改善市場穩定性）。

### Treatment 3: Random / Pure noise traders (control)

100% noise traders baseline — no strategy crowding possible by construction. Establishes that any threshold under VT/TF/MR is **strategy-induced** not microstructure artifact.

---

## Predictions / Falsifiability

| Hypothesis | TF result | MR result | Implication for P5 |
|---|---|---|---|
| H1: Crowding is generic positive-feedback property | TF 也有 critical threshold（~50-70% 範圍）| MR 沒有 threshold 或 threshold 反向 | P5 finding 不是 VT-specific，**framing 必須 reframe 從「VT 特殊」改為「positive-feedback 通用」**。但 P5 仍可 publish—只是定位變「VT 是 positive-feedback 策略 family 的 representative case」 |
| H2: Crowding is VT-specific channel | TF 沒有 critical threshold（漸進 degradation）| MR 沒有 threshold | P5 claim **站得住 reviewer challenge**，VT specific feedback loop（VIX → exposure reduction → realized vol up → VIX up）不是其他策略複製得了 |
| H3: 兩者都有，但 magnitude 不同 | TF threshold magnitude < VT | MR no | Mixed: P5 finding 是 VT-amplified positive feedback，TF 是 weaker variant，MR 是 absent |

**Falsifiability**: Pre-register prediction H2（P5 paper 隱含 claim），如果 TF 也有 threshold → H2 reject → P5 必 reframe。

---

## Success Criteria

1. **3 treatments × 7 adoption × 500 MC = 10,500 simulations**, total 26.46M agent-day observations
2. **Bootstrap 95% CI** for each (treatment, adoption) cell on Sharpe / vol amplification / kurtosis / flash crash freq
3. **Threshold detection**: define critical threshold as adoption level where Sharpe drops > 50% from baseline, kurtosis > 10, vol amplification > 50%
4. **Cross-treatment comparison table**: TF threshold vs VT threshold vs MR threshold (or absence)
5. **OAT sensitivity check**: re-run TF / MR at λ ±50%, γ ±50% to confirm threshold (if found) is parameter-stable not knife-edge

---

## Implementation Plan (worktree agent)

**主線程**: Design proposal（本 README）+ 寫 experiment script outline + identify entry points
**Worktree agent dispatch（後續 slot）**:
- Brief: per `.claude/skills/autonomous-research/references/agent-brief-template.md` 6-element brief
- Skills referenced: `.claude/skills/autonomous-research/SKILL.md` + `.claude/rules/experiments.md`
- Code base: replicate P5 **K827v3** ABM framework（讀 `paper/vt-crowding-abm/experiments/k827v3_abm_fixed_liquidity.py`, P5 reproduce.py 跑此 script；fork to `experiments/k1261/k1261_non_vt_ablation.py`）。已驗證 K827v3 7 adoption levels (10/20/30/50/70/100%) Sharpe 數值 byte-match paper Table 2（baseline_check_2026_04_27.md）。Note: K1031=GARCH-X SSVS, K110/`vt_crowding_simulation`=placeholder draft, 之前都寫錯 cross-link
- Output: `experiments/k1261/{k1261_non_vt_ablation.py, k1261_results.json, threshold_comparison.png}`
- Codex review **PASS** before writing knowledge.json (per experiments.md SOP)
- Estimated runtime: 10,500 simulations × ~2 min each ≈ 350 hours single-thread → must parallelize（multiprocessing pool 8-16 workers → 22-44 hours wall）
- Worktree isolation per `.claude/skills/worktree-merge-verification/SKILL.md`

**Estimated total effort**: 3-5 days wall (compute-bound), 主線程 effort ≤ 4 hours (review + integration)

---

## Cross-link

- `paper/vt-crowding-abm/main.tex` (target paper, §3 ABM specs L85-100, OAT details L101)
- `paper/vt-crowding-abm/review_history/v2/README.md` ⚠️ addendum (cross-paper meta-eval verdict)
- `paper/vt-crowding-abm/experiments/k827v3_abm_fixed_liquidity.py` (**P5 K827v3 canonical baseline**, fixed-liquidity ABM, K1261 fork source)
- `paper/vt-crowding-abm/experiments/k827v3_abm_fixed_liquidity_results.json` (byte-match P5 Table 2 verified)
- `experiments/k1261/baseline_check_2026_04_27.md` (本 slot baseline 驗證 + Q3 VIX feedback resolution)
- `experiments/vt_crowding_simulation/` (placeholder draft, 不 actual run, ignore)
- `experiments/k827/` (initial 397-line iteration, superseded by K827v3)
- Memory: `project_paper_portfolio_decisions_2026_04_27.md` (Tier B P5 推進 priority 1)
- Memory: `feedback_paper_cross_paper_meta_eval.md` (cross-paper meta-eval methodology)
- `.claude/rules/experiments.md` (Pooled-MLE 100+ multistart, lookahead `signal.shift(1)`, seed required)

---

## Open Questions（design 待釐清）

### Resolved 2026-04-27（主線程 K1261 design refinement）

1. ~~**N (momentum window)** for TF/MR~~: **N=22 days**。理由：(a) conventional CTA window；(b) 接近 P5 paper σ 計算 20-day rolling window，差異 2 days 不致 mechanism qualitative shift；(c) `vt_crowding_simulation.py` baseline 已用 22 left as-is for return aggregation logic。**Robustness check**: phase 2 加跑 N=20 + N=66（quarterly momentum）兩組驗證 threshold qualitative 不依賴 N=22 specifically。

2. ~~**Noise trader 共同 baseline**~~: **是, 200 noise traders fixed across all 3 treatments + control**（per K110 baseline + paper §3 design rationale: "fixed liquidity isolates crowding from liquidity evaporation"）. TF / MR / pure-noise treatments 都保持 N_noise=200 ensures cross-treatment comparison apple-to-apple.

### Pending（dispatch worktree agent 前必 resolve）

3. **VIX feedback loop under non-VT**: P5 ABM 的 VIX 演化方程 (paper L90) 是 `VIX_t = max(0, VIX_{t-1} + κ(V̄ + γ·ΔΣ - VIX_{t-1}) + η_t)`。TF/MR 不直接讀 VIX exposure scaling 但 ΔΣ (realized vol) 仍會 evolve as agent flow 改變 σ_real。問題: 在 TF/MR scenario 下保留 γ=200 VIX feedback 是 fair comparison（all treatments share same VIX dynamics）還是 unfair（VIX 對 TF/MR 不該 feedback）？**Tentative resolution**: 保留 γ=200 across all treatments — VIX 演化是 market 內生 dynamics, 不該因 strategy mix 改變。Worktree agent brief 必明寫此 design choice 並 sensitivity check (γ=0 disabled VIX feedback subset, 看 threshold 是否消失 → 若消失則 confirm threshold IS γ-driven 不是 strategy-driven, NotebookLM critique 站得住).

4. **OAT sensitivity scope phasing**: full 9 OAT × 3 treatments × 3 adoption levels × 200 sims = 16,200 sims +baseline 10,500 = 26,700 total. **Resolution**: **2-phase plan**:
   - **Phase 1 (K1261)**: baseline + 3 treatments × 7 adoption × 500 MC = 10,500 sims（threshold detection 主結果，~22-44 hrs wall）
   - **Phase 2 (K1261b)**: OAT sensitivity λ ±50% × 3 treatments × 3 adoption × 200 sims = 5,400 sims（only if Phase 1 finds non-VT threshold, else NS no need OAT）— 等 Phase 1 results decide whether OAT meaningful
   - 不 single-shot dispatch all 26,700 sims，避免 phase 1 無 finding 時 phase 2 浪費 compute
