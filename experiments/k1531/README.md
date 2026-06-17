# K1531 — FX Realized-Skewness Risk Premium Without Options

## Motivation

The classic carry-crash-risk literature (Brunnermeier-Nagel-Pedersen 2008;
Chernov-Graveline-Zviadadze 2018; Della Corte-Ramadorai-Sarno 2016) attributes
positive carry returns to compensation for sudden, asymmetric crash risk in
high-yield currencies. The canonical empirical handle is **implied skewness
from currency options** — a paywalled data source most replicators lack.

Question: **Can we recover the same crash-risk premium signal using only free,
yfinance-grade ETF prices, by computing realized skewness from the trailing
60 daily returns?**

If yes, retail-grade traders gain a no-options crash-premium proxy. If no,
we have direct evidence that implied skewness is doing more than mechanical
realized higher moments — it embeds risk-neutral information that realized
moments cannot back out.

## Related K entries

- **K447** (`SKEW Index Tail Risk`) — equity SKEW null
- **K979** (`CBOE SKEW vs VIX`) — equity SKEW null, VIX² nonlinearity dominates
- **K535** (`SKEW Index in HAR Framework`) — same conclusion
- **K539** (`VRP Carry`) — variance-risk-premium carry strategies all null
- **K760** (`Alt Risk Premia Rotation`) — multi-factor including skew, all NS
- **K763** (`Regime-Switched Carry Filter`) — Sharpe 0.674 < 12/VIX 0.827
- **K181 / K184 / K258** — earlier SKEW-as-predictor failures
- **K18** (`VIX-timed forex carry`) — only carry-related K that worked
- **K1135** (`Skew-t GAS commodity`) — realized higher-moment used for VaR not predictive premium

**Pattern**: in this knowledge base, realized higher-moment proxies have
**never** delivered a robust positive expected-return signal. K1531 is the
direct FX-cross-sectional test of that observation against the options-based
literature.

## Universe

8 yfinance currency ETFs, daily Adj-Close (auto-adjusted), 2007-01-01 to
2026-05-31:

| Ticker | Underlying | Inception |
|--------|------------|-----------|
| FXY | JPY | 2007-02-13 |
| FXE | EUR | 2007-01-03 |
| FXB | GBP | 2007-01-03 |
| FXA | AUD | 2007-01-03 |
| FXC | CAD | 2007-01-03 |
| FXF | CHF | 2007-01-03 |
| CEW | EM currency basket | 2009-06-02 |
| UUP | USD index | 2007-03-01 |

CEW's later inception is handled by requiring ≥5 tickers to have a signal
each month — this is a *real-time* filter (no future-knowledge of which
tickers exist later), but does mean the very-early sample (before mid-2009)
has 7-name baskets while the later sample has 8.

## Methodology

1. **Signal** (causally lagged):
   - Daily log returns of each ETF
   - 60-trading-day **rolling realized skewness** (Amaya, Christoffersen,
     Jacobs, Vásquez 2015 JFE-style; pandas `.rolling(60).skew()` is the
     unbiased Fisher-Pearson estimator, right-aligned → only past data)
   - Take month-end value, **then** `.shift(1)` → signal at month-end t-1
     predicts month-t return.
2. **Portfolio formation**: each month, cross-sectional rank by lagged
   skewness, split into 5 equal-rank quintiles (Q1 = most negative skew,
   Q5 = most positive). Equal-weight inside each bucket.
3. **Robustness**: same procedure with **downside/upside semivariance ratio**;
   and a simpler **top-half vs bottom-half** (4-vs-4) sort.
4. **Statistics**:
   - Annualised mean return, vol, Sharpe per bucket
   - Compounded wealth-curve maximum drawdown
   - Historical 95% / 99% VaR and ES
   - Conditional left-tail mean (worst 10% months)
   - **Newey-West t-stat (lag 3)** on the Q1−Q5 spread
   - **Stationary block bootstrap** (block=12 months, B=2000, seed=42) for
     Sharpe CI

## Lookahead safeguards

| Risk | Safeguard | Line |
|------|-----------|------|
| Signal sees its own forecast period | `.shift(1)` after monthly resample | k1531.py L423 |
| Rolling window uses future data | `pandas.rolling(60, min_periods=60).skew()` is left-anchored | L116 |
| Month-end signal mixes month's last day return with prediction | Signal is `.last()` of *that month's* daily skew, then shifted forward by 1 month → signal value at end-of-Apr predicts May return | L157-158, L423 |
| Quintile sort sees same-month return | Sort uses `monthly_sig` (already lagged); applied to `monthly_ret.loc[date]` of the *current* month | L207 |
| Bootstrap randomness | `seed=42` fixed | L262 |

## Data sources

- `yfinance` 1.2.0 (auto-adjusted close prices)
- Date range: 2007-01-01 to 2026-05-31
- 230 monthly observations after lookahead filtering, basket size ≥5 tickers
- Realized skewness window: 60 trading days (~3 months)

## Results

See `k1531_results.json`. Headline (verdict: **NULL**):

| Bucket | Ann. mean | Sharpe | MDD | ES95 (mo) |
|--------|-----------|--------|-----|-----------|
| Q1 (most negative skew) | +0.64% | +0.09 | **−35.9%** | −4.84% |
| Q5 (most positive skew) | +1.50% | +0.21 | −21.8% | −4.18% |
| **Q1 − Q5 spread** | **−0.86%** | **−0.10** | — | — |

Newey-West t = −0.44 (p = 0.66); bootstrap 95% CI on spread Sharpe
[−0.51, +0.33].

**Q1 is strictly dominated**: it has lower mean return, lower Sharpe, AND
materially worse drawdown / tail. The "crash-risk premium" predicted by
BNP / CGZ is **not** detectable using realized skewness as proxy.

## Interpretation

- **Realized skewness ≠ implied skewness**. The latter embeds a
  risk-neutral price for crash protection that the former cannot recover.
- The left-tail asymmetry leg of the hypothesis holds (Q1 does crash
  harder), but the *premium* leg fails. This is consistent with the K447 /
  K535 / K979 pattern: backward-looking SKEW proxies have very limited
  forward predictive power.
- Practical implication: free-data FX strategies cannot substitute realized
  skewness for option-implied crash-risk pricing. Anyone selling such a
  product is selling a free downside without compensating premium.

## Limitations

- N = 8 ETFs → average ~1.6 tickers per quintile. Top-half vs bottom-half
  (4 vs 4) robustness gives the same NULL conclusion (`halves_robustness`
  in JSON).
- ETF universe excludes EM single-currencies (no liquid yfinance ticker for
  TRY / ZAR / BRL alone post-2007); CEW is the EM proxy.
- 60-day window choice unswept; longer windows (120, 252) untested in v1.

## References

1. Brunnermeier, M. K., Nagel, S., & Pedersen, L. H. (2008). Carry Trades
   and Currency Crashes. *NBER Macroeconomics Annual* 23.
2. Della Corte, P., Ramadorai, T., & Sarno, L. (2016). Volatility Risk
   Premia and Exchange Rate Predictability. *Journal of Financial
   Economics* 120 (1).
3. Chernov, M., Graveline, J., & Zviadadze, I. (2018). Crash Risk in
   Currency Returns. *Journal of Financial and Quantitative Analysis* 53
   (1).
4. Amaya, D., Christoffersen, P., Jacobs, K., & Vasquez, A. (2015). Does
   Realized Skewness Predict the Cross-Section of Equity Returns?
   *Journal of Financial Economics* 118 (1).
5. Patton, A. J. (2011). Volatility Forecast Comparison Using Imperfect
   Volatility Proxies. *Journal of Econometrics* 160 (1).

## Reproduce

```bash
uv run python experiments/k1531/k1531.py
```

Re-running produces identical numbers (seed=42 fixes the bootstrap;
yfinance occasionally adjusts historical adj-close after splits/dividends —
date range pinned).
