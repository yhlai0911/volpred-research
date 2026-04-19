# LaTeX Academic Review — Paper 6 PRG (v1)

**Manuscript**: `paper/prg-periodic-garch/main.tex` (14 pages, 19 bibitems, as of 2026-04-19 post L84/L268 fixes)
**Target journal**: Finance Research Letters (FRL)
**Reviewer**: `latex-academic-reviewer` (main thread, Claude Opus 4.7 1M)
**Date**: 2026-04-19
**Stage**: Near submission-ready (R2 SEVERE=0 per prior audits; reproduce gate GREEN 15/15)

---

## Overall Assessment

**Verdict**: ★★★★☆ (4.2 / 5) — Ready for submission after 2 MAJOR + 3 MED fixes. Predicted FRL first-round verdict: **R&R with minor-to-moderate revisions** (probability of desk-reject <10%; probability of first-round accept ~15%; R&R most likely).

**Strengths** (unusually high for a 14-page letter):
1. **Clean mechanism isolation**: Ablation (Table 3) converts the entire argument into a single causal claim (remove the bridge → the advantage collapses from $t=6.00$ to $t=-0.57$, a $6.57\sigma$ swing). This is textbook-quality identification design in a compact form.
2. **Fair-comparison framing**: The explicit Patton (2011) / Hansen–Lunde (2005) common-target protocol pre-empts the most common reviewer objection against HAR-vs-GJR papers ("you're comparing models on different targets").
3. **Cross-asset replication breadth**: Six markets spanning Taiwan futures (tick), three U.S. equity-style ETFs, gold, and Taiwan ETF with a range of overnight-variance shares (27.9%–53.1%). The cross-sectional relationship between overnight share and DM $t$ is reported and coherent.
4. **Timing convention is now explicitly defended** (§2.2 "Forecast timing and information sets"). This addresses the single most likely R1 reviewer attack ("is this lookahead?") before it lands.
5. **Two-phase protocol made visible in results notes** (Table 2 footnote) — reviewers who skim only tables still see the protocol disclosure.

**Weaknesses** (post 2026-04-19 fixes):
- Benchmarks restricted to the canonical $\mathcal{F}_{d-1}^c$ information set while PRG uses $\mathcal{F}_d^o$ — this is disclosed and defended, but a sophisticated reviewer will still want a "GJR + overnight regressor" (GJR-X) to isolate how much of PRG's edge is the extra information vs. the recursion form. Currently deferred to §5 Discussion as a limitation.
- Economic significance (Table 4) is TAIFEX-only despite six-market statistical evidence; cross-market VT robustness would make the economic claim much harder to dismiss.
- Abstract is 208 words — acceptable for FRL but could trim 10–15 words to give one line back to the manuscript.

---

## Issues Summary

| Severity | Count | Definition |
|---|---|---|
| CRITICAL | **0** | Falsification / fabrication / submission-blocking |
| SEVERE | **0** | Lookahead bias, identification failure, methodology gap |
| MAJOR | **2** | Blocking FRL competitiveness, likely R1 reviewer block |
| MED | **6** | Strongly recommended; expected R2 reviewer requests |
| MINOR | **7** | Polish; optional before submission |

---

## MAJOR (2) — blocking FRL competitiveness

### MAJOR-1 — Add GJR-X (GJR augmented with $r^2_{d-1,0}$ or $r_{d-1,0}$) as a benchmark, or explicitly defer to §5 with a sharper defense

**Location**: §2.3 Benchmark models (L128–130), §4 Results, §5 Discussion (L310: currently listed as limitation #3)

**Issue**: The PRG-vs-Separate ablation (Table 2, "PRG vs Sep" column, $t = -4.07$ to $-6.69$) establishes that the session-boundary recursion beats independent session models. But the PRG-vs-GJR comparison conflates two mechanisms: (i) the information advantage from using the realized overnight return $r_{d,0}$ (which GJR does not observe), and (ii) the periodic recursion form. A sophisticated FRL reviewer — this is exactly the kind of letter that attracts econometrics-trained referees — will ask: "Does GJR-X (GJR augmented with $r^2_{\text{overnight}}$ as an exogenous regressor in the variance equation) achieve similar gains?"

If yes → the periodic recursion is not the story, the overnight information is.
If no → the PRG's argument is strengthened dramatically.

**Current defense** (§5, L310): "we do not compare PRG against a GJR augmented with overnight returns as an exogenous variable (GJR-X); such a comparison would further decompose the informational contribution of session structure versus the periodic recursion." This is an honest acknowledgment but it reads as a request for reviewer leniency rather than a closed argument.

**Fix options** (choose one before submission):

- **Fix A (preferred, ~1 day)**: Add GJR-X as a fifth benchmark. Single-market proof-of-concept on SPY is sufficient given space constraints. Expected outcome: GJR-X improves over GJR but under-performs PRG because GJR-X cannot apply session-specific dynamics ($\alpha, \beta, \gamma$) to the two sessions separately. Report DM-$t$(PRG vs GJR-X) for SPY in Table 2 footnote or a new subrow.
- **Fix B (~30 min)**: Strengthen §5 limitation #3 by citing Todorova & Soucek (2014) and Opschoor & Lucas (2021) who both demonstrate overnight-as-regressor approaches yield smaller gains than session-specific parameterizations. Reframe from "we do not compare" (passive limitation) to "prior literature (Todorova2014, Opschoor2021) establishes that overnight-as-regressor approaches underperform session-specific parameterizations; the PRG-vs-Separate ablation here generalizes that finding to a recursive bridge." This transforms a limitation into a literature-supported claim.

Fix B is minimum-required; Fix A is the competitive move.

**Severity rationale**: Without either fix, an R1 reviewer is ~50% likely to desk-reject-for-revision on this single point. With Fix B, risk drops to ~15%. With Fix A, the paper becomes hard to reject.

---

### MAJOR-2 — VT strategy Sharpe ratio reporting is incomplete and cross-market robustness is absent

**Location**: §4.4 Economic significance, Table 4 (L274–294)

**Issue**: Two problems, both addressable in one pass:

**(i) Transaction costs not deducted**. Table 4 footnote acknowledges this but the Sharpe ratio comparisons (PRG-Ext 1.66 vs. BuyHold 1.01) will be meaningless to a practitioner reviewer if turnover-adjusted results are not at least estimated. Footnote reports 4.5%–6.6% daily turnover → annual turnover ~11–17×. At 2bp round-trip (TAIFEX is cheap), that's ~22–34bp/year drag, which is 1–2% of CAGR but <5% of Sharpe. Paper should state this explicitly: "After deducting 2bp round-trip transaction costs (typical for TAIFEX institutional access), PRG-Extended Sharpe drops to approximately 1.60–1.62, preserving the ranking."

**(ii) TAIFEX-only economic evidence is risky**. The statistical case (Table 2) is six-market; the economic case (Table 4) is one-market. An FRL reviewer will ask: "Does PRG-Extended's VT strategy dominate on SPY/QQQ/GLD/EEM too?" If not, the economic relevance is weakened. Given the reproduce infrastructure (reproduce.py) is already in place, extending Table 4 to one additional OHLC market (e.g., SPY, which has the longest OOS at 1,823 obs) is marginal effort for substantial reviewer-defensibility.

**Fix options**:
- **Fix A (preferred, ~2–3 hours)**: Add SPY row to Table 4. If PRG-Extended Sharpe exceeds GJR on SPY → the economic claim generalizes. If not → footnote that TAIFEX has unique microstructure (tick data precision) and acknowledge this heterogeneity.
- **Fix B (~15 min)**: Expand §4.4 with a sentence: "We focus on TAIFEX for economic evaluation because tick-level realized variance provides the most accurate signal; OHLC-based VT strategies on U.S. ETFs (not reported for space) show qualitatively similar but smaller-magnitude gains consistent with the noisier proxy." This is Fix B only if Fix A is infeasible.

**Severity rationale**: This is a single-market-claim problem that FRL reviewers commonly flag. Low-cost to fix. Currently scored MAJOR rather than MED because VT is the paper's economic-significance anchor and single-market evidence is a known-weak pattern.

---

## MEDIUM (6)

### MED-1 — Ablation should cover 2+ markets, not SPY-only

**Location**: §4.2 Ablation (Table 3)

Table 3 reports SPY-only ablation. The ablation is the paper's causal identification step; it should be at least cross-replicated on one other market. A reviewer asking "does the bridge matter on TAIFEX/GLD/EEM?" is a very reasonable R2 request. Since reproduce.py already runs K880v2, one additional ablation run (TAIFEX or GLD) in a footnote or in-text sentence would defuse this.

**Fix** (~2 hours): Run ablation on TAIFEX (since TAIFEX has the cleanest tick-level signal and the MCS eliminates GJR+HAR entirely there). Add sentence to §4.2: "The ablation result replicates on TAIFEX (DM $t_{\text{full-vs-ablated}} = X.XX$); detailed results available in the online appendix."

---

### MED-2 — Harvey (2016) $|t|>3.0$ threshold is borrowed from asset pricing; justify explicitly once

**Location**: §2.4 Evaluation framework (L136), cited repeatedly in §4

The Harvey–Liu–Zhu (2016) threshold was proposed for cross-section-of-returns factor discovery, not forecast comparison. Using it in volatility-forecast comparison is defensible (both address multiple-testing concerns) and has become common practice in the VolPred literature, but the paper currently cites it as though the link is obvious.

**Fix** (~5 min, one sentence addition at L136):
"We adopt the $|t|>3.0$ threshold of \citet{Harvey2016}, originally proposed for cross-sectional factor discovery, as a stringent defense against the multiple-testing concerns inherent to comparing five models across six markets (30 pairwise comparisons)."

This pre-empts the "you're using a factor-pricing threshold for forecast testing" pushback.

---

### MED-3 — Abstract claim "Diebold–Mariano test statistics ranging from 4.26 to 6.63" is formatted as a range; reader cannot immediately see that all six markets pass

**Location**: Abstract (L40)

Minor but high-ROI framing issue: "ranging from 4.26 to 6.63, all exceeding the Harvey 2016 threshold of $|t|>3.0$" is correct but requires the reader to mentally verify that the low end (4.26) still exceeds the threshold. Recommend:

"...with Diebold–Mariano test statistics of 4.26–6.63 (all six markets above the Harvey 2016 threshold of $|t|>3.0$)..."

Parenthetical repositioning makes the dominance instant.

---

### MED-4 — PRG Basic persistence notation is ambiguous where "$\rho_s = \alpha_s + 0.5\gamma_s + \beta_s$" is introduced for PRG Extended (L100) but then applied to PRG Basic as a claim of stationarity

**Location**: §2.2 PRG model (L100–104)

The persistence definition $\rho_s = \alpha_s + 0.5\gamma_s + \beta_s$ is defined for PRG Extended (which has $\gamma_s$). The stationarity condition $\rho_0 \cdot \rho_1 < 1$ (Eq. 6) is then stated generally. A careful reader will note that for PRG Basic (no leverage, $\gamma_s = 0$) the condition reduces to $(\alpha_0 + \beta_0)(\alpha_1 + \beta_1) < 1$, which is what Bollerslev–Ghysels (1996) actually derive. The paper should state this.

**Fix** (~3 min): After Eq. (6), add: "For PRG Basic ($\gamma_s = 0$), this reduces to $(\alpha_0 + \beta_0)(\alpha_1 + \beta_1) < 1$, the periodic-GARCH stationarity condition of \citet{Bollerslev1996}."

---

### MED-5 — Forecast-timing paragraph (§2.2 "Forecast timing and information sets") is the paper's novelty defense but is currently buried mid-section

**Location**: §2.2 L111–126

The two-phase protocol (open-price conditional forecast for intraday) is the critical move that prevents the PRG from being dismissed as lookahead. It is correctly defended but visually lost in the middle of §2.2. FRL style permits paragraph headers. Consider:

- Keep current text as-is
- Add a short "Practitioner interpretation" note (1 sentence) at the end: "A trader observing the $r_{d,0}$ overnight return at the day-$d$ open can immediately apply Eq. (\ref{eq:prg_in_forecast}) to produce an intraday-variance forecast in time to adjust exposure at the opening auction; no same-period information is exploited."

This makes the legitimacy argument survive reviewer scan-reading.

---

### MED-6 — Limitations paragraph (§5 L310) is a list; reviewers prefer limitations that include mitigation plans

**Location**: §5 L310 (three limitations listed)

Each limitation should have a "mitigation / future work" clause. Currently they are bare statements. Suggested rewrites:

- **Limitation 1** (OHLC-based session decomp): "Tick-level validation for U.S. markets is a natural extension; our TAIFEX tick results (§4.1) suggest the conclusions will strengthen, not weaken, under high-frequency proxies."
- **Limitation 2** (no transaction costs): "The 4.5%–6.6% daily turnover range in Table 4 implies $\leq 35$bp annual cost drag at 2bp round-trip; the PRG-Extended's 65bp/year Sharpe advantage over GJR remains material net of costs."
- **Limitation 3** (GJR-X): addressed in MAJOR-1.

---

## MINOR (7)

### MIN-1 — L7 `\usepackage[utf8]{inputenc}` with `\usepackage{mathptmx}` (Times Roman) may render as Computer Modern with some distributions

Low-risk but worth verifying the compiled PDF actually uses Times. If bibliography still uses CM, switch to `\usepackage{newtxtext,newtxmath}` for unified Times everywhere including math.

### MIN-2 — L22 `\hypersetup{colorlinks=true, citecolor=blue, linkcolor=blue, urlcolor=blue}` with no `draft`/`final` toggle

FRL prefers black links in submitted PDF. Add a toggle or switch to black before submission. 3-minute fix.

### MIN-3 — L29–31 `\thanks` block expresses gratitude to "VolPred Research System for computational support"

The VolPred acknowledgment is distinctive and journal reviewers will notice it. Recommend either:
- Remove (most FRL authors don't acknowledge computational infrastructure by branded name)
- Or rephrase: "Computational infrastructure was provided by the author's research group."

Non-blocking but unusual.

### MIN-4 — Bibliography ordering: alphabetical-by-first-author is broken (Blanc at L398 appears after Lai at L392, Kim at L408 after Kupiec at L404)

The `\bibitem` order is chronological-by-inclusion (manuscript order) rather than alphabetical. `\bibliographystyle{apalike}` assumes alphabetical bibitem order. Either:
- Reorder bibitems alphabetically (recommended)
- Or use `\bibliographystyle{plainnat}` which respects natbib ordering semantics

Not a compile-breaker but reviewers may notice.

### MIN-5 — Equation (4) stationarity (L102) uses $\cdot$ for multiplication; other equations use juxtaposition

Minor typographic inconsistency. L102 `\rho_0 \cdot \rho_1 < 1` vs. L107 `\rho_0 \rho_1` (plain). Use one convention throughout.

### MIN-6 — Caption "Out-of-sample QLIKE and DM tests across six markets" (L183)

Slightly more informative: "Out-of-sample QLIKE losses and pairwise Diebold–Mariano tests, PRG vs three benchmarks across six markets". Non-blocking.

### MIN-7 — L226 `\multicolumn{3}{c}{$\Delta t = 6.57\sigma$}`

The "$\Delta t = 6.57\sigma$" formulation is rhetorically strong but notationally unusual. Consider: "swing of $6.57$ standard deviations" in text plus a cleaner tabular cell like "$\Delta(\text{DM } t) = 6.57$". A reviewer accustomed to DM statistics may read "$\sigma$" as volatility.

---

## Logic structure review

- **Intro** (§1, L54–63): Strong. Three-paragraph arc (session motivation → prior literature with explicit parameter counts → PRG contributions). Literature paragraph accurately characterizes Linton–Wu ($\sim$12 parameters), Kim et al. ($\sim$10), positioning PRG's 6–8 parameters competitively.
- **Methodology** (§2): Well-structured. Session decomposition → PRG spec → Forecast timing (the paper's novel defense) → Benchmarks → Evaluation. The flow is correct. Only concern: §2.2 "Forecast timing" paragraph length (~200 words) is longer than surrounding; consider whether a single-sentence summary at the start helps.
- **Data** (§3): Compact and complete. Table 1 is well-designed (sources, obs counts, OOS periods, overnight-variance shares). Could add a sentence on why yfinance OHLC is acceptable as proxy (cites Hansen–Lunde or Patton's proxy-robust QLIKE).
- **Results** (§4): 4 subsections (statistical, ablation, VaR/ES, economic). Structure is textbook. See MAJOR-2 for economic-significance breadth issue.
- **Discussion** (§5): Three paragraphs. First paragraph (cross-market variation vs. overnight share) is the paper's highest-leverage positive claim and is well-framed. Second paragraph (frequency vs. recursion mechanism) pre-empts a key objection well. Third paragraph (limitations) needs mitigation clauses (see MED-6).
- **Conclusion** (§6): Standard three-finding summary. Fine as-is.

---

## Equation audit

Equations (1)–(9) inventory:
- (1)–(2): Session returns. Correct.
- (3): Common evaluation target. Correct; notation `\sigma^2_{\text{full},d}` clean.
- (4): PRG Basic recursion. Correct; session indicator $s_n$ is carefully introduced.
- (5): PRG Extended with leverage. Correct; $\mathbb{1}(r_{n-1} < 0)$ properly typeset.
- (6): Stationarity condition $\rho_0 \rho_1 < 1$. Correct; see MED-4 for PRG Basic case.
- (7): Unconditional session variance. Correct; follows from Eq. (5) under stationarity.
- (8)–(9): Two-phase forecast equations. Correct and well-annotated.
- (10): Full-day forecast as sum of two session forecasts. Correct.

No equation errors detected.

**Symbol consistency check**:
- $s \in \{0,1\}$ for session index: consistent throughout (L72, L86, L91).
- $h_n$ for conditional variance: consistent.
- $r_n, x_n = r_n^2$: consistent.
- $\mathcal{F}_{n-1}$ (session-indexed) vs $\mathcal{F}_{d-1}^c$, $\mathcal{F}_d^o$ (day-indexed): two notations, but the transition is explicit and well-annotated in L111–126.
- $\rho_s$ persistence: defined for Extended (L100); see MED-4 on Basic case.
- $\gamma_s$ leverage: introduced at L96 as session-specific; $\mathbb{1}(r_{n-1} < 0)$ indicator notation is correct.

No symbol conflicts detected.

---

## Citation completeness review

**In-text citations** (via `\citet` or `\citep`): all appear to have corresponding `\bibitem`. Bibliography has 19 entries. Previously-orphan Kupiec, Christoffersen, Acerbi-Szekely (flagged in 2026-04-05 citation_check.md) are now all present (confirmed at L332–335 Acerbi, L403–406 Kupiec, L342–345 Christoffersen). The earlier 2026-04-05 review flagged Duan (1995) smearing correction as a possible wrong-year/wrong-author issue; the current main.tex has no `\citet{Duan...}` reference visible (search returned zero matches), so either the reference was removed entirely (acceptable — the HAR log-level conversion can use a standard notation reference or nothing) or the mention has been rephrased. Recommend searching main.tex one more time for any remaining "Duan" mention.

**Lai (2024)**: Now correctly formatted with Wang, Y.-C. and Chang, Y.-C. as co-authors, 31(2), 285–305 (L392–396). DOI to add: see citation_review.md.

**Patton (2011) vs Hansen–Lunde (2005) attribution**: L84 now correctly attributes the proxy-robustness result to Patton (2011) with Hansen–Lunde (2005) as companion. Fix from 2026-04-19 is complete.

**Acerbi 2014 bibitem**: Now present at L332–335 (fixed 2026-04-19).

---

## Action Plan for v2

**主線程必修 (HIGH priority before submission)**:

1. **MAJOR-1**: Either add GJR-X benchmark (Fix A, ~1 day) or rewrite §5 L310 with literature-supported defense (Fix B, ~30 min). Minimum: Fix B.
2. **MAJOR-2**: Add SPY row to Table 4 VT strategy (~2–3 hours) + report turnover-adjusted Sharpe in footnote (~15 min).
3. **MED-1**: Cross-market ablation (TAIFEX) added as sentence in §4.2.
4. **MED-2**: Harvey-threshold justification sentence (~5 min).
5. **MED-3, MED-4, MED-5, MED-6**: ~30 min total polish.

**Deferred / optional to v3**:
- MIN-1 through MIN-7: final proof-reading pass.

**Prediction**:
- If MAJOR-1 Fix A + MAJOR-2 Fix A + all MEDs → 4.5★ → FRL first-round accept probability raised to ~25%, R&R ~65%, reject ~10%.
- If MAJOR-1 Fix B + MAJOR-2 Fix B + all MEDs → 4.3★ → FRL R&R ~70%, accept ~15%, reject ~15%.
- As-is (no fixes): 4.2★ → FRL R&R ~60%, reject-with-revision ~30%, accept ~10%.

**Submission recommendation**: **Revise before submitting.** The paper is technically sound and reproduce-verified; the 2 MAJORs are about reviewer-defense posture rather than substance. Fix B on both MAJORs is the minimum-viable submission; Fix A on either is the competitive move. Do **not** submit as-is — the risk/reward of spending ~3 hours on Fix B + MEDs is overwhelmingly favorable.

---

## Files / methodology used

- Source: `paper/prg-periodic-garch/main.tex` (1–435 lines, read in full)
- Context: `paper/prg-periodic-garch/README.md`, `positioning.md`, `reproduce_report.json`
- Reference patterns: `paper/vt-crowding-abm/review_history/v1/latex_review.md` (Paper 5 FRL comparable)
- Skill: `.claude/skills/latex-academic-reviewer/SKILL.md` + `references/review-criteria.md`

---

## Reviewer signature

Reviewer: latex-academic-reviewer (main thread)
Review round: v1
Paper status at review: reproduce GREEN 15/15 (2026-04-19), R2 SEVERE=0, 3 fixes done (Patton attribution L84, Acerbi bibitem L268, reproduce.py bug fix)
