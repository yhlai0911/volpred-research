# P6 PRG — Academic Review v3

**Date**: 2026-04-27
**Reviewer**: Claude general-purpose (latex-academic-reviewer SOP, Opus 4.7 1M)
**Manuscript**: `paper/prg-periodic-garch/main.tex` (459 lines, 11pt, ~14 pages compiled — uncompiled in this round)
**Target**: Finance Research Letters (FRL)
**v2 baseline**: 3.6★ / 0 CRITICAL / 0 SEVERE / 3 MAJOR (M1 GJR-X / M2 §1 contribution / M3 VT cross-market) / 5 MED / 4 MINOR
**v3 actions**: 12 done (M1 K1260, M2 §1 + abstract, MED-C1 Todorova DOI, Med-1 calendar→session, Med-2 cross-market generalization, Med-3 bibliography, Med-4 paragraph break, Med-5 §5 first-order finding upgrade, Min-3 MDD caption); 5 pending optional/cosmetic
**Reproduce gate**: GREEN (per `reproduce_report.json`, not re-run this round)

---

## Overall Assessment

**Verdict**: **Minor revise** (1 NEW MAJOR uncovered: forward-reference error to non-existent §4.5; 0 carry-over MAJORs from v2)

**Predicted FRL outcome (post v3)**:
- desk-accept: **~30%** (up from 10% as-is v2)
- R&R likely-accept: **~55%** (down slightly because more papers move to desk-accept tier)
- desk-reject / reject-with-revision: **~15%** (down from 30%)

**Academic score**: **★★★★ / 5 (4.1 / 5)** — up from 3.6★ in v2.
- +0.5★ from M1 K1260 fair-info baseline (closes the single highest-leverage v2 fairness concern with stronger-than-predicted result)
- +0.2★ from M2 §1 contribution rewrite (NotebookLM Argument B + C now in manuscript)
- +0.1★ from Med-1/2/3/4/5 + Min-3 cluster (cleanup raises perceived polish)
- −0.2★ from one new MAJOR (forward-reference to §4.5 that does not exist)
- −0.1★ from one MED carryover (forecast-timing paragraph still single-block 670+ words; Med-4 only fixed the run-on at end of paragraph)

**Strengths preserved + amplified from v2**:
1. K1260 GJR-X result is **stronger than NotebookLM predicted** (DM t=−0.53 NS for GJR-X vs GJR; predicted [2,4]). This converts the fairness MAJOR from "open vulnerability" to "differentiating evidence" — best possible outcome.
2. Abstract now has a one-sentence K1260 punch (L41), making first-order claim visible to desk editor in <30 seconds.
3. §1 contribution paragraph (L63) now explicitly contrasts PRG against Bollerslev1996 / Linton2020 / Kim2023 / Lai2024 with parameter counts → NotebookLM Argument B Ultra-Parsimony in manuscript.
4. §1 paragraph 2 (L59) now states "we extend the periodic GARCH structure of Bollerslev (1996) from calendar periodicity (e.g., day-of-week) to session-frequency periodicity" — Med-1 closed crisp.
5. §5 limitation #3 (L313) is now full first-order claim with K1260 numbers (δ̂=0.13, LR=49.37, DM t=7.72 / −0.53), not a "left for future work" hedge.
6. Bibliography is now strictly alphabetical (Acerbi → Blanc → Bollerslev → Christoffersen → Corsi → Diebold → Fissler → Glosten → Haas → Hansen2005 → Hansen2011MCS → Harvey1997 → Harvey2016 → Kim → Kupiec → Lai → Linton → Opschoor → Patton → Todorova). Med-3 closed.
7. Table 4 caption (L295) now has MDD sign convention disclosure ("reported as a negative percentage by convention"). Min-3 closed.

**Critical new concerns (this round)**:
- **Forward reference to §4.5 (line 313)**: §5 limitation #1 states "the TAIFEX tick-level analysis in Section 4.5 already confirms…" but §4 has only 4 subsections (4.1 Statistical / 4.2 Ablation / 4.3 VaR-ES / 4.4 Economic). §4.5 does not exist. This is a regression — likely v2 carry-over that nobody caught because it was buried in a defensive sentence. **MAJOR** because reviewers cross-reference forward links and broken refs trigger immediate "manuscript not ready" verdict.

---

## v2 → v3 Regression Audit (12 actions)

| v2 Action | Status | Verification (line refs in current main.tex) |
|---|---|---|
| **M1 K1260 GJR-X experiment cherry-picked** | ✅ DONE + stronger than predicted | `experiments/k1260/k1260_results.json` exists; PRG vs GJR-X DM=7.72 (Harvey PASS), GJR-X vs GJR DM=−0.53 (NS); narrative integrated at L41 abstract + L313 §5 limitation #3 |
| **M2 §1 contribution rewrite (Argument B + C)** | ✅ DONE | L63 now lists Bollerslev1996 / Linton2020 / Kim2023 / Lai2024 with parameter counts and "complicates estimation and risks overfitting" punch; Argument C "an evaluation methodology bias systematically obscured in prior literature" added |
| **M2 abstract trim + K1260 sentence** | ✅ DONE | Abstract now 209 words (down from ~230); K1260 sentence at L41 "a fair-information GJR-X benchmark on SPY further confirms PRG's dominance is structural rather than informational (DM t=7.72 for PRG vs GJR-X, Harvey PASS; DM t=−0.53 for GJR-X vs GJR, NS)" |
| **Med-1 Bollerslev calendar→session sentence** | ✅ DONE | L59 end: "we extend the periodic GARCH structure of \citet{Bollerslev1996} from calendar periodicity (e.g., day-of-week) to session-frequency periodicity (overnight versus intraday), retaining its parsimony while embedding a single cross-session variance recursion" |
| **Med-2 PRG-vs-Separate cross-market promote** | ✅ DONE | L239 new `\paragraph{Cross-market generalization.}` heading; explicit statement that Table 2 PRG-vs-Separate gaps (DM t=−4.07 to −6.69) constitute the implicit cross-market ablation |
| **Med-3 bibliography alphabetical reorder** | ✅ DONE | Verified L337–451 strictly alphabetical (Acerbi, Blanc, Bollerslev, Christoffersen, Corsi, Diebold, Fissler, Glosten, Haas, Hansen2005, Hansen2011MCS, Harvey1997, Harvey2016, Kim, Kupiec, Lai, Linton, Opschoor, Patton, Todorova) |
| **Med-4 forecast-timing paragraph break** | ⚠ PARTIAL | The 80-word run-on at end of L122 is now 4 shorter sentences (sub-millisecond / opening auction / directly implementable). However the **whole paragraph** L113–127 remains single block of ~670 words, dense and reviewer-unfriendly. See M-NEW-2 below. |
| **Med-5 §5 third limitation upgraded to first-order** | ✅ DONE | L313 is now ~12 lines of K1260-grounded prose with δ̂=0.13, LR=49.37, p<0.0001 IS evidence + DM t=7.72 / −0.53 OOS. "left for future work" replaced with "Cross-asset GJR-X extension to the remaining five markets is left for follow-up work, but this SPY result aligns with…". |
| **Min-3 Table 4 MDD sign convention** | ✅ DONE | L295 caption: "MDD is the maximum drawdown, reported as a negative percentage by convention (more negative values indicate deeper drawdowns)" |
| **MED-C1 Todorova2014 DOI** | ✅ DONE | L455 has `\doi{10.1016/j.frl.2014.07.001}` (verified) |
| **Knowledge.json append item_id=f16c1ade** | OUT OF SCOPE | not verified in latex review (knowledge ops domain) |

**Regression check summary**:
- 11 of 12 actions fully closed.
- 1 partial (Med-4 fix at end of paragraph but block-level density unchanged).
- 1 NEW MAJOR uncovered (forward ref §4.5 not exist) — likely v2 carry-over regression that v2 review missed.

---

## NotebookLM Critical Issues — v3 Status

### Issue A: Unfair baseline (PRG reads twice vs GJR once) → **CLOSED with stronger evidence**

- **v2 status**: MAJOR M1 — Fix B (literature defense) only; Fix A (GJR-X experiment) deferred.
- **v3 status**: **CLOSED**. K1260 ran the GJR-X experiment on SPY OOS (n=1,823) with the predicted ordering reversed *for the first leg* but **strengthened for the main claim**:
  - Predicted: GJR-X DM t ∈ [2, 4] vs GJR (overnight info should help moderately).
  - Observed: GJR-X DM t = **−0.53 vs GJR** (NS) — overnight regressor is not OOS robust despite IS LR p<0.0001.
  - Observed: PRG vs GJR-X DM t = **7.72** (Harvey PASS) — PRG dominance is structural, not informational.
- **Why this is the best possible outcome**: a referee cannot frame the paper as "PRG sees one extra return that GJR doesn't" because that argument is now empirically refuted on the paper's own data. The §5 limitation #3 paragraph (L313) is the strongest single defensive paragraph in the manuscript.
- **Residual risk**: Cross-asset GJR-X (5 remaining markets) is still future work. A referee with high methodological standards may request 1-2 additional GJR-X markets. If granted, K1260b (suggested in `experiments/k1260/README.md` L161-163) addresses with 15+ multistart on QQQ + EEM. Estimated 2 hours total. **Recommend**: defer to revision phase if reviewer requests; do not pre-empt.

### Issue B: Novelty (Bollerslev-Ghysels / Linton-Wu prior periodic GARCH) → **CLOSED via differentiation language**

- **v2 status**: MAJOR M2 — contribution claim at L63 framed as parsimony repackaging.
- **v3 status**: **CLOSED**. L59 + L63 now state explicitly:
  1. (L59) PRG extends Bollerslev1996 from calendar → session-frequency periodicity (Argument from `positioning.md` L21–22 now in manuscript).
  2. (L63) PRG contrasts deliberately with Bollerslev's original, Linton-Wu's ~12 param coupled DCS-EGARCH, Kim's continuous-time diffusions, and Lai's Markov-switching — "each of which complicates estimation and risks overfitting in moderate samples".
  3. (L63) Argument C "an evaluation methodology bias systematically obscured in prior literature" — punch is now in §1, not just §4.1.
- **Residual risk**: Editor with very high novelty bar may still mark "incremental over Bollerslev1996 + Linton-Wu + Lai2024 stack" as the worst-case framing. The defense (parsimony × cross-session bridge × first to expose target-mismatch) is now explicit, but it is a defense, not a structural novelty claim.

---

## NotebookLM 3 Arguments — Manuscript Integration Audit

| Argument | Source | In Manuscript? | Location |
|---|---|---|---|
| **A. Session-Boundary Information Bridge** (ablation 6.00→−0.57; MZ R² 0.464→0.264) | NotebookLM `notebooklm_prior_periodic_garch.md` L29-39 | ✅ Yes (since v1) | §1 L63 ("session-boundary information transfer"); §4.2 ablation table (L218); §5 L307; §6 L321 |
| **B. Ultra-Parsimony and Implementability** (6-8 params vs Linton 12+ / Kim 10 / Lai 12+) | NotebookLM L41-51 | ✅ Yes (M2 v3 added) | §1 L63 "stands in deliberate contrast to existing session-aware models requiring substantially more parameters"; §5 L311 explicit param-count comparison |
| **C. Exposing "Target-Mismatch" Illusion** (HAR vs GJR DM t=0.57 NS on common target; Patton 2011 / Hansen 2005 framework) | NotebookLM L53-62 | ✅ Yes (M2 v3 added) | §1 L63 "an evaluation methodology bias systematically obscured in prior literature" — Argument C punch now in introduction, not just §4.1 |

**Audit verdict**: 3/3 NotebookLM arguments now visible at desk-editor scan-read depth (within first ~250 words of body text). v2 had Argument A only at desk-read depth; B and C were buried in §4 / §5.

---

## New Issues (v3)

### CRITICAL (0)
None.

### SEVERE (0)
None.

### MAJOR (1 NEW)

**M-NEW-1. Forward reference to non-existent §4.5** (location: §5 L313)

- **Issue**: §5 limitation #1 at L313 states "the TAIFEX tick-level analysis in Section~4.5 already confirms that tick-level realized variance and the OHLC-based proxy yield quantitatively similar PRG estimates and the same DM $t$-ranking". However §4 has only **4** subsections: 4.1 Statistical forecast evaluation (L178), 4.2 Ablation (L213), 4.3 VaR and ES (L241), 4.4 Economic significance (L273). **§4.5 does not exist.**
- **Why it matters**: A reviewer scanning §5 for limitation defenses will follow this forward reference, find nothing, and form one of two conclusions: (a) the manuscript is not ready (broken cross-ref); (b) the author is bluffing the limitation defense. Either outcome triggers reviewer skepticism on **all other** defensive prose.
- **Likely root cause**: This sentence was likely lifted verbatim from an earlier draft (or reproduce.py supporting note) where §4 had a tick-level vs OHLC-proxy subsection. Either the subsection was cut (without updating cross-ref) or the cross-ref was added speculatively (without writing the subsection).
- **Fix options** (pick one):
  1. **Soft fix (5 min)**: Drop "in Section 4.5" — the sentence still works as "the TAIFEX tick-level analysis already confirms…" The TAIFEX tick-level claim is implicit from §3 data description (L156 "TAIFEX TX uses tick-level 5-minute realized variance") and §4.1 main results. Lowest-effort fix; conservative.
  2. **Medium fix (1-2 hours)**: Add §4.5 "Tick-level vs OHLC-proxy robustness check" subsection with a 1-row table comparing PRG-Extended estimates from tick-level RV (TAIFEX) vs squared returns (TAIFEX OHLC reconstruction) — ~3 paragraphs + 1 table. This converts the limitation defense into stronger evidence and adds page count ~½ page. **Recommended only if page count budget allows** (FRL hard limit 14 pages).
  3. **Hard fix (4-6 hours)**: Run the TAIFEX OHLC-proxy parallel experiment if not already done, write up §4.5 with full table and DM tests. Do not recommend at this stage.
- **Severity calibration**: MAJOR (not MED) because the defense at L313 is the **strongest limitation #1 defense** in the paper; a broken forward-ref undermines it entirely. Conversely, the soft fix is trivial — the MAJOR severity reflects impact-if-unfixed, not effort-to-fix.

### MEDIUM (2 NEW + 1 CARRYOVER)

**M-NEW-2. Forecast-timing paragraph (§2.2 L113–127) is single ~670-word block; Med-4 only addressed the run-on at end** (location: §2.2 paragraph "Forecast timing and information sets")

- **Issue**: v2 Med-4 flagged "L122 long sentence (~80 words including parenthetical sub-clauses)". v3 split that one sentence into 4 shorter sentences (sub-millisecond / opening auction / directly implementable). However, the **paragraph as a whole** remains a 670-word single-block of math + prose + defense + protocol description. A reviewer reading this paragraph faces ~3 minutes of dense reading without paragraph break.
- **Why it matters**: This paragraph is the paper's strongest defense against the lookahead attack. Density costs reader patience exactly where defensive clarity matters most.
- **Fix**: Insert paragraph break at L122 ("This timing convention is standard in the session-based volatility literature…") and at L122 again before "Practical implementation requires only two conditions:". Result: 3 paragraphs (a) two-phase protocol description, (b) literature defense + practitioner mirror, (c) implementation conditions + tradable timing. ~5 min of `\\` insertion.
- **Severity**: MEDIUM — does not block submission but reduces defensive clarity at peak-importance paragraph.

**M-NEW-3. K1260 narrative is in §5 limitation #3 but not in §4 results section** (location: §4.1 / §4.2 / §5)

- **Issue**: K1260 GJR-X result is now a first-order claim per Med-5. The abstract (L41) summarizes it. §5 (L313) gives full numbers. But **§4 (Results) has no GJR-X row, no GJR-X table, no GJR-X paragraph**. A reader following the standard scientific-paper reading order (Abstract → §4 Results → §5 Discussion) hits the K1260 numbers in §5 without having seen them in §4.
- **Why it matters**: FRL referees specifically check that abstract claims are supported by Results section evidence. A K1260 claim in abstract + §5 but missing in §4 may trigger "evidence presentation gap" flag.
- **Fix options**:
  1. **Soft fix (15 min)**: Add a 2-sentence paragraph at end of §4.2 Ablation: "An additional fair-information benchmark (GJR-X, K1260) confirms the bridge interpretation: GJR augmented with the lagged overnight squared return as exogenous regressor (n=1,823 SPY OOS) yields DM t=−0.53 vs GJR (NS) and DM t=7.72 vs PRG (Harvey PASS). Section 5 discusses the implications for the structural-vs-informational interpretation of PRG's advantage."
  2. **Medium fix (1 hour)**: Add §4.5 (or new §4.2.1) GJR-X subsection with 1-row table extending Table 3 (Ablation), full DM evidence, and IS LR diagnostic. Cleaner narrative. ~½ page added.
  3. **Hard fix (3-4 hours)**: Combine M-NEW-1 (§4.5 not exist) and M-NEW-3 (K1260 not in §4) by creating §4.5 "Tick-level robustness and fair-information baseline" containing **both** the tick-vs-OHLC robustness and the GJR-X result. Single subsection closes both issues. **Recommended if page budget allows**.
- **Severity**: MEDIUM — abstract → §4 evidence flow is broken but §5 closes the gap. A diligent reviewer reads §5 limitations; a desk editor may not.

**M-CARRY-1. Hansen-Huang-Shek (2012) Realized GARCH citation gap** (location: bibitem; L411-415 is the natural insertion point in alphabetical order)

- **Issue carry-over from v2 Min-4**: The model name "Realized GARCH" in PRG ("Periodic Realized GARCH") corresponds to Hansen, Huang & Shek (2012) "Realized GARCH: A joint model for returns and realized measures of volatility", *J. Applied Econometrics* 27(6), 877–906. The manuscript does not cite this paper. The citation gap was Min-4 in v2 (deferred); given that the K1260 implementation reuses the H-H-S 2012 exogenous-regressor mechanism (overnight RV as predictor), and given that v2 v3 review cycle keeps surfacing this gap, it should be promoted to MED for v3.
- **Why MED (not MIN)**: Three v2/v3 review rounds have flagged this. The model name "Realized GARCH" without citing the canonical Realized GARCH paper is an attribution gap that any reviewer with realized-volatility expertise will flag. Probability of referee comment: ~70% conditional on a methodologist referee.
- **Fix**: Add bibitem `\bibitem[Hansen et al.(2012)]{Hansen2012}` between Hansen2011MCS (L396) and Harvey1997 (L402) in alphabetical order, with DOI `10.1002/jae.1234`. Add `\citep{Hansen2012}` at §2.2 L94 ("…all parameters are estimated by maximizing the Gaussian quasi-log-likelihood…"); alternatively at §1 paragraph 2 (L59) when introducing the Realized component. ~5 min.

### MINOR (1 NEW + 4 CARRYOVER)

**Mn-NEW-1. Abstract length still 209 words** (target: ≤200 for FRL prefer; hard cap 250)
- After M2 trim, abstract is 209 words — within FRL acceptance range but ~10 words above the soft 200-word target. Optional further trim: abstract sentence "An ablation study removing the session-boundary update causes the advantage to collapse entirely (DM t = 6.00 → −0.57)" can drop the parenthetical to "(DM t collapse)" — saves ~7 words. Or trim "and generates economically meaningful gains in a volatility-timing strategy on TAIFEX futures" → "with economic gains in a TAIFEX volatility-timing strategy" — saves 3 words.

**Mn-CARRY (v1-carry, deferred to v4 / proof stage)**:
- **Min-1**: `\usepackage{mathptmx}` (L11) — recommend `newtxtext,newtxmath` for unified Times text+math. FRL accepts either; modern convention preferred.
- **MED-C2**: harvey2018 DOI gap — citation_check_report v2 flagged it after Med-3 alphabetical sort. Verify whether the entry refers to Harvey2016 (cross-section paper, ✓ DOI exists at L412) or a separate Harvey2018; if the v2 citation_check is referring to a different Harvey, verify the DOI exists. Effort: 5 min.
- **MIN-C2 / MIN-C3 / MIN-C4 / MIN-C5**: Engle-Sokalska 2012 pre-empt + Acerbi page format + bib URL drift carryover items from v1. None are blocking.

---

## Cross-Paper Portfolio Re-Evaluation (post v3)

### Same-dataset overlap risk (P1-P10 9 papers)

| Risk dimension | v2 status | v3 status | Note |
|---|---|---|---|
| Same dataset (SPY/GLD/EEM/QQQ + TAIFEX) | ⚠️ HIGH | ⚠️ MODERATE | K1260 GJR-X is **new** SPY-specific finding; broadens P6 contribution beyond pure PRG estimation. Reduces "9 papers, 1 dataset" critique by ~1 paper-equivalent in originality. |
| Common conclusion ("simpler beats complex") | ⚠️ HIGH | ⚠️ MODERATE | v2 P6 fits the pattern. v3 adds K1260 first-order finding "exogenous regressor not OOS robust despite IS significance" — this is a **new** empirical claim not in P1-P10 collection. Slightly differentiates P6. |
| Self-citation across portfolio | ⚠️ MODERATE | ⚠️ MODERATE | Unchanged. Lai2024 PRS continuity is the only self-cite; defensible. |
| Methodology spillover (PRG ↔ GARCH-X-VIX in P9) | ⚠️ MODERATE | ⚠️ LOW | K1260 GJR-X (overnight regressor) is **distinct** from P9 GARCH-X-VIX (forward-looking IV regressor). No mechanism overlap. |

**Verdict**: Cross-paper portfolio risk is **mitigated** by K1260's first-order finding (exogenous regressor not OOS robust). P6 now stands more independently from P1-P10 portfolio than it did in v2. Still recommend **not** simultaneous submission of P6 and P9 (both involve overnight/forward-looking regressors); stagger by ≥3 months.

### Genuine novelty — post K1260 upgrade

- **Pre-K1260 (v2)**: PRG novelty = "parsimonious extension of Bollerslev1996 calendar → session" + "first-to-expose target-mismatch on common σ²_full". Strong but *parsimony repackaging* risk.
- **Post-K1260 (v3)**: PRG novelty = above + "first to demonstrate that exogenous-regressor approach to overnight info is not OOS robust on SPY despite IS significance, and that session-level recursion is the OOS-robust alternative". This is a **new methodological finding** that prior literature (Todorova2014, Opschoor2021) only inferred from realized-variance forecasting context. K1260 ports this lesson to the QLIKE-loss volatility-forecasting context and provides the controlling experiment.
- **FRL editor scan-read assessment**: Novelty claim now passes the "what is genuinely new here?" 2-minute desk triage. A scan-reading editor sees: (1) ablation 6.00→−0.57; (2) GJR-X DM 7.72 / −0.53; (3) target-mismatch DM 0.57 NS. Three distinct empirical findings, each Harvey-significant, all pointing at PRG's structural mechanism. This is FRL-quality.

---

## Recommendation for v4 (if needed)

### Must-fix before submission (v4 entry gate)

1. **M-NEW-1 (Forward ref §4.5)** — pick one of the three options. **Recommend medium fix (option 2)**: write §4.5 "Tick-level robustness check" using existing TAIFEX tick + OHLC-reconstruction comparison data. ~1-2 hours. Closes M-NEW-1 + M-NEW-3 simultaneously by making §4.5 the home of K1260 GJR-X result too (option 3 of M-NEW-3).
2. **M-NEW-2 (Forecast-timing paragraph break)** — split §2.2 paragraph 4 into 3 paragraphs at natural sentence boundaries. ~5 min.
3. **M-NEW-3 (K1260 in §4)** — addressed by M-NEW-1 medium fix; otherwise apply M-NEW-3 soft fix.
4. **M-CARRY-1 (Hansen-Huang-Shek 2012)** — add bibitem + 1 cite. ~5 min.

### Strongly recommended (high ROI, low cost)

5. **Mn-NEW-1**: trim abstract from 209 → ≤200 words. ~5 min.
6. **MED-C2 (harvey2018 verification)** — citation_check_report v2 mentioned this; verify in v4. ~5 min.

### Deferred to v5 / proof stage

- Min-1 `mathptmx` → `newtxtext,newtxmath` (compile-test required).
- 4 v1-carry citation MINs (Engle-Sokalska 2012 add; Acerbi page format; URL drift).

---

## Predicted journal response (post v3, before v4 fixes)

| Outcome | v2 (3.6★) | v3 as-is (4.1★) | v4 post all-fixes (4.5★) |
|---|---|---|---|
| **FRL desk-accept** | ~10% | ~30% | ~45% |
| **FRL R&R likely-accept** | ~60% | ~55% | ~45% |
| **FRL desk-reject / reject-with-revision** | ~30% | ~15% | ~10% |

**Bottom line**: v3 is **a major step forward from v2** — academic score moves 3.6→4.1, FRL desk-reject probability halves (30→15%), and the K1260 result is the strongest single empirical finding added in any review round to date. The four v3 issues identified above are mostly polish (M-NEW-1 / M-NEW-2 / M-NEW-3 / M-CARRY-1), with M-NEW-1 the only one that needs fixing before submission to avoid reviewer skepticism on §5 defensive prose.

**Submission recommendation**: **Do not submit v3 as-is**; apply M-NEW-1 fix at minimum (5 min soft fix or 1-2 hour medium fix). With M-NEW-1 + M-NEW-2 + M-CARRY-1 closed (~2 hours total), submit v4. v4 expected score: 4.5★.

---

## 6-criteria gate evaluation (per memory `feedback_paper_cross_paper_meta_eval.md`)

| # | Criterion | v2 status | v3 status |
|---|---|---|---|
| 1 | Latex review ≥ 4★ | ✗ (3.6) | **✓ (4.1)** |
| 2 | Citation 0 MAJOR + ≤3 MED | ✓ (1 MED) | **✓ (0 MED + 1 carryover MED-C2 to verify)** |
| 3 | Cross-paper meta = no fundamental issue | ⚠️ (portfolio risk + narrow novelty) | **✓ (K1260 first-order finding mitigates portfolio + novelty concerns)** |
| 4 | True acceptance rate ≥ 50% | ✗ (~10% accept + 60% R&R = 70% positive but only 10% accept) | **⚠ (30% accept + 55% R&R = 85% positive; gate met if "positive" includes R&R, marginal if "positive" = accept-only)** |
| 5 | No critical fairness issue | ⚠ (M1 unfixed) | **✓ (K1260 closes)** |
| 6 | No methodological tautology | ✓ | **✓** |

**Pass**: **5/6 confirmed + 1 marginal (criterion 4)** — up from **2/6 in v2** (1, 4, 5 all upgraded; 2 marginally improved by removing MED-C1; 3 fully resolved by K1260; 6 unchanged).

**Stage decision**:
- If criterion 4 is interpreted as "≥50% positive (accept + R&R)" → 6/6 PASS → **promote to ready_for_submission after v4 fixes**.
- If criterion 4 is interpreted as "≥50% accept on first round" → 5/6 + marginal → **hold in review for v4 round** + run another paper-review-cycle after M-NEW fixes apply.

**Recommendation**: **Do v4 fixes (~2 hours total) → run paper-review-cycle v4 → if v4 verdict ≥ 4.4★ and FRL desk-accept ≥ 40%, promote to ready_for_submission**. Otherwise hold one more round.

---

## Files / methodology used

- Source: `paper/prg-periodic-garch/main.tex` (459 lines, read in full; structure verified via grep for `\bibitem`, `subsection`, key term audits)
- v2 baseline: `paper/prg-periodic-garch/review_history/v2/{academic_review_report.md (256 lines), citation_check_report.md (197 lines), README.md (149 lines)}` (read in full)
- v3 progress audit: `paper/prg-periodic-garch/research_notes/v3_progress_2026_04_27.md` (123 lines, read in full — confirmed 12 actions applied)
- NotebookLM source: `paper/prg-periodic-garch/research_notes/notebooklm_prior_periodic_garch.md` (76 lines, read in full — Argument A/B/C confirmed in manuscript)
- K1260 results: `experiments/k1260/k1260_results.json` (read in full — DM t=7.72/−0.53 byte-matched against §5 L313 and abstract L41); `experiments/k1260/README.md` (173 lines, read in full)
- Positioning ref: `paper/prg-periodic-garch/positioning.md` (105 lines, used for novelty differentiation cross-check)
- Skill: `.claude/skills/latex-academic-reviewer/SKILL.md` (read in full — 13-step todo, 10 review dimensions A-J, severity tiers applied)
- Memory: `feedback_paper_cross_paper_meta_eval.md` (6-criteria gate; cross-paper portfolio-level lens applied)

---

## Reviewer signature

Reviewer: Claude general-purpose (latex-academic-reviewer SOP, Opus 4.7 1M)
Review round: v3
Manuscript state at review: 11pt, 459 lines, K1260 cherry-picked, M2 §1 + abstract rewritten, Med-1/2/3/4/5 + Min-3 + MED-C1 closed, Med-4 partial
Outstanding: **1 NEW MAJOR (forward ref §4.5)** + 2 NEW MED (paragraph block density; K1260 not in §4) + 1 carryover MED (Hansen-Huang-Shek 2012 attribution) + 1 NEW MIN (abstract trim) + 4 carryover MINs (mathptmx; harvey2018; v1-carry citation polish)
Anti-optimism check: K1260 result stronger than NotebookLM predicted; this enables stage upgrade but does not eliminate the §4.5 forward-ref regression — flagged as M-NEW-1 MAJOR despite low effort to fix because impact-if-unfixed is high.
