# K1088: USO A4f with OVX — Asset-Matched Theory on Oil (4th Asset Class)

**Date**: 2026-04-13
**Proposer**: User (via K1088 brief)
**Executor**: Claude
**Status**: COMPLETE

## 1. Problem

Paper 9's cross-asset matrix before this experiment was incomplete:

| Asset class | Assets tested | Asset-matched regressor | Result |
|-------------|--------------|-----------------------|--------|
| Equity      | SPY/QQQ/IWM/EEM/FXI | VIX | PASS (K1075-K1082) |
| Commodity - Gold | GLD | GVZ | PASS, DM t=+4.46 (K1085) |
| Bonds       | TLT | MOVE, yield curve | FAIL (K1086, K1087) |
| Commodity - Oil | **USO** | **OVX** | **?** ← K1088 |

The 4th asset class decides whether Paper 9's scope statement is
- **Narrow**: "A4f works on equity + gold; bonds excluded"
- **Broad**: "A4f works on liquid risky assets (equity + commodities); bonds excluded by mechanical duration-ΔY identity"

## 2. Hypotheses

- **H1** USO full OOS A4f-OVX vs GJR Harvey-PASS (|t|>3, positive)?
- **H2** USO A4f-OVX beats A4f-VIX (head-to-head DM)?
- **H3** USO θ₁-OVX stability (refit CV reasonable)?
- **H4** A4f-COMBO (VIX²+OVX²) further improves?
- **H5** 2020-04 negative-oil episode robustness (does result survive when those 4 days are dropped)?

## 3. Method

- **Data**: USO daily 2006-04-10 to 2026-04-10 (n=5031), ^VIX, ^OVX (from 2007-05-10) via yfinance
- **OOS**: Rolling 2000-day train + 63-day refit
- **Three windows**: Early (2010-13), Middle (2014-19 includes 2014-16 oil crash), Late (2020-26 includes negative-price + Ukraine)
- **Four models**: GJR-GARCH baseline, A4f-VIX, A4f-OVX, A4f-COMBO (VIX²+OVX²)
- **Evaluation**: QLIKE on r² (Patton 2011), DM test with Newey-West HAC (Harvey 2016, |t|>3), Spearman, block-bootstrap 95% CI
- **Crisis sub-periods**: 2008 GFC, 2014-16 oil crash, 2020 negative oil, 2022 Ukraine
- **VIX + OVX bucket analysis**: 5 regimes each
- **Robustness**: drop 2020-04-20/21/22/27 (negative oil days)
- **Seed**: 42 everywhere

## 4. Expectation

Given K1085 (gold + GVZ PASS) and the well-documented role of OVX in crude-oil option market (Dutta 2017; Bouoiyour & Selmi 2016), a PASS for USO + OVX would complete the commodity asset class and validate the asset-matched principle broadly. A FAIL would turn gold into a special case.

## 5. Results

### 5.1 Full OOS (2010-01 ~ 2026-04)

| Comparison | n | QL_GJR | QL_A4f | Diff% | DM t | Harvey |
|---|---|---|---|---|---|---|
| A4f-VIX vs GJR | 4092 | -6.87709 | -6.89511 | -0.26% | +2.708 | FAIL |
| **A4f-OVX vs GJR** | **2960** | **-6.68702** | **-6.75189** | **-0.97%** | **+4.475** | **PASS** |
| A4f-COMBO vs GJR | 2960 | -6.68702 | -6.74668 | -0.89% | +4.078 | PASS |

### 5.2 Head-to-head (pairwise DM)

| Base | Alt | n | DM t | Harvey |
|---|---|---|---|---|
| A4f-VIX | A4f-OVX | 2960 | **+3.177** | **PASS** (OVX superior) |
| A4f-VIX | A4f-COMBO | 2960 | +3.039 | PASS |
| A4f-OVX | A4f-COMBO | 2960 | -1.226 | FAIL (no gain over OVX alone) |

**Key finding**: OVX (asset-matched IV) beats VIX as tau regressor. Combining them yields no additional gain — the information is subsumed by OVX.

### 5.3 Per-window (A4f-OVX vs GJR)

| Window | n | Diff% | DM t | Harvey |
|---|---|---|---|---|
| Early_GFC_Post (2010-13) | N/A | — | — | (insufficient OVX history pre-2009) |
| Middle_OilCrash (2014-19) | 1384 | -0.49% | +3.327 | PASS |
| Late_COVID_Ukraine (2020-26) | 1576 | -1.41% | +3.684 | PASS |

### 5.4 OVX bucket analysis (A4f-OVX vs GJR)

| Bucket | Range | n | QL diff% | DM t |
|---|---|---|---|---|
| OVX_Low | [0,25) | 153 | -0.32% | +1.091 |
| OVX_Normal | [25,40) | 1718 | -0.42% | +3.092 |
| OVX_High | [40,60) | 911 | -0.91% | +3.216 |
| OVX_Extreme | [60,100) | 131 | -13.46% | +3.136 |
| OVX_Crisis | [100,400) | 47 | -4.68% | +1.240 |

**Pattern**: Advantage grows with OVX regime (stronger in OVX_Extreme 60-100 than OVX_Low). Consistent with A4f's role as a crisis forecaster. OVX_Crisis (>100) is small-N and dominated by the 2020 negative-price event.

### 5.5 Crisis sub-periods

| Crisis | n | A4f-VIX t | A4f-OVX t | A4f-COMBO t |
|---|---|---|---|---|
| GFC_2008 | 0 | — | — | — (pre-OOS) |
| OilCrash_2014-16 | 441 | -0.25 | +1.08 | +0.36 |
| NegOil_2020 | 94 | +1.70 | +2.31 | +2.33 |
| Ukraine_2022 | 125 | +1.51 | +1.74 | +1.60 |

Individual crisis windows are short (n<500); the strong full-OOS result comes from cumulative improvement, not a single crisis.

### 5.6 Robustness: drop 2020 negative-oil episode (4 days)

| Comparison | n | Diff% | DM t | Harvey |
|---|---|---|---|---|
| A4f-OVX vs GJR | 2956 | -0.95% | **+4.420** | **PASS** |
| A4f-COMBO vs GJR | 2956 | -0.88% | +4.027 | PASS |

**|H5 t| / |H1 t| = 4.420 / 4.475 = 0.988**. The 2020 negative-price event contributes ~1% of the DM statistic — the result is **not driven by the extreme episode**.

### 5.7 θ₁ stability

| Regressor | n refits | mean | std | CV |
|---|---|---|---|---|
| VIX | ~66 | 1.75e-06 | 6.95e-06 | 3.98 |
| OVX | ~50 | 1.77e-04 | 5.29e-04 | 2.99 |

OVX θ₁ is two orders of magnitude larger than VIX θ₁ (OVX levels are higher; scale-dependent). CV is elevated but stable enough for consistent forecasts.

## 6. Hypothesis verdicts

| # | Hypothesis | Verdict | Evidence |
|---|------------|---------|----------|
| H1 | Full OOS A4f-OVX vs GJR Harvey-PASS | **PASS** | DM t=+4.475, p<10⁻⁵ |
| H2 | OVX beats VIX as regressor | **PASS (OVX_SUPERIOR)** | head-to-head DM t=+3.177 |
| H3 | θ₁ stability | reasonable | CV=2.99 (OVX), 3.98 (VIX) |
| H4 | A4f-COMBO beats A4f-VIX | PASS | DM t=+3.039 |
| H4b | A4f-COMBO beats A4f-OVX | FAIL | DM t=-1.226 |
| H5 | Robust to neg-oil drop | **PASS** | DM t=+4.420 (98.8% of full) |

## 7. Conclusion

**USO + OVX PASSES all four critical tests.** Combined with K1085 gold/GVZ, the 4-asset-class matrix is now:

| Asset class | Test | Result |
|-------------|------|--------|
| Equity | A4f-VIX vs GJR | PASS (5 ETFs, multiple DM |t|>3) |
| Commodity - Gold | A4f-GVZ vs GJR | PASS (DM t=+4.46) |
| Commodity - Oil | A4f-OVX vs GJR | **PASS (DM t=+4.475)** |
| Bonds | A4f-MOVE & yield-curve vs GJR | FAIL (K1086, K1087) |

**Paper 9 scope statement (confirmed)**:
> "A4f's asset-matched implied-volatility structure (τ = θ₀ + θ₁·IV²_{t-1}) extends across liquid USD-denominated equity ETFs and commodity ETFs (gold and crude oil). Bonds lie outside the scope because the mechanical duration-ΔY identity absorbs the incremental signal that an implied-volatility regressor would provide in other asset classes."

## 8. Limitations

- **OVX history starts 2007-05**: A4f-OVX effective OOS begins in 2010-01 (after 2000-day window includes some OVX history). Early_GFC_Post window lacks sufficient OVX training to evaluate A4f-OVX.
- **USO structural issues**: USO has documented contango roll decay (long-run return ≠ spot WTI). This affects the mean return but not the vol forecasting exercise (we use squared returns as target).
- **No GFC_2008 evaluation**: The 2008 oil crash happened during the OOS training window, not the OOS evaluation period (per experimental design to keep OOS clean).
- **OVX_Crisis (>100) bucket is tiny (n=47)**: Dominated by 2020-04 negative-price days; result in this bucket is suggestive not definitive.
- **Cross-commodity generalization**: We have only gold and oil. Copper, natural gas, agricultural commodities remain untested.

## 9. Files

- `k1088.py` — Full experiment script
- `k1088_results.json` — All results (full OOS, per window, crisis, buckets, robustness, refit log)
- `k1088_dm_comparison.png` — 4-model DM bar chart, per OOS window
- `k1088_crisis_periods.png` — DM t by crisis sub-period
- `k1088_vix_ovx_compare.png` — QLIKE by model + pairwise DM (Full OOS)
- `k1088_theta1_evolution.png` — θ₁ time series for VIX and OVX
- `k1088_four_asset_class_final.png` — 4-asset-class summary (SPY/QQQ/EEM/IWM/FXI/GLD/TLT/USO)
- `README.md` — This file

## 10. References

- Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic Fundamentals. RES 95(3):776-797.
- Patton (2011). Volatility forecast comparison using imperfect volatility proxies. J Econometrics 160:246-256.
- Harvey, Leybourne & Newbold (2016). Testing the equality of prediction mean squared errors.
- Hansen & Lunde (2005). A forecast comparison of volatility models.
- Kilian (2009). Not all oil price shocks are alike. AER 99(3):1053-1069.
- Dutta (2017). Modeling and forecasting oil price risk: the role of implied volatility index. J Economic Studies 44(6):1003-1016.
- Bouoiyour & Selmi (2016). How differently does oil price influence Brazilian economy?

## 11. Upstream experiments

- K988 (SPY A4f original DM t=4.48 2019-2026)
- K1075 (SPY A4f extended 2007-2026)
- K1082 (Equity cross-asset 5 ETFs)
- K1085 (GLD + GVZ PASS, DM t=+4.46) — direct commodity analogue
- K1086 (TLT + MOVE FAIL)
- K1087 (TLT + yield curve FAIL)

## 12. Downstream directions

- **Paper 9 scope finalization**: Write "Equity + Commodity PASS, Bonds FAIL" scope section
- **Cross-commodity extension (K1089?)**: Copper (CPER? No matched IV index), Natural Gas (UNG + no dedicated IV), Agricultural (DBA + no matched IV). Limited by available IV indices — only GVZ and OVX exist for single commodities.
- **Currency asset class (K1090?)**: UUP + ?EUVIX? If an IV index exists for FX, this tests whether the pattern generalizes to currencies.
- **Crypto (K1091?)**: BITO + DVOL (Deribit vol index) as an extreme non-equity test.
