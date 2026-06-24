# Codex 24h Review: mile_f3e389cf

- Article: 每日精選導讀｜隔夜波動率：學術上很重要，實戰裡很尷尬
- Review task: `paper_review_mile_f3e389cf`
- Reviewer: Codex (`codex-vscode`)
- Review date: 2026-06-24
- Verdict: PASS after minor wording fixes

## Findings

1. Source article and experiment provenance were mostly consistent. The digest points to `K772`, `K886`, `K1006`, `K1264`, and `K935`, matching the cited source articles.
2. The K1006 paragraph said the TX sample ran from 2012 to 2025, but `experiments/k1006/k1006_results.json` reports 2012-01-04 to 2026-04-08. Fixed the digest wording to 2012-01 through 2026-04.
3. The "latest validation" paragraph said the earlier experiments ended in 2025 and that "last June" extended the sample. That was temporally ambiguous and inconsistent with K1006/K1264 result files. Fixed it to explicitly cite K1006 through 2026-04-08, K1264 through 2026-04-28, and the 2026-06-19 reader-facing update.
4. The model-risk paragraph overstated the mechanism by saying daily close data "throws away" 36.8% of volatility information. Close-to-close returns include overnight and intraday movement in aggregate; the real issue is either omitting overnight gaps in intraday range estimators or mixing overnight/intraday structures into one daily target. Tightened the wording and preserved the K935 caveat that the robust conclusion is "overnight gap matters", not that a named formula always wins.

## Verification Notes

- `K772`: SPY overnight variance share is 0.368389; sample is 2007-01-03 to 2026-03-30.
- `K886`: PRG_Extended QLIKE is 0.783758 vs GJR 0.980650, with GJR-vs-PRG_Extended DM t=5.267 and Harvey PASS.
- `K1006`: TX period is 2012-01-04 to 2026-04-08; overnight share of total return is 83.6%, overnight variance share is 53.6%, net Sharpe is 0.317.
- `K1264`: TX pure overnight period is 2017-05-16 to 2026-04-28; gross annual return is 15.585%, net Sharpe after 5bp cost is 0.200, listing recommendation is NO.
- `K935`: canonical YZ rerun verdict is `CANONICAL_YZ_DOES_NOT_CONFIRM_HEADLINE`; the corrected digest no longer implies canonical Yang-Zhang always wins.

## Operational Notes

- Local canonical feed update was applied through `Publisher._rewrite_feed_entry`, preserving the feed lock and JSON read-back guard.
- The publisher's remote mirror sync hook returned HTTP 401 in this environment, so remote propagation requires valid sync credentials or an external sync run.
