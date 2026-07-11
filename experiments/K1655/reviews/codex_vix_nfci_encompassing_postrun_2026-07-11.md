# K1655 VIX/NFCI encompassing addendum — post-run review (2026-07-11)

## Verdict

**PASS, limited to the double-null conclusion.**

The evidence supports two narrow statements for the 2011–2026 true-PIT sample:

1. VIX-only has lower point-estimate pinball loss than NFCI-only at all three primary
   horizons, but none of the paired comparisons passes the pre-registered statistical gates.
2. A joint VIX+NFCI forecast does not show robust incremental NFCI information beyond VIX
   under the fixed-window CQFE design.

Failure to reject incremental value is not proof that VIX fully encompasses or subsumes
NFCI. The review therefore rejects any universal dominance or substitution claim.

## Independent numeric verification

- Forecast artifact: 4,970 rows; SHA-256
  `04a17e6741dd7ec3da2f15523a8675d5410bcaaaaab7fd015ac115558270e356`.
- Scheme counts: expanding bridge 1,580; rolling R=300 1,430; rolling R=400 1,130;
  rolling R=500 830. Every `(scheme, horizon, origin)` key is unique.
- All NFCI point-in-time gates, `target_end > origin`, and
  `latest_training_target_end < origin` pass.
- Pinball losses recomputed from realized values and serialized forecasts differ by less
  than `2e-16` from the artifact.

### Frozen expanding VIX-only versus NFCI-only

| Horizon | n | VIX loss | NFCI loss | VIX improvement | canonical DM t | Holm p |
|---:|---:|---:|---:|---:|---:|---:|
| 1 week | 536 | 0.002668862067 | 0.003076212082 | +13.241935% | -1.607802 | 0.325405 |
| 4 weeks | 530 | 0.005848477373 | 0.006214759281 | +5.893742% | -1.538484 | 0.325405 |
| 12 weeks | 514 | 0.010240433056 | 0.010420225358 | +1.725417% | -0.638165 | 0.523651 |

All three point estimates favor VIX, but no cell passes `t < -3` or Holm-adjusted
`p < 0.05`. The 12-week loss differential also changes sign across sample halves.

### Rolling R=400 VIX+NFCI versus VIX-only

| Horizon | n | Joint loss | VIX loss | Joint improvement | canonical DM t |
|---:|---:|---:|---:|---:|---:|
| 1 week | 386 | 0.002930163694 | 0.002825076115 | -3.719814% | +0.609504 |
| 4 weeks | 380 | 0.007119879259 | 0.006914213922 | -2.974530% | +0.436975 |
| 12 weeks | 364 | 0.013677903314 | 0.011939424707 | -14.560824% | +1.378642 |

These nested-model DM results are diagnostics only. All three point estimates favor the
VIX-only forecast and none supplies positive evidence for incremental NFCI information.

## CQFE method review

- The primary CQFE forecast paths use a fixed rolling window of exactly 400 admissible
  observations, refit weekly. This avoids the expanding-recursive estimation setup excluded
  by the Giacomini–Komunjer / Giacomini–White fixed-estimation-window asymptotics.
- Each training row obeys `j + H < i`; the latest training target ends strictly before its
  forecast origin.
- The combination regression uses `[1, q_VIX, q_VIX+NFCI]`. The VIX-encompassing point null
  is `(0, 1, 0)`, with a separate `lambda_joint = 0` subtest to prevent affine
  recalibration from being mislabeled as incremental NFCI information.
- `full_roots` and `reverse_roots` legitimately share the same centered three-dimensional
  bootstrap-root distribution because both are full-rank point restrictions; their observed
  Wald thresholds differ.
- All three 1,999-rep circular moving-block bootstraps completed without failure and were
  independently reproduced exactly.

| Horizon | Full-null bootstrap p | Full-null Holm p | `lambda_joint=0` bootstrap p | Subtest Holm p |
|---:|---:|---:|---:|---:|
| 1 week | 0.7990 | 0.8220 | 0.9750 | 1.0000 |
| 4 weeks | 0.4110 | 0.8220 | 0.8975 | 1.0000 |
| 12 weeks | 0.2410 | 0.7230 | 0.6335 | 1.0000 |

The H=4 and H=12 analytic chi-square p-values are much smaller than the bootstrap values.
Independent reconstruction found no branch, singularity, or transcription error: the
studentized block-root distributions are extremely heavy-tailed at the 5% quantile. Because
the analytic covariance uses a single residual sparsity rather than a fully general
conditional-density term, the block bootstrap is the primary finite-sample inference and the
chi-square p-values remain diagnostic only.

## Required reporting language

Report **no robust VIX dominance** and **no evidence of NFCI incremental information beyond
VIX**. Do not write that VIX has been proven to absorb, subsume, or replace NFCI.
