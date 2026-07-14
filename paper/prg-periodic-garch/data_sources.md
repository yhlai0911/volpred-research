# Paper 6: Data Sources (v7)

**Paper**: Forecast-Timing Conventions and the Value of Overnight Information in Volatility Forecasting

---

## Canonical data = pinned snapshots (single vintage 2026-07-12)

**v7 rule: nothing is fetched live.** Every number in the manuscript derives from
snapshot CSVs pinned inside the two canonical experiments and read back with
`float_precision="round_trip"` (1-ulp parser drift flips MLE basins — K1699 §6):

| Market | Snapshot | OOS period | OOS N |
|---|---|---|---|
| SPY | `experiments/k1699/data/SPY_snapshot.csv` (SHA256 in results JSON) | 2019-01-02 – 2026-04-02 | 1,823 |
| QQQ | `experiments/k1699/data/QQQ_snapshot.csv` | 2018-05-16 – 2026-04-02 | 1,981 |
| GLD | `experiments/k1699/data/GLD_snapshot.csv` | 2019-10-31 – 2026-04-02 | 1,613 |
| EEM | `experiments/k1699/data/EEM_snapshot.csv` | 2019-05-10 – 2026-04-02 | 1,734 |
| 0050.TW | `experiments/k1699/data/0050_TW_snapshot.csv` | 2021-01-08 – 2026-04-02 | 1,251 |
| TAIFEX TX | `experiments/k1699/data/TAIFEX_sessions_snapshot.csv` (+ `_daily_`) | 2022-07-14 – 2025-12-31 | 843 |

`experiments/K1710/data/` holds byte-identical copies; K1710 asserts SHA256
equality with K1699 at runtime.

**Adjustment convention (disclosed in the paper's Data section)**: OHLC series are
dividend- and split-adjusted (yfinance `auto_adjust=True` at download time, then
pinned). Adjusted prices keep predictable ex-dividend jumps out of overnight
returns; the pin — not the flag — is what guarantees reproducibility. See
`docs/error_log.md` 2026-07-14 11:52 for the governance disposition.

## Upstream raw sources

| Variable | Source | Notes |
|---|---|---|
| TAIFEX TX tick | TAIFEX (Taiwan Futures Exchange), volume-selected near-month | Raw ticks in `~/Dropbox/TAIFEXDATA/` (not in repo); 5-min session RV built locally; sessions: day 08:45–13:45, night 15:00–05:00 (UTC+8) |
| SPY / QQQ / GLD / EEM / 0050.TW | Yahoo Finance via yfinance (vintage 2026-07-12) | Snapshot-pinned as above; 0050.TW split-cleaned |

## Reproduction

```bash
uv run python paper/prg-periodic-garch/reproduce.py   # JSON→tex gate; NO network access
uv run python experiments/k1699/k1699.py              # close panel from snapshots (bit-identical)
uv run python experiments/K1710/K1710.py              # open + mixed panels from snapshots (bit-identical)
```

TAIFEX raw-tick access available from the corresponding author; the pinned
session-level snapshots in the repo suffice for full replication of the paper.
