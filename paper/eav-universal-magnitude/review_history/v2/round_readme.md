# Review History v2 — Round README

**Paper**: `eav-universal-magnitude`
**Round**: v2
**Date**: 2026-07-06
**Triggered by**: `paper_review_eav_universal_magnitude_v2`
**Reviewers**:
- `latex-academic-reviewer` / `finance-paper-quality` pass by Codex
- `citation-verifier` pass by Codex with web-checked bibliographic metadata

## Overall Assessment

| Reviewer | Verdict | Rating |
|---|---|---|
| Academic / LaTeX | NOT SUBMISSION READY; 4 SEVERE + 4 HIGH | 2/5 |
| Citation | MAJOR CITATION REVISION REQUIRED | warning |

v2 fixes several v1 blockers, but the manuscript should remain in review. The main blocker has shifted from "missing references" to "synthesis integrity": the revised body mixes three-market, 12-market, 13-market, 172-stock, and 182-stock evidence without a stable provenance table or consistent wording.

## Files in This Round

- `latex_academic_review.md`
- `citation_check.md`
- `round_readme.md`

## What Improved Since v1

1. `references.bib` exists and BibTeX compiles.
2. Citation keys all resolve; no missing/orphan keys.
3. `garch_x_vix_paper`, `k1213_convergence_lesson`, and `engel_rangel2008` key problems are gone.
4. Table 2 dropout minimums are corrected.
5. `reproduce.py` rerun remains 20/20 GREEN.
6. Compliance scan is clean for AI/LLM/VolPred/K-id TeX-source violations.

## Blocking Issues for v3

### SEVERE

1. PDF prints two placeholders: summary statistics and Appendix A analytic-gradient verification.
2. K1470 multistart status contradicts Table 1 footnote.
3. Market/sample counts conflict: K1172 12-market/172 stocks, K1207 12-market/182 stocks, K1216c 13-market final Spearman, K1470 3-market multistart.
4. Internal workflow language appears in final prose (`FINAL`, `Paper 2 commits...`, operational mandates).

### HIGH

1. Contribution stack is too broad; reduce to 2-3 core contributions.
2. Reproduce gate does not cover the new §6.6 panel and figure claims.
3. K1470 and K1216c multistart estimators need separate labels.
4. Model notation ambiguity persists (`\tau_t` with firm-specific EAV; `m_i` fixed effects not in equation/parameter vector).

### Citation

1. `patell_wolfson1979` is wrong: should be Journal of Accounting and Economics 1(2), not Journal of Financial Economics 7(2).
2. DOI fields are missing throughout `references.bib`.
3. Add Bollerslev (1986) for GARCH.
4. Add Harvey, Leybourne, and Newbold (1997) if the OOS tests are DM-HLN.

## Recommended v3 Action Plan

**Main thread must fix before next review**:

1. Populate or remove the summary stats and Appendix A placeholders.
2. Add a panel-provenance table and normalize all "12/13-market" and stock-N wording.
3. Rewrite Table 1 footnote after K1470, distinguishing canonical and refined estimates.
4. Remove internal workflow/status language from reader-facing prose.
5. Patch `references.bib` per `citation_check.md`.
6. Extend reproduction coverage for K1172/K1207/K1216c/K1470.

**Deferred but needed before submission**:

- CJK/PingFang dependency cleanup.
- Table layout / overfull hbox cleanup.
- Bootstrap B=150 sensitivity or limitation statement.
- Full-author first-use citation style, depending on target journal.

## Next Round Trigger

Run v3 review after the main thread completes the six "must fix" items above and reruns:

```bash
cd paper/eav-universal-magnitude
uv run python reproduce.py
/Library/TeX/texbin/xelatex -interaction=nonstopmode body.tex
/Library/TeX/texbin/bibtex body
/Library/TeX/texbin/xelatex -interaction=nonstopmode body.tex
/Library/TeX/texbin/xelatex -interaction=nonstopmode body.tex
```

Current stage recommendation: **stay in review / major revision**, not ready for arXiv or journal submission.
