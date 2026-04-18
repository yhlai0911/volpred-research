# Paper 4: Data Sources

**Paper**: Can Anything Beat VIX? A Systematic Out-of-Sample Evaluation of Eleven Signal Families for Equity Volatility Forecasting and Volatility Timing

---

## Primary Data

| Variable | Source | Ticker/Code | Sample Period | Frequency | Notes |
|----------|--------|-------------|--------------|-----------|-------|
| SPY returns | Yahoo Finance (yfinance) | SPY | 1993-01-01 – 2026-04-17 | Daily | Log-return × 100; main prediction target |
| VIX | Yahoo Finance (yfinance) | ^VIX | 1993-01-01 – 2026-04-17 | Daily | CBOE VIX; lagged 1 day to enforce no-lookahead |
| VIX3M | Yahoo Finance (yfinance) | ^VIX3M | 2000-01-01 – 2026-04-17 | Daily | 3-month VIX; term structure Family 2 |
| VIX9D | Yahoo Finance (yfinance) | ^VIX9D | 2011-01-01 – 2026-04-17 | Daily | 9-day VIX; term structure Family 2 |
| VVIX | Yahoo Finance (yfinance) | ^VVIX | 2007-01-01 – 2026-04-17 | Daily | VIX of VIX; tested in K1116/K1118 alt-data |
| GLD returns | Yahoo Finance (yfinance) | GLD | 2004-11-01 – 2026-04-17 | Daily | Gold ETF; cross-asset momentum Family 1 + K1118 |
| GVZ | Yahoo Finance (yfinance) | ^GVZ | 2008-06-01 – 2026-04-17 | Daily | CBOE Gold Volatility Index; K1118 cross-asset IV |
| TLT returns | Yahoo Finance (yfinance) | TLT | 2002-07-01 – 2026-04-17 | Daily | 20yr bond ETF; cross-asset momentum Family 1 + K1118 |
| MOVE Index | Yahoo Finance / FRED | MOVE | 1988-01-01 – 2026-04-17 | Daily | ICE BofA bond market vol; K1118 bond IV |
| USO returns | Yahoo Finance (yfinance) | USO | 2006-04-01 – 2026-04-17 | Daily | Oil ETF; cross-asset momentum Family 1 |
| UUP returns | Yahoo Finance (yfinance) | UUP | 2007-02-01 – 2026-04-17 | Daily | USD ETF; cross-asset momentum Family 1 |
| HYG, LQD | Yahoo Finance (yfinance) | HYG, LQD | 2007-01-01 – 2026-04-17 | Daily | Credit spread proxy; cross-asset momentum Family 1 |
| BTC-USD | Yahoo Finance (yfinance) | BTC-USD | 2014-09-01 – 2026-04-17 | Daily | Bitcoin; Family 7 Granger causality |
| EPU | FRED | USEPUINDXD | 2000-01-01 – 2026-04-17 | Daily | US Economic Policy Uncertainty (Baker-Bloom-Davis 2016); K1116/K1118 |
| NFCI | FRED | NFCI | 1971-01-01 – 2026-04-17 | Weekly (Fri) | Chicago Fed National Financial Conditions Index; K1116 |
| ANFCI | FRED | ANFCI | 1971-01-01 – 2026-04-17 | Weekly (Fri) | Adjusted NFCI; K1116 |
| STLFSI4 | FRED | STLFSI4 | 1993-01-01 – 2026-04-17 | Weekly (Fri) | St. Louis Fed Financial Stress Index v4; K504/K1116 |
| WLEMU | FRED | WLEMUINDXD | 2000-01-01 – 2026-04-17 | Daily | World Uncertainty Index (Europe); K1116/K1117 |
| Google Trends | pytrends (Google) | 5 fear terms | 2004-01-01 – 2026-04-17 | Weekly | "stock market crash", "recession", etc.; Family 9 (K750) |
| Put-Call Ratio | CBOE (via yfinance/manual) | PCR | 1995-01-01 – 2026-04-17 | Daily | Behavioral sentiment Family 3 |
| 10Y–2Y yield spread | FRED | GS10, GS2 | 1993-01-01 – 2026-04-17 | Daily | Yield curve Family 10 (K749) |

---

## Cross-Asset Expansion Data (K1129, K1135, K1136, K1137, K1138)

| Variable | Source | Ticker | Sample | Notes |
|----------|--------|--------|--------|-------|
| QQQ | yfinance | QQQ | 2000-01-01 – 2026-04 | Equity; K1138 equity compendium |
| IWM | yfinance | IWM | 2000-05-01 – 2026-04 | Small-cap equity; K1138 |
| UNG | yfinance | UNG | 2007-04-01 – 2026-04 | Natural gas ETF; K1129/K1136 commodity |
| BTC-USD | yfinance | BTC-USD | 2014-09-01 – 2026-04 | Crypto; K1129/K1136 |
| Realized Variance (5-min) | QuantQuote / Oxford-Man | SPY 5-min | 2000–2026 | Used as proxy in K1137/K1138/K1139 HAR-RV; source: computed from OHLC Parkinson estimator where intraday unavailable |

---

## Publication Delay Notes (from K1116b)

- NFCI/ANFCI: released with ~5-business-day delay (weekly data released following Thursday/Friday)
- STLFSI4: similar ~5-day delay
- EPU: daily but based on news sources; same-day availability in real-time uncertain
- K1116 original used `shift(1)` on weekly data; K1116b re-verified with proper 5-day delay; most conclusions hold; TLT M4 cell collapses under strict delay correction

---

## Data Processing

- Returns: log(P_t/P_{t-1}) × 100 (percentage log-returns)
- All signals enforced via `signal.shift(1)` before multiplying by returns (no lookahead)
- Weekly aggregation for FRED series: end-of-week (Friday) value aligned to trading calendar
- Transaction costs: 5 bp per leg on weight changes (buy + sell)
- OOS evaluation window: 2008-01-01 – 2026-04-17 for main results
- Era boundaries: 1993–1999 (pre-dot-com), 2000–2007 (dot-com+), 2008–2011 (GFC), 2012–2019 (post-GFC), 2020–2026 (COVID+)

---

## Experiment-Level Data

Raw data cached in experiment-level `data/` subdirectories where applicable:

- `experiments/k1121/data/` — SPY+GLD aligned daily (for allocation K1121)
- `experiments/k1130/` — TAIFEX TX 5-min bars parquet (K1130)
- `experiments/k504/data/` — STLFSI4 + SPY

For other experiments, data downloaded fresh via yfinance/FRED at script runtime.
