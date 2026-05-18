# Review History v1 — Round README
**Paper**: eav-universal-magnitude
**Round**: v1 (first paper-review-cycle skill execution)
**Date**: 2026-05-18
**Triggered by**: User request — first formal review after body.tex §1–9 completion (commit 8b6586d9)
**Reviewers**: latex-academic-reviewer + citation-verifier (main thread, Claude Sonnet 4.6)
**Pre-conditions**: reproduce.py 20/20 GREEN, stage classified as DRAFT

---

## Overall Verdict

**NEEDS_REVISION**

The paper has a solid empirical foundation — all 20 reproduce.py checks pass, the three-market results are internally consistent, and the null-heterogeneity argument is well-constructed. However, there are 5 MAJOR+ issues that block submission in current form. The paper needs: (1) references.bib built and `[CITATION NEEDED]` §1.3 gap filled, (2) Table 2 dropout row numbers corrected, (3) Summary statistics table populated, (4) Appendix A written, (5) invalid citation keys replaced. None of these require re-running experiments.

---

## Severity Breakdown

| Severity | Count | Items |
|----------|-------|-------|
| CRITICAL | 0 | — |
| SEVERE | 1 | `[CITATION NEEDED]` international cross-market EAV anchor in §1.3 |
| MAJOR | 5 | Table 2 dropout mislabeling; Summary stats table incomplete; Appendix A placeholder; references.bib missing; `\citet{k1213_convergence_lesson}` invalid |
| MINOR | 11 | (see full reports) |
| **Total** | **17** | |

---

## v1 Issues from Previous Scaffold Review (2026-05-16) — Resolution Status

| v1 Issue | Priority | Status in body.tex |
|----------|----------|-------------------|
| Placebo 13.6σ → 13.27σ (plus σ definition) | P1 | **RESOLVED** — body §4.2 says "13.3 placebo standard errors" with explicit "(observed−placebo_mean)/placebo_SE" definition in §2.4; table shows 13.3σ, comment notes exact=13.27 |
| IS Hessian t vs OOS DM t semantic mixing | P0 | **RESOLVED** — §6.3 clearly separates IS t=10.4 from OOS DM t=−5.58/−5.25; explicit footnote "spec-consistency / OOS forecast superiority test, not an independent U.S. magnitude estimate" |
| converged=False not disclosed | P1 | **RESOLVED** — §2.3 footnote explains BFGS gradient tolerance issue vs outer-loop criterion; JP converged=True noted separately; Appendix A promised for analytic-gradient verification |
| "universal" over-claim → "cross-market regularity" | P0 | **RESOLVED** — title, abstract, intro all say "cross-market regularity"; "universal" not used in claims |
| JP data missing (K1150) | P0 | **RESOLVED** — JP fully integrated: §5, Table 1 (t=11.99, θ̂=1.41e-4), Table 2 robustness, §6.1 magnitude ordering, §9 conclusion |
| Null heterogeneity chain absent | P0 | **RESOLVED** — §6.2 "Reconciliation with Null Within-Market Heterogeneity" explicitly synthesizes K1109/K1113/K1114/K1140; conclusion §9 also summarizes |
| K1148_d2 misused as magnitude evidence | P1 | **RESOLVED** — §6.3 clearly labels K1148_d2 as "spec-consistency / OOS forecast superiority test, not an independent U.S. magnitude estimate (which is K1147)" |
| K1149 Scenario A only → A+D with TW asymmetry | P1 | **RESOLVED** — §6.4 presents full Scenario A+D: factor absorption symmetric (both pass), stress interaction asymmetric (US amplified, TW null with LRT p=0.010 disclosed) |
| K1148_d3 selection-bias unreported | P2 | **RESOLVED** — §7.3 explicitly states "K1148_d3 performs ex-post firm-characteristic heterogeneity tests conditional on the TW OOS pass from K1148_d1. Because TW OOS is marginal (p=0.076, NS), the selection is non-trivially biased." |
| Binary vs continuous "no value" over-statement | P2 | **RESOLVED** — §6.3 retracted: "The earlier framing that 'continuous adds no value' is retracted as overstated: both specifications robustly identify the earnings-announcement effect." |

**All 10 P0/P1 issues from v1 scaffold review are resolved in body.tex.**

---

## Top 3 New Unresolved Issues (This Round)

### 1. SEVERE: `[CITATION NEEDED]` in §1.3 — International Cross-Market EAV Anchor

**Location**: body.tex lines 196–199, §1 "Relation to the Literature" third paragraph

**Text**: "[CITATION NEEDED: international cross-market EAV anchor---see lit\_review.md A5; needs NotebookLM pass before submission]"

**Impact**: The third contribution strand ("cross-market regularities in volatility dynamics") is currently uncited. Without this anchor citation, the literature positioning is incomplete and reviewers will immediately flag it. This is the most important new finding of this review.

**Action required**: Run NotebookLM/literature pass to identify the specific cross-market EAV paper. Candidates from lit_review.md A5 (to be checked). Do not submit without resolving.

### 2. MAJOR: Table 2 Dropout Row Values Are Seed-42 Not Minimums

**Location**: body.tex Table 2 (robustness), "Min θ̂ (5 seeds)" and "Min Hess t (5 seeds)" rows

**Discrepancy found (byte-traceable from JSON)**:
- US "min θ̂": body=1.94×10⁻⁴, JSON actual min=1.82×10⁻⁴, seed-42=1.94×10⁻⁴
- US "min Hess t": body=20.67, JSON actual min=20.27, seed-42=20.67
- JP "min Hess t": body=18.24, JSON actual min=18.22, seed-42=18.24

**Note**: TW values are correct (happen to match). The substantive robustness conclusion is unaffected — all values are still highly significant. But the numerical claim "minimum across 5 seeds" must match the stated methodology.

**Action required**: Either (a) correct the US/JP values to the true minimums, or (b) relabel as "Sample estimate (seed=42)" and add a note that all 5 seeds yield qualitatively identical results. Option (a) is cleaner.

### 3. MAJOR: references.bib Missing + 4 Invalid/Unresolved Citation Keys

**Citations requiring resolution before compilation**:
1. `\citet{k1213_convergence_lesson}` — internal experiment ID, not academic citation; must be replaced
2. `\citep{garch_x_vix_paper}` — placeholder key with no corresponding inline comment or bib entry; must be resolved to a specific paper
3. Missing `diebold1995` (DM test methodology — used in K1148_d2 / K1149 but never cited in body)
4. `engel_rangel2008` typo — should be `engle_rangel2008`

**Additionally missing citations**: Benjamini & Hochberg (1995) for BH-FDR, Harvey-Leybourne-Newbold (1997) for HLN-corrected DM.

---

## Additional Notable Findings

- **Engle-Ghysels-Sohn (2013) journal**: Previously flagged as possibly JBES — confirmed as **Review of Economics and Statistics** (correct in inline comment)
- **Patell-Wolfson (1979) journal**: Confirmed **JFE** (not JFQA) — inline `[NOTE: verify]` comment should be removed
- **Summary statistics table (§3.4)**: All cells contain `---` dashes. Cannot submit without populating. The reproduce.py does not test this table, so it is not blocked by the green gate, but it is a visible incompleteness.
- **Appendix A**: Referenced in §2.3 footnote ("Appendix~\ref{app:gradient} provides an analytic-gradient verification"). Appendix exists as a label but contains only a placeholder. This cross-reference will compile with a `?` in the PDF.
- **CJK font packages** (PingFang TC): Will fail on Linux/Windows LaTeX distributions. Remove if CJK characters are not needed in English-language paper.

---

## Actions for Body.tex (Main Thread — Revision v2)

**Do immediately (SEVERE/MAJOR)**:
1. [ ] Build `references.bib` with all 9 existing keys + missing DM/HLN/BH citations
2. [ ] Replace `\citet{k1213_convergence_lesson}` with inline explanation or proper citation
3. [ ] Resolve `garch_x_vix_paper` placeholder key
4. [ ] Fix `engel_rangel2008` typo to `engle_rangel2008`
5. [ ] Run NotebookLM literature pass to fill `[CITATION NEEDED]` in §1.3
6. [ ] Correct Table 2 dropout "min" values for US and JP to actual minimums
7. [ ] Populate summary statistics table (§3.4) via reproduce.py or separate computation
8. [ ] Write Appendix A (analytic-gradient verification — pending P1 follow-up experiment)

**Do before submission (MINOR)**:
9. [ ] Remove "(First draft; not for citation)" from title page
10. [ ] Replace `[GitHub repo TBD]` with actual URL
11. [ ] Remove CJK font packages if not needed, or test compilation on non-macOS
12. [ ] Remove `[NOTE: verify JFE vs JFQA]` inline comment from patell_wolfson1979
13. [ ] Add TW OOS DM −2.48 near-threshold caveat in §6.4
14. [ ] Add JP earnings date source quality statement in §3.3
15. [ ] Add calendar clustering acknowledgment in §2.2

---

## Deferred to v2 Review

- Full literature cross-map after references.bib is built
- Citation-verifier pass on all bib entries (DOI/journal verification)
- Formal Harvey-Liu-Zhu multiplicity accounting across all specifications
- Factor absorption (K1149) Japan extension — not in current K1149 design; whether to run K1149-JP or note as limitation

---

## Reproduce Gate Status

- **reproduce_report.json**: 20/20 PASS (match_rate=1.00, alert_level=green)
- **Gate pre-condition for this review**: MET
- **Next review pre-condition**: reproduce.py must be updated to include summary statistics table cells before v2 review can be considered complete
