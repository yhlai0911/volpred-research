# K978: Congressional Trading vs SPY Volatility

## Research Question
Does aggregate congressional trading activity (disclosed under the STOCK Act) predict SPY realized volatility beyond what VIX already captures?

## Motivation
- US congressional members' stock trades are publicly disclosed, with a well-documented literature suggesting potential information advantages (Ziobrowski et al. 2004 JFE, Eggers & Hainmueller 2013)
- If congresspeople trade on policy-relevant information, aggregate trading patterns might signal upcoming market turbulence
- Key challenge: disclosure delays (median 28 days) severely limit real-time signal utility

## Data
- **Congressional trades**: `data/congressional_trades_house.csv` (15,674 records)
  - Disclosure period: 2020-01-02 to 2022-10-30
  - Transaction period: 2012-06-19 to 2022-12-31
  - Mean disclosure delay: 58.5 days (median: 28 days)
- **SPY + VIX**: yfinance, 2020-01-01 to 2026-04-07
- **Signal date**: disclosure_date (publicly available), NOT transaction_date (avoids lookahead bias)
- Merged sample: 1,562 observations

## Method
1. Aggregate daily congressional trading activity by disclosure date (buys, sells, net, volume)
2. Granger causality tests (lags 1-5)
3. Partial correlation controlling for VIX
4. HAC-robust regression: fwd_rv5 = a + b1*VIX + b2*Congress_activity
5. Event analysis: forward vol after high-activity vs normal days
6. Quintile sort on net selling signal

## Key Results

### Granger Causality: No significance
- Volume -> RV5: all lags p > 0.06 (not significant)
- Net -> RV5: all lags p > 0.18 (not significant)

### Correlations
| Variable | r with fwd_rv5 | p-value |
|----------|----------------|---------|
| VIX | 0.7003 | <0.0001 |
| Daily volume | 0.1039 | <0.0001 |
| Daily net | 0.0184 | 0.4676 |
| Partial(volume\|VIX) | -0.0576 | 0.0228 |
| Partial(net\|VIX) | -0.0067 | 0.7909 |

### Regression (HAC standard errors)
| Model | R-squared | Congress variable | t-stat | p-value |
|-------|-----------|-------------------|--------|---------|
| VIX only | 0.4905 | - | - | - |
| VIX + volume | 0.4922 | volume | -1.871 | 0.061 |
| VIX + net | 0.4905 | net | -0.421 | 0.674 |
| VIX + both | 0.4922 | volume: -2.00, net: -0.62 | - | 0.046, 0.536 |

### Event Analysis
- High activity days (>2 sigma, n=51): mean fwd_rv5 = 0.2189
- Normal activity days (n=534): mean fwd_rv5 = 0.1947
- No disclosure days (n=977): mean fwd_rv5 = 0.1407
- T-test high vs normal: t=0.687, p=0.495 (not significant)

### Quintile Analysis (Net Selling Signal)
- No monotonic relationship between net selling quintiles and forward vol

## Conclusion
**Congressional trading activity does NOT provide a reliable predictive signal for SPY volatility beyond VIX.**

- Raw correlation between disclosure volume and forward vol (r=0.1039) is spurious -- both co-move with market stress
- After controlling for VIX, partial correlations are negligible (|r| < 0.06)
- No regression coefficient passes the Harvey (2016) |t| > 3.0 threshold
- Incremental R-squared from adding congressional variables: 0.0017 (0.17%)
- Granger causality fails at all lags

**Primary causes of null result:**
1. Disclosure delay (median 28 days, mean 58.5 days) -- by the time trades are public, information is stale
2. VIX already captures volatility expectations efficiently
3. Most congressional trading is routine portfolio management, not informed trading
4. Sample limited to 2020-2022 disclosure period

## Limitations
- Short sample (congressional data only covers ~3 years of disclosures)
- Amount data is range-based (used midpoint estimates)
- Cannot distinguish informed vs routine trading
- No control for market-wide factors beyond VIX
- Senate data not included (House only)

## Files
- `k978_congress_vol.py` -- main analysis script
- `k978_congress_vol_results.json` -- structured results
- `k978_trading_activity.png` -- time series of congressional activity vs SPY vol
- `k978_conditional_vol.png` -- conditional volatility analysis (scatter, boxplot, rolling corr, quintiles)

## References
- Ziobrowski et al. (2004) "Abnormal Returns from the Common Stock Investments of the United States Senate" JFE
- Eggers & Hainmueller (2013) "Capitol Losses: The Mediocre Performance of Congressional Stock Portfolios"
- Harvey (2016) "...and the Cross-Section of Expected Returns" RFS
