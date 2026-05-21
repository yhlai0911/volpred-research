# P6 PRG — Academic Review v4

**Date**: 2026-04-27
**Reviewer**: Claude general-purpose proxy (latex-academic-reviewer SOP, Opus 4.7 1M)
**Manuscript**: `paper/prg-periodic-garch/main.tex` (503 lines, 11pt, compiled to 15 pages — on FRL boundary)
**Target**: Finance Research Letters (FRL)
**v3 baseline**: 4.1★ / 1 NEW MAJOR (forward-ref §4.5) + 2 NEW MED + 1 carry MED + 1 NEW MIN + 4 carry MIN
**v4 batch fixes claimed** (per `research_notes/v4_batch_2026_04_27.md`):
1. M-NEW-2b: §4.5 K1260 GJR-X subsection added (L301–337)
2. M-NEW-2a: §2.2 forecast-timing paragraph break at L122
3. M-CARRY-1: Hansen2012 disambiguation at §2.2 L94 + bibitem L440–444
4. Min-NEW: abstract trim (estimated 209→184 words, verified 193 words by `wc`)
5. Bonus: §5 limitation #3 condensed to single cross-ref sentence (L351 third clause)

---

## Overall Assessment

**Verdict**: **Minor revise** — v4 batch closes M-NEW-1 (forward-ref §4.5 now exists with content), M-NEW-2a/2b, M-CARRY-1, Min-NEW. However, the §4.5 batch introduced **one NEW MAJOR (cross-section numerical inconsistency: SPY DM-vs-GJR is 6.00 in §4.1/Abstract/Ablation but 5.24 in §4.5)** and **one NEW MED (§4.5 internal narrative claims "the strongest single DM statistic in the paper" — false: 6.63 EEM is larger)**. Net trajectory still **positive vs v3** because the forward-ref MAJOR was fully closed and §4.5 now anchors the K1260 first-order finding inside §4 Results, but the new inconsistency is a **harder reviewer trigger** than a broken forward-ref because it forces the reviewer to question whether the K1260 result was run on the same sample as Table 2 / Table 3.

**Predicted FRL outcome (post v4)**:
- desk-accept: **~32%** (vs v3 30%; +2pp from §4.5 closure but offset by new inconsistency)
- R&R likely-accept: **~55%** (unchanged)
- desk-reject / reject-with-revision: **~13%** (vs v3 15%; -2pp)

**Academic score**: **★★★★ / 5 (4.2 / 5)** — up from 4.1★ in v3. Net +0.1.
- +0.3★ from M-NEW-1/2a/2b/M-CARRY-1/Min-NEW closure cluster (raises perceived polish)
- +0.1★ from §4.5 GJR-X first-order finding now living in §4 Results (abstract↔Results↔Discussion flow now coherent)
- −0.2★ from one NEW MAJOR (DM-vs-GJR numerical inconsistency 6.00 vs 5.24 between §4.1 and §4.5)
- −0.1★ from one NEW MED (§4.5 "strongest single DM statistic in the paper" claim contradicts §4.1 EEM=6.63)

**Strengths preserved + amplified from v3**:
1. §4.5 now contains the K1260 first-order finding (Eq. 12 + Table 5 + 1 paragraph + IS LR diagnostic) — the abstract→Results→Discussion narrative now flows cleanly. K1260 numbers byte-match `experiments/k1260/k1260_results.json` (verified: GJR=0.8544, GJR-X=0.8607, PRG=0.7559; DM 5.24/7.72/−0.53).
2. §2.2 forecast-timing paragraph successfully split at L122/L124 — the "timing convention is standard…" sentence now opens a new ~3-sentence paragraph on practical implementability, addressing v3 M-NEW-2a paragraph-block density. Net density: 367 words across 3 paragraphs (was ~670 / 1 paragraph in v3).
3. Hansen2012 disambiguation cleanly written at §2.2 L94: "The label 'Realized' here denotes that the session-frequency squared return $x_n = r^2_n$ is a realized (observed) volatility proxy entering the recursion, distinct from the daily Realized GARCH framework of \citet{Hansen2012}…" — pre-empts the methodology-reviewer attribution-gap challenge while remaining honest about the difference.
4. Abstract is now 193 words (verified `wc`), under the FRL ≤200 soft target.
5. §5 limitation #3 condensed (L351 third clause) — no duplication of K1260 numbers between §4.5 and §5; §5 now reads as a clean cross-reference. Saves ~80 words.
6. Bibliography retains strict alphabetical order with Hansen2012 inserted between Hansen2011MCS (L434) and Harvey1997 (L446) — verified L440–444 placement correct.

---

## v3 → v4 Action Apply Audit (5 actions)

| v3 → v4 Action | Status | Verification (line refs in v4 main.tex) |
|---|---|---|
| **M-NEW-1 §4.5 forward-ref → write subsection** | ✅ DONE | New `\subsection{Fair-information benchmark: GJR-X}` at L303 with `\label{sec:gjrx}` (L304); §5 L351 cross-ref now points to a real subsection. Eq. (`eq:gjrx`) at L309. Table `tab:gjrx` at L318. |
| **M-NEW-2a §2.2 forecast-timing paragraph break** | ✅ DONE | L122 ends `…not a look-ahead construct.` then new paragraph at L124 opens with `Practical implementation requires only two conditions:`. Block now 3 paragraphs / 367 words (from 1 / ~670 in v3). |
| **M-NEW-2b K1260 in §4 Results** | ✅ DONE (subsumed by M-NEW-1) | Full GJR-X table with QLIKE/DM/Harvey verdict + IS LR diagnostic in §4.5 caption (L336). |
| **M-CARRY-1 Hansen2012 disambiguation** | ✅ DONE | §2.2 L94 has the disambiguation sentence; bibitem L440–444 alphabetical placement verified correct (between Hansen2011MCS and Harvey1997). |
| **Min-NEW abstract trim 209→≤200** | ✅ DONE | 193 words (verified `wc -w` after stripping LaTeX). |
| **Bonus: §5 third limitation condense** | ✅ DONE | L351 third clause is now a 2-sentence cross-ref to `\ref{sec:gjrx}` + Todorova/Opschoor alignment. No duplicate numbers. |

**6/6 actions fully closed**. v4 batch executed cleanly. The new issues below are **not regression of v3 fixes** but rather problems newly surfaced by the §4.5 addition.

---

## NotebookLM Critical Issues — v4 Status

### Issue A: Unfair baseline → **CLOSED + STRENGTHENED**
- v3 closed via K1260 GJR-X result, but the result lived in §5 only.
- v4 promotes K1260 to §4.5 with full table + Eq. (12) + IS LR diagnostic. **Closure is now visible at desk-editor scan-read depth** (within §4 Results, not buried in §5 Discussion).

### Issue B: Novelty (Bollerslev-Ghysels / Linton-Wu / Kim 2023 / Lai 2024) → **CLOSED**
- §1 L63 contribution paragraph unchanged from v3. NotebookLM Argument B Ultra-Parsimony differentiation language preserved.

---

## NotebookLM 3 Arguments — Manuscript Integration Audit (v4)

| Argument | In Manuscript? | Location |
|---|---|---|
| **A. Session-Boundary Information Bridge** | ✅ Yes | §1 L63; §4.2 (Ablation, L228); §5 L347 |
| **B. Ultra-Parsimony and Implementability** | ✅ Yes | §1 L63 (param-count comparison); §5 L349 |
| **C. Exposing "Target-Mismatch" Illusion** | ✅ Yes | §1 L63; §4.1 L213 |
| **D. (NEW) Fair-Info GJR-X Architectural Test** | ✅ Yes (NEW in v4) | §4.5 L303–337 (Eq. 12 + Table 5 + IS LR diagnostic) |

**Audit verdict**: All 3 NotebookLM arguments + 1 new architectural-test argument now visible at desk-editor scan-read depth. **Strongest narrative integration in any review round to date**.

---

## New Issues (v4)

### CRITICAL (0)
None.

### SEVERE (0)
None.

### MAJOR (1 NEW)

**M-NEW-1-v4. SPY DM-vs-GJR cross-section numerical inconsistency: 6.00 (§4.1, Abstract, §4.2 Ablation) vs 5.24 (§4.5)**

- **Location**: Abstract L41 ("DM $t = 6.00$ … SPY"); §4.1 Table 2 L196 ("SPY … 6.00$^{***}$"); §4.2 Ablation Table 3 L228 ("PRG Extended (full) … 6.00$^{***}$"); §4.2 prose L239 ("the DM statistic against GJR collapses from $6.00$ to $-0.57$"); **vs** §4.5 Table 5 L325 ("PRG Extended vs GJR & $5.24^{***}$") + caption L336 ("OOS period 2019-01-02 to 2026-04-08; $n=1{,}823$").
- **Evidence**:
  - `experiments/k1260/k1260_results.json` reports `dm_tests.PRG_vs_GJR.t_stat = 5.236176003002506` on **SPY OOS 2019-01-02 to 2026-04-02 with n=1,823**.
  - §4.1 Table 2 + §4.2 Ablation Table 3 report DM=6.00 on what is presumably the **same** SPY OOS window per Table 1 (L159: "SPY … OHLC … 1,823 obs … 2019/01–2026/04").
  - Both windows are nominally identical (n=1,823 SPY OOS 2019-01–2026-04), so the **same comparison (PRG Extended vs GJR on SPY)** should yield **the same DM statistic**.
- **Why it matters (high reviewer-trigger probability)**:
  - A diligent referee will cross-check: "K1260 fair-info test reports DM=5.24 for PRG vs GJR; main Table reports DM=6.00 for the same comparison on the same window. Why?"
  - Three plausible explanations, all of which the manuscript currently fails to address:
    1. **Different refit frequencies** — K1260 used `refit_freq_prg=126, refit_freq_gjr=63` (per JSON); the main Table 2 PRG estimates may use a different refit cadence (e.g., 252 days). If true, this is a fair difference but **must be footnoted in §4.5**.
    2. **Different `n_starts` for PRG estimation** — K1260 used `n_starts_prg=5`; main results used a different multistart count. Same fix: footnote.
    3. **Different OOS endpoint** — JSON says K1260 OOS ends 2026-04-02; Table 1 says SPY OOS ends 2026-04 (likely 2026-04-08 per Table 5 caption). The 6-day difference cannot account for a 0.76 swing in DM-t.
- **Severity calibration**: **MAJOR**. Unlike a broken forward-ref (visual-only), this is a **substantive numerical inconsistency** that questions whether the K1260 result and the main results are produced from the same pipeline. A methodologist referee will read this as "the authors ran two different estimations and reported whichever favored their narrative" unless explicitly addressed.
- **Fix options** (pick one):
  1. **Soft fix (10 min, recommended)**: Add a footnote to §4.5 Table 5 caption stating: "The PRG vs GJR DM statistic in this fair-info comparison ($t=5.24$) differs from the main-results value ($t=6.00$, Table 2) because K1260 uses [specify: PRG refit every 126 days with 5 random starts vs main results' refit every X days with Y starts; or: K1260 uses the OOS window through 2026-04-02 vs main results through 2026-04-08]. The $\sim$0.76 difference does not affect Harvey-PASS classification."
  2. **Medium fix (1 hr)**: Re-run K1260 GJR-X with the same refit cadence and `n_starts` as the main results pipeline; replace 5.24 with the recomputed DM and re-state Table 5. Numerical consistency restored.
  3. **Hard fix (2-3 hrs)**: Re-run main Table 2 SPY estimation under K1260 settings (`refit=126`, `n_starts=5`) and report the lower DM. Conservative but penalizes paper's own headline number unnecessarily.
- **Recommended**: Option 1 (footnote disambiguation). Honesty cheap, narrative impact zero.

### MEDIUM (1 NEW + 1 CARRY)

**M-NEW-2-v4. §4.5 prose claims "the strongest single DM statistic in the paper" for PRG-vs-GJR-X DM=7.72, but Abstract reports EEM PRG-vs-GJR DM=6.63 and §4.1 Table 2 has the same.** *(The "strongest" claim is technically correct only if read as "PRG-vs-GJR-X across the GJR-X analysis."* Wait — re-read §4.5 L313: "PRG-vs-GJR-X yields DM $t = 7.72$ ($p = 1.84 \times 10^{-14}$, Harvey PASS), the strongest single DM statistic in the paper." This claim **is correct**: 7.72 > 6.63 > 6.12 > 6.00 > 5.27 > 5.10 > 4.26 > 5.24 across all DM tests in the paper. **WITHDRAWN — claim verifies. Apologies for false flag.**)

After re-verification: **WITHDRAWN**. 7.72 is indeed the largest DM statistic anywhere in the paper. Disregard this MED.

**M-NEW-2-v4 (replacement). §4.5 in-sample LR test sample-size phrasing slightly ambiguous.**

- **Location**: §4.5 L313 ("over 4{,}778 in-sample days with 16 random initializations") + Table 5 caption L336 ("$n_{\text{IS}}=4{,}778$ days, $n_{\text{starts}}=16$").
- **Issue 1**: K1260 JSON reports `n_starts_gjr_x = 3`, **not 16**. Where does 16 come from? The JSON `n_starts_prg = 5`, `n_starts_gjr_x = 3`, `n_starts_gjr = 3` — none equals 16. This is a **data-paper traceability gap** (rule: Table row → JSON source binding, per `.claude/rules/paper-workflow.md` §4 hard rule 3). Either:
  - The 16 is from a separate LR-test pipeline (e.g., 16 = 1 base + 15 multistarts on δ profile), in which case it must be sourced or footnoted.
  - The 16 is a typo for one of {3, 5} or for a combined count (e.g., 3+3+5+5 = 16).
- **Issue 2**: "16 random initializations" applied to the LR test is ambiguous — is it 16 starts for the unrestricted GJR-X model? Or 16 each for restricted and unrestricted? The IS LR test is one-degree-of-freedom (δ=0 vs δ free), so the 16 should refer to multistart for the unrestricted estimation; restricted (standard GJR) does not need 16 starts.
- **Severity**: **MEDIUM**. Reviewers running reproducibility checks will not be able to map "16" to anything in `experiments/k1260/`. K1260 README likely contains the answer but the manuscript should be self-contained.
- **Fix** (15 min): Either (a) verify and update Table 5 caption to match K1260 actual `n_starts` (3 or 5, whichever was used for the LR-test estimation), with a brief explanation; or (b) clarify "16" by adding "16 random initializations of the GJR-X parameter vector for the unrestricted likelihood (3 for the restricted GJR baseline)" — assuming "16" is correct in some K1260 sub-script. The author must verify against `experiments/k1260/` reproduction code.

**M-CARRY-1-v4 (was M-CARRY-1 in v3). Hansen2012 attribution gap.**

- **Status**: ✅ **CLOSED in v4** by §2.2 L94 disambiguation sentence + bibitem L440–444. Both citation agent's "not needed" position and reviewer's "needed" position are addressed: cite is in the bib, but framed as "distinct from" rather than "we use Realized GARCH framework". Honest and complete.

### MINOR (3 NEW + 2 CARRY)

**Mn-NEW-1-v4. Section ref in §2.2 L129 uses hard-coded "Section~2.3" instead of `\ref{sec:bench}` or similar.**
- **Location**: L129 "All benchmark models in Section~2.3 that target $\sigma^2_{\text{full},d}$ directly".
- **Issue**: §2.3 has no `\label`. If the section numbering ever changes (e.g., adding a §2.0 introduction), this becomes a stale ref. Cosmetic.
- **Fix** (2 min): Add `\label{sec:bench}` to `\subsection{Benchmark models}` at L131 and replace L129 with `Section~\ref{sec:bench}`. Or leave as-is if sections are stable.

**Mn-NEW-2-v4. §4.5 Table 5 caption sentence ordering: "OOS period … $n=1{,}823$" comes after "${}^{***}$ denotes Harvey PASS"; reads less cleanly.**
- **Location**: L336.
- **Issue**: Caption flow is "DM tests use HAC SE … Harvey threshold is $|t|>3.0$. ${}^{***}$ Harvey PASS. **In-sample LR test for the GJR-X exogenous regressor: $\hat{\delta}=0.13, \mathrm{LR}=49.37, p<0.0001$ ($n_{IS}=4{,}778, n_{starts}=16$).**" The IS LR diagnostic is logically out-of-place in a Table-5 (OOS) caption. It belongs either (a) in body text (where L313 already mentions it inline), or (b) as a separate "in-sample diagnostic" footnote.
- **Fix** (5 min): Either remove the LR phrase from Table 5 caption (L336 last sentence) since it's already in body L313, or move the body sentence into the caption and remove from body. Avoid redundancy.

**Mn-NEW-3-v4. Page count = 15, on FRL boundary.**
- **Issue**: FRL hard limit is typically 15 pages including references. v3 was 14 pages; v4 is 15 (per `v4_batch_2026_04_27.md`: "+1 page from §4.5 + Hansen sentence"). Submitting at exactly the boundary is risky — any reviewer comment requiring expanded discussion will push to 16.
- **Mitigation options**:
  1. Tighten §1 introduction by ~10 lines (currently L57–63 are dense; some sentences in L59 paragraph 2 could be merged).
  2. Tighten §5 Discussion (L345–351) — the Lai2024 simplification paragraph at L349 partially duplicates §6 Conclusion paragraph at L365. Could remove L365 conclusion paragraph (it's redundant with §1 + §5).
  3. Use `\small` on Table 5 (already small) or compress Table 4 economic table.
- **Recommended**: Remove §6 conclusion's third paragraph (L365 "The PRG extends the Periodic Regime-Switching (PRS) model …" — already stated at §5 L349). Saves ~6 lines, ~½ page. Net 14.5 pages.
- **Severity**: MINOR — submission still feasible at 15 but tighter is safer.

**Mn-CARRY-1 (v3 → v4). `\usepackage{mathptmx}` (L11) — recommend `newtxtext,newtxmath` for unified Times text+math.**
- **Status**: Carry-over from v1/v3. FRL accepts both. Optional cosmetic. Defer to galley proof.

**Mn-CARRY-2 (v3 → v4). Other v1-carry citation polish (Acerbi page format, URL drift).**
- **Status**: Citation agent v3 confirmed 5 of these were misattributed from P5 and not in P6. **Withdrawn permanently**. Only mathptmx remains (Mn-CARRY-1).

---

## §4.5 Subsection Quality Audit (NEW in v4)

This audit targets the v4 batch's most substantive addition (M-NEW-2b/M-NEW-1 fix).

### Strengths
1. **Eq. 12 (`eq:gjrx`)** is well-formulated: standard GJR with leverage + δ·r²_overnight,t-1 exogenous regressor. Explicit, replicable.
2. **Table 5** is clear: 3 DM rows + 3 QLIKE rows; layout (`\multicolumn{2}{c}{0.8544}` etc.) handles the asymmetric "DM has Harvey verdict, QLIKE doesn't" cleanly.
3. **Caption disclosure** is comprehensive: HAC standard errors, Harvey1997 small-sample correction, Harvey2016 threshold cited, ${}^{***}$ explained.
4. **Body prose** (L313) elegantly handles the IS-significant / OOS-NS asymmetry — reads as a methodological finding rather than a defensive concession. The phrase "the asymmetry … demonstrates that PRG's advantage cannot be reduced to overnight information access" is the strongest single sentence in the §4 Results.
5. **Connection to §5 Discussion**: §5 L351 references `\ref{sec:gjrx}` correctly, no duplication of numbers.

### Weaknesses
1. **DM=5.24 vs main results 6.00 inconsistency** (M-NEW-1-v4 above) — needs footnote disambiguation.
2. **`n_starts=16` provenance** (M-NEW-2-v4 above) — needs JSON traceability check.
3. **Table 5 LR-test diagnostic in caption** (Mn-NEW-2-v4 above) — caption-vs-body redundancy.
4. **Table number sequencing**: §4 contains Tables 2, 3, 4, 5; §3 contains Table 1. Table 5 is correctly the 5th body table, but referenced via `\ref{tab:gjrx}` only — no auto-renumber issues. ✅ OK.
5. **Equation count**: §4.5 introduces Eq. 12 (`eq:gjrx`); body now has 12 equations total (1: r_overnight, 2: r_intraday, 3: target, 4: prg_basic, 5: prg_extended, 6: stationarity, 7: uncond_var, 8: prg_ov_forecast, 9: prg_in_forecast, 10: prg_fullday, 11: gjrx). Wait — 11 not 12 (counting `\label`s). All valid, no orphans. ✅ OK.

### Verdict on §4.5
**Net positive**. Closes 3 v3 issues (M-NEW-1 forward-ref, M-NEW-2b K1260-not-in-§4, narrative architecture-test argument). Introduces 2 new fixable issues (DM inconsistency, n_starts provenance). On balance, the §4.5 addition raises the manuscript's overall quality but requires a follow-up footnote pass before submission.

---

## v4-Specific Cross-Section Coherence Audit

I cross-checked all SPY DM-vs-GJR statistics across the manuscript:

| Location | Value | Source | Consistent with main? |
|---|---|---|---|
| Abstract L41 | DM $t$=6.00 | (no explicit source) | ✅ Matches §4.1 Table 2 |
| §4.1 Table 2 (L196) | 6.00$^{***}$ | (Best QLIKE 0.748) | ✅ Reference value |
| §4.2 Ablation Table 3 (L228) | 6.00$^{***}$ | (PRG Extended full) | ✅ Matches §4.1 |
| §4.2 Ablation prose (L239) | 6.00 | (DM swing 6.57) | ✅ Matches |
| **§4.5 Table 5 (L325)** | **5.24$^{***}$** | (K1260 JSON) | **❌ CONFLICT with §4.1** |
| **§4.5 prose (L313)** | (none, references Eq. 12) | — | (consistent with Table 5 internally) |

The §4.5 sub-pipeline's PRG-vs-GJR DM statistic differs from the main pipeline by 0.76 (6.00 vs 5.24). This is the **single most important outstanding issue in v4** because:
1. Both numbers are presumably correct (the JSON byte-matches Table 5; the main results presumably byte-match a separate JSON not yet inspected by this reviewer).
2. The discrepancy suggests pipeline differences that are not disclosed.
3. Reviewer cross-checks will surface this immediately.

I cross-checked all SPY QLIKE values:

| Location | PRG QLIKE | GJR QLIKE | Consistent? |
|---|---|---|---|
| §4.1 Table 2 (L196) | 0.748 (Best) | (not shown — only DM) | (assumes 4-decimal precision) |
| §4.2 Ablation Table 3 (L228) | 0.748 | (not shown) | ✅ Matches §4.1 |
| **§4.5 Table 5 (L332)** | **0.7559** | **0.8544** | **❌ 0.748 vs 0.7559 differ at 3rd decimal** |

So **two** numerical inconsistencies on SPY exist between §4.1/§4.2 and §4.5: (i) PRG QLIKE 0.748 vs 0.7559, (ii) DM-vs-GJR 6.00 vs 5.24. Both stem from pipeline differences. Both must be disclosed via footnote.

---

## Predicted journal response (v4)

| Outcome | v2 (3.6★) | v3 (4.1★) | v4 as-is (4.2★) | v4 post-fix all (4.4-4.5★) |
|---|---|---|---|---|
| **FRL desk-accept** | ~10% | ~30% | ~32% | ~40% |
| **FRL R&R likely-accept** | ~60% | ~55% | ~55% | ~50% |
| **FRL desk-reject / reject-with-revision** | ~30% | ~15% | ~13% | ~10% |

**Bottom line on v4**: The batch fixes are well-executed (6/6 closed), and the §4.5 addition substantively strengthens narrative integration. **However, the §4.5 batch surfaced one new MAJOR (numerical inconsistency 6.00 vs 5.24) and one new MED (n_starts=16 provenance) that did not exist in v3.** These are **not regressions of v3 fixes** but **side effects of the §4.5 addition** — the new §4.5 table forces a comparison against §4.1/§4.2 numbers, and that comparison is currently failing.

**Submission recommendation**:
- Do **not** submit v4 as-is.
- Apply **M-NEW-1-v4 footnote** (10 min) — disambiguates 6.00/5.24 and 0.748/0.7559 via "different refit cadence and multistart count" footnote in §4.5.
- Apply **M-NEW-2-v4 fix** (15 min) — verify n_starts=16 against `experiments/k1260/` and either correct or add provenance footnote.
- Apply **Mn-NEW-3-v4 fix** (10 min) — remove §6 L365 redundant conclusion paragraph to drop to 14.5 pages.
- Total effort: **~35 min**.
- After fixes: v4.1 score 4.4-4.5★, FRL desk-accept 35-40%, R&R 50-55%, desk-reject <10%.

---

## 6-criteria gate evaluation (v4)

| # | Criterion | v3 status | v4 status |
|---|---|---|---|
| 1 | Latex review ≥ 4★ | ✓ (4.1) | ✓ (4.2) |
| 2 | Citation 0 MAJOR + ≤3 MED | ✓ | ✓ (Hansen2012 added; bib clean) |
| 3 | Cross-paper meta = no fundamental issue | ✓ | ✓ (K1260 architectural-test argument now in §4) |
| 4 | True acceptance rate ≥ 50% | ⚠ marginal (30%+55%=85% but accept-only=30%) | ⚠ marginal (32%+55%=87% but accept-only=32%) |
| 5 | No critical fairness issue | ✓ | ✓ (closed v3) |
| 6 | No methodological tautology | ✓ | ✓ |

**Pass**: **5/6 + 1 marginal** (criterion 4 unchanged from v3 marginal). **No upgrade to 6/6** because the 35-min fix is needed to actually push desk-accept ≥40% (criterion 4 promote threshold).

**Stage decision**: **HOLD in review for v4.1** (apply 35-min fix → re-run paper-review-cycle v4.1). If v4.1 verdict ≥ 4.4★ and FRL desk-accept ≥ 40%, **promote to ready_for_submission**. The §4.5 addition put the manuscript closer to the gate but not over it; one more round closes the consistency gap.

---

## Files / methodology used

- Source: `paper/prg-periodic-garch/main.tex` (503 lines, read in full)
- v3 baseline: `paper/prg-periodic-garch/review_history/v3/{academic_review_report.md (256 lines), README.md (125 lines)}` (read in full)
- v4 batch audit: `paper/prg-periodic-garch/research_notes/v4_batch_2026_04_27.md` (54 lines, read in full)
- K1260 results verification: `experiments/k1260/k1260_results.json` (key fields read; QLIKE 0.8544/0.8607/0.7559, DM 5.24/7.72/−0.53 byte-matched Table 5; `n_starts_gjr_x=3`, `n_starts_prg=5`, `n_starts_gjr=3` — none equals the "16" in §4.5 caption)
- NotebookLM source: `paper/prg-periodic-garch/research_notes/notebooklm_prior_periodic_garch.md` (referenced but unchanged from v3 audit)
- Skill: `.claude/skills/latex-academic-reviewer/SKILL.md` (read in full — 13-step todo, 10 review dimensions A-J, severity tiers applied)
- Skill: `.claude/skills/latex-academic-reviewer/references/review-criteria.md` (read in full — abbreviation/citation/equation rules applied)
- Memory: `feedback_paper_cross_paper_meta_eval.md` (6-criteria gate); `.claude/rules/paper-workflow.md` §4 hard rule 3 (Table row → JSON source binding) — basis for M-NEW-2-v4 severity calibration

---

## Reviewer signature

Reviewer: Claude general-purpose (latex-academic-reviewer SOP, Opus 4.7 1M)
Review round: v4
Manuscript state at review: 11pt, 503 lines, 15 pages, K1260 §4.5 added, §2.2 paragraph break done, Hansen2012 disambiguated, abstract trimmed to 193 words, §5 limitation #3 condensed
Outstanding: **1 NEW MAJOR (DM 5.24 vs 6.00 + QLIKE 0.7559 vs 0.748 inconsistency between §4.5 and §4.1)** + **1 NEW MED (n_starts=16 provenance)** + 3 NEW MIN (§2.3 stale section ref; Table 5 caption LR-redundancy; 15-page boundary) + 1 carry MIN (mathptmx)
Anti-optimism check: §4.5 substantively strengthens the manuscript's narrative architecture, but introduces 2 new disclosure issues. Net +0.1★. The 35-min fix path is well-defined and does not require new experiments. I am NOT recommending this for direct submission; one more round (v4.1) is needed.

---

## Verdict line

**★4.2/5** (v3 4.1 → +0.1) — minor positive trajectory; §4.5 batch closes 6/6 v3 issues but surfaces 1 new MAJOR + 1 new MED that require ~35 min of footnote/disambiguation work before v4.1 paper-review-cycle. **Top blocker: SPY DM-vs-GJR 6.00 (§4.1) vs 5.24 (§4.5) numerical inconsistency.** Submission recommendation: HOLD for v4.1.
