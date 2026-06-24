# Codex 24h Review: mile_1597b341

- Article: 每日精選導讀｜分散投資的幻覺：你以為無關的資產，其實偷偷牽動著你整個組合
- Review task: `paper_review_mile_1597b341`
- Reviewer: Codex (`codex-vscode`)
- Review date: 2026-06-24
- Verdict: CONDITIONAL PASS after provenance fixes

## Findings

1. The Taiwan/Japan Copula paragraph and chart caption cited `K1538a`, but the source article `mile_6a189e72` points to `K1412`. The `K1538` experiment on disk is about bond mutual fund demandable-equity run proxies and credit ETF volatility, so it is unrelated to the Copula claim. Fixed article content and `details.experiment_refs` to use `K1412`.
2. The SpaceX/Google volatility example cited `K1545`, but `experiments/k1545/k1545_results.json` is a KRBN carbon auction regime experiment. Source article `mile_10a52949` has no experiment ref and is an article-level yfinance daily-line example. Removed `K1545` from `details.experiment_refs` and changed the paragraph/footer attribution to `mile_10a52949` instead of an experiment result.
3. The original footer said all numbers could be verified in experiment `results.json` files. That was too strong for the SpaceX/Google segment. Fixed the footer to distinguish experiment-backed claims from the source article example.

## Verification Notes

- `mile_6a189e72` has `details.experiment_refs = ["K1412"]`.
- `K1412` reports full-sample correlation 0.586376 and 5 completed OOS windows; Student-t is the best Copula in the inspected OOS row and passes Harvey/HLN there.
- `K1538` and `K1545` were confirmed to be unrelated experiments and should not be used as evidence for this digest.
- After the fix, `mile_1597b341` has `details.experiment_refs = ["K1011", "K819", "K865", "K628b", "K1445", "K1412"]`; article content no longer contains `K1538a` or `K1545`.

## Operational Notes

- Local canonical feed update was applied through `Publisher._rewrite_feed_entry`, preserving the feed lock and JSON read-back guard.
- The publisher's remote mirror sync hook returned HTTP 401 in this environment, so the local canonical `storage/reports/feed.json` is corrected but remote propagation requires valid sync credentials.
