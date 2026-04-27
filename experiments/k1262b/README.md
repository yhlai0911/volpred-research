# K1262b — P5 Phase 2 OAT Sensitivity (λ × γ)

**Status**: 🟡 **DESIGN proposed (2026-04-27)** — worktree dispatch pending.

**Date**: 2026-04-27
**Target paper**: P5 vt-crowding-abm
**Predecessor**: K1262 Phase 2 (verdict H1+ STRONGLY SUPPORTED, knowledge.json item_id `f3b9edd4`)
**Driver**: Address NotebookLM critique「70% threshold = λ/γ mathematical artifact (knife-edge), not emergent」directly. K1262 confirmed strategy specification (scaling/window) is NOT knife-edge; K1262b confirms market microstructure (λ/γ) is also not knife-edge. Together rebut the critique fully.

---

## Motivation

K1262 Phase 2 demonstrated H1+ direction is robust to TF/MR scaling × window choices. But NotebookLM's original critique was about **market microstructure parameters** (λ Kyle impact, γ VIX feedback intensity). If small λ/γ changes (e.g. ±50%) flip the threshold from 70% → 0% or → 100%, then "70% IS the λ/γ mathematical solution" is correct. If threshold magnitude shifts modestly (e.g. 60-80% range) but qualitative ordering (TF/MR < VT) preserves, then critique is rebutted.

**This is confirmatory, not essential** per K1262 verdict. P5 v3 paper rewrite can proceed without K1262b. K1262b makes reviewer response stronger if reviewer challenges "70% IS λ/γ artifact."

---

## Experimental Design

### OAT (One-At-a-Time) sensitivity sweep

| Parameter | Baseline | Low | High |
|---|---|---|---|
| λ (Kyle impact) | 0.005 | 0.0025 | 0.0075 |
| γ (VIX feedback) | 200 | 100 | 300 |

4 OAT cells: (λ_low, γ_base) / (λ_high, γ_base) / (λ_base, γ_low) / (λ_base, γ_high). Plus baseline (λ_base, γ_base) = 5 cells total. 1 baseline + 4 perturbations.

### Treatments × Adoption × MC

- 4 treatments (VT_baseline, TF, MR, NoiseControl) × 3 adoption levels {30%, 70%, 100%} × 200 MC × 5 OAT cells
- = 4 × 3 × 200 × 5 = **12,000 sims**
- Wall time estimate: 12,000 × 35 ms/sim (K1262 rate, includes OAT pool overhead) ≈ 7 min
- 3 adoption levels chosen: 30% / 70% / 100% — covers transition / mid / saturated regimes.
- TF scaling=10, window=22 (K1261 default; K1262 showed scaling/window robust so fix at default)

### Threshold detector

Apply P5-style (Sharpe-only: sign flip OR drop > 70%) detector — calibrates to VT=70% per K1262 verdict, exact match to P5 paper.

### Falsifiability

| Outcome | Implication |
|---|---|
| **All 4 OAT cells: VT threshold ∈ {50%, 70%, 100%} AND TF/MR threshold < VT** | H1+ confirmed robust to λ/γ. NotebookLM "knife-edge" critique fully rebutted. |
| **OAT cells show VT threshold flips to 0% or stays at 100% across cells** | λ/γ IS knife-edge artifact. P5 reframe to「positive-feedback family」still valid, but threshold magnitude IS λ/γ-determined (acknowledge in paper). |
| **TF/MR threshold > VT in some OAT cells** | H1+ rejected at boundary parameters. Threshold ranking is parameter-specific. P5 needs careful framing. |

---

## Implementation Plan

**Main thread** (this README): design + dispatch
**Worktree agent**: code + run + verdict

### Worktree agent scope

- Output dir: `experiments/k1262b/` (worktree branch)
- Files:
  - `k1262b.py` — fork `experiments/k1262/k1262.py` parameterizing KYLE_LAMBDA + VIX_FEEDBACK_GAMMA. Loop 5 OAT cells × 4 treatments × 3 adoption × 200 MC.
  - `k1262b_results.json` — per-(cell, treatment, adoption) aggregates, schema matching K1262.
  - `k1262b_oat_table.md` — 5 OAT cells × {VT/TF/MR/NoiseControl threshold} table (P5-style detector).
  - `k1262b_verdict.md` — falsifiability outcome (one of 3 above) + 3 caveats: (a) only 3 adoption levels not 7, (b) MC=200 vs K827v3's 500, (c) λ/γ ±50% may not span full reasonable range.

### Critical agent constraints

1. **No lookahead**: TF/MR signals use `returns[t-window:t]` (already verified in K1261/K1262)
2. **Seed propagation**: per-cell base_seed extends K1262 formula: `int(adoption*100000) + sim_idx + 42 + scaling*1000 + window*10 + lambda_idx*100 + gamma_idx*10`
3. **No knowledge.json / paper/*.tex / shared state writes** (worktree禁忌)
4. **Independent code review pending** — main thread re-reviews via `feature-dev:code-reviewer` (Codex CLI fallback) before knowledge.json update

### Computational estimate

- 12,000 sims × 35 ms/sim ≈ **7 min wall** (K1262 had Pool spawn overhead per cell — K1262b refactor to single Pool may halve this to ~4 min)
- Code review: ~3 min
- Total slot time: ~12 min

---

## Cross-link

- K1261 Phase 1: `experiments/k1261/`
- K1262 Phase 2 scaling × window sweep: `experiments/k1262/`
- K1262 verdict: `experiments/k1262/k1262_verdict.md`
- K1262 knowledge entry: `storage/memory/knowledge.json` item_id `f3b9edd4`
- K1261 knowledge entry: `storage/memory/knowledge.json` item_id `f1d85a74`
- P5 paper: `paper/vt-crowding-abm/main.tex`
- NotebookLM critique原文: `paper/vt-crowding-abm/review_history/v2/README.md`

---

## Success Criteria

1. ✅ K1262b worktree agent commits 4 files: `k1262b.py`, `k1262b_results.json`, `k1262b_oat_table.md`, `k1262b_verdict.md`
2. ✅ 5 OAT cells × 4 treatments × 3 adoption = 60 (cell, treatment, adoption) tuples × 200 MC = 12,000 sims
3. ✅ Verdict identifies one of 3 falsifiability outcomes
4. ✅ Detector calibration check: P5-style detector applied to baseline (λ=0.005, γ=200) reproduces VT 70% (matches K1262 calibration)
5. ✅ Wall time < 15 min
6. ✅ Independent code review PASS before knowledge.json update
