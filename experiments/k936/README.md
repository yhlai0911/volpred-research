# K936: Time-Varying Hurst Exponent via Rolling Estimation

## Problem
K529 used a fixed Hurst exponent (H=0.1) for rough volatility and found HAR-Rough significantly beats GJR (DM=-7.04) but not EWMA. The Rough Volatility literature (Gatheral et al. 2018) established H≈0.1 for financial assets, but H may vary over time. This experiment tests whether a **time-varying H(t)** estimated via rolling R/S analysis and DFA contains predictive information for volatility **beyond what VIX already captures**.

## Motivation
- arXiv:2509.05820 proposed EWMA-driven time-varying H(t) in rBergomi models
- K889 confirmed MF-GJR(VIX) as the best model with QLIKE improvement of ~2.6% over GJR
- Question: Does the fractal structure of volatility (captured by H) provide incremental information that VIX misses?

## Method
1. **Hurst Estimation**: Two methods applied to |r_t| (absolute returns) with rolling 63-day windows:
   - R/S (Rescaled Range) analysis — classical
   - DFA (Detrended Fluctuation Analysis) — more robust for non-stationary series
2. **Models tested** (7 total):
   - GARCH(1,1) — baseline
   - GJR-GARCH(1,1) — standard asymmetric
   - MF-GJR(VIX) — current best (K889)
   - MF-GJR(H_RS) — Hurst R/S only
   - MF-GJR(H_DFA) — Hurst DFA only
   - MF-GJR(VIX, H_RS) — both VIX and Hurst R/S
   - MF-GJR(VIX, H_DFA) — both VIX and Hurst DFA
3. **Evaluation**: QLIKE on r², Spearman rank correlation, DM test with Harvey (2016) |t|>3.0

## Data
- Asset: SPY
- Source: yfinance
- Period: 2005-01-04 to 2026-04-02 (n=5,345)
- OOS: 2016-01-04 to 2026-04-02 (2,577 days)
- Window: 2000, Refit every 63 days

## Key Results

### Hurst Descriptive Statistics
| Method | Mean | Std | Min | Max |
|--------|------|-----|-----|-----|
| R/S | 0.576 | 0.067 | 0.396 | 0.746 |
| DFA | 0.686 | 0.186 | 0.039 | 1.412 |

- Correlation R/S vs DFA: rho = 0.180 (low agreement between methods)
- Correlation H_RS vs log(VIX): rho = 0.121 (weak — Hurst captures different information)

### QLIKE on r² (lower = better)
| Model | QLIKE | % vs GJR |
|-------|-------|----------|
| GARCH | 1.5868 | +1.13% |
| GJR | 1.5691 | 0.00% |
| **MF-GJR(VIX)** | **1.4710** | **-6.25%** |
| MF-GJR(H_RS) | 1.5675 | -0.10% |
| MF-GJR(H_DFA) | 1.5666 | -0.16% |
| MF-GJR(VIX,H_RS) | 1.4754 | -5.97% |
| MF-GJR(VIX,H_DFA) | 1.4712 | -6.24% |

### DM Tests vs GJR (Harvey |t|>3.0)
| Model | t-stat | Significant? |
|-------|--------|-------------|
| MF-GJR(VIX) | -4.49 | YES |
| MF-GJR(H_RS) | -0.12 | NO |
| MF-GJR(H_DFA) | -0.20 | NO |
| MF-GJR(VIX,H_RS) | -4.22 | YES |
| MF-GJR(VIX,H_DFA) | -4.45 | YES |

### The Key Test: Does Hurst Add to VIX?
| Model | DM t vs MF-GJR(VIX) | QLIKE change |
|-------|---------------------|--------------|
| MF-GJR(VIX,H_RS) | +1.77 (NS) | +0.30% (worse) |
| MF-GJR(VIX,H_DFA) | +0.17 (NS) | +0.02% (negligible) |

**Hurst does NOT add significant information beyond VIX.**

### Does Hurst Alone Beat GARCH?
| Model | DM t vs GARCH | Significant? |
|-------|---------------|-------------|
| MF-GJR(H_RS) | -0.80 | NO |
| MF-GJR(H_DFA) | -0.87 | NO |

**Hurst alone has no significant predictive power even vs plain GARCH.**

## Conclusions

1. **MF-GJR(VIX) remains the best model** (QLIKE -6.25% vs GJR, DM t=-4.49)
2. **Daily-frequency Hurst exponent has no meaningful predictive power** for next-day volatility
3. **Hurst does NOT add incremental value beyond VIX** — adding H(t) to MF-GJR(VIX) either worsens or leaves QLIKE unchanged
4. **Hurst alone does NOT beat even GARCH** — DM tests all non-significant
5. **The two Hurst methods (R/S and DFA) agree**: both fail to improve predictions

### Why?
- H(t) estimated from daily |r_t| is **noisy** (R/S std=0.067 with mean 0.576)
- The correlation between H(t) and VIX is weak (rho=0.121), so H captures *different* information — but that information is not useful for predicting next-day σ²
- Rough volatility may require **intraday data** to estimate H reliably (the original Gatheral et al. 2018 result used 5-min data)
- The 63-day rolling window may be too short/long — but the DFA method (which is more robust) gives equally poor results

### Comparison with K529
- K529 found HAR-Rough (fixed H=0.1) beats GJR with DM=-7.04, but that model used HAR structure (which inherently captures multi-timescale volatility)
- Time-varying H(t) in a multiplicative factor framework does not provide the same benefit
- The K529 result was likely driven by HAR's multi-timescale aggregation rather than by Hurst per se

## Limitations
- Only SPY tested (single asset)
- Rolling Hurst estimation uses daily data only; intraday H estimation might perform differently
- OOS period 2016-2026 includes both calm and volatile regimes
- R/S and DFA are classical methods; wavelet-based or MLE-based H estimation was not tested

## Files
- `k936.py` — Experiment script
- `k936_results.json` — Full results
- `k936_hurst_timeseries.png` — H(t) time series + VIX
- `k936_comparison.png` — Model comparison bar charts
- `k936_hurst_vix_scatter.png` — H(t) vs VIX scatter

## References
- Gatheral, Jaisson & Rosenbaum (2018). Volatility is rough. QF 18(6):933-949.
- arXiv:2509.05820: EWMA-driven time-varying H in rBergomi
- Patton (2011). J Econometrics 160:246-256.
- Harvey et al. (2016). JBES 34:92-104.
- Engle, Ghysels & Sohn (2013). RES 95(3):776-797.
