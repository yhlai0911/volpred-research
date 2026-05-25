# Paper 1 — Data Sources

**Paper**: Leverage Direction Matters: Cross-Asset Evidence on GARCH Model Selection and Volatility Targeting
**Target Journal**: Journal of Banking and Finance (JBF)
**Snapshot date**: 2026-04-19 (canonical pinning; see `README.md` §Snapshot Pinning)
**Last updated**: 2026-05-25

---

## 1. Pinned local snapshots

All paper numbers and tables are computed off the pinned CSVs in `data/`. The
reproduction harness (`reproduce.py`) reads these snapshots only — it does **not**
issue live API calls. This protects the paper from yfinance vintage drift
(e.g. the 2026-04-19 Normal-row violation count revision in Table 4).

| File | Tickers | Period | Frequency | Source API | Used by |
|---|---|---|---|---|---|
| `data/spy_qqq_gld_tlt_eem_iwm_slv_btc_usd_vix_2010-2026.csv` | SPY, QQQ, GLD, TLT, EEM, IWM, SLV, BTC-USD, ^VIX | 2010-01-04 → 2026-04-18 | Daily (close) | yfinance | Tables 1-3, 6-12, Figs 1-7 (cross-asset GJR, VaR panel, VT backtests) |
| `data/spy_vix_2004-2026.csv` | SPY, ^VIX | 2004-01-02 → 2026-04-18 | Daily (close) | yfinance | Long-history SPY-only tests (Sec 4.5 cumulative-returns, Sec 4.8 VIX-weight timeline 2007 start) |
| `data/vix_daily.csv` | ^VIX | 1990-01-02 → 2026-04-18 | Daily (close) | yfinance | Legacy single-series reference; figure 5 (`fig_vix_weight_timeline.py`) primary input |

**Pull provenance**: `yfinance.download(..., auto_adjust=False, progress=False)`
on 2026-04-19. `auto_adjust=False` is hard-required per
`.claude/rules/paper-workflow.md` §Data snapshot pinning — `True` retroactively
splits dividend / split adjustments back through history, invalidating any
pre-existing numbers in the paper.

---

## 2. Primary asset universe

Seven cross-asset primary instruments + 1 currency-hedged tail (BTC-USD), per
body.tex Table 1:

| Asset | Ticker | Asset class | Sample start | Why included |
|---|---|---|---|---|
| SPY | SPY | US large-cap equity | 2010-01-04 | Reference; GJR γ > 0 leverage |
| QQQ | QQQ | US tech | 2010-01-04 | High β complement |
| GLD | GLD | Gold | 2010-01-04 | Safe haven; γ ≈ 0 / mildly negative |
| TLT | TLT | Long Treasury | 2010-01-04 | Duration; γ near zero |
| EEM | EEM | Emerging markets | 2010-01-04 | EM equity tail |
| IWM | IWM | US small-cap | 2010-01-04 | Size factor |
| SLV | SLV | Silver | 2010-01-04 | Industrial-precious bridge |
| BTC-USD | BTC-USD | Crypto | 2014-09-17 (yfinance first available) | Volatility / γ outlier; shorter history flagged in Table 1 footnote |
| ^VIX | ^VIX | Implied vol index | 1990-01-02 | Hybrid VT switching variable (Sec 3.5) |

BTC-USD's shorter sample is documented in Table 1 (n=2870 vs ~4090 for the
2010-start assets). Tables 6-8 footnote drops BTC where the cross-asset panel
requires a fully balanced window.

---

## 3. License / redistribution

- **Yahoo Finance**: redistribution restrictions allow inclusion of the small
  derived snapshots above as part of an academic replication package
  (non-commercial, attribution to source). CSVs are saved at daily close
  granularity only.
- **^VIX**: CBOE historical OHLC is public domain; yfinance scrape used for
  convenience.

If the paper is accepted, snapshot CSVs ship inside the supplementary materials
ZIP. They are pinned to commit (see `git log paper/leverage-direction/data/`).

---

## 4. Refresh / extension policy

Adding new data to this paper (e.g. extending the OOS window past 2026-04-18)
requires:

1. New yfinance pull with `auto_adjust=False` and a recorded `snapshot_date`
2. Side-by-side rerun of `reproduce.py` on **both** old and new snapshots; any
   number that moves must be footnoted in body.tex, not silently overwritten
   (per `.claude/rules/paper-workflow.md` §Reproduce gate)
3. Update of this file's `Period` column and §1 snapshot table
4. Bump of `snapshot_date` in `README.md` to the new date

Refresh is **not** done automatically. The paper is in R1; reviewer numbers
are pinned until acceptance.

---

## 5. Cross-reference

- `README.md` — top-level paper status + Snapshot Pinning section
- `experiments.md` — table/figure → experiment K-id mapping
- `scripts/README.md` — entry points for figure / table regeneration
- `results/README.md` — index of result JSONs and table outputs
- `reproduce.py` / `reproduce_report.json` — paper-wide claim verification
