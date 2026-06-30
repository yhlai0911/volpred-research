# Codex Primary-Path Re-verification — v7 (K1259 protocol)

**Timestamp**: 2026-06-30 18:10 台灣時間
**Codex version**: codex-cli 0.142.3
**Predecessor**: codex_4th_review.md (subagent fallback v1, CONDITIONAL_PASS → v7.1 revision)
**Purpose**: Upgrade subagent-fallback verdict to canonical primary-path Codex verdict per K1259.

## Verdict: PASS

All five v6 Codex findings are genuinely resolved after the v7.1 minor revision, and both LOW new findings from the subagent fallback review are addressed. The K1458 README now states the additive identity correctly, scopes trough-window/MDD-path language as inference rather than direct path decomposition, avoids closure framing, and makes the beta-clip claim conditional on indirect JSON evidence. The body text keeps K1458 descriptive at the trough-window paragraph while reserving broader synthesis language for K1376/K1192/K687 aggregate evidence.

## v6 Finding Re-verification

### F1 (CRITICAL) — RESOLVED

K1458 README explicitly states the additive daily and window identities as `PureVT_excess = VIX_timing_contrib + TSMOM_hedge_contrib` and `sum(PureVT_excess) = sum(VIX_timing) + sum(TSMOM_hedge_full)` at `experiments/k1458_h1_trough_decomposition/README.md:26-35`. The README also warns that `VIX_timing_contrib` is not equal to `PureVT_excess_vs_BH` except when `TSMOM_hedge_full = 0` at `experiments/k1458_h1_trough_decomposition/README.md:35`. Numeric spot checks match `k1458_results.json`: SPY 2020 has `0.037654210238158604 = -0.08433252915648443 + 0.12198673939464298`, and QQQ 2020 has `-0.11017489581924826 = -0.14058035785206002 + 0.030405462032811702`, matching the rounded table at `experiments/k1458_h1_trough_decomposition/README.md:37-40`.

### F2 (HIGH) — RESOLVED

The two previously over-strong K1458 README sentences have been rewritten. The 2020 interpretation now says the shallower-peak/not-faster-rebound reading is an **inference** from window-summed arithmetic, not a direct path-level measurement, at `experiments/k1458_h1_trough_decomposition/README.md:80`. The narrative implication repeats the same limitation, stating that the drawdown-peak interpretation is inference consistent with window arithmetic rather than direct synchronized-path measurement at `experiments/k1458_h1_trough_decomposition/README.md:86`.

### F3 (HIGH) — RESOLVED

The old `NO (CLEARED)` / "no mechanical hedge" closure is absent from the checked body and K1458 README. The body now says the mechanical hedge is "not universal" but cannot be declared entirely absent in 2009, and labels K1458 as descriptive trough-window arithmetic rather than direct drawdown-path attribution at `paper/vt-trend-following/body_v3.tex:258`. The K1458 README likewise reports 2009 as mixed evidence, with three clipped zero-hedge assets and two small offsetting contributions, at `experiments/k1458_h1_trough_decomposition/README.md:67-69`.

### F4 (MEDIUM) — RESOLVED

The beta-clip claim is conditional and indirect: the README states that the beta path is not stored in JSON and that the conclusion depends on the zero hedge not being an offsetting-sum coincidence at `experiments/k1458_h1_trough_decomposition/README.md:67`. Specific JSON checks support the claim: SPY, DIA, and IWM each have 2009 `tsmom_hedge_total_arith = 0`, and their `tsmom_neg_partition` and `tsmom_nonneg_partition` hedge sums are also `0.0`. This is consistent with clip-to-0 for 3/5 assets, while staying short of a direct beta-path measurement.

### F5 (MEDIUM) — RESOLVED

The K1458 body paragraph is descriptive and cautious at `paper/vt-trend-following/body_v3.tex:258`, explicitly avoiding direct PureVT-versus-buy-and-hold drawdown-path attribution. The broader synthesis at `paper/vt-trend-following/body_v3.tex:528` is attached to K1376/K1192/K687 aggregate evidence, not the K1458 H1 trough-window claim, and includes the required caution that `>100%` point estimates are not a license to claim stronger standalone insurance technology. Search found no remaining `CLOSURE`, `CLEARED`, or "確實有貢獻" closure-style language in the checked body/K1458 files.

### New Finding A (LOW) — RESOLVED

The v7 self-audit no longer overclaims that line 528 itself is "descriptive"; it now says line 528 uses synthesis language attached to K1376/K1192/K687 and includes the `>100%` caution at `paper/vt-trend-following/review_history/v7/README.md:53`.

### New Finding B (LOW) — RESOLVED

The legacy compute-queue command no longer contains `"H1 closure verdict"`; it now uses `"H1 PARTIAL SUGGESTIVE EVIDENCE verdict (non-closure language; see v7 review_history)"` at `experiments/k1458_h1_trough_decomposition/README.md:109`.

## New Findings (if any, primary-path only)

None.

## Recommendation

PASS: the subagent-fallback PASS is upgraded to canonical primary-path Codex PASS. The v7.1 package satisfies the K1259 re-verification target, and the narrative state can advance to `ready_for_submission_candidate`.
