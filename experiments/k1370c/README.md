# K1370c — N_start=10 vs N_start=100 Sensitivity Micro-Test

## Motivation

K1370 v2 Codex review (CONDITIONAL PASS, 2026-05-16) flagged residual concern:
reduced multistart `N_start=10` (vs canonical `N_start=100` per K1302/K1302b) might
introduce optimization noise that inflates bootstrap CI bounds. The
tractability rationale was sound (10,000 × N_start_100 ≈ 15h vs 1.5h at
N_start=10), but the assumption that 10-start was "good enough" was untested.

## Design

- Pick 20 evenly-spaced replicates from K1370 v2 (B=1000) — deterministic
  selection step = 50, indices 0/50/100/.../950
- Re-run each at `N_start=100` keeping all other variables **identical**:
  - Same `boot_seed` (= `seed_base + rep_idx`, guarded by explicit assert)
  - Same `block_length=252`, same `seed_base=42`
  - Same `returns_by_ticker` (loaded via same `k1370.load_*` pipeline)
  - Same MD5 ticker sub-seed (deterministic per K1370 v2 fix)
- Compare per-replicate amplification ratio: `amp_n100 - amp_v2`

## Verdict Logic

- **PASS** if `max_abs_delta < 0.1×` AND `mean_abs_delta < 0.05×`
  → N_start=10 sufficient, Codex residual concern closed
- **FAIL** if `max > 0.5×` OR `mean > 0.1×`
  → re-run K1370 with N_start=100
- **CONDITIONAL** otherwise — disclose in paper appendix

## Results

| Metric | Value | Threshold | Status |
|---|---|---|---|
| max_abs_delta | 0.092× | < 0.1× | ✅ PASS |
| mean_abs_delta | 0.005× | < 0.05× | ✅ PASS |
| median_abs_delta | 1.9e-5× | — | virtually identical |
| n_delta > 0.1× | 0 / 20 | — | — |
| n_delta > 0.5× | 0 / 20 | — | — |
| v2 median amp | 3.839 | — | — |
| N100 median amp | 3.839 | — | identical |
| v2 mean amp | 4.118 | — | — |
| N100 mean amp | 4.123 | — | 0.1% diff |

**Verdict: PASS** — N_start=10 sufficient; Codex residual concern (K1370 v2
CONDITIONAL PASS) is **closed**. K1370 v2 CI [2.31, 6.61] stands as canonical
Paper 2 §3.2 reference.

## Process Notes

- Codex CLI hung 2× (32min + 10min, 0-byte output both times). Diagnostic per
  `.claude/rules/experiments.md` L36-46 fallback: code-reviewer subagent
  reviewed wrapper, flagged hold-constant assertion gap → fixed with explicit
  assert `derived_boot_seed == v2_record_boot_seed`.
- Runtime 490s (~8 min) for 20 reps × 10 series × 100 multistart = 20,000 arch
  fits. Linear extrapolation to full B=1000 × N_start=100 = ~7h (consistent
  with v2's documented 15h estimate; v2's 8x speedup from N_start=10 confirmed
  in practice).
- Only 1/20 reps showed non-trivial delta (+0.092 at v2_idx=550 / boot_seed=592)
  — likely from 2412.TW flat-surface basin selection (per K1370 v2 noted weak
  multistart convergence for that stock). At N_start=100, deeper basin found;
  effect on amplification still <0.1×.

## Files

- `k1370c_nstart_sensitivity.py` — wrapper script
- `k1370c_results.json` — per-replicate comparison + verdict
- `run.log` — execution log

## Closes

- K1370 v2 Codex residual concern (CONDITIONAL_PASS → de facto PASS for paper
  citation purposes)
- Knowledge.json K1370 entry's `follow_up_suggested[1]` (N_start sensitivity)
