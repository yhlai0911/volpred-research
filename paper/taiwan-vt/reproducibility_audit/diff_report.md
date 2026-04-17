# Paper 2 (Taiwan VT) Reproducibility Audit — Diff Report

**Audit Date**: 2026-04-17  
**Auditor**: Claude Sonnet 4.6 (worktree agent-a6be0705)  
**Target**: `paper/taiwan-vt/main.tex` + `paper/taiwan-vt/body.tex`  
**Available Experiments**: K461, K553, K558, K844, K847, K848, K849, K850, K851, K852, K852b, K853, K854, K886, K892, K896, K900  
**Tolerance**: rtol=0.01 point estimates, rtol=0.001 test stats

---

## Summary Statistics

| Category | Count |
|---|---|
| Total numbers extracted from paper | 82 |
| Matched (✓ or ≈) | 14 |
| Approximate match (≈ within rtol) | 8 |
| Divergent (✗) | 18 |
| No source found (?) | 42 |
| **Coverage (has-source)** | **49% (40/82)** |
| **Matched among sourced** | **55% (22/40)** |

---

## TOP 5 DIVERGENCES (Ranked by Severity)

### DIV-1: Table 3 (VT Performance) — Sample Period Mismatch (BLOCKER)

**Severity**: BLOCKER  
**Paper claims**: Buy & Hold Sharpe=0.729, MDD=-41.3%, Ann Return=10.2%, Vol=20.8% over 2010–2026  
**K900 (closest source)**: Buy & Hold Sharpe=1.247, MDD=-33.83%, Ann Return=25.97%, Vol=20.83% over 2019–2026  
**K558 (2010–2026)**: base Sharpe=0.472, MDD=-48.38%

**Root cause**: No single experiment JSON covers the 2010–2026 period with the exact Table 3 strategy set (Buy&Hold, EWMA VT, GARCH VT, GJR VT). K900 uses 2019–2026 OOS; K558 only covers 8.63/VIX base and hybrid variants. The paper's Table 3 numbers are internally consistent and plausible for 2010–2026, but no backing JSON exists for this period with all strategies.

**Recommendation**: (a) Run a new experiment covering 2010–2026 with all Table 3 strategies and save results JSON; update K900 to also cover 2010–2026 period, or (b) Update Table 3 caption to clarify exact periods match K900 OOS (2019–2026) and update all Sharpe/MDD figures accordingly.

---

### DIV-2: VaR Violation Count — Student-t vs. Cornish-Fisher Confusion (MAJOR)

**Severity**: MAJOR  
**Paper claims** (body.tex line 463): "8 violations (0.5%)" for GJR-GARCH + Student-t(5) over 2020–2026 (1,501 days). "Normal distribution produces 30 violations (2.0%)."  
**K896 (2019–2026, n=1,756)**: GJR+Student-t = 18 violations (1.03%, Kupiec p=0.916); GJR+CF = 9 violations (0.51%); GJR+Normal = 30 violations (1.71%).  
**Analysis**: The Normal violation count (30) matches K896 exactly. The 0.5%/8-violation claim matches GJR+CF (9 violations ≈ 0.51%), NOT GJR+Student-t. Either the paper mis-labels CF as Student-t, OR the 2020–2026 sub-period (shorter than K896's 2019–2026) produces fewer violations. The Kupiec p=0.12 in paper does NOT match K896's GJR+Student-t p=0.916 — this is a critical mismatch.

**Recommendation**: (a) Identify which distribution actually produces 8 violations; likely GJR+CF on the 2020–2026 sub-period. Update paper to correctly attribute. Run K896 restricted to 2020–2026.

---

### DIV-3: 0050.TW Descriptive Statistics — Skewness Sign Flip and Kurtosis (MAJOR)

**Severity**: MAJOR  
**Paper (Table 1)**: 0050.TW skewness = −0.47, kurtosis = 4.73  
**K900 (2009–2026)**: skewness = +0.473, kurtosis = 19.054  
**Analysis**: The skewness sign is flipped (+0.473 vs. −0.47), and kurtosis is dramatically different (19.054 vs. 4.73). The K900 period starts 2009 vs. paper's 2008 (minor sample difference), but neither explains the sign flip. The paper kurtosis of 4.73 suggests moderate fat tails, while K900's 19 is consistent with heavy tails from extreme events. This likely reflects a different return computation (e.g., raw returns vs. percentage returns) or sample period. Paper claims 4,532 trading days; K892/K900 show 4,217–4,219 days — a discrepancy of ~313 days (~15 months).

**Recommendation**: (a) Reconcile the return computation (raw log-return vs. ×100 pct-return). The kurtosis difference may be a scaling artifact — but sign flip cannot be. Verify sample boundaries (January 2008 exact start date) and recalculate. K900 descriptive stats likely computed on raw returns; paper may have used a different period or pre-split data.

---

### DIV-4: 0050.TW GJR-GARCH Gamma — Unresolved Conflict (MAJOR)

**Severity**: MAJOR  
**Paper (Tables 1 & 2)**: 0050.TW gamma = 0.087, t = 2.20  
**K892 analysis**: Full sample gives gamma=0.097, t=3.60; Last 2000-day rolling window gives gamma=0.136, t=2.19. The t=2.20 matches the last rolling window, but gamma=0.087 does not match any configuration (closest full-sample is 0.097; closest to t=2.20 is gamma=0.136).  
**K892 conclusion**: K892 explicitly flags this as unresolved — the paper value 0.087 is not reproduced by any configuration tested.

**Recommendation**: (a) Re-examine the exact estimation period and window used. The paper states "rolling window w=2000" — but K892 shows the last w=2000 window gives gamma=0.136, not 0.087. Check if the paper used a different data vendor, different split adjustment, or different estimation period ending date. (b) If 0.087 cannot be reproduced, update Tables 1 & 2 to 0.097 (full sample) or 0.136 (rolling), and adjust t-stat accordingly.

---

### DIV-5: Time-Zone Table (Table 4) — No Backing JSON Exists (BLOCKER)

**Severity**: BLOCKER  
**Paper (Table 4)**: Taiwan TZ momentum Sharpe (c2c)=1.473, (o2o)=0.87, t-stat=2.22, MDD=-12.8%, period 2012–2025; Japan c2c=1.306; Six-market t-stats (HK=4.12, AU=4.04, SG=4.03, KR=3.83, TW=3.76, JP=3.69); TW+JP 50/50 Sharpe=1.810; Global composite=1.610.  
**K experiments**: No experiment in `paper/taiwan-vt/experiments/` provides these numbers. K847 provides overnight gap decomposition (SPY-conditional gap analysis) but NOT the time-zone strategy performance. K844 provides futures vs stock VT but not multi-market TZ results.  
**Impact**: All Section 5 (time-zone information transmission) core results — the paper's Third contribution — have NO backing experiment JSON.

**Recommendation**: (a) Identify which original experiment produced these numbers (possibly older experiments not in the `paper/taiwan-vt/experiments/` folder). Create/run a definitive TZ momentum experiment covering 2012–2025 for all six markets and save as a new K experiment. This is the most urgent reproducibility gap.

---

## Additional Divergences (Medium Severity)

### DIV-6: SSVS PIP for "Lagged Own Return"

**Paper (body.tex:207)**: "Lagged own return PIP = 0.312"  
**K461**: AR(1) PIP = 0.9994, AR(2) PIP = 0.979  
**Analysis**: Paper's 0.312 for "lagged own return" does not match K461 AR(1)=0.9994. Possible explanation: the paper refers to a different lag specification or a pre-2026 SSVS run with different priors. The K461 SPY_ret_L1 PIP=1.000 is confirmed.  
**Recommendation**: (a) Clarify which "lagged own return" PIP=0.312 refers to; check if earlier SSVS run produced this value.

### DIV-7: TWII Full-Sample Gamma

**Paper**: TWII gamma=0.272, t=3.18 (full sample 1997–2026)  
**K892**: TWII full_sample gamma=0.109, t=5.62; TWII rolling_last gamma=0.261, t=3.32  
**Analysis**: Paper t=3.18 approximately matches K892 rolling_last t=3.32, and gamma 0.272 approximately matches rolling_last 0.261. But the paper's Table 1 note says "rolling window w=2000" — which would use the rolling estimate, so 0.261 vs. 0.272 is within ~4% but the t-stat diverges (3.18 vs 3.32).  
**Status**: ≈ approximate match within 5%. Not a blocker but should be reconciled.

### DIV-8: Sample Size (n trading days)

**Paper (body.tex:34)**: 0050.TW = 4,532 trading days (Jan 2008–Mar 2026)  
**K892**: n=4,219; K900: n=4,217; K886: n=4,217  
**Discrepancy**: 4,532 vs. 4,217 = 315 days gap. Jan 2008 to March 2026 for Taiwan should be approximately 4,218 trading days. The paper's stated 4,532 appears to be an error (possibly 2007 or an incorrect count).  
**Recommendation**: (b) Correct the stated trading day count in the paper.

### DIV-9: SPY→0050.TW Correlation r=0.376

**Paper (body.tex:191)**: r=0.376 for lagged SPY→next-day 0050.TW c2c correlation  
**K847**: stock_gap vs SPY pearson = 0.399 (2017–2026 period only, n=2,112)  
**Analysis**: K847's 0.399 uses a different period (2017–2026) and measures gap vs SPY rather than c2c vs lagged SPY. No experiment directly computes the 2012–2025 c2c-to-c2c correlation.  
**Status**: ✗ Cannot be confirmed with existing experiments.

### DIV-10: n=4,532 vs. Actual TWII Observations

**Paper (body.tex:35)**: TWII = 7,148 trading days (Jan 1997–Mar 2026)  
**K892**: TWII full_sample n=7,044  
**Discrepancy**: 7,148 vs. 7,044 = 104 days. Minor but present.  
**Recommendation**: (b) Update paper count to match K892.

---

## Confirmed Results (✓ Matched)

| Statistic | Paper | K-experiment | Status |
|---|---|---|---|
| SSVS SPY_ret_L1 PIP | 1.000 | K461: 1.000 | ✓ |
| Conditional leverage Sharpe diff | +0.162 | K558: 0.162 | ✓ |
| Conditional leverage Harvey t | 4.79 | K558: 4.7929 | ✓ |
| Normal VaR violations | 30 | K896: 30 | ✓ |
| Normal VaR violation rate | 2.0% | K896: 1.71% | ≈ |
| GJR+Student-t Kupiec pass (≠ reject) | p=0.12 | K896: p=0.916 | ✗ |
| TWII rolling gamma | 0.272 | K892: 0.261 | ≈ |
| SPY rolling gamma mean | 0.211 | K892: 0.214 | ✓ |
| SPY rolling t mean | 5.79 | K892: 5.31 | ≈ |
| TSMC full-sample gamma | 0.039 | K892: 0.053 | ≈ |
| K558 OOS wins claim (18/18) | 18/18 | K558 has 5-split+13-split | ≈ |
| DM p (VT vs B&H) | 0.0005 (sec 8) | K558 uses different DM | ? |

---

## Missing Experiment Sources (Cannot Be Audited)

The following sections/tables have **no backing experiment JSON** in `paper/taiwan-vt/experiments/`:

1. **Section 5 (TZ momentum) — Table 4 entire** — all c2c/o2o Sharpe values, 6-market t-stats, combination portfolios
2. **Section 5 — Overnight gap diagnostics** — SPY-conditional means (+10.73bp, -8.91bp), gap fraction 87%, bootstrap CI [0.65, 2.24]
3. **Section 6 (Macro indicators)** — import growth r=0.214, OOS improvement 5.6%, DM p=0.043; BCI t=-0.53; leading indicator t=3.74, R²=7.1%; BCI momentum Sharpe; ex-dividend volatility spikes
4. **Section 8 Discussion** — TSMC decomposition (Sharpe 1.121, 0.193–0.637 range); VIX+Leading combo DM p=0.0005; sub-period 8.63/VIX Sharpe=0.334; skewed-t parameters (η=5.2, λ=−0.05); currency drag −18%; VIX sufficiency R²+0.003
5. **Cross-market validation** — Europe-to-US null result r=−0.07, India/Indonesia fails
6. **Correlation asymmetry** — Taiwan down-day vs up-day correlation diff=0.058

---

## Figure Generation Scripts

Per Paper 1 pilot pattern, figure generation scripts are **absent**:

- `figures/fig1_rolling_gamma.pdf` — no generation script found
- `figures/fig2_cumulative_returns.pdf` — no generation script found  
- `figures/fig3_overnight_vix.pdf` — no generation script found

**Recommendation**: (a) Create figure generation scripts tied to experiment JSONs. At minimum, each figure caption must cite the K experiment that provides the underlying data.

---

## Data Period Alignment Issues (Paper 1 Pilot Pattern #1)

| Claimed Period | Actual in JSON | Gap |
|---|---|---|
| 0050.TW: Jan 2008–Mar 2026 (4,532 days) | K892/K900: n≈4,217 (≈2009–2026) | 315 days |
| TWII: Jan 1997–Mar 2026 (7,148 days) | K892: n=7,044 | 104 days |
| VT Table 3: 2010–2026 for B&H/EWMA | K900: 2019–2026 | 9 years mismatch |
| VaR: 2020–2026 (1,501 days) | K896: 2019–2026 (1,756 days) | 255 days |

---

## Summary Table by Status

| Status | Count | Examples |
|---|---|---|
| ✓ Confirmed | 6 | SSVS PIP=1.000; leverage Sharpe diff=0.162; leverage Harvey t=4.79; Normal violations=30 |
| ≈ Approximate (within 5%) | 8 | TWII gamma≈0.261 vs 0.272; SPY t≈5.31 vs 5.79; TSMC gamma≈0.053 vs 0.039 |
| ✗ Divergent | 18 | Table 3 Sharpe all; 0050 gamma=0.087; skewness sign flip; VaR 8 vs 18 violations; PIP 0.312; n=4532 |
| ? No source | 42 | All TZ Table 4; all macro; TSMC decomp; currency; figure scripts |

---

## Submission Readiness

**Verdict: NEEDS-FIX (borderline BLOCKER)**

**Score**: 14/82 confirmed + approximate = **17%** fully matched; **49%** has any source.

**Critical blockers before submission**:
1. Table 4 (TZ momentum) — entire Third contribution has no backing JSON (BLOCKER)
2. Table 3 (VT performance) — no JSON covers the stated 2010–2026 period (BLOCKER)
3. 0050.TW gamma 0.087 — not reproduced by K892 in any configuration (MAJOR)
4. VaR "8 violations / 0.5%" — mislabeled as Student-t when K896 shows CF achieves 0.51% (MAJOR)
5. Sample size 4,532 stated vs ~4,217 actual (MAJOR)

**Can proceed to revision without fixing**:
- Sec 5 body text (gap decomposition narrative ≈ consistent with K847)
- Sec 4 conditional leverage (K558 confirms Sharpe diff=0.162, t=4.79)
- Section 7 Normal distribution results (K896 confirms)
