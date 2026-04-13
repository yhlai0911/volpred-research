# Academic Review — leverage-direction (main_v2.tex / body_v2.tex)

- **Date**: 2026-04-13
- **Reviewer**: Claude (latex-academic-reviewer skill)
- **Files reviewed**: main_v2.tex, body_v2.tex, tables.tex, table_nulls.tex, additions_jk.tex
- **Paper**: "Leverage Direction Matters: Cross-Asset Evidence on GARCH Model Selection and Volatility Targeting"
- **Version**: main_v2.pdf (62 pages, 54 bibliography entries)
- **Target journal**: Journal of Banking and Finance (JBF)

---

## Summary

- **Overall rating**: 3/5 stars (★★★) — solid empirical paper with a clear taxonomy and genuinely novel proposition, but carrying several internal contradictions, a length problem, and at least one statistically weak "centerpiece" result that will invite hostile reviewer reactions.
- **Main strengths**:
  1. The leverage-direction taxonomy (equity γ > 0, gold γ < 0, bonds γ ≈ 0) is clean, economically motivated, and directly operational for model selection.
  2. Proposition 1 (γ → VT alpha mechanism) is a genuine theoretical contribution linking Hood–Raughtigan (2025) to cross-asset VT.
  3. The orthogonality framing (variance equation ⊥ distribution ⊥ signal source), especially Table `var_ortho`, is a memorable and defensible empirical point.
  4. Robustness work is unusually thorough (HAC, block bootstrap, non-overlapping windows, cross-OOS, AR(1) mean check, df sensitivity).
  5. Honest, explicit OOS caveats (v2-H3) and domain restrictions on Proposition 1 (N = 6 vs N = 12).
- **Main weaknesses (HIGH priority — must fix before submission)**:
  1. **Internal contradiction in regime-gamma values (Sec 4.2.4)** — bear-market gold γ is reported simultaneously as "+0.20" (mean) and "+0.048" (t-test) in the **same sentence**.
  2. **Internal contradiction in Henriksson-Merton gamma** — Sec 4.8 reports γ_HM = −0.035 (t = −0.39, n.s.), while Sec 5.4.4 reports γ_HM = −0.043 (t = −4.06, p < 0.001). These are presented as the "same" HM regression.
  3. **Proposition 1 correlation is statistically fragile** — Spearman ρ = 0.886 with N = 6 is barely significant (p = 0.019) and collapses to ρ = −0.448 (N = 12). A JBF reviewer will likely call this underpowered.
  4. **Table 3 "perfect" 9/9 classification is in-sample** — the paper honestly admits this, but the abstract still reads as if 9/9 and 6/6 are equally convincing. Framing must be tempered.
  5. **Orphan citations** (bollerslev1994, corsi2009, engle2002) — already flagged in citation_check.md, still present in main_v2.tex bibliography.
  6. **Paper length (62 pages) vs JBF norm (~45 pages)** — explicitly known issue (README).
- **Minor improvements**: figure-caption axis labels missing; several `t`-statistics without sample size disclosure; two tables without column units; inconsistent Patton-QLIKE convention documentation.

---

## Detail by Section

### 1. Abstract (main_v2.tex lines 36–48)

**Strengths**
- Two contributions clearly labeled (v2-H1 fix worked).
- Quantitative headline numbers (γ taxonomy, ρ = 0.886 / 0.944, regime t = −4.71) are specific.
- JEL codes and keywords are appropriate for JBF.

**Issues**
- **[MED]** "correctly classifying all nine Diebold-Mariano comparisons in the primary sample" — without the "in-sample" qualifier inside the abstract, this overstates. The body honestly discloses (lines 236–237); the abstract should mirror this with a half-clause, e.g. "...classifying all nine in-sample comparisons, with 6/6 correct out-of-sample (N = 6, limited power)".
- **[MED]** "seven primary assets (equities, gold, bonds, emerging markets, cryptocurrency)" — only five asset classes are listed despite N = 7 (QQQ, SPY, EEM, GLD, SLV, TLT, BTC). Either list all seven or collapse to four (equities, precious metals, bonds, crypto). SLV is missing from the class enumeration.
- **[LOW]** "extended to 26 assets in validation analyses" — body says "up to 26 assets" with different sub-samples (12, 14, 17, 21, 26). Abstract should say "up to 26".
- **[LOW]** Abstract uses both "($\rho = 0.944$ for primary assets)" and later "($\rho = 0.944$, $N = 5$)" in conclusion — abstract should give N = 5 once to forestall reviewer confusion.

### 2. Introduction (body_v2.tex lines 3–18)

**Strengths**
- Opens with a focused gap: prior literature assumes asymmetric ⊃ symmetric; we show this is asset-class dependent.
- Chevallier & Ielpo (2017) correctly cited as the closest precedent.
- Two-contribution structure is clean after v2 rewrite.

**Issues**
- **[HIGH]** Line 5 "This 'leverage effect,' first noted by Black (1976) and formalized by Christie (1982)" — Christie (1982) is commonly credited with formalizing the financial-leverage mechanism but NOT the "leverage effect" term itself. Consider "first noted by Black (1976) and given a structural interpretation by Christie (1982)". Reviewers from the GARCH community will flag this.
- **[MED]** Line 12 "correctly classifying all nine Diebold-Mariano comparisons in the primary sample, with 6/6 correct out-of-sample predictions" — reading this in sequence, the reader cannot distinguish in-sample fit from OOS validation without reaching Sec 4.3.2. Add "(in-sample threshold calibration)" to the 9/9 clause.
- **[MED]** Line 14 "Within equity-type assets, γ predicts whether VT acts as trend-following or contrarian (Spearman ρ = 0.886, p = 0.019 for six equity-type assets" — the phrase "six equity-type assets" is ambiguous: the data in Table gamma-mechanism (N = 7) include GLD (not equity-type). Explicitly name the six (SPY, QQQ, EEM, USO, BTC, TLT? or another subset) or refer the reader to Table X.
- **[LOW]** "Supplementary evidence of cross-market information transmission is presented in Appendix" — v2-H1 reframed TZ momentum as supplementary. Good. But Section 4.8/Appendix B still spans ~3 pages. If JBF length is binding, consider cutting further or moving to online-only.

### 3. Literature Review (body_v2.tex lines 22–52)

**Strengths**
- Four well-defined subsections (GARCH/leverage; commodity/inverted; VaR/Basel; VT).
- Identifies a credible gap for each.
- Critical references covered: Hansen & Lunde (2005), Moreira & Muir (2017), Harvey et al. (2018), Hood & Raughtigan (2025), Chang et al. (2021).

**Issues**
- **[HIGH]** Missing key citation: **Engle, Ghysels & Sohn (2013, RFS)** GARCH-MIDAS is mentioned in Table `complexity_ceiling` (row "GJR → MIDAS/MS/CARR") but never cited in text or bibliography. If you test GARCH-MIDAS, cite the source.
- **[HIGH]** Missing key citation: **Patton & Sheppard (2015, RFS)** "Good Volatility, Bad Volatility" — this is the most cited paper on signed realized variance and asymmetry at daily frequency, directly relevant to Section 4.5 (HAR paradox and overnight decomposition).
- **[MED]** Section 2.4 "Cederburg et al. (2020) show that using VIX as the scaling signal produces approximately 4.9% alpha versus realized-variance scaling" — Cederburg et al. (2020) actually argue the OPPOSITE for many factors (VT harms in the cross-section after controlling for transaction costs). Re-check this claim; it may be conflated with Moreira & Muir.
- **[MED]** Section 2.2: Chevallier & Ielpo (2017) is properly attributed, but the phrase "gold, wheat, coffee, and cocoa" should include the specific sign of their gamma (they report which direction) for clarity.
- **[LOW]** The deep-learning subsection (§2.5) feels disproportionate to the paper's scope: DL is only referenced in the null-results table. Consider compressing to two sentences.
- **[LOW]** No citation to **Bollerslev, Chou & Kroner (1992, JoE)** — the foundational GARCH survey. If citing GARCH foundations, include.

### 4. Methodology (body_v2.tex lines 54–147)

**Strengths**
- Model equations written out cleanly (GARCH, GJR, QLIKE, DM).
- Sample-period justification section (v2, lines 70–78) is one of the strongest defensive sections in the paper. The four-part rebuttal (rolling window, OOS length, structural feature, regime diversity) will satisfy most referees on the "only 8 years" criticism.
- Mean-specification footnote (Francq-Zakoïan citation) is appropriate.
- `arch` package + version documented.

**Issues**
- **[HIGH]** Section 3.4.3 (VaR Backtesting): VaR formula for Student-t is written as `VaR_α = t^{-1}_ν(α) · sqrt((ν−2)/ν) · σ_t`. This is the **standardized** form. It must be explicit that σ_t here is the conditional std (not the raw Student-t scale). Reviewers confuse the Student-t density scale with the conditional variance; this cost Kuester et al. (2006) a paragraph of clarification.
- **[HIGH]** Missing ES (Expected Shortfall) backtest. Basel III FRTB (2019, cited) replaced VaR with ES at 97.5% as the regulatory risk measure. A paper built on Basel III VaR compliance without ES backtesting (Fissler-Ziegel, Acerbi-Szekely) will be criticized. The HAR paradox section mentions "Fissler-Ziegel joint loss" but only for Normal vs skewed-t ranking, not as a primary backtest. Add at least one ES table, or justify the omission.
- **[HIGH]** Overlapping-windows discussion (lines 186–195) cites Harri-Brorsen (2009) — correct — and uses Newey-West with 8 lags. But 8 lags < overlap length (504-day / 63-day step → overlap of ~7 quarters in each direction). Should be at least 7 + 1 = 8 lags but the HAC kernel should run out to the overlap horizon. This is technically defensible but the reviewer will ask why not 12 or 16 lags. Pre-empt: "Results robust with 12 lags (t = −5.51) and 16 lags (t = −5.33)" — if true.
- **[MED]** Line 89 "The estimated $\hat{\phi}$ coefficients are economically negligible (mean $|\hat{\phi}| < 0.03$ across assets)" — daily auto-correlation of 0.03 is small but not "economically negligible" for high-frequency traders. Consider softer language: "statistically small relative to variance dynamics".
- **[MED]** Window sizes $w \in \{504, 1000, 2000, 3000, 5000\}$ — a 5000-day window for a 2017–2025 sample will REQUIRE pre-2017 data, contradicting Section 3.1 ("January 2017 through March 2026"). Reconcile: state explicitly that large-window robustness uses 2006+ data.
- **[MED]** `σ_target = 10%` for GARCH but `σ_target = 12%` for VIX — the paper explains this via VRP, but many VT papers use 15% or 20% as target. Justify the specific numerical choice (e.g., "to match long-run SPY realized volatility of 15% while preserving headroom for the 1.5× cap").
- **[LOW]** Weight clipping `[0, 1.5]` — reviewers will ask whether the 1.5 upper bound is binding. Report percentage of days weight = 1.5 by asset.

### 5. Results (body_v2.tex lines 151–389)

**Strengths**
- Section 4.2 (leverage-direction taxonomy) is the paper's best-argued section.
- 93% negative quarterly γ for GLD with HAC t = −5.79 is a strong empirical claim backed up with block bootstrap and non-overlapping windows.
- Section 4.4 (VaR orthogonality Table `var_ortho`) is sharp: three rows that exactly demonstrate the orthogonality claim. This is the single most memorable table in the paper.
- Section 4.6 (QLIKE ceiling) / Section 4.10 (HAR paradox) honestly disclose that the GARCH family is statistically tied with a 22-day rolling average — a finding that contradicts a naive reading of Section 4.3 yet strengthens the overall "complexity ceiling" framing.

**Critical issues**

- **[CRITICAL-HIGH]** **Regime-gamma numerical contradiction**, line 208:
  > "2013--2015 gold bear market, gamma turns sharply positive (**mean γ = +0.20**)... A two-sample t-test confirms: bull market γ = −0.043 versus **bear market γ = +0.048** (t = −4.71, p < 0.0001)."
  
  Bear-market γ cannot be both "+0.20" and "+0.048" in the same sentence. Also line 201 says "γ turned sharply positive (+0.17 to +0.30)" for the same period. A referee will seize on this. FIX: choose one consistent set of numbers (most likely +0.20 is the 2013–2015 subsample, while +0.048 is a different bull/bear decomposition over the full 2005–2026) and label them distinctly.

- **[CRITICAL-HIGH]** **Henriksson-Merton γ_HM contradiction**:
  - Section 4.8 (line 373): `γ_HM = −0.035, t = −0.39, p = 0.70` (not significant)
  - Section 5.4.4 (line 433): `γ_HM = −0.043, t = −4.06, p < 0.001` (highly significant)
  
  These are both described as the Henriksson-Merton regression of "VT returns on max(0, r^f − r^m)" with HAC errors. The t-statistics differ by an order of magnitude. This is the C1 issue flagged in README but NOT resolved in v2. A reviewer will require reconciliation. LIKELY CAUSE: one uses simple VT, the other Hybrid VT, or different sample windows. Label each version explicitly with strategy name and sample period.

- **[HIGH]** **Proposition 1 statistical power**. Line 455: "Spearman correlation between γ and β^trend is ρ = 1.000 (p < 0.001) across seven primary assets". With N = 7 and a mechanical link (both derived from GJR), ρ = 1.000 is nearly tautological. Line 465 then admits: "This correlation is partly mechanical..." then "becomes insignificant for 12 diverse assets (ρ = −0.448, p = 0.14); restricting to equity-type assets recovers it (ρ = 0.886, p = 0.019, N = 6)." A referee will ask: at N = 6, the 95% CI for Spearman ρ is approximately [0.32, 0.99] — the lower bound barely excludes zero. This is not a robust proposition. Consider:
  1. Pre-registering the equity-subset definition more rigorously.
  2. Reporting bootstrap CI for Spearman ρ at N = 6.
  3. Adding a permutation test.
  4. Tempering language from "Proposition" to "Conjecture" or "Empirical Regularity" — the word "Proposition" invokes a theorem-like promise that N = 6 cannot deliver.

- **[HIGH]** **Model selection threshold calibration is largely in-sample** (line 237). Paper honestly admits this but the sensitivity claim "any value in [0.06, 0.12] produces identical classifications for all nine asset-period combinations" is ALSO in-sample. True OOS evidence is one sentence: "6/6 correct classifications (single-point: 5/6)". At N = 6, random classification achieves 6/6 with probability 2^−6 ≈ 1.6% — the paper correctly notes this. But this means the OOS test has essentially no power. Strengthen with at least one external dataset (e.g., FTSE 100 constituents, Chinese A-shares) or acknowledge the limitation more prominently in the abstract and conclusion.

- **[MED]** **Cross-asset MDD correlation**, Section 4.5.2:
  - Line 279: `ρ = 0.944 (p < 0.001)` for 5 primary assets
  - Same line: `ρ = 0.83 (p = 0.0002)` for N = 14 extended
  
  With N = 5, Pearson ρ = 0.944 has 95% CI ≈ [0.39, 0.996] — wide. The extended N = 14 result is more credible. Reorder the prominence: lead with N = 14, use N = 5 only as a replication check.

- **[MED]** **Table 3 QLIKE numbers**. Values like −9.034 (SPY GJR, 2023–2024) should be cross-checked against the K799 experimental JSON flagged in NEW-H4. The review_v2.md says "QLIKE numbers inconsistent between body text and K799". This needs resolution before submission. We cannot verify from the LaTeX alone.

- **[MED]** **Table 5 (VT cross-asset)**: the caption is "Volatility Targeting: Cross-Asset Performance" but the period is unstated in the caption. Footnote says "7–16 year periods" but table doesn't say which asset uses which period. Add a column "Sample Period" or a note under the table.

- **[MED]** Line 247: "SPY achieves Green Zone in only 1 of 6 annual periods (2020–2025), with violation rate 2.2% versus the 1.0% target" — 6 annual periods means 2020, 2021, 2022, 2023, 2024, 2025. The aggregate rate 2.2% contradicts 1/6 Green Zone years (since Green Zone allows up to 4 violations per ~250 days = 1.6%). If 5 of 6 years were Yellow/Red with ~2.7% each, it's consistent, but the arithmetic should be explicit. Add a small sub-table or rewrite: "mean annual violation rate = X; Green Zone = 1/6; Yellow = 3/6; Red = 2/6".

- **[MED]** Section 4.6 (QLIKE ceiling, line 360): "CC-RV 22d ranks first for all three tested assets". But only SPY is shown in Table `qlike_ceiling`. State "SPY, GLD, EEM results available on request" or add the GLD / EEM rows.

- **[MED]** Section 4.5.4 (Strategy Implementation, line 273): "GJR-GARCH for assets with γ > 0.10 (SPY, EEM, BTC-USD)" — but Table 2 shows BTC γ = +0.117 (13% > 0.10 threshold), yet Section 4.3.1 (line 221) says "for BTC-USD, mild standard leverage (γ ≈ +0.12), GARCH slightly outperforms GJR (Δ = +0.14%, p = 0.293)". So why would a γ > 0.10 asset with DM evidence *against* GJR be assigned GJR in the VT construction? This inconsistency between the selection rule and VT implementation is a direct hit to the thesis. Either revise the rule to require t > 1.65 AND DM evidence, or exclude BTC from the VT panel, or acknowledge.

- **[LOW]** Table 8 (Gamma-Mechanism): BTC γ = +0.030 in this table but +0.117 in Table 2. Different averaging windows? Must be labeled.

- **[LOW]** Table 6 (Amplification): "(50 stocks)" for SPY but SPY has 500 constituents. Presumably "top 50 by market cap". Clarify.

- **[LOW]** Figure captions (fig_rolling_gamma, fig_gamma_mechanism, etc.) lack y-axis units in the prose descriptions.

### 6. Discussion / Conclusion (body_v2.tex lines 391–608)

**Strengths**
- Section 5.4 (Proposition 1 economic intuition) bridges the statistical result to the safe-haven literature well.
- Section 5.5 (VT as insurance, MDD utility function Eq. 8) gives practitioners a decision rule.
- Section 5.7 (Complexity Ceiling table) is a strong summary device.
- Conclusion ends with clear domain restrictions (ρ = −0.448 for N = 12) — honest.

**Issues**
- **[HIGH]** Section 5.4.1 (VaR attribution) introduces a new number not in any earlier table: "skewed-t and FHS share the highest Trinity pass rate at 76.2% (16/21)". Consistent with Table `var_panel`, but this table is never referenced in the Methodology section. Forward reference at first use of "Trinity" would help (line 247 "criterion-dependent" invokes Trinity without definition until 3 pages later).
- **[MED]** Section 5.4.4 (Nature of VT Alpha) reports `α = 5.77% annualized (t = 3.99, p < 0.001)`. This t is computed over how many observations? The text says "~3,100 daily observations (2014–2026)". With 3100 observations and 10-lag HAC, an annualized alpha of 5.77% with t = 3.99 is plausible. But the number isn't in any table. Add to an existing table or the appendix.
- **[MED]** Section 5.5 (Eq. mdd_utility): `U = W_T · (1 + λ · MDD)` with MDD ≤ 0. A referee will ask: where does λ ≥ 2 come from in the loss-aversion literature? Reference Barberis-Huang (2001) or Ang-Bekaert-Liu (2005) on disappointment aversion / prospect theory to anchor the utility specification.
- **[MED]** Section 5.6 (VT Alpha Not Calendar): the test "month dummies + VIX" is one way but doesn't address the real concern: is VIX itself driven by seasonal effects? Add a regression of VIX on month dummies and report R². If > 5%, concern is real; if < 1%, concern dismissed.
- **[LOW]** Section 5.4.5 (HAR paradox) is conceptually important but structurally misplaced as "Implications for Risk Management Practice" subsection. Consider a top-level "5.x Reconciling QLIKE and VT" section.
- **[LOW]** Section 5.8 (Limitations) combines multiple categories (multiple testing, behavioral implications, future directions) into one subsection. Split into 5.8 Limitations and 5.9 Future Directions for JBF readability.
- **[LOW]** Conclusion repeats abstract headline numbers ρ = 0.944 / 0.83 three times. Trim one.

### 7. References / Citations

(Detailed citation verification is delegated to `citation-verifier` agent; this review adds framing and uncaught orphans.)

**From existing citation_check.md (2026-03-30)**:
- 3 confirmed orphans in bibliography: `bollerslev1994`, `corsi2009`, `engle2002`.
- 1 format issue: `campbell2017` uses `[Author et~al., Year]` instead of `[Author(Year)]`.

**Additional issues identified in this review**:
- **[HIGH]** Missing: **Engle, Ghysels & Sohn (2013)** GARCH-MIDAS — referenced in Table `complexity_ceiling` but not in bibliography.
- **[HIGH]** Missing: **Patton & Sheppard (2015, RFS)** — directly relevant to overnight decomposition (line 344).
- **[MED]** Missing: **Bollerslev, Chou & Kroner (1992)** — foundational GARCH survey.
- **[MED]** `engle2018` (Structural GARCH) is cited in Sec 2.1 but not mentioned again — ensure this is not merely a "citation-for-citation's-sake" placement.
- **[LOW]** `hood2025` appears with "Hood and Raughtigan (2025)" in text but bibliography lists "Raughtigan, C." — verify the spelling and attribution (both Hood and Raughtigan appear to be invented names; cross-reference the actual Journal of Portfolio Management 2025 paper).

**Recommendation**: Re-run `citation-verifier` after adding the 3 missing citations and fixing the campbell2017 format. Orphan removal is a mechanical 5-minute fix.

---

## Critical Recommendations (for v3)

### Must fix before JBF submission

1. **[HIGH]** Resolve the regime-γ contradiction in line 208 (bear market = +0.20 vs +0.048). Pick one definition per row and label the periods distinctly.
2. **[HIGH]** Resolve the HM γ_HM contradiction (Sec 4.8 t = −0.39 vs Sec 5.4.4 t = −4.06). Label each instance with strategy name (plain VT vs Hybrid VT) and sample window.
3. **[HIGH]** Temper Proposition 1 framing — rename to "Conjecture" or "Empirical Regularity"; report bootstrap CI for the N = 6 Spearman ρ; add permutation p-value. Or (preferred) find one external asset universe to test OOS.
4. **[HIGH]** Add Expected Shortfall backtest (Fissler-Ziegel or Acerbi-Szekely) to complement VaR. Basel III FRTB compliance without ES is a red flag for the JBF reviewer pool.
5. **[HIGH]** Fix the BTC assignment inconsistency (γ > 0.10 rule assigns GJR, but DM prefers symmetric GARCH for BTC). Either refine the rule to require DM corroboration or exclude BTC from the VT implementation panel.
6. **[HIGH]** Remove 3 orphan citations; add 2–3 missing core references (GARCH-MIDAS, Patton-Sheppard 2015).
7. **[HIGH]** Reconcile QLIKE numerical values with the underlying experiment (K799) — the NEW-H4 issue from review_v2.md is unresolved.

### Should fix (length/framing)

8. **[MED]** Compress to ~45 pages for JBF norms:
   - Move TZ momentum appendix to online-only or remove entirely (currently reads as orphaned material even with v2-H1 reframing).
   - Trim deep-learning literature review (§2.5).
   - Consolidate the 3 "Complexity Ceiling" passages (§4.10, §5.7, §5.9) into one decisive treatment.
   - Move detailed robustness numbers (Sec 4.6, 4.7) to appendix.
9. **[MED]** Add sample-period-stratified results: JBF reviewers typically want a 2008–2015 replication. The γ taxonomy result in the non-overlapping 4-window analysis partially addresses this; promote to a full table.
10. **[MED]** Add a forward-reference table of contents for the tables (Tab. 1–10 with captions and their role in the narrative).
11. **[MED]** Make the HAR paradox (§4.10) more prominent — it is the most counter-intuitive and publishable finding in the paper. Consider elevating to a main-text contribution ("prediction ≠ application") rather than subsection 4.10.

### Nice to have

12. **[LOW]** Figure improvements: axis labels, font size, color-blind-safe palette.
13. **[LOW]** Appendix C: "Reproducibility" — list exact Python package versions, random seeds, and point to reproduce.py.
14. **[LOW]** Acknowledge Claude / GPT assistance per JBF AI-disclosure policy (Springer/Elsevier added this in 2024).

---

## Submission Readiness

- **Target journal fit (JBF)**: ★★★☆☆ (3/5)
  - JBF publishes cross-asset GARCH and VT studies (recent: Gagliardini et al. 2020, Campbell et al. 2023, etc.). Topic fit is good.
  - Methodological standard is met (HAC, DM, bootstrap, MCS, Harvey threshold).
  - However, JBF increasingly expects: (i) international sample, (ii) ES alongside VaR, (iii) pre-registered OOS specification. The paper partially satisfies (i), misses (ii), and is weak on (iii).

- **Predicted referee reactions**:
  - **Referee 1 (methodology-focused econometrician)**: will seize on the N = 6 Proposition 1, the HM γ contradiction, and the 9/9 vs 6/6 framing. Likely verdict: "major revision" with a request to strengthen OOS evidence.
  - **Referee 2 (applied finance/risk management)**: will appreciate the VaR orthogonality framing (Table `var_ortho`) and the insurance-premium framing (Eq. 8). Likely more favorable. Will ask for ES backtest.
  - **Referee 3 (if asset pricing)**: will push back on the "complexity ceiling" claim as potentially overfit to daily frequency; will ask about intraday / 5-min evidence.
  
  **Median outcome**: major revision (R&R), 1 round to get to minor revision if HIGH issues above are resolved.

- **Revision effort estimate**: 2–3 weeks of focused work to produce a v3 that resolves the 7 HIGH issues. OOS validation on an external asset universe is the longest-lead item.

- **Alternative targets if JBF rejects**: Journal of Empirical Finance (JEF), Journal of Financial Econometrics (JoFEc), International Review of Financial Analysis (IRFA — where Bozovic 2024 appeared). The paper in current form is closest to IRFA / JEF fit than to JBF.

---

## Appendix: Checklist Summary

| Check | Status | Notes |
|-------|--------|-------|
| Logic structure | ★★★★☆ | Two-contribution structure works; TZ appendix still orphaned |
| Argument quality | ★★★☆☆ | Proposition 1 fragile at N = 6 |
| Model specification (GJR γ) | ★★★★☆ | Clear math, robust to mean specification |
| Equation derivation | ★★★★☆ | QLIKE footnote well done; Student-t VaR formula needs clarification |
| Symbol consistency (γ direction) | ★★★★★ | GJR vs EGARCH sign note in line 324 handled correctly |
| Citation completeness | ★★☆☆☆ | 3 orphans + 2 missing = 5 bibliographic issues |
| Reproducibility | ★★★★☆ | reproduce.py exists, data sources documented |
| Statistical rigor | ★★★☆☆ | Harvey threshold used; HAC OK; but N = 6 problem |
| Contribution clarity | ★★★★☆ | v2 rewrite to 2 contributions succeeded |
| Robustness checks | ★★★★★ | Unusually thorough |
| Internal consistency | ★★☆☆☆ | **2 numerical contradictions (regime γ, HM γ_HM)** |
| Length / JBF norms | ★★☆☆☆ | 62 pages vs ~45 target |

---

**Reviewer's bottom line**: The paper has a real contribution (leverage-direction taxonomy + γ → VT mechanism proposition) and unusually strong robustness work. The two numerical contradictions and the statistically fragile Proposition 1 are the blocking issues. If these are resolved in a v3 that is also compressed to 45 pages, the paper is submission-ready for JBF with a realistic R&R outcome.
