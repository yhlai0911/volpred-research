# Review Round v1 — crypto-fear-channel (Paper 10)

**Date**: 2026-04-28
**Triggered by**: Full body draft completion (8434d9ad §8+§9; 5d651d0d reproduce expand 7→29 + main.tex canonical). First paper-review-cycle round on the 9-section main.tex.
**Manuscript**: `paper/crypto-fear-channel/main.tex` (v1 canonical, 15 pages, 0 errors / 0 undefined refs, reproduce GREEN 29/29 100%)
**Target journal**: Journal of International Financial Markets, Institutions & Money (1st), Journal of Empirical Finance (2nd), Finance Research Letters (backup short-form)
**Reviewers** (Claude general-purpose subagent proxies):
- `latex-academic-reviewer` proxy via `a50eea0a9b597c3a5`
- `citation-verifier` proxy via `a0d24cf34b4868243`

---

## Overall Assessment

| Reviewer | Verdict | Rating |
|----------|---------|--------|
| Academic | **1 CRITICAL** / **3 SEVERE** / 5 MAJOR / 9 MED / 7 MINOR | ★★★★ (3.95/5) |
| Citation | **1 MAJOR** / 5 MED / 7 MINOR | ⚠️ pending MAJOR-1 fix |

**Joint verdict**: **DO NOT promote to review stage** — v2 round needed (~2-3 main-thread slots). v1 is a strong first draft (3.95★ first-pass rating, no zero-tolerance fabrication issues, reproduce GREEN), but has 2 page-one-sanity-check level defects that any FRL/JIMFIM editor will catch immediately:

1. **CRITICAL-1 (academic)**: §3.3 line 94 prose inverts BTC vs SPY kurtosis — claims BTC "materially fatter-tailed" while citing SPY's higher 14.15 vs BTC's 7.58. Table 1 numbers are correct; the surrounding prose is wrong.
2. **MAJOR-1 (citation)**: `corbet2018` bibitem has wrong title. Vol 165:28-34 + DOI `10.1016/j.econlet.2018.01.004` corresponds to "Exploring the dynamic relationships between cryptocurrencies and other financial assets" (the actual Economics Letters 2018 paper); main.tex labeled it "Cryptocurrency reaction to FOMC announcements" which is a different Corbet et al. paper (J Fin Stab 46, 2020).

**Predicted outcome (post-v2 fix)**: JIMFIM R&R high probability; JEF R&R medium; FRL accept high (but loses §8.2 methodological reconciliation strength via shorter format).

---

## Issues Summary

### CRITICAL (1) — page-one sanity check failure

**CRIT-1. §3.3 line 94 BTC vs SPY kurtosis prose inversion**
- Source: academic v1
- Issue: Prose claims "BTC daily returns exhibit ... excess kurtosis 7.58 — materially fatter-tailed than SPY (14.15 excess kurtosis is concentrated in a handful of crisis days)" — but 14.15 > 7.58, so SPY is fatter-tailed (in this dataset, due to SPY's COVID concentration). The factual statement that "BTC fatter-tailed" is wrong as written.
- Fix: rewrite line 94 to honestly state SPY excess kurtosis (14.15) actually exceeds BTC (7.58) in this sample, attributable to SPY's COVID-2020 outliers; this preserves Table 1 integrity and removes the prose contradiction.
- Effort: 5 min main thread.

### MAJOR (1 academic + 1 citation = 2)

**MAJ-1 (citation). `corbet2018` wrong title**
- Bibitem currently: "Cryptocurrency reaction to FOMC announcements" — this is Corbet et al. (2020) J. Financial Stability 46
- Vol 165:28-34 + DOI 10.1016/j.econlet.2018.01.004 corresponds to "Exploring the dynamic relationships between cryptocurrencies and other financial assets"
- Fix: replace bibitem title to canonical Economics Letters 2018 paper title; verify DOI resolves.
- Effort: 2 min.

### SEVERE (3) — review-blocking

**SEV-1. Hatemi-J first-difference vs cumulative form inconsistency** (§3.2 line 90 vs §4.2 line 136)
- §3.2 describes $\Delta \text{RV}^{\text{btc}}_t$ first-difference decomposition; §4.2 says "cumulative positive and negative innovations". These are not equivalent operations.
- Verify against K1025 implementation; align both sections to the actual implementation.

**SEV-2. HAC kernel/bandwidth specification missing** (§4.1 / §4.2 / §4.5 all use bare "HAC standard errors")
- Top-tier referees (JIMFIM editors) require kernel choice (Bartlett / quadratic-spectral) and bandwidth selection rule (Newey-West automatic / fixed) explicitly stated.
- Fix: add 1-sentence specification (e.g., "Newey-West HAC with automatic bandwidth selection per Andrews 1991") in §4.1 first appearance, then reference subsequent uses.

**SEV-3. γ in Eq.~(\ref{eq:oos_aug}) never reported** (§7 OOS narrative gap)
- §7 reports only DM test; never reports γ in-sample t-stat or sign stability across rolling re-estimations.
- Without this, OOS NULL becomes mechanical (DM=−0.98 happens to fail) rather than informative (γ is small and non-monotonic across rolling windows, which would explain the OOS failure).
- Fix: add 1-paragraph γ in-sample summary in §7 (e.g., median γ across rolling estimations + sign-positive proportion).

### MAJOR (5) — substantive revisions

- **M1 (academic)**: Abstract/§4 "four building blocks" claim contradicts §4 five subsections — either rebrand to five blocks or merge §4.1 + §4.2 into "Granger family"
- **M2 (academic)**: Abstract 5 subperiod phrasing → "only 2020 / other four NS" explicit
- **M3 (academic)**: §6.1 spillover index "0.21%" unit ambiguity — clarify whether percentage points (of the 0–100% spillover scale) or relative to the 90.11% mean
- **M4 (academic)**: Line 287 wording fix
- **M5 (academic)**: §1 line 52 hard-codes "Section 3..." instead of `\ref{sec:data}` etc.

### MEDIUM (9 academic + 5 citation = 14)

**Academic MEDs (9)**: kurtosis interpretation refinement / quantile list ordering / DCC monotone wording / HAC bandwidth rule / harvey1997 cite footnote / RV symbol convention / Wald-vs-F formula choice / lag-1 interpretive box / 4 LaTeX overfull-hbox warnings.

**Citation MEDs (5)**:
- 3 bibitems missing `\url{}` DOI line (conrad2020 / diebold1995 / harvey2016)
- harvey2016 |t|>3 threshold transfer context footnote (cross-sectional asset pricing → single time-series predictor)
- iyer2022 IMF policy note label (already partially mitigated; optional)

### MINOR (7 academic + 7 citation = 14)

**Academic MINORs**: 7 cosmetic typos / LaTeX format / table column headers / cross-ref polish.

**Citation MINORs**:
- main.tex header says "19 bibitems" but actual count is 21 (MIN-1)
- harvey2016 sorted before harvey1997 in bibliography (year-within-author rule violation)
- §6.3 ETF cutoff 2024-01-11 footnote (SEC approve 1/10, trading begin 1/11)
- conrad2020 §2.3 framing partial overclaim (Conrad-Kleen had positive OOS for housing starts; soften the cautionary tale)
- 3 cosmetic / cross-paper consistency / moot

---

## v2 Fix Priority Plan

**Slot 1 (~50 min main thread; CRITICAL + SEVERE + citation MAJOR; ~7 issues)**:
1. **CRIT-1**: §3.3 line 94 kurtosis prose rewrite (5 min)
2. **MAJ-1 citation**: corbet2018 title fix (2 min)
3. **SEV-1**: Hatemi-J form alignment §3.2 ↔ §4.2 (10 min — read K1025 implementation)
4. **SEV-2**: HAC kernel/bandwidth specification §4.1 first appearance (5 min)
5. **SEV-3**: γ in-sample summary §7 (15 min — may need to extract from K1025 results or estimate)
6. **M5**: §1 hard-coded "Section 3..." → `\ref{sec:data}` etc. (5 min)
7. Compile + reproduce verify (8 min)

**Slot 2 (~50 min; MAJOR + half MED; ~10 issues)**:
- M1/M2/M3/M4 wording + abstract 5-subperiod precision
- 9 academic MEDs (~30 min batch)
- 3 citation MEDs (DOI URL补; ~5 min)

**Slot 3 (optional polish; MINOR + cosmetic ~14 issues)**:
- harvey1997/harvey2016 ordering
- conrad2020 framing soften
- ETF date footnote
- LaTeX overfull-hbox cleanup
- 21 vs 19 bibitem header sync

**Predicted post-v2 verdict**: 0 CRITICAL / 0 SEVERE / 0-1 MAJOR / 5-7 MED / 5-7 MINOR — academic ★★★★½ (4.5/5) — promote to **review stage**. Continue continuous-review-loop until 升 ready_for_submission.

---

## Stage Decision

**Stay at `draft` stage** (NOT promoted to review).

**Reason**: 1 CRITICAL + 1 citation MAJOR + 3 SEVERE = 5 review-blocking issues. Per `paper-stage-classifier` skill conventional gate (latex ≥ 4★ + citation 0 MAJOR + 0 SEVERE), v1 fails on 3 dimensions. Promote to review stage only after v2 closes CRIT-1 + MAJ-1 + SEV-1/2/3 (estimated 1 slot effort).

---

## Strengths Preserved (do not regress)

- **Honest joint reporting** (§8.2 Granger ≠ forecastability methodological lesson) — publication-worthy framing
- **3-dim decomposition** (asymmetry / tail / regime) well-integrated, not disconnected sections
- **§6 Robustness** maps to each §5 headline 1-to-1
- **§8.4 Limitations** 4 honest items (2020 single-window confound / daily frequency / single-asset BTC / future ETF accumulation)
- **Reproduce gate** 29/29 GREEN — replication strong
- **Stylistic fluency** — first-pass academic English appropriate for top-3 finance journal letter format

---

## Files in this round

- `academic_review_report.md` (latex-academic-reviewer proxy a50eea0a9b597c3a5)
- `citation_check_report.md` (citation-verifier proxy a0d24cf34b4868243)
- `README.md` (本檔)

## Next round trigger

After main thread v2 fix CRIT-1 + MAJ-1 + SEV-1/2/3 → 跑新一輪 review → 寫入 `review_history/v2/`. Estimated v2 round arrival: 1-2 slots.
