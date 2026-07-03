# K1610 Codex source review

Reviewer: Codex self-review in main interactive session  
Date: 2026-07-03  
Verdict: `CONDITIONAL_PASS`

## Scope

Reviewed:

- `experiments/K1610/K1610.py`
- `experiments/K1610/K1610_results.json`
- `experiments/K1610/README.md`
- generated CSV and PNG artifacts under `data/` and `figures/`

## Checks

### Data binding

PASS. All reported numbers in the README are copied from `K1610_results.json`.

Primary source is yfinance adjusted close through `yf.download(auto_adjust=True)`. The decisive data limitation is correctly recorded: `FM` ends on 2025-01-08 in this runtime, so no 2025-2026 live-frontier inference is claimed.

### Lookahead

PASS. The experiment is descriptive rather than predictive. It does not construct a signal multiplied by same-day or future returns. The only portfolio test uses constant monthly-rebalanced `EEM/FM` weights. Stress conditioning uses within-sample bottom-quintile `SPY` quarters and is explicitly labelled descriptive, not tradable.

### Overlap and inference

PASS with caveat. Formal correlation inference uses non-overlapping calendar-quarter correlations rather than rolling 252-day windows. Quarterly sample size is modest (`49` quarters), so the README correctly treats secular trend results as low-power.

Bootstrap settings are reproducible (`seed=42`, `3000` reps). The script avoids reporting exact `p=0` when bootstrap tails have zero opposite-sign draws; it records simulation-resolution upper bounds instead.

### Statistical conclusion

PASS. The final verdict is mixed and does not overclaim:

- Volatility reduction from adding 20% `FM` is robust: annualized vol reduction `0.0204`, bootstrap CI `[0.0183, 0.0225]`.
- Sharpe improvement is not robust: CI crosses zero.
- Secular convergence is not robust: `FM vs EEM` trend HAC `t=0.23`, early/late CI crosses zero.
- Stress erosion is supported descriptively: stress `FM vs EEM` corr `0.675` vs calm `0.504`, bootstrap CI for Fisher-z difference `[0.0758, 0.4454]`.

The interpretation "diversification retains support in full-sample volatility, but stress-period erosion is real" matches the evidence.

## Caveats

- Self-review is weaker than an independent second reviewer.
- `FM` ETF closure/delisting means investable-proxy evidence ends before 2026.
- Country ETF diagnostics are not a replacement for a broad frontier index.
- Stress/calm conditioning is descriptive and within-sample.

## Required before publication

Any article should keep the caveat in the headline or first screen: `FM` lowers EM volatility in the historical ETF sample, but it is not current and the benefit weakens in stress quarters.
