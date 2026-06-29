# Codex Review: K1574

Verdict: `CONDITIONAL_PASS`

## Scope

Reviewed:

- `experiments/K1574/k1574.py`
- `experiments/K1574/k1574_results.json`
- `experiments/K1574/README.md`
- Generated figures under `experiments/K1574/figures/`

## Checks

- Data provenance is explicit: yfinance adjusted OHLCV plus Kenneth French
  daily five-factor and momentum CSV files.
- Sample is reproducible from the artifacts: aligned daily sample is
  `2013-07-19` to `2026-04-30`, `n=3,215`.
- No trading strategy is formed. Same-day factor and ETF returns are used only
  for ex-post attribution, so the usual `signal.shift(1)` requirement is not
  applicable to a trading signal.
- Statistical inference is present: Newey-West HAC alpha tests, Holm adjustment
  across ETF alpha tests, stationary bootstrap with seed `42`.
- Conclusion strength is aligned with evidence: no Holm-significant negative
  alpha, bootstrap median-alpha CI crosses zero, and the README does not claim
  a robust 2-4% implementation shortfall.

## Caveats

- This is ETF-level attribution, not a causal transaction-cost estimate.
- Expense ratios, live bid-ask spreads, securities lending, holdings turnover,
  and short-leg financing are not observed.
- USMV does not map cleanly to a Fama-French six-factor paper factor.
- yfinance and French Library downloads are external data sources; reruns may
  shift if either source revises history.

## Review Result

The experiment is suitable as a narrow null/dilution finding:
tradable factor ETFs load on the intended paper factors, but this run does not
find statistically reliable negative alpha or a clustered 2-4% annual
implementation shortfall.
