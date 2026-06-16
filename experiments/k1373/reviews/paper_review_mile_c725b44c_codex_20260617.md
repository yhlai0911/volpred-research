# Codex 24h Source Review: mile_c725b44c

- Article: `真正先變吵的，是除息前那 10 天`
- Task: `paper_review_mile_c725b44c`
- Source experiment: `experiments/k1373/`
- Review date: 2026-06-17
- Verdict: `CONDITIONAL_PASS`

## Scope

Reviewed:

- `experiments/k1373/k1373.py`
- `experiments/k1373/k1373_results.json`
- `experiments/k1373/README.md`
- `experiments/k1373/plot_article_charts.py`
- `storage/reports/feed.json` item `mile_c725b44c`
- Cross-reference checks against K512 and K1374 for the article's related-article claims.

## Claim-Evidence Match

No numeric mismatch found in the article's K1373 claims.

| Article claim | Source check | Status |
|---|---:|---|
| 5 assets: 0050, 0056, TSMC, Hon Hai, Cathay Financial | `assets` in JSON | PASS |
| 2015-01-01 to 2025-12-31 | `period` in JSON | PASS |
| 92 ex-dividend events | `pooled.n_events_total=92` | PASS |
| 11,455 control observations | `pooled.ttest_exdate_vs_control.n_control=11455` | PASS |
| Control mean `0.945%` | `0.0094515` | PASS |
| Pre-10 mean `1.047%` | `0.0104733` | PASS |
| Ex-date mean `1.143%` | `0.0114285` | PASS |
| Post-10 mean `0.978%` | `0.0097836` | PASS |
| Pre-window statistically supported | `t=2.918`, `p=0.00359` | PASS, with caveat below |
| Ex-date is borderline by t-test | `t=1.967`, `p=0.0521` | PASS |
| Cathay Financial ratio `1.56x`, `d=0.52` | ratio `1.555`, `d=0.5166` | PASS |
| Other four assets `1.10x` to `1.20x` | ratios `1.098` to `1.196` | PASS |

The K512 comparison is directionally supported: K512's 0050/0056 event study emphasizes post-near volatility lift more than pre-window lift. The "larger extension" statement is supported by K1374 (`226` events, PASS, mean ex-date `1.324%` vs control `0.986%`, Welch `t=4.019`, `p=0.0001`).

## Lookahead / Timing Audit

`k1373.py` is a descriptive event study, not an OOS forecasting or trading model. It uses `yfinance.Ticker(...).dividends` as an external ex-dividend calendar, then measures contemporaneous and surrounding realized absolute log returns. There is no `signal * same-day return` trading rule, no forecast target at `t`, and no rolling refit. Therefore the usual `signal.shift(1)` requirement is not directly applicable.

Timing is acceptable for descriptive evidence, but the reader-facing operational sentence "提早幾天看部位" should be understood as conditional on the ex-dividend date being publicly known before the pre-window. The code uses the full historical dividend calendar from yfinance; it does not independently verify the announcement date or whether each ex-date was known at `t-10`.

## DM / Harvey Check

No DM or Harvey-Newey-West statistic is used or claimed. That is acceptable here because K1373 is not comparing volatility forecasts by loss-differential time series. The relevant formal tests are Welch t-test and Mann-Whitney U. The article does not overclaim DM/Harvey significance.

## Overclaim / Hidden Risks

The article is mostly careful: it calls K1373 a small-sample pilot, says ex-date evidence is borderline, and limits the main conclusion to pre-window volatility buildup. That matches the JSON.

The conditional part is inference strength. The pooled t-tests treat daily window observations as independent. Pre-window uses up to 10 trading days per event and pools across assets, so observations are clustered by event, asset, and calendar period. There is no event-level aggregation, cluster-robust standard error, block bootstrap, or permutation test. This does not invalidate the reported means, but it weakens the phrase "統計上站得住" if read as final inferential proof.

## Actionable Items

1. If the article is revised, add one sentence: "這裡的提前風險管理，前提是除息日程已公告；本文不是用報酬序列預測未知事件。"
2. For K1373/K1374 follow-up, add event-level or asset-cluster bootstrap inference for pre/ex/post windows before using "正式過門檻" wording.
3. Add `n_pre_obs` and `n_post_obs` to `pooled` in future result JSONs so article-level sample-size checks do not rely on README-only tables.

Final review verdict: `CONDITIONAL_PASS`. Article numbers and qualitative direction match K1373, K512, and K1374; no lookahead bug or DM/Harvey overclaim found. The remaining caveat is inferential clustering and real-time ex-date announcement availability, not a published-number error.
