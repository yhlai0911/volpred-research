# K1052: Asymmetric A4f — Does VIX Direction Matter?

**[提出: 賴奕豪, 執行: Claude]**

## Motivation

A4f (Paper 9 champion, K988 DM t=4.03 vs GJR) treats VIX symmetrically in the long-run component:

```
τ_t = θ₀ + θ₁ × VIX²_{t-1}
```

But VIX has known asymmetry: spikes (fear) are sharper than declines (calm). If VIX increases and decreases affect next-day volatility differently, an asymmetric extension could improve forecasts. This is a natural robustness check that reviewers might request for Paper 9.

Related question: GJR-GARCH's γ parameter already captures return asymmetry (negative returns → higher volatility). Does VIX-based asymmetry add information beyond return asymmetry?

## Models

| Model | Specification | Params |
|-------|--------------|--------|
| M1: A4f (baseline) | τ_t = θ₀ + θ₁ × VIX²_{t-1} | 6 |
| M2: A4f + ΔVIX⁺ | τ_t = θ₀ + θ₁ × VIX²_{t-1} + θ₂ × ΔVIX⁺_{t-1} | 7 |
| M3: A4f + High-VIX | τ_t = θ₀ + θ₁ × VIX²_{t-1} + θ₃ × VIX²_{t-1} × 1_{VIX > median} | 7 |
| M4: GJR-GARCH | Standard benchmark | 4 |

All A4f models use GJR short-run g_t with free ω_g, joint MLE.

## Data

- SPY: 2005-04-05 to 2026-04-10 (n=5,288)
- VIX: ^VIX from yfinance
- OOS: 2019-01-01 to 2026-04-10 (n=1,828)
- Window: 2000, refit every 63 days (30 refits)
- Seed: 42

## Results

### QLIKE (lower = better)

| Model | QLIKE | vs M1 | Spearman |
|-------|-------|-------|----------|
| M1: A4f | 1.4052 | baseline | 0.4191 |
| M2: +ΔVIX⁺ | 1.4165 | +0.80% (worse) | 0.4133 |
| **M3: +High-VIX** | **1.3995** | **-0.41%** | **0.4246** |
| M4: GJR | 1.4880 | +5.89% | 0.3704 |

### DM Tests (Harvey |t| > 3.0)

| Comparison | DM t | p-value | Significant? |
|-----------|------|---------|-------------|
| M2 vs M1 | +4.277 | <0.001 | M1 sig. better *** |
| M3 vs M1 | -0.713 | 0.476 | NS |
| M1 vs M4 (GJR) | -4.440 | <0.001 | M1 sig. better *** |
| M2 vs M4 (GJR) | -3.610 | <0.001 | M2 sig. better *** |
| M3 vs M4 (GJR) | -4.451 | <0.001 | M3 sig. better *** |

### Parameter Analysis

**M2 θ₂ (ΔVIX⁺ coefficient):** mean = -7.3e-5, t-test vs 0: t=-1.734, p=0.094. Not significantly different from zero. Negative sign suggests VIX increases may slightly *reduce* the τ component, which is counterintuitive and likely noise from overfitting.

**M3 θ₃ (high-VIX regime interaction):** mean = 1.3e-7, always positive (100% of refits), t-test vs 0: t=3.920, p<0.001. The parameter is consistently estimated as positive, meaning VIX sensitivity is slightly higher in high-VIX regimes. However, the magnitude is negligible relative to θ₁, and the OOS improvement is not statistically significant by DM test.

## Conclusion

**NULL RESULT**: Neither VIX direction (M2) nor VIX regime (M3) significantly improves over the symmetric A4f model at the Harvey (2016) |t| > 3.0 threshold.

Key findings:

1. **M2 (ΔVIX⁺) is significantly WORSE than M1** (DM t=+4.277): Adding VIX direction information introduces noise that degrades OOS forecasts. The extra parameter overfits.

2. **M3 (high-VIX interaction) is slightly better but NOT significant** (DM t=-0.713, p=0.476): The 0.41% QLIKE improvement does not pass statistical scrutiny.

3. **A4f continues to dominate GJR** (DM t=-4.440): Confirms K988 finding.

4. **All A4f variants beat GJR**: Even the worst A4f extension (M2) significantly beats GJR (DM t=-3.610), showing the VIX² component's value is robust.

## Implications for Paper 9

- **Symmetric VIX² in A4f is parsimonious and sufficient**. Reviewers asking about asymmetry can be addressed with this evidence.
- GJR's γ parameter already captures return-based asymmetry. VIX-based asymmetry in τ is redundant.
- The 6-parameter A4f is optimal; adding a 7th parameter for asymmetry is not justified.

## Prior Knowledge Connection

- **K988**: A4f champion (DM t=4.03 vs GJR) — confirmed here with updated data (DM t=-4.44)
- **K1015**: Dual-factor VIX9D+VIX3M NULL (θ₂=0) — consistent with this NULL result
- **K1048**: Threshold GARCH in-sample significant but OOS NULL — consistent with M3's pattern (parameter significant but OOS improvement NS)

## Files

- `K1052.py` — Experiment script
- `K1052_results.json` — Full results
- `K1052_asymmetric.png` — 4-panel comparison plot
- `README.md` — This file

## References

- Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.
- Harvey et al. (2016). Tests for forecast encompassing. JBES 34(4):574-587.
- Engle, Ghysels & Sohn (2013). Stock Market Volatility. RES 95(3):776-797.
- Conrad & Loch (2015). Anticipating Long-Term Stock Market Volatility. JBES 33(3):338-358.
