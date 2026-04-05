# Paper 3 Audit: Steps 1 & 2 — Experiment Linkage and Number Verification

**Paper:** "Is Volatility Targeting Just Trend Following? Decomposing the Benefits of Volatility Targeting"
**Version:** body_v2.tex (compiled as main_v2.pdf, ~31-32 pages)
**Date:** 2026-04-05
**Auditor:** VolPred Research System (Claude Opus 4.6)

---

## 1. Experiment Linkage — Traceability Table

### Table 1: Alpha Decomposition (22 assets, Tab. 1 in paper)

| Paper Element | Source Experiment | Source File | Match Status |
|---|---|---|---|
| Table 1 (22-asset alpha decomposition) | K55/K73 (N=22 VT-TSMOM final) | `storage/experiments/vt_tsmom_final_n22.json` | **VERIFIED** |
| SPY gamma=0.261 | K55 `gjr_gamma=0.261` | vt_tsmom_final_n22.json | **MATCH** |
| SPY M1 alpha=1.35%, t=1.44 | K55 `alpha_ann=0.01348, t=1.44` | vt_tsmom_final_n22.json | **MATCH** (1.35% = 0.01348 * 100) |
| SPY M1 R2=0.802 | K55 `r2=0.802` | vt_tsmom_final_n22.json | **MATCH** |
| SPY TSMOM_orth=0.121, t=7.65 | K55 `beta_tsmom_orth=0.1208, t=7.6452` | vt_tsmom_final_n22.json | **MATCH** (rounded) |
| SPY M2 R2=0.867 | K55 `r2=0.8667` | vt_tsmom_final_n22.json | **MATCH** (rounded) |
| SPY delta-alpha=26.9% | K55 `alpha_reduction_pct=26.85%` | vt_tsmom_final_n22.json | **MATCH** (rounded) |
| QQQ gamma=0.225 | K55 `gjr_gamma=0.225` | vt_tsmom_final_n22.json | **MATCH** |
| DIA gamma=0.235, t=11.57 | K55 `gjr_gamma=0.235, t=11.5659` | vt_tsmom_final_n22.json | **MATCH** |
| GLD gamma=-0.037, TSMOM=-0.073, t=-3.18 | K55 `gjr_gamma=-0.037, beta=-0.0729, t=-3.1831` | vt_tsmom_final_n22.json | **MATCH** |
| TLT gamma=-0.015, TSMOM=-0.078, t=-4.55 | K55 `gjr_gamma=-0.015, beta=-0.078, t=-4.5504` | vt_tsmom_final_n22.json | **MATCH** |
| 17/22 significant TSMOM loadings | K55 conclusions | vt_tsmom_final_n22.json | **MATCH** |

### Table 2: Cross-Sectional (Tab. 2 in paper)

| Paper Element | Source Experiment | Source File | Match Status |
|---|---|---|---|
| Pearson r=0.564, p=0.006 | K55/K73 | vt_tsmom_final_n22.json | **MATCH** (r=0.5644, p=0.006216) |
| Spearman rho=0.544, p=0.009 | K55/K73 | vt_tsmom_final_n22.json | **MATCH** (rho=0.5438, p=0.008902) |
| Bootstrap 95% CI [0.263, 0.772] | K55/K73 | vt_tsmom_final_n22.json | **MATCH** |
| CS regression: gamma1=0.568, t=3.06, R2=0.319 | K55/K73 | vt_tsmom_final_n22.json | **MATCH** (gamma1=0.5681, t=3.0575, R2=0.3185) |
| Split-sample r=0.487, p=0.021 | Stated in review_v2 | **NO SOURCE JSON FOUND** | **UNTRACEABLE** — see Issue #1 |
| Split-sample bootstrap CI [0.114, 0.737] | Stated in paper | **NO SOURCE JSON FOUND** | **UNTRACEABLE** |
| Split-sample Spearman rho=0.461, p=0.031 | Stated in paper | **NO SOURCE JSON FOUND** | **UNTRACEABLE** |
| Equity mean TSMOM=0.087, Non-Equity=0.012 | K55 | vt_tsmom_final_n22.json | **MATCH** (0.0872, 0.0121) |
| Welch t=1.98, p=0.080 | K55 | vt_tsmom_final_n22.json | **MATCH** (t=1.978, p=0.0802) |

### Table 3: Dual Mechanism Decomposition (Tab. 3 in paper)

| Paper Element | Source Experiment | Source File | Match Status |
|---|---|---|---|
| SPY B&H Sharpe=0.611, MDD=-55.2% | **UNTRACEABLE** | No matching JSON for 2005-2026 period | **UNTRACEABLE** — see Issue #2 |
| SPY VT Sharpe=0.797, MDD=-24.7% | **UNTRACEABLE** | No matching JSON for 2005-2026 period | **UNTRACEABLE** |
| SPY Hedged VT Sharpe=0.737, MDD=-26.9% | **UNTRACEABLE** | No matching JSON for 2005-2026 period | **UNTRACEABLE** |
| SPY Pure TSMOM Sharpe=0.172, MDD=-27.5% | **UNTRACEABLE** | No matching JSON | **UNTRACEABLE** |
| SPY delta-Sharpe=+0.186, lost to TSMOM=-0.060 (32%) | **UNTRACEABLE** | Derived from above | **UNTRACEABLE** |
| SPY MDD protection 30.5 pp, retained 28.3 pp (93%) | **PARTIALLY TRACEABLE** | paper3_fixes.json shows 92.13% for 2007 period | **PERIOD MISMATCH** |
| 50/50 B&H Sharpe=0.865, MDD=-32.5% | **UNTRACEABLE** | No matching JSON for 2005-2026 period | **UNTRACEABLE** |
| 50/50 VT Sharpe=0.982, MDD=-12.4% | **UNTRACEABLE** | No matching JSON | **UNTRACEABLE** |
| DIA MDD retention 91% | **UNTRACEABLE** | Not in paper3_fixes.json (only SPY/QQQ/EEM/EFA/GLD) | **UNTRACEABLE** |
| IWM MDD retention 97% | **UNTRACEABLE** | Not in paper3_fixes.json | **UNTRACEABLE** |

**Critical note on Table 3:** The paper states "Full-sample results over 2005-2026" in the table notes, but the paper3_fixes.json (K79) uses a 2007-2026 period and tests only SPY/QQQ/EEM/EFA/GLD (not DIA or IWM). The Sharpe ratios in paper3_fixes.json (SPY VT=0.618, B&H=0.541) are completely different from Table 3 (SPY VT=0.797, B&H=0.611). **There is no discoverable source file for the Table 3 numbers.** Either: (a) they were computed in a script that did not save results to JSON, or (b) they were directly embedded in the LaTeX during figure generation. The figures/ directory has `generate_figures.py` which might contain the computation.

### Table 4: Factor Model Controls (Tab. 4 in paper)

| Paper Element | Source Experiment | Source File | Match Status |
|---|---|---|---|
| M1 alpha=1.45%, t=1.60 | K71 | ff5_factor_controls.json | **MATCH** (1.445%, t=1.604) |
| M2 TSMOM=0.121, t=8.89 | K71 | ff5_factor_controls.json | **CLOSE** (0.1212, t=8.892) — paper says t=8.89 |
| M5 alpha=1.28%, t=1.50 | K71 | ff5_factor_controls.json | **MATCH** (1.276%, t=1.496) |
| M5 TSMOM=0.117, t=8.07 | K71 | ff5_factor_controls.json | **MATCH** (0.1166, t=8.068) |
| M5 BAB=-0.022, t=-3.31 | K71 | ff5_factor_controls.json | **MATCH** (-0.0217, t=-3.312) |
| M5 N=3,740 (BAB subsample) | K71 | ff5_factor_controls.json | **MISMATCH** — see Issue #3 |
| R2: 0.787, 0.849, 0.852, 0.852, 0.853 | K71 | ff5_factor_controls.json | **MATCH** (0.787, 0.849, 0.852, 0.852, 0.853) |
| AIC: -45339, -47092, -47160, -47171, -47213 | K71 | ff5_factor_controls.json | **MATCH** |
| M1-M4 N=5,049 | K71 | ff5_factor_controls.json | **MATCH** |

### Table 5: International VT (Tab. 5 in paper)

| Paper Element | Source Experiment | Source File | Match Status |
|---|---|---|---|
| 13 international ETFs | K567 + related | `k567_international_vt_leverage_results.json` | **PARTIALLY TRACEABLE** |
| Average delta-MDD = 28.7 pp, t=15.70 | Unknown | **NO EXACT SOURCE FOUND** | **UNTRACEABLE** — see Issue #4 |
| VIX sensitivity vs delta-MDD: r=-0.770, p=0.002 | Unknown | **NO EXACT SOURCE FOUND** | **UNTRACEABLE** |
| Specific country numbers (EFA, EWJ, etc.) | Unknown | **NO EXACT SOURCE FOUND** | **UNTRACEABLE** |

### Table 6: MDD Bootstrap (Tab. 6 in paper)

| Paper Element | Source Experiment | Source File | Match Status |
|---|---|---|---|
| SPY 93% [86%, 97%] | **UNTRACEABLE** | No bootstrap JSON found | **UNTRACEABLE** — see Issue #5 |
| 50/50 96% [90%, 99%] | **UNTRACEABLE** | No bootstrap JSON found | **UNTRACEABLE** |
| DIA 91% [83%, 96%] | **UNTRACEABLE** | No bootstrap JSON found | **UNTRACEABLE** |
| QQQ 90% [82%, 95%] | **UNTRACEABLE** | No bootstrap JSON found | **UNTRACEABLE** |
| IWM 97% [91%, 100%] | **UNTRACEABLE** | No bootstrap JSON found | **UNTRACEABLE** |
| All reject H0: Retention <= 80% at p < 0.01 | **UNTRACEABLE** | No bootstrap JSON found | **UNTRACEABLE** |

### Figures

| Paper Element | Source | Match Status |
|---|---|---|
| Fig. 1: Return decomposition | `figures/fig1_return_decomposition.pdf` | Exists; **hard-coded numbers** in `generate_figures.py` (lines 44-56, 116-117); not read from JSON |
| Fig. 2: Cross-asset scatter | `figures/fig2_cross_asset_scatter.pdf` | Exists; **hard-coded numbers** in `generate_figures.py` (lines 171-187); not read from JSON |

**Note:** `generate_figures.py` confirms the traceability gap: both figures use manually entered numbers from the paper text rather than reading from experiment JSON files. The numbers in the script match the paper exactly (by construction), but neither traces back to a verifiable computation.

**Additional concern with Figure 1:** For DIA/QQQ/IWM, the figure script uses *estimated* MDD total protection values (`mdd_total = [30.5, 20.1, 28.0, 32.0, 27.0]`, lines 116-117) because the paper only provides retention percentages (91%/90%/97%) but not the absolute MDD values for these three assets. The script comments acknowledge this: "We estimate from Table 1 B&H MDD context" (line 113). This means Figure 1 Panel (b) bars for DIA/QQQ/IWM are based on guesswork, not verified data.

### Other Key Claims

| Claim | Source Experiment | Source File | Match Status |
|---|---|---|---|
| "1.4% TSMOM contribution to total Sharpe" | K79 paper3_fixes.json | paper3_fixes.json | **SEE ISSUE #6** |
| VIX thresholds 8-20 all significant (t=7.98-10.91) | K79 | paper3_fixes.json | **MATCH** (t range 7.98-10.91 verified) |
| Sector gamma range [0.077, 0.160] | K79 or separate sector analysis | **UNTRACEABLE** | No sector JSON found |
| Sector r=0.163, NS | Paper only | **UNTRACEABLE** | No sector JSON found |
| 5 trend strategies all fail Harvey | K518 | k518_trend_following_results.json | **MATCH** (all t < 3.0) |
| Golden Cross Sharpe 0.51, t=0.94, cross-OOS 3/5 | K518 | k518_trend_following_results.json | **MATCH** (Sharpe=0.5104, t=0.9402, 3/5 beats) |
| 427 VT configurations, 12/VIX return-optimal | K568 | k568_optimal_weight_function_results.json | **MATCH** |
| K533 HAR-RV best forecast but worst VT | K533 | k533_har_vt_strategy_results.json | **TRACEABLE** (but sparse JSON) |
| K697 VIX predicts vol (0.57) not direction (0.04) | K697 | k697_results.json | **MATCH** (0.5704, 0.0417) |
| K687 no VT beats BH 50/50 after lag | K687 | k687_results.json | **TRACEABLE** |
| K688 CRRA utility gamma >= 5 | K688 | k688_results.json | **MATCH** (EWMA VT wins at gamma=5) |

---

## 2. Number Verification — Specific Issues

### Issue #1: Split-Sample Results (r=0.487) — NO SOURCE JSON

**Severity: HIGH**

The split-sample robustness check (estimating gamma from 2007-2016 and TSMOM loading from 2017-2026) is a v2 addition that addresses the endogeneity concern. The paper reports r=0.487, p=0.021, bootstrap CI [0.114, 0.737], Spearman rho=0.461, p=0.031.

**No corresponding JSON file exists.** The `vt_tsmom_final_n22.json` contains only full-sample cross-sectional results. The split-sample was likely computed during the v1-to-v2 revision but the results were not saved to a traceable experiment file.

**Action required:** Re-run the split-sample analysis and save results to `experiments/` and `storage/experiments/`. The numbers themselves may well be correct, but they violate the research integrity principle (rule #3: every experiment must have a corresponding results file).

### Issue #2: Table 3 Numbers (Dual Mechanism, 2005-2026) — NO SOURCE JSON

**Severity: HIGH**

Table 3 reports SPY B&H Sharpe=0.611, VT Sharpe=0.797, Hedged VT Sharpe=0.737, plus MDD numbers and 50/50 blend results. The table notes say "2005-2026".

The closest source file is `paper3_fixes.json` (K79), but it uses the **2007-2026** period and shows completely different numbers:
- K79 SPY B&H Sharpe=0.541 vs paper 0.611
- K79 SPY VT Sharpe=0.618 vs paper 0.797
- K79 MDD preservation=92.13% vs paper 93%

The paper3_fixes.json also tests **SPY/QQQ/EEM/EFA/GLD**, not SPY/50-50/DIA/QQQ/IWM as in Table 3.

Furthermore, `vt_trend_decomposition.json` (K46/K49) uses a GARCH VT with sigma_target=0.12 (not 12/VIX), and shows SPY VT Sharpe=0.243 — completely different.

**The entire Table 3 appears to have been computed by a script (likely `figures/generate_figures.py` or an ad-hoc computation during paper drafting) without saving structured results.** This is the single largest traceability gap in the paper.

**Action required:** Re-run the dual mechanism decomposition for SPY/50-50/DIA/QQQ/IWM using 12/VIX with 2005-2026 data, save as `experiments/kXXX_dual_mechanism_2005_results.json`, and verify all 6 numbers per asset.

### Issue #3: Table 4 M5 Sample Size Discrepancy

**Severity: MEDIUM**

The paper states M5 (with BAB) uses N=3,740 due to SPLV/SPHB ETF availability from May 2011. However, `ff5_factor_controls.json` shows M5 with **N=5,049** — the same as M1-M4. This means the JSON likely used AQR BAB data (available from 1926) rather than the SPLV-SPHB ETF proxy, or it substituted zeros/NaN for the missing period.

The paper's note "$^\dagger$M5 is estimated over the post-2011 subsample (N=3,740)" may describe a different run than what is in the JSON.

**Consequence:** If M5 was actually estimated on N=5,049 (using AQR BAB), then the paper's claim about SPLV-SPHB proxy is incorrect — which would also address review issue B.2 (replace SPLV with AQR BAB). If M5 was estimated on N=3,740 (SPLV proxy), then the JSON does not match the paper.

**Action required:** Determine which BAB data was actually used in the JSON, and reconcile with the paper text. If AQR BAB was used (N=5,049), update the paper text to reflect this and remove the SPLV-SPHB discussion.

### Issue #4: Table 5 (International Evidence) — NO EXACT SOURCE JSON

**Severity: MEDIUM**

The 13-market international results (Table 5) include specific numbers for each country ETF (Sharpe, MDD, delta-MDD), plus cross-sectional statistics (average delta-MDD=28.7 pp, t=15.70, VIX sensitivity correlation r=-0.770). The knowledge base references K567 (International VT Leverage), but that experiment tested only 6 markets (SPY/EFA/EWZ/EWJ/EWU/FXI) with a different set of assets than the paper's 13.

**No single JSON file contains all 13 markets' results as presented in Table 5.** The data may have been computed by `figures/generate_figures.py` or a separate script.

**Action required:** Create a dedicated experiment file for the 13-market international analysis.

### Issue #5: Table 6 (MDD Bootstrap) — NO SOURCE JSON

**Severity: HIGH**

The block bootstrap results (10,000 replications, block size 252) for 5 assets are critical to the paper's statistical inference. These include point estimates, 90% CIs, and hypothesis test p-values. **No JSON file containing bootstrap results was found anywhere in the repository.**

**Action required:** Re-run the bootstrap analysis, save results, and verify all numbers.

### Issue #6: The "1.4%" TSMOM Contribution — Misleading Average

**Severity: HIGH** (matches review_v2 issue C.1)

The paper states "the TSMOM contribution to Sharpe improvement is approximately 1.4% of total strategy Sharpe" (Section 3.3, Table 1 notes).

The source is `paper3_fixes.json`, field `mean_tsmom_sharpe_contribution_pct = 1.39%`. This is the mean of:
- SPY: **7.10%**
- QQQ: **5.30%**
- EEM: **-0.61%** (negative!)
- EFA: **-5.01%** (strongly negative!)
- GLD: **0.18%**

The 1.4% is a **simple arithmetic mean across 5 heterogeneous assets**, pulled down by the negative values for EEM and EFA (where hedging actually *increases* Sharpe). This mean is misleading because:

1. **For SPY specifically** (the paper's primary asset), TSMOM explains 7.1% of VT Sharpe — not 1.4%.
2. **The negative values for EEM and EFA** arise because VIX is a poor match for these assets' volatility drivers, so the TSMOM hedge introduces noise.
3. **The 1.4% is not a universal property of VT** — it is an artifact of averaging across assets with very different VIX-sensitivity.
4. **Period mismatch:** The 1.4% comes from the 2007-2026 sample, while Table 3 uses 2005-2026. The Table 3 numbers imply a different TSMOM contribution (the paper says delta-Sharpe=-0.060 and VT Sharpe=0.797, giving 0.060/0.797 = **7.5%** for SPY).

**The paper's own Table 3 implies 7.5% for SPY, but the text says "approximately 1.4%".** This is internally inconsistent. The review correctly flagged this as unexplained.

**Recommended fix:** Report the TSMOM Sharpe contribution separately for each asset (as the Sharpe change from TSMOM hedging / total VT Sharpe). State explicitly that it is 7% for SPY but averaging near zero across the 5-asset panel due to non-equity assets.

---

## 3. Additional Mismatched Numbers

### 3a. Table 1 note vs Table 3 period

- Table 1 notes: "January 2007-March 2026" (22-asset analysis)
- Table 3 notes: "2005-2026" (dual mechanism for SPY/50-50)
- Table 4 notes: "January 2005-March 2026"

The different periods are **now explicitly rationalized** in Section 2.1 and Table "Sample Periods by Analysis" (body_v2.tex lines 56-76). This partially addresses review issue B.1, but the reviewer may still find it confusing that the same asset (SPY) appears in different tables with different sample periods.

### 3b. paper3_fixes.json MDD retention vs paper

Paper3_fixes.json (2007-2026):
- SPY: 92.13%
- QQQ: 93.33%
- EEM: 90.28%
- EFA: 94.02%
- GLD: 96.56%

Paper Table 3 / abstract (2005-2026 for SPY):
- SPY: 93%
- 50/50: 96%
- DIA: 91%
- QQQ: 90%
- IWM: 97%

**The asset sets are different** (paper3_fixes tests EEM/EFA/GLD; paper tests 50-50/DIA/IWM). Both claim 90-97% range. The SPY retention differs (92.13% vs 93%) due to different sample periods. This is consistent but makes tracing from paper to data difficult.

### 3c. K697 correlation numbers

Paper knowledge (from CLAUDE.md): "VIX predicts vol magnitude (corr 0.57) but NOT direction (corr 0.04)"
K697 results JSON: `corr_vix_lag_absret=0.5704`, `corr_vix_lag_ret=0.0417`

These match but are not directly cited in the paper text. The review (A.1) recommends incorporating K697 into the paper.

---

## 4. Status of 5 HIGH Issues from review_v2

| # | Issue | Status | Detail |
|---|---|---|---|
| **A.1** | Reconciliation with K687/K697/K688 | **NOT ADDRESSED** | The paper does not cite K687, K697, or K688. K687 (VT=insurance) *supports* the paper's thesis. K697 (VIX predicts magnitude not direction) directly validates the VIX-level mechanism. K688 (CRRA gamma>=5) provides formal framework for Cederburg rebuttal. All three are verified in their respective result JSONs. |
| **B.1** | Inconsistent sample periods | **PARTIALLY ADDRESSED** | v2 added Table "Sample Periods by Analysis" (Section 2.1) that explains the different periods. However, Table 3 notes still say "2005-2026" while using N values that may not match. The rationalization is good but the underlying data traceability is poor. |
| **B.2** | BAB proxy (SPLV->AQR) | **AMBIGUOUS** | The ff5_factor_controls.json shows M5 with N=5,049 (same as M1-M4), suggesting AQR BAB may have actually been used. But the paper text still describes SPLV-SPHB as the proxy with N=3,740. Need to verify which was actually used. |
| **B.3** | MDD retention only 5 US equity assets | **NOT ADDRESSED** | Table 3 still covers only SPY/50-50/DIA/QQQ/IWM. paper3_fixes.json tested different assets (SPY/QQQ/EEM/EFA/GLD), showing the methodology works for non-equity. But neither set is the full 22. |
| **C.1** | "1.4%" number unverifiable/wrong | **SOURCE FOUND BUT PROBLEMATIC** | The 1.4% is traceable to paper3_fixes.json (mean_tsmom_sharpe_contribution_pct=1.39%). However, it is a misleading average (see Issue #6 above). For SPY, the actual contribution is 7.1%, consistent with Table 3's implied 7.5%. The number is not "wrong" in the narrow sense of being a valid computation, but it is misleading as presented. |

---

## 5. Summary of Findings

### Fully Verified (traceable to JSON with matching numbers)
- Table 1 (alpha decomposition, 22 assets) — all numbers verified against `vt_tsmom_final_n22.json`
- Table 2 (cross-sectional correlations, N=22) — all full-sample numbers verified
- Table 4 factor loadings (M1-M5 coefficients and t-statistics) — verified against `ff5_factor_controls.json`
- K518 trend following results — all 5 strategies verified
- K568 optimal weight function — verified
- VIX threshold robustness (t=7.98-10.91) — verified against `paper3_fixes.json`

### Partially Traceable (source exists but period/asset mismatch)
- Table 3 MDD retention rates — paper3_fixes.json has similar numbers but different period (2007 vs 2005) and different assets
- Table 4 M5 sample size — JSON says N=5,049, paper says N=3,740
- Table 5 international evidence — K567 covers only 6 of the 13 markets

### Untraceable (no source JSON found)
- **Table 3 dual mechanism numbers** (Sharpe, MDD, Calmar for all 4 strategies x 2 assets)
- **Table 5 full 13-market international results** (all country-specific numbers)
- **Table 6 bootstrap results** (point estimates, CIs, p-values for 5 assets)
- **Split-sample cross-sectional analysis** (r=0.487, p=0.021, CI, Spearman)
- **Sector analysis** (gamma range [0.077, 0.160], r=0.163)

### Untraceable Count: 5 major data blocks (~50% of paper's tables)

---

## 6. Recommended Actions (Priority Order)

1. **[CRITICAL] Create experiment scripts + result JSONs for Table 3, Table 5, Table 6, and split-sample analysis.** These are the paper's core novel results and currently have no reproducible audit trail.

2. **[HIGH] Resolve the 1.4% inconsistency.** Either: (a) report per-asset TSMOM Sharpe contribution with the mean and clarify it is a cross-asset average, or (b) change the narrative to report SPY's 7.5% contribution and note the cross-asset variation.

3. **[HIGH] Verify Table 4 M5 sample size.** Determine whether AQR BAB or SPLV-SPHB was used and update paper text to match.

4. **[MEDIUM] Incorporate K687/K697/K688.** These experiments are verified and strongly support the paper's thesis. Their absence is noted by the review as the paper's "main weakness."

5. **[MEDIUM] Store all intermediate computations.** Any future revision must save every statistical output to a structured JSON file. The current gap appears to stem from computations done directly in figure-generation scripts or interactive sessions.
