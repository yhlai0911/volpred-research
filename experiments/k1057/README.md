# K1057: HAR-RV-J — Jump Component & Bipower Variation (60-Day 5-min SPY)

## Status: PRELIMINARY
OOS only ~30 days, well below 252-day minimum. Results indicative only.

## Motivation
K156 (46 days) provided descriptive RV decomposition finding that BPV (continuous) is the most predictable component (ACF=0.398) and jumps are rare (0/45 significant). K1054 (60 days) showed HAR-RV underperforms A4f-VIX^2 on r^2 proxy. This experiment tests whether **decomposing RV into continuous (BPV) + jump** improves HAR forecasting via the HAR-RV-J and HAR-C model variants.

## Research Questions
1. What is the SPY jump detection rate over 60 days? (BN-S z-test)
2. Does HAR-RV-J (adding jump term) outperform standard HAR-RV?
3. Does HAR-C (continuous BPV only) outperform HAR-RV? (denoising effect)
4. Can the best HAR variant match A4f-VIX^2?
5. What is the overnight return^2 vs intraday RV ratio?

## Data
- **5-min SPY**: 60 trading days (2026-01-14 to 2026-04-10), `data/intraday/SPY_5min_YYYY-MM-DD.csv`
- **Daily SPY/VIX**: yfinance, 2581 daily observations (2016-01 to 2026-04)
- **OOS**: 30 days (2026-02-27 to 2026-04-10), expanding window HAR (initial=30 days)
- **GARCH/A4f**: rolling w=2000 daily returns

## Method

### RV Decomposition
- **RV** = sum(r_5min^2) — standard realized variance
- **BPV** = (pi/2) * sum(|r_i| * |r_{i-1}|) — bipower variation (robust to jumps)
- **J** = max(RV - BPV, 0) — jump component
- **BN-S z-test**: Barndorff-Nielsen & Shephard (2006) test for significant jumps at 5% level

### Models Compared
| Model | Specification |
|-------|--------------|
| HAR-RV | RV_t = b0 + b_d*RV_{t-1} + b_w*RV_w + b_m*RV_m |
| HAR-C | RV_t = b0 + b_d*C_{t-1} + b_w*C_w + b_m*C_m (C=BPV) |
| HAR-RV-J | HAR-RV + gamma*J_{t-1} |
| HAR-CJ | HAR-C + gamma*J_{t-1} |
| HAR-CJ-ABD | HAR-C(ABD truncated) + gamma*J_ABD (Andersen-Bollerslev-Diebold 2007) |
| GJR-GARCH | GJR(1,1) normal, rolling w=2000 |
| A4f-VIX^2 | (VIX_{t-1}/100)^2/252 |

### Evaluation
- QLIKE on RV proxy (HAR native target)
- QLIKE on r^2 proxy (Patton 2011 cross-model fair comparison)
- Spearman rank correlation
- DM test (Harvey |t|>3.0)

## Key Results

### Jump Detection
- **8/60 significant jumps (13.3%)** — much higher than K156's 0/45 (longer sample caught more events)
- Jump fraction of total RV: **3.9%** (consistent with literature: jumps are rare but impactful)
- Jump ACF(1) = -0.056 (unpredictable, as expected)

### Model Rankings

**On RV proxy (HAR native):**
| Rank | Model | QLIKE |
|------|-------|-------|
| 1 | HAR-RV | -8.5973 |
| 2 | HAR-C | -8.5828 |
| 3 | HAR-RV-J | -8.5720 |
| 4 | HAR-CJ | -8.5458 |
| 5 | HAR-CJ-ABD | -8.5215 |
| 6 | GJR-GARCH | -8.5042 |
| 7 | A4f-VIX^2 | -8.0742 |

**On r^2 proxy (Patton 2011 fair):**
| Rank | Model | QLIKE |
|------|-------|-------|
| 1 | GJR-GARCH | -8.0697 |
| 2 | A4f-VIX^2 | -7.8948 |
| 3 | HAR-CJ-ABD | -7.7798 |
| 4 | HAR-RV | -7.7738 |
| 5 | HAR-RV-J | -7.7732 |
| 6 | HAR-C | -7.7617 |
| 7 | HAR-CJ | -7.7436 |

**Rankings are NOT consistent across proxies** — mechanical result per preamble: HAR naturally wins on RV, GARCH naturally wins on r^2.

### DM Tests (Harvey |t|>3.0 threshold)
- **HAR variants vs HAR-RV on RV proxy**: None significant (all |t| < 1.5). Adding jump term does NOT help.
- **HAR-RV vs A4f on RV proxy**: t=-5.97*** (HAR significantly better — but this is HAR's native target, mechanical advantage)
- **On r^2 proxy (fair)**: No significant differences between HAR variants and A4f (all |t| < 0.5)
- **A4f vs GJR-GARCH on RV proxy**: t=+12.4*** (GARCH much better than A4f on RV)

### Spearman Rank Correlations
- HAR variants: **negative rho(RV)** (-0.10 to -0.17) — HAR forecasts are inversely correlated with actual RV in this short sample!
- A4f-VIX^2: rho(RV)=0.313, rho(r^2)=0.303 — best directional accuracy
- GJR-GARCH: rho(RV)=0.072, rho(r^2)=0.023 — low in this period

### Overnight Analysis
- Mean overnight share: **32.7%** of total variance (lower than K156's 47.4%, which used a different calculation)
- Correlation(overnight_r^2, intraday_RV): **0.186** (low, suggesting different information content)

## Conclusions

1. **Adding jump components does NOT improve HAR forecasting** (Q2: negative). In this 30-day OOS, jump decomposition slightly *hurts* performance. This is consistent with literature: jumps are unpredictable (ACF=-0.056), so adding them as regressors just adds noise.

2. **HAR-C (BPV only) does NOT beat standard HAR-RV** (Q3: negative). The denoising benefit of BPV is offset by information loss. With only 30 OOS days, the differences are negligible.

3. **Standard HAR-RV remains the best HAR variant** on its native RV target. But all HAR variants have negative Spearman correlations in this sample — a serious concern.

4. **A4f-VIX^2 has the best directional accuracy** (rho=0.31) despite worse QLIKE on RV proxy. On the fair r^2 proxy, GJR-GARCH wins, followed by A4f. HAR variants rank lower — consistent with K1054 findings.

5. **Proxy-sensitivity confirmed**: Rankings flip entirely between RV and r^2 proxies. This is a mechanical result (models optimized for different targets), NOT an empirical finding.

## Limitations
- 30 OOS days is far below the 252-day minimum for reliable conclusions
- HAR expanding window starts from only 30 observations (very small for OLS with 4 regressors)
- BN-S jump test power is low with ~78 intraday observations per day
- No VaR/ES evaluation (requires longer OOS period)

## Files
- `k1057.py` — Complete experiment script
- `k1057_results.json` — Full results with all statistics
- `k1057_rv_decomposition.png` — RV vs BPV vs Jump time series with BN-S test
- `k1057_model_comparison.png` — QLIKE comparison bar charts (RV and r^2 proxies)
- `k1057_overnight_share.png` — Overnight variance share and scatter plot

## References
- Barndorff-Nielsen & Shephard (2006). Econometrics of testing for jumps. JFE.
- Corsi (2009). A simple approximate long-memory model of realized volatility. JFEC.
- Andersen, Bollerslev & Diebold (2007). Roughing it up. REStat.
- Patton (2011). Volatility forecast comparison using imperfect volatility proxies. JoE.
- Hansen & Lunde (2005). A forecast comparison of volatility models. JFEC.
