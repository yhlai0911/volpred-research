# Codex 24h Review — mile_abe9e68f

- Article: `mile_abe9e68f`
- Title: `每一次失敗都在說同一件事：日頻資料的訊號天花板`
- Published: `2026-06-29T01:25:20.254224+00:00`
- Review date: `2026-06-29`
- Task: `paper_review_mile_abe9e68f`
- Verdict: `CONDITIONAL_PASS_AFTER_CORRECTION`

## Scope

This is a synthesis / daily digest article, not a single experiment article. The audit checked the article against six source reports and five underlying experiment result sets:

- `mile_23312ae9` research-system self-audit
- `mile_b722be0e` / K998
- `mile_764012ef` / K431 v2
- `mile_c8b81b48` / K1014
- `mile_d3993bd1` / K1312
- `mile_e8d4f335` / K188

## Claim-Evidence Findings

| Claim | Source Evidence | Status |
|---|---|---|
| 305 experiments, 86 positive, 28.2% | Source article `mile_23312ae9` states 305 / 86 / 28.2%. | match |
| Research-system audit date range | Source article states 2026-03-14 to 2026-03-22; article said "三月十四日到三十二日". | mismatch, fixed |
| K998 SPY sample 2005-2026, n=5,346 | `experiments/k998/k998_results.json` metadata period `2005-01-05 to 2026-04-07`, `n_oos=1825`; source article says n=5,346. | match |
| K998 Granger F=66.17 | `k998_results.json` h=1 `f_stat=66.16799555348649`. | match |
| K998 controlled t-stat maximum | Controlled VRP-lag model has max absolute t about 2.15; article said 2.119. | mismatch, fixed |
| K998 strategy Sharpe -1.06 vs baseline +0.85 | `k998_results.json` `variance_swap_strategy.sharpe=-1.058`, baseline `0.849`. | match |
| K431 v2 QLIKE table and +5.05% to +6.56% | `k431_stgarch_v2_results.json` `oos_metrics` / `dm_tests` match source article. | match |
| K1014 QLIKE 1.283 / 1.483 / 1.627 and 1,824 OOS days | `k1014_results.json` `qlike_results` and `n_oos=1824`. | match |
| K1312 SPY/QQQ QLIKE and MSE claims | `k1312_results.json` per-asset QLIKE/MSE relative improvements match rounded article numbers. | match |
| K188 60 comparisons, GARCH 31 / HAR 1 / ties 28 | `k188_results.json` `cross_asset_summary` matches. | match |
| Article count | Body and selected-reading list cite six articles; article said "這五篇文章". | mismatch, fixed |
| K188 proxy wording | K188 uses daily OHLC proxies, not intraday 5-minute RV. "高頻代理" wording was misleading. | mismatch, fixed |
| VIX date wording | Article said 2026-06-27 close; 2026-06-27 was Saturday and local snapshots did not verify a trading-day close. | mismatch, fixed |

## Methodology Findings

- K998 explicitly uses lagged VIX for VRP proxy and `signal_lag=1` for strategy simulation; OOS alignment notes state no target-overlap lookahead.
- K431 v2 README and code document the original lookahead/state-propagation fixes; rolling baselines use data up to t-1.
- K1014 uses same-day features to forecast next-day absolute return target; the reviewed claim is about OOS QLIKE ranking, not a tradable same-day strategy.
- K1312 results/config explicitly state all features are shifted one day before walk-forward.
- K188 HAR and HAR-X functions use lagged RV/VIX terms for one-step forecasts; results support the stated 31/1/28 aggregate.

## Lookahead Status

`clean_for_cited_canonical_results`

No new lookahead violation was found in the cited canonical experiment results used by the corrected article. The review did not rerun all experiments; it checked result lineage, code alignment, and source article consistency.

## Overclaim Status

`minor_before_correction`

The core thesis, daily-data volatility forecasting often hits a low signal-to-noise ceiling, is supported as a synthesis of these null/negative results. The original wording overreached by saying "日頻收盤資料" while K188 also used OHLC proxies; the corrected article now says "日頻資料" and "日內高低價代理".

## Corrections Applied

- Added corrected draft `storage/drafts/mile_abe9e68f_codex_review_fix.md`.
- Updated article with `scripts/publish_draft.py --update mile_abe9e68f --update-action codex_24h_review_fix`.
- Synced the single article to Supabase via `sync_article`.
- Remote read-back confirmed:
  - date-range fix present
  - K998 t-stat fix present
  - six-article wording present
  - OHLC proxy wording present
  - old bad strings absent

## Summary

Original published article was a conditional fail on source-trace precision due to date/count/t-stat/proxy wording drift. After in-place correction and remote read-back, the article is acceptable as a consumer-facing synthesis of the cited null results, with no evidence that the core conclusion exceeds the corrected evidence base.
