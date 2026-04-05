# Paper 5 Audit: Steps 1-2 (Experiment Linking & Number Verification)

**Paper**: "When Volatility Targeting Crowds: Quantifying the Tipping Point via Agent-Based Simulation"
**Auditor**: Claude Opus 4.6 (1M context)
**Date**: 2026-04-05

---

## Step 1: Experiment Linking

### Experiments Available

| Experiment | Description | Sims | Design |
|-----------|-------------|------|--------|
| **K827** | Original ABM VT crowding | 100 | Scaled liquidity (noise traders reduced with VT adoption) |
| **K827v2** | Sensitivity analysis + 500 sims | 500 main + 200 sensitivity | Scaled liquidity |
| **K827v3** | Fixed liquidity (critical fix) | 500 main + 200 sensitivity | **Fixed** noise traders (N=200 constant) |
| **K864** | Heterogeneous ABM extension | 200 | Fixed liquidity, 4 strategy types |

### Paper's Design Choice

The paper uses the **fixed-liquidity design** (N_noise = 200 constant), which corresponds to **K827v3**. This is explicitly stated in Section 2.1 and the design validation (Section 3.5). K864 is a follow-up not used in the paper.

---

## Step 2: Number Traceability Table

### Table 1 (VT Strategy and Market Outcomes by Adoption Level)

**Source: K827v3 `part1_results`** (500 sims, 2000 bootstrap)

| phi | Metric | Paper Value | K827v3 Value | Match? |
|-----|--------|------------|-------------|--------|
| 0% | Kurtosis | -0.00 | -0.0027 | OK (rounds to -0.00) |
| 0% | Kurt CI | [-0.01, 0.01] | [-0.0115, 0.0058] | OK |
| 0% | Flash/yr | 0.32 | 0.3229 | OK |
| 10% | Sharpe | 0.47 | 0.4675 | OK |
| 10% | CI | [0.44, 0.50] | [0.4397, 0.4958] | OK |
| 10% | Ret (%) | 4.69 | 4.6886 | OK |
| 10% | dVol (%) | -0.1 | -0.05 | OK (rounds to -0.1) |
| 10% | Kurtosis | -0.01 | -0.0128 | OK |
| 10% | Kurt CI | [-0.02, -0.00] | [-0.0217, -0.0045] | OK |
| 10% | Flash/yr | 0.30 | 0.2967 | OK |
| 20% | Sharpe | 0.50 | 0.4956 | OK |
| 20% | CI | [0.47, 0.52] | [0.4705, 0.5216] | OK |
| 20% | dSharpe | +6% | +6.0% | OK |
| 20% | Ret (%) | 4.98 | 4.9809 | OK |
| 20% | dVol (%) | +0.8 | +0.76 | OK |
| 20% | Kurtosis | 0.00 | 0.0028 | OK |
| 20% | Kurt CI | [-0.01, 0.01] | [-0.0057, 0.0114] | OK |
| 20% | Flash/yr | 0.31 | 0.3101 | OK |
| 30% | Sharpe | 0.47 | 0.4664 | OK |
| 30% | CI | [0.44, 0.50] | [0.4391, 0.4950] | OK |
| 30% | dSharpe | -0% | -0.22% | OK |
| 30% | Ret (%) | 4.74 | 4.7358 | OK |
| 30% | dVol (%) | +3.8 | +3.75 | OK |
| 30% | Kurtosis | -0.00 | -0.0037 | OK |
| 30% | Kurt CI | [-0.01, 0.00] | [-0.0112, 0.0045] | OK |
| 30% | Flash/yr | 0.31 | 0.3061 | OK |
| 50% | Sharpe | 0.34 | 0.3357 | OK |
| 50% | CI | [0.31, 0.36] | [0.3128, 0.3583] | OK |
| 50% | dSharpe | -28% | -28.2% | OK |
| 50% | Ret (%) | 3.46 | 3.4566 | OK |
| 50% | dVol (%) | +18.8 | +18.75 | OK |
| 50% | Kurtosis | 0.06 | 0.0563 | OK |
| 50% | Kurt CI | [0.05, 0.07] | [0.0455, 0.0666] | OK |
| 50% | Flash/yr | 0.40 | 0.4030 | OK |
| 70% | Sharpe | 0.08 | 0.0844 | OK |
| 70% | CI | [0.07, 0.10] | [0.0664, 0.1022] | OK |
| 70% | dSharpe | -82% | -81.95% | OK |
| 70% | Ret (%) | 0.90 | 0.8952 | OK |
| 70% | dVol (%) | +42.7 | +42.66 | OK |
| 70% | Kurtosis | 1.41 | 1.4121 | OK |
| 70% | Kurt CI | [1.28, 1.55] | [1.2770, 1.5530] | OK |
| 70% | Flash/yr | 1.09 | 1.0868 | OK |
| 100% | Sharpe | -0.27 | -0.2670 | OK |
| 100% | CI | [-0.28, -0.26] | [-0.2783, -0.2557] | OK |
| 100% | dSharpe | -157% | -157.1% | OK |
| 100% | Ret (%) | -3.82 | -3.8159 | OK |
| 100% | dVol (%) | +119.1 | +119.05 | **MINOR**: rounds to +119.0, paper says 119.1 |
| 100% | Kurtosis | 61.4 | 61.3526 | **MINOR**: rounds to 61.35, paper says 61.4 |
| 100% | Kurt CI | [59.2, 63.4] | [59.20, 63.42] | OK |
| 100% | Flash/yr | 1.20 | 1.1991 | OK |

**Table 1 Summary**: 48 values checked. 46 exact match, 2 minor rounding differences (100% dVol and Kurtosis).

---

### Table 2 (Market Microstructure Effects)

**Source: K827v3 `part1_results`** (500 sims)

| phi | Metric | Paper Value | K827v3 Value | Match? |
|-----|--------|------------|-------------|--------|
| 0% | Ann Vol | 16.0% | 16.01% | OK |
| 0% | VIX Mean | 19.4 | 19.41 | OK |
| 0% | VIX Std | 1.76 | 1.760 | OK |
| 0% | Skewness | -0.005 | -0.00516 | OK |
| 0% | MDD | -33.4% | -33.40% | OK |
| 0% | VIX Spike | 0.0 | 0.0007 | OK |
| 10% | Ann Vol | 16.0% | 16.01% | OK |
| 10% | VIX Mean | 19.4 | 19.40 | OK |
| 10% | VIX Std | 1.76 | 1.761 | OK |
| 10% | Skewness | 0.001 | 0.000486 | **MINOR**: rounds to 0.000, paper says 0.001 |
| 10% | MDD | -34.2% | -34.17% | OK |
| 10% | VIX Spike | 0.0 | 0.0002 | OK |
| 20% | Ann Vol | 16.1% | 16.14% | OK |
| 20% | VIX Mean | 19.5 | 19.53 | OK |
| 20% | VIX Std | 1.77 | 1.774 | OK |
| 20% | Skewness | -0.002 | -0.00224 | OK |
| 20% | MDD | -33.2% | -33.20% | OK |
| 20% | VIX Spike | 0.0 | 0.0022 | OK |
| 30% | Ann Vol | 16.6% | 16.61% | OK |
| 30% | VIX Mean | 20.0 | 19.96 | OK |
| 30% | VIX Std | 1.89 | 1.888 | OK |
| 30% | Skewness | 0.002 | 0.00161 | OK |
| 30% | MDD | -34.9% | -34.88% | OK |
| 30% | VIX Spike | 0.0 | 0.0047 | OK |
| 50% | Ann Vol | 19.0% | 19.02% | OK |
| 50% | VIX Mean | 22.8 | 22.82 | OK |
| 50% | VIX Std | 2.33 | 2.331 | OK |
| 50% | Skewness | -0.024 | -0.02374 | OK |
| 50% | MDD | -40.2% | -40.25% | OK |
| 50% | VIX Spike | 0.3 | 0.3411 | OK (1dp rounds to 0.3) |
| 70% | Ann Vol | 22.8% | 22.85% | OK |
| 70% | VIX Mean | 27.4 | 27.37 | OK |
| 70% | VIX Std | 3.39 | 3.390 | OK |
| 70% | Skewness | -0.321 | -0.32062 | OK |
| 70% | MDD | -60.1% | -60.09% | OK |
| 70% | VIX Spike | 16.2 | 16.158 | OK |
| 100% | Ann Vol | 35.1% | 35.08% | OK |
| 100% | VIX Mean | 35.0 | 34.96 | OK |
| 100% | VIX Std | 6.45 | 6.452 | OK |
| 100% | Skewness | -4.73 | -4.7344 | **MINOR**: rounds to -4.73 at 2dp (OK) |
| 100% | MDD | -91.3% | -91.31% | OK |
| 100% | VIX Spike | 90.0 | 90.025 | OK |

**Table 2 Summary**: 42 values checked. 40 exact match, 2 minor rounding issues (10% skewness, 100% skewness).

---

### Table 3 (Sensitivity of VT Tipping Point)

**Source: K827v3 `part2_sensitivity`** (200 sims per cell)

| Parameter | Value | Sharpe_10 Paper | Sharpe_10 Data | Sharpe_30 Paper | Sharpe_30 Data | Sharpe_50 Paper | Sharpe_50 Data | Threshold Paper | Threshold Data | Match? |
|-----------|-------|----------------|---------------|----------------|---------------|----------------|---------------|-----------------|---------------|--------|
| lambda | 0.0025 (-50%) | 0.52 | 0.5172 | 0.49 | 0.4879 | 0.43 | 0.4334 | >50% | >50% | OK |
| lambda | 0.005 (base) | 0.49 | 0.4874 | 0.45 | 0.4541 | 0.35 | 0.3486 | >50% | >50% | OK |
| lambda | 0.0075 (+50%) | 0.52 | 0.5152 | 0.40 | 0.4015 | 0.23 | 0.2269 | 30-50% | 30-50% | OK |
| gamma | 100 (-50%) | 0.47 | 0.4713 | 0.51 | 0.5105 | 0.36 | 0.3605 | >50% | >50% | OK |
| gamma | 200 (base) | 0.52 | 0.5156 | 0.47 | 0.4656 | 0.32 | 0.3208 | >50% | >50% | OK |
| gamma | 300 (+50%) | 0.48 | 0.4813 | 0.41 | 0.4096 | 0.31 | 0.3134 | >50% | >50% | OK |
| kappa | 0.015 (-50%) | 0.45 | 0.4517 | 0.48 | 0.4807 | 0.32 | 0.3195 | >50% | >50% | OK |
| kappa | 0.03 (base) | 0.49 | 0.4879 | 0.47 | 0.4658 | 0.34 | 0.3364 | >50% | >50% | OK |
| kappa | 0.045 (+50%) | 0.51 | 0.5098 | 0.44 | 0.4415 | 0.32 | 0.3184 | >50% | >50% | OK |

**Table 3 Summary**: All 36 values match. All 9 threshold classifications correct (under paper's stated 50%-degradation criterion).

**Note**: The stored `threshold_stability` in the K827v3 JSON used a different (30% degradation) criterion, producing only 4/9 ">50%". The paper's stated criterion (footnote c: "degradation first exceeds 50%") gives the correct 8/9 count.

---

### Section 3.3 (Statistical Significance) -- Inline Numbers

**Source: Paper claims K827v3 (fixed liquidity), but t-values match K827v2 (scaled liquidity)**

| Claim | Paper Value | K827v3 (correct) | K827v2 (wrong source) | Match? |
|-------|------------|-----------------|----------------------|--------|
| t-stat (10% vs 30%) | 3.64 | **0.05** | 3.637 | **CRITICAL MISMATCH** |
| p-value (10% vs 30%) | <0.001 | **0.96** | 0.00029 | **CRITICAL MISMATCH** |
| t-stat (50% vs 10%) | 17.82 | **7.12** | 17.816 | **CRITICAL MISMATCH** |
| p-value (50% vs 10%) | <0.001 | <0.001 | <0.001 | OK (both significant) |
| Sharpe "0.47 vs 0.47" (10% vs 30%) | 0.47 vs 0.47 | 0.47 vs 0.47 | 0.50 vs 0.43 | OK (K827v3 values) |

**This is the most serious error in the paper.** The t-test values in Section 3.3 are from K827v2 (scaled liquidity, the **rejected** design), not K827v3 (fixed liquidity, the paper's stated design). The consequences:

1. **10% vs 30%**: Paper claims t=3.64 (significant, "marginally exceeding Harvey threshold"). Actual K827v3: t=0.05 (completely non-significant, p=0.96). The claim about exceeding the Harvey (2016) t>3.0 threshold is **false** for the fixed-liquidity design.
2. **50% vs 10%**: Paper claims t=17.82. Actual K827v3: t=7.12. Still highly significant (p<0.001), but the magnitude is wrong by 2.5x.
3. **Narrative impact**: The paper argues that the 10%-30% difference "marginally exceeds the Harvey threshold" -- this is wrong. Under fixed liquidity, 10% and 30% are statistically *indistinguishable* (t=0.05). Ironically, this *strengthens* the paper's main claim that VT is stable below 30%, but the statistical text is incorrect.

---

### Section 3.4 (Sensitivity Analysis) -- Inline Numbers

| Claim | Paper Value | K827v3 Value | Match? |
|-------|------------|-------------|--------|
| Lambda spread at phi=50% | 0.21 (0.43 to 0.23) | 0.2065 (0.43 to 0.23) | OK |
| Gamma spread at phi=50% | 0.05 | 0.0471 | OK (rounds to 0.05) |
| Kappa spread at phi=50% | 0.02 | 0.0180 | OK (rounds to 0.02) |
| Combos with threshold >50% | 8 of 9 | 8 of 9 | OK (under 50% criterion) |
| Only high-lambda below 50% | lambda +50% | lambda 0.0075 | OK |

---

### Section 3.5 (Design Validation) -- Inline Numbers

**Source: K827v3 `analysis.v2_comparison`** (comparing K827v2 vs K827v3)

| Claim | Paper Value | Data Value | Match? |
|-------|------------|-----------|--------|
| Scaled: 30% Sharpe | 0.43 | 0.4308 | OK |
| Scaled: 50% Sharpe | 0.18 | 0.1801 | OK |
| Fixed: 30% Sharpe | 0.47 | 0.4664 | OK |
| Fixed: 50% Sharpe | 0.34 | 0.3357 | OK |
| Fixed: 70% Sharpe | 0.08 | 0.0844 | OK |

---

### Abstract & Conclusion -- Inline Numbers

| Claim | Paper Value | K827v3 Value | Match? |
|-------|------------|-------------|--------|
| Stable up to 30% (Sharpe~0.47) | ~0.47 | 0.4664 | OK |
| 50% Sharpe~0.34, 28% decline | ~0.34, 28% | 0.3357, 28.2% | OK |
| 70% Sharpe~0.08, 82% decline | ~0.08, 82% | 0.0844, 82.0% | OK |
| 100% Sharpe = -0.27 | -0.27 | -0.2670 | OK |
| 100% kurtosis ~61 | ~61 | 61.35 | OK |
| 70% kurtosis ~1.4 | ~1.4 | 1.41 | OK |
| Skewness at 70%: -0.32 | -0.32 | -0.321 | OK |
| Skewness at 100%: -4.7 | -4.7 | -4.734 | OK |
| 500 Monte Carlo simulations | 500 | 500 (n_sims_main) | OK |
| 2,520 days | 2,520 | 2520 (n_days) | OK |
| N = 1,000 agents | 1,000 | 1000 (n_agents) | OK |
| N_noise = 200 fixed | 200 | 200 (n_noise_fixed) | OK |
| VIX spike at 70%: 16% | 16% | 16.16% | OK |
| VIX spike at 100%: 90% | 90% | 90.02% | OK |
| Annualized vol at 100%: 35% | 35% | 35.08% | OK |
| Vol amplification at 50%: +19% | +19% | +18.75% | OK |
| Vol amplification at 100%: +119% | +119% | +119.05% | OK |

---

### Model Parameters (Section 2.2)

| Parameter | Paper Value | K827v3 Config | Match? |
|-----------|------------|--------------|--------|
| mu (drift) | 0.08/252 | Not explicit in JSON | Assumed correct (standard) |
| lambda (Kyle) | 0.005 | kyle_lambda: 0.005 | OK |
| sigma_f | 0.16/sqrt(252) | fundamental_vol_annual: 0.16 (K827) | OK |
| kappa | 0.03 | vix_mr_speed: 0.03 | OK |
| V_bar | 18 | vix_long_run_mean: 18.0 (K827) | OK |
| gamma | 200 | vix_vol_sensitivity: 200.0 | OK |
| eta std | 0.3 | Not explicit in config | Assumed correct |
| VIX bounds | [9, 80] | Not explicit in config | Assumed correct |
| Bootstrap | 2,000 | n_bootstrap: 2000 | OK |
| VT cap | 1.5 | vt_cap: 1.5 (K827) | OK |

---

## Summary of Discrepancies

### CRITICAL (Must Fix Before Submission)

**1. Section 3.3 t-test values from wrong experiment (K827v2 instead of K827v3)**

The paper's statistical significance section uses t-values from K827v2 (scaled liquidity, the **rejected** design) while the paper's results are from K827v3 (fixed liquidity). Specific errors:

- **10% vs 30%**: Paper says t=3.64 (p<0.001, significant). K827v3 actual: **t=0.05, p=0.96 (NOT significant)**. The claim about marginally exceeding the Harvey (2016) t>3.0 threshold is **false**.
- **50% vs 10%**: Paper says t=17.82. K827v3 actual: **t=7.12**. Still significant (p<0.001), but magnitude is 2.5x off.

**Recommendation**: Rewrite Section 3.3 entirely using K827v3 values. The corrected narrative is actually *stronger* for the paper's thesis: the 10%-30% difference is statistically indistinguishable (t=0.05), confirming VT is truly stable below 30%. The 50% degradation is still highly significant (t=7.12), confirming the tipping point.

### MODERATE (Should Fix)

**2. "27 parameter combinations" terminology**

Section 2.4 says "a 3x3x3 sensitivity grid" producing "27 parameter combinations". The actual design is one-at-a-time (OAT): 3 parameters, each varied at 3 levels while others are held at baseline = 9 unique parameter settings, tested at 3 adoption levels = 27 cells. "3x3x3" misleadingly implies a full factorial design (27 unique parameter combinations). Table 3 footnote correctly says "varies one parameter" but the text contradicts this.

**Recommendation**: Change "27 parameter combinations" to "9 parameter variations tested at 3 adoption levels (27 cells total)" and clarify that the design is one-at-a-time, not full factorial.

### MINOR (Cosmetic)

**3. Table 1, 100% dVol**: Paper says +119.1%, data rounds to +119.0% (raw: 119.046).

**4. Table 1, 100% Kurtosis**: Paper says 61.4, data rounds to 61.35 (raw: 61.353).

**5. Table 2, 10% Skewness**: Paper says 0.001, data is 0.000486 which rounds to 0.000 at 3dp (or 0.0 at 1dp). The paper's 0.001 rounds *up* from 0.000486.

**6. Table 2, 100% Skewness**: Paper says -4.73, data is -4.734. Consistent if rounded to 2dp (-4.73) rather than 3dp (-4.734).

---

## Traceability Matrix

| Paper Section | Numbers From | Experiment | Verified? |
|--------------|-------------|------------|-----------|
| Abstract | Sharpe, kurtosis, adoption levels | K827v3 part1 | YES |
| Table 1 | All strategy performance metrics | K827v3 part1 | YES (48/48) |
| Table 2 | All market microstructure metrics | K827v3 part1 | YES (42/42) |
| Table 3 | All sensitivity Sharpe values | K827v3 part2 | YES (27/27) |
| Table 3 | Threshold classifications | K827v3 part2 (recomputed) | YES (9/9) |
| Section 3.3 | **t-test values** | **K827v2** (WRONG!) | **NO** |
| Section 3.4 | Spread values, threshold count | K827v3 part2 analysis | YES |
| Section 3.5 | Design validation comparison | K827v3 v2_comparison | YES |
| Conclusion | Summary statistics | K827v3 part1 | YES |
| K864 | Not used in paper | N/A | N/A |
