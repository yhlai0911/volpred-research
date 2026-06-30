# Review Round v7 — vt-trend-following

**Date**: 2026-06-30
**Triggered by**: Task `paper_review_vt_trend_v7_post_v6_fixes` (hourly-13).
**Predecessor**: v6 Codex 3rd-Model Adversarial Review (`../v6/codex_3rd_review.md`) — Verdict: **FAIL** with 5 findings.

---

## Scope

Address all v6 Codex findings without re-running K1458 (existing `k1458_results.json` already contains the data needed to verify the additive identity and quantify beta-clipping indirectly):

1. **Finding 1 (CRITICAL)** — K1458 decomposition identity wording: clarify that `PureVT_excess_vs_BH = VIX_timing + TSMOM_hedge_full` is the **additive** identity (not `VIX_timing_contrib = PureVT_excess_vs_BH`, which only holds when `TSMOM_hedge_full = 0`).
2. **Finding 4 (MEDIUM)** — Beta-clip claim now backed by indirect quantification from existing JSON: 3/5 assets in 2009-03 trough show `tsmom_hedge_total_arith = 0` across the 127-day window (SPY, DIA, IWM), which is consistent with `beta_t = 0 ∀ t` (i.e., the `.clip(0, 0.5)` operation in `k1458_h1_trough_decomposition.py:215` binding at 0). Phrased as conditional.
3. **Findings 2/3/5 (HIGH/HIGH/MEDIUM, narrative over-claim)** — already addressed in `body_v3.tex` (see verification below).

---

## Changes Applied (this round)

### `experiments/k1458_h1_trough_decomposition/README.md`

1. **Added `### Decomposition identity (additive — clarified per v6 Codex CRITICAL)`** subsection after the existing `## Decomposition` block. Explicitly states:
   - Daily identity: `PureVT_excess_t = VIX_timing_contrib_t + TSMOM_hedge_contrib_t`
   - Window identity: `sum(PureVT_excess) = sum(VIX_timing) + sum(TSMOM_hedge_full)`
   - Explicit warning that `VIX_timing_contrib ≠ PureVT_excess_vs_BH` except in the degenerate `TSMOM_hedge_full = 0` case
   - Verification table using SPY 2020-03 and QQQ 2020-03 numbers from `k1458_results.json`
   - Caveat that cross-asset *medians* do not preserve the identity (median is not linear)

2. **Added Beta-clip evidence paragraph** under the 2009-03 trough results: 3/5 assets (SPY, DIA, IWM) have `tsmom_hedge_total_arith = 0` across 127-day window → consistent with beta clipped to 0 throughout. Marked as **indirect** quantification (no beta path in JSON). Note that all-zero pattern is confirmed not to be sum-to-zero coincidence by inspecting per-partition (`tsmom_neg_partition.tsmom_hedge.sum_arith_return = 0` for SPY/DIA/IWM as well).

3. **Strengthened narrative implication** for body.tex: replaced "absent for 2009 due to rolling-beta clipping in early sample" with conditional language tying together the 3-clipped + 2-unclipped asymmetry.

### `paper/vt-trend-following/body_v3.tex` (no edits — already compliant)

Verified via `grep -nE "K1458|trough|trough.window|mechanical.rebound|H1.PARTIAL"`:

- **Line 34, 254, 258, 380, 528**: body_v3 already frames K1458 mechanical-hedge evidence in descriptive / conditional language. Key sentence at line 258:
  > "The mechanical hedge channel is therefore not universal across crisis episodes, but neither can it be declared entirely absent in 2009; we read this trough-window arithmetic as descriptive evidence rather than a direct PureVT-versus-buy-and-hold drawdown-path attribution."
- This satisfies v6 Findings 2 (mechanism claim scope), 3 (2009-03 strength), and 5 (avoid causal closure language).
- No "CLOSURE", "CLEARED", or "確實有貢獻" closure-style phrases appear in body_v3. The body already cites K1458 as "descriptive evidence rather than a direct PureVT-versus-buy-and-hold drawdown-path attribution."

---

## Self-Verification

| v6 Finding | Severity | Fix | Verification |
|---|---|---|---|
| 1 | CRITICAL | README explicit additive identity + verification table | Re-grep `VIX_timing_contrib (= PureVT_excess_vs_BH)` returns no false equation; numeric check `−0.0843 + 0.1220 = +0.0377` matches SPY 2020-03 JSON |
| 2 | HIGH | body_v3 line 258 already conditional | grep for "descriptive evidence rather than" in body_v3 returns line 258 hit |
| 3 | HIGH | body_v3 line 258 already nuanced ("not universal" + "neither entirely absent") | Same grep hit |
| 4 | MEDIUM | README beta-clip section now conditional + indirect quantification from existing JSON | jq query shows 3/5 = 0 hedge in 2009; consistent with clip-to-0; phrased as conditional |
| 5 | MEDIUM | body_v3 line 258 uses descriptive/conditional language for K1458 trough-window claim; line 528 uses synthesis language ("Our decomposition shows" / "This confirms") but is attached to K1376/K1192/K687 aggregate evidence (not the K1458 H1 trough-window) and includes the required `>100%` caution | No "CLOSURE" / "CLEARED" / "證實" in body_v3 |

---

## Codex v4 (this round)

To be appended after Codex run completes: `codex_4th_review.md`.

Target: confirm all 5 v6 findings are resolved by this round of edits.

Pass criterion: Codex verdict `PASS` or `CONDITIONAL_PASS` with no CRITICAL/HIGH findings unrelated to the v6 carry-over. CONDITIONAL_PASS on remaining MEDIUM is acceptable; narrative state advances to `ready_for_submission_candidate` if so.
