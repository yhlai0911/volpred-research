# Codex 4th-Model Adversarial Review — v7 README

**Timestamp**: 2026-06-30 (台灣時間)
**Codex version**: codex-cli 0.142.3
**Predecessor**: v6 codex_3rd_review.md (Verdict: FAIL, 5 findings)

## Verdict: PASS

## v6 carry-over verification

### F1 CRITICAL — RESOLVED

The v6 error was the false identity `VIX_timing_contrib (= PureVT_excess_vs_BH)`. K1458 now states the additive identity explicitly at `experiments/k1458_h1_trough_decomposition/README.md:26-42`: daily `PureVT_excess_t = VIX_timing_contrib_t + TSMOM_hedge_contrib_t`, window `sum(PureVT_excess) = sum(VIX_timing) + sum(TSMOM_hedge_full)`, and the warning that `VIX_timing_contrib` is not equal to `PureVT_excess_vs_BH` except when the hedge term is zero.

`jq '.per_asset.SPY[1].headline'` confirms the requested SPY 2020-03 identity:

- `pure_vt_excess_bh_total_arith = 0.037654210238158604`
- `vix_timing_total_arith = -0.08433252915648443`
- `tsmom_hedge_total_arith = 0.12198673939464298`
- sum check: `-0.08433252915648443 + 0.12198673939464298 = 0.037654210238158556`
- numerical difference: `4.85722573273506e-17`

This resolves the decomposition-identity defect.

### F2 HIGH — RESOLVED

`paper/vt-trend-following/body_v3.tex:258` no longer uses K1458 as direct MDD-path attribution. It frames the K1458 trough arithmetic as "consistent with this caution" and says it is "descriptive evidence rather than a direct PureVT-versus-buy-and-hold drawdown-path attribution."

The earlier overreach is therefore corrected in the body narrative. The remaining statement that MDD retention is consistent across the five assets is tied to K1192 point estimates, while the K1458 mechanism interpretation is properly scoped as descriptive trough-window arithmetic.

### F3 HIGH — RESOLVED

The body no longer says the 2009 mechanical hedge channel was simply absent or cleared. `paper/vt-trend-following/body_v3.tex:258` states that in March 2009 three of five assets show zero hedge contribution, while the remaining two are small and mixed sign: 50/50 SPY/GLD `+2.1` pp and QQQ `-3.5` pp. It then explicitly says the channel is "not universal" but also cannot be "declared entirely absent in 2009."

This is the correct strength of conclusion for the JSON evidence.

### F4 MEDIUM — RESOLVED

K1458 now gives conditional, JSON-side quantification at `experiments/k1458_h1_trough_decomposition/README.md:67`: 3/5 assets (SPY, DIA, IWM) have `tsmom_hedge_total_arith = 0` across the 127-day 2009-03 window, while 50/50 SPY/GLD has `+0.021107601066936293` and QQQ has `-0.03500289511543407`.

The `jq` check of 2009 per-asset headline values gives:

- SPY: full hedge `0`, negative-signal partition `0`
- DIA: full hedge `0`, negative-signal partition `0`
- IWM: full hedge `0`, negative-signal partition `0`
- 50/50: full hedge `0.021107601066936293`, negative-signal partition `0.11914442745927381`
- QQQ: full hedge `-0.03500289511543407`, negative-signal partition `0.03262772268716604`

The README also correctly labels the beta-clip interpretation as indirect and conditional because `k1458_results.json` does not store the beta path. That is sufficient to resolve the v6 objection: the text no longer presents beta clipping as directly observed, and it supplies the available JSON-side evidence.

### F5 MEDIUM — RESOLVED

The closure-style body language is gone. `paper/vt-trend-following/body_v3.tex:258` uses "descriptive evidence" and explicitly denies direct drawdown-path attribution; `paper/vt-trend-following/body_v3.tex:528` warns that point estimates above 100% are not a license to claim a stronger standalone insurance technology.

K1458 also removed the v6-problematic `CLOSURE` / `CLEARED` framing. The remaining K1458 language at `experiments/k1458_h1_trough_decomposition/README.md:69-87` uses "NOT validated for 2009", "PARTIALLY validated for 2020", "conditional caveat", and asset-count qualifications. That is still assertive, but it is no longer causal-closure language and is backed by the per-trough decomposition numbers.

## New findings (only list ones NOT carried over from v6; explicit "none" if none)

None.

## Recommendation

advance to ready_for_submission_candidate
