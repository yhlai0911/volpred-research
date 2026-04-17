# K1199 — Expanding-window Adaptive VIX Quantile for OFI→Jump Logit

**Status**: **NULL** (4th complementary experiment fails to rescue K1128 regime-switching narrative)
**Date**: 2026-04-17
**Author**: Claude (worktree `agent-a5c40c3c`)
**Data**: TAIFEX TX 5-min bars 2017-2021 (K1124 parquet cache, 73,203 bars; 115 Lee-Mykland K=16 jumps)

## 1. Task-ID Mapping

`storage/next_tasks.json` references this task as **`K1133_expanding_window`**. However, K1133 was already consumed by the BTC GAS-t experiment. To avoid the K1032/K1114-class ID collision hazard, this experiment lives under `experiments/k1199/` while preserving the original task spec verbatim.

## 2. Motivation and Context

K1128/K1131/K1142 already returned three NULL/PARTIAL results along the "OFI→jump predictability depends on VIX regime" research line:

| K | Approach | Result |
|---|---|---|
| K1128 | IS-fixed VIX tertile (IS 33%/67% = 12.07/14.99) | **Degenerate OOS coverage**: low=0 / mid=854 / high=20,060 |
| K1131 | Continuous VIX-dependent β via natural cubic spline | **NULL**: OOS DM t=−3.94, AUC=0.4965 (below chance); IS LRT p=0.235 |
| K1142 | Vol-normalized OFI (|OFI|/σ̂) bypassing VIX | **PARTIAL**: DM ~0 vs base; decent AUC=0.67 but not distinct from base |

`docs/error_log.md` 2026-04-13 lesson #4 proposed **three fixes** for the IS-fixed cutoff degeneracy:
  1. ~~Extend IS to include prior crises (2008/2011/2015)~~ → **K1130 INVALIDATED** (extended IS max VIX=40.7 still disjoint from COVID VIX=83)
  2. **Expanding-window adaptive quantile** ← **this experiment**
  3. ~~Continuous VIX-dependent β via spline~~ → **K1131 INVALIDATED**

K1199 is the 4th complementary attempt (and 2nd attempt at fix #2 specifically). Under the project rule "≥ 3 complementary experiments before narrative pivot", a NULL here enables main-thread to make a formal pivot decision on the K1128 regime-switching story.

## 3. Method

### 3.1 Expanding-window adaptive tertile

For each bar t on date D:
  - `vix_lag1(t) = VIX(D-1)` (previous US close; TAIFEX opens next morning)
  - **Quantile window**: VIX daily history **strictly before** the index of `VIX(D-1)`, i.e. `vix[0 : idx_of(D-1)]`. This ensures `VIX(D-1)` itself does NOT enter its own quantile computation (preventing any mild lookahead).
  - `q33_t = np.quantile(window, 1/3)`, `q67_t = np.quantile(window, 2/3)`
  - Tertile label: 0 (low) if `VIX(D-1) < q33_t`, 1 (mid) if `VIX(D-1) < q67_t`, 2 (high) else
  - Burn-in: require ≥ 30 VIX obs in window before assigning tertile (defaults to mid for first 30 days of history).

### 3.2 Refit cadence

MLE refit every **252 trading days (≈ 1 year)** on IS + all prior OOS bars. This balances:
  - Computational cost (82 refits over OOS period instead of per-bar)
  - Information absorption (β estimates see each new regime once per year)
  - The expanding **quantile** still updates per bar, so tertile labels propagate daily info even within a refit window.

### 3.3 Model specs

| Model | Formula | Features |
|---|---|---|
| `M_base` | `logit P = α + β1·jump_curr + β2·|OFI| + β3·OFI` | 4 params |
| `M_tertile` (K1128) | `base + β_mid·mid_IS·|OFI| + β_high·high_IS·|OFI| + γ_mid·mid_IS·OFI + γ_high·high_IS·OFI` (IS-fixed cutoffs) | 8 params |
| `M_volnorm` (K1142) | `α + β1·jump_curr + β2·|OFI|/σ̂ + β3·OFI/σ̂` (σ̂ from rolling 60-bar) | 4 params |
| `M_expanding` (K1199) | same structure as `M_tertile` but tertile labels use **expanding quantile** | 8 params, 82 refits |

### 3.4 Lag discipline (strict)

- VIX is daily; cutoff uses data BEFORE the published `VIX(D-1)` observation.
- OFI/returns from K1124 cache (DAY_END=13:44:59, T-1 rolling active contract).
- Lee-Mykland BV uses strictly past K=16 returns (K1125/K1128 Codex-fix inherited).
- `jump_{t+1}` target within same day only.
- `seed=42`; L-BFGS-B with L2 ridge `1e-4` (no intercept penalty).

## 4. Results

### 4.1 Sample split

| | IS (2017-2019) | OOS (2020-2021) |
|---|---|---|
| N bars | 31,498 | 20,914 |
| Jumps | 81 | 33 |
| VIX range | 9.14 — 37.32 | 12.32 — 82.69 |

### 4.2 **OOS tertile coverage: the core finding**

| Tertile | K1128 IS-fixed (cutoffs 12.07/14.99) | K1199 expanding-window |
|---|---|---|
| low  | **0** | **0** |
| mid  | 854 | 6,816 |
| high | 20,060 | 14,098 |

**Critical result**: the expanding-window adaptive quantile **does not rescue the low tertile** — still 0 bars. COVID OOS begins 2020-01-02 with quantile window = full IS (max VIX=37), and COVID vol spike in Feb/Mar 2020 immediately pushes observations above the then-current q67 (~14). The expanding window **lags the regime shift** by construction: it cannot recognize a "low VIX" day in 2021 as below-history when the history already includes the COVID spike that permanently lifted the quantile.

The mid/high split *is* more balanced (6,816 / 14,098 vs K1128's 854 / 20,060), so in that limited sense H1 "coverage balanced" is partially satisfied. But the structural failure of the "low" regime persists: the regime-switching framing requires three populated regimes, and **no IS-based cutoff strategy — fixed, extended, or expanding — can generate a "low VIX" OOS sample when the OOS period is structurally higher-vol than the IS period it seeded from.**

### 4.3 IS LRT

| Contrast | χ² | df | p-value |
|---|---|---|---|
| expanding vs base | 4.79 | 4 | 0.309 |
| tertile   vs base | 4.39 | 4 | 0.356 |

Neither specification reaches significance in-sample. The expanding-window design contributes marginally over IS-fixed (Δχ² = 0.40), but both are dominated by noise at df=4.

### 4.4 OOS performance (4-spec comparison)

| Model | log-loss | AUC | Brier |
|---|---|---|---|
| `M_base` | 0.011708 | 0.5543 | 0.001569 |
| `M_tertile` (K1128) | 0.011721 | 0.5559 | 0.001570 |
| `M_volnorm` (K1142) | 0.011738 | **0.6712** | 0.001571 |
| `M_expanding` (K1199) | **0.011646** | 0.5484 | 0.001568 |

Expanding wins the log-loss (lowest) but *loses* the AUC to both the simple IS-fixed tertile (K1128) and vol-normalized OFI (K1142). K1142 retains the highest AUC by a wide margin (0.67 vs 0.55), suggesting **the discriminating signal lives in vol-normalization, not in VIX regime**.

### 4.5 DM-HLN pairwise (positive t ⇒ 2nd model beats 1st)

| Contrast | t | mean_d |
|---|---|---|
| exp vs base | **+1.143** | +6.18e-05 |
| exp vs tertile | **+1.435** | +7.49e-05 |
| exp vs volnorm | +0.812 | +9.26e-05 |
| tertile vs base | −0.416 | −1.32e-05 |
| volnorm vs base | −0.267 | −3.08e-05 |

All |t| < 2. No pairwise comparison achieves even weak Harvey |t|>2, let alone the top-journal |t|>3 threshold.

### 4.6 Regime-β spread (H3 PASS — cosmetic)

Effective β on `|OFI|` at final refit (K1199):
  - low: +2.223 (small sample; IS-only)
  - mid: +1.653
  - high: **+0.417**

β on signed OFI:
  - low: +0.104
  - mid: −1.918
  - high: −1.376

H3 ("regime β spread > 0.05") passes numerically, but this is cosmetic: the OOS low-regime has 0 bars, so the low-regime β is effectively identified from IS only (where low has 6,601 bars). The *OOS-relevant* spread (mid vs high) is β_mid−β_high = +1.24 on |OFI|, which economically looks meaningful but DM rejects the predictive gain.

### 4.7 Verdict table

| Hypothesis | Criterion | Result | Status |
|---|---|---|---|
| H1 coverage balanced | low/mid/high each ≥ 1000 | 0 / 6816 / 14098 | **FAIL** |
| H2 DM vs base | \|t\|>3, positive | +1.143 | **FAIL** |
| H3 regime β spread | max spread > 0.05 | 1.81 | PASS (cosmetic) |
| H4 beats K1128 tertile | AUC ↑ and DM t>0 | 0.5484 < 0.5559 | **FAIL** |

**VERDICT: NULL** (H1, H2, H4 all FAIL; H3 cosmetic).

## 5. Interpretation and Paper 3 / K1128 Narrative Implication

K1199 is the **4th complementary attempt** at salvaging the K1128 "OFI→jump depends on VIX regime" framing (K1128 IS-fixed, K1131 spline, K1142 vol-norm, K1199 expanding). All four have returned NULL or cosmetic-only results:

| K | Fix strategy | Key metric | Outcome |
|---|---|---|---|
| K1128 | IS-fixed tertile | DM=−0.42 vs base | NULL + degenerate coverage |
| K1131 | Spline continuous β | DM=−3.94, AUC=0.497 | **INVALIDATED** (harmful) |
| K1142 | Vol-normalized OFI | DM=−0.27, AUC=0.67 | PARTIAL (signal without regime) |
| K1199 | Expanding quantile | DM=+1.14, AUC=0.548 | **NULL** |

### Pivot decision (for main thread)

The narrative **"OFI→jump predictability is regime-dependent on VIX"** is not empirically defensible in TAIFEX 2017-2021 data. No cutoff scheme — fixed, extended, spline, or expanding — produces a statistically significant regime-dependent β with OOS DM |t|>2 in a positive direction.

**Recommended pivot (main-thread decision)**:
1. **Drop K1128 regime-switching framing** in Paper 3.
2. **Reframe as pooled continuous microstructure signal**:
   - The K1142 vol-normalized spec has AUC=0.67 OOS, distinctively above all other variants
   - The high-tertile K1128 within-regime M3 DM=+3.49 (documented in error_log) suggests OFI magnitude matters, but **without regime qualifier**
   - Unified story: "|OFI|/σ̂ is a regime-free microstructure jump predictor on TAIFEX"
3. **K1128 story retained only as null result** — document that "regime-dependent" framing was tested 4 ways and rejected. This is valuable negative evidence per research-honesty principle #9 (report nulls).
4. **Structural reason**: Taiwan IS 2017-2019 VIX range (9-37) is disjoint from COVID OOS (12-83). Any IS-seeded cutoff is doomed because IS contains no COVID-magnitude regime. Expanding window cannot "un-learn" COVID values once seen, so OOS late-period "low" tertile identification is structurally impossible.
5. **Update `research_program.md`** Paper 3 narrative decision to `decision_made_awaiting_body_rewrite` after main-thread confirms.

## 6. Files

- `k1199.py` — experiment script (single-file, self-contained)
- `k1199_results.json` — full results including per-refit nll, pairwise DM, LRT, verdicts
- `k1199_coverage_auc.png` — OOS tertile coverage bars + AUC comparison
- `k1199_roc.png` — OOS ROC curves for 4 specs
- `k1199_quantile_trajectory.png` — expanding q33/q67 trajectory vs K1128 IS-fixed over OOS

## 7. References

- Lee, S. S., & Mykland, P. A. (2008). Jumps in financial markets: a new nonparametric test and jump dynamics. *RFS* 21(6), 2535-2563.
- Cont, R., Kukanov, A., & Stoikov, S. (2014). The price impact of order book events. *JFE* 12(1), 47-88.
- Harvey, D., Leybourne, S., & Newbold, P. (1997). Testing the equality of prediction mean squared errors. *IJF* 13(2), 281-291.
- Harvey, C. R., Liu, Y., & Zhu, H. (2016). … and the cross-section of expected returns. *RFS* 29(1), 5-68. [Multiple-testing t-stat thresholds |t|>3]
- Ang, A., & Timmermann, A. (2012). Regime changes and financial markets. *Annu. Rev. Financ. Econ.* 4, 313-337.
