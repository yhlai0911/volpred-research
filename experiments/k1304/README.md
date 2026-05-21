# K1304: K1257 BMA 0050.TW H1 FAIL — TAIFEX microstructure hypothesis test

[提出: Claude (autonomous backlog from K1257 closure asymmetry + Paper 3 reframe motivation), 執行: TBD worktree agent]

## Motivation

K1257 BMA closure (knowledge entry `c4db347a`, Codex CONDITIONAL PASS 2026-04-29) reports:

  H1 (BMA > GJR-t single best): **PARTIAL**
    - SPY: PASS (DM-Harvey t = -3.40)
    - GLD: PASS (DM-Harvey t = -3.38)
    - 0050.TW: **FAIL** — posterior collapses onto GJR-t early, BMA degenerates to GJR-t

Why does **0050.TW alone** fail when SPY and GLD pass with t > |3|? The Codex review treats this as descriptive — "posterior degenerates within ~500 days" — but doesn't ask **why 0050.TW degenerates faster than SPY or GLD**. Three candidate explanations have ROI for both Paper 2 (taiwan-vt) and Paper 3 (currently in reframe-pending state per research_program.md L398-420):

1. **TAIFEX microstructure (H_micro)**: Taiwan equity index has thicker tails / different jump distribution / lower-volume tail days, so a single fat-tailed spec (GJR-t) absorbs the relative-skill differential of the other 5 candidates faster than on SPY/GLD.

2. **Sample-size asymmetry (H_sample)**: 0050.TW OOS sample is shorter or has more refit-cycle holidays than SPY/GLD, so log-posterior accumulates fewer effective updates → faster concentration.

3. **Candidate-pool fit asymmetry (H_pool)**: 5 of the 6 candidates were never reasonable for 0050.TW (e.g., GARCH-N severely mis-specified), so BMA was de-facto picking from 1-2 viable models from day-1 — degeneracy is not regime-induced, it's spec-induced.

Distinguishing these matters because:
- H_micro → suggests Taiwan needs a different candidate pool (e.g., jump-augmented HAR, asymmetric-t with skew) → feeds Paper 2 §5 revision (Paper2_section5_rewrite pending in next_tasks)
- H_sample → trivial fix, re-run with matched OOS days → may resurrect 0050.TW H1
- H_pool → suggests our BMA pool is fragile for emerging markets generally → has Paper 3 reframe implications

## Hypothesis

**H_K1304 (decomposition)**: At least one of {H_micro, H_sample, H_pool} dominates the 0050.TW H1 FAIL.

Operationalization:

- **H_sample test**: re-run BMA on 0050.TW with SPY-matched start date and equal-length OOS; if H1 now PASS → H_sample wins
- **H_pool test**: leave-one-out — re-run BMA on 0050.TW dropping each candidate in turn; if removing any single candidate (likely GJR-t) flips H1 to PASS, posterior was carrying dead weight from non-competitive specs
- **H_micro test**: estimate per-candidate fitted log-likelihood-per-day on 0050.TW vs SPY/GLD; if 0050.TW's GJR-t LL-per-day advantage over GARCH-N is ≥2× larger than SPY/GLD's advantage, GJR-t was dominantly best from day-1 (microstructure-driven)

## Design

| Item | Setting |
| --- | --- |
| Reuse | K1257 baseline candidate pool (GARCH-N / GJR-N / GJR-t / EGARCH-N / HAR-ABS / A4f-IV²) |
| Asset | 0050.TW (with SPY/GLD as control) |
| Period | K1257 canonical OOS 2020-2026 |
| Treatments | (a) full K1257 baseline replication, (b) SPY-window-matched, (c) leave-one-out × 6, (d) per-candidate LL-per-day diagnostic |
| Metrics | DM-Harvey vs GJR-t, posterior weight trajectory, concentration-hitting-time (HHI > 0.9) |
| Seed | 42, plus K1257-MAJOR-1 fix (invalid-model day → log_w = -inf before normalize, per pending K1257+K1258 family fix slot) |

## Lookahead discipline

- Inherits K1257 forecast-then-update timing
- Per-candidate LL-per-day uses only [s..t-1] return window
- Concentration hitting-time computed forward only

## Differentiation vs prior K

- **K1257**: established H1 FAIL on 0050.TW but did not decompose **why**
- **K1258 (forgetting-factor BMA)**: tested if discounting past evidence rescues H1 — got Harvey FAIL even for 0050.TW best λ (CONDITIONAL PASS knowledge entry); ortho to K1304 which keeps λ=1 but varies candidate pool / window
- **K1216c (developed-markets multistart)**: established symmetric-refinement principle — K1304 applies same principle (treatments b/c match SPY-window / drop unfair candidates)

## Success criterion

- ≥1 of {H_sample, H_pool, H_micro} produces decisive signal (numeric criterion stated per test above)
- If H_micro dominates → next_tasks gets K1305b candidate "0050.TW jump-augmented BMA pool"
- If H_pool dominates → K1257 family fix expanded to "pool-pruning before posterior collapse"
- If H_sample dominates → K1257 erratum row in Paper 2 §5 (matched-window 0050.TW H1 result supersedes original)
- Codex PASS before knowledge entry

## Mission 5 sanity

Primary beneficiary: **Mission 2 (research) + Mission 3 (Paper 2 §5)**. Paper 2 §5 rewrite (pending in next_tasks: Paper2_section5_rewrite) cannot be finalized while 0050.TW BMA H1 FAIL is unexplained — reviewer R1 would ask exactly this question. Secondary: Mission 1 (article — a "why does Taiwan market reject BMA?" piece is content-rich).

## References

- knowledge entry `c4db347a` (K1257 closure)
- knowledge entry `b3f...` (K1258 forgetting-factor closure)
- research_program.md L500 Paper Portfolio Status — Paper 2 entry
- methodology `.claude/rules/experiments.md` §"跨市場比較必 symmetric refinement"
- K1216c (developed-markets symmetric multistart precedent)
