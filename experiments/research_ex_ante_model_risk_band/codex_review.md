# Codex review — research_ex_ante_model_risk_band

Verdict: `PASS_WITH_CAVEATS`.

## Scope reviewed

- Script: `research_ex_ante_model_risk_band.py`
- Results: `research_ex_ante_model_risk_band_results.json`
- Supporting outputs: `data/spec_metrics.csv`, `data/formal_tests_10bps.csv`,
  `figures/model_risk_bands_10bps.png`,
  `figures/representative_navs_10bps.png`

## Checks

### Lookahead / alignment

PASS.  `_holding_periods()` constructs holding windows strictly after the
rebalance date.  Each `weight_func()` estimates covariance from
`universe_returns.loc[:date].tail(lookback)`, and `_backtest()` applies the
weights only to `returns.index > rebalance_date`.  This is equivalent to
month-end `t` signal, next-period returns.

The current partial month is dropped in `_month_end_dates()` when the data end
inside the run month, so the OOS period ends at 2026-05-29 rather than a partial
June 2026 holding period.

### Reproducibility

PASS.  The script writes the yfinance price cache, all daily returns, monthly
weights, metrics, formal tests, and figures.  Random procedures use
`SEED = 20260624`; bootstrap uses `B=1000`, block length 21 trading days.

### Statistical interpretation

PASS.  The results do not claim return alpha.  Formal DM/HAC tests show 72/72
lower-variance Harvey passes vs both sector equal weight and SPY, but 0/72
higher-return Harvey passes.  The README correctly frames the finding as
robust variance reduction plus modest construction model-risk band.

### Optimization and constraints

PASS_WITH_CAVEAT.  Long-only specs have zero optimizer failures.  Limited-short
specs have 141 fallbacks across 36 specs and 173 monthly holding periods.  The
fallback is feasible equal weight and is counted in the results JSON; it can
compress limited-short dispersion.  Because the long-only subset independently
has the same realized-vol and Sharpe band ranges, this does not block the main
`MODEL_RISK_BAND_MODEST` conclusion.

### Cost handling

PASS.  Turnover is measured at rebalance dates against drifted prior holdings,
then one-way bps cost is deducted on the first trading day of the holding
period.  Initial deployment cost is excluded, which is standard for comparing
ongoing strategy rules and is disclosed by the cost-grid design.

## Caveats before publication

1. The universe is sector ETFs, not stock-level constituents.  A stock-level
   large-cap panel with historical constituents, liquidity screens, and
   industry-neutral constraints could show a wider model-risk band.
2. The limited-short gross constraint uses SLSQP with an absolute-value gross
   constraint; some failures remain.  If a future article focuses on
   limited-short design, replace this with a split long/short variable
   formulation.
3. yfinance adjusted close is acceptable for a backlog experiment but not a
   production-grade index replication source.

## Conclusion

The experiment is safe to record in knowledge as a modest/null implementation
model-risk result: in this ETF-sector proxy, low-risk construction consistently
lowers realized variance, but covariance/lookback/cap/shorting choices do not
create a large realized-volatility band and do not produce significant return
alpha.
