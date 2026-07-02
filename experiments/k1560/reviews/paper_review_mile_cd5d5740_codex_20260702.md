# Codex 24h Review - mile_cd5d5740 (K1560)

**Reviewer**: Codex failover
**Reviewed at**: 2026-07-02 22:00 Taiwan time
**Article**: 波動率「測不準」能不能當減碼訊號？六檔 ETF、六十天的老實答案
**Article ID**: `mile_cd5d5740`
**Article status at review**: `draft`
**Task ID**: `paper_review_mile_cd5d5740`
**Experiment**: `experiments/k1560/`

## Verdict: PASS_WITH_LOW_METADATA_GAP

- LOOKAHEAD_RISK: LOW
- OVERCLAIM_RISK: LOW
- REPRODUCIBILITY: 4/5
- REQUIRED CONTENT FIXES: none
- LOW FOLLOW-UP: add article metadata through the normal publisher path before promotion, because `storage/reports/mile_cd5d5740.json` has `experiment_refs=null` and `k_ids=null`.

## Findings

### 1. Metadata provenance gap (LOW)

The article footer says the experiment ID is marked in the system metadata, but the single-report JSON currently has:

```json
{
  "experiment_refs": null,
  "k_ids": null
}
```

This does not affect the numerical or methodological conclusion. It is still a provenance gap for downstream discovery and should be fixed through the normal feed-publisher/update path if the article is promoted. Do not hand-edit `feed.json` or the report JSON to close it.

## Claim And Number Checks

| Article claim | Source check | Verdict |
|---|---:|---|
| Six ETFs: SPY, QQQ, IWM, TLT, GLD, HYG | `k1560_results.json.data_summary` has all six | PASS |
| Intraday window 2026-04-01 to 2026-06-26 | all six assets show same `intraday_start` / `intraday_end` | PASS |
| 354 evaluation rows | six assets x 59 rows | PASS |
| GARCH direction positive in 5/6 assets, GLD negative | `positive_spearman_assets.loss_GARCH = HYG, IWM, QQQ, SPY, TLT` | PASS |
| Closest raw tests around p=0.07-0.08 | GARCH sizing error p=0.0731; GARCH QLIKE p=0.0847 | PASS |
| No signal survives multiple-testing correction | all seven `holm_significant_5pct=false` | PASS |
| "Direction right, strength insufficient" | strongest raw positive p-values fail Holm and verdict is `NULL_SHORT_WINDOW` | PASS |
| GARCH/EWMA mostly best direct forecasters | best models: GARCH for SPY/QQQ/IWM/GLD, EWMA for TLT/HYG | PASS |

## Lookahead Audit

PASS.

- Direct OHLC/RV forecasts and disagreement signals are shifted by one row before target-date evaluation in `k1560.py`.
- The saved `lookahead_audit` checked six examples and passed all: each target date uses a strictly earlier origin date and origin-day intraday dispersion is present.
- HAR training rows use `y_next = log(r2.shift(-1))` but the loop fits only on rows before the target origin, so target-day realized variance is not used for training.
- GARCH forecasts are generated in a manual loop indexed by target date with `origin_pos = target_pos - 1`, avoiding the common origin-vs-target alignment error in `arch.forecast`.
- Pointwise QLIKE uses `qlike_pointwise(actual, forecast)`, matching the canonical Patton direction.

## Statistical Review

PASS.

- The article does not claim a pass. It says the direction is plausible but not strong enough for a mechanical de-risking rule.
- The formal signal tests use HAC(maxlags=5), asset fixed effects, origin RV, origin absolute return, and dollar-volume controls.
- Holm-Bonferroni is applied across the seven signal tests.
- DM/MCS diagnostics are reported in the result artifact, but the article does not overuse the many significant pairwise DM results to claim that estimator disagreement is a deployable uncertainty signal.

## Chart Provenance

PASS.

- `k1560_article_charts.py` reads all chart values directly from `k1560_results.json`; no hardcoded statistical values were found.
- Supabase image URLs used in the article returned HTTP 200 during review.
- Remote `content-length` matched local file sizes for:
  - `k1560_article_direction.png`
  - `k1560_article_pvalues.png`
  - `k1560_lazypack_1_concept.png`
  - `k1560_lazypack_2_method.png`
  - `k1560_lazypack_3_result.png`

## Reproducibility Caveats

- yfinance 5-minute data is a rolling vendor window. Future reruns may not reproduce the exact same intraday sample unless the cached data is preserved.
- The realized-kernel-lite proxy is explicitly approximate and should not be presented as a full noise-optimized realized kernel.
- The sample is only 60 recent intraday sessions, so the article's short-window caution is necessary and correctly stated.

## Conclusion

The article is aligned with the K1560 source code and result artifact. No lookahead issue, QLIKE-direction error, or Harvey/DM overclaim was found. The only follow-up is metadata provenance: attach K1560 / experiment references through the publisher workflow before promotion.
