# Paper 9: Data Sources

**Paper**: Multiplicative GARCH-X with VIX: A Parsimonious Alternative to GARCH-MIDAS for Volatility Forecasting and Risk Management

---

## Primary Data

| Variable | Source | Ticker | Sample Period | Frequency | Notes |
|----------|--------|--------|--------------|-----------|-------|
| SPY returns | Yahoo Finance (yfinance) | SPY | 2000-01-01 – 2026-04-08 | Daily | Adjusted close; IS: 2000–2018, OOS: 2019-01-01 – 2026-04-08 (n_OOS=1,825) |
| VIX | Yahoo Finance (yfinance) | ^VIX | 2000-01-01 – 2026-04-08 | Daily | CBOE Volatility Index; lagged 1 day (shift(1)) to avoid lookahead |
| VIX9D | Yahoo Finance (yfinance) | ^VIX9D | 2011-01-01 – 2026-04-08 | Daily | 9-day VIX variant; shorter sample used in robustness section |
| VIX3M | Yahoo Finance (yfinance) | ^VIX3M | 2000-01-01 – 2026-04-08 | Daily | 3-month VIX variant |
| QQQ returns | Yahoo Finance (yfinance) | QQQ | 2000-01-01 – 2026-04-08 | Daily | Cross-asset validation |
| EEM returns | Yahoo Finance (yfinance) | EEM | 2003-01-01 – 2026-04-08 | Daily | Cross-asset validation |
| GLD returns | Yahoo Finance (yfinance) | GLD | 2004-11-01 – 2026-04-08 | Daily | Cross-asset; paired with GVZ |
| GVZ | Yahoo Finance (yfinance) | ^GVZ | 2008-06-01 – 2026-04-08 | Daily | CBOE Gold Volatility Index (asset-matched IV for GLD) |
| FEZ returns | Yahoo Finance (yfinance) | FEZ | 2002-10-01 – 2026-04-08 | Daily | EURO STOXX 50 ETF; European cross-asset |
| 0050.TW returns | Yahoo Finance (yfinance) | 0050.TW | 2009-01-01 – 2026-04-08 | Daily | Taiwan; split-adjusted (1:4 pre-2014 correction per Lai 2026) |
| VIXTWN | TAIFEX / yfinance | — | 2006-01-01 – 2021-12-31 | Daily | Taiwan implied vol; used in K1098 Taiwan robustness |

---

## Data Processing Notes

- All returns computed as log(P_t / P_{t-1}) × 100 (percentage log-returns)
- VIX enters models as VIX_{t-1} (lagged one day) — enforced via `signal.shift(1)` in all scripts
- 0050.TW split-adjustment: unadjusted 1:4 stock split before 2014 corrected per procedure in `experiments/k1077/`
- IS window: rolling 2,000 trading days; refitted every 63 trading days (29 total refits for main OOS window)
- Missing data handled by forward-fill (max 5 consecutive days); days with any missing variable excluded

---

## Experiment-Level Data

Raw price/return data is stored within individual experiment directories:

- `experiments/k988/data/` — SPY + VIX daily returns (parquet)
- `experiments/k989/data/` — MF2-VIX² synthesis data
- `experiments/k1085/data/` — GLD + GVZ data
- `experiments/k1088/data/` — USO + OVX data
- `experiments/k1098/data/` — 0050.TW + VIXTWN data (2006–2021)

---

## External References

- Yahoo Finance API via `yfinance` Python package
- TAIFEX VIXTWN: Taiwan Futures Exchange, Options Market Statistics page
- Bekaert & Hoerova (2014): VIX² = E[RV] + VRP decomposition
- Patton (2011): QLIKE loss function is robust to noise in volatility proxy
