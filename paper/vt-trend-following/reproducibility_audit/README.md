# Paper 3 Reproducibility Audit Summary
**Paper:** "Is Volatility Targeting Just Trend Following?" (vt-trend-following)  
**Audit Date:** 2026-04-17  
**Worktree:** agent-af2babb1  
**Auditor:** Claude Sonnet 4.6 (reproducibility audit agent)

---

## Audit Score

| Metric | Value |
|---|---|
| Total numbers checked | 74 |
| Matched (✓) | 47 (63%) |
| Near-match (≈, rtol≤2%) | 5 (7%) |
| Divergent (✗) | 14 (19%) |
| Cannot verify (?) | 8 (11%) |
| **Coverage rate** | **82% of extractable numbers** |
| **Verified match rate** | **77% (47/61 verifiable)** |

**Overall verdict: NEEDS-FIX → several numbers are BLOCKER-level divergent**

---

## 5 HIGH Issues from review_v2 — Current Status

| Issue | Description | Status |
|---|---|---|
| H1 (v2 B.1) | Sample period inconsistency (2005 vs 2007 in same paper) | **PENDING** — confirmed unresolved in main.tex |
| H2 (v2 B.2) | BAB proxy N=3740 truncation vs N=5049 in script | **DIVERGENT** — script uses N=5049, paper says N=3740 |
| H3 (v2 B.3) | MDD retention only for 5 correlated US equity assets | **PENDING** — no extension experiment found |
| H4 (v2 C.1) | "1.4% TSMOM contribution to Sharpe" unexplained/wrong | **BLOCKER** — K898 gives 5.3% not 1.4%; no derivation found |
| H5 (v2 A.1) | K687/K697/K688 not cited or reconciled | **PENDING** — three directly relevant experiments ignored in main.tex |

---

## Top 5 Divergences (Priority Order)

### 1. MDD Retention Values (D1+D2) — BLOCKER
**The paper's PRIMARY claim** (90–97% MDD retention across 5 assets) is unverified by K898, which computes 104–120% (hedged VT has BETTER MDD than VT). The entire Table 3 decomposition differs from K898.  
**Root cause:** TSMOM hedge implementation mismatch between paper and K898. K898 uses a daily TSMOM hedge with rolling OLS that produces different results than what the paper presents.  
**Recommendation:** Find or recreate the authoritative script that produces the paper's Table 3 values (Hedged VT Sharpe=0.737, MDD=−26.9% for SPY). Store it as `paper/vt-trend-following/experiments/table3_authoritative.py`. The K898 script's `paper_comparison` field hard-codes the claimed values, suggesting K898 is not the source.

### 2. International Table 5 (D5) — BLOCKER
Table 5 claims average ΔMDDpp=28.7, t=15.70, r=−0.770, ρ=0.830. None of these can be reproduced from K901 because K901 uses a different 13-market set. No experiment with the paper's exact markets {EWC, VGK, MCHI} exists.  
**Recommendation:** Create `paper/vt-trend-following/experiments/table5_international_13markets.py` with the exact paper assets and period (Jan 2007–Mar 2026).

### 3. "1.4% TSMOM Sharpe contribution" (D7) — BLOCKER
No experiment produces this number. Back-calculation from K898 gives 5.3% (SPY) or negative (50/50). The number appears to be a central claim in the paper but has no traceable source.  
**Recommendation:** Either (a) compute and document the derivation clearly, or (b) remove/replace this claim.

### 4. Table 4 M5 N=3740 vs N=5049 (D6) — HIGH
Paper claims post-2011 subsample N=3,740 for M5, but K54 experiment runs N=5,049 using a full-sample BAB proxy. Review_v2 B.2 flags this as HIGH since direct comparison of M1–M5 is misleading when N differs.  
**Recommendation:** Use AQR BAB (free, full history) and report M5 on full N=5,049.

### 5. K687/K697/K688 Reconciliation (H5) — HIGH
K687 shows BH 50/50 beats 12/VIX on Sharpe after lookahead fix. K688 shows 12/VIX doesn't win CRRA utility at any gamma for the 50/50 blend (EWMA wins). K697 provides the strongest empirical support for the VIX-level mechanism (not cited).  
**Recommendation:** Add one paragraph in Section 4.1/4.3 citing these findings. The K687 finding actually SUPPORTS the paper's insurance framing (VT loses on Sharpe but wins on risk) — but this must be stated explicitly.

---

## What Is Well-Reproduced ✓

- **Table 1 (N=22 alpha decomposition):** 100% of individual asset values matched to K55/vt_tsmom_final_n22.json. All gamma, M1 alpha, t-stats, R2, TSMOM betas, delta_alpha values confirmed.
- **Table 2 (cross-sectional):** All correlation values (r=0.564, rho=0.544, CI, regression coefficients) confirmed from K55.
- **Table 4 M1–M4:** All alpha, t-stats, factor loadings confirmed from K54/ff5_factor_controls.json.
- **Discussion numbers:** 427 configs (K568), 3.4/14.9 bps breakeven (K499), 5 TF strategy failures (K518) — all confirmed.

---

## Submission Readiness

**VERDICT: NEEDS-FIX — NOT READY FOR SUBMISSION**

The paper has 3 BLOCKER-level issues that must be resolved before submission:

1. **Table 3 TSMOM decomposition values** have no verified authoritative script — the K898 experiment produces materially different results.
2. **Table 5 international evidence** has no script with the paper's exact asset universe.
3. **"1.4% TSMOM Sharpe contribution"** claim has no traceable derivation and is numerically inconsistent with available experiments.

Additionally, 5 HIGH issues from review_v2 remain unresolved (sample period inconsistency, BAB N truncation, MDD retention coverage, K687/K697/K688 integration).

Once the 3 BLOCKERs are resolved, the paper should be competitive for JPM/FAJ submission.

---

## Files in This Audit

| File | Description |
|---|---|
| `main_tex_numbers.csv` | Full number extraction: 74 rows with tex_value, script_value, status |
| `script_output.json` | Raw values from each experiment file |
| `diff_report.md` | Detailed analysis of divergences with root causes |
| `README.md` | This summary |

---

## Experiments Referenced

| Experiment | File | Purpose |
|---|---|---|
| K55 / N=22 | `paper/experiments/vt_tsmom_final_n22.json` | Tables 1–2 |
| K54 | `paper/experiments/ff5_factor_controls.json` | Table 4 |
| K898 | `paper/experiments/k898_paper3_table3_supplement_results.json` | Table 3 |
| K901 | `experiments/k901_international_vt_13markets_results.json` | Table 5 (partial) |
| K518 | `experiments/k518_trend_following_results.json` | Sec 4.1 |
| K499 | `experiments/k499_rebalancing_frequency_results.json` | Sec 4.2 |
| K568 | `experiments/k568_optimal_weight_function_results.json` | Sec 4.2 |
| K687 | `experiments/k687_results.json` | Context (should be cited) |
| K688 | `experiments/k688_results.json` | Context (should be cited) |
| K697 | `experiments/k697_results.json` | Sec 4.2 support (should be cited) |
