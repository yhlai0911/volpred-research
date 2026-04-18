# Paper 8: Data Sources

**Paper**: The Volatility Absorption Hypothesis

---

## Primary Data

| Variable | Source | Ticker/Code | Sample Period | Frequency | Notes |
|----------|--------|-------------|--------------|-----------|-------|
| SPY returns | Yahoo Finance (yfinance) | SPY | 2006-01-01 – 2026-04-17 | Daily | Log-return × 100; main test asset |
| VIX | Yahoo Finance (yfinance) | ^VIX | 2006-01-01 – 2026-04-17 | Daily | CBOE VIX; regime classification variable |
| QQQ returns | Yahoo Finance (yfinance) | QQQ | 2006-01-01 – 2026-04-17 | Daily | Cross-asset robustness (Table 4) |
| GLD returns | Yahoo Finance (yfinance) | GLD | 2006-01-01 – 2026-04-17 | Daily | Cross-asset robustness (Table 4) |
| EEM returns | Yahoo Finance (yfinance) | EEM | 2006-01-01 – 2026-04-17 | Daily | Cross-asset robustness (Table 4) |
| NFP announcement dates | Manual / FRED | — | 2006–2026 | Monthly | Nonfarm payroll release dates (Table 5) |

---

## VIX Regime Classification

Regimes are defined by VIX level at time t−1:
- Regime 1 (Low): VIX < 15
- Regime 2: 15 ≤ VIX < 20
- Regime 3: 20 ≤ VIX < 25
- Regime 4: 25 ≤ VIX < 30
- Regime 5 (High): VIX ≥ 30

See `experiments/k716/k716_results.json` for regime counts.

---

## Data Storage

| File Location | Contents |
|--------------|----------|
| `experiments/k716/data/` | SPY + VIX processed data |
| `experiments/k718/data/` | Cross-asset data (QQQ/GLD/EEM) |
| `experiments/k897/data/` | SAR null simulation synthetic data |

---

## Notes

- All market data downloadable via `yfinance` (no proprietary data).
- NFP dates are public (available from FRED or BLS website).
- Original estimation scripts for K716–K722 are missing; only JSON results preserved.
  [TODO: Reconstruct scripts before submission]
