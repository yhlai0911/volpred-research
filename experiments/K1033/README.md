# K1033: A4f Refit Frequency Sensitivity (Paper 9 Robustness)

## Motivation
Paper 9 (GARCH-X with VIX) uses `refit_every=63` (quarterly) for all A4f experiments. Reviewers will ask: "Are results sensitive to refit frequency?" This experiment tests 5 refit frequencies to answer that question and provide a robustness table for the paper.

K783b previously tested window size sensitivity (conclusion: w=2000 is a reasonable default). This experiment complements that by testing the refit frequency dimension.

## Method
- **Assets**: SPY and QQQ (strongest A4f effects from K988/K994)
- **Models**: GJR-t(df=8) baseline vs A4f-VIX-t(df=8)
- **Refit frequencies**: 21 (monthly), 42 (bi-monthly), 63 (quarterly, baseline), 126 (semi-annual), 252 (annual)
- **Fixed**: DATA_START='2005-01-01', OOS_START='2019-01-01', WINDOW=2000, df=8, seed=42

## Evaluation
- QLIKE on r² (Patton 2011) for each refit frequency
- DM test (Harvey |t| > 3.0) for each refit frequency
- VaR 2.5% and 1% Kupiec test
- ES backtesting (Acerbi & Szekely 2014)
- Spearman rank correlation
- Coefficient of variation (CV) of QLIKE across refit frequencies
- Summary table: refit freq vs QLIKE and DM t-stat

## Data Source
- yfinance: SPY, QQQ, ^VIX (2005-01-01 to 2026-04-10)

## Files
- `k1033.py` — experiment script
- `k1033_results.json` — full results
- `k1033_qlike_vs_refit.png` — QLIKE vs refit frequency line chart
- `k1033_dm_vs_refit.png` — DM t-stat vs refit frequency bar chart
- `k1033_improvement_heatmap.png` — QLIKE improvement heatmap

## Related Experiments
- K988: A4f champion for SPY (DM t=+4.48 vs GJR, refit=63)
- K1003: A4f sensitivity analysis (13/16 PASS)
- K783b: Window size sensitivity (w=2000 reasonable default)
- K1030: European market A4f test (refit=63)
- K1032: Japan market A4f test (refit=63)

## Results

### Summary Table (Paper 9 ready)

| Asset | Refit | QLIKE GJR | QLIKE A4f | Improvement | DM t | Harvey |
|-------|-------|-----------|-----------|-------------|------|--------|
| SPY | 21 (M) | 1.4813 | 1.4095 | 4.84% | -3.476 | SIG *** |
| SPY | 42 (2M) | 1.4897 | 1.4091 | 5.41% | -3.460 | SIG *** |
| SPY | 63 (Q) | 1.5063 | 1.4114 | 6.30% | -2.592 | n.s. |
| SPY | 126 (6M) | 1.5075 | 1.4091 | 6.53% | -2.705 | n.s. |
| SPY | 252 (Y) | 1.5335 | 1.4069 | 8.26% | -2.759 | n.s. |
| QQQ | 21 (M) | 1.5030 | 1.4123 | 6.03% | -2.491 | n.s. |
| QQQ | 42 (2M) | 1.5004 | 1.4160 | 5.63% | -2.424 | n.s. |
| QQQ | 63 (Q) | 1.5033 | 1.4150 | 5.87% | -2.169 | n.s. |
| QQQ | 126 (6M) | 1.5065 | 1.4162 | 6.00% | -2.453 | n.s. |
| QQQ | 252 (Y) | 1.5017 | 1.4206 | 5.41% | -2.771 | n.s. |

### Robustness Analysis

**SPY:**
- A4f QLIKE CV = 0.001 (extremely stable across refit frequencies)
- GJR QLIKE CV = 0.012 (GJR varies more with refit frequency)
- DM t-stat range: [-3.476, -2.592], mean = -2.998
- Harvey significant: 2/5 (refit=21 and 42)
- QLIKE improvement: 4.84%-8.26% (mean 6.27%)
- VaR: GJR FAIL all 10 tests, A4f PASS all 10
- ES: Both PASS all 10

**QQQ:**
- A4f QLIKE CV = 0.002 (very stable)
- GJR QLIKE CV = 0.001
- DM t-stat range: [-2.771, -2.169], mean = -2.462
- Harvey significant: 0/5 (all conventional significance but not Harvey threshold)
- QLIKE improvement: 5.41%-6.03% (mean 5.79%, range only 0.62%)
- VaR: GJR FAIL all 10, A4f PASS 9/10
- ES: Both PASS all 10

### Key Findings

1. **A4f QLIKE is remarkably stable**: CV < 0.2% for both assets. The A4f model's forecast quality is essentially invariant to refit frequency. This is the strongest robustness finding.

2. **GJR is MORE sensitive to refit frequency**: For SPY, GJR QLIKE varies from 1.481 (refit=21) to 1.534 (refit=252), CV=1.2%. A4f absorbs this via the VIX-driven tau component.

3. **A4f consistently improves over GJR across ALL refit frequencies**: 4.8%-8.3% for SPY, 5.4%-6.0% for QQQ. No refit frequency reverses the ranking.

4. **DM significance depends on refit frequency**: For SPY, more frequent refitting (21, 42) achieves Harvey significance, while less frequent (63, 126, 252) is conventionally significant but not Harvey. For QQQ, all are conventional but not Harvey.

5. **VaR/ES backtesting strongly favors A4f regardless of refit**: A4f PASS rate 19/20 vs GJR 0/20 for VaR. Both pass ES.

6. **Less frequent refit paradoxically gives larger QLIKE improvement (SPY)**: Because GJR degrades more with stale parameters while A4f's VIX component stays current.

## Conclusion
**A4f-VIX is robust to refit frequency.** The model's QLIKE is essentially invariant (CV < 0.2%) across monthly to annual refitting, while GJR degrades with less frequent refit. For Paper 9, this means:
- The choice of refit_every=63 is NOT driving the results
- A4f's advantage is persistent across all refit regimes
- VaR performance is consistently better for A4f regardless of refit
- The VIX-driven tau component provides "between-refit stability" that plain GJR lacks

**Limitations**: DM significance varies with refit frequency, so the exact statistical inference is somewhat frequency-dependent. For QQQ, no refit frequency achieves Harvey |t|>3.0 (though all achieve conventional significance).
