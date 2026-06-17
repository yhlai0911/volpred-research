# K1532 — VT / Dynamic Risk Parity Turnover-Cost Dominance

**Verdict: CONDITIONAL_PASS.** The cost-frequency threshold is visible and
economically interpretable, but it is an execution-engineering result, not a
new alpha claim.

## Question

When do transaction costs make **monthly** rebalancing beat **daily**
rebalancing for dynamic risk parity and volatility-targeted risk parity?

The backlog target asked for SPY/TLT/GLD/HYG/SHY, daily / weekly / monthly
rebalancing, a cost-to-turnover grid of 0.08% to 0.35%, and net-of-cost Sharpe,
MDD, cost drag, and break-even thresholds.

## Related Work

- Moreira and Muir (2017), *Volatility-Managed Portfolios*: scale exposure
  down when volatility is high.
- Maillard, Roncalli, and Teiletche (2010), *The Properties of Equally
  Weighted Risk Contribution Portfolios*: ERC / risk-parity definition.
- Recent transaction-cost-aware portfolio work, including minimum-risk /
  risk-parity cost control, motivates reporting net returns and turnover
  explicitly instead of treating rebalance frequency as free.

## Data

- Source: yfinance adjusted close, explicitly `auto_adjust=True`
- Tickers: SPY, TLT, GLD, HYG, SHY
- Common price sample: 2007-04-11 to 2026-06-17
- Backtest return sample after 252d warmup: 2008-04-11 to 2026-06-17
- OOS-like daily observations after warmup: 4,575
- Cached files: `data/*_adjusted_close.csv`

Adjusted close is intentional here because the object is ETF total-return-like
strategy performance. The script pins `auto_adjust=True` to avoid yfinance
default drift.

## Method

Strategies:

| Strategy | Definition |
|---|---|
| `drp_4asset` | Long-only ERC over SPY/TLT/GLD/HYG; SHY weight is zero |
| `drp_5asset` | Long-only ERC over SPY/TLT/GLD/HYG/SHY |
| `vt_drp_4asset_shy` | ERC over SPY/TLT/GLD/HYG scaled down to 10% annual vol; residual goes to SHY; no leverage |

Lookahead guard:

- For return date `i`, the covariance estimate uses
  `returns.iloc[i-252:i]`, ending at `i-1`.
- Target weights are applied to return date `i`.
- Diagnostics confirm first target date 2008-04-11 uses returns only through
  2008-04-10.
- Optimizer failures: 0 for all three strategies.

Transaction cost:

- Cost grid: 0, 8, 15, 25, 35 bps per dollar traded.
- L1 dollar turnover: `sum(abs(new_weight - current_drifted_weight))`.
- Cost: `turnover * cost_bps / 10000`.
- Initial portfolio deployment cost is excluded; ongoing rebalance turnover is
  the object of comparison.

Formal test:

- Newey-West HAC t-tests, maxlag 21, on mean daily return differences.
- These tests compare net daily return levels, not Sharpe ratios.

## Results

### Break-Even Cost

Monthly rebalancing crosses daily rebalancing at:

| Strategy | Monthly-minus-daily Sharpe threshold |
|---|---:|
| `drp_4asset` | 18.72 bps |
| `drp_5asset` | 17.87 bps |
| `vt_drp_4asset_shy` | 15.71 bps |

Interpretation: at zero cost, daily has a small gross edge. Once execution
cost reaches roughly 16-19 bps per dollar traded, lower turnover dominates
and monthly net Sharpe becomes higher.

### Net Sharpe Snapshot

| Strategy | Cost | Daily | Weekly | Monthly |
|---|---:|---:|---:|---:|
| `drp_4asset` | 0 bps | 0.901 | 0.891 | 0.874 |
| `drp_4asset` | 35 bps | 0.830 | 0.855 | 0.854 |
| `drp_5asset` | 0 bps | 0.966 | 0.948 | 0.933 |
| `drp_5asset` | 35 bps | 0.864 | 0.890 | 0.896 |
| `vt_drp_4asset_shy` | 0 bps | 0.897 | 0.888 | 0.874 |
| `vt_drp_4asset_shy` | 35 bps | 0.821 | 0.847 | 0.849 |

### Turnover

Annual L1 turnover before costs:

| Strategy | Daily | Weekly | Monthly |
|---|---:|---:|---:|
| `drp_4asset` | 1.60 | 0.81 | 0.46 |
| `drp_5asset` | 0.89 | 0.50 | 0.33 |
| `vt_drp_4asset_shy` | 1.68 | 0.89 | 0.55 |

Daily is not catastrophically expensive in this ETF universe, but it trades
about 2-3.5x as much as monthly depending on the strategy.

### HAC Return Tests

At 35 bps, daily-minus-monthly net return is negative:

| Strategy | HAC t | p-value |
|---|---:|---:|
| `drp_4asset` | -2.595 | 0.0095 |
| `drp_5asset` | -3.294 | 0.0010 |
| `vt_drp_4asset_shy` | -3.083 | 0.0020 |

At 0 bps, the daily edge is smaller. Only `drp_4asset` daily-minus-monthly
return is conventionally significant (HAC t=2.089, p=0.0367); `drp_5asset`
and `vt_drp_4asset_shy` are not.

## Interpretation

The result supports a narrow claim:

> In SPY/TLT/GLD/HYG/SHY dynamic RP and VT-RP implementations, daily
> rebalancing has a small gross edge, but monthly rebalancing becomes
> preferable once cost per dollar traded is around 16-19 bps.

This is not evidence that monthly rebalancing is universally better. It says
that when daily's gross edge is small, turnover cost can erase it quickly.
Weekly is often competitive and sometimes slightly better than monthly at the
top of the grid, so the practical decision is "avoid unnecessary daily churn,"
not "monthly always dominates."

## Limitations

1. yfinance adjusted close is an ETF proxy, not institutional total-return
   data with exact execution prices.
2. Costs are linear per dollar traded; no bid-ask widening, market impact,
   tax, borrow, or slippage state dependence.
3. ERC uses a 252d covariance window with 10% diagonal shrinkage; no window
   sensitivity grid yet.
4. `drp_5asset` is cash-heavy because SHY is inside ERC; interpret it as a
   conservative all-asset RP sleeve, not the only dynamic RP definition.
5. VT overlay uses no leverage. A levered implementation may have different
   turnover and financing-cost behavior.
6. HAC return tests do not test Sharpe differences directly.

## Codex Review

Source-level self-review after rerun:

- Lookahead: PASS. Weight construction uses `iloc[i-252:i]` and applies to
  return date `i`; no `shift(-...)` appears in the signal path.
- Cost model: PASS with caveat. Costs are proportional to L1 turnover and are
  charged at each rebalance; initial deployment cost is excluded by design.
- Data reproducibility: PASS. yfinance adjusted-close snapshots are cached in
  `data/`; `auto_adjust=True` is explicit.
- Statistical caveat: PASS. README and JSON label HAC tests as return-level
  comparisons, not Sharpe tests.
- Overclaim guard: PASS. Verdict is `CONDITIONAL_PASS`, not a strategy alpha
  recommendation.

## Files

- `k1532.py` — reproducible script
- `k1532_results.json` — structured output
- `data/*.csv` — cached yfinance adjusted-close snapshots
- `fig_drp_4asset_sharpe_cost.png`
- `fig_drp_5asset_sharpe_cost.png`
- `fig_vt_drp_4asset_shy_sharpe_cost.png`
- `fig_annual_turnover.png`

## Reproduce

```bash
uv run python experiments/k1532/k1532.py
```
