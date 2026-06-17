# K858 / mile_5acc24ee Codex 24h Publication Review

- Article: `mile_5acc24ee` — "跟單國會議員的股票交易能打敗市場嗎？實證告訴你不能"
- Source experiment: `experiments/k858/`
- Reviewed files: `k858_congressional_trades.py`, `k858_results.json`, `storage/reports/feed.json`
- Verdict: **CONDITIONAL_PASS**
- Reviewer: Codex
- Review date: 2026-06-17

## Bottom Line

The article's headline numeric claims match `experiments/k858/k858_results.json`, and the implemented portfolio return calculation does not use future returns after the signal month. The publication should not be treated as a clean PASS until the method wording is narrowed: the code implements a **monthly, month-end, 60-day trailing disclosure-based aggregate portfolio over a full-sample-selected active ticker universe**, not literal per-disclosure `disclosure_date + 1 business day` fastest-follow trading over all 13,401 cleaned trades.

## Claim-Evidence Match

Matched:

- Cleaned trades `13,401`, members `165`, available tickers `132`, period `2020-02-03 to 2022-09-30`.
- Disclosure lag mean `37.8`, median `27`, p90 `52`, p95 `93`.
- Realistic strategy CAGR `10.83%`, Sharpe `0.502`, MDD `-35.15%`, annual alpha vs SPY `-0.61%`.
- Perfect-info strategy CAGR `10.07%`, Sharpe `0.472`, annual alpha vs SPY `-1.38%`.
- SPY CAGR `11.45%`, Sharpe `0.488`, MDD `-36.16%`.
- p-values `0.8787` and `0.8564`, rounded in article as `0.88` and `0.86`.
- Count-based disclosure strategy CAGR `14.93%`, rounded in article as `14.9%`.

Needs wording correction:

- Article says the realistic strategy buys the next day after disclosure and calls this the fastest realistic follow. In code, `compute_monthly_signals()` builds month-end signals from disclosures in a trailing 60-day window, then `build_portfolio_returns()` holds during the next month (`returns_df.index > signal_date`). This is no-lookahead, but it is **month-end+next-month**, not per-trade or per-disclosure next-day execution.
- Article says the portfolio is based on stocks "被最多議員淨買進". The main strategy uses `net_dollar` ranking, i.e. dollar amount midpoint times direction, not distinct-member count. The count-based version is separate and post-hoc.
- Article states the dataset as 13,401 trades and 132 stocks. The code cleans 13,401 trades, but the tradable universe is selected from full-sample top tickers by trade count/dollar volume before price download. A quick reproduction gives 2,061 cleaned tickers, 141 top-union tickers before price availability, and only about 5,312 trades in that top-union subset. The article should distinguish cleaned source data from effective portfolio universe.

## Lookahead / Implementation Audit

No direct future-return lookahead found in the portfolio return construction:

- `compute_monthly_signals()` uses only trades with `date_col <= month_end` inside a trailing 60-day window (`k858_congressional_trades.py:270-304`).
- Realistic signals use `disclosure_dt`; perfect-info signals use `transaction_dt` and are labelled an upper bound (`k858_congressional_trades.py:371-384`).
- Holding-period returns are strictly after the signal date (`returns_df.index > signal_date`) and through the next month end (`k858_congressional_trades.py:336-345`).

Hidden lookahead/spec risk:

- Ticker universe is chosen using full-sample trade count and dollar volume (`k858_congressional_trades.py:180-185`). This is not a return lookahead, but it is full-sample universe selection and should be disclosed because it narrows the tested claim.

## Statistical Check

The article's "p=0.88 / 0.86" is consistent with the code and results JSON, but it is a simple one-sample daily excess-return t-test (`scipy.stats.ttest_1samp`) rather than DM or Newey-West/HAC (`k858_congressional_trades.py:689-696`). Because the article uses this only to say "not significant", this is acceptable for a null-result reader piece; do not present it as a formal DM/Harvey-Newey-West test.

## Reproducibility / Three-Piece Risk

- `experiments/k858/README.md` is still a placeholder, so the experiment is not self-describing.
- The script writes `experiments/k858_results.json` if run from repo root, while the reviewed result file is `experiments/k858/k858_results.json` (`k858_congressional_trades.py:828-830`). This should be fixed before relying on one-command reproduction.
- Article images `k858_general_cumret.png` and `k858_general_alpha_bars.png` exist under `experiments/k858/`, but the reviewed script saves different chart paths under `experiments/k858_charts/`. Figure provenance should be tied to a committed chart script or README instructions.

## Actionable Items

1. Revise article wording from "揭露後+1日 / 跟得最快" to "月末用過去60天已揭露交易建構訊號、下月持有".
2. Replace "被最多議員淨買進" with "淨買入金額最高" for the main strategy; keep "人頭計票" only for the count-based variant.
3. Add an explicit limitation: effective portfolio universe is the full-sample active/price-available ticker subset, not all 2,061 cleaned tickers.
4. Fix K858 reproducibility: fill README, correct output paths, and document/generate the two article figures from code.

