# Review Round v10 — leverage-direction

**Date**: 2026-06-05 (initial); 2026-06-15 (DOI form refinement)
**Triggered by**: `Paper1_v10_citation_cleanup` follow-up from `decision_2026_06_05.md`
**Reviewer**:
- codex-cli (2026-06-05)
- hourly-13 agent (2026-06-15 refinement)

## Overall Assessment

| Reviewer | Verdict | Rating |
|----------|---------|--------|
| Citation | 0 MAJOR / 0 MEDIUM / 0 MINOR — PASS | ✅ |

## Changes in v10

1. **`engle1982` citation normalized (2026-06-05)**: replaced JSTOR DOI-form resolver `https://doi.org/10.2307/1912773` with explicit JSTOR stable URL `https://www.jstor.org/stable/1912773` in `main.tex`.
   **Refinement (2026-06-15)**: Further updated from JSTOR stable URL form back to canonical DOI resolver form `https://doi.org/10.2307/1912773` — this is consistent with all other citations in the bibliography which use `https://doi.org/` prefix. The JSTOR DOI `10.2307/1912773` is the canonical persistent identifier for this pre-digital Econometrica paper (source: IDEAS/RePec + Semantic Scholar cross-references). XeLaTeX compiled clean; 49 pages, 0 errors, 0 undefined references.
2. **`moreira2017` rechecked**: full journal title `Journal of Finance` is already consistent with the paper's bibliography style; no text change required.
3. **`cederburg2020` rechecked**: published page range `95--117` is already present; no text change required.
4. **`bayerdimitriadis2022` rechecked**: published Journal of Financial Econometrics citation is already used instead of a preprint; no text change required.

## Compilation Status

- XeLaTeX compiled clean after the citation normalization.
- No undefined reference warnings introduced by the v10 change.

## Files in this round

- `citation_check_report.md`
- `README.md` (本檔)

## Stage Assessment

- Citation tier upgraded from v9 `0 MAJOR / 1 MEDIUM / 3 MINOR` to **0 / 0 / 0**.
- Paper remains `ready_for_submission`; remaining work is page reduction and submission-package prep, not citation hygiene.
