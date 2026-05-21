# K1319: HAR + Wavelet Decomposition — Daily RV Forecasting (Preliminary)

**Date:** 2026-05-22
**Proposer:** 賴奕豪 · **Executor:** Claude
**Seed:** 42
**Status:** COMPLETE — NULL

## Research Question

Does replacing HAR's simple rolling-average lag structure with DWT (Discrete Wavelet Transform) coefficients improve out-of-sample daily RV forecasting?

Standard HAR decomposes variance memory via 1d/5d/22d rolling sums — a crude frequency decomposition. Wavelet HAR (HAR-W) applies orthogonal DWT to extract multi-scale spectral components explicitly, potentially capturing non-stationary or nonlinear volatility dynamics that HAR averages miss.

**Preliminary note:** The target paper (ScienceDirect 2026) uses 5-min RV. This experiment uses the daily squared-return RV proxy (r²_t) as a preliminary test. Full replication with 5-min data is deferred to ETA 2026 Q2.

## Data

- Asset: SPY (S&P 500 ETF)
- Source: `paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv`
- Period: 2010-01-01 to 2026-05-20
- RV proxy: (log return)² — daily squared log return
- Training (IS): 2010-01-01 to 2019-12-31
- OOS: 2020-01-01 to 2026-05-20

## Lookahead Policy

- Target: RV_{t+1} (next trading day RV)
- Features computed from {RV_1, ..., RV_t} only
- Implementation: `rv_lead = rv.shift(-1)` + drop last row
- No data from t+1 onwards enters any feature

## Models

| ID | Description |
|---|---|
| EWMA | EWMA (λ=0.94) — pure baseline |
| HAR | Standard HAR: RV_{t+1} = α + β_d*RV_t + β_w*RV5̄ + β_m*RV22̄ |
| HAR-W-4 | HAR-Wavelet: DWT(db4, L=4) summary features via OLS |
| HAR-W-3 | HAR-Wavelet: DWT(db4, L=3) alternative window |

**HAR-W feature construction:**
- Window: past W=64 trading days of RV
- DWT levels: db4 wavelet, 4 decomposition levels
- Features per level: last-value of approximate/detail coefficients
- Total features: 5 (cA4, cD4, cD3, cD2, cD1)
- Train by OLS on IS data

## OOS Results (2020–2026, N=1613)

| Model | QLIKE | MSE | DM vs HAR (t / p) |
|---|---|---|---|
| EWMA-0.94 | -8.118 | 3.54e-7 | — |
| HAR | **-8.175** | **3.18e-7** | (baseline) |
| HAR-W (energy) | -7.974 | 7.03e-7 | +6.29 / <0.001 |

**HAR-W is significantly WORSE than HAR** on both QLIKE and MSE.
DM t=+6.29 (positive = HAR-W has higher loss), p<0.001.

**Root cause:** Daily r² is high-noise; wavelet energy features amplify that noise
rather than extracting meaningful multi-scale structure. Standard HAR rolling
averages act as efficient low-pass filters by design. A test with true 5-min RV
(ETA Q2 2026) may give different results.

**Verdict: NULL** — Wavelet decomposition does not improve HAR with daily r² proxy.

## Success Criteria

- HAR-W vs HAR: DM test, Harvey (1997) correction, α=0.05
- Verdict PASS: HAR-W QLIKE < HAR QLIKE, DM |t| > 2 (corrected), p < 0.05
- Verdict CONDITIONAL_PASS: significant improvement in QLIKE but not all metrics
- Verdict NULL: no significant improvement (DM p > 0.05)

## References

- Corsi (2009) — original HAR model [Journal of Financial Econometrics]
- Mallat (1989) — DWT multiresolution analysis
- ScienceDirect 2026 — HAR + Wavelet Decomposition (full intraday version)
- Harvey, Leybourne & Newbold (1997) — DM test size correction
