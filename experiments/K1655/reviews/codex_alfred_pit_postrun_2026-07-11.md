# K1655 ALFRED PIT post-run review — 2026-07-11

## Verdict

**PASS, limited to the corrected true-PIT NULL conclusion.**

The reviewed result supports this statement:

> In the 2011-05-27 through 2026-06-26 true-PIT sample, with expanding OOS scoring from
> 2016 onward, NFCI did not improve forecasts of the 5% left tail of S&P 500 price-index
> returns over the unconditional empirical-quantile benchmark.

It does not support a universal claim about NFCI, a causal or forced-deleveraging mechanism,
or a VIX-dominance/encompassing claim.

## Evidence checked

- ALFRED raw cache: 207,755 rows in 3 complete pages, 786 vintages, and 809 observation
  dates. The cache hash matches its audit metadata; there are no duplicate, reversed, or
  overlapping revision intervals.
- PIT alignment: 1,382 requested Friday origins; all 594 origins before the first public
  vintage are excluded; the remaining 788 origins begin 2011-05-27. Independent row-level
  reconstruction found 788/788 selections were the latest observations active at their
  forecast origins.
- Forecast artifact: 31,600 rows covering all 60 model cells, with no duplicates or
  non-finite values. Target horizons, strict `j + H < i` embargo, NFCI observation dates,
  and ALFRED revision windows all pass.
- All 60 cells' losses, loss reductions, DM statistics, p values, and Newey-West lags were
  independently recomputed from the CSV. The largest DM-statistic difference was about
  `6.5e-14`.
- QuantReg audit: 37,980 fits; 3 iteration-limit events resolved by the 20,000-iteration
  retry; zero unresolved limits, other warnings, bootstrap exceptions, or OOS exceptions.
  Every bootstrap cell completed 500/500 replications.

## Primary cells

| Horizon | n | Loss improvement | DM-HLN t | p |
|---:|---:|---:|---:|---:|
| 1 week | 536 | −1.934% | +0.898 | 0.370 |
| 4 weeks | 530 | −2.656% | +0.690 | 0.491 |
| 12 weeks | 514 | −7.331% | +1.819 | 0.0695 |

All three point estimates are worse than the benchmark, and none is a significant
improvement. The PIT-sample NFCI slopes at the 5% return quantile are also not significant
(`p = 0.151, 0.205, 0.871`).

## Required close-out

The old pseudo-PIT README, run log, article claims, and metadata must be replaced. In
particular, the corrected record must not retain claims about the 2000 start date, the 2008
episode, a replicated in-sample GaR fan, VIX dominance/subsumption, strong Vol-at-Risk, or the
old `CONDITIONAL_PASS` verdict. The asset is `^GSPC`, the S&P 500 price index, rather than SPY
total return.
