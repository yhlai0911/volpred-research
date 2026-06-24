# K1545 Code Review

**Date**: 2026-06-24
**Reviewer source**: `feature-dev:code-reviewer` subagent (K1259 FALLBACK)
**Why fallback**: Codex CLI 0.141.0 invocation hung (>5min, output file 0 bytes)
because another parallel codex session was monopolizing the shared
companion runtime (PID 84822, since 6:09PM previous day — unrelated test). Per
K1259 protocol, fallback to `feature-dev:code-reviewer` is allowed; verdict bar
unchanged.

## Verdict: CONDITIONAL_PASS

## Reviewer findings

### (a) Lookahead audit — CLEAN
- `build_rv`: `rv_past` uses past returns [t-4..t]; `rv_fwd = rv_past.shift(-5)`
  yields std of returns at [t+1..t+5] strictly forward. ✓
- `event_study_rv` baseline: `s_past.loc[:t].iloc[:-6].tail(24)` excludes
  [t-5..t] and yields the 24 obs window [t-29..t-6]. No leakage. ✓
- Event-date alignment: `t = first trading day >= event_date`; post-RV uses
  strictly future window. ✓

### (b) HAC Newey-West — CORRECT
- Bartlett kernel with weights `1 - L/(lag+1)`; `gamma_L = (xc[L:] @ xc[:-L])/n`;
  `S = gamma0 + 2 * sum_L w_L gamma_L`; `var_mean = S/n`. Textbook formula. ✓

### (c) Seed — COMPLIANT
- `RNG_SEED = 20260624` used in `np.random.default_rng(seed)`. Recorded in
  `results.json`. No unseeded randomness. ✓

### (d) K1355 compliance — COMPLIANT
- `cross_asset_aggregated_test` aggregates per-date diff (mean across assets)
  BEFORE HAC on the date-level series. Not stacked asset-day. ✓

### (e) Results-README consistency — MATCHES
- All numbers in README table match `k1545_results.json` exactly:
  KRBN 22/+0.0377/0.747, GRN 24/+0.0633/0.617, KCCA 20/+0.0093/1.000,
  XLE 25/-0.0432/0.312, XLU 25/-0.0153/0.548, cross-asset 24/+0.0531/0.071.

### (f) Honesty — PASS
- EEX paywall limitation prominently disclosed in README + results.json.
- `_verdict()` unconditionally returns `PRELIMINARY` when n_events < 50,
  regardless of p-value. No overclaiming.

## Required README clarifications (applied)

1. README claimed baseline window `[t-30, t-6]` but implementation yields the
   24-obs window `[t-29, t-6]` (off-by-one in nominal description, not a bug).
   → Fixed in README §Method.
2. Cross-asset `n_assets_per_date_mean = 2.75` not explained (KCCA inception
   2021-10-05 means earlier events have only 2 of 3 assets).
   → Added one-sentence clarification in README §Results cross-asset paragraph.

## Implications

- Code logic is correct; no lookahead, no seed leakage, K1355 compliant.
- Verdict CONDITIONAL_PASS reflects the documentation discrepancies (now fixed)
  and the hard PRELIMINARY tag (n_events=25 < 50).
- Primary-Codex re-verification recommended once shared runtime frees up
  (per K1259 v2 hard rule: subagent fallback PASS ≠ primary-Codex PASS).
  Will be done in a follow-up main-thread tick when CLI is unblocked.
