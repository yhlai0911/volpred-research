# K1550 Codex Review

Review date: 2026-06-24

## Verdict

PASS with limitations.

The experiment is valid as a public-data proxy test and should be described narrowly. It does not support a robust claim that FINRA short-volume squeeze-pressure events forecast higher next-5-day realized volatility, jumps, or left-tail losses across the tested basket.

## Checks

- Required experiment artifacts exist: `README.md`, `k1550.py`, and `k1550_results.json`.
- The script writes reusable data artifacts and figures under `experiments/k1550/`.
- Data source, sample window, universe, and row counts are explicit in `k1550_results.json`.
- Random procedures use `SEED = 1550`.
- No `storage/memory/knowledge.json` write is performed by Codex.
- The implementation avoids live-data drift by reusing the K1502 FINRA/yfinance cache and failing fast if requested symbols are missing.
- Lookahead controls are explicit:
  - event thresholds are rolling historical quantiles shifted by one day;
  - forecast targets start at `t+1` and end at `t+5`;
  - jump thresholds use trailing volatility through `t`;
  - left-tail thresholds use historical forward-return outcomes shifted by one day.
- Statistical checks include ticker-level Welch tests, cross-ticker bootstrap CIs, and a sign test.

## Result Audit

- `tickers_tested`: 21
- `positive_log_rv_tickers`: 10 / 21
- `median_log_rv_diff`: -0.0583
- `mean_log_rv_diff`: -0.0412
- `log_rv_effect_bootstrap_ci`: [-0.1760, 0.1039]
- `sign_test_log_rv_pvalue`: 1.0000

The aggregate CI crosses zero and the positive-effect count is close to a coin flip. The null verdict is therefore the correct interpretation.

## Issues Found During Review

1. The first run attempted to expand beyond the K1502 cache and began fetching 908 FINRA daily files. This was stopped and fixed by making the experiment cache-backed and fail-fast. The README now documents the fixed 21-name universe rather than claiming historical Russell 2000 coverage.
2. The initial ticker list included names not present in the K1502 cache. The final list is restricted to symbols covered by both the FINRA and price caches.

## Remaining Limitations

- This is not a true short-interest, borrow-rate, or stock-loan utilization experiment.
- FINRA daily short-sale volume is not consolidated exchange-wide short interest.
- The universe is current-name and cache-constrained, not survivorship-free.
- Event-vs-control comparisons do not include a multivariate risk model or controls for scheduled news.
- Strong single-name effects, such as `BB` and `KOSS`, should be treated as hypothesis-generating rather than publishable standalone evidence.
