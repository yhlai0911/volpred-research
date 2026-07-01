# Paper Review — mile_cfa5eb89

Task: `paper_review_mile_cfa5eb89`

Article: `mile_cfa5eb89`, "K1586：穩定幣儲備變化與短端 T-bill realized vol 的領先性檢定"

Review verdict: **PASS_WITH_LOW_CAVEAT**. No must-fix issue found.

## Findings

- No blocking findings.

## Checks

- Metadata: PASS. The reviewed article is `status=published`, audience
  `research`, article id `mile_cfa5eb89` in `storage/reports/feed.json:282`.
- Experiment-result match: PASS. The article reports `NULL_PARTIAL`, sample
  `2020-04-06` to `2026-06-26`, and `1557` business days; these match
  `experiments/K1586/K1586_results.json:6` and
  `experiments/K1586/K1586_results.json:271`.
- H1 lead-lag claim: PASS. The article says all DGS1MO/DGS3MO Granger p-values
  exceed 0.29 and therefore no incremental lead-lag predictability is supported.
  Results JSON reports DGS1MO lag p-values 0.4453 to 0.9379 and DGS3MO lag
  p-values 0.2921 to 0.4480 (`experiments/K1586/K1586_results.json:85`,
  `experiments/K1586/K1586_results.json:178`). The article correctly treats HAC
  OLS as marginal association rather than causal evidence.
- H2 USDC-SVB event claim: PASS. The article's SHY numbers match results:
  event mean abs return `37.2406` bps, control `13.1759` bps, ratio `2.8264`,
  Welch `t=2.7518`, Bonferroni `p=0.0383`, block-bootstrap Bonferroni
  `p=0.0228` (`experiments/K1586/K1586_results.json:217`). It also correctly
  reports BIL as NULL (`experiments/K1586/K1586_results.json:233`).
- H3 GENIUS Act claim: PASS. The article reports DGS1MO_RV up, DGS3MO_RV down,
  and explicitly avoids a law-effect causal claim. This matches the split
  results in `experiments/K1586/K1586_results.json:250`.
- Lookahead: PASS. The source script explicitly documents no contemporaneous
  stablecoin predictor, trailing RV responses only, and seed 42
  (`experiments/K1586/K1586.py:3`). H1 uses `panel["sb_dlog"].shift(k)` for
  `k>=1` (`experiments/K1586/K1586.py:254`). The results file records the same
  lookahead policy (`experiments/K1586/K1586_results.json:16`).
- Robustness / inference strength: PASS. The article does not claim DM/Harvey
  forecasting superiority and does not promote H3 to causal evidence. H2's event
  claim is supported by both Welch and block bootstrap gates
  (`experiments/K1586/K1586.py:319`, `experiments/K1586/K1586.py:414`).
- Figures: PASS. Both public image URLs in the article returned HTTP 200 on
  review: `leadlag_corr.png` and `svb_event_study.png`.

## Low Caveat

The title shorthand says "T-bill realized vol", while the only passing event
result is SHY, a 1-3 year Treasury ETF, and BIL is NULL. The body repeatedly
clarifies this maturity split and says not to generalize to all short-end
T-bill volatility, so no correction is required.

## Must-Fix Items

None.
