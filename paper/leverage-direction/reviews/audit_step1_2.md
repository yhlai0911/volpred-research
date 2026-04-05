# Paper 1 Audit: Leverage Direction Matters

**Audit Date:** 2026-04-05
**Paper version:** `main_v2.tex` + `body_v2.tex` (March 2026)
**Target journal:** Journal of Banking and Finance (JBF)

---

## 1. Complete Traceability Table

### Tables

| Paper Table | Label | Paper Claim | Source Experiment(s) | Field / Evidence | Paper Value | Experiment Value | Verified? |
|---|---|---|---|---|---|---|---|
| **Table 1** (`tab:desc`) | Descriptive Statistics | SPY mean 0.063%, std 1.16%, skew -0.32, kurt 14.6, N=2260 | **No single K-experiment found** | Inline calculation from yfinance data | Various | No JSON to verify | **UNTRACEABLE** |
| Table 1 | | GLD std 0.92%, skew -0.30, kurt 3.5 | No K-experiment | | | | **UNTRACEABLE** |
| Table 1 | | BTC mean 0.202%, std 3.61%, N=3285 | No K-experiment | | | | **UNTRACEABLE** |
| **Table 2** (`tab:gamma`) | Rolling Gamma | SPY mean gamma=+0.211, std=0.044, 0% neg, HAC t=+8.30 | K141/K143 (structural_leverage), K228, knowledge base entries | Multiple knowledge entries confirm SPY gamma ~0.21 | +0.211 | K824v2 full-sample gamma=0.2209 (consistent) | **PARTIALLY VERIFIED** (rolling mean vs full-sample differ slightly, no single JSON with exact 0.211) |
| Table 2 | | GLD mean gamma=-0.067, std=0.044, 93% neg, HAC t=-5.79 | Knowledge base: "GLD leverage direction" | "93% negative" confirmed in multiple entries | -0.067, 93% | Knowledge confirms 93% negative, gamma ~ -0.067 to -0.089 | **PARTIALLY VERIFIED** (consistent range but no exact JSON) |
| Table 2 | | TLT gamma=-0.008, 52% neg, HAC t=-0.34 | Knowledge base | | -0.008 | No direct JSON | **UNTRACEABLE** |
| Table 2 | | BTC gamma=+0.117, 28% neg, HAC t=+1.83 | K445 | | +0.117 | K445 exists but not verified field-by-field | **PARTIALLY VERIFIED** |
| Table 2 | | QQQ gamma=+0.110, 12% neg, HAC t=+3.21 | No specific K-experiment | | +0.110 | No JSON | **UNTRACEABLE** |
| Table 2 | | SLV gamma=-0.041, 72% neg, HAC t=-2.91 | No specific K-experiment | | -0.041 | No JSON | **UNTRACEABLE** |
| **Table 3** (`tab:qlike`) | QLIKE OOS | SPY 2023-24: GARCH=-8.985, GJR=-9.034, Delta=-0.54%, DM p=0.001 | Knowledge base (feature contribution analysis); K799 (Patton scale) | K799 QLIKE: GJR=1.466, GARCH=1.510 (Patton centered); text says -9.034 (quasi-LL) | -9.034 / -8.985 | Knowledge: "GARCH baseline -8.985, +GJR -9.034(-0.55%)" | **VERIFIED** (values consistent across multiple sources; -0.54% vs -0.55% is rounding) |
| Table 3 | | SPY 2025: GARCH=-8.719, GJR=-8.818, Delta=-1.13%, DM p=0.029 | No specific JSON found for 2025 OOS | | -8.818 / -8.719 | No direct JSON | **UNTRACEABLE** |
| Table 3 | | QQQ 2023-24: GARCH=-8.554, GJR=-8.475, Delta=+0.92%, DM p=0.067 | No specific JSON | | | | **UNTRACEABLE** |
| Table 3 | | QQQ 2025: Delta=-1.04%, DM p=0.023 | No specific JSON | | | | **UNTRACEABLE** |
| Table 3 | | GLD 2023-24: Delta=-0.07%, DM p=0.871 | No specific JSON | | | | **UNTRACEABLE** |
| Table 3 | | GLD 2025: Delta=+0.05%, DM p=0.350 | No specific JSON | | | | **UNTRACEABLE** |
| Table 3 | | TLT 2023-24: Delta=-0.01%, DM p=0.104 | No specific JSON | | | | **UNTRACEABLE** |
| Table 3 | | EEM 2023-24: Delta=-0.25%, DM p=0.156 | No specific JSON | | | | **UNTRACEABLE** |
| Table 3 | | BTC 2023-24: Delta=-0.14%, DM p=0.293 | No specific JSON | | | | **UNTRACEABLE** |
| **Table 4** (`tab:var`) | VaR Attribution SPY 2020-2025 | Normal: 33 violations, 2.2% | Knowledge base (multiple entries) | "Normal VaR 33 violations (2.2%)" | 33 / 2.2% | Knowledge confirms exactly | **VERIFIED** |
| Table 4 | | Student-t(5): 18 violations, 1.2%, -45.5% | Knowledge base | "Student-t(5) 降到 18 (1.2%)" | 18 / 1.2% / -45.5% | Knowledge confirms | **VERIFIED** |
| Table 4 | | +Adaptive: 14 violations, 0.9%, -22.2% | Knowledge base | "加 Adaptive threshold 降到 14 (0.9%)" | 14 / 0.9% | Knowledge confirms | **VERIFIED** |
| Table 4 | | +Jump: 14 violations, 0.9%, 0.0% | Knowledge base | "Jump augmentation 冗餘（+0%）" | 14 / 0.9% / 0% | Knowledge confirms | **VERIFIED** |
| **Table 5** (`tab:var_ortho`) | VaR Orthogonality SPY 2023-24 | GARCH Normal: 7 violations, 1.39%, Kupiec p=0.40, Green | K802: GARCH+Normal | K802: 7/502, rate=0.0139, kupiec_p=0.4019, green | 7 / 1.39% / 0.40 | 7 / 1.39% / 0.40 | **VERIFIED** |
| Table 5 | | GJR Normal: 10 violations, 1.99%, Kupiec p=0.049, Yellow | K799 layer_6: GJR=10/502 | K799: 10/502, rate=0.0199, kupiec_p=0.0491 | 10 / 1.99% / 0.049 | K799: 10 / 1.99% / 0.049 | **VERIFIED** (from K799; note K802 shows 9/502 -- different refit schedule) |
| Table 5 | | GJR Student-t(5): 6 violations, 1.20%, Kupiec p=0.60, Green | K802: GJR+StudentT | K802: 6/502, kupiec_p=0.6698 | 6 / 1.20% / 0.60 | 6 / 1.20% / 0.67 | **MISMATCH**: Kupiec p=0.60 in paper vs 0.67 in K802 |
| Table 5 | | GJR Hist.Sim: 4 violations, 0.80%, Kupiec p=0.60, Green | K824v2: M4_HistSim | K824v2: 4/502, kupiec_p=0.6353 | 4 / 0.80% / 0.60 | 4 / 0.80% / 0.64 | **MISMATCH**: Kupiec p=0.60 in paper vs 0.64 in K824v2; also K802 FHS says 5/502 |
| **Table 6** (`tab:var_panel`) | VaR Panel 7 assets | Skewed-t pass 76.2% (16/21), FHS 76.2% (16/21) | K829 (4 assets) + K802 (SPY) + other experiments | K829 only covers QQQ/GLD/BTC/0050.TW with 3 methods | 76.2% | K829: HistSim pass 6/8, Student-t 5/8, Normal 5/8 (different metrics) | **PARTIALLY VERIFIED** (K829 has 4 assets not 7; paper adds SPY+EEM+TLT+IWM; Skewed-t/CF-VaR not in K829) |
| **Table 7** (`tab:vt`) | VT Cross-Asset | SPY: BH=0.82, VT=0.85, BH MDD=-33.7%, VT MDD=-14.8% | Knowledge base (multiple entries) | Various knowledge entries | 0.82 / 0.85 | No single JSON; knowledge mentions -33.7% MDD for BH | **PARTIALLY VERIFIED** (MDD figures appear in multiple knowledge entries; Sharpe values not in a single verifiable JSON) |
| Table 7 | | GLD: BH=1.56, VT=1.71 | Knowledge: "GLD VT: VT Sharpe=1.71 > BH 1.56" | confirmed in knowledge | 1.56 / 1.71 | 1.56 / 1.71 | **VERIFIED** (from knowledge entry; note: this is 2022-2026 subsample only, not full sample) |
| Table 7 | | TLT: BH=0.02, VT=0.33 | No specific JSON | | 0.02 / 0.33 | No verification source | **UNTRACEABLE** |
| Table 7 | | EEM: BH=0.42, VT=0.45 | No specific JSON | | 0.42 / 0.45 | No verification source | **UNTRACEABLE** |
| Table 7 | | BTC: BH=0.43, VT=0.60, BH MDD=-76.6%, VT MDD=-21.3% | Knowledge: "BTC VT MDD: -83.7%" (different!) | Knowledge mentions BTC VT results | 0.43 / 0.60 / -76.6% / -21.3% | Knowledge: BH Sharpe=0.32, VT=0.50, MDD=-83.7% (different period) | **DISCREPANCY**: Knowledge entry shows different BTC numbers (possibly different period/parameters) |
| **Table 8** (`tab:window`) | Window Robustness | SPY GJR QLIKE for w=504/1000/2000/3000/5000 across 3 OOS | Knowledge: K591 "4 windows × 5 OOS periods" | K591 follow-up | Various | No single JSON verified | **UNTRACEABLE** |
| **Table 9** (`tab:hybrid`) | Hybrid VT | Hybrid Sharpe=0.99, MDD=-11.4% | Knowledge: "Kill Test #3: Hybrid VT Sharpe 0.985, MaxDD -11.4%" | confirmed | 0.99 | 0.985 | **MISMATCH**: Paper rounds 0.985 to 0.99 (aggressive rounding: +0.005 = +0.5%) |
| Table 9 | | RV20 VT: Sharpe=0.83, MDD=-13.8% | Knowledge: "RV20 0.834" | | 0.83 | 0.834 | **VERIFIED** (reasonable rounding) |
| Table 9 | | GARCH VT: Sharpe=0.82, MDD=-13.5% | Knowledge: "GARCH 0.820" | | 0.82 | 0.820 | **VERIFIED** |
| Table 9 | | EWMA VT: Sharpe=0.79, MDD=-13.4% | Knowledge: "EWMA 0.786" | | 0.79 | 0.786 | **VERIFIED** |
| Table 9 | | Buy & Hold: Sharpe=0.75, MDD=-33.7% | Knowledge: "BH Sharpe 0.75" | | 0.75 | Consistent across entries | **VERIFIED** |
| **Table 10** (`tab:amplify`) | Diversification Amplification | SPY ETF gamma=0.211, Avg Stock=0.076, Ratio=2.8x, t=-16.92 | Knowledge: "50-stock validation: SPY gamma=0.211 > avg 0.076, t=-16.92" | confirmed | 0.211 / 0.076 / 2.8x / -16.92 | 0.211 / 0.076 / -16.92 | **VERIFIED** |
| Table 10 | | EEM: ETF=0.138, Avg=0.041, Ratio=3.3x | Knowledge: "EEM 3.3x (3 stocks)" | confirmed | | | **VERIFIED** |
| Table 10 | | EWJ: ETF=0.087, Avg=0.127, Ratio=0.7x, t=2.09 | Knowledge: "Japan shows ATTENUATION: EWJ 0.087 < avg 0.127, ratio 0.7x, t=2.09" | confirmed | | | **VERIFIED** |
| **Table 11** (`tab:tail`) | Tail Risk Metrics | ES(1%)=-4.68% BH, -1.35% VT, -71% | No specific K-experiment JSON | | Various | No JSON | **UNTRACEABLE** |
| Table 11 | | Worst day: -11.59% BH, -1.70% VT, -85% | No specific JSON | | | | **UNTRACEABLE** |
| Table 11 | | Excess kurtosis: 14.71 BH, 0.46 VT, -97% | No specific JSON | | 14.71 | Table 1 shows SPY kurtosis 14.6 (different!) | **MISMATCH**: 14.71 vs 14.6 (different period: Table 11 is 2014-2026, Table 1 is 2017-2025) |
| **Table 12** (`tab:gamma-mechanism`) | Gamma-Mechanism | SPY gamma=+0.211, beta_trend=+0.109, t=18.0 | Knowledge: "Gamma-mechanism proposition" | Spearman rho=1.000 confirmed | +0.211 / +0.109 / 18.0 | Knowledge confirms rho=1.000, N=7 | **PARTIALLY VERIFIED** (aggregate result confirmed, individual values not in a single JSON) |
| Table 12 | | GLD gamma=-0.088, beta_trend=-0.055, t=-11.8, Contrarian | Knowledge entries | | -0.088 | Knowledge range: -0.067 to -0.089 | **VERIFIED** (within known range) |
| Table 12 | | Spearman rho=1.000 (p<0.001), Pearson r=0.993 | Knowledge: rho=1.000 confirmed | | 1.000 / 0.993 | 1.000 confirmed | **VERIFIED** |
| **Table 13** (`tab:complexity_ceiling`) | Complexity Ceiling | 10 rows of complexity steps | Various experiments | | Various | Multiple knowledge entries | **PARTIALLY VERIFIED** (individual entries confirmed; no single comprehensive JSON) |
| **Table 14** (`tab:qlike_ceiling`) | QLIKE Ceiling 14 models | CC-RV 22d = -9.071, GJR = -9.034 | K6 (knowledge: "QLIKE ceiling meta-analysis") | K6 confirmed CC-RV #1, GJR #5 | -9.071 / -9.034 | Knowledge: "CC-RV 22d ranks #1 on ALL 3 assets" | **PARTIALLY VERIFIED** (ranking confirmed, exact values not in accessible JSON) |
| **Table 15** (`tab:nulls`) | Null Results | 25 methods that failed | Various (K826, K833, K834, etc.) | | Various | Multiple K-experiments | **PARTIALLY VERIFIED** |
| **Table 16** (`tab:tz_arbitrage`) | TZ Momentum | HK t=4.12, Taiwan c2c=1.62, o2o=0.87 | Knowledge: "Taiwan c2c Sharpe 1.62, o2o 0.87" | confirmed | 1.62 / 0.87 | Knowledge confirms | **VERIFIED** |

### Figures

| Figure | Description | Source | Verified? |
|---|---|---|---|
| Fig 1 (`fig_rolling_gamma.pdf`) | Rolling gamma for SPY/GLD/TLT/EEM 2010-2026 | Generated from rolling GJR estimation | **No source script identified** -- likely inline generation |
| Fig 2 (`fig_vix_garch_ratio.pdf`) | VIX/GARCH ratio time series | Hybrid VT analysis | **No source script identified** |
| Fig 3 (`fig_cumulative_returns.pdf`) | Cumulative returns BH vs Hybrid VT | Hybrid VT backtest | **No source script identified** |
| Fig 4 (`fig_gamma_mechanism.pdf`) | Gamma vs trend-beta scatter | Gamma-mechanism analysis | **No source script identified** |
| Fig 5 (`fig_vix_weight_timeline.pdf`) | VIX weight timeline 2007-2026 | 12/VIX strategy | **No source script identified** |
| Fig 6 (`fig_mdd_comparison.pdf`) | MDD comparison across crises | Crisis analysis | **No source script identified** |
| Fig 7 (`fig_kurtosis_reduction.pdf`) | Kurtosis reduction chart | Tail risk analysis | **No source script identified** |

### Key In-Text Claims

| Section | Claim | Source | Verified? |
|---|---|---|---|
| Abstract | "nine Diebold-Mariano comparisons" | Table 3 (10 rows but 9 DM tests -- QQQ has 2 periods, others 1) | **VERIFIED** (count matches) |
| Abstract | "6/6 correct out-of-sample predictions" | Body text: 2023 gamma predicting 2024-25 model choice | **UNTRACEABLE** (no JSON for this specific OOS test) |
| Abstract | "Spearman rho=0.886, p=0.019 for six equity-type assets" | Knowledge: "equity 子群 rho=0.886 (p=0.019)" | **VERIFIED** |
| Abstract | "rho=-0.448, p=0.14 for twelve assets" | Knowledge: "跨所有 12 資產 rho=-0.448, p=0.14 (NS)" | **VERIFIED** |
| Abstract | "rho=0.944 for primary assets" | Body text Section 4.5.2 | Knowledge: "corr=0.944" | **PARTIALLY VERIFIED** |
| Abstract | "rho=0.83, p=0.0002, N=14 extended" | Body text | No specific JSON | **UNTRACEABLE** |
| Sec 4.2.1 | Gold 93% negative gamma, HAC t=-5.79 | Table 2; knowledge confirms 93% | | **VERIFIED** |
| Sec 4.2.3 | Gold regime: bull gamma=-0.043, bear=+0.048, t=-4.71, p<0.0001 | Knowledge: "正式 t-test 確認 (t=-4.705, p<0.0001)" | | **VERIFIED** |
| Sec 4.4 | GJR QLIKE -3.8% improvement, DM p=0.001 | K799 DM: GJR vs GARCH stat=-2.93, p=0.004 | Paper says p=0.001 for Table 3 SPY 2023-24 | **MISMATCH**: K799 DM p=0.004 (not passing Harvey t>3.0), paper Table 3 says p=0.001 |
| Sec 4.5 | EWMA VT SPY Sharpe=0.828 vs GJR 0.782, DM p=0.73 | Knowledge: "EWMA 0.828, GJR 0.782" | | **VERIFIED** |
| Sec 4.5 | COVID: GJR Sharpe 1.130, MDD -13.9% vs EWMA 0.745, -18.8% | Knowledge: mentioned in multiple entries | | **PARTIALLY VERIFIED** |
| Sec 4.5.5 | 12/VIX Sharpe 0.856, GARCH VT 0.826, MDD -16.5% vs -18.4% | Knowledge entries | | **PARTIALLY VERIFIED** |
| Sec 5.4 | Hybrid VT HM alpha=5.77%, t=3.99 | Knowledge: "Alpha=5.77% ann (t=3.99, p<0.001)" | | **VERIFIED** |
| Sec 5.4 | gamma_HM=-0.043, t=-4.06 | Knowledge: same entry | | **VERIFIED** |
| Sec 4.7 | HM gamma=-0.035, t=-0.39, p=0.70 | additions_jk.tex: "$\hat{\gamma}_{HM} = -0.035$ ($t = -0.39$, $p = 0.70$)" | **Discrepancy with Sec 5.4**: Sec 5.4 says gamma_HM=-0.043 (t=-4.06), Sec 4.7 says -0.035 (t=-0.39). **DIFFERENT VALUES for same test** | **CONFLICT** |
| Sec 5.5 | Proposition 1 Spearman rho=1.000, Pearson r=0.993 | Knowledge: confirmed | | **VERIFIED** |
| Sec 5.6 | VT no crossover, ~4%/yr cost, lambda>=2 VT dominates | Knowledge: "K41: VT 沒有 crossover point, ~4%/yr" | | **VERIFIED** |
| Sec 5.7 | Calendar R2=1.2%, VIX R2=88% | K736 results | K736 mentions "less than 10% seasonal" | **PARTIALLY VERIFIED** (exact R2 not in K736 JSON) |
| Sec 5.9 | HAR-ABS QLIKE=0.49 vs GJR 1.51, DM=-15.45 | Knowledge: HAR-ABS results mentioned | | **PARTIALLY VERIFIED** |

---

## 2. List of Untraceable Numbers

Numbers that have **no corresponding experiment JSON** and cannot be verified against stored data:

1. **Table 1 (Descriptive Statistics)**: ALL values (mean, std, skew, kurt, min, max, N for 7 assets). No `kXXX_descriptive_stats_results.json` exists. These are likely computed inline during paper writing but never saved as a formal experiment.

2. **Table 3 (QLIKE OOS) -- non-SPY assets**: QQQ, GLD, TLT, EEM, BTC QLIKE values and DM p-values. Only SPY 2023-24 is partially verified. The remaining 8 of 10 rows have no traceable JSON.

3. **Table 3 -- SPY 2025 OOS**: The -8.719/-8.818 values have no specific experiment JSON.

4. **Table 7 (VT Cross-Asset)**: TLT and EEM Sharpe/MDD values have no traceable source. BTC values conflict with knowledge base (different period/parameters).

5. **Table 8 (Window Robustness)**: All QLIKE values across 5 window sizes x 3 OOS periods have no single traceable JSON.

6. **Table 11 (Tail Risk Metrics)**: ES, worst day, kurtosis numbers have no source JSON. The kurtosis value (14.71) conflicts with Table 1 (14.6).

7. **Table 14 (QLIKE Ceiling)**: Individual QLIKE values for 14 models lack a traceable JSON. K6 is referenced in knowledge but no `k006_results.json` exists.

8. **All 7 Figures**: No source generation scripts were found. The PDF figures exist but the code that generated them is not in the experiments directory.

9. **Abstract claim "6/6 correct OOS predictions"**: No experiment JSON validates this specific out-of-sample classification test.

10. **Abstract/body "rho=0.83, p=0.0002, N=14 extended sample"**: MDD-volatility correlation for 14 assets has no traceable JSON.

---

## 3. List of Numbers That Don't Match

### Definite Mismatches

| # | Location | Paper Value | Experiment Value | Source | Severity |
|---|---|---|---|---|---|
| 1 | Table 5: GJR+Normal violations | **10/502 (1.99%)** | K802: **9/502 (1.79%)**, K824v2: **9/502** | K799 shows 10/502 | **MEDIUM** -- paper uses K799, but K802/K824v2 disagree. Likely different refit schedules. Should document which source is used. |
| 2 | Table 5: GJR+Student-t Kupiec p | **0.60** | K802: **0.6698** | K802 | **LOW** -- paper rounds 0.67 to 0.60. Not standard rounding. |
| 3 | Table 5: GJR+HistSim violations | **4/502 (0.80%)** | K802 FHS: **5/502 (1.00%)**, K824v2 HistSim: **4/502** | K802 vs K824v2 | **MEDIUM** -- paper matches K824v2 but calls it "Hist.Sim" while K802 calls the same method "FHS" with 5/502. Different implementations? |
| 4 | Table 5: GJR+HistSim Kupiec p | **0.60** | K824v2: **0.6353**, K802 FHS: **0.9928** | conflicting | **LOW** -- 0.64 rounded to 0.60 is aggressive |
| 5 | Table 9: Hybrid VT Sharpe | **0.99** | Knowledge: **0.985** | Kill Test #3 | **MEDIUM** -- rounding 0.985 to 0.99 inflates by 0.5%. Should report 0.99 or 0.985, not round up. |
| 6 | Table 11: BH Excess Kurtosis | **14.71** | Table 1 SPY Kurtosis: **14.6** | Internal inconsistency | **MEDIUM** -- different periods (2014-2026 vs 2017-2025) explain this, but it should be noted explicitly |
| 7 | Sec 4.4: DM p-value for GJR vs GARCH | **p=0.001** (Table 3) | K799: DM stat=-2.93, **p=0.004** | K799 layer_4 | **HIGH** -- paper's p=0.001 in Table 3 may come from a different experiment than K799. The K799 DM stat=-2.93 yields p~0.003-0.004, not 0.001. |
| 8 | Sec 4.7 vs Sec 5.4: Henriksson-Merton gamma | Sec 4.7: **gamma=-0.035 (t=-0.39)** vs Sec 5.4: **gamma=-0.043 (t=-4.06)** | Internal conflict | **HIGH** -- Two different values for the same Henriksson-Merton test. Sec 4.7 says "no directional timing" (t=-0.39), Sec 5.4 says "significant negative" (t=-4.06). These cannot both be correct for the same test on the same data. Likely different sample/specification. |
| 9 | Table 7: BTC BH MDD | **-76.6%** | Knowledge: BTC VT MDD=-83.7% (BH) | Different period | **LOW** -- different periods likely explain this, but the paper should cite which period Table 7 covers |

### Potential Mismatches (need further verification)

| # | Issue | Notes |
|---|---|---|
| A | Table 3 QLIKE values for non-SPY assets | Cannot verify -- no source JSON |
| B | Table 6 VaR Panel pass rates | Paper shows 5 methods x 7 assets; only partial coverage from K829 (4 assets x 3 methods) and K802 (SPY). The combined Skewed-t/CF-VaR results have no traceable source. |
| C | Table 12 individual gamma/beta_trend values | Aggregate rho confirmed, but individual asset values (e.g., USO gamma=+0.050, beta_trend=+0.032, t=12.9) lack individual JSON verification |

---

## 4. Recommendations

### Priority 1: Must Fix Before Submission (HIGH)

1. **Resolve HM gamma conflict (Sec 4.7 vs 5.4)**: The paper reports two different Henriksson-Merton gamma values (-0.035 vs -0.043). Determine which is correct and which specification is used. If they are different regressions (e.g., different sample periods or controls), state this explicitly.

2. **Verify Table 3 DM p=0.001 for SPY**: K799 shows DM stat=-2.93 which gives p~0.004, not 0.001. Either (a) a different experiment produced p=0.001 (need to identify it), or (b) the p-value is incorrect. Re-run the DM test and report the accurate p-value.

3. **Create a single reproducible experiment** for each paper table:
   - `experiments/paper1_table1_descriptive.py` + `_results.json`
   - `experiments/paper1_table3_qlike_oos.py` + `_results.json`
   - `experiments/paper1_table7_vt_crossasset.py` + `_results.json`
   - `experiments/paper1_table8_window_robust.py` + `_results.json`
   - `experiments/paper1_table11_tail_risk.py` + `_results.json`
   - `experiments/paper1_table12_gamma_mechanism.py` + `_results.json`
   This is essential for replication and for resolving all UNTRACEABLE items.

### Priority 2: Should Fix (MEDIUM)

4. **Standardize Table 5 (VaR Ortho) source**: The paper mixes K799 (GJR Normal=10) with K802 (Student-t=6) and K824v2 (HistSim=4). These experiments use different refit schedules. Re-run all 4 configurations with identical settings and report from one source.

5. **Fix Kupiec p-value rounding**: Paper reports p=0.60 for both Student-t and HistSim in Table 5, but actual values are 0.67 and 0.64 respectively. Report to 2 decimal places or use proper rounding.

6. **Hybrid VT Sharpe rounding**: Report 0.985 or 0.99 consistently; rounding 0.985 to 0.99 is aggressive. The paper already shows 2 decimal places for other strategies (0.83, 0.82, 0.79).

7. **Table 11 kurtosis consistency**: Note that Table 11 uses 2014-2026 while Table 1 uses 2017-2025, explaining the 14.71 vs 14.6 difference. Or use the same period.

8. **Figure source code**: Save the Python scripts that generated all 7 figures alongside the paper. This is required for replication.

### Priority 3: Nice to Have (LOW)

9. **Create comprehensive cross-asset VT experiment** covering all 5 assets in Table 7 with identical methodology, outputting a single JSON. The current situation relies on knowledge base text snippets from different experiments.

10. **Archive experiment-to-table mapping** in a `paper/leverage-direction/experiment_map.json` documenting which K-experiment backs each table cell.

---

## Summary Statistics

| Category | Count |
|---|---|
| Tables verified | 16 (across all tables) |
| Cells fully verified | ~35% |
| Cells partially verified | ~25% |
| Cells untraceable | ~30% |
| Cells with mismatches | ~10% |
| HIGH severity issues | 2 (HM gamma conflict; DM p-value) |
| MEDIUM severity issues | 5 |
| LOW severity issues | 3 |
| Experiments needing (re)run | 6 (one per major table lacking dedicated source) |
