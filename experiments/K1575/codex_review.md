# K1575 Codex Review

Review status: **CONDITIONAL_PASS**

## Scope

Reviewed `experiments/K1575/k1575.py`, `events.csv`, generated `k1575_results.json`, `event_ticker_metric_results.csv`, and figures.

## Checks Passed

- Event windows are lookahead-safe: post metrics start at T+1; pre baseline ends at T-6.
- Same-day announcement returns are not used as post-event evidence.
- Bootstrap randomness is fixed with seed `42`.
- Results are generated from actual yfinance adjusted-close data and cached in `close_yfinance.csv`.
- Multiple testing is explicitly reported over all 416 event-ticker-metric p-values.
- The original jump-ratio sign-test issue was corrected: `jump5_abs` is now treated as bootstrap-only because a 5-day max / pre mean ratio is not expected to center at 1.
- `README.md` states the market-confounding limitation for the 2025-04-04 rare-earth event instead of overclaiming a causal mineral-specific effect.

## Findings

No critical implementation bug found after the jump-ratio correction.

Residual risks:

- Event dates are manually curated; the event list is source-linked but not exhaustive.
- Daily close-to-close data may miss intraday announcement effects.
- 2025-04-04 and 2025-10-09 windows overlap broader tariff / US-China stress, so causal attribution to export restrictions is weak.
- Benchmark contrasts are descriptive; no full market-model residual-volatility event study is run here.

## Conclusion

The code and results are suitable for a **mixed / caveated knowledge entry**:

> No robust sector-specific RV transmission after critical-minerals export-restriction announcements in daily ETF data. Two Bonferroni-significant jump observations appear for LIT/REMX after the 2025-04-04 rare-earth control event, but broad benchmark volatility in the same window prevents clean causal attribution.
