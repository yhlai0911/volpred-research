# BTC-GAS Paper — Data Sources & Snapshot Pinning

## Primary data source

**BTC-USD daily close**

- **Provider**: Yahoo Finance via `yfinance` Python package
- **Symbol**: `BTC-USD`
- **Endpoint**: `yfinance.download("BTC-USD", start, end, auto_adjust=False)`
- **Period**: 2015-01-01 → 2026-04-15 (4,121 daily observations)
- **OOS evaluation window**: 2017-01-21 → 2026-04-15 (1,886 days, distributed across three institutional regimes)
- **License**: Yahoo Finance terms of service (free academic use; not redistributable in raw form)
- **`auto_adjust`**: `False` (required per `.claude/rules/paper-workflow.md` data-snapshot rule; preserves dividend/split-adjusted close as primary, raw close as separate column)

## Snapshot pinning (replication requirement)

- **Snapshot timestamp**: 2026-04-15 (last in-sample observation per K1133b record; K1133b results.json `created_at` 2026-04-17T17:04:57 UTC)
- **Snapshot file** (to be added): `paper/btc-gas-negative/data/btc_daily_20260410.csv`
- **Reproduce gate**: `reproduce.py` (to be added) reads local snapshot CSV; **must not** call `yfinance.download` at runtime.
- **Rationale**: Yahoo Finance historical bars can revise retrospectively (dividends, splits, corporate actions). Live fetch would break match_rate gate on revision. K903/K904 sign-flip lesson (2026-04-19) is the canonical reminder.

## Three-period sample split (institutional structure-based, pre-registered)

| Period | Name | Start | End | n_OOS | Rationale |
|--------|------|-------|-----|-------|-----------|
| 1 | Pre-institutional | 2017-01-21 | 2020-12-31 | 1,441 | No spot ETF; no major institutional custody; retail-flow-dominated |
| 2 | FTX-Luna recovery | 2023-01-21 | 2023-12-31 | 345 | Post-crash institutional rebuild |
| 3 | Spot-ETF era | 2024-01-21 | 2024-04-30 | 100 | BlackRock + Fidelity spot ETF approvals 2024-01-10 (preliminary; sample expected to grow to ≥500 days by 2026Q4) |

Period boundaries are **pre-registered** in `experiments/k1133/README.md` (committed 2026-04-12, before K1133b factorial run on 2026-04-15).

## Out-of-distribution check (Appendix B)

- **ETH-USD**: Pre-institutional 2017-2020 same window; yfinance `auto_adjust=False`
- **BNB-USD**: Pre-institutional 2017-2020 same window; yfinance `auto_adjust=False`

Used for directional replication of the BTC Period 1 reversal pattern. Not the primary identification; documented as robustness only.

## Computed quantities (derived from primary source)

All downstream quantities (squared log-returns, realized variance proxy, model parameter MLE estimates, QLIKE losses, DM-HLN test statistics) are computed in:

- `experiments/K1129/k1129.py`
- `experiments/k1133/k1133.py`
- `experiments/k1133b/k1133b.py`

Each script is deterministic given the snapshot CSV and seed `42` (multistart MLE seeds 1–100). No live API calls during evaluation.

## Sensitive material

None. BTC-USD price data is public market data; no proprietary feeds, no PII, no NDA-restricted sources.
