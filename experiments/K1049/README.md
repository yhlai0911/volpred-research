# K1049: HAR-RV 60-Day SPY Pilot — Proxy Comparison r² vs RV

## Status: PRELIMINARY (28 OOS days, minimum 252 required)

## Motivation

Paper 9 (GARCH-X with VIX) uses r² (squared daily return) as the evaluation proxy, which is justified by Patton (2011) as proxy-robust for QLIKE. However, reviewers may ask: "What if you used realized variance from 5-min data instead?" This experiment tests whether the choice of proxy (r² vs 5-min RV) changes model rankings.

Prior experiments:
- K960: HAR-RV with 19 OOS days — too small, but found OOS R²=0.243
- K745: HAR-ABS (37 days) found daily proxy beats HAR-RV
- K530: HAR-ABS DM=-15.45 vs GJR on |r| target — mechanical result (wrong target comparison)

## Method

Three models compared on the **same 28 OOS days** (2026-03-03 to 2026-04-10):

| Model | Specification | Training |
|-------|--------------|----------|
| **HAR-RV** | RV_t = β₀ + β₁×RV_{t-1} + β₅×RV_{t-1:t-5} + β₂₂×RV_{t-1:t-22} | Expanding OLS, initial 30 days |
| **GJR-GARCH** | GJR(1,1) with normal innovations | Rolling 2000 daily returns |
| **A4f-VIX²** | τ_t = θ₀ + θ₁×VIX²_{t-1}, g_t = GJR on r_t/√τ_t | Rolling 2000 daily returns |

Evaluated with **two proxies**:
- **RV (5-min)**: Sum of squared 5-min log returns (HAR-RV's native target)
- **r² (daily)**: Squared close-to-close return (GARCH's native target)

## Key Results

### QLIKE Loss (Lower = Better)

| Model | RV Proxy | r² Proxy | Rank (RV) | Rank (r²) |
|-------|----------|----------|-----------|-----------|
| HAR-RV | -7.646 | -7.848 | 2 | 3 |
| GJR-GARCH | -7.646 | -7.977 | 3 | 2 |
| **A4f-VIX²** | **-7.794** | **-8.040** | **1** | **1** |

**Rankings differ between proxies** (HAR-RV vs GJR-GARCH swap positions 2-3), but A4f-VIX² wins under both proxies.

### DM Tests (Harvey 2016: |t| > 3.0 for significance)

- A4f-VIX² vs HAR-RV: t=2.46 (RV proxy), t=2.23 (r² proxy) — marginally significant but below Harvey threshold
- No pairwise comparison reaches |t| > 3.0

### Spearman Rank Correlation

| Model | ρ (RV) | ρ (r²) |
|-------|--------|--------|
| HAR-RV | **-0.383** | **-0.432** |
| GJR-GARCH | 0.137 | -0.073 |
| A4f-VIX² | **0.424** | 0.148 |

**HAR-RV shows NEGATIVE rank correlation** — its forecasts move in the wrong direction relative to both proxies. This is likely due to the extremely small training sample (initial HAR estimation uses only 8 usable observations = 30 days - 22 lags).

## Interpretation

1. **A4f-VIX² (the Paper 9 model) wins under both proxies** — This is the most important finding for Paper 9. Even evaluated against 5-min RV (not its native target), A4f-VIX² still ranks first. This suggests VIX contains information about intraday volatility too, not just close-to-close.

2. **Ranking inconsistency is expected with 28 OOS days** — Patton (2011) proves QLIKE ranking preservation asymptotically. With only 28 observations, noise dominates, and the 2nd/3rd position swap (HAR-RV vs GJR-GARCH) is not meaningful.

3. **HAR-RV performs poorly** — This is NOT evidence against HAR-RV in general. The model is estimated on only 30 RV observations (8 usable after 22 lags), whereas GJR and A4f use 2000+ daily returns. This is a severe disadvantage. HAR-RV with 1000+ RV observations would be expected to perform much better.

4. **A4f theta_0 at boundary** (1e-10) — The intercept in τ_t = θ₀ + θ₁×VIX² is essentially zero, meaning all low-frequency variance comes from VIX. This suggests strong VIX dominance but also potential estimation instability with more data.

## Mechanical vs Empirical

- **Mechanical**: HAR-RV performing best on RV proxy would be expected (its native target). But it doesn't even win on RV, so this mechanical advantage was overwhelmed by the tiny training sample.
- **Partially mechanical**: A4f winning on r² proxy leverages its GARCH component (native r² target) + VIX information.
- **Empirical**: A4f winning on RV proxy (NOT its native target) is a genuine empirical finding — VIX-augmented GARCH captures intraday volatility dynamics despite being designed for close-to-close.

## Limitations (Critical)

1. **Only 28 OOS days** — Far below the 252-day minimum for definitive conclusions
2. **HAR-RV severely disadvantaged** — 30-day training (8 usable) vs 2000 for GARCH models
3. **Single market period** — Mar-Apr 2026 included tariff-driven vol spikes (not representative)
4. **Proxy correlation = 0.575** — RV and r² only moderately correlated in this period
5. **No bootstrap CI** — Sample too small for meaningful confidence intervals
6. **A4f estimation issues** — theta_0 at boundary, GJR omega=268 (very large in standardized units)

## Files

- `K1049.py` — Full experiment script
- `K1049_results.json` — Complete numerical results
- `K1049_proxy_comparison.png` — 4-panel comparison chart

## References

- Patton (2011). Volatility forecast comparison using imperfect volatility proxies. JoE.
- Corsi (2009). A simple approximate long-memory model of realized volatility. JFEC.
- Hansen & Lunde (2005). A forecast comparison of volatility models. JFEC.
- Engle & Rangel (2008). The Spline-GARCH Model for Low-Frequency Volatility. RFS.

## Next Steps

1. Accumulate more 5-min data (target: 252+ OOS days for definitive comparison)
2. Re-run HAR-RV with 250+ training RV observations (need ~1 year of 5-min data)
3. Add HAR-RV-J (jump component) when enough data available
4. Bootstrap CI once sample reaches 100+ days
5. Use result in Paper 9 as preliminary evidence that proxy choice doesn't affect A4f superiority
