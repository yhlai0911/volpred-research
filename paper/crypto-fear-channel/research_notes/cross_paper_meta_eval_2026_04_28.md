# P10 Crypto-Fear-Channel — Cross-Paper Meta-Evaluation (NotebookLM-style)

**Date**: 2026-04-28
**Reviewer**: Main thread (cross-paper meta-evaluator role, NotebookLM-style)
**Manuscript**: `paper/crypto-fear-channel/main.tex` (v2.3, 16 pages, 509 lines, 22 bibitems, reproduce GREEN 29/29)
**v2 review verdict**: 4.40★ academic / 0 MAJOR citation; promote to **review stage** (commit 78593750)
**Stage gate criterion #3**: cross-paper meta = no fundamental issue → this evaluation
**Comparison portfolio**: P5 (vt-crowding-abm), P6 (prg-periodic-garch), P9 (garch-x-vix), portfolio-level positioning across 9-paper pipeline

---

## Section 1 — Designed-by-Construction vs Emergent Empirical Findings

**Question**: Are P10's 5 stylized facts mathematically forced by data structure / design choices, or are they genuinely emergent empirical observations? Apply the NotebookLM 2026-04-27 critique that flagged P5's ABM 70% threshold as "λ/γ mathematical consequence not emergent finding."

### Verdict: **PASS** with one minor framing tightening recommended.

### Reasoning

The five P10 stylized facts are evaluated independently:

1. **Asymmetric Granger** (BTC- → VIX significant; BTC+ → VIX null at all 5 lags). **Status: emergent.** The Hatemi-J framework only forces sign-conditional decomposition, not the result that one branch has F up to 18.96 while the other has F < 2 across 5 lags. A symmetric leverage effect within BTC alone would not mechanically force this — both branches would carry signal through the volatility-of-volatility channel. The monolithic asymmetry (no overlap region, all 5 lags one-sided) is a non-trivial empirical finding.

2. **QR sign reversal** (β_τ = -2.86 at τ=0.05 → +22.31 at τ=0.95). **Status: emergent + headline novelty.** Quantile regression by construction allows sign reversal but does not force it — the lower-tail negative slope at τ=0.05/0.25 is a finding, not a methodological artifact. Indeed, the paper frames this correctly in §5.2 as "to our knowledge, a new finding for crypto-equity spillover." 8.54× upper-tail amplification is a derived ratio, not a forced quantity.

3. **Subperiod regime dependence** (only 2020 significant out of 5 subperiods). **Status: emergent but partly design-dependent.** The choice of 5 subperiods (pre-mania / crypto winter / COVID / bull-bear / recovery+ETF) is theory-laden; an alternative segmentation could yield different significance patterns. Robustness §6.2 (uniform ℓ=5 lag length) addresses lag-mining but does not address subperiod-boundary mining. The narrative "COVID-2020 is a structural watershed" is **slightly stronger than the evidence** because the subperiod boundaries are chosen ex post. **Recommended fix**: §6.2 footnote acknowledging subperiod boundaries are author-chosen for narrative parsimony, with reference to a ±6-month boundary-perturbation robustness check (or note that this is left for follow-up). This matches the discipline standard P10 already adopts elsewhere.

4. **DY net receiver** (mean net spillover -76.9 pp). **Status: emergent.** DY framework yields directional decomposition but does not force receiver vs sender; the empirical -76.9 pp + zero rolling-window flips is a strong directional finding.

5. **OOS DM null** (t = -0.98). **Status: emergent + honest reporting.** Not designed-by-construction; this is a genuine null that the in-sample structure could plausibly have overcome.

### Comparison to P5 ABM 70% threshold critique

P5's NotebookLM critique was specifically that the 70% VT threshold is sensitive to (λ, γ) Kyle parameter choice, making it a calibration-conditional output rather than a robust emergent finding. P5 v2 addressed this with the OAT robustness sweep (5 cells × ±50% λ/γ perturbation, §3 of P5) confirming TF/MR ≤ VT ordering survives microstructure perturbation — converting the critique from "designed-in finding" to "robust qualitative ordering."

**P10 has no analogous risk for 4/5 facts.** Only the subperiod regime claim has a structurally similar "boundary-mining" exposure, which the recommended fix above addresses. The QR sign reversal and asymmetric Granger results are not parameter-conditional in the same way.

### Suggested fix

Add a one-paragraph robustness note in §6.2 (lag-length sensitivity already there) acknowledging subperiod boundary choice and the ex post nature of the 5-window partition. Roughly 60-100 words. Optional but recommended: a reproduce.py output cell showing F-statistic stability under ±6-month boundary perturbation. Not a blocker.

---

## Section 2 — Portfolio Overlap Risk: P10 vs P9

**Question**: Does P10 overlap with P9 garch-x-vix to a degree that creates "same author cluster on overlapping data and methods" reviewer risk?

### Verdict: **PASS** — overlap is asset-level only, methodologically orthogonal. No defensive footnote required, though one-sentence cross-reference recommended.

### Reasoning

**Asset overlap matrix**:

| Asset | P9 garch-x-vix | P10 crypto-fear-channel |
|---|---|---|
| SPY | ✓ (S&P 500 returns) | ✓ (RV target) |
| VIX | ✓ (exogenous τ_t input) | ✓ (response variable) |
| QQQ | ✓ | ✗ |
| EEM | ✓ | ✗ |
| 0050.TW | ✓ | ✗ |
| EURO STOXX / FEZ | ✓ | ✗ |
| GLD + GVZ | ✓ | ✗ |
| **BTC** | **✗** | **✓** (primary) |

P9 is a **multi-asset GARCH-X horse race using VIX as exogenous regressor**; SPY+VIX is the primary case, with 5-asset cross-validation. P10 is a **bivariate-spillover characterization study with BTC as the primary actor**, using SPY+VIX as the equity counterparty system. The overlap is the SPY+VIX pair, but the role of each variable differs:

- P9: VIX is a **predictor** (input to τ_t), SPY RV is the **target**
- P10: VIX is the **response variable**, BTC RV is the **predictor**

**Methodological overlap matrix**:

| Method | P9 | P10 |
|---|---|---|
| GARCH-X with VIX | ✓ primary | ✗ |
| GARCH-MIDAS | ✓ benchmark | ✗ |
| Diebold-Mariano OOS | ✓ Harvey 2016 |t|>3 | ✓ Harvey 2016 |t|>3 |
| Asymmetric (Hatemi-J) Granger | ✗ | ✓ |
| Quantile regression | ✗ | ✓ |
| Diebold-Yilmaz spillover | ✗ | ✓ |
| Source decomposition (τ × g) | ✓ | ✗ |
| VRP tracking | ✓ | ✗ |

**Method overlap is single-method** (DM with Harvey threshold), and that method is now standard discipline rather than authorial signature — using it does not create an "author cluster" signal. Other methods are entirely disjoint.

**Reviewer risk assessment**: An IJFMIM/JEF reviewer who has both papers on desk would note the overlap is about the BTC question (P10) versus the GARCH-X parsimony question (P9). The papers answer different questions on partially overlapping data — comparable to a researcher having two papers on US equity returns but one is about momentum factor design and the other is about variance risk premium. Common practice in finance.

### Suggested fix

P10 §1 (intro) could include a one-sentence cross-reference acknowledging that the author has separately studied VIX-augmented GARCH forecasting in a parsimonious GARCH-X framework, and that the present paper studies the orthogonal question of crypto-driven directional spillover. This is 100% optional and only relevant if both papers were submitted simultaneously to the same journal. Currently P9 is "under review at journal" (per task brief); P10 targets IJFMIM 1st / JEF 2nd / FRL backup. If P9 is already at one of these three, then a cover-letter mention is the cleaner channel. **Recommendation**: skip the §1 footnote; handle via cover letter if relevant journals overlap.

---

## Section 3 — Methodology vs Novelty Trade-off

**Question**: P10 uses 4 settled methods (asymmetric Granger, QR, DY, DM). Strength (rigorous + replicable) or weakness (no new methodology)? Where is P10's contribution lever compared to P6's new periodic GARCH spec or P5's NoiseControl falsifier?

### Verdict: **CONDITIONAL PASS** — contribution lever is real but currently understated in framing.

### Reasoning

**Contribution lever taxonomy across the portfolio**:

| Paper | Contribution lever | Type |
|---|---|---|
| P5 vt-crowding-abm | NoiseControl falsifier + cross-strategy threshold ordering | **methodology innovation** (new falsifier design pattern) |
| P6 prg-periodic-garch | Periodic Realized GARCH (PRG) with session-boundary information transfer | **model innovation** (new GARCH spec, 6-8 params) |
| P9 garch-x-vix | Multiplicative GARCH-X-VIX with τ_t = VIX² parsimony argument + source decomposition | **specification + interpretation innovation** |
| **P10 crypto-fear-channel** | **Combined four-dimensional decomposition** (asymmetric × tail × regime × OOS) **+ honest joint reporting of in-sample structure with OOS null** | **synthesis + discipline innovation** |

P10 does NOT introduce a new estimator, new model spec, new falsifier, or new asymptotic theory. Its contribution is at a different level: **first crypto-equity spillover study to combine all four dimensions in a single framework with OOS discipline**, exposing a sign-reversing tail structure invisible to single-technique studies. This is a legitimate publication lever — it is the same lever that papers like Adrian-Brunnermeier (2016) use when applying quantile regression to systemic risk (no new estimator, but new application of existing tool to a new question).

The current §1 contribution paragraph (line 51) lists three contributions but undersells lever 1: "by combining asymmetric Granger causality, quantile regression for tail dependence, Diebold-Yilmaz spillover direction, and an honest out-of-sample forecasting test in a single framework, we show that each dimension tells a distinct story." This is correct but reads as a methods enumeration, not as a positioning argument.

### Comparison to P5/P6/P9 contribution density

- P5 has **falsifier design** (NoiseControl) that is genuinely transferable methodology
- P6 has **new GARCH spec** that is a model contribution
- P9 has **GARCH-MIDAS-is-unnecessary parsimony argument** that is a methodological position
- P10 has **synthesis + discipline** which is the weakest type of lever for a top-tier journal

For IJFMIM (the 1st target), synthesis-type contributions are acceptable when the synthesis exposes a new empirical fact. The QR sign reversal at the lower tail is exactly such a new fact. **The contribution paragraph should lead with the empirical novelty (sign reversal + 8.54× upper-tail amplification), not with the methodological combination.**

### Suggested fix

Rewrite the §1 contribution paragraph (line 51) to reorder: lead with the **empirical novelty** (sign reversal and 8.54× amplification), then the **regime watershed** finding, then the **honest joint reporting discipline**. The methods enumeration should support the empirical claims, not lead them. Roughly 80-150 word rewrite, no new evidence required. **This is the single most consequential revision for journal placement**.

---

## Section 4 — OOS NULL Strategic Framing

**Question**: P10 honest OOS DM=-0.98 NULL — publication strength (discipline) or weakness (no actionable predictor)? P9 vs P10 which is more defensible? Is §8.2 "Granger ≠ forecastability" a publishable contribution or defensive framing?

### Verdict: **PASS** — OOS NULL is a strategic strength conditional on the empirical novelty in §5 carrying the contribution.

### Reasoning

**Publication economics of OOS NULL**:

A pure OOS null with no in-sample structure would be a weakness. P10 does not have that profile — it pairs an OOS null with five in-sample stylized facts, three of which are individually publishable (asymmetric Granger, QR sign reversal, regime watershed). The OOS null serves three publication purposes:

1. **Discipline signal to editors**: communicates that the author voluntarily applied Harvey 2016 |t|>3 threshold and reported transparently when it failed. This is a positive signal for top-tier journals after the replication crisis discussion.
2. **Methodological pivot**: the §8.2 "Granger ≠ forecastability" reconciliation is doing genuine intellectual work — it explains why a sparse signal (BTC- × upper-VIX × COVID) fails to dominate a dense AR baseline in expected loss. This is publishable methodology.
3. **Forward defense**: pre-empts a reviewer who might run their own DM test and discover the null themselves.

P10 vs P9 defensibility for the OOS section:

| Criterion | P9 | P10 |
|---|---|---|
| OOS verdict | DM t = 4.03 against GJR (positive) | DM t = -0.98 (null) |
| Multi-asset OOS | 5 markets, 4/5 cross Harvey threshold | Single asset (SPY/VIX/BTC) |
| Risk-management OOS | VaR/ES backtest 3/4 vs GJR 1/4 | Not in scope |
| Honest reporting | g_t no OOS predictability for VRP (one null amid positives) | Full negative DM transparently reported |

P9 is **more straightforwardly defensible** because it has multi-asset positive OOS results plus VaR/ES validation. P10's defensibility depends on the §8.2 reconciliation argument carrying the day. If a reviewer accepts that Granger ≠ forecastability is a substantive observation, P10 passes; if a reviewer demands an OOS positive somewhere in the paper, P10 may need an R&R round to add (e.g.) a regime-conditional VaR/ES exercise on the BTC- × upper-VIX channel.

§8.2 is publishable contribution, not defensive framing — but it is contribution **only because it is paired with the in-sample novelty**. Standalone, it would be too thin. The current draft handles this correctly.

### Suggested fix

None required. §8.2 is well-written. One minor enhancement: §7 could explicitly preview the §8.2 argument earlier, so a reader who skims §7 first is not led to interpret the null as a paper failure. A single sentence in §7 introduction pointing forward to §8.2 would suffice.

---

## Section 5 — Editor / Reviewer First Impression: Same-Author Cluster Risk

**Question**: If IJFMIM editor receives P5 + P6 + P10 simultaneously, would this trigger a "same author cluster" flag? Should P10 stagger submission timing or cross-link in cover letter?

### Verdict: **CONDITIONAL PASS** — stagger timing recommended, cross-link only if requested.

### Reasoning

**Portfolio submission state (per task brief)**:

| Paper | Stage | Target |
|---|---|---|
| P5 vt-crowding-abm | ready_for_submission | FRL |
| P6 prg-periodic-garch | ready_for_submission | FRL |
| P9 garch-x-vix | under review at journal | (already submitted, journal not specified) |
| **P10 crypto-fear-channel** | **review (just promoted)** | **IJFMIM 1st / JEF 2nd / FRL backup** |
| P1, P2, P3, P4ins, P7, P8 | various stages | various |

**Topical overlap matrix (for cluster-flag risk)**:

| Pair | Topic overlap | Method overlap | Asset overlap | Risk level |
|---|---|---|---|---|
| P5 ↔ P10 | low (ABM crowding vs spillover) | low | none (P5 simulated) | **none** |
| P6 ↔ P10 | low (session GARCH vs spillover) | low (DM only) | low (TAIFEX/SPY/QQQ vs SPY/BTC/VIX — SPY only) | **none** |
| P9 ↔ P10 | medium (both VIX-relevant) | low (DM only) | high (SPY/VIX overlap) | **low-medium** |

**FRL clustering** (P5 + P6 → FRL): both are ready_for_submission and both target FRL. P10 has FRL only as backup. If P5 and P6 are both submitted to FRL within the same quarter, that itself is a same-author signal at FRL — but P5 and P6 are methodologically very different (ABM simulation vs new GARCH spec) so a flag is unlikely. **Recommendation**: stagger P5 and P6 by 4-6 weeks, not because the editor will reject one, but because parallel desk-rejections are correlated.

**IJFMIM** (P10 1st target): P5/P6 are not at IJFMIM. P9 is at "a journal" (unspecified). If P9 is at IJFMIM, then P9+P10 simultaneous review at IJFMIM creates the cluster signal we discussed in §2. If P9 is at a different journal (e.g., JoE, JFE, JBF), the IJFMIM editor sees only P10 from this author currently and there is no cluster signal.

**Cover letter recommendation**: P10's cover letter should mention that the author has companion work on volatility forecasting (P9) currently at another journal, and on session-boundary GARCH (P6) targeting FRL — but only because journal etiquette favors disclosing related submissions to avoid the appearance of withholding. This is standard practice and not a defensive maneuver.

### Suggested fix

1. Confirm P9's submission journal. If P9 is at IJFMIM, stagger P10 submission until P9 has first decision (R&R or reject) — likely 8-12 weeks.
2. If P9 is at a different journal, P10 can submit to IJFMIM whenever revisions per Sections 1, 3, 6 are done.
3. Cover letter: standard disclosure of related submissions; no special framing required.
4. P5 + P6 to FRL: stagger by 4-6 weeks to decorrelate desk-rejection risk.

---

## Section 6 — Structural Integrity vs Single-Paper Polish

**Question**: v2 round closed 25 issues to reach review stage. Does cross-paper view reveal structural issues invisible to single-paper review?

### Verdict: **CONDITIONAL PASS** — three structural observations, two are flag-and-monitor, one needs fix before submission.

### Reasoning

**Issue 1 (flag-and-monitor): Portfolio defining theme alignment**

The 9-paper portfolio's defining themes are: (a) volatility forecasting under session structure / external information (P6, P9), (b) volatility-risk strategy crowding and systemic implications (P5, P7-VT-related), (c) target-asset diversification with TAIFEX as Taiwan-specific anchor (P1, P2, P3, P6 partially). P10 fits theme (a) loosely (it studies volatility transmission, not forecasting per se) and adds a new sub-theme: cross-asset spillover with crypto. P10 expands the portfolio outward rather than reinforcing the existing core. This is **not a defect** — strong publication portfolios benefit from controlled diversification — but the author should be aware that P10 reads as a one-off rather than a serial-entry within an established research program.

For the JIMFIM target, this is fine (broad scope journal). For an FRL submission, P10 might benefit from a one-sentence portfolio context hint in the cover letter.

**Issue 2 (flag-and-monitor): §8 policy claim potential overlap with P5**

§8.3 (subsec:d_policy) makes policy claims about: (i) crypto not being decoupled even after ETF integration, (ii) margin systems for cross-asset exposure should account for tail amplification, (iii) retail investor protection on centralized crypto exchanges has positive externalities. P5 makes systemic-risk policy claims about volatility-targeting crowding. **The two policy domains are distinct** — P5 is about VT strategy adoption thresholds, P10 is about cross-asset margin design. No actual claim overlap. **No fix required**, but if both papers are publicly visible (e.g., on the volpred.zeabur.app feed), the author may want to briefly note in §8.3 that the policy claims here are complementary to (not duplicative of) the systemic-risk literature on volatility-targeting strategies. Two-sentence enhancement, optional.

**Issue 3 (FIX before submission): Single-asset OOS evaluation limitation**

P10 OOS test is on a single asset pair (BTC-USD → VIX). Cross-paper reading shows that P9 conducts OOS evaluation across 5 assets (SPY, QQQ, EEM, 0050.TW, GLD) and P6 across 6 markets (TAIFEX, SPY, QQQ, GLD, EEM, 0050.TW). P10's single-asset OOS is a structural weakness when read against the same author's other papers — a reviewer who pulls up the author's recent work will notice the asymmetry and may push back with "why no DAX or FTSE robustness?"

This is structural rather than cosmetic because the OOS-NULL result is the most reviewer-vulnerable claim in P10. A multi-asset OOS that produces consistent nulls across (e.g.) BTC→VIX, ETH→VIX, BTC→VSTOXX would convert the null from "single-asset DM didn't reach Harvey" to "the predictability null is robust across crypto-equity-fear pairs." Conversely, if any of those alternative pairs produce a positive DM, the §8.2 narrative would need reframing.

**Recommended fix**: §6 robustness add a multi-asset OOS section with at least one additional crypto-equity-fear pair. Candidates: ETH-USD → VIX (most natural extension); BTC-USD → VSTOXX (geographic robustness); BTC-USD → VXN (NASDAQ fear). Engineering effort: 1-2 days using existing K1025 infrastructure. **This is a blocker for review-stage → ready_for_submission promotion** if the goal is IJFMIM/JEF placement; if FRL backup is acceptable then single-asset OOS can stand (FRL accepts shorter scope).

### Verdict gradient

- Issue 1: monitor only
- Issue 2: optional 2-sentence enhancement
- **Issue 3: blocker for top-tier (IJFMIM/JEF), acceptable for FRL backup**

---

## Overall Verdict & Stage Gate Assessment

### Stage gate criterion #3 (cross-paper meta-evaluation): **CONDITIONAL PASS**

The five stylized facts are mostly emergent (Section 1: PASS with minor framing fix); portfolio overlap with P9 is asset-level only and methodologically orthogonal (Section 2: PASS); the synthesis-type contribution lever is legitimate but currently understated in §1 framing (Section 3: CONDITIONAL PASS); the OOS null is a publication strength conditional on §5 carrying the empirical novelty (Section 4: PASS); same-author cluster risk is low and manageable via timing + cover letter (Section 5: CONDITIONAL PASS); structural integrity is generally sound but single-asset OOS is a top-tier blocker (Section 6: CONDITIONAL PASS).

**No fundamental issue identified that prevents review-stage status.** Three CONDITIONAL PASS verdicts each have specific suggested fixes; one is a top-tier blocker (multi-asset OOS for IJFMIM/JEF), two are framing improvements (contribution paragraph rewrite + subperiod boundary footnote).

### Recommendations for ready_for_submission promotion

**Mandatory (blocker for IJFMIM/JEF)**:
- Section 6 Issue 3: Add multi-asset OOS robustness to §6 (ETH→VIX or BTC→VSTOXX or BTC→VXN). 1-2 days engineering.

**Recommended (improves placement probability)**:
- Section 1 fix: §6.2 add subperiod boundary perturbation footnote (60-100 words).
- Section 3 fix: rewrite §1 contribution paragraph to lead with empirical novelty rather than method enumeration (80-150 word rewrite, single most impactful revision).

**Optional (polish)**:
- Section 4 minor: §7 forward-reference to §8.2 reconciliation (1 sentence).
- Section 6 Issue 2: §8.3 complementary-not-duplicative phrasing (2 sentences).

### Submission timing & portfolio scheduling

**Recommended ordering**:
1. **P9** (already under review): hold pending journal decision.
2. **P5** to FRL: submit when v2 review complete (per existing portfolio decisions).
3. **P6** to FRL: submit 4-6 weeks after P5 to decorrelate desk-rejection risk.
4. **P10** to IJFMIM: submit AFTER (a) multi-asset OOS robustness done, (b) §1 contribution rewrite done, (c) confirmed P9 is not at IJFMIM (or P9 has first decision). Estimated timing: **6-10 weeks from now** (2026-06-09 to 2026-07-07 window).
5. If IJFMIM rejects, P10 → JEF without major changes.
6. If JEF rejects, P10 → FRL with §6 multi-asset robustness trimmed and §8.2 reconciliation shortened (FRL has 12-page hard limit).

### Key recommendation summary

**P10 is structurally sound and v2 review work has been thorough; no critical research-honesty or methodology issues identified at cross-paper level. The single highest-impact pre-submission revision is multi-asset OOS robustness in §6 (1-2 days work), paired with the §1 contribution paragraph rewrite (no new evidence required). With both done, P10 is competitive for IJFMIM submission.**

---

## Cross-references

- v2 review verdict: `paper/crypto-fear-channel/review_history/v2/README.md`
- Portfolio decisions: memory `project_paper_portfolio_decisions_2026_04_27.md`
- NotebookLM cross-paper meta-eval rule: memory `feedback_paper_cross_paper_meta_eval`
- P10 status memo: `paper/crypto-fear-channel/research_notes/p10_status_2026_04_27.md`
- P5 ABM 70% threshold critique: NotebookLM 2026-04-27 (referenced in task brief)
- Comparison papers:
  - P5 `paper/vt-crowding-abm/main.tex`
  - P6 `paper/prg-periodic-garch/main.tex`
  - P9 `paper/garch-x-vix/main.tex`
- Source experiment: `experiments/k1025/` (reproduce GREEN 29/29)
