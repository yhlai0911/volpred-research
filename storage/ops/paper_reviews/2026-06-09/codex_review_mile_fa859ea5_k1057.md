# Codex Source-Code Review — mile_fa859ea5 / K1057

- **Article**: 把 SPY 波動拆成「平常」跟「跳一下」，預測有變準嗎？60 天 NULL
- **Experiment**: K1057 (SPY 5-min HAR-RV-J, 2026-01-14 → 2026-04-10, 30-day OOS expanding window)
- **Reviewer**: Codex CLI 0.137.0 (gpt-5.4 medium)
- **Review timestamp**: 2026-06-09 21:14 台灣時間
- **Verdict**: **CONDITIONAL_PASS / amend**

## Critical bugs

1. **BN-S z-statistic implementation** (`experiments/k1057/k1057.py:119-126`)
   - Code computed `rel_jump = (rv - bpv)/rv` but `z_stat` uses unnormalized `rv - bpv`; denominator missing standard `max(1, TPQ/BPV^2)` form.
   - Impact: `8/60` jump count + per-day p-values rest on this implementation. Magnitude unknown until recomputed.
   - Fix: re-implement canonical relative BN-S z-stat OR rename to absolute-difference variant + amend article.

2. **QLIKE formula** (`experiments/k1057/k1057.py:453-459, 558-562`)
   - Implementation: `actual/predicted + log(predicted)` (constant-shifted).
   - Patton (2011) canonical: `σ²/h - log(σ²/h) - 1`.
   - Impact: model rankings unchanged (constant cancels), but article claims "Patton (2011) QLIKE" — imprecise.
   - Fix: either swap to canonical OR rename "constant-shifted QLIKE-equivalent loss" in article.

## Methodology concerns (non-blocking)

- HAR lookahead: **clean** (x_test uses t-1; y_train aligned to 1..t-1).
- HAR rolling `min_periods=1` deviates from canonical 5/22-day windows (shortened in first 21 days). Affects early estimation only, not OOS.
- GJR-GARCH: no lookahead; uses d-1 prior 2000 days correctly. HAR/GJR window mismatch (expanding vs 2000-day rolling) is design choice, not bug.
- DM test: HAC variance used (not Harvey 1997 small-sample correction). p-values standard t-distribution. If article claims "Harvey 1997 |t|>3.0", language imprecise.
- Spearman correlation: computed on `common_dates` (30-day OOS), not full 60-day sample. Article should clarify window.
- Overnight share 32.7%: implementation matches stated formula. No issue.

## Article overclaims

- **NULL narrative correct** — HAR-RV-J vs HAR-RV DM truly non-significant; matches code output.
- **PRELIMINARY status honestly stated** in code + results JSON + article.
- **No borderline hype** — no DM-marginal claims oversold as significant.
- **Issues to amend**:
  - `8/60` jump count depends on suspect BN-S implementation → either recompute with canonical or hedge claim.
  - "Patton (2011) QLIKE" phrasing needs constant-shifted clarification or formula swap.

## Recommendation

**amend** (not retract). Core NULL narrative, lookahead-clean, HAR/GJR OOS alignment all hold. Required follow-up:

1. Recompute BN-S z-stat with canonical relative form → confirm `8/60` figure stays / changes.
2. Either swap QLIKE to canonical Patton OR rename "constant-shifted QLIKE-equivalent loss" in article.
3. Add clarifying note: Spearman uses 30-day OOS (not full sample).
4. Add clarifying note: DM uses HAC, not Harvey (1997) small-sample correction.

Re-publish article with above amendments. If 8/60 changes materially after BN-S fix, issue correction note.
