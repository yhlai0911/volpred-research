# K1042: Congressional Trades as Volatility/Return Signal

## Motivation

Congressional stock trading is publicly disclosed and has attracted attention as a potential information signal. Ziobrowski et al. (2004, 2011) found that US senators and representatives earned abnormal returns, suggesting possible informational advantages. This experiment tests whether the **aggregate** buy/sell flow from congressional trades can predict SPY returns or volatility at a market-wide level.

This is a **Category G (leap exploration)** experiment -- entirely different from the GARCH/volatility modeling core of this research program.

## Data

- **Congressional trades**: `data/congressional_trades_house.csv` (15,674 rows, House of Representatives)
  - Transaction dates: 2019-01 to 2022-12
  - Disclosure dates: 2020-01 to 2022-10
  - 8,235 buys, 7,291 sells, 138 exchanges
  - Median disclosure lag: 28 days (consistent with 45-day reporting rule)
- **SPY prices**: yfinance, 2019-01-02 to 2023-06-30 (1,127 trading days after merge)

## Method

### Signal Construction
1. **Count-based net flow**: daily `buy_count - sell_count` on disclosure date
2. **Dollar-weighted net flow**: midpoint of amount range, daily buy_volume - sell_volume
3. **Rolling averages**: 5-day and 21-day rolling means
4. **Cumulative z-score**: standardized cumulative net flow

### Anti-lookahead Design
- Signals keyed on **disclosure_date** (not transaction_date) -- investors cannot act until disclosure
- All signals **shifted by 1 day** (`signal.shift(1)`) before regression/backtest
- Transaction_date signals included only as robustness comparison (with explicit lookahead caveat)

### Tests
- Pearson/Spearman correlations (signal vs return/volatility)
- Granger causality (lags 1-5)
- OLS regressions with Newey-West HAC standard errors (maxlags=10)
- Direction accuracy (binomial test)
- Quintile return analysis
- OOS expanding-window prediction (init=252 days)
- Simple strategy backtest (long when net flow > 0, half when <= 0)

## Key Results

### Return Prediction: NULL
- **No regression passes Harvey (2016) |t| > 3.0 threshold** (0/15 regressions)
- **No regression significant at p < 0.05** for return prediction
- Best return regression: net_volume_roll5_lag1, t = -1.26, p = 0.208
- Direction accuracy: ~47-51%, not significantly different from 50% (all binomial p > 0.11)

### Volatility Prediction: Weak/Marginal
- net_count_roll21_lag1 vs |r|: t = 1.825, p = 0.068, R2 = 0.008 (marginal, fails Harvey)
- net_count_roll21_lag1 vs r2: t = 1.743, p = 0.081, R2 = 0.003 (marginal, fails Harvey)
- Spearman correlation (net_count_roll21 vs |r|): r = 0.14, p < 0.001 -- significant but very weak

### Granger Causality: Mixed Signal
- Disclosure-date signals: net_count -> |r| at lag 3, p = 0.046 (marginal)
- Transaction-date signals (with lookahead): stronger Granger causality for volatility
  - net_count_tx -> r2, lag 4: F = 5.37, p = 0.0003
  - But this uses transaction_date, which has lookahead bias for real-time use

### OOS Prediction: Negative R2
- OOS R2 for returns: **-0.016** (worse than naive mean)
- OOS R2 for volatility: **-0.050** (worse than naive mean)
- OOS direction accuracy: 52.3% (not significant)

### Strategy Backtest
- Congressional signal strategy: Sharpe 0.412 (8.2% ann, 19.9% vol)
- Buy & hold SPY: Sharpe 0.635 (13.9% ann, 21.8% vol)
- Signal strategy **underperforms** buy & hold (t = -2.30, p = 0.022)

### COVID Period
- Pre-crash (Jan 15 - Feb 20, 2020): net flow +1.46 (slightly net buy -- did not anticipate crash)
- Crash (Feb 20 - Mar 23): net flow +0.22 (near neutral)
- Post-crash (Mar 24 - May 1): net flow -0.14 (near neutral)
- Congressional aggregate flow did **not** anticipate the COVID crash

### Quintile Analysis (Counterintuitive)
- High net-sell periods (Q0): 22.7%/yr, Sharpe 1.54
- High net-buy periods (Q3): 9.6%/yr, Sharpe 0.36
- **Net sell > net buy in returns** -- opposite of "smart money" narrative
- But top vs bottom quintile t-test p = 0.66 (not significant)

## Conclusion

**Congressional aggregate trade flow has NO actionable predictive power for SPY returns or volatility at the daily level.** Specifically:

1. **No return prediction**: All regressions fail Harvey threshold; OOS R2 is negative
2. **Marginal volatility link**: 21-day rolling net flow has weak (r = 0.14) positive correlation with subsequent volatility -- more congressional trading activity (in either direction) coincides with higher market volatility. However, this does not survive OOS testing
3. **Not "smart money" at aggregate level**: High net-buy periods actually showed lower returns than high net-sell periods (though not statistically significant). This aligns with Eggers & Hainmueller (2014) who found mediocre performance
4. **Disclosure lag kills any signal**: Even if transaction-date signals show some Granger causality, the 28-day median disclosure lag means retail investors cannot exploit this in real time
5. **Short sample**: Only ~4 years of data (2019-2023) limits statistical power

### Limitations
- House trades only (no Senate)
- Short sample period (4 years, ~1,127 trading days)
- Amount data is coarse (reported as ranges, not exact)
- Aggregate analysis only -- individual "smart" congresspeople (e.g., high-volume traders) might have signal but would require individual-level study

## Files
- `k1042.py` -- experiment script
- `k1042_results.json` -- full results
- `k1042_net_flow_vs_spy.png` -- time series overlay
- `k1042_quintile_returns.png` -- quintile return bar chart

## References
- Ziobrowski et al. (2004) "Abnormal Returns from the Common Stock Investments of the U.S. Senate" JFQA 39(4)
- Ziobrowski et al. (2011) "Abnormal Returns from the Common Stock Investments of Members of the U.S. House" Business and Politics 13(1)
- Eggers & Hainmueller (2014) "Capitol Losses: The Mediocre Performance of Congressional Stock Portfolios" Journal of Politics 76(2)
- Harvey (2016) "... and the Cross-Section of Expected Returns" Journal of Finance -- |t| > 3.0 threshold
