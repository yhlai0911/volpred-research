# Codex 24h Review — mile_476d20ea (K1530)

- **Article**: 散戶越熱，0050 明天就越震？數字給的答案很保守
- **Task**: `paper_review_mile_476d20ea`
- **Reviewed**: 2026-06-22 台灣時間
- **Reviewer**: Codex CLI
- **Verdict**: **PASS**

## Summary

這篇文章和 K1530 canonical source 對齊，核心敘事保持在 `MIXED_PROXY_WEAK_OOS` 的證據邊界內。文章明確限定資料是 0050 ETF-level public proxy，而不是全市場散戶占比；數字表格與 `k1530_tw_retail_interaction_rv_results.json` 一致；最重要的結論也沒有把 0/4 Harvey OOS pass 說成正式可用訊號。

## Numeric verification

| Article claim | Source | Match |
|---|---|---|
| 價格樣本 2009-01-05 至 2026-03-17 | `results.data.sample_start/end` | yes |
| 0050 價格 4,208 個交易日 | `results.data.n_price_days` | yes |
| residual proxy valid n = 3,370 | `results.data.n_retail_residual_valid` | yes |
| margin proxy valid n = 3,383 | `results.data.n_margin_valid` | yes |
| residual proxy mean = 81.77% | `results.data.retail_residual_share_mean` | yes |
| r2/residual QLIKE improvement = 9.55%, Harvey no | `results.specs[0]` | yes |
| r2/margin QLIKE improvement = 8.93%, Harvey no | `results.specs[1]` | yes |
| Parkinson/residual QLIKE improvement = 11.83%, DM t about -2.78 | `results.specs[2]` | yes |
| Parkinson/margin QLIKE improvement = 9.59%, Harvey no | `results.specs[3]` | yes |
| seed = 42 | `results.seed` | yes |

## Findings

No blocking or major findings.

1. **Claim framing is source-aligned and conservative** — article extract lines 9, 59, 71-73; `experiments/k1530_tw_retail_interaction_rv/k1530_tw_retail_interaction_rv_results.json:7`
   The article states there is some signal but it is unstable, then ends with suggestive-only / not a formal signal. That matches the experiment verdict and summary.

2. **Lookahead discipline is correctly represented** — article extract line 26; `experiments/k1530_tw_retail_interaction_rv/k1530_tw_retail_interaction_rv.py:175`
   Source uses lagged HAR features, lagged 5-day return, and explicit `.shift(1)` for retail and margin z-scores before constructing interactions. The article's "yesterday-visible signals forecast today's volatility" wording is accurate.

3. **Harvey / DM conclusion is not overstated** — article extract lines 49 and 53; `experiments/k1530_tw_retail_interaction_rv/k1530_tw_retail_interaction_rv_results.json:104`
   The best OOS spec is Parkinson plus residual retail with DM t = -2.7765, below the project's strict `t < -3` superiority bar. The article correctly says the result misses the strict threshold.

4. **Proxy limitation is clear enough for reader-facing publication** — article extract lines 5-7, 30, 67, 75; `experiments/k1530_tw_retail_interaction_rv/README.md:119`
   The article repeatedly says the proxies are ETF-level substitutes and not household order-flow or official full-market retail share. This is the key limitation and it is not buried.

## Source-code audit

- PASS — QLIKE direction is inherited from `volpred.stats.model_evaluation.qlike_pointwise`, which computes `actual / forecast - log(actual / forecast) - 1`; see `src/volpred/stats/model_evaluation.py:51`.
- PASS — DM pointwise comparison uses `dm_test(aug_loss, base_loss, h=1)`, so negative t means augmented loss is lower; see `experiments/k1530_tw_retail_interaction_rv/k1530_tw_retail_interaction_rv.py:255`.
- PASS — OOS split is fixed at `2022-01-01`, with training strictly before OOS; see `experiments/k1530_tw_retail_interaction_rv/k1530_tw_retail_interaction_rv.py:241`.
- PASS — Image URLs used by the article returned HTTP 200 during review.

## Verification commands

```bash
uv run python -m py_compile experiments/k1530_tw_retail_interaction_rv/k1530_tw_retail_interaction_rv.py
uv run python experiments/k1530_tw_retail_interaction_rv/k1530_tw_retail_interaction_rv.py
```

Both completed successfully. The experiment rerun preserved the substantive verdict and numbers; only runtime metadata changed, so that non-research diff was restored before committing.
