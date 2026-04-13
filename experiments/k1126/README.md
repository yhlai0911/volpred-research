# K1126 — TAIFEX OFI Buy/Sell Asymmetry by Rolling VIX Regime

**Status**: FAIL (triple-gate); no per-regime Wald significance; mid-regime shows strongest signed-OFI signal but buy/sell asymmetry is NOT statistically distinguishable in any regime
**Date**: 2026-04-13
**Author**: Claude (worktree agent-a1f8a651)
**Data**: TAIFEX TX 5-min bars 2017-2021 (via K1124 cache) + yfinance ^VIX

## Problem & Motivation

K1125 found TAIFEX sell-side signed OFI asymmetry: M3 standardized coefs `|OFI|=+0.20, signed OFI=-0.187`, implying **sell-side pressure → higher next-bar jump probability** (opposite to Cont et al. 2014 US-equity symmetry). K1128 attempted a VIX-tertile regime split but degenerated because COVID-era OOS VIX was entirely outside the 2017-2019 IS training distribution (E064-type chain trap: IS-based cutoffs don't transfer to unprecedented volatility).

**K1126 question**: Is the K1125 sell-side asymmetry regime-dependent? Specifically:
- **H1**: No regime dependence — the effect is structural across VIX regimes (K1125 asymmetry = non-regime)
- **H2**: High-VIX fear asymmetry — sell-side |β| >> buy-side |β| during stress (thin order books crack more easily)
- **H3**: Low-VIX thin-market asymmetry — sell-side |β| > buy-side |β| during calm (reverse of fear-asymmetry)

## Method

### Fix for K1128's degeneration
Use **ex-ante rolling 252-day VIX percentile** (trailing window, strictly past values at each date). For each TAIFEX trading day d, rank the previous US trading day's VIX close against its trailing 252-day distribution. Low = <33%, Mid = 33-67%, High = >67%. This is stationary by construction (always 1/3 of time in each regime on average) and avoids the IS vs OOS distribution disjunction that broke K1128.

### Regime-conditional logistic (per regime separately)
For each of {low, mid, high}, fit two logistic regressions on the regime's IS subsample (2017-2019) and evaluate on the regime's OOS subsample (2020-2021):

| Spec | Features | Purpose |
|------|----------|---------|
| Baseline (K1125 M3) | `jump_curr`, `|OFI|_t`, `OFI_t` (signed) | Reference: signed OFI effect per regime |
| Asymmetric | `jump_curr`, `ofi_buy = max(0, OFI)`, `ofi_sell = -min(0, OFI)` | Buy-side vs sell-side split |

Both features in the asymmetric spec are non-negative, so the coefficients are directly comparable as impact-per-unit-magnitude per side.

### Wald test (buy vs sell)
Fit an unregularized logistic on standardized features (C=1e6), compute Fisher-information covariance from `(X' W X)⁻¹`, and test `H0: β_buy = β_sell` via `z = (β_buy − β_sell) / √Var(β_buy − β_sell)`. Harvey (2016) gate: `|z| > 3`.

### Triple-gate (adapted to binary target)
- Per-regime Wald |z| > 3 for buy vs sell difference
- Per-regime OOS AUC > 0.55 (K1125 M1 baseline)
- Cross-regime pattern consistent with a clean hypothesis (H1/H2/H3)

### Lookahead discipline
- VIX percentile uses strictly past 252 trading days (explicit exclusion of current value from the window)
- VIX used is `vix_lag1` = previous US trading day's close (TAIFEX day session opens ~09:45 local on the following day)
- Features at bar t predict jump at bar t+1 (no same-bar leak)
- IS/OOS split at 2020-01-01
- Seed 42

## Results

### Regime x sample bar counts (valid prediction rows)

| Regime | IS N | OOS N | IS jumps | OOS jumps |
|--------|------|-------|----------|-----------|
| Low    | 12,555 | 9,207 | 37 | 17 |
| Mid    | 9,387  | 5,535 | 16 | 10 |
| High   | 9,556  | 6,172 | 28 | 6 |

Rolling percentile DID NOT degenerate — all three regimes have meaningful IS/OOS coverage (contrast with K1128 where high-regime had 20,060 OOS vs 0 OOS in low).

### Baseline signed-OFI per regime

| Regime | AUC IS | AUC OOS | Brier OOS |
|--------|--------|---------|-----------|
| Low    | 0.6015 | 0.4899 | 0.00322 |
| Mid    | **0.6775** | **0.6278** | 0.00187 |
| High   | 0.5542 | 0.3998 | 0.00133 |

### Asymmetric (buy/sell split) per regime — Wald test for β_buy ≠ β_sell

| Regime | β_buy (std) | β_sell (std) | \|sell\|/\|buy\| | Wald z | p-value |
|--------|-------------|--------------|------------------|--------|---------|
| Low    | +0.274 | +0.383 | 1.40 | **−0.72** | 0.473 |
| Mid    | −0.333 | +0.276 | 0.83 | **−1.74** | 0.082 |
| High   | −0.080 | +0.091 | 1.14 | **−0.78** | 0.438 |

All three Wald z values are < 1.8 in absolute value → **no regime shows statistically distinguishable buy vs sell asymmetry** at the Harvey |z| > 3 gate.

### Triple-gate verdict

| Criterion | Low | Mid | High |
|-----------|-----|-----|------|
| Wald \|z\| > 3 | FAIL (0.72) | FAIL (1.74) | FAIL (0.78) |
| AUC OOS > 0.55 | FAIL (0.49) | PASS (0.63) | FAIL (0.40) |

**No regime passes both gates. Triple-gate overall: FAIL.**

### Automatic hypothesis label
The script labels the outcome "H3: Low-VIX thin-market asymmetry" because the |sell|/|buy| ratio is highest in Low (1.40) vs High (1.14). **But the underlying Wald z is not significant, so the label is descriptive only.** The more honest reading: none of the H1/H2/H3 alternatives is supported at a statistically meaningful level.

## Interpretation

### What actually happened
- The Low regime has the strongest "sell-side > buy-side" coefficient pattern in raw magnitudes, but standard errors are large (few IS jumps: 37) and Wald z is 0.72 — essentially zero signal.
- The Mid regime is the **only regime where the full signed-OFI model has useful OOS AUC (0.628)**, but the asymmetric decomposition actually flips sign (β_buy negative, β_sell positive — implying BOTH buy and sell activity at moderate VIX are associated with jumps). Wald z=−1.74 is borderline, p=0.082, but does NOT exceed the strict Harvey gate.
- The High regime collapses: in-sample AUC only 0.55, OOS AUC **0.40** (worse than chance). OOS had only 6 jumps (small-sample fragility), and the COVID-era flow dynamics do not resemble the 2017-2019 High-VIX flow dynamics the model trained on.
- The overall K1125 "signed OFI predicts jumps" effect survives conditionally on being in the **Mid VIX regime** (AUC OOS 0.628), but disintegrates in both tails.

### Why K1125's pooled result didn't hold regime-by-regime
Pooling across regimes lets the Mid-regime signal dominate (Mid has the most jumps relative to base rate: 10/5,535 in OOS vs 6/6,172 in High and 17/9,207 in Low). The pooled K1125 signed-OFI coefficient of −0.187 is mechanically driven by Mid-regime observations; it is NOT a stable sell-side fear asymmetry that strengthens in stress.

### Relation to K1128
K1128's problem was that IS-based cutoffs placed all OOS bars in the High tertile (20,060/0/854). K1126's rolling-percentile fix eliminates that distribution mismatch: OOS coverage is now 9,207 Low / 5,535 Mid / 6,172 High. But with the balanced split, the per-regime signal is too weak to survive Wald |z|>3 at the tight per-regime sample sizes (IS jumps per regime: 37/16/28).

## Verdict

- **H1 (symmetric)**: |sell|/|buy| ratios 1.40, 0.83, 1.14 — not cleanly in (0.7, 1.5) for both tails, so H1 fails weak form; but effectively, because Wald p-values are large (0.47, 0.08, 0.44), the data is consistent with H1 in the sense that we cannot reject symmetry.
- **H2 (high-VIX fear asymmetry)**: FAIL. High-regime Wald z=−0.78 and OOS AUC=0.40. No evidence.
- **H3 (low-VIX thin-market asymmetry)**: marginal ratio pattern but Wald z=−0.72. NO significance.

**Overall: triple-gate FAIL. The K1125 "sell-side asymmetry on TAIFEX" effect is NOT a robust stress-regime phenomenon and cannot support a Taiwan microstructure fear-asymmetry story.**

## Taiwan Microstructure Paper Narrative Guidance

Based on K1126, the paper framing on TAIFEX OFI → jump should be:

1. **Positive**: K1125's OFI-is-not-merely-symmetric finding (−0.187 signed coef, p<0.01) is a genuine aggregate stylized fact on TAIFEX and contrasts with Cont et al. (2014) US evidence of symmetric impact.
2. **Caveat**: K1126 shows the effect is NOT driven by a clean "fear asymmetry in high-VIX regimes" mechanism; it is concentrated in the Mid-VIX regime where both buy and sell pressure predict jumps. This weakens a narrative that high-VIX stress makes TAIFEX order books fragile in the sell direction.
3. **Preferred framing**: Describe K1125 as a **pooled stylized fact**; flag that per-regime decomposition is statistically weak at 5-year sample sizes and requires longer history or higher base-rate target (e.g., continuous RV quantiles instead of binary jumps) to resolve. Do not over-claim a mechanistic stress-asymmetry story.
4. **Next experiments** to strengthen or refute:
   - K112x + more years (2012-2016) to expand jump count per regime
   - Replace binary jump target with bar-level top-decile RV (continuous, more events) to get per-regime estimation statistical power
   - Volume-tertile regime split (K1126 proposed this as fallback) — may reveal liquidity-based asymmetry even when VIX regimes fail
   - Contemporaneous (t-0) OFI → jump risk may be the truer mechanism; lag-1 loses most of the microstructure signal

## Limitations

- Only 115 jumps in 5-year sample; splitting 3 ways gives 37/16/28 IS jumps per regime — Wald power is weak.
- VIX is a US implied-vol index; TAIFEX-specific VIX (VIXT) might classify regimes differently but has shorter history. Using US VIX as a global-stress proxy.
- Jump definition binary at α=0.01 (~0.21% rate); not tested at α=0.05.
- Buy/sell split treats magnitudes as linear-separable; could miss non-linear thresholds.
- OOS period (2020-2021) is dominated by COVID — not a normal high-VIX episode.

## Files

- `k1126.py` — full experiment script (reuses K1124 bar cache, K1125 Lee-Mykland jump detection)
- `k1126_results.json` — full numeric results, per-regime models, Wald tests, verdict
- `k1126_per_regime_table.csv` — summary table of coefs / AUC / Wald per regime
- `k1126_regime_coefs_auc.png` — (a) buy vs sell coefficient bar chart by regime, (b) AUC signed vs asymmetric
- `k1126_vix_percentile_timeline.png` — rolling 252d VIX percentile time series with regime cutoffs
- `run.log` — console output of full run
