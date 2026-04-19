# Paper 4: Data Sources

**Paper**: The True Cost of Volatility Targeting — Insurance Premium Decomposition

---

## Primary Data

| Variable | Source | Ticker/Code | Sample Period | Frequency | Notes |
|----------|--------|-------------|--------------|-----------|-------|
| SPY returns | Yahoo Finance (yfinance) | SPY | 2012-01-01 – 2024-12-31 | Daily | **raw Close (auto_adjust=False) canonical; K811v2 anchor**; pre-cached as `data/spy_2012_2024.csv` |
| GLD returns | Yahoo Finance (yfinance) | GLD | 2012-01-01 – 2024-12-31 | Daily | **raw Close (auto_adjust=False) canonical; K811v2 anchor**; Gold ETF; cross-asset robustness |
| VIX | Yahoo Finance (yfinance) | ^VIX | 2012-01-01 – 2024-12-31 | Daily | CBOE VIX; pre-cached as `data/vix_2012_2024.csv` |
| VVIX | Yahoo Finance (yfinance) | ^VVIX | 2012-01-01 – 2024-12-31 | Daily | VIX of VIX; volatility-of-volatility proxy; pre-cached |

> **Canonical raw Close convention** (2026-04-18): SPY and GLD CSVs contain both `Adj Close` (dividend-adjusted) and `Close` (raw). The `reproduce.py` pipeline and paper canonical statistics (K811v2 anchor) use the **raw Close** column (yfinance `auto_adjust=False`). A prior bundled snapshot used `auto_adjust=True` adjusted close in the `Close` column, which caused a 44% reproduce match rate; see `docs/error_log.md` entry for Paper 4 P4 Sub1 re-bundle. Downstream users must not substitute Adj Close for Close without re-anchoring all VT / buy-and-hold metrics.

---

## Data Storage

Pre-downloaded CSV files are included in the paper folder (no external download needed):

| File | Location | Contents |
|------|----------|----------|
| `spy_2012_2024.csv` | `paper/vt-insurance-cost/data/` | SPY raw Close (auto_adjust=False) + Adj Close + OHLCV |
| `gld_2012_2024.csv` | `paper/vt-insurance-cost/data/` | GLD raw Close (auto_adjust=False) + Adj Close + OHLCV |
| `vix_2012_2024.csv` | `paper/vt-insurance-cost/data/` | VIX daily level |
| `vvix_2012_2024.csv` | `paper/vt-insurance-cost/data/` | VVIX daily level |

### Snapshot Pinning

- `snapshot_date`: `2026-04-19`
- Existing canonical reproduction inputs remain the bundled single-purpose CSVs above.
- Additional pinned manifests created on `2026-04-19`:
  - `spy_gld_vix_vvix_2012-2024_snapshot.csv`
  - `spy_gld_2006-2024_rebal_snapshot.csv`
- `reproduce.py` remains local-data-only and continues to read the canonical per-claim bundles (`spy_2012_2024.csv`, `gld_2012_2024.csv`, `vix_2012_2024.csv`, `vvix_2012_2024.csv`, `spy_2006_2024.csv`, `gld_2006_2024.csv`).

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
