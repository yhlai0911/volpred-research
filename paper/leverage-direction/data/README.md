# Data — Frozen Replication Vintage

**Status**: FROZEN as of 2026-04-19 canonical snapshot. Do not re-fetch from yfinance.
**Snapshot commit**: see `../data_sources.md` for full pull provenance.

## Contents

| File | Tickers | Period | Freq | Rows |
|---|---|---|---|---|
| `spy_qqq_gld_tlt_eem_iwm_slv_btc_usd_vix_2010-2026.csv` | SPY, QQQ, GLD, TLT, EEM, IWM, SLV, BTC-USD, ^VIX | 2010-01-04 → 2026-04-18 | Daily close | ~4,080 |
| `spy_vix_2004-2026.csv` | SPY, ^VIX | 2004-01-02 → 2026-04-18 | Daily close | ~5,600 |
| `vix_daily.csv` | ^VIX | 1990-01-02 → 2026-04-18 | Daily close | ~9,150 |

Pull command (executed once, 2026-04-19):

```python
yf.download(tickers, start="2010-01-01", end="2026-04-19",
            auto_adjust=False, progress=False)
```

`auto_adjust=False` is a hard requirement — see `.claude/rules/paper-workflow.md`
§Data snapshot pinning. Setting `True` retroactively re-writes split/dividend
adjustments through history and invalidates every number in the paper.

## Do not

- **Do not** re-run `yf.download` to "refresh" these CSVs. Every paper number,
  every table cell, and every figure is pinned to the frozen vintage above.
  yfinance backfill revisions after 2026-04-19 will diverge from published values.
- **Do not** replace individual columns from a newer source. Cross-asset relations
  in Tables 2, 6, and 7 depend on consistent snapshot dates across all assets.
- **Do not** add new tickers here. The primary universe is fixed for the submitted
  version; extensions belong in a follow-up paper.

## To reproduce paper numbers

```bash
uv run python paper/leverage-direction/reproduce.py
```

Reads only these CSVs (no live API calls). Exit 0 + `alert_level=green` +
`traceable_match_rate ≥ 0.95` in `reproduce_report.json` is required before
any submission or ready flip.

## History

- **2026-04-19**: Initial canonical snapshot. All Table 1--12 numbers pinned to
  this vintage.
- **2026-07-01**: Vintage frozen for submission replication package. yfinance
  auto-refresh disabled at the workflow level; snapshot marked as final.

See `REPLICATION.md` in the paper root for the full audit trail of prior data
vintages that were superseded by this snapshot.
