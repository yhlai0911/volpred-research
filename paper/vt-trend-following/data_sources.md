# Paper 3: Data Sources

**Paper**: Is Volatility Targeting Just Trend Following? Decomposing the Benefits of Volatility Targeting
**Target Journal**: Journal of Portfolio Management / Financial Analysts Journal
**Status**: R1 review — 7 HIGH, needs revision

---

## Primary Data (N=22 asset set — Tables 1, 2)

All equity/commodity/bond data sourced from Yahoo Finance via `yfinance` (free public API, no license required). Daily frequency, auto_adjust=True for total-return (dividend-reinvested) series.

| Variable | Source | Ticker | Sample Period | Frequency | Notes |
|----------|--------|--------|---------------|-----------|-------|
| VIX | yfinance | ^VIX | 1993-01-01 – 2026-03-31 | Daily | CBOE VIX; unadjusted Close; `VIX_{t-1}` drives VT weight at t |
| SPY returns | yfinance | SPY | 1993-01-29 – 2026-03-31 | Daily | S&P 500 ETF; main analysis asset; auto_adjust=True |
| QQQ returns | yfinance | QQQ | 1999-03-10 – 2026-03-31 | Daily | NASDAQ-100 ETF (Table 1, 3) |
| DIA returns | yfinance | DIA | 1998-01-20 – 2026-03-31 | Daily | Dow Jones ETF (Table 1, 3) |
| IWM returns | yfinance | IWM | 2000-05-22 – 2026-03-31 | Daily | Russell 2000 ETF (Table 1, 3) |
| XLF returns | yfinance | XLF | 1998-12-22 – 2026-03-31 | Daily | Financials sector SPDR (Table 1) |
| XLE returns | yfinance | XLE | 1998-12-22 – 2026-03-31 | Daily | Energy sector SPDR (Table 1) |
| EEM returns | yfinance | EEM | 2003-04-14 – 2026-03-31 | Daily | Emerging Markets ETF (Table 1, 5) |
| EFA returns | yfinance | EFA | 2001-08-27 – 2026-03-31 | Daily | MSCI EAFE ETF (Table 1, 5) |
| FXI returns | yfinance | FXI | 2004-10-08 – 2026-03-31 | Daily | China Large-Cap ETF (Table 1, 5) |
| EWZ returns | yfinance | EWZ | 2000-07-14 – 2026-03-31 | Daily | MSCI Brazil ETF (Table 1, 5) |
| GLD returns | yfinance | GLD | 2004-11-18 – 2026-03-31 | Daily | Gold ETF (Table 1, 3 via 50/50 blend) |
| TLT returns | yfinance | TLT | 2002-07-30 – 2026-03-31 | Daily | 20+ Year Treasury ETF (Table 1) |
| SHY returns | yfinance | SHY | 2002-07-26 – 2026-03-31 | Daily | 1-3 Year Treasury ETF; VT cash proxy |

Remaining 10 of the 22-asset set (Table 1 full panel): USO, DBC, IEF, AGG, VNQ, EWJ, EWG, EWU, EWA, EWC — all yfinance, auto_adjust=True, from inception of each ETF through 2026-03-31. Per-asset first-valid dates stored in `experiments/vt_tsmom_final_n22.json` (K55 output).

---

## International Data (N=13 — Table 5, K1178 canonical)

Paper-exact 13-market set (January 2007 – March 2026). All yfinance, auto_adjust=True.

| Region | Ticker | Name | First Valid |
|---|---|---|---|
| Developed | EFA | MSCI EAFE | 2001-08-27 |
| Developed | EWJ | MSCI Japan | 1996-03-18 |
| Developed | EWG | MSCI Germany | 1996-03-18 |
| Developed | EWU | MSCI UK | 1996-03-18 |
| Developed | EWA | MSCI Australia | 1996-03-18 |
| Developed | EWC | MSCI Canada | 1996-03-18 |
| Developed | VGK | Vanguard FTSE Europe | 2005-03-10 |
| Emerging | EEM | MSCI Emerging Markets | 2003-04-14 |
| Emerging | FXI | China Large-Cap | 2004-10-08 |
| Emerging | EWZ | MSCI Brazil | 2000-07-14 |
| Emerging | INDA | iShares MSCI India | 2012-02-06 |
| Emerging | EWT | MSCI Taiwan | 2000-06-23 |
| Emerging | MCHI | MSCI China (Broad) | 2011-04-01 |

**Note**: INDA and MCHI began after 2007; their sub-samples start at ETF inception.

---

## Factor Data (Table 4 FF5 controls, K54/K71)

| Factor | Source | Sample | Notes |
|--------|--------|--------|-------|
| MKT, SMB, HML, RMW, CMA | Kenneth French Data Library | 1990-01 – 2026-03 | FF5 monthly factors; daily via ff_research_data_daily (CSV) |
| MOM (UMD) | Kenneth French Data Library | 1990-01 – 2026-03 | Momentum factor |
| BAB (proxy) | yfinance: IWD−QQQ (pre-2011) + SPLV−SPHB (post-2011) | 1990-01 – 2026-03 | Betting-Against-Beta ETF proxy. Paper claims N=3,740 (SPLV-only post-2011), but `ff5_factor_controls.json` (K54) runs full sample N=5,049 via hybrid splice (see audit D6) |

Kenneth French data: public, no license required (Dartmouth).

---

## Auxiliary Data (Discussion section sources)

| Variable | Source | K Experiment | Purpose |
|----------|--------|-------------|---------|
| Pure TSMOM factor (252-day lookback) | Constructed from SPY in yfinance | K55/K898 | TSMOM orthogonalization (Eq. 3) |
| 12/VIX threshold sweep (thresholds 8–20) | yfinance | K79 → `paper3_fixes.json` | VIX sensitivity robustness |
| Pure-TF strategies (SMA, Faber, Golden, Dual Mom, MA+VT) | yfinance | K518 | Harvey (2016) t>3.0 failure test |
| 427 VT configurations | yfinance | K568 | 12/VIX is return-optimal claim |
| Transaction cost breakeven | yfinance | K499 | daily 3.4 bps / monthly 14.9 bps |
| 50/50 SPY/GLD VT (reconciliation) | yfinance | K687, K688 | Methodology gap footnote |
| VIX predictive power (direction vs magnitude) | yfinance | K697 | r=0.570 magnitude, r=0.042 direction |

---

## Data Storage

| Location | Contents |
|----------|----------|
| `paper/vt-trend-following/experiments/vt_tsmom_final_n22.json` | K55: 22-asset panel Tables 1 & 2 |
| `paper/vt-trend-following/experiments/ff5_factor_controls.json` | K54/K71: Factor model controls Table 4 |
| `paper/vt-trend-following/experiments/paper3_fixes.json` | K79: VIX threshold sensitivity + 5-asset MDD cross-check |
| `paper/vt-trend-following/experiments/k898_paper3_table3_supplement_results.json` | K898: 5-asset Table 3 dual-mechanism supplement |
| `experiments/k1178/k1178_results.json` | K1178: canonical 13-market Table 5 replication |
| `experiments/k1192/k1192_results.json` | K1192: canonical MDD retention block bootstrap Table 6 |
| `experiments/k1193/k1193_results.json` | K1193: canonical split-sample robustness (Section 3.3) |
| `experiments/k518/` | 5 pure-TF strategies Harvey threshold test |
| `experiments/k568/` | 427 VT configuration sweep |
| `experiments/k499/` | Transaction cost breakeven |
| `experiments/k687/`, `experiments/k688/` | 50/50 SPY/GLD reconciliation analyses |
| `experiments/k697/` | VIX direction-vs-magnitude predictive power |
| `storage/experiments/vt_tsmom_final_n22.json` | Backup copy of K55 panel |
| `storage/experiments/ff5_factor_controls.json` | Backup copy of K54/K71 panel |

---

## Methodology Notes

- VT weight rule: `w_t = min(12 / VIX_{t-1}, 1.0)`; remainder `(1 - w_t)` → SHY cash proxy.
- **Lookahead**: enforced via `signal.shift(1)` in all scripts (K898 line 103: `w = w.shift(1)`).
- TSMOM lookback: 252 trading days; signal `sign(cumulative 252d return, shifted 1 day)`.
- Bootstrap: block-bootstrap with 10,000 replications, block size = 252, fixed `seed=42`.
- Rebalancing: paper body describes monthly; K898 uses daily signal (qualitative result robust — see K1192 README §Root cause analysis). K1192 re-runs with monthly rebalancing per paper spec.
- Newey-West HAC lags: 9 (consistent across K55, K1193).
- RF rate: effective ~1–2% implied in paper VT Sharpe; K1178/K1192 use 4% constant (MDD unaffected; Sharpe residual gap noted).

---

## Licenses & Access

- **yfinance**: free public API, no key required (`pip install yfinance`). No commercial redistribution of raw prices, but derived statistics are unrestricted.
- **Kenneth French Data Library**: public domain, CSV download.
- **No proprietary data used**. No TAIFEX, no Bloomberg terminal, no Compustat.

All experiments in this package can be re-run on any machine with internet access and Python >= 3.10.
