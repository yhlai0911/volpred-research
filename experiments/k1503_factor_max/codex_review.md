# K1503 Codex Review

Reviewer: Codex CLI, 2026-06-16 Asia/Taipei

## Verdict

**CONDITIONAL_PASS**

The implementation is reproducible and the main conclusion is properly
qualified: ETF-level Factor-MAX does not support a next-month underperformance
claim, but it does show strong next-month realized-volatility persistence.

## Checks

- **Lookahead / timing: PASS.** The core feature construction uses
  `panel.groupby("ticker")[col].shift(1)` in `k1503.py:155-157`, so the MAX
  signal is formed from month `t-1` and applied to month `t` outcomes.
- **Partial-month handling: PASS.** `last_complete_month_end()` in
  `k1503.py:54-55` and the filter in `k1503.py:133-134` exclude the partial
  2026-06 outcome; results end at 2026-05-31.
- **Return claim: PASS.** The README and results do not overclaim a return
  anomaly. All four return tests fail Harvey and are directionally null or
  opposite.
- **Volatility claim: PASS with caveat.** All four volatility tests pass
  Harvey, but this should be described as ETF-level volatility persistence /
  state dependence, not as evidence for the stock-level MAX expected-return
  anomaly.
- **Seed / reproducibility: PASS.** Bootstrap uses fixed `SEED = 42` and the
  yfinance cache is stored under `data/prices_yfinance.csv`.

## Issues

No blocking issues found.

## Caveats

- The universe has only five factor ETFs, so cross-sectional return inference
  is inherently low power.
- ETF-level MAX is not the same object as stock-level MAX from Bali, Cakici,
  and Whitelaw (2011).
- The vol result is strong but mechanically plausible because high prior-month
  jumps are closely related to volatility clustering. It should not be framed
  as a new return anomaly.
