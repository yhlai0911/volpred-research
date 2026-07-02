# Codex Source Review

Review date: 2026-07-02

Verdict: PASS as scoped weak/null public-data pilot.

## Checks

- Reproducibility: PASS. The experiment runs with:

```bash
uv run python experiments/research_mutual_fund_to_etf_active_etf_conversion_event_w/research_mutual_fund_to_etf_active_etf_conversion_event_w.py
```

- Required artifacts: PASS. The directory contains `README.md`, the experiment script, and `research_mutual_fund_to_etf_active_etf_conversion_event_w_results.json`.
- Data provenance: PASS. Events are hand-built from public issuer/industry/Fed sources listed in the README and results JSON. yfinance raw OHLCV caches are stored under `data/raw/`.
- Lookahead and event-window discipline: PASS. Listing-day returns are excluded from primary windows. Wrapper diagnostics begin at `T+1`; underlying RV uses baseline `T-60..T-11` and post windows beginning at `T+1`.
- Inference unit: PASS. Wrapper liquidity is ETF-event level. Underlying RV is aggregated to unique listing-date means, so same-day conversion batches do not multiply a single market date.
- Multiple testing: PASS. The script reports Holm-adjusted primary p-values across the summary metrics.
- Randomness: PASS. Bootstrap and placebo use fixed seed `42`.
- Result honesty: PASS. The raw tracking-noise improvement is reported as weak only because Holm-adjusted p is `0.0716`; underlying RV is reported as null.

## Caveats

- The event calendar is a public-source pilot, not a complete SEC N-14 / CRSP conversion universe.
- Converted ETF pre-listing exchange trading does not exist, so the wrapper test measures post-listing maturation rather than true exchange-liquidity before/after.
- Category ETFs proxy holdings; no holdings-level exposure weights are used.
- Daily OHLCV cannot directly measure ETF bid-ask spreads, premium/discount, primary-market creation/redemption, or AP activity.
- Same-day conversion/listing returns are excluded for window discipline, but this may miss any opening-day microstructure effects.

## Reviewer Notes

The main empirical takeaway is narrow: converted ETFs show a raw decline in return tracking noise versus category proxies after the first post-listing month, but the evidence is not strong enough for a formal pass. No robust abnormal category-RV spillover is visible in the public proxy design.
