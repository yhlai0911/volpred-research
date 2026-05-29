# K709 Method Notes

This directory was empty in the original K709 artifact set. The rebuild uses a
best-faith specification consistent with the published article text and the
surviving `knowledge.json` entry.

## Reconstructed rules

- Data: yfinance `SPY`, `GLD`, `^TNX`, `^IRX`
- Price series for returns: `Adj Close`
- Rate regime: trailing 126-trading-day change in `^TNX`
- "Meaningful move" threshold: `+/- 0.50` percentage points (50 bp)
- Descriptive regime table: same-day slicing by current trailing-126d regime
- Tradable strategy:
  - use the regime label from 126 trading days earlier
  - freeze signal at month-end
  - apply weights in the following month
  - weights = `60/40`, `50/50`, `40/60` for `rising/stable/falling`

## Important limitation

No surviving source file documented the exact pre-review K709 implementation.
The rebuilt script therefore prioritizes:

1. explicit anti-lookahead mechanics,
2. transparent data snapshots,
3. article-claim reconciliation,
4. statistical uncertainty reporting.

## Interpretation

The rebuild suggests the original article likely combined:

- a hindsight descriptive regime slice (`GLD 30.8% vs SPY 13.4%` in falling
  regimes under the 50 bp rule), and
- a separate lagged tradable backtest (small Sharpe improvement only).
