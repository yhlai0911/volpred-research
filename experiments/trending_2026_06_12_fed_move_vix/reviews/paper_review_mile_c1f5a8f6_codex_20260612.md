# Codex 24h Source Review: mile_c1f5a8f6

**Article**: `mile_c1f5a8f6` - 降息交易退了，MOVE 也退了：為什麼 VIX 還停在 19？

**Experiment**: `trending_2026_06_12_fed_move_vix`

**Date**: 2026-06-12

**Verdict**: PASS, no correction required

## Scope

This review checked whether the production article's numerical claims and methodological framing are supported by:

- `storage/reports/feed.json`
- `storage/drafts/trending_fed_move_vix_2026_06_12.md`
- `experiments/trending_2026_06_12_fed_move_vix/README.md`
- `experiments/trending_2026_06_12_fed_move_vix/trending_2026_06_12_fed_move_vix.py`
- `experiments/trending_2026_06_12_fed_move_vix/trending_2026_06_12_fed_move_vix_results.json`
- `experiments/trending_2026_06_12_fed_move_vix/close_prices.csv`
- `experiments/trending_2026_06_12_fed_move_vix/summary_table.csv`

## Checks

### PASS: Headline numbers are traceable

The article's headline values match `trending_2026_06_12_fed_move_vix_results.json` and a fresh standard-library recomputation from `close_prices.csv`:

- Latest common MOVE/VIX date: 2026-06-11
- Common MOVE/VIX sample: 5,796 trading days, 2003-01-02 to 2026-06-11
- VIX: 19.44, 5-day change +26.23%, full-sample percentile P65
- MOVE: 69.45, 5-day change -2.41%, full-sample percentile P34
- MOVE/VIX: 3.57, 5-day change -22.69%, full-sample percentile P19
- 20-day MOVE/VIX daily-change correlation: 0.37
- 60-day MOVE/VIX daily-change correlation: 0.48
- SPY 5-day return: -2.55%
- TLT 5-day return: +0.56%

The script computes these from `raw["Close"]`, constructs the common MOVE/VIX panel with `dropna()`, and writes both `summary_table.csv` and the article-ready JSON numbers.

### PASS: No lookahead-sensitive trading claim

The package is descriptive, not a trading backtest. It does not multiply same-day signals by same-day returns, produce strategy weights, or claim an ex-ante tradable rule. Percentiles, 5-day changes, and rolling correlations include the 2026-06-11 close because the article is explicitly framed as a post-close cross-asset snapshot.

### PASS: DM/Harvey and causal overclaim risk is controlled

The article does not use DM, Harvey, bootstrap, or statistical-significance language. It states that the work is descriptive and avoids causal wording between MOVE and VIX. The line that current relative pricing "比較支持第一種壓力較大" is framed immediately as "不是預測，只是當前相對價的位置", which keeps the conclusion within the evidence.

### PASS: Data-source caveats are present

The README and article both disclose that `ZQ=F` is a Yahoo Finance generic Fed Funds futures proxy rather than CME FedWatch target-rate probabilities. The article also cites the Cboe VIX methodology and ICE MOVE description, and lists all yfinance tickers used.

### PASS: Reader-facing style audit did not flag this article

`python3 scripts/validate_anti_ai_style.py --recent 5 --json` flagged a different recent article (`mile_5e0786d0`) but did not flag `mile_c1f5a8f6`.

## Residual Risks

- Reproduction requires live yfinance if `trending_2026_06_12_fed_move_vix.py` is rerun from scratch, but the review verified the pinned local `close_prices.csv`, `summary_table.csv`, and results JSON already present in the experiment folder.
- `storage/reports/index.json` and `storage/reports/INDEX.md` had not yet picked up `mile_c1f5a8f6` at review time. Per `docs/architecture.md`, `storage/reports/feed.json` is the canonical article source and individual `mile_*.json` files are deprecated; this is an index freshness issue, not an article-source failure.

## Action Taken

No article correction was required. This review record documents the source-level verification for the 24h-rule task.
