# K1262 — P5 Phase 2 Robustness Sweep (TF/MR scaling × window + softer detector)

**Status**: 🟡 **DESIGN proposed (2026-04-27)** — Phase 2 worktree dispatch pending.

**Date**: 2026-04-27
**Target paper**: P5 vt-crowding-abm
**Predecessor**: K1261 Phase 1 main (verdict H1+, code review CONDITIONAL PASS, knowledge.json item_id `f1d85a74`)
**Driver**: Phase 1 code review caveat #4 — "Phase 1 preliminary; H1+ direction robust but threshold magnitudes specification-dependent (TF/MR scaling=10 may be aggressive)". Plus verdict pending list items: (a) softer detector matching P5 paper criterion, (b) scaling sensitivity sweep before P5 paper rewrite.

---

## Motivation

### Phase 1 results recap (K1261)

| Treatment | Critical Adoption (strict detector) | Notes |
|---|---|---|
| VT_baseline | 100% | P5 paper reports 70% under softer criterion |
| TF (scaling=10, window=22) | 20% | 50% adoption: vol ×1500, kurt 1412, 40,199 price clamps |
| MR (scaling=10, window=22) | 50% (per detector) | 30% all 500 sims price collapse to 1e-23 |
| NoiseControl | null | Sharpe = 0.50 at 100%, validates framework |

**H1+ verdict**: positive-feedback crowding is generic (not VT-specific).

### Phase 2 objectives — falsifying H1+ robustness

If H1+ is true, threshold qualitative ranking (TF < VT, MR < VT, NoiseControl null) should hold across **reasonable** scaling/window choices, not just (scaling=10, window=22). Phase 2 tests:

1. **Scaling sensitivity**: at lower scaling (1, 3, 5) does TF threshold disappear? If yes → H1+ depends on knife-edge scaling=10 choice (weakens P5 reframe)
2. **Window sensitivity**: at different momentum windows (10, 22, 60), does TF/MR threshold qualitative ranking persist?
3. **Detector criterion**: under softer detector matching P5 paper (kurt > 1 + Sharpe sign flip), how does VT/TF/MR threshold compare? VT 70% would emerge under softer detector — if TF threshold also < 70% under softer, H1+ is robust to detector spec.

---

## Experimental Design

### Part A: Scaling × Window grid (16,800 new sims)

- TF/MR × scaling ∈ {1, 3, 5, 10} × window ∈ {10, 22, 60} = **24 cells**
- 7 adoption levels (matching K1261 Phase 1) × 100 MC = 700 sims per cell
- Total: 24 × 700 = **16,800 sims** (~3-5 min wall at K1261 Phase 1 throughput ~12.6ms/sim)
- Reuse `experiments/k1261/k1261_non_vt_ablation.py` simulation core; parameterize TF_SCALING / MOMENTUM_WINDOW
- No K827v3 baseline rerun (already in K827v3 stored 500-MC; reference for VT comparison)

### Part B: Softer threshold detector recompute (no new sims)

- Read existing `experiments/k1261/k1261_results.json`
- Apply 3 detector variants:
  1. **Strict** (Phase 1): Sharpe drop > 50% AND kurt > 10 AND vol amp > 50%
  2. **Softer (kurt-weak)**: Sharpe drop > 50% AND kurt > 1 AND vol amp > 50%
  3. **P5-style (Sharpe-only)**: Sharpe sign flip OR Sharpe drop > 70%
- Output cross-detector threshold table for VT_baseline + TF + MR

### Part C: Cross-cell threshold matrix (Part A output)

For each scaling × window cell, identify critical adoption per softer detector. Output:

| Scaling \ Window | 10 | 22 | 60 |
|---|---|---|---|
| 1 | TF: ?% / MR: ?% | ... | ... |
| 3 | ... | ... | ... |
| 5 | ... | ... | ... |
| 10 | TF: 20%* / MR: 30%* | ... | ... |

(* Phase 1 numbers re-validated under softer detector)

### Falsifiability tests for H1+

| Outcome | Implication for P5 |
|---|---|
| **TF threshold < VT threshold across all 12 cells under softer detector** | H1+ strongly supported. P5 paper rewrite to「positive-feedback family」reasonable |
| **TF threshold = VT threshold at some cells (e.g. scaling=1)** | H1+ partially supported. P5 paper can claim "TF crosses earlier under aggressive scaling" but threshold magnitude is spec-dependent |
| **TF threshold > VT threshold at most cells** | H1+ rejected at typical scaling. P5 paper claim of VT-specific channel partially rescued; threshold rank reverses with milder TF |
| **MR threshold extremely sensitive (e.g. only 30% under scaling=10, no threshold under scaling≤3)** | MR result was scaling-driven artifact; weakens H1+ but doesn't reject |

---

## Implementation Plan

**Main thread** (this README): design + dispatch brief
**Worktree agent**: code + run + verdict

### Worktree agent scope

- Output dir: `experiments/k1262/` (worktree branch)
- Files:
  - `k1262.py` — forks `k1261_non_vt_ablation.py`; parameterize TF_SCALING, MOMENTUM_WINDOW; loop over 24 cells
  - `k1262_results.json` — Part A raw aggregates per (treatment, scaling, window, adoption)
  - `k1262_softer_detector_table.md` — Part B output (3 detector variants × VT/TF/MR/Noise from K1261)
  - `k1262_threshold_matrix.md` — Part C output (TF/MR scaling × window → critical adoption under softer detector)
  - `k1262_verdict.md` — Phase 2 falsifiability verdict (which of 4 outcomes above; H1+ robust or spec-dependent)

### Critical agent constraints (per `.claude/rules/experiments.md`)

1. **No lookahead**: TF/MR signals use `returns[t-window:t]` (verified in K1261 Phase 1)
2. **Seed propagation**: per-cell base_seed = `int(adoption*100000) + sim_idx + 42 + scaling*1000 + window*10` (extends K1261 formula to disambiguate cells)
3. **No knowledge.json write** (worktree agent禁忌)
4. **No paper/*.tex modification** (worktree agent禁忌)
5. **Codex review pending** — main thread re-reviews code via fallback (`feature-dev:code-reviewer`) before knowledge.json update per `.claude/rules/experiments.md` SOP

### Computational estimate

- Phase 1: 10,500 sims in 132.3s = 12.6 ms/sim
- Phase 2 Part A: 16,800 sims × 12.6 ms = **~3.5 min wall**
- Phase 2 Part B: aggregate-only, no sims = **~30 sec**
- Phase 2 Part C: tabulate-only = **~10 sec**
- **Total wall**: <5 min

---

## Cross-link

- K1261 Phase 1 main: `experiments/k1261/k1261_phase1_main.py` (757L)
- K1261 simulation core: `experiments/k1261/k1261_non_vt_ablation.py` (903L) — fork source for K1262
- K1261 Phase 1 verdict: `experiments/k1261/k1261_phase1_verdict.md`
- K1261 raw results: `experiments/k1261/k1261_results.json`
- K1261 knowledge entry: `storage/memory/knowledge.json` item_id `f1d85a74`
- P5 paper: `paper/vt-crowding-abm/main.tex`
- P5 baseline: `paper/vt-crowding-abm/experiments/k827v3_abm_fixed_liquidity.py`
- Memory: `project_paper_portfolio_decisions_2026_04_27.md` (Tier B P5 priority 1)

---

## Open Questions (pre-dispatch)

1. **MOMENTUM_WINDOW=10 short-term momentum applicability**: 10-day momentum is a short-term CTA window. K1261 used 22 (1-month, conventional). 10 may produce noisier signal but also faster-reaction crowding. Inclusion justified for sensitivity check.

2. **Softer detector calibration**: P5 paper reports VT 70% threshold. If softer detector applied to K1261 VT_baseline gives 70%, that calibrates the detector. If softer gives 80% or 100%, P5's exact criterion remains opaque — Phase 2 then provides best-effort comparison, not exact match.

3. **N_MC = 100 per cell justification**: Phase 1 used 500 MC (best practice for threshold detection). Phase 2 uses 100 per cell × 24 cells × 7 adoption to keep wall < 5 min. With 100 MC bootstrap CIs are wider but threshold detection still reliable for qualitative ranking. If a cell shows borderline threshold in Part A, can rerun with 500 MC for that specific cell.

4. **No Phase 2b (λ/γ OAT) in this dispatch**: deferred to K1262b. Rationale: scaling × window sensitivity addresses caveat #4 directly; λ/γ OAT addresses different mechanism question (parameter knife-edge vs strategy-specification knife-edge). If Phase 2 (this K1262) shows H1+ robust, λ/γ OAT becomes optional confirmation; if Phase 2 shows H1+ spec-dependent, λ/γ OAT is needed before P5 rewrite.

---

## Success Criteria

1. ✅ K1262 worktree agent commits 4 files: `k1262.py`, `k1262_results.json`, `k1262_softer_detector_table.md`, `k1262_threshold_matrix.md`, `k1262_verdict.md`
2. ✅ Verdict identifies which of 4 falsifiability outcomes applies (H1+ robust / partially supported / rejected / MR-only artifact)
3. ✅ Softer detector recompute gives VT_baseline threshold consistent with P5 paper's 70% (within 10%-adoption tolerance) → calibration check passes
4. ✅ Independent code review of `k1262.py` PASS before knowledge.json update (Codex CLI fallback to `feature-dev:code-reviewer` per `.claude/rules/experiments.md` 2026-04-27 update)
5. ✅ Main thread synthesis: K1261 + K1262 → updated knowledge entry / P5 narrative recommendation to user (need confirm to reframe paper)
