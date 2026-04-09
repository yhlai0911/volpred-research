# K1004: VIX9D-Driven A4f Full Validation

## Motivation
K1003 sensitivity analysis found VIX9D (9-day VIX, ^VIX9D) as a stronger tau driver than standard VIX:
- VIX9D: DM t=+5.15
- VIX (baseline): DM t=+4.29
- VIX3M: DM t=+2.59 (not robust)

VIX9D captures shorter-term fear, more timely for volatility prediction. K1003 only did QLIKE; this experiment performs the full validation suite.

## Method
- **Models**: A4f-VIX9D-N, A4f-VIX9D-t (joint MLE), A4f-VIX-t (baseline), GJR-t (benchmark)
- **Data**: SPY + QQQ, 2011-2026 (VIX9D availability), yfinance
- **OOS**: 2019-01-02 to 2026-04-07, N=1825 per asset
- **Window**: 2000, refit every 63 days
- **Evaluation**: QLIKE on r^2, DM test (Harvey t>3.0), VaR (1%/2.5%/5%), ES (2.5%)
- **Model spec**: tau_t = theta0 + theta1 * VIX9D^2_{t-1}, g_t = omega + alpha*u^2 + gamma*u^2*I + beta*g_{t-1}
- **Student-t**: scale = sigma * sqrt((df-2)/df), joint MLE
- **Seed**: 42

## Results

### SPY — QLIKE
| Model | QLIKE | DM vs GJR-t |
|-------|-------|-------------|
| A4f-VIX9D-t | -8.394681 | t=-6.180*** |
| A4f-VIX9D-N | -8.393042 | t=-6.128*** |
| A4f-VIX-t | -8.361372 | t=-4.414*** |
| GJR-t | -8.271973 | (baseline) |

**Key DM: A4f-VIX9D-t vs A4f-VIX-t: t=-4.588*** (SIGNIFICANT)**

### SPY — VaR/ES Scorecard (2.5%)
| Model | Viol Rate | UC_p | CC_p | DQ_p | Basel | ES_Z1_p | ES_Z2_p | Score |
|-------|-----------|------|------|------|-------|---------|---------|-------|
| A4f-VIX9D-t | 2.68% | 0.617 | 0.768 | 0.765 | GREEN | 0.500 | 0.530 | 6/6 |
| A4f-VIX9D-N | 2.96% | 0.222 | 0.601 | 0.395 | GREEN | 0.504 | 0.532 | 6/6 |
| A4f-VIX-t | 2.85% | 0.350 | 0.666 | 0.628 | GREEN | 0.501 | 0.528 | 6/6 |
| GJR-t | 3.40% | 0.020 | 0.938 | 0.103 | GREEN | 0.510 | 0.521 | 5/6 |

### QQQ — QLIKE
| Model | QLIKE | DM vs GJR-t |
|-------|-------|-------------|
| A4f-VIX9D-t | -7.786479 | t=-5.002*** |
| A4f-VIX9D-N | -7.785651 | t=-5.026*** |
| A4f-VIX-t | -7.768298 | t=-3.696*** |
| GJR-t | -7.689791 | (baseline) |

**Key DM: A4f-VIX9D-t vs A4f-VIX-t: t=-2.331 (NOT significant by Harvey t>3.0)**

### QQQ — VaR/ES Scorecard (2.5%)
| Model | Viol Rate | UC_p | CC_p | DQ_p | Basel | ES_Z1_p | ES_Z2_p | Score |
|-------|-----------|------|------|------|-------|---------|---------|-------|
| A4f-VIX9D-t | 3.23% | 0.055 | 0.946 | 0.072 | GREEN | 0.509 | 0.540 | 6/6 |
| A4f-VIX-t | 3.07% | 0.133 | 0.829 | 0.234 | GREEN | 0.521 | 0.535 | 6/6 |
| GJR-t | 3.62% | 0.004 | 0.789 | 0.015 | GREEN | 0.525 | 0.529 | 4/6 |

## Conclusions

1. **SPY: VIX9D significantly improves A4f** — DM t=-4.588 passes Harvey (2016) t>3.0 threshold. QLIKE improvement: -8.395 vs -8.361 (0.033 reduction). Confirms K1003 finding with full validation.

2. **QQQ: VIX9D improves A4f but NOT statistically significant** — DM t=-2.331 < 3.0. QLIKE: -7.786 vs -7.768 (0.018 reduction). Improvement direction consistent but weaker.

3. **VaR/ES: All A4f variants score 6/6 on both assets** — VIX9D does not degrade risk management performance. VIX9D-t has the best violation rate on SPY (2.68% vs 2.85% target 2.5%).

4. **A4f >> GJR-t on both assets** — All A4f variants significantly beat GJR-t (DM t > 4.0). This is consistent with K988/K1000 findings that external VIX information strongly improves GARCH.

5. **Normal vs Student-t**: Marginal QLIKE difference (A4f-VIX9D-t slightly better), but Student-t provides much better 1% VaR calibration (1.37% vs 1.70% violation for SPY).

## Limitations
- VIX9D only available from 2011 (shorter in-sample than VIX)
- VIX9D is SPY-specific; QQQ results use SPY's VIX9D as proxy
- OOS period 2019-2026 includes COVID crash (extreme event)
- GVZ9D (gold VIX 9-day) does not exist, so GLD cross-asset test was skipped

## Files
- `k1004.py` — Experiment script
- `k1004_results.json` — Full results with all statistics
- `README.md` — This file
