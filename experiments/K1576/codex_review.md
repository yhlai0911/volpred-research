# K1576 Codex Review

Review status: **CONDITIONAL_PASS**

## Scope

Reviewed `experiments/K1576/k1576.py`, `events.csv`, generated `k1576_results.json`, `event_ticker_metric_results.csv`, and figures.

## Checks Passed

- Event windows are lookahead-safe: RV post windows start at T+1; pre baseline ends at T-6.
- Beta metric uses T+1..T+63 post returns and T-90..T-6 pre returns; announcement day is excluded.
- Bootstrap randomness is fixed with seed `42`.
- Data come from yfinance adjusted closes and are cached in `close_yfinance.csv`.
- Event dates are source-linked and framed as spending-path announcements, not generic war-news events.
- Multiple testing is explicit: 315 p-values, Bonferroni alpha 0.000159.
- Conclusion does not overclaim the weak `rv22` descriptive elevation because defense-minus-benchmark and beta evidence are negative.

## Findings

No critical implementation bug found.

Residual risks:

- Event set is hand-curated and small (9 dates), so power is low.
- US-listed ETFs are coarse proxies for European rearmament beneficiaries.
- Announcements may be anticipated; ETF reaction may occur before public summit text.
- Broad macro shocks in 2024-2025 can dominate the event windows.
- Daily close-to-close data cannot test intraday announcement effects.

## Conclusion

Suitable for a **NULL / caveated knowledge entry**:

> Defence-spending announcements do not produce robust defense-specific daily ETF RV or beta effects. Some 22-day RV windows are elevated, but the effect is broad-market-heavy and does not survive multiple testing or benchmark contrasts.
