# Paper 3 Reproducibility Audit — Diff Report
**Paper:** "Is Volatility Targeting Just Trend Following?" (vt-trend-following)  
**Audit Date:** 2026-04-17  
**Auditor:** Reproducibility Audit Agent (worktree agent-af2babb1)  
**rtol thresholds:** primary=0.01, strict=0.001

---

## Summary Statistics

| Category | Count |
|---|---|
| Total numbers checked | 74 |
| ✓ Matched (rtol ≤ 0.01) | 47 |
| ≈ Near-match (rtol 0.01–0.02) | 5 |
| ✗ Divergent | 14 |
| ? Cannot verify (no source) | 8 |
| **Coverage** | **74 / ~90 extractable = 82%** |

**Audit score: 47/61 verified = 77% matched** (excluding ? items)

---

## CRITICAL DIVERGENCES (✗)

### D1 — Table 3 Hedged VT Sharpe (BLOCKER)
| | Paper | K898 Script |
|---|---|---|
| SPY Hedged VT Sharpe | 0.737 | 0.848 |
| SPY Hedged VT MDD | −26.9% | −22.5% |
| 50/50 Hedged VT Sharpe | 0.937 | 0.830 |

**Divergence:** 15–22% relative difference.  
**Root cause:** K898 uses daily VIX signal with 1-day lag and no transaction costs; paper text says "monthly rebalancing with lagged weights, 10 bps tx costs." The TSMOM hedge implementation differs — K898 uses daily TSMOM signal while the paper likely uses monthly.  
**Recommendation (a):** Identify which script produced the paper's 0.737 / 0.937 values. K898 appears to use a different TSMOM hedge construction than intended. Add the correct script to `paper/vt-trend-following/experiments/` and verify.  
**Recommendation (b):** If K898 is correct, the paper's Table 3 must be updated. The narrative ("Sharpe drops from 0.797 to 0.737") would change.  
**Recommendation (c):** Note that K898 avg_tsmom_beta=0.318 for SPY is very high — paper uses a rolling 252-day regression which may differ substantially from K898's approach.

---

### D2 — MDD Retention Percentages (BLOCKER)
| Asset | Paper | K898 Script | Bootstrap 5th pctile |
|---|---|---|---|
| SPY | 93% | 107% | 95% |
| 50/50 | 96% | 110% | 78% |
| DIA | 91% | 104% | 88% |
| QQQ | 90% | 120% | 93% |
| IWM | 97% | 115% | 90% |

**Divergence:** All assets show K898 retention >100% (hedged VT has BETTER MDD than VT), while paper claims 90–97%.  
**Root cause:** Same as D1 — the TSMOM hedge construction differs. In K898, hedging TSMOM actually IMPROVES MDD, while the paper claims partial MDD degradation after hedging. The paper's paper_comparison field stores the claimed 90–97% values, suggesting these come from a different run than K898.  
**Note:** The K898 `bootstrap_mdd_retention` correctly found that SPY CI lower bound is 95%, not 86% as paper claims in review. The bootstrap methodology itself differs.  
**Recommendation (a):** Find the original script that computed the 93% / 96% / 91% / 90% / 97% values. It may be a different experiment not stored in `paper/vt-trend-following/experiments/`.  
**Recommendation (b):** If K898 is the authoritative script, the paper must be updated — the core claim (90–97% MDD retention) is the paper's PRIMARY contribution and the numbers have changed materially.

---

### D3 — Table 3 Pure TSMOM Metrics (MAJOR)
| | Paper | K898 Script |
|---|---|---|
| SPY Pure TSMOM Sharpe | 0.172 | 0.242 |
| SPY Pure TSMOM MDD | −27.5% | −51.4% |

**Divergence:** Large (41% Sharpe, 87% MDD).  
**Root cause:** Pure TSMOM construction differs. K898's TSMOM uses daily 252-day sign-of-return signal and likely has different scaling. Paper's 0.172 may use standardized vol-scaled TSMOM.  
**Recommendation (a):** Clarify TSMOM normalization — is Pure TSMOM signal ±1 (unscaled) or vol-scaled? K898 note `avg_tsmom_beta=0.318` suggests unnormalized. The paper's method (Section 2.5) uses rolling 252-day OLS hedge which should produce consistent results.

---

### D4 — Table 3 Sharpe Lost to TSMOM (MAJOR)
| | Paper | K898 Script |
|---|---|---|
| SPY TSMOM contribution | −0.060 (32% reduction) | −0.043 (−22.8%) |

**Divergence:** K898 shows TSMOM hedge HELPS (negative % = improvement), while paper shows TSMOM hedge HURTS (−0.060 reduction). Sign reversal in narrative.  
**Root cause:** Same as D1/D2. The entire decomposition in K898 shows an inverted relationship to what the paper claims, driven by the TSMOM hedge producing better (not worse) performance.  
**Recommendation (a):** This is the same root cause as D1–D3. Resolving D1 will resolve D4.

---

### D5 — International Table 5 Average MDD Improvement (BLOCKER)
| | Paper Table 5 | K901 Experiment |
|---|---|---|
| Average ΔMDDpp | 28.7 pp | ~17.3 pp |
| Developed mkt avg | 32.0 pp | ~26.0 pp |
| Emerging mkt avg | 24.7 pp | ~13.7 pp |
| t=15.70 | reported | NOT FOUND in K901 |
| r=−0.770 (VIX sens) | reported | NOT FOUND in K901 |
| GJR γ vs ΔSharpe ρ=0.830 | reported | NOT FOUND in K901 |

**Root cause:** K901 uses a different 13-market set (EWH, EWY, EWY instead of EWC, VGK, MCHI). The paper's Table 5 asset list does not match K901's asset list. There is NO experiment in `paper/vt-trend-following/experiments/` that reproduces Table 5 with the paper's exact assets.  
**Recommendation (a):** The paper claims Table 5 results but the matching script is missing. A new experiment must be run with exactly {EFA, EWJ, EWG, EWU, EWA, EWC, VGK, EEM, FXI, EWZ, INDA, EWT, MCHI} over Jan 2007–Mar 2026. r=−0.770, t=15.70, ρ=0.830 cannot be verified without this script.  
**Recommendation (b):** This is a BLOCKER for submission — the international section's main claims have no reproducible experiment.

---

### D6 — Table 4 M5 N=3740 vs N=5049 (HIGH — carries over from review_v2 B.2)
| | Paper | K54 Experiment |
|---|---|---|
| M5 N | 3,740 | 5,049 |
| BAB proxy | SPLV−SPHB (post-2011) | IWD-QQQ (pre-2011) + SPLV-SPHB |

**Divergence:** Paper says M5 uses "post-2011 subsample N=3,740" but K54 uses full sample N=5,049 via an IWD-QQQ hybrid proxy pre-2011.  
**Root cause:** K54 constructed a full-sample BAB proxy using IWD (Value/Defensive) minus QQQ (Growth/Aggressive) pre-2011 spliced with SPLV-SPHB post-2011. Paper Table 4 notes describe only the SPLV-SPHB ETF proxy.  
**Impact:** The AIC numbers and all M5 coefficients are based on N=5049, but the paper claims N=3740. This creates a false comparison issue (review_v2 B.2 HIGH).  
**Recommendation (a):** Reconcile — either use AQR BAB factor (full sample, no truncation) or honestly report which N was used. Current state: paper claims N=3740 but script uses N=5049.

---

### D7 — "1.4% TSMOM contribution to Sharpe" (HIGH — review_v2 C.1)
**Paper claim:** "TSMOM contribution to Sharpe improvement is approximately 1.4% of total strategy Sharpe"  
**From experiment:** Using K898 numbers: if contribution = 0.060/0.797 = 7.5%, or 0.060/4.237 (portfolio total return?) = ???  
**No experiment produces this number.** The review_v2 already flagged this.  
**Recommendation (a):** Show derivation explicitly. If 1.4% = (0.060/0.797)×(VT_vol/SPY_vol) or some scaled version, explain. If the number is wrong, correct it.  
**Recommendation (b):** This is a frequently cited number in the paper; an unexplained statistic in the central argument will be caught by reviewers.

---

### D8 — Table 5 VIX Sensitivity column values
The paper Table 5 shows VIX sensitivity values (e.g., EFA=−0.653, EWJ=−0.575). These cannot be verified from K901 which doesn't report VIX sensitivity per market in the same format.  
**Status:** ? (unverifiable without the matching script)

---

## MINOR DIVERGENCES (≈)

| Location | Paper | Script | Diff | Status |
|---|---|---|---|---|
| Table 3 SPY B&H Sharpe | 0.611 | 0.616 | +0.8% | ≈ |
| Table 3 50/50 B&H Sharpe | 0.865 | 0.878 | +1.5% | ≈ |
| Table 3 50/50 VT Sharpe | 0.982 | 0.998 | +1.6% | ≈ |
| Table 3 50/50 Hedged MDD | −13.1% | −13.3% | +1.5% | ≈ |
| Table 3 Delta Sharpe (SPY) | +0.186 | +0.189 | +1.6% | ≈ |

These small differences (1–2%) likely reflect: (a) different sample start dates (paper claims 2005–2026, K898 starts 2005-01-03), (b) minor differences in SHY cash proxy treatment, (c) rounding.

---

## CONFIRMED MATCHES (✓) — Key Numbers

**Table 1 (N=22 alpha decomposition):** All individual asset values (gamma, M1 alpha, M1 t, M1 R2, M2 beta, M2 t, M2 R2, delta_alpha) match K55 results to 3 significant figures. Coverage 22/22 assets for key columns.

**Table 2 (Cross-sectional):** r=0.564, p=0.006, Spearman rho=0.544, CI=[0.263,0.772], gamma1=0.568, t=3.06, R2=0.319, Welch t=1.98 all confirmed from K55.

**Table 4 (FF5 M1–M5):** All alpha values, t-stats, factor loadings for M1–M4 confirmed from K54. M5 also confirmed except for the N discrepancy.

**Discussion section numbers:** 427 configs (K568 ✓), daily breakeven 3.4 bps (K499 ✓), monthly breakeven 14.9 bps (K499 ✓), 5 TF strategies all fail Harvey t>3.0 (K518 ✓).

**VIX predictive power:** r=0.570 (vol magnitude), r=0.042 (direction) confirmed from K697 — but K697 is NOT cited in main.tex, only in review_v2.

---

## 5 HIGH ISSUES FROM review_v2 — CURRENT STATUS

### H1 (v2 B.1): Sample period inconsistency (2005 vs 2007 vs 1998)
**Status: PENDING (unresolved)**  
Table 3 notes say "2005–2026"; Table 4 notes say "January 2005–March 2026"; Data section says "January 2007 to March 2026"; K898 data start "2005-01-03". K55 data start "2007-01-01".  
Table 1 uses 2007 start (K55), Table 3 uses 2005 start (K898), Table 4 uses 2005 start (K54). Inconsistency confirmed and unresolved.

### H2 (v2 B.2): BAB proxy SPLV-SPHB causes N=3740 sample truncation
**Status: DIVERGENT — paper claims N=3740 but experiment K54 runs N=5049**  
The paper notes the truncation but the experiment doesn't actually implement the truncation. Either the paper's note is wrong (script uses full sample) or a different unreported script created Table 4 M5.

### H3 (v2 B.3): MDD retention reported for only 5 highly correlated US equity assets
**Status: PENDING (unresolved)**  
No extension to non-equity assets (GLD, TLT, EEM, etc.) in any experiment file.

### H4 (v2 C.1): "1.4% TSMOM contribution" derivation missing and potentially incorrect
**Status: BLOCKER — no experiment produces this number**  
From K898: Sharpe lost = 0.043 (SPY), Sharpe VT = 0.805. That's 5.3%, not 1.4%.  
From K898 50/50: Sharpe lost could even be negative (TSMOM hedge helps Sharpe).  
The 1.4% claim is unverifiable and likely incorrect.

### H5 (v2 A.1): K687/K697/K688 not cited/reconciled
**Status: PENDING**  
K687 shows BH 50/50 (Sharpe=0.545) beats 12/VIX (Sharpe=0.438) after lag correction on SPY+GLD universe. Paper Table 3 shows VT Sharpe 0.982 vs BH 0.865 for 50/50. These are fundamentally different results because K687 evaluates on 50/50 as a whole (VT applied to the 50/50 blend), while the paper evaluates VT on each asset separately then blends.  
K688 CRRA: 12/VIX does NOT win at any gamma for the 50/50 blend; EWMA VT wins at gamma≥5. Paper's Cederburg rebuttal needs to acknowledge this.  
K697 direction vs magnitude finding (corr=0.57 vol, 0.04 direction) is directly relevant to Section 4.2 but not cited.

---

## MISSING EXPERIMENTS (Cannot Verify)

1. **Table 5 core numbers** (r=−0.770, t=15.70, ρ=0.830, average 28.7pp): No matching script with paper's exact 13-market set.
2. **Sector analysis** (Section 3.4, r=0.163, gamma range [0.077,0.160]): No sector experiment found in `paper/vt-trend-following/experiments/`.
3. **Sub-period stability** (Section 3.6, COVID Sharpe 1.295 vs 1.254): No sub-period experiment found.
4. **VIX threshold sensitivity** in main text (t-stats 7.98–10.91): Found in paper3_fixes.json but asset=SPY only, consistent.
5. **Bootstrap CI for MDD retention** (paper claims [86,97] for SPY): K898 reports different CI [95,172], indicating different bootstrap methodology.
