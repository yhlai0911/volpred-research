# Data Sources Catalog — Paper 2: Volatility Targeting in Taiwan

**Snapshot date**: 2026-04-19
**Pinned local CSV**: `paper/taiwan-vt/data/0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv`

The pinned CSV covers the core yfinance panel (0050.TW / TWII / 9 stocks / SPY / VIX).
`reproduce.py` reads stored experiment JSONs rather than live yfinance; this snapshot
is provided for reviewer-package completeness and future local reruns.

---

## 1. Taiwan Equity — Daily (yfinance)

| Asset | Ticker | Source API | Sample Period | N Days | Notes |
|-------|--------|-----------|---------------|--------|-------|
| 0050.TW (Yuanta Taiwan 50 ETF) | `0050.TW` | yfinance | 2009-01-02 – 2026-03 | 4,217 | Earliest yfinance quote; fund launched 2003 but pre-2009 unavailable |
| TWII (TAIEX broad index) | `^TWII` | yfinance | 1997-01 – 2026-03 | 7,148 | Extended to Jan 1997; pre-Jul-1997 ~81 days from Asian Financial Crisis |
| TSMC | `2330.TW` | yfinance | 2008-01 – 2026-03 | ~4,200 | Primary large-cap constituent of 0050.TW |
| Hon Hai Precision | `2317.TW` | yfinance | 2008-01 – 2026-03 | ~4,200 | |
| MediaTek | `2454.TW` | yfinance | 2008-01 – 2026-03 | ~4,200 | |
| Cathay Financial | `2882.TW` | yfinance | 2008-01 – 2026-03 | ~4,200 | |
| Mega Financial | `2886.TW` | yfinance | 2008-01 – 2026-03 | ~4,200 | |
| CTBC Financial | `2891.TW` | yfinance | 2008-01 – 2026-03 | ~4,200 | |
| Chunghwa Telecom | `2412.TW` | yfinance | 2008-01 – 2026-03 | ~4,200 | |
| Yuanta Financial | `2885.TW` | yfinance | 2008-01 – 2026-03 | ~4,200 | |
| Fubon Financial | `2881.TW` | yfinance | 2008-01 – 2026-03 | ~4,200 | |
| Yuanta High Dividend ETF | `0056.TW` | yfinance | 2008-01 – 2026-03 | ~4,200 | ETF (30+ constituents); excluded from primary 9-stock average |
| ELITE Material (2383.TW) | `2383.TW` | yfinance | — | — | Used in K1302 Table 2; **H2 HIGH issue**: disclosed in Table 2 but absent from Sec 2.1 data description — must be added |

*All prices are closing prices, adjusted for dividends and splits (`auto_adjust=True` in
yfinance at time of download; experiments use `auto_adjust=False` for consistency —
see snapshot pinning note in README.md).*

---

## 2. U.S. Market Benchmarks — Daily (yfinance)

| Asset | Ticker | Source API | Sample Period | Notes |
|-------|--------|-----------|---------------|-------|
| S&P 500 ETF (SPY) | `SPY` | yfinance | 2008-01 – 2026-03 | Price return series |
| CBOE VIX | `^VIX` | yfinance | 2008-01 – 2026-03 | Used as Taiwan implied-vol proxy (8.63/VIX strategy) |
| CBOE VXEEM | `^VXEEM` | yfinance | ~2011 – 2026-03 | Emerging-market ETF vol index |
| iShares MSCI Taiwan ETF | `EWT` | yfinance | 2008-01 – 2026-03 | Cross-listed Taiwan exposure |

---

## 3. Asia-Pacific Benchmarks — Daily (yfinance)

| Asset | Ticker | Source API | Notes |
|-------|--------|-----------|-------|
| Nikkei 225 (Japan) | `^N225` | yfinance | Section 5 EAV cross-market; Appendix time-zone |
| Hang Seng (Hong Kong) | `^HSI` | yfinance | Appendix time-zone |
| ASX 200 (Australia) | `^AXJO` | yfinance | Appendix time-zone |
| Straits Times (Singapore) | `^STI` | yfinance | Appendix time-zone |
| KOSPI (South Korea) | `^KS11` | yfinance | Appendix time-zone |
| Sensex (India) | `^BSESN` | yfinance | Appendix time-zone |

---

## 4. VIXTWN — Daily (TAIFEX)

| Asset | Source | Sample Period | Notes |
|-------|--------|---------------|-------|
| VIXTWN (TAIEX Options Vol Index) | TAIFEX official website | 2020-11 – 2026-03 | Computed via CBOE VIX methodology; limited history (post-Nov 2020); used for ratio calibration (VIXTWN/VIX ≈ 1.39) in K1181 |

*Download page: https://www.taifex.com.tw/cht/11/vixFOIndex*

---

## 5. TAIFEX TX Tick Data — High-Frequency (Local Archive)

| Asset | Source | Sample Period | Location | Notes |
|-------|--------|---------------|----------|-------|
| TAIFEX TX Futures Tick | TAIFEX (local archive) | 2010-01 – 2024-12 | `~/Dropbox/TAIFEXDATA/` | 5-min aggregated for K848; tick-level for K847, K851; NOT publicly redistributable |

*Used by K844, K847, K848, K849, K851, K852, K852b, K853, K854.
Reviewers requiring tick data should contact the TAIFEX directly or the authors.*

---

## 6. Macroeconomic Indicators (Section 4 Macro)

| Variable | Source | Frequency | Notes |
|----------|--------|-----------|-------|
| Taiwan Import Growth | DGBAS / FRED | Monthly | Sec 4.1 macro predictor |
| Taiwan Business Cycle Indicator | CEPD (Council for Economic Planning and Development) | Monthly | Sec 4.3 business cycle momentum |
| Earnings Announcement Dates (Taiwan) | TWSE / Bloomberg | Event-date | K1145 EAV panel (N=31 stocks) |
| Earnings Announcement Dates (US) | Compustat / Refinitiv | Event-date | K1147 EAV panel (N=30 S&P 500) |
| Earnings Announcement Dates (Japan) | TSE / Bloomberg | Event-date | K1150 EAV panel (N=30 TOPIX) |

---

## 7. Derived / Computed Variables

| Variable | Derived From | Experiments |
|----------|-------------|-------------|
| Log returns (r_t) | Closing prices: ln(P_t/P_{t-1}) × 100 | All |
| 5-min Realized Volatility (RV) | TAIFEX TX tick (5-min aggregation) | K848, K849, K851, K852, K853 |
| VIXTWN-to-VIX ratio | VIXTWN / VIX (2020-11 window) | K1181 (ratio = 1.39) |
| Overnight gap | 0050.TW open − previous close | K847 |
| VIX-proxy scaling | 8.63 / VIX (calibrated via VIXTWN ratio) | K900, K1175 |

---

## Authorization and Reproducibility Notes

- **yfinance data**: Free, publicly accessible via `pip install yfinance`. Results subject to
  minor variation if yfinance changes its data correction methodology post-snapshot.
- **TAIFEX tick data**: Proprietary; requires institutional subscription or direct data
  purchase from TAIFEX. High-frequency sections (Section 5) cannot be fully reproduced
  without this data.
- **Snapshot pinning**: Core results are reproducible from the pinned CSV
  `data/0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv` without
  live API calls. See `reproduce.py` for field-level traceability.
- **H2 HIGH issue (open)**: ELITE Material (2383.TW) appears in Table 2 (sourced from K1302)
  but is not listed in Section 2.1. This must be resolved before submission.

*Generated: 2026-05-26 — do not edit manually; update via task paper_taiwan_vt_self_contained*
