# K1548 Codex Review

Review date: 2026-06-24

## Verdict

PASS with limitations.

The experiment is suitable as a free-data currency-overlay result. The empirical conclusion should be stated narrowly: in this yfinance USD ETF + USD/TWD OOS sample, simple full/static hedging reduces realized TWD volatility about as well as, or better than, the tested dynamic EWMA/HMM proxies.

## Checks

- Data source and sample are explicit in `k1548_results.json`.
- The script writes the required three-piece experiment set: `README.md`, `k1548.py`, and `k1548_results.json`.
- Random procedures use `SEED = 1548`.
- No `storage/memory/knowledge.json` write is performed by Codex.
- OOS hedge ratios avoid same-day lookahead:
  - static ratios are train-only;
  - EWMA sets `h_t` before updating with return `t`;
  - HMM parameters and state ratios are train-only;
  - HMM day-`t` hedge uses state inferred through `t-1`.
- Statistical testing compares daily squared-return loss vs unhedged with HAC t-statistics and 3000-rep circular block-bootstrap CIs.

## Issues Found During Review

1. The first script version forward-filled all close-price columns before computing returns. That created synthetic zero returns on non-trading days across different market calendars. This was fixed by removing cross-market forward-fill and requiring asset/FX close-return intersections for each USD ETF.
2. The first script version indexed local benchmark returns with the original dataframe mask after `dropna()`. This produced a length mismatch. It was fixed by applying the date mask to the benchmark series' own index.

## Remaining Limitations

- `ewma_dcc_lite` must not be described as full DCC-GARCH.
- The hedge-return formula does not include carry, forward points, transaction costs, taxes, borrowing limits, or roll execution.
- HMM state inference is intentionally conservative to avoid lookahead, but that also limits adaptation to the post-2020 regime.
- The result is about realized volatility of USD ETF overlays, not a complete wealth-management recommendation for Taiwan investors.
