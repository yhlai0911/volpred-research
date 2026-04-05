# Paper 8 Audit: Volatility Absorption Hypothesis
## Step 1 (Experiment Linkage) + Step 2 (Number Verification)

**Paper:** "Volatility Absorption: The Diminishing Marginal Impact of Market Fear"
**Latest version:** `paper/volatility-absorption/main_v2.tex` (38 pages, 37 citations)
**Audit date:** 2026-04-05

---

## Step 1: Experiment Linkage

### 1.1 Inventory of Tables, Figures, and Key Numerical Claims

| # | Item | Label | Description | Source Experiment | Script Exists? |
|---|------|-------|-------------|-------------------|----------------|
| 1 | Table 1 | `tab:desc_stats` | Descriptive Statistics (returns + VIX, 2006-2026) | No dedicated experiment | N/A |
| 2 | Table 2 | `tab:regime_dist` | VIX Regime Distribution + Shock Frequency | K716 (partial) | NO .py |
| 3 | Table 3 | `tab:absorption_core` | SAR by VIX Regime (5-bin, SPY) | **K716** | NO .py |
| 4 | Table 4 | `tab:cross_asset` | Cross-Asset Absorption Coefficients | **K718** | NO .py |
| 5 | Table 5 | `tab:shock_types` | Absorption by Shock Type (endo/exo) | **K721** | NO .py |
| 6 | Table 6 | `tab:nfp` | NFP Day Volatility by VIX Regime | **K741** | YES (.py) |
| 7 | Table 7 | `tab:vrp` | Variance Risk Premium by VIX Regime | **K720** (partial) | NO .py |
| 8 | Table 8 | `tab:hedge_cb` | Hedging Cost-Benefit Ratio by VIX Regime | **K719** (partial) | NO .py |
| 9 | Table 9 | `tab:robust_threshold` | Alternative Shock Thresholds | UNTRACEABLE | NO |
| 10 | Table 10 | `tab:robust_subperiod` | Sub-Period Stability | UNTRACEABLE | NO |
| 11 | Table A1 | `tab:variables` | Variable Definitions (no data) | N/A | N/A |
| 12 | Table A2 | `tab:cross_asset_detail` | Full Regression Results by Asset | **K718** (extended) | NO .py |
| 13 | Eq. 6 (text) | `eq:absorption_result` | NSI regression: slope=-0.00028, t=-3.42 | **K716** | NO .py |
| 14 | Text (Sec 7.3) | --- | Alt normalization: beta_RV=-0.0031, t=-2.76 | UNTRACEABLE | NO |
| 15 | Text (Sec 7.4) | --- | Controlled regression: beta=-0.00025, t=-3.14 | UNTRACEABLE | NO |
| 16 | Text (Sec 6.3) | --- | VT overlay: Sharpe 0.53 vs 0.68, DM t=-2.81 | Referenced as "prior work" | NO |
| 17 | Text (Sec 6.2) | --- | Rebalancing: daily Sharpe 1.42 vs monthly 0.82 | Referenced as "prior work" | NO |

### 1.2 Experiment-to-Paper Mapping

| Experiment | Knowledge ID | Title | Used in Paper |
|------------|-------------|-------|---------------|
| **K716** | K716 | Panic Paralysis CONFIRMED | Tables 2, 3; Eq. 6; core regression |
| **K718** | K718 | Panic Paralysis Cross-Asset | Tables 4, A2 |
| **K719** | K719 | VRP sign flip PARTIALLY WRONG | Table 8 (hedging cost-benefit concept) |
| **K720** | K720 | VRP Correction | Table 7 (VRP by regime) |
| **K721** | K721 | Shock Type Paralysis | Table 5 |
| **K722** | K722 | Absorption-adjusted VIX | Not used (null result, correctly excluded) |
| **K741** | k_20260330_195451 | NFP Event Vol Study | Table 6 |
| K723 | K723 | Codex Review 1 | Review only |
| K728 | K728 | Codex Review 2 | Review only |
| K729 | K729 | Codex Review 3 | Review only |

### 1.3 Linkage Issues

**CRITICAL: No .py scripts exist for K716, K717, K718, K719, K720, K721, K722, K724-K727.**
Only `_results.json` files exist. The paper's core experiments lack replication scripts. Only K741 has both `.py` and `_results.json`.

**UNTRACEABLE claims (no experiment JSON source):**
1. Table 1 (Descriptive Statistics): SPY mean 0.040%, std 1.194%, etc. -- No experiment computes these. Likely generated during paper writing.
2. Table 9 (Alternative thresholds): tau=1.0 N=1842 beta=-0.00015, tau=1.5 N=1287 beta=-0.00022, etc. -- No experiment JSON.
3. Table 10 (Sub-period): 2006-2012 N=378 beta=-0.00035, 2013-2019 N=198 beta=-0.00018, 2020-2026 N=317 beta=-0.00031. -- No experiment JSON. (Note: 378+198+317=893 matches the regression N, providing internal consistency.)
4. Section 7.3 (RV normalization): beta_RV=-0.0031, t=-2.76. -- No experiment JSON.
5. Section 7.4 (Controlled regression): beta=-0.00025, t=-3.14. -- No experiment JSON.
6. Section 6.2-6.3 (VT performance): daily Sharpe 1.42, monthly 0.82, overlay Sharpe 0.53 vs 0.68. -- Cited as "prior work in our research program" with no specific experiment ID.

---

## Step 2: Number Verification

### 2.1 Table 3 (SAR Core) vs K716 -- FULL MATCH

| Regime | Paper shock_days | K716 | Paper shock_|r| | K716 | Paper normal_|r| | K716 | Paper SAR | K716 |
|--------|-----------------|------|-----------------|------|-------------------|------|-----------|------|
| Calm (<15) | 34 | 34 MATCH | 1.24 | 1.24 MATCH | 0.39 | 0.39 MATCH | 3.16 | 3.16 MATCH |
| Normal (15-20) | 168 | 168 MATCH | 1.44 | 1.44 MATCH | 0.52 | 0.52 MATCH | 2.77 | 2.77 MATCH |
| Elevated (20-25) | 189 | 189 MATCH | 1.64 | 1.64 MATCH | 0.69 | 0.69 MATCH | 2.37 | 2.37 MATCH |
| High (25-30) | 132 | 132 MATCH | 1.93 | 1.93 MATCH | 0.83 | 0.83 MATCH | 2.32 | 2.32 MATCH |
| Crisis (>=30) | 244 | 244 MATCH | 2.99 | 2.99 MATCH | 1.23 | 1.23 MATCH | 2.43 | 2.43 MATCH |

Regression slope: Paper=-0.00028, K716=-0.00028 **MATCH**

**Verdict: 20/20 cells verified. PERFECT MATCH.**

### 2.2 Table 4 (Cross-Asset) vs K718 -- SLOPES MATCH, t-stats UNTRACEABLE

| Asset | Paper slope | K718 slope | Match? | Paper t-stat | K718 t-stat | Match? |
|-------|-----------|-----------|--------|-------------|-------------|--------|
| SPY | -0.00028 | -0.00028 | MATCH | -3.42 | NOT IN JSON | UNTRACEABLE |
| GLD | -0.00043 | -0.00043 | MATCH | -4.17 | NOT IN JSON | UNTRACEABLE |
| TLT | -0.00044 | -0.00044 | MATCH | -3.89 | NOT IN JSON | UNTRACEABLE |
| 0050.TW | +0.00019 | +0.00019 | MATCH | +1.62 | NOT IN JSON | UNTRACEABLE |

**Verdict: 4/4 slopes verified. 0/4 t-statistics verifiable from JSON (t-stats not stored).**

### 2.3 Table A2 (Full Regression) vs K718 -- PARTIAL MATCH

| Asset | Paper alpha | K718 | Paper beta(x10^4) | K718 | Paper Adj R2 | K718 | Paper N | K718 |
|-------|-----------|------|-------------------|------|-------------|------|---------|------|
| SPY | 0.091 | NOT STORED | -2.8 | -2.8 (from slope) MATCH | 0.031 | NOT STORED | 893 | NOT STORED |
| GLD | 0.078 | NOT STORED | -4.3 | -4.3 MATCH | 0.044 | NOT STORED | 893 | NOT STORED |
| TLT | 0.074 | NOT STORED | -4.4 | -4.4 MATCH | 0.039 | NOT STORED | 893 | NOT STORED |
| 0050.TW | 0.062 | NOT STORED | +1.9 | +1.9 MATCH | 0.008 | NOT STORED | 612 | 612 (n_shocks) MATCH |

**Verdict: Slopes match. Intercepts, R2, and N (except 0050) not stored in JSON.**

### 2.4 Table 5 (Shock Types) vs K721 -- ABSORPTION MATCH, N and t-stats UNTRACEABLE

| Shock Type | Paper Absorption | K721 Computed | Match? | Paper N | K721 N | Paper t | K721 t |
|-----------|-----------------|---------------|--------|---------|--------|---------|--------|
| Rate shocks | +0.019 | 0.085-0.066=+0.019 | MATCH | 127 | n_low=23+n_high=56=79 | 2.87 | NOT STORED |
| Risk-off | +0.007 | 0.083-0.076=+0.007 | MATCH | 203 | 38+144=182 | 1.94 | NOT STORED |
| Geopolitical | -0.003 | 0.073-0.076=-0.003 | MATCH | 89 | 29+117=146 | -0.68 | NOT STORED |

**DISCREPANCY (HIGH): Sample sizes in K721 (n_low + n_high) do NOT match paper N.**
- Rate shocks: Paper says N=127, K721 has only 79 (23+56). MISMATCH.
- Risk-off: Paper says N=203, K721 has only 182 (38+144). MISMATCH.
- Geopolitical: Paper says N=89, K721 has only 146 (29+117). Wait -- 146 > 89? This suggests K721's "low" and "high" are different from the paper's full-sample count.

**Interpretation:** K721 JSON stores n_low (calm-regime shock days of that type) and n_high (high-regime shock days), which are subsets used for the absorption calculation. The paper's N column appears to represent the TOTAL number of shock days of each type across ALL regimes, not just the low/high extremes used for the absorption computation. The absorption coefficients themselves are correctly computed from the low/high extremes. However, the total N values (127, 203, 89) cannot be verified from K721 data. The geopolitical total (89) is puzzling because K721 shows 29+117=146 observations in just two bins.

**Assessment:** The absorption coefficients match perfectly. The total N column may represent a different counting methodology (e.g., only negative-return shock days, or after the priority classification filter). This needs replication to verify.

### 2.5 Table 6 (NFP) vs K741 -- DISCREPANCIES FOUND

| Field | Paper | K741 JSON | Match? |
|-------|-------|-----------|--------|
| Total NFP days | 195 | 195 | MATCH |
| Overall ratio | 1.17x | 1.145 (vs all) / 1.165 (vs Friday) | **MISMATCH** |
| Overall p-value | 0.037 | 0.081 (vs all) / 0.061 (vs Friday) | **MISMATCH** |
| Low VIX n | 63 | 62 | **MISMATCH** (off by 1) |
| Low VIX |r| | 0.499% | 0.498% | CLOSE (rounding) |
| Medium VIX n | 76 | 78 | **MISMATCH** (off by 2) |
| Medium VIX |r| | 0.784% | 0.757% | **MISMATCH** |
| Elevated VIX n | 27 | 27 | MATCH |
| Elevated VIX |r| | 1.053% | 1.022% | **MISMATCH** |
| High VIX n | 28 | 28 | MATCH |
| High VIX |r| | 1.523% | 1.488% | **MISMATCH** |

**DISCREPANCIES (HIGH):**
1. **Overall ratio**: Paper reports 1.17x, K741 has 1.145 (vs all non-NFP). The paper's 1.17x matches K741's "vs Friday" ratio (1.165 rounded). The paper's footnote says "Welch's t-test, N_NFP=195" but doesn't specify the comparison group. The paper text appears to use an unspecified comparison, potentially a different computation.
2. **Overall p-value**: Paper reports p=0.037. K741 has p=0.081 (vs all) and p=0.061 (vs Friday). Neither matches 0.037. The Wilcoxon p=0.004 is also different. This is a significant discrepancy.
3. **Regime sample sizes**: Low VIX n differs by 1 (63 vs 62), Medium by 2 (76 vs 78). This suggests the paper may have used a slightly different VIX regime definition or sample period for the NFP analysis.
4. **Regime |r| values**: Systematic small deviations (0.784 vs 0.757, 1.053 vs 1.022, 1.523 vs 1.488) suggest the paper may have used a refined version of the K741 analysis with slightly different parameters.

**Assessment:** The NFP table numbers have systematic deviations from K741. The paper may have been written using a separate (possibly earlier) computation, or the K741 analysis may have used different parameters (e.g., different NFP date identification -- K741 Codex review noted a holiday-date identification bug). The ratios (1.24x, 1.30x, 1.18x, 0.95x) and t-statistics in the paper CANNOT be verified from K741 JSON since K741 does not store per-regime ratios or t-stats.

### 2.6 Table 7 (VRP) vs K720 -- PARTIAL MATCH

Paper reports: Calm +3.5%, Elevated +3.1%, High +2.8%.
K720 JSON: Q1 VRP=+3.5%, Q5 VRP=+2.8%. Only boundary values verifiable.

**Verdict:** Boundary values (3.5%, 2.8%) match K720 knowledge entry. Middle regime (3.1%) and all t-statistics/std devs UNTRACEABLE.

### 2.7 Table 8 (Hedging Cost-Benefit) vs K719 -- PARTIAL MATCH

Paper reports: Calm CB=13.7x, Elevated CB=8.0x, High CB=3.6x.
K719 knowledge entry mentions: "hedging payoff ratio 13.7x -> 3.6x". Values 13.7 and 3.6 match.
K719 JSON has no numerical data beyond experiment citations and qualitative implications.

**Verdict:** 13.7x and 3.6x confirmed from K719 knowledge text. 8.0x UNTRACEABLE.

### 2.8 Tables 9-10 (Robustness) -- FULLY UNTRACEABLE

No experiment JSON exists for the robustness tables (alternative thresholds, sub-periods). All 10 data rows (5 thresholds + 3 sub-periods + controlled regression + RV normalization) are unverifiable.

**Internal consistency check:** Sub-period N totals 378+198+317=893, matching the regression sample N reported elsewhere. This suggests internal consistency but does not confirm correctness.

---

## Summary of Findings

### Verification Scorecard

| Category | Verified | Partially Verified | Untraceable | Discrepancy |
|----------|----------|-------------------|-------------|-------------|
| Table 3 (SAR core) | 20 cells | 0 | 0 | 0 |
| Table 4 (Cross-asset slopes) | 4 | 0 | 4 (t-stats) | 0 |
| Table 5 (Shock types) | 3 (absorption) | 0 | 3 (t-stats) + 3 (N) | N mismatch (see 2.4) |
| Table 6 (NFP) | 3 | 4 (close) | 8 (ratios, t-stats) | 6 (n, |r|, ratio, p) |
| Table 7 (VRP) | 2 | 0 | 7 | 0 |
| Table 8 (Hedge CB) | 2 | 0 | 7 | 0 |
| Tables 9-10 (Robustness) | 0 | 0 | 18 | 0 |
| Table A2 (Full regression) | 4 (slopes) | 1 (N) | 11 | 0 |
| Text claims | 1 (slope) | 0 | 5+ | 0 |
| **TOTAL** | **39** | **5** | **63+** | **6+** |

### Critical Issues

1. **CRITICAL: No replication scripts (.py) for K716-K722.** Only `_results.json` files exist. The 6 core experiments supporting the paper cannot be independently re-run. Only K741 (NFP study) has a script.

2. **HIGH: NFP table (Table 6) has systematic discrepancies with K741.** The overall ratio (1.17x vs 1.145), p-value (0.037 vs 0.081), and regime sample sizes (63 vs 62, 76 vs 78) all differ. The paper may have used a separate, unrecorded computation. Codex Review K741 also flagged a holiday-date identification bug affecting ~5-10 of 195 dates.

3. **HIGH: 63+ numerical claims are untraceable.** The robustness tables (Tables 9-10), t-statistics throughout, VRP details, and several text claims have no corresponding experiment JSON. These numbers may have been generated during the paper-writing process without being recorded in a results file.

4. **MEDIUM: Shock type sample sizes (Table 5 N column) don't match K721.** The paper reports N=127/203/89 for rate/risk-off/geopolitical, but K721 stores n_low+n_high=79/182/146. The N column appears to use a different counting methodology than the absorption computation.

5. **MEDIUM: "Prior work" claims without experiment IDs.** Sections 6.2-6.3 cite VT performance numbers (Sharpe 0.53 vs 0.68, DM t=-2.81; daily 1.42 vs monthly 0.82) as "prior work in our research program (available upon request)" without specifying experiment IDs. These claims should be linked to specific K-numbers.

### Recommendations

1. **Create replication scripts** for K716, K718, K720, K721 (the core experiments). Even retroactively writing scripts that reproduce the JSON results would improve traceability.
2. **Reconcile NFP numbers**: Re-run K741 with the corrected NFP date identification (per Codex review) and update the paper table if numbers change.
3. **Record robustness analysis**: Run the threshold/sub-period/RV-normalization robustness checks as a dedicated experiment (e.g., K_robustness_absorption.py) and save results.
4. **Store t-statistics in experiment JSONs**: Current JSONs lack t-statistics, p-values, and sample sizes for most analyses. Future experiments should store complete statistical output.
5. **Link "prior work" claims**: Identify the specific experiments behind the VT performance numbers and add experiment IDs to the paper or supplementary materials.

---

*Audit performed 2026-04-05 by Claude Code (Opus 4.6)*
