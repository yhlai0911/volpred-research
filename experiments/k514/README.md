# K514: FOMC Surprise Impact on Volatility

- Experiment ID: `k514`
- Status: completed
- Created At: 2026-04-16T09:39:52.892306+00:00
- Executed At: 2026-03-26
- Data Source: yfinance daily `SPY` and `^VIX`
- Data Range: 2004-01-02 to 2025-12-30
- Sample: 5,534 trading days, 165 matched FOMC meetings

## Question

Does a FOMC-day VIX change proxy for monetary-policy surprise predict 5-to-21 day forward realized volatility, and can it improve a simple 12/VIX volatility-targeting strategy?

## Motivation

Prior work suggested FOMC timing matters for volatility, but the calendar dummy alone is not enough. K514 tests whether a simple FOMC-day market-reaction proxy contains usable forecasting information beyond lagged realized volatility.

## Method

- Build daily SPY log returns and VIX close-to-close changes.
- Match Federal Reserve FOMC dates to nearby trading days.
- Use FOMC-day VIX change as the surprise proxy, forward-filled until the next FOMC meeting.
- Estimate OLS models for forward 5-, 10-, and 21-day annualized realized volatility.
- Compare baseline lagged-RV forecasts against lagged-RV plus FOMC surprise using expanding-window OOS QLIKE.
- Test a 12/VIX allocation overlay with one-day-lagged weights.

## Key Results

- In-sample h=21 VIX-surprise t-stat: -8.18.
- In-sample h=21 delta R2: 0.74 percentage points.
- OOS QLIKE: baseline -2.5797 vs surprise -2.5692.
- Raw DM t-stat for surprise minus baseline: +3.89, p=0.0001.
- Strategy Sharpe: buy-and-hold SPY 0.516, 12/VIX baseline 0.628, surprise overlay 0.599.
- Strategy max drawdown: buy-and-hold SPY -59.6%, 12/VIX baseline -30.8%, surprise overlay -32.2%.
- Regime correlations are unstable: 2010-2014 h=21 corr -0.41, 2020-2025 h=21 corr +0.37.

## Caveats

- VIX change is a noisy proxy for true policy surprise; fed funds futures data would be cleaner.
- Forward 21-day realized-volatility targets are overlapping. The reported OLS and DM tests use conventional standard errors, so the raw significance should be treated as a warning signal rather than a final HAC-corrected inference.
- FOMC dates are manually compiled and may have minor matching issues.

## Artifacts

- Script: `experiments/k514/k514_fomc_surprise.py`
- Results: `experiments/k514/k514_fomc_surprise_results.json`
- Article draft: `storage/drafts/k514_general_draft.md`
- Charts: `storage/charts/k514_is_vs_oos.png`, `storage/charts/k514_regime_corr.png`

## Conclusion

K514 is a negative OOS result. The FOMC VIX-change proxy looks strong in-sample but does not improve OOS QLIKE or the 12/VIX strategy overlay. The correct interpretation is not that FOMC surprise is useless, but that this noisy proxy is not stable enough for production forecasting without cleaner surprise measurement and HAC/bootstrap inference.
