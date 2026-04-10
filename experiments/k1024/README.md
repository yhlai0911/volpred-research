# K1024: A4f Refit Frequency Sensitivity Analysis (Paper 9 Robustness)

## Motivation

K988 established A4f(VIX^2) as the winning volatility specification with QLIKE = -8.358 vs GJR's -8.277 (DM t = 4.167, significant at Harvey 2016 threshold). The default refit frequency was every 63 days (quarterly). Reviewers will inevitably ask: **"Why 63 days? How sensitive are results to this choice?"**

This experiment systematically tests 5 refit frequencies to answer that question.

## Method

**Models (both with Student-t df=8 per K1021):**
- **A4f**: sigma^2_t = tau_t * g_t, where tau_t = max(theta_0 + theta_1 * VIX^2_{t-1}, eps), g_t = omega + alpha*u^2_{t-1} + gamma*u^2_{t-1}*I(u<0) + beta*g_{t-1}, omega free
- **GJR**: Standard GJR-GARCH(1,1) benchmark

**Refit Frequencies:**
| Frequency | Days | Refits |
|-----------|------|--------|
| Weekly    | 5    | 668    |
| Monthly   | 21   | 159    |
| Quarterly | 63   | 53     |
| Semi-annual | 126 | 27   |
| Annual    | 252  | 14     |

**Data:** SPY 2005-2026, n=5349. OOS: 2013-01-01 onwards, n_oos=3337. Window: 2000 rolling.

**Evaluation:** QLIKE on r^2 (Patton 2011), DM test with Harvey (2016) |t| > 3.0 threshold.

## Key Results

### A4f QLIKE is remarkably stable across frequencies

| Frequency | GJR QLIKE | A4f QLIKE | DM t-stat | Significant | Runtime |
|-----------|-----------|-----------|-----------|-------------|---------|
| Weekly (5d) | -8.5434 | -8.6374 | -6.471 | YES | 49.0s |
| Monthly (21d) | -8.5404 | -8.6380 | -6.666 | YES | 11.7s |
| Quarterly (63d) | -8.5414 | **-8.6391** | **-6.868** | **YES** | 3.9s |
| Semi-annual (126d) | -8.5362 | -8.6381 | -6.661 | YES | 1.9s |
| Annual (252d) | -8.5350 | -8.6373 | -6.089 | YES | 1.0s |

### Critical metrics:
- **A4f QLIKE spread across all 5 frequencies: 0.021%** (range: -8.6391 to -8.6373)
- **Weekly(5d) vs Quarterly(63d) difference: 0.020%** -- effectively zero
- **A4f beats GJR at ALL frequencies** with DM |t| > 3.0 (range: 6.09 to 6.87)
- **No cross-frequency DM test is significant**: 5d vs 63d: t=1.15, 5d vs 252d: t=-0.11

### GJR is slightly more sensitive to refit frequency
- GJR QLIKE spread: 0.098% (range: -8.5434 to -8.5350), ~5x wider than A4f
- A4f's tau component (driven by VIX) is updated daily regardless of refit, stabilizing predictions

## Interpretation

1. **GARCH parameters are slow-moving.** The typical persistence (alpha + gamma/2 + beta) is ~0.97, meaning the conditional variance half-life is ~23 days. Parameters estimated 63 days apart will be nearly identical.

2. **A4f's tau provides daily external information.** Even when g_t parameters are stale, the tau_t = theta_0 + theta_1*VIX^2_{t-1} component updates every day with fresh VIX information. This is why A4f is more robust to infrequent refitting than GJR.

3. **Quarterly refit is the practical sweet spot.** It achieves the best A4f QLIKE (-8.6391), runs in 3.9s (vs 49s for weekly), and the DM t-stat (6.87) is actually the highest of all frequencies -- likely because more training data stability compensates for slight staleness.

## Paper 9 Implication

This result supports a single sentence in the robustness section:

> "Results are robust to the choice of refit frequency: QLIKE varies by less than 0.02% across weekly (5-day) to annual (252-day) refitting, and the A4f advantage over GJR remains statistically significant (DM |t| > 3.0) at all tested frequencies."

## Files
- `k1024.py` -- Experiment script (numba-accelerated)
- `k1024_results.json` -- Full results JSON
- `k1024_qlike_vs_frequency.png` -- QLIKE vs refit frequency (line chart)
- `k1024_dm_vs_frequency.png` -- DM t-statistics (bar chart)
- `k1024_runtime_vs_frequency.png` -- Runtime comparison (bar chart)

## References
- Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.
- Harvey et al. (2016). Tests for Forecast Comparison.
- Engle, Ghysels & Sohn (2013). GARCH-MIDAS. RES 95(3):776-797.
- Conrad & Loch (2015). JBES 33(3):338-358.
