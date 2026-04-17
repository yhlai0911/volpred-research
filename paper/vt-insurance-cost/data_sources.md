# Paper 4: Data Sources

**Paper**: The True Cost of Volatility Targeting — Insurance Premium Decomposition

---

## Primary Data

| Variable | Source | Ticker/Code | Sample Period | Frequency | Notes |
|----------|--------|-------------|--------------|-----------|-------|
| SPY returns | Yahoo Finance (yfinance) | SPY | 2012-01-01 – 2024-12-31 | Daily | Log-return; pre-cached as `data/spy_2012_2024.csv` |
| GLD returns | Yahoo Finance (yfinance) | GLD | 2012-01-01 – 2024-12-31 | Daily | Gold ETF; cross-asset robustness |
| VIX | Yahoo Finance (yfinance) | ^VIX | 2012-01-01 – 2024-12-31 | Daily | CBOE VIX; pre-cached as `data/vix_2012_2024.csv` |
| VVIX | Yahoo Finance (yfinance) | ^VVIX | 2012-01-01 – 2024-12-31 | Daily | VIX of VIX; volatility-of-volatility proxy; pre-cached |

---

## Data Storage

Pre-downloaded CSV files are included in the paper folder (no external download needed):

| File | Location | Contents |
|------|----------|----------|
| `spy_2012_2024.csv` | `paper/vt-insurance-cost/data/` | SPY adjusted close prices |
| `gld_2012_2024.csv` | `paper/vt-insurance-cost/data/` | GLD adjusted close prices |
| `vix_2012_2024.csv` | `paper/vt-insurance-cost/data/` | VIX daily level |
| `vvix_2012_2024.csv` | `paper/vt-insurance-cost/data/` | VVIX daily level |

---

## Strategy Definition

**Volatility Targeting (VT)**:
- Target annualized volatility: 10%
- Daily rebalancing: weight = target_vol / estimated_vol_{t-1}
- Vol estimator: 21-day rolling standard deviation of daily returns
- Signal is lagged: estimated at t−1, applied at t (no lookahead)

**Benchmark**: Constant-weight buy-and-hold (100% SPY)

---

## Notes

- All data is included in the repo (`data/` folder) — no downloads required.
- OOS period: 2023-01-01 to 2024-12-31
- IS period: 2012-01-01 to 2022-12-31
