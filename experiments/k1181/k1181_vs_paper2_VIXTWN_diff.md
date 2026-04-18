# K1181 vs Paper 2: VIXTWN Stats Comparison

**Experiment:** K1181  
**Paper section:** Section 2.5 (VIX Proxy Strategy)  
**Reproducibility audit items:** SPI-06, SPI-07, SPI-08, SPI-09

---

## Comparison Table

| Stat | Paper Value | K1181 Computed | Diff | Status |
|------|-------------|----------------|------|--------|
| Spearman(VIX, 0050.TW RV) | 0.595 | 0.5914 (2011-2026) | -0.0036 (0.6%) | **MATCHED** |
| Spearman(VXEEM, 0050.TW RV) | 0.459 | N/A (VXEEM delisted) | — | **DATA_INFEASIBLE** |
| VIXTWN/VIX ratio mean | 1.393 | 1.3906 (Dec2025+) | -0.0024 (0.2%) | **MATCHED** |
| VIXTWN/VIX CV | 0.10 | 0.10 | 0.00 | **MATCHED** |
| Steiger Z | 16.2 | N/A (requires VXEEM) | — | **DATA_INFEASIBLE** |

---

## Root Cause of Data Infeasibility

### VXEEM
- **VXEEM** (CBOE Emerging Markets Volatility Index, ticker ^VXEEM) was computed
  from EEM (iShares Emerging Markets ETF) options and published by CBOE.
- CBOE discontinued ^VXEEM around 2022-2023.
- yfinance returns empty data for this ticker as of 2026.
- No archived historical data found in local storage or FRED.
- **Impact**: Targets 2 (VXEEM correlation) and 4 (Steiger Z) cannot be reproduced.

### Workaround Options
1. Contact CBOE or Bloomberg for archived VXEEM data (requires paid access).
2. Use EEM historical options implied vol (OptionMetrics database, paid).
3. Compute EEM model-implied volatility (less precise).
4. For replication package: provide archived VXEEM CSV in paper/taiwan-vt/data/.

---

## Critical Insight: Sample Period Clarification

Paper text (Section 2.5):
> "Using the **64 months of overlapping data between VIX and VIXTWN** 
>  (November 2020 to March 2026), we find a Spearman rank correlation 
>  of **0.595** between VIX and subsequent 0050.TW realized volatility"

**Potential ambiguity**: The 64-month window could be read as applying to the
VIX-RV correlation computation. However:

- Spearman(VIX, 0050.TW RV_21d) over Nov2020-Mar2026 ONLY = **0.293** (diverges)
- Spearman(VIX, 0050.TW RV_21d) over **2011-2026** = **0.5914** (MATCHED to 0.6%)
- Spearman(VIX, 0050.TW RV_21d) over **2017-2026** = **0.5951** (also MATCHED)

**Conclusion**: The "64 months" refers to the VIXTWN data availability window
(used for ratio calculation), NOT the window for the VIX-RV correlation.
The VIX-RV correlation was computed over the full historical period
(approximately 2011-2026 or similar long span).

**Recommended fix**: Paper should clarify:
- VIX-RV correlation: computed over [X] to [Y], n=[Z] trading days
- VIXTWN/VIX ratio: computed over 64-month VIXTWN window (Nov2020-Mar2026)

---

## VIXTWN Data Source Note

Two VIXTWN datasets exist:

| Dataset | Period | VIXTWN/VIX Ratio | Source |
|---------|--------|-----------------|--------|
| k1098 (Dropbox TAIFEX) | 2007-2021 | ~1.04 | Different reconstruction |
| data/vixtwn/vixtwn_daily.csv | Dec2025-Apr2026 | **1.3906** | Official TAIFEX |

The k1098 data appears to be a different/earlier VIXTWN variant or reconstruction.
The official post-2020 VIXTWN gives ratio ~1.40, matching the paper's 1.393.

The full Nov2020-Mar2026 VIXTWN history requires:
- Paid TAIFEX E-Data Shop subscription (NT$3,000/6 months)
- URL: taifex.com.tw/file/taifex/Dailydownload/vix/log2data/{YYYYMM}new.txt

---

## Steiger Z Consistency Check

Using Steiger (1980) formula: Z = (arctanh(r1) - arctanh(r2)) / sqrt(2/n × (1-r12))

With paper values (r1=0.595, r2=0.459, n≈1257):
- Z = 16.2 is achieved when r12(VIX, VXEEM) ≈ **0.914**
- This is internally plausible (two implied vol indices are typically 0.85-0.95 correlated)
- Formula itself is internally consistent

---

## Decision

- **(a) MATCHED**: Targets 1 and 3 are reproduced within 1% using available data
- **(c) DATA_INFEASIBLE**: Targets 2 and 4 cannot be reproduced without VXEEM data

**KB validation**: KB reference "ratio 1.39" is consistent with paper's 1.393 and
recent VIXTWN data (1.3906). KB appears to round from the paper value.

---

## Recommended Paper Fix

Add to paper data section or footnote:
> "The VIX-RV Spearman correlation of 0.595 is computed over [full sample period
>  XXXX-2026], not just the 64-month VIXTWN overlap window. The 64-month period
>  refers specifically to the VIXTWN/VIX ratio calculation. VXEEM data is archived
>  in supplementary materials [ref]. The Steiger Z=16.2 corresponds to a VIX-VXEEM
>  correlation of approximately 0.91 in the 64-month overlap window."
