# Paper 6: Data Sources

**Paper**: Periodic Realized GARCH — Session-Boundary Information Transfers

---

## Primary Data

| Variable | Source | Ticker/Code | Sample Period | Frequency | Notes |
|----------|--------|-------------|--------------|-----------|-------|
| TAIFEX TX tick data | TAIFEX (Taiwan Futures Exchange) | TX (near-month contract) | 2012–2026 | Tick (1-min aggregated) | Volume-based contract selection; stored in ~/Dropbox/TAIFEXDATA/ |
| SPY returns | Yahoo Finance (yfinance) | SPY | 2010–2026 | Daily | Log-return; OOS 2018–2026 |
| QQQ returns | Yahoo Finance (yfinance) | QQQ | 2010–2026 | Daily | Cross-asset robustness |
| GLD returns | Yahoo Finance (yfinance) | GLD | 2010–2026 | Daily | Cross-asset robustness |
| EEM returns | Yahoo Finance (yfinance) | EEM | 2010–2026 | Daily | Cross-asset robustness |
| 0050.TW returns | Yahoo Finance (yfinance) | 0050.TW | 2012–2026 | Daily | Taiwan ETF; OOS 2018–2026 |

---

## Session Decomposition

TAIFEX TX trades in two sessions:
- **Daytime**: 08:45–13:45 (Taiwan local time)
- **Night (after-hours)**: 15:00–05:00 next day (UTC+8)

The PRG model uses the overnight session return to predict next-day daytime volatility. This is NOT lookahead: sessions complete sequentially (overnight ends → daytime starts).

---

## Data Storage

| File Location | Contents |
|--------------|----------|
| `~/Dropbox/TAIFEXDATA/` | Raw TAIFEX tick data (not in repo — too large) |
| `experiments/k874/data/` | Processed TAIFEX daily session RV |
| `experiments/k880/data/` | SPY daily data (cached from yfinance) |
| `experiments/k881/data/` | QQQ/GLD/EEM data (cached) |

---

## Reproduction Notes

All non-TAIFEX data can be downloaded automatically via `yfinance`. TAIFEX data requires access to `~/Dropbox/TAIFEXDATA/`. Contact corresponding author for data access.

```bash
# Download and cache all yfinance data:
uv run python paper/prg-periodic-garch/reproduce.py --quick
```
