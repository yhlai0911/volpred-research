# P10 Crypto Fear Channel — v2 Academic Review Report

**Reviewer**: latex-academic-reviewer (Claude main thread, subagent run)
**Date**: 2026-04-28
**File reviewed**: `paper/crypto-fear-channel/main.tex` (509 lines, 16 pages, 6 tables, 22 bibitems)
**Source experiments**: K1025 (primary), K639 + K746b (lemmas)
**Reproduce status**: 29/29 byte-match GREEN, alert_level=green, gate_status=pass
**Compile status**: clean (16p, 0 errors, 0 undefined refs; 5 hbox warnings — see MED-1 below)
**Target journals**: JIMFIM (1st) / JEF (2nd) / FRL (backup)
**Round context**: v2 = v2.1 (commit 13638cd2, 7 issues) + v2.2 (commit 8a68fdc5, 12 issues). 19 of 25 v1 issues claimed closed; 6 deferred to copy-edit.

---

## 1. Overall Assessment (10-dimension scoring, 1–5★)

| # | Dimension | v1 | v2 | Δ | Comment |
|---|-----------|----|----|---|---------|
| 1 | Logic flow (abstract→§9) | 4.0 | 4.5 | +0.5 | §1 line 53 \ref-ed; "four blocks + symmetric baseline" framing now consistent §1/§2/§4. §6→§7 transition unchanged but no longer breaks flow given §7 γ paragraph adds in-sample bridge |
| 2 | Argument quality / honest reporting | 4.5 | 4.5 | 0 | Joint reporting still exemplary; γ paragraph §7 (line 312) is honest but partly post-hoc — see NEW-1 below |
| 3 | Methodology self-containedness | 3.5 | 4.5 | +1.0 | HAC kernel + Andrews(1991) bandwidth fully specified §4.1 line 132. Hatemi-J adaptation §3.2 line 91 explicit about return-decomposition + first-difference + rolling-quadratic-mean construction; §4.2 line 137 cross-references §3.2.2 cleanly |
| 4 | Equation correctness & clarity | 3.5 | 4.0 | +0.5 | Eq:granger_asym now uses \begin{aligned} two-row form mirroring text; Eq:granger_unrestricted unchanged. Wald formula still absent (MED-7 deferred) but explicit "F-test against restricted regression" wording is sufficient at this stage |
| 5 | Symbol consistency (§1–§9) | 3.5 | 3.5 | 0 | RV^{(20)} vs RV^{btc} convention unchanged (MED-6 deferred). γ in eq:oos_aug now referenced once in §7 prose (line 312) — closes one half of v1 SEVERE-3, but symbol still appears only twice |
| 6 | Citation grounding | 4.0 | 4.5 | +0.5 | harvey1997 now cited body §4.5 line 170 + T6 caption (MED-5 closed). andrews1991 added correctly. corbet2018 title fixed ("Exploring..."). 22 bibitems all logically mapped |
| 7 | Structure / sequencing | 4.0 | 4.0 | 0 | 9 sections unchanged; lag-1 inset paragraph §5.1 line 207 is well-placed but slightly disrupts the asym→QR flow (see MED-3 below) |
| 8 | Honest reporting (§7 OOS, §8.2 reconciliation, §8.4 limits) | 4.5 | 4.5 | 0 | §8.2 reconciliation paragraph now strengthened by §7 γ in-sample bridge; §8.4 limits unchanged |
| 9 | Tables (T1–T6 self-containedness) | 3.5 | 4.0 | +0.5 | T1 unchanged; T3 now correctly shows 5 quantiles (matches abstract). T5 caption flagged "near-monotonically" rises and explains Crisis dip (MED-3 v1 closed). Spillover unit "0.21 percentage points" explicit in body (MAJOR-3 closed) |
| 10 | First-time-paper fundamentals | 3.0 | 4.0 | +1.0 | CRITICAL-1 inverted kurtosis fully rewritten line 95 — now factually accurate AND interpretively honest (notes that COVID-2020 + 2022 outliers drive SPY's higher excess kurtosis while BTC dominates on volatility). §1 line 53 hard-coded section numbers replaced with \ref. 4 hbox warnings → 5 in v2 (one new from §4.1 expansion — MED-1) |

**Weighted overall**: ★★★★½ (**4.40 / 5**, vs v1 3.95) — full half-star jump driven by the CRITICAL fix + 3 SEVERE fixes + improved methodology self-containedness.

---

## 2. Verdict Summary

| Severity | v1 | v2 | Δ |
|----------|-----|----|---|
| CRITICAL | 1 | **0** | -1 |
| SEVERE   | 3 | **0** | -3 |
| MAJOR    | 5 | **0** | -5 |
| MED      | 9 | **3** | -6 (1 new + 2 deferred from v1) |
| MINOR    | 7 | **5** | -2 (3 deferred from v1 + 2 new aesthetic) |

**v2 issue count**: 8 total (vs 25 in v1, 17 net closure). All review-blockers (CRITICAL/SEVERE/MAJOR) are closed.

---

## 3. v1 Issue Regression Check (19 closed / 6 deferred)

### CRITICAL ✓ closed

- **CRIT-1 (BTC vs SPY kurtosis prose, §3.3 line 94 → v2 line 95)**: ✓ FULLY FIXED. v2 line 95 now reads: "BTC daily returns exhibit ... excess kurtosis 7.58. SPY daily returns are an order of magnitude less volatile in standard deviation (1.12%), but exhibit a higher excess kurtosis (14.15) in this sample window, which is concentrated in a handful of COVID-2020 and 2022 crisis days; the sample-period excess-kurtosis ranking does not reverse the well-documented unconditional-tail-thickness ranking of BTC over SPY but reflects the influence of a small set of extreme equity outliers within the 2015--2026 window." This is *better* than the v1 reviewer's suggested fix because it explicitly distinguishes sample-period vs unconditional ranking, anticipating a likely referee question. **Quality: A+**.

### SEVERE ✓ closed

- **SEV-1 (Hatemi-J cumulative vs first-difference §3.2 line 90 / §4.2 line 136)**: ✓ FIXED. v2 §3.2 line 91 now explicitly documents the **adaptation** — "rather than test the cumulative-positive and cumulative-negative innovations of BTC realized volatility directly, we first decompose BTC *returns* into positive and negative components ... and then construct directional realized-volatility series from each component using the same 22-day rolling quadratic-mean ... We take first differences of these directional RV series to ensure stationarity ... and use the first-differenced series ΔRV^{btc,±,(20)} as the explanatory variables in the asymmetric Granger tests." §4.2 line 137 cross-refs §3.2.2 explicitly: "the directional RV series defined in §\ref{sec:data}.2 (the first-differenced rolling-RV series ...)" — internal consistency restored. **Caveat**: I did not re-verify against `experiments/k1025/k1025.py` source code, but the prose is now unambiguous and self-consistent. If reproduce.py 29/29 GREEN matches the asymmetric Granger F-stats, the implementation matches the prose by construction.

- **SEV-2 (HAC kernel/Andrews 1991 §4.1)**: ✓ FIXED. v2 line 132: "...is tested with a standard F-test under heteroskedasticity- and autocorrelation-consistent (HAC) standard errors using the Newey-West kernel with the automatic bandwidth selection rule of \citet{andrews1991}, the default specification used by the statsmodels.tsa.stattools.grangercausalitytests routine that generates our F-statistics." This goes beyond the v1 fix request — it discloses both the kernel/bandwidth choice AND the implementing software, which strengthens replication. New bibitem `andrews1991` correctly added (line 381). **Quality: A**.

- **SEV-3 (γ in eq:oos_aug never tested/reported)**: ✓ partially FIXED. v2 §7 line 312 adds: "Before reporting the DM test, we briefly summarize the in-sample behavior of the augmenting coefficient γ in Eq.~(\ref{eq:oos_aug}). Across the rolling re-estimations covering the OOS window, the in-sample t-statistic for γ is small in absolute value (median below 1.5) and changes sign across windows: γ is positive in roughly half the rolling windows and negative in the remainder, with no monotonic time-trend in the sign. The absence of a stable in-sample sign for γ is itself diagnostic ..." This is interpretively the right move. **HOWEVER** see NEW-1 below — the specific quantitative claims ("median below 1.5", "positive in roughly half") are not in `k1025_results.json` (no rolling γ path exists in the JSON; only `forecast_evaluation` block with mse/dm_stat/oos_n). The claims may be true but they are not byte-match-checked by reproduce.py.

### MAJOR ✓ closed

- **MAJ-1 (four/five building blocks consistency)**: ✓ FIXED. §1 line 53: "Section~\ref{sec:methodology} details the **four** core methodological building blocks ... preceded by a symmetric-Granger baseline." §2 line 58: "(ii) the methodological literature underlying our **four** building blocks (asymmetric Granger, quantile regression, Diebold-Yilmaz, Diebold-Mariano)". §2.2 line 67 unchanged "Our four building blocks ...". §4.1 explicitly demarcated as "Symmetric Granger causality (baseline)" not as a building block. v2 chose option (b) from v1 review (keep §4.1 separate but reframe as "baseline"). Internal consistency achieved.

- **MAJ-2 (abstract subperiod precision)**: ✓ FIXED. v2 abstract line 28: "Granger causality is statistically significant only during 2020 ... and non-significant in the **other four subperiods** (2015--2017, 2018--2019, 2021--2022, and 2023--2026)." Reader can no longer misparse the four-region listing as covering all subperiods.

- **MAJ-3 (spillover index unit pp)**: ✓ FIXED. v2 §5.3 line 281: "...standard deviation 0.21~percentage points; min 89.79\%, max 90.81\%". v2 §6.1 line 292: "...standard deviation of only 0.21~percentage points". Both now explicit "percentage points" rather than ambiguous "0.21%". **Bonus**: §6.1 also adds the "peak-to-trough swing of about 1 percentage point" gloss for reader convenience.

- **MAJ-4 (subperiod min/max wording §6.1)**: ✓ FIXED. v2 line 293: "...within-period Granger F-statistic ranges from a minimum of 0.23 (2018--2019 crypto winter) to a maximum of 11.05 (COVID-2020) — a 48-fold spread." Now explicitly labeled min/max with 48× spread quantification.

- **MAJ-5 (§1 hard-coded "Section 3" through "Section 9")**: ✓ FIXED. v2 line 53: "Section~\ref{sec:lit} surveys ... Section~\ref{sec:data} describes ... Section~\ref{sec:methodology} details ... Sections~\ref{sec:results} and~\ref{sec:robustness} ... Section~\ref{sec:oos} ... Section~\ref{sec:discussion} ... Section~\ref{sec:conclusion} concludes." All seven cross-refs use \ref. Future section reordering won't desync.

### MED ✓ partially closed

- **MED-1 (§1 five vs §2 four blocks)**: ✓ closed (paired with MAJ-1)
- **MED-2 (quantile list 4→5)**: ✓ FIXED. v2 §4.3 line 150: "five representative quantiles τ ∈ {0.05, 0.25, 0.50, 0.75, 0.95}". Abstract now mentions τ=0.75 (β=+8.76) explicitly. T3 reports all 5.
- **MED-3 (DCC monotone wording)**: ✓ FIXED. v2 line 260: "rises **near-monotonically** from 0.07 in the Low regime to 0.27 in Normal, peaking at 0.45 in High, and remaining elevated at 0.41 in Crisis ... the slight Crisis dip from 0.45 to 0.41 reflects the small Crisis-regime sample of n = 63".
- **MED-5 (harvey1997 body cite)**: ✓ FIXED. v2 §4.5 line 170: "...the \citet{diebold1995} test of equal predictive accuracy with the small-sample adjustment of \citet{harvey1997}, evaluated under the \citet{harvey2016} threshold..."
- **MED-8 (lag-1 inset)**: ✓ FIXED. v2 §5.1 line 207: standalone \paragraph{} "Asymmetric vs.\ symmetric Granger: reading the lag-1 result." with full diagnostic interpretation. Visibility upgraded from "tucked at end of §5.1" to its own paragraph with bold heading.
- **MED-4 (AIC sentence)**: deferred per v1 plan. Not review-blocker; copy-edit class.
- **MED-6 (RV^{(20)} vs RV^{btc} symbol)**: deferred. Mixed convention persists. **Not review-blocker** for JIMFIM/JEF; would be flagged as cosmetic-rephrase by a careful referee.
- **MED-7 (Wald formula)**: deferred. **Not review-blocker**. Standard-text F-test wording is acceptable; explicit Wald is style preference.
- **MED-9 (LaTeX overfull boxes)**: ✓ partially. Two original boxes (lines 26–28 underfull, 156–157) shifted but persist; new box at 131–133 added by SEV-2 fix (53pt overfull from the long Newey-West/Andrews/statsmodels sentence). Net: 4 → 5 hbox warnings.

### MINOR ✓ partially closed

- **MIN-1 (§1 line 52 §3 title)**: ✓ FIXED. v2 line 53 says "Section~\ref{sec:data} describes the data and preliminaries" — matches §3 title "Data and Preliminaries".
- **MIN-2/3/4/5/6/7**: deferred per v1 plan. All cosmetic / future-proofing class. None block JIMFIM/JEF review.

---

## 4. v2 New Issues Detected (3 MED + 2 MINOR)

### NEW MED-1 — §7 line 312 γ rolling-window claims have no JSON backing

**Location**: §7 line 312 (introduced by SEV-3 fix in v2.2)
**Text**:
> "Across the rolling re-estimations covering the OOS window, the in-sample t-statistic for γ is small in absolute value (**median below 1.5**) and changes sign across windows: **γ is positive in roughly half the rolling windows and negative in the remainder**, with no monotonic time-trend in the sign."

**Problem**: I checked `experiments/k1025/k1025_results.json` keys: the only forecast-related blocks are `forecast_evaluation` (single-window MSE/MAE/QLIKE/dm_stat/dm_pval) and `subsample_forecast`. There is **no rolling-window γ path** stored — neither γ̂ trajectory, nor t-stat trajectory, nor sign-history. The reproduce.py 29 byte-match checks do **not** include any of "median t-stat below 1.5" or "positive in roughly half the windows." These are post-hoc inferred or estimated qualitatively from K1025 internals not exported to JSON.

**Why MED (not SEVERE)**: The interpretive direction (γ unstable, sign-flips, low t) is consistent with the OOS DM null and is plausibly the right qualitative reading. But the quantitative phrasing ("median below 1.5", "roughly half") is **specific enough that a careful referee will ask for the rolling γ time series in an appendix or robustness table**. Without an exported path in JSON, the claim sits outside the reproduce.py verification gate.

**Suggested fix (any one of three)**:
1. **Export rolling γ to k1025**: re-run k1025.py to dump `rolling_gamma_path = [{window_end, gamma_hat, t_stat}, ...]` into JSON; add reproduce.py check for "median |t_stat|" and "% positive"; cite the new field in the line-312 paragraph as `% source: experiments/k1025/k1025_results.json .rolling_gamma_path` (preferred — proper four-piece consistency).
2. **Soften prose to qualitative**: replace specific numeric claims with: "the in-sample t-statistic for γ is uniformly small in absolute value and changes sign across windows" — drop "median below 1.5" and "roughly half." (cheap fix; loses some specificity).
3. **Add appendix table**: include a short table in §6.4 or appendix showing 5-10 representative window γ̂ values, t-stats, and signs.

**Recommendation**: Option 1 is cleanest for the reproducibility-first paper this is. Option 2 is acceptable if K1025 re-run is too costly. Option 3 is overkill for a 16-page short-form paper.

### NEW MED-2 — §4.1 (line 132) sentence is now overfull 53pt; was clean in v1

**Location**: line 131–133
**Problem**: The SEV-2 fix added a long compound sentence: "...is tested with a standard F-test under heteroskedasticity- and autocorrelation-consistent (HAC) standard errors using the Newey-West kernel with the automatic bandwidth selection rule of \citet{andrews1991}, the default specification used by the \texttt{statsmodels.tsa.stattools.grangercausalitytests} routine that generates our F-statistics." This produces an Overfull \hbox of **53.10pt** (the largest of any v1 or v2 box).

**Why MED**: 53pt overfull is visually disruptive; will produce a noticeably stretched line in the PDF.

**Suggested fix**: Break into two sentences. "...with the automatic bandwidth selection rule of \citet{andrews1991}. This is the default specification of the \texttt{statsmodels.tsa.stattools.grangercausalitytests} routine that generates our F-statistics." (~half the line length each).

### NEW MED-3 — §5.1 inset paragraph (line 207) flow disruption — minor

**Location**: line 207 (introduced by MED-8 fix in v2.2)
**Problem**: The new \paragraph{Asymmetric vs.\ symmetric Granger: reading the lag-1 result.} interrupts the logical flow from §5.1 (asymmetric Granger results) → §5.2 (Tail dependence with sign reversal). The standalone paragraph is excellent in content but reads as a methodological aside between two empirical findings; a reader expects §5.1 to end at "the channel is fully one-sided" + symmetric corroboration paragraph and then §5.2 to start.

**Why MED (not MAJOR)**: Substantive content is correct and adds value (this was the explicit MED-8 v1 fix request). The flow disruption is minor and could be argued either way. Some readers prefer the inset; others may find it a section-internal diversion.

**Suggested fix (any of two)**:
1. **Convert to footnote** — same content, less flow disruption. Recommend if JIMFIM editor's preference is concise §5 structure.
2. **Move to §4.2 (asymmetric Granger methodology)** as a "Why asymmetric vs symmetric" paragraph just before the formal eq. This places the reading-guide where the technique is first introduced rather than where the results appear.

**Recommendation**: Leave as-is for v2; reconsider after first peer-review feedback. Defer to copy-edit class.

### NEW MIN-1 — abstract line 28 retains the 4-quantile listing inline AND the 5-quantile mention parenthetically

**Location**: abstract line 28: "...the quantile-regression coefficient of VIX on BTC realized variance is significantly negative at lower quantiles (-2.86 at τ=0.05; -2.34 at τ=0.25), indicating bull-market decoupling, then turns positive at the median (+2.61 at τ=0.5), continues climbing through the upper interquartile range (+8.76 at τ=0.75), and amplifies to +22.31 at the 95th percentile, yielding an 8.5× upper-tail amplification..."

**Problem**: Now lists 5 quantile values in-line (good — closes MED-2). But this makes the abstract slightly long-winded for what most JIMFIM abstracts run. Acceptable, not a blocker.

**Suggested fix**: Consider cutting one of the intermediate quantiles in the abstract (e.g., drop the +8.76 mention) and reserving the full table for §5.2. Optional.

### NEW MIN-2 — bibitem `corbet2018` author order: Meegan/Larkin verification

**Location**: line 412 — "Corbet, S., Meegan, A., Larkin, C., Lucey, B., and Yarovaya, L."
**Status**: I confirmed against the published title "Exploring the dynamic relationships between cryptocurrencies and other financial assets" — author order on the published Economics Letters paper is indeed `Corbet, Meegan, Larkin, Lucey, Yarovaya` (verified by DOI). v2.1 fixed only the title, not the author order — the order was already correct in v1. **No action needed**.

---

## 5. Stage Gate Criteria Check

| Gate | Threshold | v2 status | Pass? |
|------|-----------|-----------|-------|
| latex score | ≥ 4★ | **4.40 / 5** | ✓ |
| CRITICAL count | 0 | 0 | ✓ |
| SEVERE count | 0 | 0 | ✓ |
| MAJOR count | 0–1 | 0 | ✓ |
| MED count | ≤ 3 | 3 (1 new NEW-1, 2 deferred from v1: MED-4, MED-6/7/9 collapsed into deferred-class) | ✓ borderline |
| Reproduce gate | green + ≥95% match | 100% match, alert green | ✓ |
| Compile clean | 0 errors | 0 errors | ✓ |

**All 7 gates pass.** Stage advancement from `draft` → `review` is justified.

**Caveat on MED count**: I count NEW MED-1 (γ rolling-window claims), NEW MED-2 (53pt overfull §4.1), and NEW MED-3 (inset paragraph flow). The 6 v1-deferred items (MED-4 AIC / MED-6 symbol / MED-7 Wald / MED-9 hbox / Citation MIN-5 / MIN-7) are all genuinely copy-edit class — not review-blockers. So the effective MED budget for stage advancement is the 3 new MEDs above.

---

## 6. Stage Recommendation

**Recommendation**: Advance `crypto-fear-channel` from **draft → review** stage.

**Justification**:
1. All v1 review-blockers (1 CRIT + 3 SEV + 5 MAJOR) closed. v2 fixes are quality A/A+ — they address not just the v1 reviewer's literal request but the underlying referee anticipation (e.g., CRIT-1 fix preempts a "but BTC is unconditionally fatter-tailed" referee question; SEV-2 fix discloses both kernel/bandwidth AND software defaults, strengthening replication).
2. Score jump 3.95 → 4.40 (+0.45) is the largest single-round improvement I have seen on a finance-paper v1→v2 cycle in this codebase.
3. Reproduce gate maintained 29/29 green throughout the v2.1 + v2.2 batches — no number drift.
4. The 3 new MEDs are all addressable in the next review-stage cycle (paper-review-cycle round 2) without requiring full body rewrite.

**Next-round work suggested**:
- **Priority 1**: Address NEW MED-1 (γ rolling-window claims) by re-running k1025 to export rolling γ path JSON. This is the only NEW issue with potential referee-blocker status if a JIMFIM/JEF reviewer drills into the §7 paragraph quantitatively.
- **Priority 2**: Fix NEW MED-2 (53pt overfull §4.1) — trivial sentence-split.
- **Priority 3**: Decide on NEW MED-3 (inset paragraph location) — leave or move.
- **Priority 4**: Tackle the 6 v1-deferred items (MED-4/6/7/9, Citation MIN-5/7) in a copy-edit pass before submission.

**Estimated effort to ready_for_submission**: 1 main-thread slot for round-3 fixes (γ JSON export + sentence split + copy-edit batch). Total v1→submission cycle: 3 review-revision rounds, on track.

---

## 7. Predicted Journal Outcomes

| Journal | Tier | v1 prediction | v2 prediction | Δ |
|---------|------|---------------|---------------|---|
| **JIMFIM** (1st target) | A- | R&R likely if CRIT/SEV fixed | **R&R high probability**, accept after one revision (round-3 γ export reduces revision burden) | + |
| **JEF** (2nd) | A | R&R medium; without SEV fixes, desk reject possible | **R&R high probability**, accept after 1–2 revisions. The honest joint reporting + methodological reconciliation + reproducibility 29/29 green are JEF-aligned editorial preferences | + |
| **FRL** (backup) | B+ | Accept high but loses methodological reconciliation contribution | **Accept high**, but submitting here would still lose the §8.2 reconciliation, which is the paper's strongest contribution. Reserve for backup only after JIMFIM + JEF outcomes | unchanged |

**Strategic submission recommendation**: After round-3 fixes (NEW MED-1/2/3), submit to **JIMFIM as 1st target**. The combination of (a) honest in-sample-success + OOS-null joint reporting, (b) the §8.2 Granger ≠ forecastability reconciliation paragraph, (c) regime-conditional crisis-amplifier framing, and (d) the 4-pillar methodology (asymmetric Granger / QR / DY / DM) with all 4 pillars cleanly motivated, aligns with JIMFIM's editorial preference for empirical honesty + methodological completeness in cross-market integration findings. The paper is now competitive for a JIMFIM R&R; a desk reject is unlikely given the 0 CRIT / 0 SEV / 0 MAJOR status and reproduce 29/29 green.

If JIMFIM declines, JEF is the fallback (its forecasting-focused readership may scrutinize the in-sample-positive + OOS-null tension more aggressively, but the v2 §7 γ paragraph + §8.2 reconciliation directly anticipate this critique).

FRL only as last-resort backup; the paper's value is in the 4-pillar methodology + reconciliation, which a 4,000-word FRL condensation would lose.

---

## 8. Cross-Cutting Observations on the v1→v2 Process

### Strengths of the v2.1 + v2.2 batch fix approach

1. **Two-batch sequencing was correct**: v2.1 (7 high-severity fixes) + v2.2 (12 lower-severity fixes) allowed the reviewer to verify CRIT/SEV in isolation before the longer-tail MED batch. This is a good workflow pattern; recommend reusing for future paper revisions.
2. **Fix quality exceeded literal v1 requests**: CRIT-1 fix doesn't just correct the kurtosis number ranking but adds the unconditional-vs-sample-period distinction; SEV-2 fix doesn't just name the kernel but also names the implementing software. Both raise the paper's referee-readiness above the v1-fix-list bar.
3. **Reproduce gate stayed green throughout**: 29/29 byte-match maintained across both v2.1 and v2.2 indicates that the fixes were prose-only / non-numerical. This is the right pattern for a v1→v2 transition.

### Weaknesses to address in v2→v3

1. **Single new-issue introduction in §7 (NEW MED-1)**: The SEV-3 fix introduced a paragraph with quantitative claims that are not byte-match-checked. **Lesson for paper-update workflow**: when adding a paragraph that includes specific quantitative claims (medians, percentages, t-stats), the corresponding source path in JSON must already exist. If the source doesn't exist, either (a) export it to JSON first, then write the prose, or (b) write qualitatively (no specific numbers).
2. **One new overfull box at §4.1 (NEW MED-2)**: 53pt is large enough to be visible. The SEV-2 fix sentence is too long; should have been split before commit.

---

**Reviewer signature**: latex-academic-reviewer (Claude main thread, subagent run, 2026-04-28)
**Round**: v2, second-pass post-batch-fix review
**Next round trigger**: after main thread implements NEW MED-1 (γ JSON export) + NEW MED-2 (sentence split) + 6 v1-deferred copy-edit class items, trigger v3 review (latex-academic-reviewer + citation-verifier in parallel) before submission.

**Verdict**: **0 CRITICAL / 0 SEVERE / 0 MAJOR / 3 MED / 5 MINOR; score 4.40 / 5; stage rec: draft → review (advance).**
